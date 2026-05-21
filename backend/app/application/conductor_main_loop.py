"""Anthropic-style ProjectConductor tool-use loop.

This module is intentionally transport-agnostic: tests and API endpoints can
pass any LLM callable that returns Anthropic message-shaped dictionaries.
"""
from __future__ import annotations

import inspect
import json
import logging
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
from app.domain.models import ConductorTask


ToolCallable = Callable[[dict[str, Any]], Union[Awaitable[Any], Any]]
LLMCallable = Callable[
    [list[dict[str, Any]], list[dict[str, Any]]],
    Union[Awaitable[dict[str, Any]], dict[str, Any]],
]


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
) -> ConductorLoopResult:
    """Run a conductor session until it reaches final text or a final tool.

    Anthropic represents tool calls as assistant `content` blocks with
    `type=tool_use`; each call must be answered by a user message containing
    matching `tool_result` blocks before the next LLM turn.
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    tool_events: list[dict[str, Any]] = []
    final_text = ""

    for turn_index in range(max_turns):
        response = await _maybe_await(llm(deepcopy(messages), tool_definitions))
        content = _normalise_content(response.get("content"))
        messages.append({"role": "assistant", "content": content})
        final_text = _text_from_content(content) or final_text

        tool_uses = [block for block in content if block.get("type") == "tool_use"]
        if not tool_uses:
            return ConductorLoopResult(
                status="done",
                final_text=final_text,
                messages=messages,
                tool_events=tool_events,
                turn_count=turn_index + 1,
            )

        result_blocks: list[dict[str, Any]] = []
        for tool_use in tool_uses:
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
            if event["name"] == "finalize_task" and not event["is_error"]:
                result = event["result"] if isinstance(event["result"], dict) else {}
                return ConductorLoopResult(
                    status=str(result.get("status") or "done"),
                    final_text=str(result.get("answer") or result.get("summary") or final_text),
                    messages=messages,
                    tool_events=tool_events,
                    turn_count=turn_index + 1,
                )

        messages.append({"role": "user", "content": result_blocks})

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


async def run_issue_conductor_loop(
    issue,
    project_id: str,
    store,
    event_bus=None,
    task_dispatcher_fn=None,
) -> "ConductorLoopResult":
    """Entry point for Conductor-driven issue orchestration.

    Replaces the fixed PM->Architect->Engineer->QA pipeline. The Conductor
    decides which agents to call in what order based on the issue context.
    """
    _logger = logging.getLogger(__name__)

    # Build tool registry with real dispatch capability
    registry = build_conductor_tools(
        project_id=project_id,
        store=store,
        event_bus=event_bus,
        task_dispatcher_fn=task_dispatcher_fn,
        issue_id=issue.id,
    )

    catalog = await RuntimeCatalogService(store).load_catalog()
    ctx = resolve_streaming_context(catalog)

    # Load project context (pinned team_notes + warm memories)
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
                "content": [{"type": "tool_use", "id": "toolu_fallback", "name": "finalize_task",
                              "input": {"status": "done", "answer": "LLM not configured; conductor loop skipped."}}],
            }
        return await call_llm_with_tools(messages=messages, tools=tools, ctx=ctx)

    # Save conductor task record
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

    result = await run_conductor_loop(
        prompt=prompt,
        llm=llm,
        tools=registry.tools,
        tool_definitions=registry.definitions,
        max_turns=30,
    )

    # Write final answer to ProjectConductor hot thread
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
        _logger.warning("conductor hot event append failed: %s", exc)

    # Seal the graph: WorkflowScheduler.on_task_completed no longer marks
    # the graph terminal in Conductor mode — that was a stale fixed-pipeline
    # assumption (it would fire as soon as the current node set was all done,
    # even though Conductor was about to dispatch the next agent). The loop
    # owns the graph lifecycle now.
    try:
        graph = await store.load_workflow_graph_for_issue(issue.id)
        if graph is not None:
            graph_status = "done" if result.status in {"done", "success", "completed"} else "failed"
            if graph.status != graph_status:
                graph.status = graph_status
                graph.updated_at = datetime.now()
                await store.save_workflow_graph(graph)
            await record_project_memory(graph.id, store)
            if event_bus is not None:
                try:
                    issue_status = "completed" if graph_status == "done" else "failed"
                    if issue.status not in {"awaiting_approval", "awaiting_review", "awaiting_merge"}:
                        issue.status = issue_status
                        issue.updated_at = datetime.now()
                        await store.save_codex_issue(issue)
                        await event_bus.append({
                            "type": "issue_updated",
                            "issue_id": issue.id,
                            "session_id": issue.session_id,
                            "status": issue.status,
                        })
                except Exception as exc:  # noqa: BLE001
                    _logger.debug("issue_updated emit failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("graph status seal / project memory failed: %s", exc)

    # Update conductor task status
    conductor_task.status = result.status
    conductor_task.updated_at = datetime.now()
    conductor_task.result_json = json.dumps({
        "status": result.status, "answer": result.final_text,
        "tool_events": result.tool_events, "turn_count": result.turn_count,
    }, ensure_ascii=False, default=str)
    await store.save_conductor_task(conductor_task)

    return result
