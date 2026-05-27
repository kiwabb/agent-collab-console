"""Tool registry for the ProjectConductor loop."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.application.project_conductor import ProjectConductor


ToolCallable = Callable[[dict[str, Any]], Awaitable[Any]]
ToolStatusCallback = Callable[[str, str | None], Awaitable[None] | None]


def _max_dispatches_per_role() -> int:
    """GAP G: max times the Conductor may dispatch the same role for one issue
    before the tool returns `retries_exhausted`. Allows the initial run plus a
    few reworks (e.g. engineer after QA failure) without unbounded looping."""
    raw = os.getenv("CONDUCTOR_MAX_DISPATCHES_PER_ROLE")
    if not raw:
        return 4
    try:
        return max(1, int(raw))
    except ValueError:
        return 4


@dataclass(frozen=True)
class ConductorToolRegistry:
    definitions: list[dict[str, Any]]
    tools: dict[str, ToolCallable]


def build_conductor_tools(
    *,
    project_id: str,
    store,
    event_bus=None,
    task_dispatcher_fn=None,
    issue_id: str | None = None,
    on_status: ToolStatusCallback | None = None,
) -> ConductorToolRegistry:
    conductor = ProjectConductor(project_id=project_id, store=store, event_bus=event_bus)

    async def retrieve_cold_memory(tool_input: dict[str, Any]) -> dict[str, Any]:
        query = str(tool_input.get("query") or "")
        top_k = int(tool_input.get("top_k") or 3)
        return {"memories": await conductor.retrieve_cold(query, top_k=max(1, min(top_k, 10)))}

    async def dispatch_subagent(tool_input: dict[str, Any]) -> dict[str, Any]:
        if task_dispatcher_fn is None or not issue_id:
            # Fallback stub (project-level ad-hoc usage without issue context)
            payload = {
                "project_id": project_id,
                "node_key": tool_input.get("node_key"),
                "role": tool_input.get("role"),
                "prompt": tool_input.get("prompt"),
                "status": "queued",
                "note": "no issue context",
            }
            await _emit(event_bus, "conductor_tool", {"tool": "dispatch_subagent", **payload})
            return payload

        from app.application.task_completion_registry import TaskCompletionRegistry
        from app.application.task_dispatcher import dispatch_role

        role = str(tool_input.get("role") or "")
        prompt_override = tool_input.get("prompt") or None
        prev_node_key = tool_input.get("prev_node_key") or None
        detail = role or prev_node_key or "subagent"

        issue = await store.load_codex_issue(issue_id)
        if issue is None:
            return {"error": f"Issue {issue_id} not found"}

        # GAP G: bound re-dispatch. Each dispatch of a role adds a graph node
        # (role, role#1, role#2…); past the budget the Conductor is stuck in a
        # rework loop, so return a terminal `retries_exhausted` to stop it from
        # hammering the same role forever.
        if role:
            try:
                graph = await store.load_workflow_graph_for_issue(issue_id)
            except Exception:  # noqa: BLE001
                graph = None
            if graph is not None:
                same_role = sum(
                    1 for n in (graph.nodes or [])
                    if n.node_key == role or n.node_key.startswith(f"{role}#")
                )
                max_dispatches = _max_dispatches_per_role()
                if same_role >= max_dispatches:
                    await _emit(event_bus, "conductor_tool", {
                        "tool": "dispatch_subagent",
                        "role": role,
                        "status": "retries_exhausted",
                        "dispatches": same_role,
                    })
                    return {
                        "status": "retries_exhausted",
                        "role": role,
                        "dispatches": same_role,
                        "max_dispatches": max_dispatches,
                        "note": (
                            f"role '{role}' already dispatched {same_role} times "
                            f"(max {max_dispatches}); do not re-dispatch it"
                        ),
                    }

        try:
            await _notify_status(on_status, "dispatching_subagent", detail)
            task_id, node_id = await dispatch_role(
                issue=issue,
                role=role,
                prompt_override=prompt_override,
                store=store,
                task_dispatcher_fn=task_dispatcher_fn,
                event_bus=event_bus,
                prev_node_key=prev_node_key,
            )
        except ValueError as exc:
            return {"error": str(exc)}

        registry = TaskCompletionRegistry.get()
        registry.register(task_id)
        await _notify_status(on_status, "awaiting_subagent", detail)

        await _emit(event_bus, "conductor_tool", {
            "tool": "dispatch_subagent",
            "role": role,
            "task_id": task_id,
            "status": "dispatched",
        })

        # Activity-aware wait: a slow-but-progressing subagent (e.g. a thorough
        # gpt-5.5 QA pass that streams for >900s) must NOT be abandoned and
        # redispatched — that discards its work. Keep waiting while it shows
        # recent activity; only give up on a genuine stall or the hard ceiling.
        from datetime import datetime
        from app.application import task_activity, timeouts

        def _activity_age(tid: str) -> float | None:
            last = task_activity.last_activity.get(tid)
            return None if last is None else (datetime.now() - last).total_seconds()

        idle_timeout = timeouts.subagent_idle_s()
        hard_timeout = timeouts.subagent_max_s()
        try:
            result = await registry.wait_for_active(
                task_id,
                idle_timeout=idle_timeout,
                hard_timeout=hard_timeout,
                activity_age=_activity_age,
            )
        except TimeoutError:
            return {
                "error": (
                    f"subagent timed out (idle >{idle_timeout:.0f}s or total >{hard_timeout:.0f}s)"
                ),
                "task_id": task_id,
                "role": role,
            }

        return result or {"task_id": task_id, "role": role, "status": "done"}

    async def spawn_custom_subagent(tool_input: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "project_id": project_id,
            "role_key": tool_input.get("role_key"),
            "label": tool_input.get("label"),
            "prompt": tool_input.get("prompt"),
            "status": "registered",
        }
        await _emit(event_bus, "conductor_tool", {"tool": "spawn_custom_subagent", **payload})
        return payload

    async def inject_context_into_node(tool_input: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "project_id": project_id,
            "node_key": tool_input.get("node_key"),
            "context": tool_input.get("context"),
            "status": "accepted",
        }
        await _emit(event_bus, "conductor_tool", {"tool": "inject_context_into_node", **payload})
        return payload

    async def request_user_clarification(tool_input: dict[str, Any]) -> dict[str, Any]:
        await _notify_status(on_status, "awaiting_user_clarification", str(tool_input.get("question") or "").strip() or None)
        payload = {
            "project_id": project_id,
            "question": tool_input.get("question"),
            "status": "waiting_for_user",
        }
        await _emit(event_bus, "conductor_tool", {"tool": "request_user_clarification", **payload})
        return payload

    async def finalize_task(tool_input: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": str(tool_input.get("status") or "done"),
            "answer": str(tool_input.get("answer") or tool_input.get("summary") or ""),
            "summary": str(tool_input.get("summary") or tool_input.get("answer") or ""),
        }

    tools: dict[str, ToolCallable] = {
        "retrieve_cold_memory": retrieve_cold_memory,
        "dispatch_subagent": dispatch_subagent,
        "spawn_custom_subagent": spawn_custom_subagent,
        "inject_context_into_node": inject_context_into_node,
        "request_user_clarification": request_user_clarification,
        "finalize_task": finalize_task,
    }
    return ConductorToolRegistry(definitions=_tool_definitions(), tools=tools)


async def _emit(event_bus, event_type: str, payload: dict[str, Any]) -> None:
    if event_bus is None:
        return
    if hasattr(event_bus, "emit"):
        result = event_bus.emit(event_type, payload)
    elif hasattr(event_bus, "append"):
        result = event_bus.append({"type": event_type, **payload})
    else:
        return
    if hasattr(result, "__await__"):
        await result


async def _notify_status(callback: ToolStatusCallback | None, phase: str, detail: str | None) -> None:
    if callback is None:
        return
    result = callback(phase, detail)
    if hasattr(result, "__await__"):
        await result


def _tool_definitions() -> list[dict[str, Any]]:
    return [
        _tool(
            "retrieve_cold_memory",
            "Search ProjectConductor cold memory for relevant project history.",
            {
                "query": {"type": "string", "description": "Search query."},
                "top_k": {"type": "integer", "description": "Maximum memories to return."},
            },
            ["query"],
        ),
        _tool(
            "dispatch_subagent",
            "Dispatch a workflow sub-agent by role. Waits for completion and returns the result. Available roles: product_manager, architect, engineer, qa. You can also use specialist role keys from the agent catalog.",
            {
                "role": {"type": "string", "description": "Role to dispatch: product_manager, architect, engineer, qa, or a specialist role_key"},
                "prompt": {"type": "string", "description": "Optional focused instruction for this agent run"},
                "prev_node_key": {"type": "string", "description": "node_key of the previously dispatched node, for graph edge visualization"},
            },
            ["role"],
        ),
        _tool(
            "spawn_custom_subagent",
            "Register a custom specialist sub-agent for a project-specific task.",
            {
                "role_key": {"type": "string"},
                "label": {"type": "string"},
                "prompt": {"type": "string"},
            },
            ["role_key", "prompt"],
        ),
        _tool(
            "inject_context_into_node",
            "Inject conductor context into a pending workflow node.",
            {
                "node_key": {"type": "string"},
                "context": {"type": "string"},
            },
            ["node_key", "context"],
        ),
        _tool(
            "request_user_clarification",
            "Ask the user a blocking clarification question.",
            {"question": {"type": "string"}},
            ["question"],
        ),
        _tool(
            "finalize_task",
            "Finish the conductor task with a final answer.",
            {
                "answer": {"type": "string"},
                "summary": {"type": "string"},
                "status": {"type": "string"},
            },
            [],
        ),
    ]


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }
