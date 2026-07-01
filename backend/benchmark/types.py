"""Shared value types for the benchmark harness.

These are the data shapes that flow between the runner (PR2) and the
scorers. Keeping them in a dedicated module lets the runner, the API,
the persistence layer, and the scorers all import the same shapes
without a circular dependency on the scorers.

Design rule: every type here is a plain dataclass with snake_case
fields, no Pydantic. Pydantic is reserved for the *external* boundary
(API request/response, JSON-loaded golden fixtures); the in-process
boundary uses dataclasses for speed and because we control all the
producers.
"""

from __future__ import annotations  # noqa: I001

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Scorer interface
# ---------------------------------------------------------------------------


@dataclass
class Score:
    """A scorer's verdict on a single issue run.

    Attributes:
        value: normalized 0..1 score. Higher is better. Always set, even
            when the scorer cannot evaluate (use 0.0 + a reason in
            ``metadata``).
        passed: did the issue "pass" by the scorer's own threshold?
            Default threshold is ``value >= 1.0`` for hard-fail scorers
            (e.g. execution) and ``value >= 0.8`` for soft scorers
            (e.g. coverage). The scorer sets ``passed`` explicitly so
            the threshold lives next to the rule that uses it.
        metadata: free-form debug info. The runner logs it on the
            run record; the frontend does not surface it.
        notes: human-readable one-liner for the run record / log line.
    """

    value: float
    passed: bool
    metadata: dict[str, Any] = field(default_factory=dict)
    notes: str | None = None


@dataclass
class CommandResult:
    """The actual result of one pinned QA command, as captured by the runner.

    A scorer compares the runner's ``CommandResult`` against the golden
    fixture's ``PinnedCommand`` to decide pass/fail.
    """

    command: str
    exit_code: int
    duration_s: float
    stdout_tail: str = ""
    stderr_tail: str = ""


@dataclass
class IssueArtifacts:
    """All the signals a scorer might want for one issue run.

    The runner (PR2) produces this from a completed Conductor loop;
    the scorers in this package consume it. For unit tests, the test
    itself constructs an ``IssueArtifacts`` from a fixed payload —
    that is the determinism contract the methodology requires.

    The fields are **additive** — scorers should ignore fields they
    do not need, and a new scorer type (e.g. LLM-as-judge in PR3) can
    add a new field without breaking existing scorers.
    """

    issue_id: str
    prd_acceptance_criteria: list[str] = field(default_factory=list)
    qa_results: list[CommandResult] = field(default_factory=list)
    completed_engineer_tasks: list[str] = field(default_factory=list)
    # Reserved for PR3:
    pm_artifacts: dict[str, str] = field(default_factory=dict)
    architect_artifacts: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate_weighted(
    scorer_results: dict[str, Score],
    weights: dict[str, float],
) -> float:
    """Weighted average of scorer values, normalized by total weight.

    Returns 0.0 when there are no weights or no scores, so the caller
    never has to special-case "no scorers registered". A scorer
    missing from ``weights`` is silently dropped — the caller's job
    to keep the registry and the weights in sync.
    """
    if not weights:
        return 0.0
    numerator = 0.0
    denominator = 0.0
    for name, weight in weights.items():
        if name not in scorer_results:
            continue
        numerator += scorer_results[name].value * weight
        denominator += weight
    if denominator == 0.0:
        return 0.0
    return numerator / denominator
