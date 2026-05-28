"""Shared utilities for extracting and pricing token usage."""
import os


def extract_usage(obj) -> dict | None:
    """Pull the usage dict out of a Codex / Claude stream event payload.

    Codex app server emits shapes like:
      {"type":"assistant","message":{...,"usage":{...}}}
      {"type":"stream_event","event":{"type":"message_delta","usage":{...}}}
    """
    if not isinstance(obj, dict):
        return None
    if isinstance(obj.get("usage"), dict):
        return obj["usage"]
    msg = obj.get("message")
    if isinstance(msg, dict) and isinstance(msg.get("usage"), dict):
        return msg["usage"]
    event = obj.get("event")
    if isinstance(event, dict) and isinstance(event.get("usage"), dict):
        return event["usage"]
    return None


def extract_message_id(obj) -> str | None:
    """Extract message ID from a parsed event object."""
    if not isinstance(obj, dict):
        return None
    msg = obj.get("message")
    if isinstance(msg, dict):
        mid = msg.get("id")
        if isinstance(mid, str):
            return mid
    return None


def price_tokens(input_tokens: int | None = None, output_tokens: int | None = None, cache_read_tokens: int | None = None) -> float:
    """Compute the USD cost of token usage.

    Reads env vars:
      COST_USD_PER_M_INPUT (default "0.30")
      COST_USD_PER_M_OUTPUT (default "1.20")
      COST_USD_PER_M_CACHE_READ (default "0.075")
    """
    input_per_m = float(os.getenv("COST_USD_PER_M_INPUT", "0.30"))
    output_per_m = float(os.getenv("COST_USD_PER_M_OUTPUT", "1.20"))
    cache_per_m = float(os.getenv("COST_USD_PER_M_CACHE_READ", "0.075"))

    cost = 0.0
    if input_tokens is not None and input_tokens > 0:
        cost += (input_tokens / 1_000_000) * input_per_m
    if output_tokens is not None and output_tokens > 0:
        cost += (output_tokens / 1_000_000) * output_per_m
    if cache_read_tokens is not None and cache_read_tokens > 0:
        cost += (cache_read_tokens / 1_000_000) * cache_per_m

    return cost
