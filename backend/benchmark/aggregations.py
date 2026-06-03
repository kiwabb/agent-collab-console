"""Statistical aggregation for benchmark runs.

This module turns the raw per-epoch "did the issue pass?" booleans
into the standard evaluation metrics (pass@k from HumanEval, stderr,
per-fixture and aggregate resolve-rate). All functions are pure —
they do not touch the store, the runner, or any IO.

The math follows the conventions from the task
``research/eval-methodology.md``:

  - **pass@1** is the unbiased estimator from the HumanEval paper
    (Chen et al., 2021, arXiv:2107.03374). With ``n`` samples and
    ``c`` correct, ``pass@1 = c / n``. The combinatorial form
    ``pass@k = 1 - C(n-c, k) / C(n, k)`` is the unbiased estimator
    for the probability that at least one of ``k`` random draws
    passes; we use it for ``k > 1`` when the runner reports
    ``k`` (the test-budget parameter, not the per-fixture epoch count).

  - **Aggregate resolve-rate** is the unweighted mean of per-fixture
    pass@1 across the fixture set. Per-fixture variance is high
    (each fixture's pass rate is itself a noisy estimate), so the
    aggregate carries a stderr / confidence interval.

  - **stderr** is ``std / sqrt(N_fixtures)`` with the sample
    standard deviation. This is the standard error of the mean; it
    lets the runner answer "is the candidate's resolve rate
    *significantly* different from the baseline's?" with a simple
    delta-vs-2σ rule (per the task ADR: regression = drop beyond
    stderr, never byte-equality).

  - **Cost** aggregates use simple sums (total spend across all
    epochs); per-fixture cost is the mean across epochs. The runner
    reads cost/tokens from the existing ``ExecutionProcess`` ledger
    via the executor; this module only does the math.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Iterable


# ---------------------------------------------------------------------------
# pass@k — unbiased HumanEval estimator
# ---------------------------------------------------------------------------


def _comb(n: int, k: int) -> float:
    """``C(n, k)`` as a float. Returns 0.0 when ``k > n`` (the standard
    convention for the empty case; ``C(n-c, k) / C(n, k) = 0`` when
    there are not enough failures to form a k-subset)."""
    if k < 0 or n < 0:
        raise ValueError(f"C(n, k) requires n,k >= 0; got n={n}, k={k}")
    if k > n:
        return 0.0
    if k == 0 or k == n:
        return 1.0
    # Use float math directly; n is small (epochs <= a few dozen).
    return math.comb(n, k)


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased HumanEval pass@k estimator.

    Args:
        n: total samples drawn for this task.
        c: number of samples that passed.
        k: target ("probability that at least one of k random draws
            passes"). For pass@1 this is just ``c / n``.

    Returns:
        A float in ``[0.0, 1.0]``. Returns 0.0 when ``n == 0`` (no
        samples, no signal) and 1.0 when ``c == n`` (all passed) and
        ``k == 0`` (asking "what's the probability that 0 draws
        pass" is 1.0 by convention; we treat ``k == 0`` as
        ill-defined and return 1.0 to keep callers off the NaN path).

    Notes:
        The formula is the standard HumanEval estimator
        ``1 - C(n-c, k) / C(n, k)``. It avoids the high variance of
        the naive ``1 - (1 - c/n)**k`` form and is the
        industry-standard reference (Inspect's ``pass_at_{k}``
        reducer uses the same formula).
    """
    if n < 0 or c < 0 or k < 0:
        raise ValueError(f"n, c, k must be non-negative; got n={n}, c={c}, k={k}")
    if n == 0:
        return 0.0
    if c < 0 or c > n:
        raise ValueError(f"c must satisfy 0 <= c <= n; got c={c}, n={n}")
    if k == 0:
        return 1.0
    if k > n:
        # Asking for a draw larger than the sample. The combinatorial
        # form collapses to 0 here ("can't draw k failures from n-c if
        # k > n-c") which means "probability of 0 successes in k draws
        # is 1" → pass@k = 0. Mirror the standard convention.
        return 0.0
    return 1.0 - _comb(n - c, k) / _comb(n, k)


# ---------------------------------------------------------------------------
# Aggregation result types
# ---------------------------------------------------------------------------


@dataclass
class FixtureStats:
    """Per-fixture statistics across the N epochs of one run."""

    fixture_id: str
    n_epochs: int
    n_passed: int
    pass_at_1: float
    pass_at_k_by_k: dict[int, float] = field(default_factory=dict)

    @property
    def pass_rate(self) -> float:
        """Alias of pass@1; the conventional name on SWE-bench-style
        leaderboards."""
        return self.pass_at_1


@dataclass
class RunAggregate:
    """Aggregate statistics for one full run (all fixtures, all epochs)."""

    fixtures: list[FixtureStats]
    total_epochs: int
    total_passed: int
    aggregate_pass_at_1: float
    aggregate_pass_at_1_stderr: float
    cost_total_usd: float = 0.0
    cost_per_issue_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_duration_s: float = 0.0
    # Per-fixture cost means (for the score×cost frontier).
    cost_per_fixture: dict[str, float] = field(default_factory=dict)

    @property
    def resolve_rate(self) -> float:
        """Alias of aggregate_pass_at_1; matches the SWE-bench
        leaderboard terminology used in the task PRD."""
        return self.aggregate_pass_at_1


# ---------------------------------------------------------------------------
# Aggregation entry points
# ---------------------------------------------------------------------------


def per_fixture(
    epochs: Iterable[tuple[str, bool]],
    *,
    k: int = 1,
) -> list[FixtureStats]:
    """Group per-epoch pass/fail booleans by fixture id and compute
    per-fixture pass@k.

    Args:
        epochs: iterable of ``(fixture_id, passed)`` tuples, one per
            epoch. Multiple epochs per fixture are expected; the
            function does not require that every fixture have the
            same number of epochs (the runner may vary N per
            fixture in a future feature, e.g. adaptive budgets).
        k: pass@k target. Defaults to 1.

    Returns:
        One ``FixtureStats`` per unique ``fixture_id``, in the
        order the fixture first appears in the input.
    """
    by_id: dict[str, list[bool]] = {}
    order: list[str] = []
    for fid, passed in epochs:
        if fid not in by_id:
            by_id[fid] = []
            order.append(fid)
        by_id[fid].append(passed)

    out: list[FixtureStats] = []
    for fid in order:
        passes = by_id[fid]
        n = len(passes)
        c = sum(1 for p in passes if p)
        stats = FixtureStats(
            fixture_id=fid,
            n_epochs=n,
            n_passed=c,
            pass_at_1=pass_at_k(n, c, 1),
            pass_at_k_by_k={k: pass_at_k(n, c, k)},
        )
        out.append(stats)
    return out


def aggregate(
    fixtures: list[FixtureStats],
    *,
    cost_per_fixture: dict[str, float] | None = None,
    cost_total_usd: float = 0.0,
    total_input_tokens: int = 0,
    total_output_tokens: int = 0,
    total_duration_s: float = 0.0,
) -> RunAggregate:
    """Aggregate per-fixture stats into a single ``RunAggregate``.

    Args:
        fixtures: per-fixture stats from :func:`per_fixture`.
        cost_per_fixture: optional ``{fixture_id: mean_cost_usd}`` map
            for the score×cost frontier.
        cost_total_usd: total spend across the run.
        total_input_tokens / total_output_tokens: aggregate token
            counts.
        total_duration_s: aggregate wall-clock duration.
    """
    if not fixtures:
        return RunAggregate(
            fixtures=[],
            total_epochs=0,
            total_passed=0,
            aggregate_pass_at_1=0.0,
            aggregate_pass_at_1_stderr=0.0,
            cost_total_usd=cost_total_usd,
            cost_per_issue_usd=0.0,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            total_duration_s=total_duration_s,
        )

    rates = [f.pass_at_1 for f in fixtures]
    mean_rate = statistics.fmean(rates)
    # Sample stdev; use 1 (not 0) for N-1 denominator. For N=1
    # stdev is undefined → 0 stderr. (One-fixture runs are too small
    # to be statistically useful, but the math shouldn't crash.)
    if len(fixtures) > 1:
        stdev = statistics.stdev(rates)
    else:
        stdev = 0.0
    stderr = stdev / math.sqrt(len(fixtures)) if len(fixtures) > 0 else 0.0

    total_epochs = sum(f.n_epochs for f in fixtures)
    total_passed = sum(f.n_passed for f in fixtures)
    cost_per_issue = cost_total_usd / len(fixtures) if fixtures else 0.0

    return RunAggregate(
        fixtures=fixtures,
        total_epochs=total_epochs,
        total_passed=total_passed,
        aggregate_pass_at_1=mean_rate,
        aggregate_pass_at_1_stderr=stderr,
        cost_total_usd=cost_total_usd,
        cost_per_issue_usd=cost_per_issue,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        total_duration_s=total_duration_s,
        cost_per_fixture=cost_per_fixture or {},
    )


# ---------------------------------------------------------------------------
# Candidate vs baseline diff
# ---------------------------------------------------------------------------


@dataclass
class FixtureDiff:
    fixture_id: str
    candidate_pass_at_1: float
    baseline_pass_at_1: float

    @property
    def delta(self) -> float:
        return self.candidate_pass_at_1 - self.baseline_pass_at_1

    @property
    def status(self) -> str:
        """improved / regressed / unchanged — coarse classifier for
        the leaderboard diff column. The threshold is the
        baseline's per-fixture pass@1 error (we'd need the per-
        fixture stderr here, which the run record stores; for the
        coarse "improved/regressed/unchanged" label we use a flat
        ±0.05 cutoff that is small relative to the typical stderr
        at N=3)."""
        d = self.delta
        if d > 0.05:
            return "improved"
        if d < -0.05:
            return "regressed"
        return "unchanged"


@dataclass
class RunDiff:
    """Diff of one run (the candidate) against a baseline run."""

    baseline_label: str
    candidate_label: str
    per_fixture: list[FixtureDiff]
    candidate_aggregate: float
    baseline_aggregate: float
    candidate_stderr: float
    baseline_stderr: float

    @property
    def aggregate_delta(self) -> float:
        return self.candidate_aggregate - self.baseline_aggregate

    @property
    def aggregate_status(self) -> str:
        """A run regresses when the aggregate resolve rate drops
        beyond the baseline's stderr (per the task ADR: never
        byte-equality, always statistical). The exact threshold is
        a 1-stderr drop; tighten to 2-stderr in a noisy regime by
        swapping the multiplier here."""
        if self.candidate_aggregate < self.baseline_aggregate - self.baseline_stderr:
            return "regressed"
        if self.candidate_aggregate > self.baseline_aggregate + self.baseline_stderr:
            return "improved"
        return "unchanged"

    def regressed_fixtures(self) -> list[FixtureDiff]:
        return [d for d in self.per_fixture if d.status == "regressed"]

    def improved_fixtures(self) -> list[FixtureDiff]:
        return [d for d in self.per_fixture if d.status == "improved"]


def diff(
    candidate: RunAggregate,
    baseline: RunAggregate,
    *,
    baseline_label: str = "baseline",
    candidate_label: str = "candidate",
) -> RunDiff:
    """Compute a candidate-vs-baseline diff.

    Per-fixture pass rates are paired by ``fixture_id``. Fixtures
    present in only one side are skipped (the leaderboard should
    show the union, but the diff needs both sides to be
    comparable).
    """
    base_by_id = {f.fixture_id: f for f in baseline.fixtures}
    cand_by_id = {f.fixture_id: f for f in candidate.fixtures}
    common = sorted(set(base_by_id) & set(cand_by_id))
    per_fixture = [
        FixtureDiff(
            fixture_id=fid,
            candidate_pass_at_1=cand_by_id[fid].pass_at_1,
            baseline_pass_at_1=base_by_id[fid].pass_at_1,
        )
        for fid in common
    ]
    return RunDiff(
        baseline_label=baseline_label,
        candidate_label=candidate_label,
        per_fixture=per_fixture,
        candidate_aggregate=candidate.aggregate_pass_at_1,
        baseline_aggregate=baseline.aggregate_pass_at_1,
        candidate_stderr=candidate.aggregate_pass_at_1_stderr,
        baseline_stderr=baseline.aggregate_pass_at_1_stderr,
    )
