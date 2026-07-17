"""Typed recorder facade for the unified audit trail.

This is the seam business modules depend on. Each function owns the *shaping*
of one audited choke point — picking the category constant, deriving status /
actor / error, trimming payloads — that previously lived inline in the business
module as a private `_audit_*` helper. Business code now calls
`audit.record_xxx(...)` and never imports the writer, the global singleton, or a
bare category string.

Every recorder:
- takes an optional `sink: AuditSink` first parameter (default None →
  `default_sink()`, resolved lazily at call time so tests that monkeypatch the
  singleton's `record` are observed),
- is best-effort + fire-and-forget: it swallows every exception so audit
  instrumentation can never perturb the thing it audits.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.application.audit import categories as cat
from app.application.audit.writer import default_sink
from app.domain.ports import AuditSink
from app.json_safety import JsonObject, object_dict

logger = logging.getLogger(__name__)

_REDACTION_MARKER = "[REDACTED]"
_MCP_CONFIG_REDACTION_MARKER = "<mcp config redacted>"
_SENSITIVE_MCP_KEY_FRAGMENTS = frozenset(
    {"api_key", "authorization", "token", "password", "secret"}
)
_MCP_SECRET_CONTAINER_KEYS = frozenset({"env", "headers"})
_MCP_FAILURE_CODE_RE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_MCP_FAILURE_ISSUE_PATH_RE = re.compile(
    r"(?:\$|[A-Za-z_][A-Za-z0-9_-]*(?:\.(?:[A-Za-z_][A-Za-z0-9_-]*|[0-9]+))*)\Z"
)
_MCP_FAILURE_ISSUE_TYPE_RE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_MCP_FAILURE_ISSUE_LIMIT = 20
_MCP_FAILURE_ISSUE_PATH_MAX_LENGTH = 256
_MCP_EXTRA_FIELD_PATH = "__extra__"


@dataclass(frozen=True, slots=True)
class McpValidationIssueEvidence:
    path: str
    issue_type: str


@dataclass(frozen=True, slots=True)
class McpCallFailureEvidence:
    code: str
    issues: tuple[McpValidationIssueEvidence, ...] = ()


def _sink(sink: AuditSink | None) -> AuditSink:
    """Resolve the sink lazily: injected one, else the process-wide default.

    Resolving at call time (not import time) is what keeps the existing tests
    green — they `monkeypatch.setattr(audit_logger, "record", ...)` on the
    singleton instance that `default_sink()` returns.
    """
    return sink if sink is not None else default_sink()


def _audit_optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _safe_mcp_failure_payload(evidence: McpCallFailureEvidence) -> JsonObject:
    code = evidence.code if _MCP_FAILURE_CODE_RE.fullmatch(evidence.code) else "unknown_error"
    issues: list[JsonObject] = []
    for issue in evidence.issues:
        path = issue.path
        if issue.issue_type == "extra_forbidden" and not (
            path == _MCP_EXTRA_FIELD_PATH or path.endswith(f".{_MCP_EXTRA_FIELD_PATH}")
        ):
            path = _MCP_EXTRA_FIELD_PATH
        if len(path) > _MCP_FAILURE_ISSUE_PATH_MAX_LENGTH:
            continue
        if not _MCP_FAILURE_ISSUE_PATH_RE.fullmatch(path):
            continue
        if not _MCP_FAILURE_ISSUE_TYPE_RE.fullmatch(issue.issue_type):
            continue
        issues.append({"path": path, "type": issue.issue_type})
        if len(issues) == _MCP_FAILURE_ISSUE_LIMIT:
            break
    return {"code": code, "issues": issues}


def _redact_mcp_config_value(value: object, *, redact_all: bool = False) -> object:
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if redact_all or any(fragment in lowered for fragment in _SENSITIVE_MCP_KEY_FRAGMENTS):
                redacted[key_text] = _REDACTION_MARKER
            else:
                redacted[key_text] = _redact_mcp_config_value(
                    item,
                    redact_all=lowered in _MCP_SECRET_CONTAINER_KEYS,
                )
        return redacted
    if isinstance(value, list):
        if redact_all:
            return [_REDACTION_MARKER for _ in value]
        return [_redact_mcp_config_value(item) for item in value]
    return _REDACTION_MARKER if redact_all else value


def _redact_mcp_config(raw_config: str) -> str:
    try:
        parsed = json.loads(raw_config)
    except json.JSONDecodeError:
        return _MCP_CONFIG_REDACTION_MARKER
    if not isinstance(parsed, dict):
        return _MCP_CONFIG_REDACTION_MARKER
    return json.dumps(
        _redact_mcp_config_value(parsed),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _redact_cli_argv(cmd: list[str]) -> list[str]:
    argv = [str(arg) for arg in cmd]
    mcp_config_value_indexes: set[int] = set()
    for index, arg in enumerate(argv):
        if arg == "--mcp-config" and index + 1 < len(argv):
            mcp_config_value_indexes.add(index + 1)
            argv[index + 1] = _redact_mcp_config(argv[index + 1])
        elif arg.startswith("--mcp-config="):
            _, raw_config = arg.split("=", 1)
            argv[index] = f"--mcp-config={_redact_mcp_config(raw_config)}"

    # Claude may append a prompt as the final positional argument. Do not
    # mistake a trailing --mcp-config value for that prompt.
    if argv and not argv[-1].startswith("-") and len(argv) - 1 not in mcp_config_value_indexes:
        argv[-1] = "<prompt redacted>"
    return argv


# --- generic EventBus event ------------------------------------------------

# Event types NOT mirrored into the `event` category, to avoid a double-write
# storm. `conductor_turn` / `conductor_turn_delta` are already captured (richer,
# structured) by `record_conductor_turn`. The high-frequency, low-value
# real-time-only types (`log`, `message_delta`, `heartbeat`) are deliberately
# not persisted — `log` lines already land in `log_events` (the PRD says NOT to
# re-copy per-line stdout/stderr into audit_log), and delta/heartbeat are pure
# streaming signals the PRD leaves on the event channel only.
EVENT_SKIP_TYPES = frozenset(
    {
        "conductor_turn",
        "conductor_turn_delta",
        "log",
        "message_delta",
        "heartbeat",
    }
)
# Cap how much of a generic event payload we mirror into the audit row. The
# writer truncates to 8000 chars on serialize anyway; this keeps the common case
# small and avoids shipping big nested blobs through the queue.
_EVENT_PAYLOAD_LIMIT = 4000
_EVENT_INLINE_KEYS = frozenset(
    {
        "project_id",
        "issue_id",
        "task_id",
        "workspace_id",
        "session_id",
        "role",
        "task_kind",
        "status",
        "execution_process_id",
        "trace_id",
        "span_id",
        "parent_span_id",
        "setup_script",
        "run_command",
    }
)


def _event_inline_value(value: object) -> object:
    """Keep business event fields readable without turning audit rows huge."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= 2000 else value[:2000] + "…[trimmed]"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_event_inline_value(item) for item in list(value)[:20]]
    if isinstance(value, Mapping):
        return {str(key): _event_inline_value(nested) for key, nested in list(value.items())[:20]}
    text = str(value)
    return text if len(text) <= 1000 else text[:1000] + "…[trimmed]"


def _tail_text(value: object, limit: int = 2000) -> str:
    return str(value or "")[-limit:]


def record_event(
    envelope: Mapping[str, object],
    *,
    trace_id: str | None = None,
    span_id: str | None = None,
    parent_span_id: str | None = None,
    sink: AuditSink | None = None,
) -> None:
    """Mirror a generic EventBus event into the unified audit_log.

    Best-effort + non-blocking: any failure here is swallowed so audit
    instrumentation can never perturb event broadcasting (the thing it audits).
    Skips types already captured elsewhere or that are pure streaming noise (see
    EVENT_SKIP_TYPES). Only the event type plus a trimmed payload is recorded —
    the writer truncates again on serialize, so this stays cheap on the hot path.
    """
    try:
        event_type = str(envelope.get("type") or "unknown")
        if event_type in EVENT_SKIP_TYPES:
            return
        payload = object_dict(envelope.get("payload"))
        issue_id = payload.get("issue_id")
        task_id = payload.get("task_id")
        conductor_task_id = payload.get("conductor_task_id")
        execution_process_id = payload.get("execution_process_id")
        resolved_execution_process_id = _audit_optional_str(execution_process_id)
        resolved_trace_id = (
            trace_id
            or _audit_optional_str(payload.get("trace_id"))
            or resolved_execution_process_id
        )
        resolved_span_id = (
            span_id or _audit_optional_str(payload.get("span_id")) or _audit_optional_str(task_id)
        )
        resolved_parent_span_id = parent_span_id or _audit_optional_str(
            payload.get("parent_span_id")
        )
        # Trim before enqueue: keep the type + a bounded payload preview so a
        # large nested blob never travels through the queue in full.
        preview = str(payload)
        if len(preview) > _EVENT_PAYLOAD_LIMIT:
            preview = preview[:_EVENT_PAYLOAD_LIMIT] + "…[trimmed]"
        audit_payload: dict[str, object] = {
            "type": event_type,
            "event_id": envelope.get("event_id"),
            "ts": envelope.get("ts"),
            "payload_preview": preview,
        }
        for key in _EVENT_INLINE_KEYS:
            if key in payload:
                audit_payload[key] = _event_inline_value(payload.get(key))
        event_status = _audit_optional_str(payload.get("status"))
        if event_type == "project_script_updated" and event_status is None:
            event_status = "ok"
        correlation_id = (
            resolved_trace_id
            or resolved_execution_process_id
            or _audit_optional_str(payload.get("project_id"))
            or _audit_optional_str(payload.get("issue_id"))
            or _audit_optional_str(task_id)
        )
        _sink(sink).record(
            cat.CATEGORY_EVENT,
            actor=event_type,
            issue_id=str(issue_id) if issue_id else None,
            task_id=str(task_id) if task_id else None,
            conductor_task_id=str(conductor_task_id) if conductor_task_id else None,
            execution_process_id=resolved_execution_process_id,
            correlation_id=correlation_id,
            trace_id=resolved_trace_id,
            span_id=resolved_span_id,
            parent_span_id=resolved_parent_span_id,
            status=event_status,
            payload=audit_payload,
        )
    except Exception:  # noqa: BLE001, RUF100
        logger.exception("audit event mirror failed")


# --- git command -----------------------------------------------------------


def record_git_command(
    args: list[str],
    cwd: object,
    exit_code: int | None,
    stdout: str,
    stderr: str,
    started: float,
    *,
    error: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    parent_span_id: str | None = None,
    sink: AuditSink | None = None,
) -> None:
    """Record one git command into the unified audit_log.

    `git_service._run` is hot (every git op funnels through it), so the payload
    is kept small: full argv + cwd + exit_code + duration, but stdout/stderr are
    truncated to a short tail (git does not stream into log_events, and a
    calls-level audit only needs a summary, not full blobs). Best-effort +
    fire-and-forget: never blocks or raises into the git path.
    """
    try:
        duration_ms = int((time.monotonic() - started) * 1000)
        status = "error" if (error is not None or (exit_code or 0) != 0) else "ok"
        _sink(sink).record(
            cat.CATEGORY_GIT_COMMAND,
            actor="git",
            status=status,
            duration_ms=duration_ms,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            payload={
                "argv": ["git", *[str(a) for a in args]],
                "cwd": str(cwd) if cwd else None,
                "exit_code": exit_code,
                "stdout": (stdout or "")[-2000:],
                "stderr": (stderr or "")[-2000:],
            },
            error=error,
        )
    except Exception:  # noqa: BLE001, RUF100
        logger.debug("audit git command recording failed", exc_info=True)


# --- QA command executions -------------------------------------------------


def record_command_execs(
    execution_results: Sequence[Mapping[str, object]] | None,
    issue_id: str | None,
    task_id: str | None,
    *,
    trace_id: str | None = None,
    span_id: str | None = None,
    parent_span_id: str | None = None,
    sink: AuditSink | None = None,
) -> None:
    """Mirror each QA command execution into the command_exec category.

    Best-effort + fire-and-forget. None (execution disabled / mock) records
    nothing. stdout/stderr are already tail-trimmed by the executor; refused
    commands record their refusal reason in `status`/`error`.
    """
    if not execution_results:
        return
    try:
        resolved = _sink(sink)
        for r in execution_results:
            refused = r.get("refused")
            exit_code = r.get("exit_code")
            status = "error" if (refused or (exit_code or 0) != 0) else "ok"
            duration_s = r.get("duration_s")
            duration_ms = int(duration_s * 1000) if isinstance(duration_s, (int, float)) else None
            resolved.record(
                cat.CATEGORY_COMMAND_EXEC,
                actor="qa",
                issue_id=issue_id,
                task_id=task_id,
                status=status,
                duration_ms=duration_ms,
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                payload={
                    "command": r.get("command"),
                    "exit_code": exit_code,
                    "stdout": _tail_text(r.get("stdout")),
                    "stderr": _tail_text(r.get("stderr")),
                    "duration_s": duration_s,
                    "refused": refused,
                },
                error=str(refused) if refused else None,
            )
    except Exception:  # noqa: BLE001, RUF100
        logger.debug("audit command execution recording failed", exc_info=True)


# --- CLI subprocess spawn --------------------------------------------------


def record_cli_spawn(
    *,
    cmd: list[str],
    cwd: str | None,
    task_id: str | None,
    workspace_id: str | None,
    provider: str | None,
    model: str | None,
    resume_session_id: str | None,
    pid: int | None,
    execution_process_id: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    parent_span_id: str | None = None,
    sink: AuditSink | None = None,
) -> None:
    """Record a CLI subprocess launch into the cli_spawn category.

    Best-effort + fire-and-forget. Captures structural argv with the trailing
    prompt and MCP config credentials redacted. MCP server identity and endpoint
    remain visible. cwd/model/provider/resume id and pid round out HOW the agent
    process was launched.
    """
    try:
        argv = _redact_cli_argv(cmd)
        _sink(sink).record(
            cat.CATEGORY_CLI_SPAWN,
            actor="claude",
            task_id=task_id,
            execution_process_id=execution_process_id,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            payload={
                "argv": argv,
                "cwd": cwd,
                "workspace_id": workspace_id,
                "execution_process_id": execution_process_id,
                "executor": "claude",
                "provider": provider,
                "model": model,
                "resume_session_id": resume_session_id,
                "pid": pid,
            },
        )
    except Exception:  # noqa: BLE001, RUF100
        logger.debug("audit cli spawn recording failed", exc_info=True)


def record_mcp_call(
    *,
    server_id: str,
    tool_id: str,
    scope_id: str,
    task_id: str | None,
    started: float,
    is_error: bool,
    failure_evidence: McpCallFailureEvidence | None = None,
    sink: AuditSink | None = None,
) -> None:
    """Record one MCP outcome without retaining arguments, output, or credentials."""
    try:
        payload: JsonObject = {
            "transport": "mcp",
            "server_id": server_id,
            "tool_id": tool_id,
            "scope_id": scope_id,
        }
        if is_error and failure_evidence is not None:
            payload["failure"] = _safe_mcp_failure_payload(failure_evidence)
        _sink(sink).record(
            cat.CATEGORY_TOOL_RESULT,
            actor=f"mcp:{server_id}",
            task_id=task_id,
            correlation_id=scope_id,
            status="error" if is_error else "ok",
            duration_ms=int((time.monotonic() - started) * 1000),
            payload=payload,
            error="MCP tool returned an error" if is_error else None,
        )
    except Exception:  # noqa: BLE001, RUF100
        logger.exception("audit MCP call recording failed: server_id=%s", server_id)


# --- conductor turn --------------------------------------------------------

# A conductor turn `kind` maps 1:1 onto an audit category: `llm_request` is the
# call (prompt going out), `llm_response` is the return (content + usage), tool
# use/result mirror 1:1, and every finalize flavour (done/max_turns/max_wall/
# finalize_task) is an `agent_finalize`. A loop-crash `error` turn is also
# audited as an `agent_finalize` (it is a terminal outcome of the loop). Kinds
# not in this map are simply not audited.
CONDUCTOR_TURN_CATEGORY = {
    "llm_request": cat.CATEGORY_LLM_CALL,
    "llm_response": cat.CATEGORY_LLM_RETURN,
    "tool_use": cat.CATEGORY_TOOL_USE,
    "tool_result": cat.CATEGORY_TOOL_RESULT,
    "finalize": cat.CATEGORY_AGENT_FINALIZE,
    "error": cat.CATEGORY_AGENT_FINALIZE,
}


def record_conductor_turn(
    *,
    issue_id: str,
    conductor_task_id: str,
    kind: str,
    payload: JsonObject,
    trace_id: str | None = None,
    span_id: str | None = None,
    parent_span_id: str | None = None,
    sink: AuditSink | None = None,
) -> None:
    """Co-locate a unified audit row alongside the conductor_turns write.

    Best-effort fire-and-forget: import + record are wrapped so an audit failure
    can never perturb the conductor loop. The audit row reuses the conductor's
    own payload (the writer truncates on serialize), so there is no second
    computation and no divergence from conductor_turns. tool_result is marked
    error when the tool errored, mirroring the conductor_turns is_error flag.
    """
    category = CONDUCTOR_TURN_CATEGORY.get(kind)
    if category is None:
        return
    try:
        status = None
        if kind == "tool_result" and isinstance(payload, dict):
            status = "error" if payload.get("is_error") else "ok"
        elif kind == "error":
            status = "error"
        actor: str | None
        if kind in ("tool_use", "tool_result") and isinstance(payload, dict):
            actor = str(payload.get("name") or "") or None
        else:
            actor = "conductor"
        error = None
        if kind == "error" and isinstance(payload, dict):
            error = str(payload.get("message") or payload.get("error_class") or "") or None
        _sink(sink).record(
            category,
            actor=actor,
            issue_id=issue_id,
            conductor_task_id=conductor_task_id,
            status=status,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            payload=payload,
            error=error,
        )
    except Exception:  # noqa: BLE001, RUF100
        logger.debug("audit conductor turn recording failed", exc_info=True)


# --- auto-plan LLM call ----------------------------------------------------


def record_autoplan(
    category: str,
    *,
    executor_id: str | None,
    model: str | None,
    payload: JsonObject | None = None,
    status: str | None = None,
    started: float | None = None,
    error: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    parent_span_id: str | None = None,
    sink: AuditSink | None = None,
) -> None:
    """Record an auto-plan LLM call/return into the unified audit_log.

    Best-effort + fire-and-forget. The auto-plan path has no issue/task context
    (it runs for the workflow orchestrator before any issue task exists), so it
    audits actor + executor/model + a small payload only. Never raises into the
    runner, which already swallows its own errors and falls back to heuristics.
    """
    try:
        body: JsonObject = {"executor_id": executor_id, "model": model}
        if payload:
            body.update(payload)
        duration_ms = int((time.monotonic() - started) * 1000) if started is not None else None
        _sink(sink).record(
            category,
            actor="auto_plan",
            status=status,
            duration_ms=duration_ms,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            payload=body,
            error=error,
        )
    except Exception:  # noqa: BLE001, RUF100
        logger.debug("audit auto-plan call recording failed", exc_info=True)
