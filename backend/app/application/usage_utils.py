from __future__ import annotations

"""Shared utilities for extracting and pricing token usage."""

from typing import Any, cast

from app.application import timeouts


def extract_usage(obj: Any) -> dict[str, Any] | None:
    """Pull the usage dict out of a Codex / Claude stream event payload.

    Codex app server emits shapes like:
      {"type":"assistant","message":{...,"usage":{...}}}
      {"type":"stream_event","event":{"type":"message_delta","usage":{...}}}
    """
    if not isinstance(obj, dict):
        return None
    if isinstance(obj.get("usage"), dict):
        return cast(dict[str, Any], obj["usage"])
    msg = obj.get("message")
    if isinstance(msg, dict) and isinstance(msg.get("usage"), dict):
        return cast(dict[str, Any], msg["usage"])
    event = obj.get("event")
    if isinstance(event, dict) and isinstance(event.get("usage"), dict):
        return cast(dict[str, Any], event["usage"])
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


def _env_rates() -> tuple[float, float, float]:
    """Global flat per-million-tokens USD rates from env (the legacy fallback)."""
    return (
        timeouts.cost_usd_per_m_input(),
        timeouts.cost_usd_per_m_output(),
        timeouts.cost_usd_per_m_cache_read(),
    )


def price_tokens(
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_read_tokens: int | None = None,
    pricing=None,
) -> float:
    """Compute the USD cost of token usage.

    Model-aware: when ``pricing`` is supplied (a ``RuntimeModelConfig`` or any
    object/dict exposing ``input_usd_per_m`` / ``output_usd_per_m`` /
    ``cache_read_usd_per_m``), each per-token rate uses the model's explicit
    price when set; any rate left ``None`` falls back to the global flat env
    rate below — so partially-priced models still work and unpriced models /
    ``pricing=None`` behave exactly like the legacy global-rate path.

    Env fallback rates:
      COST_USD_PER_M_INPUT (default "0.30")
      COST_USD_PER_M_OUTPUT (default "1.20")
      COST_USD_PER_M_CACHE_READ (default "0.075")
    """
    env_input, env_output, env_cache = _env_rates()

    model_input = _read_price(pricing, "input_usd_per_m")
    model_output = _read_price(pricing, "output_usd_per_m")
    model_cache = _read_price(pricing, "cache_read_usd_per_m")

    input_per_m = model_input if model_input is not None else env_input
    output_per_m = model_output if model_output is not None else env_output
    cache_per_m = model_cache if model_cache is not None else env_cache

    cost = 0.0
    if input_tokens is not None and input_tokens > 0:
        cost += (input_tokens / 1_000_000) * input_per_m
    if output_tokens is not None and output_tokens > 0:
        cost += (output_tokens / 1_000_000) * output_per_m
    if cache_read_tokens is not None and cache_read_tokens > 0:
        cost += (cache_read_tokens / 1_000_000) * cache_per_m

    return cost


def _read_price(pricing, attr: str) -> float | None:
    """Read a per-million price field from a model config object or dict."""
    if pricing is None:
        return None
    if isinstance(pricing, dict):  # noqa: SIM108
        value = pricing.get(attr)
    else:
        value = getattr(pricing, attr, None)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def price_tokens_for_model(
    model,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_read_tokens: int | None = None,
) -> float:
    """Convenience wrapper to price usage against a model's catalog pricing.

    ``model`` is a ``RuntimeModelConfig`` (or dict/None). Missing per-rate
    prices fall back to the global env rates via :func:`price_tokens`.
    """
    return price_tokens(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        pricing=model,
    )
