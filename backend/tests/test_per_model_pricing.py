"""Tests for per-model token pricing (PR1 of cost-aware conductor scheduling).

Covers:
- price_tokens with explicit per-model prices (input/output/cache each).
- fallback to global env rates for unpriced / partially-priced models
  (regression: matches legacy price_tokens behavior exactly).
- RuntimeModelConfig price-field serialization round-trip through the JSON store.
"""

import json  # noqa: I001
from pathlib import Path

import pytest

from app.domain.models import (
    RuntimeCatalog,
    RuntimeExecutorConfig,
    RuntimeProviderConfig,
    RuntimeModelConfig,
)
from app.application.usage_utils import price_tokens, price_tokens_for_model
from app.adapters.async_sqlite_store import AsyncSQLiteStore


# --- pricing math ---


def test_price_tokens_uses_explicit_model_prices():
    model = RuntimeModelConfig(
        id="m1",
        label="M1",
        input_usd_per_m=2.0,
        output_usd_per_m=8.0,
        cache_read_usd_per_m=0.5,
    )
    cost = price_tokens(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_tokens=1_000_000,
        pricing=model,
    )
    # 1M each at 2.0 / 8.0 / 0.5 per-M => 10.5
    assert cost == pytest.approx(2.0 + 8.0 + 0.5)


def test_price_tokens_input_rate_isolated():
    model = RuntimeModelConfig(id="m", label="m", input_usd_per_m=3.0)
    cost = price_tokens(input_tokens=2_000_000, pricing=model)
    assert cost == pytest.approx(6.0)


def test_price_tokens_output_rate_isolated(monkeypatch):
    # ensure env output rate is not what's exercised
    monkeypatch.setenv("COST_USD_PER_M_OUTPUT", "99.0")
    model = RuntimeModelConfig(id="m", label="m", output_usd_per_m=4.0)
    cost = price_tokens(output_tokens=500_000, pricing=model)
    assert cost == pytest.approx(2.0)


def test_price_tokens_cache_rate_isolated():
    model = RuntimeModelConfig(id="m", label="m", cache_read_usd_per_m=1.0)
    cost = price_tokens(cache_read_tokens=3_000_000, pricing=model)
    assert cost == pytest.approx(3.0)


def test_price_tokens_for_model_wrapper_matches():
    model = RuntimeModelConfig(
        id="m",
        label="m",
        input_usd_per_m=2.0,
        output_usd_per_m=8.0,
        cache_read_usd_per_m=0.5,
    )
    a = price_tokens_for_model(model, 1000, 2000, 3000)
    b = price_tokens(1000, 2000, 3000, pricing=model)
    assert a == b


# --- fallback / backward compatibility ---


def test_unpriced_model_falls_back_to_env_rates():
    """A model with no prices must equal the legacy global-rate result."""
    model = RuntimeModelConfig(id="m", label="m")  # all prices None
    with_model = price_tokens(1_000, 2_000, 3_000, pricing=model)
    legacy = price_tokens(1_000, 2_000, 3_000)  # no pricing arg = old behavior
    assert with_model == legacy


def test_pricing_none_is_legacy_behavior(monkeypatch):
    monkeypatch.setenv("COST_USD_PER_M_INPUT", "0.30")
    monkeypatch.setenv("COST_USD_PER_M_OUTPUT", "1.20")
    monkeypatch.setenv("COST_USD_PER_M_CACHE_READ", "0.075")
    cost = price_tokens(1_000_000, 1_000_000, 1_000_000)
    assert cost == pytest.approx(0.30 + 1.20 + 0.075)


def test_invalid_global_env_rates_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("COST_USD_PER_M_INPUT", "oops")
    monkeypatch.setenv("COST_USD_PER_M_OUTPUT", "oops")
    monkeypatch.setenv("COST_USD_PER_M_CACHE_READ", "oops")

    cost = price_tokens(1_000_000, 1_000_000, 1_000_000)

    assert cost == pytest.approx(0.30 + 1.20 + 0.075)


def test_partial_model_prices_mix_with_env_fallback(monkeypatch):
    """Only input priced explicitly; output/cache fall back to env."""
    monkeypatch.setenv("COST_USD_PER_M_OUTPUT", "1.20")
    monkeypatch.setenv("COST_USD_PER_M_CACHE_READ", "0.075")
    model = RuntimeModelConfig(id="m", label="m", input_usd_per_m=5.0)
    cost = price_tokens(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_tokens=1_000_000,
        pricing=model,
    )
    # input from model (5.0), output+cache from env
    assert cost == pytest.approx(5.0 + 1.20 + 0.075)


def test_dict_pricing_supported():
    cost = price_tokens(
        input_tokens=1_000_000,
        pricing={"input_usd_per_m": 7.0},
    )
    assert cost == pytest.approx(7.0)


# --- pricing-arg robustness (must never raise; fall back to env) ---


def test_dict_missing_key_falls_back_to_env():
    """A dict without the requested rate key falls back to env, not a crash."""
    cost = price_tokens(input_tokens=1_000_000, pricing={"output_usd_per_m": 9.0})
    legacy = price_tokens(input_tokens=1_000_000)
    assert cost == legacy


def test_empty_model_config_falls_back_to_env():
    """An empty (all-None) RuntimeModelConfig equals the legacy result."""
    model = RuntimeModelConfig(id="x", label="x")
    assert price_tokens(1_000, 2_000, 3_000, pricing=model) == price_tokens(1_000, 2_000, 3_000)


def test_object_without_price_attrs_falls_back_to_env():
    """An arbitrary object lacking the price attrs must not raise."""

    class Bare:
        pass

    cost = price_tokens(1_000, 2_000, 3_000, pricing=Bare())
    assert cost == price_tokens(1_000, 2_000, 3_000)


def test_non_numeric_price_value_falls_back_to_env():
    """A garbage (non-numeric) price value falls back rather than crashing."""
    cost = price_tokens(input_tokens=1_000_000, pricing={"input_usd_per_m": "oops"})
    assert cost == price_tokens(input_tokens=1_000_000)


def test_empty_dict_pricing_falls_back_to_env():
    cost = price_tokens(1_000, 2_000, 3_000, pricing={})
    assert cost == price_tokens(1_000, 2_000, 3_000)


# --- catalog serialization round-trip ---


@pytest.fixture
async def store():
    store = AsyncSQLiteStore(Path(":memory:"))
    await store._init_db()
    try:
        yield store
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_catalog_price_fields_round_trip(store):
    catalog = RuntimeCatalog(
        executors=[
            RuntimeExecutorConfig(
                id="claude",
                label="Claude",
                executor_type="claude",
                providers=[
                    RuntimeProviderConfig(
                        id="anthropic",
                        label="Anthropic",
                        models=[
                            RuntimeModelConfig(
                                id="sonnet",
                                label="Sonnet",
                                input_usd_per_m=3.0,
                                output_usd_per_m=15.0,
                                cache_read_usd_per_m=0.3,
                            ),
                            RuntimeModelConfig(id="haiku", label="Haiku"),  # no prices
                        ],
                    )
                ],
            )
        ]
    )
    await store.save_runtime_catalog(catalog)
    loaded = await store.load_runtime_catalog()
    assert loaded is not None
    models = loaded.executors[0].providers[0].models
    sonnet = next(m for m in models if m.id == "sonnet")
    haiku = next(m for m in models if m.id == "haiku")
    assert sonnet.input_usd_per_m == 3.0
    assert sonnet.output_usd_per_m == 15.0
    assert sonnet.cache_read_usd_per_m == 0.3
    assert haiku.input_usd_per_m is None
    assert haiku.output_usd_per_m is None
    assert haiku.cache_read_usd_per_m is None


def test_model_dump_includes_price_fields():
    model = RuntimeModelConfig(id="m", label="m", input_usd_per_m=1.5)
    dumped = model.model_dump()
    assert dumped["input_usd_per_m"] == 1.5
    assert dumped["output_usd_per_m"] is None
    # round-trip via JSON
    reparsed = RuntimeModelConfig(**json.loads(json.dumps(dumped)))
    assert reparsed.input_usd_per_m == 1.5


# --- public GET serialization whitelist carries price fields ---


@pytest.mark.slow
def test_public_runtime_catalog_get_exposes_price_fields(client):
    """The _public_runtime_catalog whitelist must surface the new price fields
    on GET; nothing downstream may strip them."""
    resp = client.put(
        "/api/runtime-catalog",
        json={
            "catalog": {
                "executors": [
                    {
                        "id": "claude",
                        "label": "Claude",
                        "enabled": True,
                        "executor_type": "claude",
                        "providers": [
                            {
                                "id": "anthropic",
                                "label": "Anthropic",
                                "enabled": True,
                                "models": [
                                    {
                                        "id": "sonnet",
                                        "label": "Sonnet",
                                        "enabled": True,
                                        "input_usd_per_m": 3.0,
                                        "output_usd_per_m": 15.0,
                                        "cache_read_usd_per_m": 0.3,
                                    },
                                    {"id": "haiku", "label": "Haiku", "enabled": True},
                                ],
                                "default_model_id": "sonnet",
                            }
                        ],
                        "default_provider_id": "anthropic",
                    }
                ]
            }
        },
    )
    assert resp.status_code == 200

    body = client.get("/api/runtime-catalog").json()
    models = body["executors"][0]["providers"][0]["models"]
    sonnet = next(m for m in models if m["id"] == "sonnet")
    haiku = next(m for m in models if m["id"] == "haiku")
    assert sonnet["input_usd_per_m"] == 3.0
    assert sonnet["output_usd_per_m"] == 15.0
    assert sonnet["cache_read_usd_per_m"] == 0.3
    # unpriced model still exposes the keys (as null), so UI can render "no price"
    assert haiku["input_usd_per_m"] is None
    assert haiku["output_usd_per_m"] is None
    assert haiku["cache_read_usd_per_m"] is None
