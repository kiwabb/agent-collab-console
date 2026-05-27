"""Anthropic-style ProjectConductor tool-use loop.

This module is intentionally transport-agnostic: tests and API endpoints can
pass any LLM callable that returns Anthropic message-shaped dictionaries.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import traceback
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Union
from uuid import uuid4

from app.application import timeouts
from app.application.conductor_tools import build_conductor_tools
from app.application.conductor_lease import get_conductor_lease_owner, get_conductor_lease_ttl_s
from app.application.conductor_pause_registry import ConductorPauseRegistry
from app.application.phase_duration_estimator import get_phase_duration_estimator
from app.application.conductor_llm import call_conductor_llm, resolve_conductor_llm_context
from app.application.project_conductor import ProjectConductor
from app.application.project_memory_service import record_project_memory
from app.application.runtime_catalog_service import RuntimeCatalogService
from app.domain.models import ConductorStateLog, ConductorTask, ConductorTurn


ToolCallable = Callable[[dict[str, Any]], Union[Awaitable[Any], Any]]
LLMCallable = Callable[
    [list[dict[str, Any]], list[dict[str, Any]]],
    Union[Awaitable[dict[str, Any]], dict[str, Any]],
]
TurnRecorder = Callable[..., Union[Awaitable[None], None]]
InboxDrainer = Callable[[], Union[Awaitable[list[str]], list[str]]]
PauseGate = Callable[[], Union[Awaitable[None], None]]
PausePredicate = Callable[[], Union[Awaitable[bool], bool]]
InflightTaskSetter = Callable[[asyncio.Task | None], Union[Awaitable[None], None]]
TokenDeltaRecorder = Callable[..., Union[Awaitable[None], None]]

_TURN_PAYLOAD_LIMIT = 32_768
_TRACEBACK_LIMIT = 8_000
# Number of consecutive heartbeat-pulse failures before we emit a structured
# `conductor_heartbeat_degraded` event (GAP A): the pulse keeps retrying, but a
# sustained failure means the lease is at risk of expiring, so make it visible.
HEARTBEAT_DEGRADED_ALERT_AFTER = 3
# Terminal phases: once a conductor reaches one of these its run is over.
# A transition *out* of a terminal phase is a resurrection bug and is blocked
# (GAP C) rather than silently reviving a finished run.
_TERMINAL_PHASES: frozenset[str] = frozenset({"done", "failed", "stalled"})
LEGAL_TRANSITIONS: dict[str, set[str]] = {
    "awaiting_llm": {"streaming_llm", "dispatching_subagent", "awaiting_user_clarification", "paused", "done", "failed", "stalled"},
    "streaming_llm": {"dispatching_subagent", "awaiting_user_clarification", "paused", "done", "failed", "stalled"},
    "dispatching_subagent": {"awaiting_subagent", "awaiting_llm", "paused", "failed", "stalled"},
    "awaiting_subagent": {"awaiting_llm", "paused", "failed", "stalled"},
    "awaiting_user_clarification": {"awaiting_llm", "paused", "failed", "stalled"},
    "paused": {"awaiting_llm", "streaming_llm", "dispatching_subagent", "awaiting_subagent", "awaiting_user_clarification", "done", "failed", "stalled"},
    "done": set(),
    "failed": set(),
    "stalled": set(),
}


@dataclass
class ConductorLoopResult:
    status: str
    final_text: str
    messages: list[dict[str, Any]]
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    turn_count: int = 0


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
        except Exception as exc:  # noqa: BLE001
            consecutive_failures += 1
            log.warning(
                "conductor heartbeat pulse failed (%d consecutive): %s",
                consecutive_failures, exc,
            )
            if consecutive_failures == alert_after and on_degraded is not None:
                try:
                    await on_degraded(consecutive_failures, exc)
                except Exception:  # noqa: BLE001
                    pass


async def run_conductor_loop(
    *,
    prompt: str,
    llm: LLMCallable,
    tools: dict[str, ToolCallable],
    tool_definitions: list[dict[str, Any]],
    max_turns: int = 8,
    turn_recorder: TurnRecorder | None = None,
    inbox_drain: InboxDrainer | None = None,
    wait_if_paused: PauseGate | None = None,
    is_pause_requested: PausePredicate | None = None,
    on_inflight_llm_task: InflightTaskSetter | None = None,
    on_token_delta: TokenDeltaRecorder | None = None,
) -> ConductorLoopResult:
    """Run a conductor session until it reaches final text or a final tool."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    tool_events: list[dict[str, Any]] = []
    final_text = ""

    for turn_index in range(max_turns):
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
            await _record_turn(
                turn_recorder,
                turn_index=turn_index,
                sub_index=0,
                kind="finalize",
                payload={"status": "done", "answer": final_text},
            )
            return ConductorLoopResult(
                status="done",
                final_text=final_text,
                messages=messages,
                tool_events=tool_events,
                turn_count=turn_index + 1,
            )

        result_blocks: list[dict[str, Any]] = []
        for sub_index, tool_use in enumerate(tool_uses, start=1):
            await _record_turn(
                turn_recorder,
                turn_index=turn_index,
                sub_index=sub_index,
                kind="tool_use",
                payload={
                    "id": str(tool_use.get("id") or ""),
                    "name": str(tool_use.get("name") or ""),
                    "input": tool_use.get("input") if isinstance(tool_use.get("input"), dict) else {},
                },
            )
            event = await _execute_tool_use(tool_use, tools)
            tool_events.append(event)
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
            if event["name"] == "finalize_task" and not event["is_error"]:
                result = event["result"] if isinstance(event["result"], dict) else {}
                final_status = str(result.get("status") or "done")
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


async def _execute_tool_use(
    tool_use: dict[str, Any],
    tools: dict[str, ToolCallable],
) -> dict[str, Any]:
    tool_id = str(tool_use.get("id") or "")
    name = str(tool_use.get("name") or "")
    tool_input = tool_use.get("input") if isinstance(tool_use.get("input"), dict) else {}
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
    except Exception as exc:  # noqa: BLE001
        return {
            "id": tool_id,
            "name": name,
            "input": tool_input,
            "result": {"error": str(exc)},
            "is_error": True,
        }


def _normalise_content(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    return []


def _text_from_content(content: list[dict[str, Any]]) -> str:
    return "".join(str(block.get("text") or "") for block in content if block.get("type") == "text")


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def _call_llm_with_optional_delta(
    llm: LLMCallable,
    *,
    messages: list[dict[str, Any]],
    tool_definitions: list[dict[str, Any]],
    on_token_delta: TokenDeltaRecorder | None,
):
    params = inspect.signature(llm).parameters
    if "on_token_delta" in params:
        return await _maybe_await(
            llm(messages, tool_definitions, on_token_delta=on_token_delta)
        )
    return await _maybe_await(llm(messages, tool_definitions))


async def _record_turn(
    turn_recorder: TurnRecorder | None,
    *,
    turn_index: int,
    sub_index: int,
    kind: str,
    payload: dict[str, Any],
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


async def run_issue_conductor_loop(
    issue,
    project_id: str,
    store,
    event_bus=None,
    task_dispatcher_fn=None,
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
    await store.save_conductor_task(conductor_task)
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
    if getattr(issue, "status", None) in {"open", "queued"}:
        try:
            issue.status = "in_progress"
            issue.updated_at = datetime.now()
            await store.save_codex_issue(issue)
            await _append_event(
                event_bus,
                {
                    "type": "issue_updated",
                    "issue_id": issue.id,
                    "session_id": issue.session_id,
                    "status": issue.status,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("issue in_progress transition failed: %s", exc)
    estimator = get_phase_duration_estimator(store)

    current_turn_index = -1
    heartbeat_pulse_task: asyncio.Task | None = None

    async def heartbeat() -> None:
        now = datetime.now()
        conductor_task.lease_owner = lease_owner
        conductor_task.heartbeat_at = now
        conductor_task.lease_expires_at = now + timedelta(seconds=lease_ttl_s)
        conductor_task.updated_at = now
        await store.save_conductor_task(conductor_task)

    async def _on_heartbeat_degraded(n: int, exc: Exception) -> None:
        await _append_event(event_bus, {
            "type": "conductor_heartbeat_degraded",
            "issue_id": issue.id,
            "conductor_task_id": conductor_task.id,
            "consecutive_failures": n,
            "error": str(exc),
        })

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

    async def persist_turn(*, turn_index: int, sub_index: int, kind: str, payload: dict[str, Any]) -> None:
        nonlocal current_turn_index
        # Non-fatal: the background pulse is the authoritative lease renewer;
        # a transient blip here must not crash the loop.
        try:
            await heartbeat()
        except Exception as exc:  # noqa: BLE001
            logger.warning("conductor heartbeat (persist_turn) failed for issue %s: %s", issue.id, exc)
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

    async def persist_delta(*, turn_index: int, sub_index: int, content_block_index: int, kind: str, chunk: str) -> None:
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

    async def set_phase(phase: str, detail: str | None = None, *, status: str | None = None) -> None:
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
        if latest_task is not None and latest_task.id == conductor_task.id and (
            latest_task.status == "paused" or _conductor_phase(latest_task) == "paused"
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
        if latest_task is not None and latest_task.id == conductor_task.id and latest_task.status == "running":
            conductor_task.status = latest_task.status
            conductor_task.payload = latest_task.payload
            conductor_task.updated_at = latest_task.updated_at
        elif conductor_task.status == "paused":
            payload = conductor_task.payload if isinstance(conductor_task.payload, dict) else {}
            await set_phase(
                str(payload.get("resume_phase") or "awaiting_llm"),
                payload.get("resume_detail") if payload.get("resume_detail") else None,
                status="running",
            )

    try:
        registry = build_conductor_tools(
            project_id=project_id,
            store=store,
            event_bus=event_bus,
            task_dispatcher_fn=task_dispatcher_fn,
            issue_id=issue.id,
            on_status=set_phase,
        )

        catalog = await RuntimeCatalogService(store).load_catalog()
        cllm = resolve_conductor_llm_context(catalog)

        conductor = ProjectConductor(project_id=project_id, store=store, event_bus=event_bus)
        project_context = ""
        try:
            state = await conductor._load_state()
            if state:
                if state.pinned_text:
                    project_context += f"\n\n## PROJECT CONTEXT (team_notes)\n{state.pinned_text[:2000]}"
                if state.warm_summaries_json:
                    warm = json.loads(state.warm_summaries_json or "[]")
                    if warm:
                        project_context += "\n\n## RECENT PROJECT HISTORY\n" + "\n".join(str(w) for w in warm[-3:])
        except Exception:  # noqa: BLE001
            pass

        prompt = f"""You are the ProjectConductor orchestrating work on this issue.

## Issue
Title: {issue.title}
Description: {issue.description or "(no description provided)"}
{project_context}

## Your Job
Use the `dispatch_subagent` tool to run the agents needed to complete this issue.
Standard agents: pm, architect, engineer, qa.
You can also use specialist roles: security_reviewer, perf_reviewer, doc_writer, etc.

## Guidelines
- Start with `pm` to clarify requirements (unless the issue is purely technical and requirements are crystal clear)
- Use `architect` for features needing design decisions; skip for simple fixes
- Always run `engineer` to implement
- Always run `qa` to verify
- Pass `prev_node_key` as the node_key of the agent you just dispatched (for graph visualization)
- If a subagent result shows `clarification_question`, use `request_user_clarification` to ask the user
- If QA fails (status=failed), consider dispatching `engineer` again with the QA failure in the prompt
- If a subagent returns `status=artifact_invalid`, its output did not match the expected schema (see `validation_error`). Re-dispatch the SAME role with a corrective prompt that restates the required output schema and what was wrong — do NOT proceed as if it succeeded
- If a dispatch returns `status=retries_exhausted`, that role has already been retried the maximum number of times. Do NOT dispatch it again — either try a different role, `request_user_clarification`, or `finalize_task` with a summary of what's blocked
- When all work is complete, call `finalize_task` with a summary
- You MUST call `finalize_task` to end the loop

## Important
Think step by step. After each dispatch_subagent returns, analyze the result before deciding the next step.
If something is unclear or blocked, use `request_user_clarification`.
Users may inject `[USER INTERJECTION]` messages between turns. Treat them as authoritative steering for the next decision.
"""

        async def llm(messages, tools, on_token_delta=None):
            if cllm is None:
                return {
                    "stop_reason": "tool_use",
                    "content": [{
                        "type": "tool_use",
                        "id": "toolu_fallback",
                        "name": "finalize_task",
                        "input": {"status": "done", "answer": "LLM not configured; conductor loop skipped."},
                    }],
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
                except Exception as exc:  # noqa: BLE001
                    logger.warning("conductor streaming fallback to non-streaming: %s", exc)
            return await call_conductor_llm(messages=messages, tools=tools, cllm=cllm)

        heartbeat_pulse_task = asyncio.create_task(
            heartbeat_pulse(), name=f"conductor-heartbeat-{issue.id[:8]}"
        )

        result = await run_conductor_loop(
            prompt=prompt,
            llm=llm,
            tools=registry.tools,
            tool_definitions=registry.definitions,
            max_turns=30,
            turn_recorder=persist_turn,
            inbox_drain=drain_inbox_messages,
            wait_if_paused=wait_until_resumed,
            is_pause_requested=lambda: pause_registry.is_paused(conductor_task.id),
            on_inflight_llm_task=lambda task: pause_registry.set_inflight_llm_task(conductor_task.id, task),
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
        except Exception as exc:  # noqa: BLE001
            logger.warning("conductor hot event append failed: %s", exc)

        await _seal_graph_and_issue_status(
            store=store,
            issue=issue,
            event_bus=event_bus,
            result_status=result.status,
        )

        await transition_conductor_phase(
            store=store,
            event_bus=event_bus,
            issue_id=issue.id,
            conductor_task=conductor_task,
            phase="done" if result.status != "failed" else "failed",
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
        await store.save_conductor_task(conductor_task)
        return result
    except Exception as exc:  # noqa: BLE001
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
    store,
    event_bus,
    exc: BaseException,
) -> None:
    issue = await store.load_codex_issue(issue_id)
    if issue is None or not hasattr(store, "load_latest_conductor_task_for_issue"):
        return
    conductor_task = await store.load_latest_conductor_task_for_issue(issue_id)
    if conductor_task is None or conductor_task.status == "failed":
        return
    await _record_failure(
        store=store,
        issue=issue,
        conductor_task=conductor_task,
        event_bus=event_bus,
        exc=exc,
    )


async def _record_failure(*, store, issue, conductor_task: ConductorTask, event_bus, exc: BaseException) -> None:
    error_message = str(exc) or exc.__class__.__name__
    tb_text = _truncate_text("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)), _TRACEBACK_LIMIT)
    estimator = get_phase_duration_estimator(store)
    save_turn = getattr(store, "save_conductor_turn", None)
    if callable(save_turn):
        turn = ConductorTurn(
            id=str(uuid4()),
            conductor_task_id=conductor_task.id,
            issue_id=issue.id,
            turn_index=0,
            sub_index=0,
            kind="error",
            payload_json=json.dumps(
                {
                    "error_class": exc.__class__.__name__,
                    "message": error_message,
                    "traceback": tb_text,
                },
                ensure_ascii=False,
            ),
            created_at=datetime.now(),
            consumed_at=None,
        )
        await _maybe_await(save_turn(turn))
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
    await store.save_conductor_task(conductor_task)
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


async def _seal_graph_and_issue_status(*, store, issue, event_bus, result_status: str) -> None:
    graph_status = "done" if result_status in {"done", "success", "completed"} else "failed"
    try:
        graph = await store.load_workflow_graph_for_issue(issue.id)
        if graph is not None:
            if graph.status != graph_status:
                graph.status = graph_status
                graph.updated_at = datetime.now()
                await store.save_workflow_graph(graph)
            if graph_status == "done":
                await record_project_memory(graph.id, store)
        if issue.status not in {"awaiting_approval", "awaiting_review", "awaiting_merge"}:
            issue.status = "completed" if graph_status == "done" else "failed"
            issue.updated_at = datetime.now()
            await store.save_codex_issue(issue)
            await _append_event(
                event_bus,
                {
                    "type": "issue_updated",
                    "issue_id": issue.id,
                    "session_id": issue.session_id,
                    "status": issue.status,
                },
            )
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning("graph status seal / project memory failed: %s", exc)


async def _append_event(event_bus, payload: dict[str, Any]) -> None:
    if event_bus is None or not hasattr(event_bus, "append"):
        return
    result = event_bus.append(payload)
    if hasattr(result, "__await__"):
        await result


def _prepare_payload(payload: dict[str, Any]) -> dict[str, Any]:
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


def _summarize_turn(kind: str, payload: dict[str, Any]) -> str:
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
    if kind == "finalize":
        return f"Finalize: {payload.get('status') or 'done'}"
    if kind == "error":
        return f"Error: {payload.get('message') or payload.get('error_class') or 'unknown'}"
    return kind


async def transition_conductor_phase(
    *,
    store,
    event_bus,
    issue_id: str,
    conductor_task: ConductorTask,
    phase: str,
    detail: str | None = None,
    status: str | None = None,
    estimator=None,
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
    if not is_legal and current_phase in _TERMINAL_PHASES:
        logging.getLogger(__name__).error(
            "Blocked illegal resurrection of terminal conductor for issue %s: %s -> %s",
            issue_id, current_phase, phase,
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
    await store.save_conductor_task(conductor_task)
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
        logging.getLogger(__name__).warning("Illegal conductor phase transition for issue %s: %s -> %s", issue_id, current_phase, phase)
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
    store,
    issue_id: str,
    from_phase: str | None,
    to_phase: str,
    from_detail: str | None,
    to_detail: str | None,
    transition_at: datetime,
    is_legal: bool,
    estimator=None,
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


async def _emit_conductor_status(event_bus, *, issue_id: str, conductor_task: ConductorTask) -> None:
    await _append_event(
        event_bus,
        {
            "type": "conductor_status",
            "issue_id": issue_id,
            "conductor_task_id": conductor_task.id,
            "status": conductor_task.status,
            "phase": _conductor_phase(conductor_task),
            "detail": _conductor_detail(conductor_task),
            "updated_at": conductor_task.updated_at.isoformat() if conductor_task.updated_at else None,
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
