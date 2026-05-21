"""Anthropic-style ProjectConductor tool-use loop.

This module is intentionally transport-agnostic: tests and API endpoints can
pass any LLM callable that returns Anthropic message-shaped dictionaries.
"""
from __future__ import annotations

import inspect
import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Union


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
