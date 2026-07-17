"""PR1 tests for the unified audit_log table + audit_logger write module.

Scope: table + async writer infrastructure only. No choke-point instrumentation
(PR2), no read API (PR3), no frontend (PR4).
"""

import asyncio
import json
from typing import cast

import pytest

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.application import audit
from app.application.audit_logger import (
    AUDIT_CATEGORIES,
    AuditLogger,
    _serialize_payload,
)
from app.domain.models import ConductorTurnKind


def _new_logger(store):
    logger = AuditLogger()
    logger.set_store(store)
    logger.set_loop(asyncio.get_event_loop())
    return logger


@pytest.fixture
async def audit_store(tmp_path):
    store = AsyncSQLiteStore(tmp_path / "console.db")
    await store._ensure_db()
    try:
        yield store
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_record_each_category_lands_in_db(audit_store):
    logger = _new_logger(audit_store)

    for category in sorted(AUDIT_CATEGORIES):
        logger.record(
            category,
            actor="tester",
            issue_id="issue-1",
            task_id="task-1",
            payload={"k": category},
            status="ok",
            duration_ms=12,
    )
    await logger.drain()

    rows = await audit_store.list_audit_logs(limit=100)
    assert len(rows) == len(AUDIT_CATEGORIES)
    categories = {r.category for r in rows}
    assert categories == set(AUDIT_CATEGORIES)
    sample = next(r for r in rows if r.category == "git_command")
    assert sample.actor == "tester"
    assert sample.issue_id == "issue-1"
    assert sample.status == "ok"
    assert sample.duration_ms == 12
    assert json.loads(sample.payload_json) == {"k": "git_command"}

    await logger.shutdown()


@pytest.mark.asyncio
async def test_payload_truncation(audit_store):
    logger = _new_logger(audit_store)

    big = {"blob": "x" * 20000}
    logger.record("llm_return", payload=big)
    await logger.drain()

    rows = await audit_store.list_audit_logs(limit=10)
    assert len(rows) == 1
    parsed = json.loads(rows[0].payload_json)
    assert parsed.get("__truncated__") is True
    assert parsed["original_length"] > 8000
    assert len(rows[0].payload_json) <= 8200  # envelope overhead is small

    await logger.shutdown()


def test_serialize_payload_below_limit_is_verbatim():
    payload = {"a": 1, "b": "short"}
    assert json.loads(_serialize_payload(payload)) == payload


def test_serialize_payload_none_is_empty_object():
    assert _serialize_payload(None) == "{}"


def test_serialize_payload_non_json_falls_back_to_repr():
    class Weird:
        def __repr__(self):
            return "<weird>"

    out = json.loads(_serialize_payload({"obj": Weird()}))
    # default=str handles it; either way it does not raise.
    assert "obj" in out


@pytest.mark.asyncio
async def test_write_failure_is_best_effort(tmp_path):
    class ExplodingStore:
        async def save_audit_log(self, entry):
            raise RuntimeError("boom")

    store = ExplodingStore()
    logger = AuditLogger()
    logger.set_store(store)
    logger.set_loop(asyncio.get_event_loop())

    # record must not raise even though the store explodes.
    logger.record("event", payload={"x": 1})
    await logger.drain()  # worker swallows the error
    # No exception propagated == pass.

    await logger.shutdown()


@pytest.mark.asyncio
async def test_enqueue_before_worker_starts_drains_later(audit_store):
    logger = AuditLogger()
    # Record BEFORE store/loop are set — should buffer in the queue.
    logger.record("event", payload={"early": True})

    logger.set_store(audit_store)
    logger.set_loop(asyncio.get_event_loop())
    await logger.drain()

    rows = await audit_store.list_audit_logs(limit=10)
    assert len(rows) == 1
    assert json.loads(rows[0].payload_json) == {"early": True}

    await logger.shutdown()


@pytest.mark.asyncio
async def test_table_idempotent_create(tmp_path):
    store = AsyncSQLiteStore(tmp_path / "console.db")
    try:
        # Repeated init must not raise (IF NOT EXISTS guards).
        await store._init_db()
        await store._init_db()
        await store._ensure_db()

        rows = await store.list_audit_logs(limit=10)
        assert rows == []
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_list_filters_by_category_and_issue(audit_store):
    logger = _new_logger(audit_store)

    logger.record("git_command", issue_id="i1", payload={"n": 1})
    logger.record("git_command", issue_id="i2", payload={"n": 2})
    logger.record("llm_call", issue_id="i1", payload={"n": 3})
    await logger.drain()

    git_rows = await audit_store.list_audit_logs(category="git_command")
    assert len(git_rows) == 2
    i1_rows = await audit_store.list_audit_logs(issue_id="i1")
    assert len(i1_rows) == 2
    git_i1 = await audit_store.list_audit_logs(category="git_command", issue_id="i1")
    assert len(git_i1) == 1

    await logger.shutdown()


@pytest.mark.asyncio
async def test_mcp_failure_evidence_is_bounded_redacted_and_durable(audit_store):
    logger = _new_logger(audit_store)
    sensitive_value = "capability-secret-987654321"
    issues = (
        *tuple(
            audit.McpValidationIssueEvidence(
                path=f"root/{sensitive_value}/{index}",
                issue_type="missing",
            )
            for index in range(25)
        ),
        audit.McpValidationIssueEvidence(
            path="root." + "x" * 300,
            issue_type="missing",
        ),
        audit.McpValidationIssueEvidence(
            path=sensitive_value,
            issue_type="extra_forbidden",
        ),
        audit.McpValidationIssueEvidence(path="$", issue_type="value_error"),
        audit.McpValidationIssueEvidence(
            path="contractVersion",
            issue_type="missing",
        ),
        *tuple(
            audit.McpValidationIssueEvidence(
                path=f"root.children.{index}",
                issue_type="string_type",
            )
            for index in range(25)
        ),
    )

    audit.record_mcp_call(
        server_id="structured-prototype-generation",
        tool_id="finalize_prototype_page",
        scope_id="item-1",
        task_id="task-1",
        started=0.0,
        is_error=True,
        failure_evidence=audit.McpCallFailureEvidence(
            code="schema_invalid",
            issues=issues,
        ),
        sink=logger,
    )
    await logger.drain()

    rows = await audit_store.list_audit_logs(limit=10)
    assert len(rows) == 1
    row = rows[0]
    payload = json.loads(row.payload_json)
    assert payload["failure"]["code"] == "schema_invalid"
    assert payload["failure"]["issues"][0] == {
        "path": "__extra__",
        "type": "extra_forbidden",
    }
    assert payload["failure"]["issues"][1] == {"path": "$", "type": "value_error"}
    assert payload["failure"]["issues"][2] == {
        "path": "contractVersion",
        "type": "missing",
    }
    assert payload["failure"]["issues"][-1] == {
        "path": "root.children.16",
        "type": "string_type",
    }
    assert len(payload["failure"]["issues"]) == 20
    assert row.error == "MCP tool returned an error"
    persisted = row.payload_json + (row.error or "")
    assert sensitive_value not in persisted
    assert "arguments" not in persisted
    assert "payloadJson" not in persisted

    await logger.shutdown()


@pytest.mark.asyncio
async def test_bounded_queue_drops_when_full_without_raising():
    """PR2 backpressure: a full bounded queue drops (drop-newest) + counts,
    never raises. The worker is intentionally not started so the queue fills."""
    logger = AuditLogger(max_queue=3)
    # No store/loop set -> no worker draining -> queue fills at maxsize=3.
    for i in range(10):
        logger.record("event", payload={"i": i})  # must never raise
    # 3 accepted, 7 dropped (drop-newest keeps the first 3).
    assert logger.dropped == 7
    assert logger._queue.qsize() == 3


@pytest.mark.asyncio
async def test_git_command_audit(tmp_path, monkeypatch):
    """git_service._run records a git_command audit row."""
    from app.application.git_service import GitService

    captured = []
    from app.application import audit_logger as audit_mod

    monkeypatch.setattr(
        audit_mod.audit_logger,
        "record",
        lambda category, **kw: captured.append((category, kw)),
    )

    git = GitService()
    repo = tmp_path / "repo"
    repo.mkdir()
    await git._run(["init"], cwd=repo)

    git_rows = [c for c in captured if c[0] == "git_command"]
    assert git_rows, "expected a git_command audit row"
    payload = git_rows[0][1]["payload"]
    assert payload["argv"][0] == "git"
    assert payload["argv"][1] == "init"
    assert payload["exit_code"] == 0
    assert git_rows[0][1]["status"] == "ok"


def test_cli_spawn_audit_redacts_prompt(monkeypatch):
    """claude_process_runtime._audit_cli_spawn records cli_spawn with the
    trailing prompt arg redacted."""
    from app.application.claude_process_runtime import ClaudeProcessRuntime  # noqa: I001
    from app.application import audit_logger as audit_mod

    captured = []
    monkeypatch.setattr(
        audit_mod.audit_logger,
        "record",
        lambda category, **kw: captured.append((category, kw)),
    )

    ClaudeProcessRuntime._audit_cli_spawn(
        cmd=["claude", "-p", "--model", "claude-x", "the secret prompt body"],
        cwd="/tmp/ws",
        task_id="task-1",
        workspace_id="ws-1",
        provider="anthropic",
        model="claude-x",
        resume_session_id="resume-1",
        pid=4242,
    )
    assert captured and captured[0][0] == "cli_spawn"
    payload = captured[0][1]["payload"]
    assert payload["argv"][-1] == "<prompt redacted>"
    assert "the secret prompt body" not in payload["argv"]
    assert payload["model"] == "claude-x"
    assert payload["pid"] == 4242
    assert captured[0][1]["task_id"] == "task-1"


def test_cli_spawn_audit_redacts_generated_prototype_mcp_tokens(monkeypatch):
    from app.application import audit_logger as audit_mod
    from app.application.claude_process_runtime import ClaudeProcessRuntime
    from app.application.structured_prototype_ai_mcp import PrototypeAiMcpService
    from app.application.structured_prototype_generation_mcp import (
        StructuredPrototypeGenerationMcpService,
    )

    generation_service = StructuredPrototypeGenerationMcpService()
    generation_session = generation_service.open_session(
        project_id="project-1",
        job_id="job-1",
        run_id="run-1",
        item_id="item-1",
        task_id="generation-task-1",
        task_kind="generation_page",
        context_object_hash="sha256:" + "a" * 64,
    )
    ai_service = PrototypeAiMcpService()
    ai_session = ai_service.open_session(
        project_id="project-1",
        edit_run_id="edit-run-1",
        task_id="ai-task-1",
    )
    endpoint = "http://127.0.0.1:8000/api/internal/prototype-mcp"
    cases = (
        (
            "structured-prototype-generation",
            generation_session.token,
            generation_session.claude_config(endpoint),
            "X-Prototype-Generation-Token",
        ),
        (
            "structured-prototype-ai",
            ai_session.token,
            ai_session.claude_config(endpoint),
            "X-Prototype-Ai-Token",
        ),
    )

    captured = []
    monkeypatch.setattr(
        audit_mod.audit_logger,
        "record",
        lambda category, **kw: captured.append((category, kw)),
    )

    for _, _, mcp_config, _ in cases:
        ClaudeProcessRuntime._audit_cli_spawn(
            cmd=[
                "claude",
                "-p",
                "--mcp-config",
                mcp_config,
                "--strict-mcp-config",
            ],
            cwd="/tmp/ws",
            task_id="task-1",
            workspace_id="ws-1",
            provider="anthropic",
            model="claude-x",
            resume_session_id=None,
            pid=4242,
        )

    assert len(captured) == len(cases)
    for captured_row, (server_id, token, _, header_name) in zip(captured, cases, strict=True):
        category, row = captured_row
        assert category == "cli_spawn"
        payload = row["payload"]
        assert token not in json.dumps(payload, ensure_ascii=False)
        argv = payload["argv"]
        assert argv[2] == "--mcp-config"
        assert argv[4] == "--strict-mcp-config"
        redacted_config = json.loads(argv[3])
        server = redacted_config["mcpServers"][server_id]
        assert server["type"] == "http"
        assert server["url"] == endpoint
        assert server["headers"] == {header_name: "[REDACTED]"}


def test_qa_command_exec_audit(monkeypatch):
    """QAWorkflow._audit_command_execs mirrors each command into command_exec."""
    from app.application.qa_workflow import QAWorkflow  # noqa: I001
    from app.application import audit_logger as audit_mod

    captured = []
    monkeypatch.setattr(
        audit_mod.audit_logger,
        "record",
        lambda category, **kw: captured.append((category, kw)),
    )

    QAWorkflow._audit_command_execs(
        [
            {"command": "pytest", "exit_code": 0, "stdout": "ok", "stderr": "", "duration_s": 1.5},
            {
                "command": "rm -rf /",
                "exit_code": -1,
                "stdout": "",
                "stderr": "x",
                "duration_s": 0.0,
                "refused": "danger",
            },
        ],
        "issue-1",
        "task-1",
    )
    rows = [c for c in captured if c[0] == "command_exec"]
    assert len(rows) == 2
    ok_row = next(r for r in rows if r[1]["payload"]["command"] == "pytest")
    assert ok_row[1]["status"] == "ok"
    assert ok_row[1]["duration_ms"] == 1500
    refused_row = next(r for r in rows if r[1]["payload"]["refused"] == "danger")
    assert refused_row[1]["status"] == "error"
    assert refused_row[1]["error"] == "danger"


def test_qa_command_exec_audit_none_records_nothing(monkeypatch):
    from app.application.qa_workflow import QAWorkflow  # noqa: I001
    from app.application import audit_logger as audit_mod

    captured = []
    monkeypatch.setattr(
        audit_mod.audit_logger,
        "record",
        lambda category, **kw: captured.append((category, kw)),
    )
    QAWorkflow._audit_command_execs(None, "issue-1", "task-1")
    QAWorkflow._audit_command_execs([], "issue-1", "task-1")
    assert captured == []


def test_conductor_turn_audit_maps_kinds(monkeypatch):
    """_audit_conductor_turn maps conductor turn kinds to audit categories and
    skips unknown kinds."""
    from app.application import conductor_main_loop as cml  # noqa: I001
    from app.application import audit_logger as audit_mod

    captured = []
    monkeypatch.setattr(
        audit_mod.audit_logger,
        "record",
        lambda category, **kw: captured.append((category, kw)),
    )

    cases: dict[ConductorTurnKind, str] = {
        "llm_request": "llm_call",
        "llm_response": "llm_return",
        "tool_use": "tool_use",
        "tool_result": "tool_result",
        "finalize": "agent_finalize",
    }
    for kind in cases:
        cml._audit_conductor_turn(
            issue_id="issue-1",
            conductor_task_id="ct-1",
            kind=kind,
            payload={"name": "dispatch_subagent", "is_error": False},
        )
    # Unknown kind -> not audited.
    cml._audit_conductor_turn(
        issue_id="issue-1",
        conductor_task_id="ct-1",
        kind=cast(ConductorTurnKind, "state_log"),
        payload={},
    )

    got = {c[0] for c in captured}
    assert got == set(cases.values())

    # A loop-crash `error` turn is audited as agent_finalize with status=error
    # and the message surfaced into the audit `error` field (PR2 gap fix).
    captured.clear()
    cml._audit_conductor_turn(
        issue_id="issue-1",
        conductor_task_id="ct-1",
        kind="error",
        payload={"error_class": "RuntimeError", "message": "boom", "traceback": "..."},
    )
    assert len(captured) == 1
    assert captured[0][0] == "agent_finalize"
    assert captured[0][1]["status"] == "error"
    assert captured[0][1]["error"] == "boom"
    # tool_result is_error flips status.
    cml._audit_conductor_turn(
        issue_id="issue-1",
        conductor_task_id="ct-1",
        kind="tool_result",
        payload={"name": "x", "is_error": True},
    )
    err_row = captured[-1]
    assert err_row[0] == "tool_result"
    assert err_row[1]["status"] == "error"


@pytest.mark.asyncio
async def test_event_bus_mirrors_event_and_skips_conductor_turn(monkeypatch):
    """event_bus.append mirrors generic events into audit_log `event` but skips
    conductor_turn / per-line log / delta / heartbeat to avoid double-write."""
    from app.application.event_bus import EventBus  # noqa: I001
    from app.application import audit_logger as audit_mod

    captured = []
    monkeypatch.setattr(
        audit_mod.audit_logger,
        "record",
        lambda category, **kw: captured.append((category, kw)),
    )

    bus = EventBus()
    await bus.append({"type": "batch_started", "issue_id": "issue-1", "concurrency_cap": 2})
    await bus.append({"type": "conductor_turn", "issue_id": "issue-1"})
    await bus.append({"type": "log", "task_id": "task-1", "content": "line"})
    await bus.append({"type": "heartbeat", "execution_process_id": "ep-1"})

    event_rows = [c for c in captured if c[0] == "event"]
    actors = {r[1]["actor"] for r in event_rows}
    assert "batch_started" in actors
    assert "conductor_turn" not in actors
    assert "log" not in actors
    assert "heartbeat" not in actors
    batch_row = next(r for r in event_rows if r[1]["actor"] == "batch_started")
    assert batch_row[1]["issue_id"] == "issue-1"
    assert batch_row[1]["payload"]["type"] == "batch_started"


@pytest.mark.asyncio
async def test_autoplan_llm_audit(monkeypatch):
    """llm_runner._audit_autoplan records llm_call / llm_return."""
    from app.application import llm_runner  # noqa: I001
    from app.application import audit_logger as audit_mod

    captured = []
    monkeypatch.setattr(
        audit_mod.audit_logger,
        "record",
        lambda category, **kw: captured.append((category, kw)),
    )

    llm_runner._audit_autoplan(
        "llm_call", executor_id="ex-1", model="m-1", payload={"prompt_chars": 10}
    )
    import time as _t

    llm_runner._audit_autoplan(
        "llm_return",
        executor_id="ex-1",
        model="m-1",
        status="ok",
        started=_t.monotonic() - 0.01,
        payload={"http_status": 200},
    )
    cats = [c[0] for c in captured]
    assert cats == ["llm_call", "llm_return"]
    assert captured[0][1]["actor"] == "auto_plan"
    assert captured[1][1]["payload"]["model"] == "m-1"
    assert captured[1][1]["duration_ms"] is not None


def test_sync_store_save_and_list_audit_log(tmp_path):
    from app.adapters.sqlite_store import SQLiteStore
    from app.domain.models import AuditLog

    store = SQLiteStore(tmp_path / "console.db")
    store.save_audit_log(
        AuditLog(id="a1", category="git_command", issue_id="i1", payload_json='{"x":1}')
    )
    store.save_audit_log(AuditLog(id="a2", category="llm_call", issue_id="i2", payload_json="{}"))
    rows = store.list_audit_logs(category="git_command")
    assert len(rows) == 1
    assert rows[0].id == "a1"
    assert rows[0].issue_id == "i1"


def test_record_event_preserves_business_fields_for_agent_timeline():
    """Business events keep readable fields, not only a repr payload preview."""
    from app.application.audit import record_event
    from app.domain.ports import AuditSink

    captured: list[tuple[str, dict[str, object]]] = []

    class Sink:
        def record(self, category: str, **kwargs: object) -> None:
            captured.append((category, dict(kwargs)))

    record_event(
        {
            "type": "project_script_updated",
            "event_id": "evt-1",
            "ts": "2026-07-08T10:55:56",
            "payload": {
                "project_id": "project-1",
                "task_id": "task-1",
                "execution_process_id": "ep-1",
                "trace_id": "ep-1",
                "span_id": "task-1",
                "role": "operations_engineer",
                "task_kind": "project_script_suggestion",
                "setup_script": "npm install",
                "run_command": "npm run dev",
            },
        },
        sink=cast(AuditSink, Sink()),
    )

    assert captured and captured[0][0] == "event"
    row = captured[0][1]
    assert row["actor"] == "project_script_updated"
    assert row["task_id"] == "task-1"
    assert row["execution_process_id"] == "ep-1"
    assert row["trace_id"] == "ep-1"
    assert row["correlation_id"] == "ep-1"
    assert row["status"] == "ok"
    payload = row["payload"]
    assert isinstance(payload, dict)
    assert payload["type"] == "project_script_updated"
    assert payload["role"] == "operations_engineer"
    assert payload["task_kind"] == "project_script_suggestion"
    assert payload["setup_script"] == "npm install"
    assert payload["run_command"] == "npm run dev"
