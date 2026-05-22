"""Anthropic-style ProjectConductor tool-use loop.

This module is intentionally transport-agnostic: tests and API endpoints can
pass any LLM callable that returns Anthropic message-shaped dictionaries.
"""
from __future__ import annotations

import inspect
import json
import logging
import traceback
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Union
from uuid import uuid4

from app.application.conductor_tools import build_conductor_tools
from app.application.llm_runner import call_llm_with_tools, resolve_streaming_context
from app.application.project_conductor import ProjectConductor
from app.application.project_memory_service import record_project_memory
from app.application.runtime_catalog_service import RuntimeCatalogService
from app.domain.models import ConductorTask, ConductorTurn


ToolCallable = Callable[[dict[str, Any]], Union[Awaitable[Any], Any]]
LLMCallable = Callable[
    [list[dict[str, Any]], list[dict[str, Any]]],
    Union[Awaitable[dict[str, Any]], dict[str, Any]],
]
TurnRecorder = Callable[..., Union[Awaitable[None], None]]

_TURN_PAYLOAD_LIMIT = 32_768
_TRACEBACK_LIMIT = 8_000


@dataclass
class ConductorLoopResult:
    status: str
    final_text: str
    messages: list[dict[str, Any]]
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    turn_count: int = 0


async def run_conductor_loop(
    *,
    prompt: str,
    llm: LLMCallable,
    tools: dict[str, ToolCallable],
    tool_definitions: list[dict[str, Any]],
    max_turns: int = 8,
    turn_recorder: TurnRecorder | None = None,
) -> ConductorLoopResult:
    """Run a conductor session until it reaches final text or a final tool."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    tool_events: list[dict[str, Any]] = []
    final_text = ""

    for turn_index in range(max_turns):
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
        response = await _maybe_await(llm(deepcopy(messages), tool_definitions))
        content = _normalise_content(response.get("content"))
        messages.append({"role": "assistant", "content": content})
        final_text = _text_from_content(content) or final_text

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
    conductor_task = ConductorTask(
        id=str(uuid4()),
        project_id=project_id,
        task_kind="issue",
        issue_id=issue.id,
        payload={"mode": "conductor_loop", "issue_title": issue.title},
        status="running",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await store.save_conductor_task(conductor_task)

    async def persist_turn(*, turn_index: int, sub_index: int, kind: str, payload: dict[str, Any]) -> None:
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

    try:
        registry = build_conductor_tools(
            project_id=project_id,
            store=store,
            event_bus=event_bus,
            task_dispatcher_fn=task_dispatcher_fn,
            issue_id=issue.id,
        )

        catalog = await RuntimeCatalogService(store).load_catalog()
        ctx = resolve_streaming_context(catalog)

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
- When all work is complete, call `finalize_task` with a summary
- You MUST call `finalize_task` to end the loop

## Important
Think step by step. After each dispatch_subagent returns, analyze the result before deciding the next step.
If something is unclear or blocked, use `request_user_clarification`.
"""

        async def llm(messages, tools):
            if ctx is None:
                return {
                    "stop_reason": "tool_use",
                    "content": [{
                        "type": "tool_use",
                        "id": "toolu_fallback",
                        "name": "finalize_task",
                        "input": {"status": "done", "answer": "LLM not configured; conductor loop skipped."},
                    }],
                }
            return await call_llm_with_tools(messages=messages, tools=tools, ctx=ctx)

        result = await run_conductor_loop(
            prompt=prompt,
            llm=llm,
            tools=registry.tools,
            tool_definitions=registry.definitions,
            max_turns=30,
            turn_recorder=persist_turn,
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

        conductor_task.status = result.status
        conductor_task.updated_at = datetime.now()
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
        )
        await _maybe_await(save_turn(turn))
    conductor_task.status = "failed"
    conductor_task.updated_at = datetime.now()
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
