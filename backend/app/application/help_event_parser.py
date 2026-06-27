from __future__ import annotations


def parse_help_request_event(payload: dict, *, executor: str) -> dict | None:
    payload = dict(payload)
    if payload.get("type") == "request_help":
        tool_input = payload
    else:
        tool_name = payload.get("tool_name") or payload.get("tool")
        if str(tool_name or "").strip().lower().replace("-", "_") != "request_help":
            return None
        tool_input = payload.get("input") or payload.get("payload") or {}

    if tool_input.get("blocking") is not True:
        return None

    target_executor = tool_input.get("target")
    title = tool_input.get("title")
    prompt = tool_input.get("prompt")
    if not target_executor or not title or not prompt:
        return None

    return {
        "source_executor": executor,
        "target_executor": target_executor,
        "title": title,
        "prompt": prompt,
        "context_summary": tool_input.get("context_summary"),
    }
