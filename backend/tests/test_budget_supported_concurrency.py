"""Budget-aware dispatch_batch concurrency downscaling (cost-aware PR3).

`timeouts.budget_supported_concurrency` derives the EFFECTIVE fan-out from the
remaining budget. It is a coarse, deterministic rule:
  effective = min(configured_cap, floor(remaining / EST_COST_PER_AGENT_USD)),
clamped to at least 1, with unlimited budget leaving the cap untouched and over
budget squeezing to 1. These tests pin the algorithm so the knob stays
explainable.
"""
from __future__ import annotations

import pytest

from app.application import timeouts


def test_unlimited_budget_does_not_downscale():
    # remaining=None signals "no ceiling": cap is returned unchanged.
    assert timeouts.budget_supported_concurrency(None, 3) == 3
    assert timeouts.budget_supported_concurrency(None, 1) == 1


def test_healthy_budget_keeps_configured_cap(monkeypatch):
    monkeypatch.setenv("EST_COST_PER_AGENT_USD", "0.50")
    # remaining 5.0 / 0.5 = 10 supported, clamped down to the configured cap 3.
    assert timeouts.budget_supported_concurrency(5.0, 3) == 3


def test_healthy_small_budget_keeps_configured_cap(monkeypatch):
    monkeypatch.setenv("EST_COST_PER_AGENT_USD", "0.50")
    # A $1 budget with no spend is healthy. It must not shrink a tiny three-way
    # fan-out to two lanes before the soft-warning threshold is reached.
    assert timeouts.budget_supported_concurrency(1.0, 3, soft_warn=False) == 3


def test_tight_budget_downscales(monkeypatch):
    monkeypatch.setenv("EST_COST_PER_AGENT_USD", "0.50")
    # remaining 1.2 / 0.5 = floor(2.4) = 2 < cap 3 -> downscaled to 2.
    assert timeouts.budget_supported_concurrency(1.2, 3, soft_warn=True) == 2
    # remaining 0.9 / 0.5 = floor(1.8) = 1.
    assert timeouts.budget_supported_concurrency(0.9, 3, soft_warn=True) == 1


def test_near_zero_remaining_floors_at_one(monkeypatch):
    monkeypatch.setenv("EST_COST_PER_AGENT_USD", "0.50")
    # Even with no remaining budget the supported concurrency floors at 1: a
    # batch is never made 0-wide (wind-down is steered by prompt/events).
    assert timeouts.budget_supported_concurrency(0.0, 3) == 1
    assert timeouts.budget_supported_concurrency(0.1, 3) == 1


def test_over_budget_squeezes_to_one(monkeypatch):
    monkeypatch.setenv("EST_COST_PER_AGENT_USD", "0.50")
    # over_budget forces the floor regardless of how the division would land.
    assert timeouts.budget_supported_concurrency(0.0, 5, over_budget=True) == 1
    assert timeouts.budget_supported_concurrency(-3.0, 5, over_budget=True) == 1


def test_est_cost_per_agent_env_override(monkeypatch):
    monkeypatch.setenv("EST_COST_PER_AGENT_USD", "1.00")
    # remaining 2.5 / 1.0 = floor(2.5) = 2.
    assert timeouts.budget_supported_concurrency(2.5, 5) == 2


def test_est_cost_per_agent_invalid_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("EST_COST_PER_AGENT_USD", "-1")
    assert timeouts.est_cost_per_agent_usd() == timeouts.DEFAULT_EST_COST_PER_AGENT_USD
    monkeypatch.setenv("EST_COST_PER_AGENT_USD", "garbage")
    assert timeouts.est_cost_per_agent_usd() == timeouts.DEFAULT_EST_COST_PER_AGENT_USD


def test_est_cost_per_agent_invariant_passes_by_default():
    # The new knob must not introduce a spurious invariant violation.
    violations = [v for v in timeouts.check_invariants() if "EST_COST_PER_AGENT_USD" in v]
    assert violations == []
