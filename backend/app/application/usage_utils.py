"""Shared utilities for extracting and pricing token usage."""

from __future__ import annotations

from app.application import timeouts
from app.json_safety import object_dict_or_none


def extract_usage(obj: object) -> dict[str, object] | None:
    """Pull the usage dict out of a Codex / Claude stream event payload.

    Codex app server emits shapes like:
      {"type":"assistant","message":{...,"usage":{...}}}
      {"type":"stream_event","event":{"type":"message_delta","usage":{...}}}
    """
    payload = object_dict_or_none(obj)
    if payload is None:
        return None
    usage = object_dict_or_none(payload.get("usage"))
    if usage is not None:
        return usage
    msg = object_dict_or_none(payload.get("message"))
    if msg is not None:
        usage = object_dict_or_none(msg.get("usage"))
        if usage is not None:
            return usage
    event = object_dict_or_none(payload.get("event"))
    if event is not None:
        usage = object_dict_or_none(event.get("usage"))
        if usage is not None:
            return usage
    return None


def extract_message_id(obj: object) -> str | None:
    """Extract message ID from a parsed event object."""
    payload = object_dict_or_none(obj)
    if payload is None:
        return None
    msg = object_dict_or_none(payload.get("message"))
    if msg is not None:
        mid = msg.get("id")
        if isinstance(mid, str):
            return mid
    return None


def read_usage_int(usage: dict[str, object], *names: str) -> int | None:
    """Read the first integer-compatible usage value from a usage payload."""
    for name in names:
        value = _coerce_int(usage.get(name))
        if value is not None:
            return value
    return None


def read_usage_float(usage: dict[str, object], *names: str) -> float | None:
    """Read the first float-compatible usage value from a usage payload."""
    for name in names:
        value = _coerce_float(usage.get(name))
        if value is not None:
            return value
    return None


def _coerce_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float | str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _coerce_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float | str):
        try:
            return float(value)
        except ValueError:
            return None
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
    pricing: object | None = None,
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


def _read_price(pricing: object | None, attr: str) -> float | None:
    """Read a per-million price field from a model config object or dict."""
    if pricing is None:
        return None
    value = pricing.get(attr) if isinstance(pricing, dict) else getattr(pricing, attr, None)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def price_tokens_for_model(
    model: object | None,
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
