"""Anthropic-style ProjectConductor tool-use loop.

This module is intentionally transport-agnostic: tests and API endpoints can
pass any LLM callable that returns Anthropic message-shaped dictionaries.
"""

from __future__ import annotations  # noqa: I001

import asyncio
import inspect
import json
import logging
import time
import traceback
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Awaitable, Callable, Protocol, Union, cast  # noqa: UP035
from uuid import uuid4

from app.application import timeouts
from app.application.budget_service import (
    BudgetStore,
    IssueBudgetStatus,
    budget_steering_event,
    collect_candidate_model_prices,
    compute_issue_budget_status,
    render_budget_summary,
)
from app.application.conductor_policy import render_issue_orchestration_policy_block
from app.application.conductor_tools import build_conductor_tools
from app.application.conductor_lease import get_conductor_lease_owner, get_conductor_lease_ttl_s
from app.application.conductor_pause_registry import ConductorPauseRegistry
from app.application.conductor_state_machine import (
    LEGAL_TRANSITIONS,
    TERMINAL_PHASES,
)
from app.application.conductor_policy import (
    ConductorPolicyDecision,
    decide_conductor_policy,
    render_conductor_policy_hint,
)
from app.application.github_pr_followup import EventBusLike
from app.application.phase_duration_estimator import (
    PhaseDurationEstimator,
    get_phase_duration_estimator,
)
from app.application.conductor_llm import call_conductor_llm, resolve_conductor_llm_context
from app.application.project_conductor import ProjectConductor, ProjectConductorStore
from app.application.project_memory_service import ProjectMemoryStore, record_project_memory
from app.application.runtime_catalog_service import RuntimeCatalogService, RuntimeCatalogStore
from app.application.self_improvement_service import (
    _ProposalStore as SelfImprovementProposalStore,
    record_issue_self_improvement,
)
from app.application.task_statuses import (
    TASK_FAILURE_STATUSES,
    TASK_SUCCESS_STATUSES,
    is_task_failure_status,
    normalize_task_status,
)
from app.application.task_dispatcher import TaskDispatcherFn
from app.domain.models import (
    CodexIssue,
    ConductorStateLog,
    ConductorTask,
    ConductorTurn,
    ConductorTurnKind,
    Project,
    WorkflowGraph,
)
from app.json_safety import JsonObject, object_dict


ToolCallable = Callable[[JsonObject], Union[Awaitable[object], object]]  # noqa: UP007
LLMCallable = Callable[
    [list[JsonObject], list[JsonObject]],
    Union[Awaitable[JsonObject], JsonObject],  # noqa: UP007
]
TurnRecorder = Callable[..., Union[Awaitable[None], None]]  # noqa: UP007
InboxDrainer = Callable[[], Union[Awaitable[list[str]], list[str]]]  # noqa: UP007
PauseGate = Callable[[], Union[Awaitable[None], None]]  # noqa: UP007
PausePredicate = Callable[[], Union[Awaitable[bool], bool]]  # noqa: UP007
InflightTaskSetter = Callable[[asyncio.Task[JsonObject] | None], Union[Awaitable[None], None]]  # noqa: UP007
TokenDeltaRecorder = Callable[..., Union[Awaitable[None], None]]  # noqa: UP007


class _ConductorTaskSaver(Protocol):
    def save_conductor_task(self, task: ConductorTask) -> Awaitable[None]: ...


class _IssueSaver(Protocol):
    def save_codex_issue(self, issue: CodexIssue) -> Awaitable[None]: ...


class _IssueLoader(Protocol):
    def load_codex_issue(self, issue_id: str) -> Awaitable[CodexIssue | None]: ...


class _LatestConductorTaskLoader(Protocol):
    def load_latest_conductor_task_for_issue(
        self, issue_id: str
    ) -> Awaitable[ConductorTask | None]: ...


class _WorkflowGraphLoader(Protocol):
    def load_workflow_graph_for_issue(self, issue_id: str) -> Awaitable[WorkflowGraph | None]: ...


class _WorkflowGraphSaver(Protocol):
    def save_workflow_graph(self, graph: WorkflowGraph) -> Awaitable[None]: ...


class _ProjectLoader(Protocol):
    def load_project(self, project_id: str) -> Awaitable[Project | None]: ...


def conductor_language_directive(output_language: str | None) -> str:
    """Build a system-prompt section forcing the conductor's user-facing output
    into the configured language.

    The conductor runs in a detached server-side loop and cannot read the UI's
    locale, so the chosen language is persisted on the runtime catalog and passed
    in here. ``"auto"`` (the default) returns an empty string, preserving the
    legacy behavior of matching the issue's own language.
    """
    lang = (output_language or "auto").strip().lower()
    if lang in ("", "auto"):
        return ""
    if lang.startswith("zh"):
        return (
            "\n## 输出语言\n"
            "你必须用**简体中文**输出所有面向用户的内容:推理叙述、状态说明、"
            "通过 request_user_clarification 向用户提问、以及 finalize_task 的总结。"
            "工具名、角色名(pm/architect/engineer/qa 等)和代码标识符保持原样。\n"
        )
    if lang.startswith("en"):
        return (
            "\n## Output language\n"
            "You MUST write all user-facing content — reasoning narration, status notes, "
            "questions asked via request_user_clarification, and the finalize_task summary — "
            "in **English**. Keep tool names, role names, and code identifiers as-is.\n"
        )
    return (
        "\n## Output language\n"
        f"You MUST write all user-facing content (reasoning, questions, finalize summary) "
        f"in the language identified by the locale code '{output_language}'. "
        "Keep tool names, role names, and code identifiers as-is.\n"
    )


def detect_text_language(*texts: str | None) -> str:
    """Best-effort language guess for the conductor's ``"auto"`` mode.

    Returns ``"zh"`` if any CJK ideograph appears in the given text, else
    ``"en"``. This makes ``output_language="auto"`` actually match the issue's
    own language (its documented intent) instead of leaving the model to default
    to English narration on a Chinese issue.
    """
    for text in texts:
        if not text:
            continue
        for ch in text:
            if "一" <= ch <= "鿿":
                return "zh"
    return "en"


def build_issue_conductor_prompt(
    *,
    issue: CodexIssue,
    project_context: str,
    budget_context: str,
    language_directive: str,
    conductor_policy_hint: str = "",
    recovery_context: str = "",
) -> str:
    """Build the issue-level Conductor operating prompt.

    Kept as a pure helper so changes to the Conductor's operating contract are
    testable without running the long-lived loop.

    Two policy layers feed the prompt: the static `orchestration_policy` block
    (serial vs parallel recommendation from the issue text) and the runtime
    `conductor_policy_hint` (per-loop decision from recent turns / graph /
    budget — empty string when unavailable).
    """
    orchestration_policy = render_issue_orchestration_policy_block(
        issue.title,
        issue.description,
    )
    return f"""You are the ProjectConductor orchestrating work on this issue.

## Issue
Title: {issue.title}
Description: {issue.description or "(no description provided)"}
{project_context}{budget_context}{recovery_context}{orchestration_policy}{conductor_policy_hint}

## Your Job
Complete the issue by choosing the smallest reliable multi-agent workflow. You own
the plan, delegation, recovery, verification path, and final user-facing summary.
Standard agents: pm, architect, engineer, qa.
You can also use specialist roles: security_reviewer, perf_reviewer, doc_writer, etc.

## Operating Contract
- Decision loop: inspect the issue and available context, decide whether the next
  step is clarify, design, implement, verify, recover, or finalize, then use exactly
  the tool shape that fits that step.
- Requirements first: start with `pm` when scope, acceptance criteria, or user
  intent is unclear. Skip `pm` only when requirements are already explicit.
- Design when needed: use `architect` for cross-layer changes, risky migrations,
  public contracts, or coordination plans. Skip it for tiny obvious fixes.
- Implementation is mandatory for code changes: run `engineer` with a focused prompt
  that names the concrete goal, relevant context, constraints, expected artifact or
  result, and verification expectation.
- Verification is mandatory before success: run `qa` after implementation or after
  merge-conflict reconciliation. Treat unverified work as incomplete.
- Delegation prompt quality bar: every subagent prompt should include goal, known
  context, boundaries, expected output, files or failure details when relevant, and
  whether the agent should edit, inspect only, or reconcile.
- Use `dispatch_batch` only for independent work where no agent needs another
  agent's output. Use serial `dispatch_subagent` when there is any dependency,
  shared-file risk, ordered design-to-implementation flow, or recovery path.
- Pass `prev_node_key` as the node_key of the agent you just dispatched when a
  serial dependency exists, so the workflow graph stays readable.
- If a subagent result has `clarification_question`, use
  `request_user_clarification` instead of guessing.
- Never treat `artifact_invalid` as success. Re-dispatch the same role with a
  corrective prompt that restates the expected schema and validation error.
- If QA fails, dispatch `engineer` again with the QA failure, failed command, and
  relevant artifacts in the prompt. Then verify again.
- If a dispatch returns `retries_exhausted`, do not dispatch that role again.
  Choose a different role, ask the user, or finalize with the exact blocker.
- If a dispatch returns `role_busy`, do not spam the same role. Do useful work with
  another role, narrow the workflow, or wait until a later decision.
- If `dispatch_batch` returns `merge_status=conflict`, dispatch one `engineer` to
  reconcile the conflicting files and diff, or ask the user if the conflict is a
  product decision. Do not re-run agents already merged before the conflict.
- Mind the `## COST / BUDGET` block: when healthy, use strong agents for hard work;
  near warning, narrow dispatches and prefer cheaper choices; over budget, wind
  down as soon as the work is deliverable.
- Users may inject `[USER INTERJECTION]` messages between turns. Treat them as
  authoritative steering for the next decision.
- Finish only when requirements are satisfied, implementation is verified, failure
  states are resolved or clearly blocked, and the user-facing summary is useful.
- You MUST call `finalize_task` to end the loop.
{language_directive}"""


_TURN_PAYLOAD_LIMIT = 32_768
_TRACEBACK_LIMIT = 8_000
# Number of consecutive heartbeat-pulse failures before we emit a structured
# `conductor_heartbeat_degraded` event (GAP A): the pulse keeps retrying, but a
# sustained failure means the lease is at risk of expiring, so make it visible.
HEARTBEAT_DEGRADED_ALERT_AFTER = 3
# LEGAL_TRANSITIONS and TERMINAL_PHASES now live in
# `app.application.conductor_state_machine` so the table and its predicates
# are testable in isolation. Re-exported via the import above for callers
# that still pull the names from this module (e.g. test_conductor_state_machine).


@dataclass
class ConductorLoopResult:
    status: str
    final_text: str
    messages: list[JsonObject]
    tool_events: list[JsonObject] = field(default_factory=list)
    turn_count: int = 0


_CONDUCTOR_SUCCESS_STATUSES = TASK_SUCCESS_STATUSES
_CONDUCTOR_FAILURE_STATUSES = TASK_FAILURE_STATUSES | {
    "blocked",
    "needs_user",
    "max_wall",
    "max_turns",
}


def _normalize_conductor_status(status: str | None) -> str:
    normalized = normalize_task_status(status)
    if normalized in _CONDUCTOR_SUCCESS_STATUSES:
        return "done"
    if normalized in _CONDUCTOR_FAILURE_STATUSES:
        return str(normalized)
    return "failed"


def _is_conductor_success_status(status: str | None) -> bool:
    return _normalize_conductor_status(status) == "done"


async def _run_heartbeat_pulse(
    heartbeat: Callable[[], Awaitable[None]],
    interval: float,
    *,
    on_degraded: Callable[[int, Exception], Awaitable[None]] | None = None,
    alert_after: int = HEARTBEAT_DEGRADED_ALERT_AFTER,
) -> None:
    """Background lease-renewal loop (GAP A).

    Renews the conductor lease every ``interval`` seconds so it never expires
    while the loop is blocked awaiting a slow subagent. Resilient by design: a
    transient ``heartbeat`` failure is logged and counted but NEVER kills the
    loop — if it did, the lease would silently expire and the recovery watchdog
    would relaunch a duplicate conductor, the exact bug this pulse prevents.
    After ``alert_after`` consecutive failures ``on_degraded`` is invoked once
    so the degradation is observable instead of silent.
    """
    log = logging.getLogger(__name__)
    consecutive_failures = 0
    while True:
        await asyncio.sleep(interval)
        try:
            await heartbeat()
            consecutive_failures = 0
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001, RUF100
            consecutive_failures += 1
            log.warning(
                "conductor heartbeat pulse failed (%d consecutive): %s",
                consecutive_failures,
                exc,
            )
            if consecutive_failures == alert_after and on_degraded is not None:
                try:
                    await on_degraded(consecutive_failures, exc)
                except Exception:  # noqa: BLE001, RUF100
                    log.debug("conductor heartbeat degradation callback failed", exc_info=True)


async def run_conductor_loop(
    *,
    prompt: str,
    llm: LLMCallable,
    tools: Mapping[str, ToolCallable],
    tool_definitions: list[JsonObject],
    max_turns: int = 8,
    max_wall_s: float | None = None,
    turn_recorder: TurnRecorder | None = None,
    inbox_drain: InboxDrainer | None = None,
    wait_if_paused: PauseGate | None = None,
    is_pause_requested: PausePredicate | None = None,
    on_inflight_llm_task: InflightTaskSetter | None = None,
    on_token_delta: TokenDeltaRecorder | None = None,
) -> ConductorLoopResult:
    """Run a conductor session until it reaches final text or a final tool.

    ``max_wall_s`` (0/None disables) is a whole-loop wall-clock ceiling: even
    within ``max_turns``, a single turn can block up to the subagent hard limit,
    so without this a pathological issue could run for tens of hours. When the
    ceiling is crossed the loop seals as ``status="max_wall"``.
    """
    messages: list[JsonObject] = [{"role": "user", "content": prompt}]
    tool_events: list[JsonObject] = []
    final_text = ""
    loop_started = time.monotonic()

    for turn_index in range(max_turns):
        if max_wall_s and (time.monotonic() - loop_started) >= max_wall_s:
            await _record_turn(
                turn_recorder,
                turn_index=turn_index,
                sub_index=0,
                kind="finalize",
                payload={"status": "max_wall", "answer": final_text},
            )
            return ConductorLoopResult(
                status="max_wall",
                final_text=final_text,
                messages=messages,
                tool_events=tool_events,
                turn_count=turn_index,
            )
        if inbox_drain is not None:
            injected_messages = await _maybe_await(inbox_drain())
            for text in injected_messages:
                cleaned = str(text).strip()
                if cleaned:
                    messages.append({"role": "user", "content": f"[USER INTERJECTION] {cleaned}"})
        if wait_if_paused is not None:
            await _maybe_await(wait_if_paused())
        await _record_turn(
            turn_recorder,
            turn_index=turn_index,
            sub_index=0,
            kind="llm_request",
            payload={
                "message_count": len(messages),
                "messages_tail": deepcopy(messages[-4:]),
                "tool_names": [
                    str(tool.get("name") or "")
                    for tool in tool_definitions
                    if isinstance(tool, dict) and tool.get("name")
                ],
            },
        )
        llm_task = asyncio.create_task(
            _call_llm_with_optional_delta(
                llm,
                messages=deepcopy(messages),
                tool_definitions=tool_definitions,
                on_token_delta=on_token_delta,
            )
        )
        if on_inflight_llm_task is not None:
            await _maybe_await(on_inflight_llm_task(llm_task))
        try:
            response = await llm_task
        except asyncio.CancelledError:
            if on_inflight_llm_task is not None:
                await _maybe_await(on_inflight_llm_task(None))
            if is_pause_requested is not None and await _maybe_await(is_pause_requested()):
                if wait_if_paused is not None:
                    await _maybe_await(wait_if_paused())
                continue
            raise
        finally:
            if on_inflight_llm_task is not None and llm_task.done():
                await _maybe_await(on_inflight_llm_task(None))
        content = _normalise_content(response.get("content"))
        messages.append({"role": "assistant", "content": content})
        final_text = _text_from_content(content) or final_text
        await _record_turn(
            turn_recorder,
            turn_index=turn_index,
            sub_index=0,
            kind="llm_response",
            payload={
                "content": deepcopy(content),
                "stop_reason": response.get("stop_reason"),
                "usage": response.get("usage") if isinstance(response.get("usage"), dict) else {},
            },
        )

        tool_uses = [block for block in content if block.get("type") == "tool_use"]
        if not tool_uses:
            if turn_index < max_turns - 1:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Protocol error: you responded without a tool call. "
                            "You MUST call finalize_task to finish, or use another available tool "
                            "if the task is not ready to finish."
                        ),
                    }
                )
                continue
            protocol_text = (
                final_text
                or "Conductor stopped because the model did not call finalize_task."
            )
            await _record_turn(
                turn_recorder,
                turn_index=turn_index,
                sub_index=0,
                kind="finalize",
                payload={"status": "protocol_error", "answer": protocol_text},
            )
            return ConductorLoopResult(
                status="protocol_error",
                final_text=protocol_text,
                messages=messages,
                tool_events=tool_events,
                turn_count=turn_index + 1,
            )

        # Record every tool_use block first (cheap metadata), then execute them.
        # Multiple tool_use blocks in one turn run CONCURRENTLY: the Conductor can
        # fan out independent subagents (e.g. several reviewers) and we await them
        # together instead of serially. Results are still consumed in the LLM's
        # original block order, so tool_result ordering and first-finalize-wins
        # detection stay deterministic regardless of which finished first.
        for sub_index, tool_use in enumerate(tool_uses, start=1):
            await _record_turn(
                turn_recorder,
                turn_index=turn_index,
                sub_index=sub_index,
                kind="tool_use",
                payload={
                    "id": str(tool_use.get("id") or ""),
                    "name": str(tool_use.get("name") or ""),
                    "input": tool_use.get("input")
                    if isinstance(tool_use.get("input"), dict)
                    else {},
                },
            )
        finalize_mixed_with_work = len(tool_uses) > 1 and any(
            str(tool_use.get("name") or "") == "finalize_task" for tool_use in tool_uses
        )
        clarification_mixed_with_work = len(tool_uses) > 1 and any(
            str(tool_use.get("name") or "") == "request_user_clarification"
            for tool_use in tool_uses
        )
        events: list[JsonObject]
        if clarification_mixed_with_work:
            events = [
                _tool_protocol_error(
                    tool_use,
                    (
                        "request_user_clarification cannot be used in the same turn as other "
                        "tools; ask the user first, then wait for their answer before dispatching"
                    ),
                )
                for tool_use in tool_uses
            ]
        elif finalize_mixed_with_work:
            pending_events: list[JsonObject | None] = [None for _ in tool_uses]
            executable_uses: list[JsonObject] = []
            executable_indices: list[int] = []
            for idx, tool_use in enumerate(tool_uses):
                if str(tool_use.get("name") or "") == "finalize_task":
                    pending_events[idx] = _tool_protocol_error(
                        tool_use,
                        (
                            "finalize_task cannot be used in the same turn as other tools; "
                            "consume the other tool results first, then finalize in a later turn"
                        ),
                    )
                else:
                    executable_indices.append(idx)
                    executable_uses.append(tool_use)
            executable_events = await _execute_tool_uses(executable_uses, tools)
            for idx, event in zip(executable_indices, executable_events):  # noqa: B905
                pending_events[idx] = event
            events = [event for event in pending_events if event is not None]
        else:
            events = await _execute_tool_uses(tool_uses, tools)

        result_blocks: list[JsonObject] = []
        for sub_index, event in enumerate(events, start=1):
            tool_events.append(event)
            if event["name"] == "finalize_task" and finalize_mixed_with_work:
                event = {
                    **event,
                    "result": {
                        **(event["result"] if isinstance(event["result"], dict) else {}),
                        "status": "protocol_error",
                        "error": (
                            "finalize_task cannot be used in the same turn as other tools; "
                            "consume the other tool results first, then finalize in a later turn"
                        ),
                    },
                    "is_error": True,
                }
                tool_events[-1] = event
            result_blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": event["id"],
                    "content": json.dumps(event["result"], ensure_ascii=False, default=str),
                    "is_error": event["is_error"],
                }
            )
            await _record_turn(
                turn_recorder,
                turn_index=turn_index,
                sub_index=sub_index,
                kind="tool_result",
                payload={
                    "id": event["id"],
                    "name": event["name"],
                    "result": event["result"],
                    "is_error": event["is_error"],
                },
            )
            if event["name"] == "request_user_clarification" and not event["is_error"]:
                result = event["result"] if isinstance(event["result"], dict) else {}
                question = str(result.get("question") or result.get("answer") or final_text)
                final_answer = question or "Waiting for user clarification."
                await _record_turn(
                    turn_recorder,
                    turn_index=turn_index,
                    sub_index=sub_index,
                    kind="finalize",
                    payload={"status": "needs_user", "answer": final_answer},
                )
                return ConductorLoopResult(
                    status="needs_user",
                    final_text=final_answer,
                    messages=messages,
                    tool_events=tool_events,
                    turn_count=turn_index + 1,
                )
            if event["name"] == "finalize_task" and not event["is_error"]:
                result = event["result"] if isinstance(event["result"], dict) else {}
                final_status = _normalize_conductor_status(str(result.get("status") or "done"))
                final_answer = str(result.get("answer") or result.get("summary") or final_text)
                await _record_turn(
                    turn_recorder,
                    turn_index=turn_index,
                    sub_index=sub_index,
                    kind="finalize",
                    payload={"status": final_status, "answer": final_answer},
                )
                return ConductorLoopResult(
                    status=final_status,
                    final_text=final_answer,
                    messages=messages,
                    tool_events=tool_events,
                    turn_count=turn_index + 1,
                )
        messages.append({"role": "user", "content": result_blocks})

    await _record_turn(
        turn_recorder,
        turn_index=max_turns - 1,
        sub_index=0,
        kind="finalize",
        payload={"status": "max_turns", "answer": final_text},
    )
    return ConductorLoopResult(
        status="max_turns",
        final_text=final_text,
        messages=messages,
        tool_events=tool_events,
        turn_count=max_turns,
    )


async def _execute_tool_uses(
    tool_uses: list[JsonObject],
    tools: Mapping[str, ToolCallable],
) -> list[JsonObject]:
    """Execute one turn's tool_use blocks, concurrently when there are several.

    Each ``_execute_tool_use`` already converts its own failure into an error
    event, so ``gather`` never raises and results stay positionally aligned with
    ``tool_uses``. The single-block case stays a plain await (no task overhead).
    """
    if len(tool_uses) == 1:
        return [await _execute_tool_use(tool_uses[0], tools)]
    return list(await asyncio.gather(*(_execute_tool_use(tu, tools) for tu in tool_uses)))


def _tool_protocol_error(tool_use: JsonObject, error: str) -> JsonObject:
    tool_input = tool_use.get("input") if isinstance(tool_use.get("input"), dict) else {}
    return {
        "id": str(tool_use.get("id") or ""),
        "name": str(tool_use.get("name") or ""),
        "input": tool_input,
        "result": {"status": "protocol_error", "error": error},
        "is_error": True,
    }


async def _execute_tool_use(
    tool_use: JsonObject,
    tools: Mapping[str, ToolCallable],
) -> JsonObject:
    tool_id = str(tool_use.get("id") or "")
    name = str(tool_use.get("name") or "")
    tool_input_raw = tool_use.get("input")
    tool_input = object_dict(tool_input_raw)
    tool = tools.get(name)
    if tool is None:
        return {
            "id": tool_id,
            "name": name,
            "input": tool_input,
            "result": {"error": f"Unknown conductor tool: {name}"},
            "is_error": True,
        }
    try:
        result = await _maybe_await(tool(tool_input))
        return {
            "id": tool_id,
            "name": name,
            "input": tool_input,
            "result": result,
            "is_error": False,
        }
    except Exception as exc:  # noqa: BLE001, RUF100
        return {
            "id": tool_id,
            "name": name,
            "input": tool_input,
            "result": {"error": str(exc)},
            "is_error": True,
        }


def _normalise_content(content: object) -> list[JsonObject]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [object_dict(block) for block in content if isinstance(block, dict)]
    return []


def _text_from_content(content: list[JsonObject]) -> str:
    return "".join(str(block.get("text") or "") for block in content if block.get("type") == "text")


async def _maybe_await[T](value: Awaitable[T] | T) -> T:
    if inspect.isawaitable(value):
        return await cast(Awaitable[T], value)
    return value


async def _call_llm_with_optional_delta(
    llm: LLMCallable,
    *,
    messages: list[JsonObject],
    tool_definitions: list[JsonObject],
    on_token_delta: TokenDeltaRecorder | None,
) -> JsonObject:
    params = inspect.signature(llm).parameters
    if "on_token_delta" in params:
        llm_with_delta = cast(Callable[..., Awaitable[JsonObject] | JsonObject], llm)
        return await _maybe_await(
            llm_with_delta(messages, tool_definitions, on_token_delta=on_token_delta)
        )
    return await _maybe_await(llm(messages, tool_definitions))


async def _record_turn(
    turn_recorder: TurnRecorder | None,
    *,
    turn_index: int,
    sub_index: int,
    kind: ConductorTurnKind,
    payload: JsonObject,
) -> None:
    if turn_recorder is None:
        return
    await _maybe_await(
        turn_recorder(
            turn_index=turn_index,
            sub_index=sub_index,
            kind=kind,
            payload=payload,
        )
    )


def _audit_conductor_turn(
    *,
    issue_id: str,
    conductor_task_id: str,
    kind: ConductorTurnKind,
    payload: JsonObject,
) -> None:
    """Co-locate a unified audit row alongside the conductor_turns write.

    Thin forwarding shell over `audit.record_conductor_turn` — the kind→category
    map and status/actor/error derivation live in the audit package now. Kept as
    a module function so existing tests can call it directly and the conductor
    loop's call sites stay unchanged.
    """
    from app.application import audit

    audit.record_conductor_turn(
        issue_id=issue_id,
        conductor_task_id=conductor_task_id,
        kind=kind,
        payload=payload,
        trace_id=conductor_task_id,
    )


async def run_issue_conductor_loop(
    issue: CodexIssue,
    project_id: str,
    store: object,
    event_bus: EventBusLike | None = None,
    task_dispatcher_fn: TaskDispatcherFn | None = None,
    recovery_context: str = "",
) -> ConductorLoopResult:
    """Entry point for Conductor-driven issue orchestration."""
    logger = logging.getLogger(__name__)
    pause_registry = ConductorPauseRegistry.instance()
    lease_ttl_s = get_conductor_lease_ttl_s()
    lease_owner = get_conductor_lease_owner()
    started_at = datetime.now()
    conductor_task = ConductorTask(
        id=str(uuid4()),
        project_id=project_id,
        task_kind="issue",
        issue_id=issue.id,
        payload={
            "mode": "conductor_loop",
            "issue_title": issue.title,
            "phase": "awaiting_llm",
            "detail": None,
        },
        status="running",
        lease_owner=lease_owner,
        heartbeat_at=started_at,
        lease_expires_at=started_at + timedelta(seconds=lease_ttl_s),
        created_at=started_at,
        updated_at=started_at,
    )
    await cast(_ConductorTaskSaver, store).save_conductor_task(conductor_task)
    await pause_registry.register(conductor_task.id)
    from app.application.conductor_session_registry import ConductorSessionRegistry

    await ConductorSessionRegistry.instance().bind_conductor_task(issue.id, conductor_task.id)
    await _emit_conductor_status(
        event_bus,
        issue_id=issue.id,
        conductor_task=conductor_task,
    )
    # Reflect "the Conductor is actively working this issue" at the issue level.
    # Auto-start orchestration otherwise leaves issue.status at "open" (rendered
    # as 排队中) until the terminal seal, so the badge looks queued for the whole run.
    if issue.status in {"open", "queued"}:
        try:
            issue.status = "in_progress"
            issue.updated_at = datetime.now()
            await cast(_IssueSaver, store).save_codex_issue(issue)
            await _append_event(
                event_bus,
                {
                    "type": "issue_updated",
                    "issue_id": issue.id,
                    "session_id": issue.session_id,
                    "status": issue.status,
                },
            )
        except Exception as exc:  # noqa: BLE001, RUF100
            logger.warning("issue in_progress transition failed: %s", exc)
    estimator = get_phase_duration_estimator(store)

    current_turn_index = -1
    heartbeat_pulse_task: asyncio.Task[None] | None = None

    async def heartbeat() -> None:
        now = datetime.now()
        conductor_task.lease_owner = lease_owner
        conductor_task.heartbeat_at = now
        conductor_task.lease_expires_at = now + timedelta(seconds=lease_ttl_s)
        conductor_task.updated_at = now
        await cast(_ConductorTaskSaver, store).save_conductor_task(conductor_task)

    async def _on_heartbeat_degraded(n: int, exc: Exception) -> None:
        await _append_event(
            event_bus,
            {
                "type": "conductor_heartbeat_degraded",
                "issue_id": issue.id,
                "conductor_task_id": conductor_task.id,
                "consecutive_failures": n,
                "error": str(exc),
            },
        )

    async def heartbeat_pulse() -> None:
        # Delegates to the resilient module-level pulse (GAP A): renews the lease
        # while the loop is blocked on a slow subagent, surviving transient save
        # failures so the lease never silently expires (which would trigger a
        # duplicate-conductor relaunch).
        await _run_heartbeat_pulse(
            heartbeat,
            timeouts.lease_pulse_interval_s(),
            on_degraded=_on_heartbeat_degraded,
        )

    async def persist_turn(
        *, turn_index: int, sub_index: int, kind: ConductorTurnKind, payload: JsonObject
    ) -> None:
        nonlocal current_turn_index
        # Non-fatal: the background pulse is the authoritative lease renewer;
        # a transient blip here must not crash the loop.
        try:
            await heartbeat()
        except Exception as exc:  # noqa: BLE001, RUF100
            logger.warning(
                "conductor heartbeat (persist_turn) failed for issue %s: %s", issue.id, exc
            )
        if kind == "llm_request":
            current_turn_index = turn_index
            await set_phase("awaiting_llm")
        turn = ConductorTurn(
            id=str(uuid4()),
            conductor_task_id=conductor_task.id,
            issue_id=issue.id,
            turn_index=turn_index,
            sub_index=sub_index,
            kind=kind,
            payload_json=json.dumps(_prepare_payload(payload), ensure_ascii=False, default=str),
            created_at=datetime.now(),
        )
        save_turn = getattr(store, "save_conductor_turn", None)
        if callable(save_turn):
            await _maybe_await(save_turn(turn))
        # Co-locate a unified audit row (PR2). Reuses the exact same (already
        # truncated-on-store) payload — no second computation. Fire-and-forget,
        # best-effort: never blocks or raises into the loop.
        _audit_conductor_turn(
            issue_id=issue.id,
            conductor_task_id=conductor_task.id,
            kind=kind,
            payload=payload,
        )
        await _append_event(
            event_bus,
            {
                "type": "conductor_turn",
                "id": turn.id,
                "issue_id": issue.id,
                "conductor_task_id": conductor_task.id,
                "turn_index": turn.turn_index,
                "sub_index": turn.sub_index,
                "kind": turn.kind,
                "payload": json.loads(turn.payload_json),
                "summary": _summarize_turn(kind, payload),
                "created_at": turn.created_at.isoformat() if turn.created_at else None,
            },
        )

    async def persist_delta(
        *, turn_index: int, sub_index: int, content_block_index: int, kind: str, chunk: str
    ) -> None:
        await _append_event(
            event_bus,
            {
                "type": "conductor_turn_delta",
                "issue_id": issue.id,
                "conductor_task_id": conductor_task.id,
                "turn_index": turn_index,
                "sub_index": sub_index,
                "kind": kind,
                "chunk": chunk,
                "content_block_index": content_block_index,
                "created_at": datetime.now().isoformat(),
            },
        )

    async def set_phase(
        phase: str, detail: str | None = None, *, status: str | None = None
    ) -> None:
        await heartbeat()
        await transition_conductor_phase(
            store=store,
            event_bus=event_bus,
            issue_id=issue.id,
            conductor_task=conductor_task,
            phase=phase,
            detail=detail,
            status=status,
            estimator=estimator,
        )

    async def drain_inbox_messages() -> list[str]:
        drain_inbox = getattr(store, "drain_conductor_inbox", None)
        if not callable(drain_inbox):
            return []
        drained = await _maybe_await(drain_inbox(conductor_task.id))
        flushed: list[str] = []
        for turn in drained or []:
            try:
                payload = json.loads(turn.payload_json or "{}")
            except json.JSONDecodeError:
                payload = {}
            text = str(payload.get("text") or "").strip()
            if text:
                flushed.append(text)
        return flushed

    async def wait_until_resumed() -> None:
        is_paused = await pause_registry.is_paused(conductor_task.id)
        if not is_paused:
            return
        latest_task = None
        load_latest = getattr(store, "load_latest_conductor_task_for_issue", None)
        if callable(load_latest):
            latest_task = await _maybe_await(load_latest(issue.id))
        if (
            latest_task is not None
            and latest_task.id == conductor_task.id
            and (latest_task.status == "paused" or _conductor_phase(latest_task) == "paused")
        ):
            conductor_task.status = latest_task.status
            conductor_task.payload = latest_task.payload
            conductor_task.updated_at = latest_task.updated_at
        elif conductor_task.status != "paused" or _conductor_phase(conductor_task) != "paused":
            await set_phase("paused", _conductor_detail(conductor_task), status="paused")
        await pause_registry.wait_if_paused(conductor_task.id)
        latest_task = None
        if callable(load_latest):
            latest_task = await _maybe_await(load_latest(issue.id))
        if (
            latest_task is not None
            and latest_task.id == conductor_task.id
            and latest_task.status == "running"
        ):
            conductor_task.status = latest_task.status
            conductor_task.payload = latest_task.payload
            conductor_task.updated_at = latest_task.updated_at
        elif conductor_task.status == "paused":
            payload = conductor_task.payload if isinstance(conductor_task.payload, dict) else {}
            resume_detail = payload.get("resume_detail")
            await set_phase(
                str(payload.get("resume_phase") or "awaiting_llm"),
                resume_detail if isinstance(resume_detail, str) and resume_detail else None,
                status="running",
            )

    try:
        registry = build_conductor_tools(
            project_id=project_id,
            store=store,
            event_bus=event_bus,
            task_dispatcher_fn=task_dispatcher_fn,
            issue_id=issue.id,
            conductor_task_id=conductor_task.id,
            on_status=set_phase,
        )

        catalog = await RuntimeCatalogService(cast(RuntimeCatalogStore, store)).load_catalog()
        cllm = resolve_conductor_llm_context(catalog)
        language_directive = ""
        try:
            output_language = catalog.conductor_llm.output_language
            if (output_language or "auto").strip().lower() in ("", "auto"):
                # "auto": match the issue's own language (its documented intent)
                # rather than emitting no directive — otherwise the model defaults
                # to English narration even on a Chinese issue.
                output_language = detect_text_language(issue.title, issue.description)
            language_directive = conductor_language_directive(output_language)
        except Exception:  # noqa: BLE001, RUF100
            logger.debug(
                "conductor language directive resolution failed: issue_id=%s",
                issue.id,
                exc_info=True,
            )

        conductor = ProjectConductor(
            project_id=project_id,
            store=cast(ProjectConductorStore, store),
            event_bus=event_bus,
        )
        project_context = ""
        try:
            state = await conductor.get_or_create_state()
            if state:
                if state.pinned_text:
                    project_context += (
                        f"\n\n## PROJECT CONTEXT (team_notes)\n{state.pinned_text[:2000]}"
                    )
                if state.warm_summaries_json:
                    warm = json.loads(state.warm_summaries_json or "[]")
                    if warm:
                        project_context += "\n\n## RECENT PROJECT HISTORY\n" + "\n".join(
                            str(w) for w in warm[-3:]
                        )
        except Exception:  # noqa: BLE001, RUF100
            logger.debug("conductor project context load failed: issue_id=%s", issue.id, exc_info=True)

        # Cost-aware scheduling (PR2 + PR3): make accrued spend + budget visible to
        # the orchestrating brain, and (PR3) steer model choice / wind-down by it.
        # PR3 injects candidate model unit prices (cheap→expensive) and escalates
        # the block's tone at the soft-warn threshold / over budget, plus emits a
        # structured steering event for observability. This is soft guidance only —
        # the loop is never hard-killed here. Best-effort: a failure must never
        # block the loop.
        budget_context = ""
        budget_status = None
        try:
            budget_status = await compute_issue_budget_status(cast(BudgetStore, store), issue)
            try:
                candidates = collect_candidate_model_prices(catalog)
            except Exception:  # noqa: BLE001, RUF100
                candidates = []
            prompt_budget_status = IssueBudgetStatus(
                issue_id=budget_status.issue_id,
                spent_usd=budget_status.spent_usd,
                budget_usd=budget_status.budget_usd,
                budget_source=budget_status.budget_source,
                soft_warn_ratio=budget_status.soft_warn_ratio,
                reserved_usd=0.0,
            )
            budget_context = "\n\n" + render_budget_summary(prompt_budget_status, candidates)
            steering = budget_steering_event(budget_status)
            if steering is not None:
                await _append_event(
                    event_bus,
                    {**steering, "conductor_task_id": conductor_task.id},
                )
        except Exception:  # noqa: BLE001, RUF100
            logger.debug("conductor budget context load failed: issue_id=%s", issue.id, exc_info=True)

        # Runtime per-loop policy decision (origin/main design). Required even
        # when the prompt is built by the local helper below, because the `llm`
        # closure downstream branches on `policy_decision.action == "skip_llm"`.
        policy_decision = ConductorPolicyDecision(
            action="call_llm",
            reason_code="policy_unavailable",
            reason="Policy evidence could not be loaded; falling back to the Conductor LLM.",
        )
        try:
            list_turns = getattr(store, "list_conductor_turns", None)
            recent_turns = []
            if callable(list_turns):
                recent_turns = await _maybe_await(list_turns(issue.id, limit=20))
            graph = None
            load_graph = getattr(store, "load_workflow_graph_for_issue", None)
            if callable(load_graph):
                graph = await _maybe_await(load_graph(issue.id))
            policy_decision = decide_conductor_policy(
                issue,
                conductor_task,
                recent_turns=recent_turns or [],
                graph=graph,
                budget_status=budget_status,
            )
        except Exception as exc:  # noqa: BLE001, RUF100
            logger.warning("conductor policy decision failed for issue %s: %s", issue.id, exc)

        # Local refactored prompt builder (Operating Contract design) + the
        # runtime policy hint injected as a second policy layer.
        prompt = build_issue_conductor_prompt(
            issue=issue,
            project_context=project_context,
            budget_context=budget_context,
            language_directive=language_directive,
            conductor_policy_hint=render_conductor_policy_hint(policy_decision),
            recovery_context=recovery_context,
        )

        async def llm(
            messages: list[JsonObject],
            tools: list[JsonObject],
            on_token_delta: TokenDeltaRecorder | None = None,
        ) -> JsonObject:
            if policy_decision.action == "skip_llm":
                return {
                    "stop_reason": "tool_use",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_policy_skip",
                            "name": "finalize_task",
                            "input": {
                                "status": "blocked",
                                "answer": (
                                    "Conductor policy skipped the LLM turn; "
                                    f"manual review is required before completion. {policy_decision.reason}"
                                ),
                            },
                        }
                    ],
                }
            if cllm is None:
                return {
                    "stop_reason": "tool_use",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_fallback",
                            "name": "finalize_task",
                            "input": {
                                "status": "blocked",
                                "answer": "LLM not configured; conductor loop cannot complete the issue.",
                            },
                        }
                    ],
                }
            streamed = False

            async def handle_delta(content_block_index: int, kind: str, chunk: str) -> None:
                nonlocal streamed
                if not streamed:
                    streamed = True
                    await set_phase("streaming_llm")
                if on_token_delta is not None:
                    await _maybe_await(
                        on_token_delta(
                            turn_index=current_turn_index,
                            sub_index=0,
                            content_block_index=content_block_index,
                            kind=kind,
                            chunk=chunk,
                        )
                    )

            if on_token_delta is not None:
                try:
                    return await call_conductor_llm(
                        messages=messages,
                        tools=tools,
                        cllm=cllm,
                        on_delta=handle_delta,
                    )
                except Exception as exc:  # noqa: BLE001, RUF100
                    logger.warning("conductor streaming fallback to non-streaming: %s", exc)
            return await call_conductor_llm(messages=messages, tools=tools, cllm=cllm)

        heartbeat_pulse_task = asyncio.create_task(
            heartbeat_pulse(), name=f"conductor-heartbeat-{issue.id[:8]}"
        )

        await persist_turn(
            turn_index=-1,
            sub_index=0,
            kind="policy_decision",
            payload=policy_decision.to_payload(),
        )

        result = await run_conductor_loop(
            prompt=prompt,
            llm=llm,
            tools=registry.tools,
            tool_definitions=registry.definitions,
            max_turns=30,
            max_wall_s=timeouts.conductor_loop_max_s(),
            turn_recorder=persist_turn,
            inbox_drain=drain_inbox_messages,
            wait_if_paused=wait_until_resumed,
            is_pause_requested=lambda: pause_registry.is_paused(conductor_task.id),
            on_inflight_llm_task=lambda task: pause_registry.set_inflight_llm_task(
                conductor_task.id, task
            ),
            on_token_delta=persist_delta,
        )

        try:
            await conductor.append_hot_event(
                role="project_conductor",
                content=result.final_text,
                issue_id=issue.id,
                extra={
                    "task_id": conductor_task.id,
                    "kind": "issue_loop",
                    "status": result.status,
                    "tool_events": result.tool_events,
                },
            )
        except Exception as exc:  # noqa: BLE001, RUF100
            logger.warning("conductor hot event append failed: %s", exc)

        await _seal_graph_and_issue_status(
            store=store,
            issue=issue,
            event_bus=event_bus,
            result_status=result.status,
        )

        # Only explicit success statuses seal as done. Blocked/cancelled/error,
        # protocol failures, and loop ceilings must not masquerade as completed.
        is_failed_terminal = not _is_conductor_success_status(result.status)
        await transition_conductor_phase(
            store=store,
            event_bus=event_bus,
            issue_id=issue.id,
            conductor_task=conductor_task,
            phase="failed" if is_failed_terminal else "done",
            detail=result.final_text[:160] if result.final_text else None,
            status=result.status,
            estimator=estimator,
        )
        conductor_task.result_json = json.dumps(
            {
                "status": result.status,
                "answer": result.final_text,
                "tool_events": result.tool_events,
                "turn_count": result.turn_count,
            },
            ensure_ascii=False,
            default=str,
        )
        await cast(_ConductorTaskSaver, store).save_conductor_task(conductor_task)
        return result
    except Exception as exc:  # noqa: BLE001, RUF100
        logger.exception("run_issue_conductor_loop failed for issue %s", issue.id)
        await _record_failure(
            store=store,
            issue=issue,
            conductor_task=conductor_task,
            event_bus=event_bus,
            exc=exc,
        )
        return ConductorLoopResult(
            status="failed",
            final_text=str(exc),
            messages=[],
            tool_events=[],
            turn_count=0,
        )
    finally:
        if heartbeat_pulse_task is not None:
            heartbeat_pulse_task.cancel()
        await pause_registry.set_inflight_llm_task(conductor_task.id, None)
        await pause_registry.unregister(conductor_task.id)


async def recover_background_conductor_failure(
    *,
    issue_id: str,
    store: object,
    event_bus: EventBusLike | None,
    exc: BaseException,
) -> None:
    issue = await cast(_IssueLoader, store).load_codex_issue(issue_id)
    if issue is None or not hasattr(store, "load_latest_conductor_task_for_issue"):
        return
    conductor_task = await cast(_LatestConductorTaskLoader, store).load_latest_conductor_task_for_issue(
        issue_id
    )
    if conductor_task is None or is_task_failure_status(conductor_task.status):
        return
    await _record_failure(
        store=store,
        issue=issue,
        conductor_task=conductor_task,
        event_bus=event_bus,
        exc=exc,
    )


async def _record_failure(
    *,
    store: object,
    issue: CodexIssue,
    conductor_task: ConductorTask,
    event_bus: EventBusLike | None,
    exc: BaseException,
) -> None:
    error_message = str(exc) or exc.__class__.__name__
    tb_text = _truncate_text(
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)), _TRACEBACK_LIMIT
    )
    estimator = get_phase_duration_estimator(store)
    error_payload: JsonObject = {
        "error_class": exc.__class__.__name__,
        "message": error_message,
        "traceback": tb_text,
    }
    save_turn = getattr(store, "save_conductor_turn", None)
    if callable(save_turn):
        turn = ConductorTurn(
            id=str(uuid4()),
            conductor_task_id=conductor_task.id,
            issue_id=issue.id,
            turn_index=0,
            sub_index=0,
            kind="error",
            payload_json=json.dumps(error_payload, ensure_ascii=False),
            created_at=datetime.now(),
            consumed_at=None,
        )
        await _maybe_await(save_turn(turn))
    # Co-locate a unified audit row for the loop-crash error (PR2). This path
    # writes save_conductor_turn directly (not via persist_turn), so the audit
    # call lives here too. Best-effort + fire-and-forget.
    _audit_conductor_turn(
        issue_id=issue.id,
        conductor_task_id=conductor_task.id,
        kind="error",
        payload=error_payload,
    )
    await transition_conductor_phase(
        store=store,
        event_bus=event_bus,
        issue_id=issue.id,
        conductor_task=conductor_task,
        phase="failed",
        detail=error_message[:160],
        status="failed",
        estimator=estimator,
    )
    conductor_task.result_json = json.dumps(
        {
            "status": "failed",
            "error": exc.__class__.__name__,
            "message": error_message,
            "traceback": tb_text,
        },
        ensure_ascii=False,
    )
    await cast(_ConductorTaskSaver, store).save_conductor_task(conductor_task)
    await _append_event(
        event_bus,
        {
            "type": "conductor_failed",
            "issue_id": issue.id,
            "conductor_task_id": conductor_task.id,
            "error_class": exc.__class__.__name__,
            "error_message": error_message,
            "traceback": tb_text,
        },
    )
    await _seal_graph_and_issue_status(
        store=store,
        issue=issue,
        event_bus=event_bus,
        result_status="failed",
    )


async def _seal_graph_and_issue_status(
    *,
    store: object,
    issue: CodexIssue,
    event_bus: EventBusLike | None,
    result_status: str,
) -> None:
    graph_status = "done" if _is_conductor_success_status(result_status) else "failed"
    graph = None
    try:
        graph = await cast(_WorkflowGraphLoader, store).load_workflow_graph_for_issue(issue.id)
    except Exception as exc:  # noqa: BLE001, RUF100
        logging.getLogger(__name__).warning("workflow graph load failed during terminal seal: %s", exc)

    if graph is not None:
        try:
            if graph.status != graph_status:
                graph.status = graph_status
                graph.updated_at = datetime.now()
                await cast(_WorkflowGraphSaver, store).save_workflow_graph(graph)
        except Exception as exc:  # noqa: BLE001, RUF100
            logging.getLogger(__name__).warning("workflow graph status seal failed: %s", exc)
        if graph_status == "done":
            try:
                await record_project_memory(graph.id, cast(ProjectMemoryStore, store))
            except Exception as exc:  # noqa: BLE001, RUF100
                logging.getLogger(__name__).warning(
                    "project memory record failed after successful seal: %s", exc
                )
            try:
                await record_issue_self_improvement(
                    issue, cast(SelfImprovementProposalStore, store)
                )
            except Exception as exc:  # noqa: BLE001, RUF100
                logging.getLogger(__name__).warning("self_improvement extraction failed: %s", exc)

    try:
        preserve_awaiting_status = (
            graph_status == "done"
            and issue.status in {"awaiting_approval", "awaiting_review", "awaiting_merge"}
        )
        if not preserve_awaiting_status:
            issue.status = "completed" if graph_status == "done" else "failed"
            issue.updated_at = datetime.now()
            await cast(_IssueSaver, store).save_codex_issue(issue)
            await _append_event(
                event_bus,
                {
                    "type": "issue_updated",
                    "issue_id": issue.id,
                    "session_id": issue.session_id,
                    "status": issue.status,
                },
            )
    except Exception as exc:  # noqa: BLE001, RUF100
        logging.getLogger(__name__).warning("issue terminal status seal failed: %s", exc)

    # Terminal-state swarm worktree cleanup (best-effort). Conductor finalizes
    # issues without the API merge/delete path, so residual per-agent swarm
    # worktrees + `swarm/*` branch refs have no other cleanup owner and would
    # leak across issues. Idempotent + never touches main. Mirrors the
    # fault-tolerant style of the record_project_memory block above: a failure
    # here only warns and never blocks the terminal seal.
    try:
        project: Project | None = None
        if issue.project_id:
            project = await cast(_ProjectLoader, store).load_project(issue.project_id)
        if project is not None:
            from app.bootstrap import worktree_manager as _wm

            await _wm.cleanup_issue_swarm_worktrees(project, issue)
    except Exception as exc:  # noqa: BLE001, RUF100
        logging.getLogger(__name__).warning("swarm worktree terminal cleanup failed: %s", exc)


async def _append_event(event_bus: EventBusLike | None, payload: JsonObject) -> None:
    if event_bus is None or not hasattr(event_bus, "append"):
        return
    result = event_bus.append(payload)
    if hasattr(result, "__await__"):
        await result


def _prepare_payload(payload: JsonObject) -> JsonObject:
    raw = json.dumps(payload, ensure_ascii=False, default=str)
    if len(raw) <= _TURN_PAYLOAD_LIMIT:
        return payload
    return {
        "__truncated__": True,
        "preview": _truncate_text(raw, _TURN_PAYLOAD_LIMIT - 64),
        "original_length": len(raw),
    }


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: max(0, limit - 16)]}...[truncated]"


def _summarize_turn(kind: str, payload: JsonObject) -> str:
    if kind == "llm_request":
        return f"LLM request with {payload.get('message_count', 0)} messages"
    if kind == "llm_response":
        return f"LLM response ({payload.get('stop_reason') or 'end_turn'})"
    if kind == "user_message":
        return f"User interjection: {str(payload.get('text') or '')[:80]}"
    if kind == "tool_use":
        return f"Tool call: {payload.get('name') or 'unknown'}"
    if kind == "tool_result":
        status = "error" if payload.get("is_error") else "ok"
        return f"Tool result: {payload.get('name') or 'unknown'} ({status})"
    if kind == "policy_decision":
        return f"Policy decision: {payload.get('action') or 'call_llm'} ({payload.get('reason_code') or 'unknown'})"
    if kind == "finalize":
        return f"Finalize: {payload.get('status') or 'done'}"
    if kind == "error":
        return f"Error: {payload.get('message') or payload.get('error_class') or 'unknown'}"
    return kind


async def transition_conductor_phase(
    *,
    store: object,
    event_bus: EventBusLike | None,
    issue_id: str,
    conductor_task: ConductorTask,
    phase: str,
    detail: str | None = None,
    status: str | None = None,
    estimator: PhaseDurationEstimator | None = None,
) -> None:
    new_status = status or conductor_task.status
    current_phase = _conductor_phase(conductor_task)
    current_detail = _conductor_detail(conductor_task)
    if current_phase == phase and current_detail == detail and conductor_task.status == new_status:
        return

    payload = conductor_task.payload if isinstance(conductor_task.payload, dict) else {}
    if phase == "paused" and current_phase and current_phase != "paused":
        payload = {
            **payload,
            "resume_phase": current_phase,
            "resume_detail": current_detail,
        }
    elif current_phase == "paused" and phase != "paused":
        payload = {k: v for k, v in payload.items() if k not in {"resume_phase", "resume_detail"}}

    is_legal = _is_legal_transition(current_phase, phase)
    # GAP C — force-fail policy: classify illegal transitions instead of always
    # warn-and-apply. A transition leaving a terminal phase (done/failed/stalled)
    # would resurrect a finished conductor into active work — corrupt state that
    # we must not apply. Block it (keep the run terminal) and surface it. Other
    # illegal transitions keep the historical warn-and-apply behaviour below.
    if not is_legal and current_phase in TERMINAL_PHASES:
        logging.getLogger(__name__).error(
            "Blocked illegal resurrection of terminal conductor for issue %s: %s -> %s",
            issue_id,
            current_phase,
            phase,
        )
        await _append_event(
            event_bus,
            {
                "type": "conductor_state_violation",
                "issue_id": issue_id,
                "conductor_task_id": conductor_task.id,
                "from_phase": current_phase,
                "to_phase": phase,
                "from_detail": current_detail,
                "to_detail": detail,
                "blocked": True,
                "transition_at": datetime.now().isoformat(),
            },
        )
        return
    transition_at = datetime.now()
    conductor_task.status = new_status
    conductor_task.payload = {
        **payload,
        "phase": phase,
        "detail": detail,
    }
    conductor_task.updated_at = transition_at
    await cast(_ConductorTaskSaver, store).save_conductor_task(conductor_task)
    await _record_conductor_state_transition(
        store=store,
        issue_id=issue_id,
        from_phase=current_phase,
        to_phase=phase,
        from_detail=current_detail,
        to_detail=detail,
        transition_at=transition_at,
        is_legal=is_legal,
        estimator=estimator,
    )
    if not is_legal:
        logging.getLogger(__name__).warning(
            "Illegal conductor phase transition for issue %s: %s -> %s",
            issue_id,
            current_phase,
            phase,
        )
        await _append_event(
            event_bus,
            {
                "type": "conductor_state_violation",
                "issue_id": issue_id,
                "conductor_task_id": conductor_task.id,
                "from_phase": current_phase,
                "to_phase": phase,
                "from_detail": current_detail,
                "to_detail": detail,
                "transition_at": transition_at.isoformat(),
            },
        )
    await _emit_conductor_status(
        event_bus,
        issue_id=issue_id,
        conductor_task=conductor_task,
    )


async def _record_conductor_state_transition(
    *,
    store: object,
    issue_id: str,
    from_phase: str | None,
    to_phase: str,
    from_detail: str | None,
    to_detail: str | None,
    transition_at: datetime,
    is_legal: bool,
    estimator: PhaseDurationEstimator | None = None,
) -> None:
    save_state_log = getattr(store, "save_conductor_state_log", None)
    list_state_logs = getattr(store, "list_conductor_state_logs", None)
    if not callable(save_state_log):
        return
    duration_ms = None
    if callable(list_state_logs):
        previous = await _maybe_await(list_state_logs(issue_id, limit=1, descending=True))
        if previous:
            previous_at = previous[0].transition_at
            if previous_at is not None:
                duration_ms = max(1, int((transition_at - previous_at).total_seconds() * 1000))
    await _maybe_await(
        save_state_log(
            ConductorStateLog(
                id=str(uuid4()),
                issue_id=issue_id,
                from_phase=from_phase,
                to_phase=to_phase,
                from_detail=from_detail,
                to_detail=to_detail,
                transition_at=transition_at,
                duration_ms=duration_ms,
                is_legal=is_legal,
            )
        )
    )
    if estimator is not None and hasattr(estimator, "invalidate"):
        estimator.invalidate()


async def _emit_conductor_status(
    event_bus: EventBusLike | None, *, issue_id: str, conductor_task: ConductorTask
) -> None:
    await _append_event(
        event_bus,
        {
            "type": "conductor_status",
            "issue_id": issue_id,
            "conductor_task_id": conductor_task.id,
            "status": conductor_task.status,
            "phase": _conductor_phase(conductor_task),
            "detail": _conductor_detail(conductor_task),
            "updated_at": conductor_task.updated_at.isoformat()
            if conductor_task.updated_at
            else None,
        },
    )


def _conductor_phase(conductor_task: ConductorTask) -> str | None:
    payload = conductor_task.payload if isinstance(conductor_task.payload, dict) else {}
    phase = payload.get("phase")
    return str(phase) if phase else None


def _conductor_detail(conductor_task: ConductorTask) -> str | None:
    payload = conductor_task.payload if isinstance(conductor_task.payload, dict) else {}
    detail = payload.get("detail")
    return str(detail) if detail else None


def _is_legal_transition(from_phase: str | None, to_phase: str) -> bool:
    if from_phase is None or from_phase == to_phase:
        return True
    return to_phase in LEGAL_TRANSITIONS.get(from_phase, set())
