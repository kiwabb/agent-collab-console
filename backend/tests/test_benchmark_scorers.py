"""Tests for the scorer registry + the two PR1 scorers (execution, coverage).

These tests pin the determinism contract: given a fixed
``IssueArtifacts`` value, the scorers always return the same
``Score``. The PR2 runner relies on this property to assert
"regression" without flakiness.
"""
from __future__ import annotations

import pytest

from benchmark.scorers import Scorer, ScorerEntry, ScorerRegistry
from benchmark.scorers_impl import (
    AcceptanceCoverageScorer,
    ExecutionScorer,
    _criterion_covered,
    _meaningful_tokens,
    default_registry,
)
from benchmark.types import (
    CommandResult,
    IssueArtifacts,
    Score,
    aggregate_weighted,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _artifacts(
    *,
    issue_id: str = "i-1",
    criteria: list[str] | None = None,
    qa_results: list[CommandResult] | None = None,
    tasks: list[str] | None = None,
) -> IssueArtifacts:
    return IssueArtifacts(
        issue_id=issue_id,
        prd_acceptance_criteria=criteria or [],
        qa_results=qa_results or [],
        completed_engineer_tasks=tasks or [],
    )


# ---------------------------------------------------------------------------
# ExecutionScorer
# ---------------------------------------------------------------------------


def test_execution_all_pass_returns_1_and_passed_true():
    artifacts = _artifacts(
        qa_results=[
            CommandResult(command="a", exit_code=0, duration_s=0.1),
            CommandResult(command="b", exit_code=0, duration_s=0.2),
        ]
    )
    s = ExecutionScorer().score(artifacts)
    assert s.value == 1.0
    assert s.passed is True
    assert s.metadata == {"passed": 2, "total": 2, "failed": []}


def test_execution_one_fail_decreases_value_and_passes_false():
    artifacts = _artifacts(
        qa_results=[
            CommandResult(command="a", exit_code=0, duration_s=0.1),
            CommandResult(command="b", exit_code=2, duration_s=0.2),
        ]
    )
    s = ExecutionScorer().score(artifacts)
    assert s.value == 0.5
    assert s.passed is False
    assert s.metadata["passed"] == 1
    assert s.metadata["total"] == 2
    assert len(s.metadata["failed"]) == 1
    assert s.metadata["failed"][0]["command"] == "b"
    assert s.notes == "1/2 QA commands passed"


def test_execution_all_fail_returns_0_and_passed_false():
    artifacts = _artifacts(
        qa_results=[
            CommandResult(command="a", exit_code=1, duration_s=0.1),
            CommandResult(command="b", exit_code=2, duration_s=0.2),
        ]
    )
    s = ExecutionScorer().score(artifacts)
    assert s.value == 0.0
    assert s.passed is False


def test_execution_no_results_treated_as_failure():
    """An empty qa_results list means the agent never reached QA — that's
    a failure, not a neutral 0.5 or a 'pass by default'."""
    s = ExecutionScorer().score(_artifacts(qa_results=[]))
    assert s.value == 0.0
    assert s.passed is False
    assert s.metadata == {"reason": "no_qa_results"}


def test_execution_does_not_count_expected_nonzero_as_pass():
    """The scorer is intentionally simple: exit_code == 0 is pass.
    A pinned command with expected_exit_code=2 that returns 2 is
    STILL scored as failure here. The match-with-expected logic is
    the runner's job (PR2); PR1 just provides the raw pass-rate."""
    artifacts = _artifacts(
        qa_results=[CommandResult(command="a", exit_code=2, duration_s=0.1)]
    )
    s = ExecutionScorer().score(artifacts)
    assert s.value == 0.0
    assert s.passed is False


# ---------------------------------------------------------------------------
# _meaningful_tokens
# ---------------------------------------------------------------------------


def test_meaningful_tokens_lowercases_and_dedupes():
    assert _meaningful_tokens("Backend API endpoint") == {"backend", "api", "endpoint"}


def test_meaningful_tokens_drops_stopwords_and_short_tokens():
    # "a", "the", "is" are stopwords; "x" is too short.
    assert _meaningful_tokens("A the is x backend") == {"backend"}


def test_meaningful_tokens_alphanumeric_only():
    # Punctuation and unicode are stripped.
    assert _meaningful_tokens("foo, bar! baz?") == {"foo", "bar", "baz"}


# ---------------------------------------------------------------------------
# _criterion_covered
# ---------------------------------------------------------------------------


def test_criterion_covered_full_overlap():
    assert _criterion_covered("add the echo endpoint", "Add Echo Endpoint Backend") is True


def test_criterion_covered_partial_overlap_above_threshold():
    # "budget" "meter" "state" → 3 tokens, "budget" + "meter" hit = 2/3 = 67% > 50%
    assert _criterion_covered("budget meter state derivation", "budget meter rendering") is True


def test_criterion_covered_partial_overlap_below_threshold():
    # 4 tokens, only 1 hit = 25% < 50%
    assert (
        _criterion_covered(
            "budget meter state derivation helper",
            "helper class for budget",
        )
        is False
    )


def test_criterion_covered_single_token_passes_when_present():
    assert _criterion_covered("ping", "ping the endpoint") is True


def test_criterion_covered_single_token_absent_fails():
    assert _criterion_covered("ping", "pong the endpoint") is False


def test_criterion_covered_empty_titles_fails():
    assert _criterion_covered("any criterion here", "") is False


# ---------------------------------------------------------------------------
# AcceptanceCoverageScorer
# ---------------------------------------------------------------------------


def test_coverage_all_criteria_covered():
    artifacts = _artifacts(
        criteria=["add the echo endpoint", "return application json"],
        tasks=["Added the echo endpoint", "Returns application/json content type"],
    )
    s = AcceptanceCoverageScorer().score(artifacts)
    assert s.value == 1.0
    assert s.passed is True
    assert s.metadata == {"covered": 2, "total": 2, "uncovered": []}


def test_coverage_partial_coverage_reflects_in_value():
    artifacts = _artifacts(
        criteria=["add the echo endpoint", "return application json", "log latency"],
        tasks=["Added the echo endpoint"],
    )
    s = AcceptanceCoverageScorer().score(artifacts)
    assert s.value == pytest.approx(1 / 3)
    assert s.passed is False
    assert s.metadata["covered"] == 1
    assert s.metadata["total"] == 3
    assert "return application json" in s.metadata["uncovered"][0]


def test_coverage_none_covered_returns_zero():
    artifacts = _artifacts(
        criteria=["add the echo endpoint", "return application json"],
        tasks=["unrelated work done elsewhere"],
    )
    s = AcceptanceCoverageScorer().score(artifacts)
    assert s.value == 0.0
    assert s.passed is False


def test_coverage_no_criteria_is_trivially_passing():
    """Defensive: the schema's min_length=1 should prevent this, but the
    scorer is also resilient to an empty criteria list."""
    artifacts = _artifacts(criteria=[], tasks=["anything"])
    s = AcceptanceCoverageScorer().score(artifacts)
    assert s.value == 1.0
    assert s.passed is True
    assert s.metadata == {"reason": "no_acceptance_criteria"}


# ---------------------------------------------------------------------------
# Determinism — same input, same output, every time
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "artifacts",
    [
        _artifacts(
            qa_results=[CommandResult(command="x", exit_code=0, duration_s=0.1)],
        ),
        _artifacts(
            qa_results=[
                CommandResult(command="x", exit_code=0, duration_s=0.1),
                CommandResult(command="y", exit_code=1, duration_s=0.1),
            ],
        ),
        _artifacts(
            criteria=["a", "b", "c"],
            tasks=["a", "b"],
        ),
        _artifacts(
            criteria=["a", "b"],
            tasks=[],
        ),
    ],
)
def test_scorers_are_deterministic(artifacts):
    """The same IssueArtifacts must always produce the same Score.

    This is the methodology contract. If a future scorer introduces
    randomness (e.g. LLM-as-judge in PR3), wrap it in epochs + a
    reducer rather than letting the raw scorer be non-deterministic.
    """
    exe = ExecutionScorer().score(artifacts)
    cov = AcceptanceCoverageScorer().score(artifacts)
    # Call the scorers repeatedly; the values must match.
    for _ in range(5):
        assert ExecutionScorer().score(artifacts) == exe
        assert AcceptanceCoverageScorer().score(artifacts) == cov


# ---------------------------------------------------------------------------
# aggregate_weighted
# ---------------------------------------------------------------------------


def test_aggregate_weighted_basic():
    scores = {
        "execution": Score(value=1.0, passed=True),
        "coverage": Score(value=0.5, passed=False),
    }
    weights = {"execution": 1.0, "coverage": 0.3}
    # 1.0 * 1.0 + 0.5 * 0.3 / (1.0 + 0.3) = 1.15 / 1.3 ≈ 0.8846
    assert aggregate_weighted(scores, weights) == pytest.approx(1.15 / 1.3)


def test_aggregate_weighted_drops_missing_scorer_silently():
    scores = {"execution": Score(value=1.0, passed=True)}
    weights = {"execution": 1.0, "coverage": 0.3}  # coverage missing
    # Only execution counts: 1.0 * 1.0 / 1.0 = 1.0
    assert aggregate_weighted(scores, weights) == pytest.approx(1.0)


def test_aggregate_weighted_no_weights_returns_zero():
    assert aggregate_weighted({}, {}) == 0.0


def test_aggregate_weighted_all_weights_zero_returns_zero():
    scores = {"execution": Score(value=1.0, passed=True)}
    assert aggregate_weighted(scores, {"execution": 0.0}) == 0.0


# ---------------------------------------------------------------------------
# ScorerRegistry
# ---------------------------------------------------------------------------


def test_registry_register_and_get():
    reg = ScorerRegistry()
    reg.register(ExecutionScorer())
    assert isinstance(reg.get("execution").scorer, ExecutionScorer)
    assert "execution" in reg
    assert len(reg) == 1


def test_registry_all_returns_in_registration_order():
    reg = ScorerRegistry()
    reg.register(ExecutionScorer())
    reg.register(AcceptanceCoverageScorer())
    assert [e.scorer.name for e in reg.all()] == ["execution", "coverage"]


def test_registry_weight_override():
    reg = ScorerRegistry()
    reg.register(ExecutionScorer(), weight=2.0)
    assert reg.weights() == {"execution": 2.0}


def test_registry_empty_name_rejected():
    class Nameless:
        name = ""
        weight = 1.0

        def score(self, artifacts: IssueArtifacts) -> Score:
            return Score(value=0.0, passed=False)

    reg = ScorerRegistry()
    with pytest.raises(ValueError):
        reg.register(Nameless())  # type: ignore[arg-type]


def test_registry_negative_weight_rejected():
    reg = ScorerRegistry()
    with pytest.raises(ValueError):
        reg.register(ExecutionScorer(), weight=-1.0)


def test_registry_missing_key_raises():
    reg = ScorerRegistry()
    with pytest.raises(KeyError):
        reg.get("nope")


def test_registry_score_runs_all_scorers():
    reg = default_registry()
    artifacts = _artifacts(
        qa_results=[CommandResult(command="x", exit_code=0, duration_s=0.1)],
        criteria=["budget endpoint"],
        tasks=["budget endpoint added"],
    )
    out = reg.score(artifacts)
    assert set(out) == {"execution", "coverage"}
    assert out["execution"].value == 1.0
    assert out["coverage"].value == 1.0


def test_default_registry_has_expected_scorers():
    reg = default_registry()
    assert "execution" in reg
    assert "coverage" in reg
    assert reg.weights() == {"execution": 1.0, "coverage": 0.3}


# ---------------------------------------------------------------------------
# Scorer protocol runtime check
# ---------------------------------------------------------------------------


def test_execution_scorer_satisfies_protocol():
    """The runtime_checkable Protocol lets us assert the contract on
    plain classes without explicit inheritance."""
    assert isinstance(ExecutionScorer(), Scorer)
    assert isinstance(AcceptanceCoverageScorer(), Scorer)
