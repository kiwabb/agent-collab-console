"""Budget-driven steering: candidate-model injection + soft-warn / wind-down (PR3).

These exercise budget_service in isolation: candidate model prices are flattened
and sorted cheap→expensive, the COST / BUDGET block escalates tone at the
soft-warn threshold and over budget, and a structured steering event is produced
for observability (only when it matters).
"""

from __future__ import annotations

import pytest  # noqa: F401

from app.application.budget_service import (
    IssueBudgetStatus,
    budget_steering_event,
    collect_candidate_model_prices,
    render_budget_summary,
)
from app.domain.models import (
    RuntimeCatalog,
    RuntimeExecutorConfig,
    RuntimeModelConfig,
    RuntimeProviderConfig,
)


def _catalog() -> RuntimeCatalog:
    return RuntimeCatalog(
        executors=[
            RuntimeExecutorConfig(
                id="claude",
                label="Claude",
                providers=[
                    RuntimeProviderConfig(
                        id="anthropic",
                        label="Anthropic",
                        models=[
                            RuntimeModelConfig(
                                id="opus",
                                label="Opus",
                                input_usd_per_m=15.0,
                                output_usd_per_m=75.0,
                            ),
                            RuntimeModelConfig(
                                id="haiku",
                                label="Haiku",
                                input_usd_per_m=0.80,
                                output_usd_per_m=4.0,
                            ),
                            RuntimeModelConfig(
                                id="sonnet",
                                label="Sonnet",
                                input_usd_per_m=3.0,
                                output_usd_per_m=15.0,
                            ),
                            # Disabled model must be excluded.
                            RuntimeModelConfig(
                                id="legacy",
                                label="Legacy",
                                enabled=False,
                                input_usd_per_m=0.1,
                                output_usd_per_m=0.1,
                            ),
                        ],
                    ),
                    # Unpriced model: falls back to env, sorts last.
                    RuntimeProviderConfig(
                        id="custom",
                        label="Custom",
                        models=[RuntimeModelConfig(id="mystery", label="Mystery")],
                    ),
                ],
            ),
            # Disabled executor: all its models excluded.
            RuntimeExecutorConfig(
                id="codex",
                label="Codex",
                enabled=False,
                executor_type="codex",
                providers=[
                    RuntimeProviderConfig(
                        id="openai",
                        label="OpenAI",
                        models=[RuntimeModelConfig(id="x", label="X", output_usd_per_m=0.01)],
                    )
                ],
            ),
        ]
    )


def _status(spent: float, budget: float, *, warn_ratio: float = 0.8) -> IssueBudgetStatus:
    return IssueBudgetStatus(
        issue_id="issue-1",
        spent_usd=spent,
        budget_usd=budget,
        budget_source="issue",
        soft_warn_ratio=warn_ratio,
    )


# --- Candidate model collection / ordering ---------------------------------


def test_candidates_sorted_cheapest_first_disabled_excluded():
    cands = collect_candidate_model_prices(_catalog())
    ids = [c.model_id for c in cands]
    # Disabled model + disabled executor are excluded.
    assert "legacy" not in ids
    assert "x" not in ids
    # Cheap → expensive by output price; unpriced (env) sorts last.
    assert ids == ["haiku", "sonnet", "opus", "mystery"]


def test_candidates_none_catalog_is_empty():
    assert collect_candidate_model_prices(None) == []


def test_candidate_prices_injected_and_sorted_in_block():
    cands = collect_candidate_model_prices(_catalog())
    text = render_budget_summary(_status(1.0, 10.0), cands)
    assert "Candidate models" in text
    # The unit prices appear in the injected text.
    assert "$0.8000" in text  # haiku input
    assert "$75.0000" in text  # opus output
    # Cheapest model line comes before the most expensive in the rendered block.
    assert text.index("haiku") < text.index("opus")
    # Unpriced model renders its rates as the env-fallback marker.
    assert "mystery" in text
    assert "env" in text


# --- Soft-warn / wind-down tone --------------------------------------------


def test_healthy_budget_allows_expensive_models():
    text = render_budget_summary(_status(1.0, 10.0), [])
    assert "Budget is healthy" in text
    assert "BUDGET WARNING" not in text
    assert "OVER BUDGET" not in text


def test_soft_warn_threshold_escalates_to_warning():
    # 8.5 / 10 = 85% >= 80% soft-warn but < 100% (not over budget).
    text = render_budget_summary(_status(8.5, 10.0), [])
    assert "BUDGET WARNING" in text
    assert "cheaper models" in text
    assert "OVER BUDGET" not in text


def test_over_budget_escalates_to_wind_down():
    text = render_budget_summary(_status(11.0, 10.0), [])
    assert "OVER BUDGET" in text
    assert "WIND DOWN" in text
    assert "finalize_task" in text


def test_unlimited_budget_has_no_warning():
    text = render_budget_summary(_status(999.0, 0.0), [])
    assert "unlimited" in text
    assert "BUDGET WARNING" not in text
    assert "OVER BUDGET" not in text


# --- Steering event --------------------------------------------------------


def test_steering_event_none_when_healthy():
    assert budget_steering_event(_status(1.0, 10.0)) is None


def test_steering_event_none_when_unlimited():
    assert budget_steering_event(_status(999.0, 0.0)) is None


def test_steering_event_budget_warning():
    evt = budget_steering_event(_status(8.5, 10.0))
    assert evt is not None
    assert evt["type"] == "budget_warning"
    assert evt["issue_id"] == "issue-1"
    assert evt["spent_usd"] == 8.5
    assert evt["budget_usd"] == 10.0
    assert evt["soft_warn_ratio"] == 0.8


def test_steering_event_budget_exceeded():
    evt = budget_steering_event(_status(12.0, 10.0))
    assert evt is not None
    assert evt["type"] == "budget_exceeded"
    assert evt["remaining_usd"] == -2.0
