"""Tool registry for the ProjectConductor loop."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.application.project_conductor import ProjectConductor


ToolCallable = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class ConductorToolRegistry:
    definitions: list[dict[str, Any]]
    tools: dict[str, ToolCallable]


def build_conductor_tools(*, project_id: str, store, event_bus=None) -> ConductorToolRegistry:
    conductor = ProjectConductor(project_id=project_id, store=store, event_bus=event_bus)

    async def retrieve_cold_memory(tool_input: dict[str, Any]) -> dict[str, Any]:
        query = str(tool_input.get("query") or "")
        top_k = int(tool_input.get("top_k") or 3)
        return {"memories": await conductor.retrieve_cold(query, top_k=max(1, min(top_k, 10)))}

    async def dispatch_subagent(tool_input: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "project_id": project_id,
            "node_key": tool_input.get("node_key"),
            "role": tool_input.get("role"),
            "prompt": tool_input.get("prompt"),
            "status": "queued",
        }
        await _emit(event_bus, "conductor_tool", {"tool": "dispatch_subagent", **payload})
        return payload

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
            "Dispatch an existing workflow sub-agent/node with focused instructions.",
            {
                "node_key": {"type": "string"},
                "role": {"type": "string"},
                "prompt": {"type": "string"},
            },
            ["prompt"],
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
