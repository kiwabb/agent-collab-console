from __future__ import annotations

from typing import TypedDict


class HelpRequestEvent(TypedDict):
    source_executor: str
    target_executor: str
    title: str
    prompt: str
    context_summary: object | None


def _string_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def parse_help_request_event(
    payload: dict[str, object], *, executor: str
) -> HelpRequestEvent | None:
    payload = dict(payload)
    if payload.get("type") == "request_help":
        tool_input = payload
    else:
        tool_name = payload.get("tool_name") or payload.get("tool")
        if str(tool_name or "").strip().lower().replace("-", "_") != "request_help":
            return None
        tool_input = _string_dict(payload.get("input") or payload.get("payload"))

    if tool_input.get("blocking") is not True:
        return None

    target_executor = tool_input.get("target")
    title = tool_input.get("title")
    prompt = tool_input.get("prompt")
    if not (
        isinstance(target_executor, str)
        and isinstance(title, str)
        and isinstance(prompt, str)
        and target_executor
        and title
        and prompt
    ):
        return None

    return {
        "source_executor": executor,
        "target_executor": target_executor,
        "title": title,
        "prompt": prompt,
        "context_summary": tool_input.get("context_summary"),
    }
