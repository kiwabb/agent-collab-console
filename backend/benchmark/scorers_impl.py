"""The two PR1 scorers: execution-based and acceptance-coverage.

These are intentionally the simplest useful forms of each scorer
family. They are deterministic given fixed input artifacts (the
contract the methodology requires), and they are unit-tested on
hand-built inputs.

Future scorers (PR3):
  - LLM-as-judge (PM/architect artifacts; needs calibration set)
  - File-presence scorer (a stricter version of coverage for tasks
    that need a specific file to exist with specific content)
"""

from __future__ import annotations  # noqa: I001

import re

from .scorers import ScorerRegistry
from .types import IssueArtifacts, Score


# ---------------------------------------------------------------------------
# Execution-based scorer (PRIMARY, FAIL_TO_PASS analog)
# ---------------------------------------------------------------------------


class ExecutionScorer:
    """Pass iff **every** pinned QA command returned ``exit_code == 0``.

    The score is the fraction of commands that passed; ``passed`` is
    the strict all-pass view (matching the SWE-bench ``FAIL_TO_PASS``
    semantics — a single failing command means the issue is not
    resolved).

    When the runner produces no QA results (the agent's run never
    reached the QA stage, or the harness crashed early), the scorer
    returns 0.0 + a reason. It does NOT skip; an empty ``qa_results``
    is a failure, not a neutral.
    """

    name = "execution"
    weight = 1.0  # PRIMARY per the task PRD

    def score(self, artifacts: IssueArtifacts) -> Score:
        if not artifacts.qa_results:
            return Score(
                value=0.0,
                passed=False,
                metadata={"reason": "no_qa_results"},
                notes="no QA command ran; treating as failure",
            )
        total = len(artifacts.qa_results)
        passed = sum(1 for r in artifacts.qa_results if r.exit_code == 0)
        failed = [
            {"command": r.command, "exit_code": r.exit_code, "duration_s": r.duration_s}
            for r in artifacts.qa_results
            if r.exit_code != 0
        ]
        return Score(
            value=passed / total,
            passed=passed == total,
            metadata={
                "passed": passed,
                "total": total,
                "failed": failed,
            },
            notes=None if passed == total else f"{passed}/{total} QA commands passed",
        )


# ---------------------------------------------------------------------------
# Acceptance-coverage scorer (secondary rubric layer)
# ---------------------------------------------------------------------------


# Words that carry too little signal to gate a coverage decision. Pulled
# out of the criterion text and the task-title text before comparison.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "the",
        "for",
        "in",
        "on",
        "with",
        "by",
        "is",
        "it",
        "this",
        "that",
        "as",
        "at",
        "be",
        "from",
        "into",
        "than",
        "then",
        "so",
        "but",
        "not",
        "no",
        "if",
        "do",
        "does",
        "did",
        "should",
        "would",
        "could",
        "can",
        "may",
        "might",
        "must",
        "shall",
        "will",
        "have",
        "has",
        "had",
        "i",
        "we",
        "you",
        "they",
        "he",
        "she",
        "them",
        "us",
        "my",
        "your",
        "their",
        "our",
        "its",
    }
)


def _meaningful_tokens(text: str) -> set[str]:
    """Lowercase, alnum-only, stopword-filtered token set.

    Used for the heuristic coverage match: a criterion is "covered"
    if a non-trivial fraction of its meaningful tokens appear in the
    joined completed-task titles. This is intentionally simple — PR3
    swaps in an LLM-as-judge when calibrated.
    """
    tokens = {
        tok
        for tok in re.findall(r"[a-z0-9]+", text.lower())
        if tok and tok not in _STOPWORDS and len(tok) >= 2
    }
    return tokens


def _criterion_covered(criterion: str, joined_titles: str) -> bool:
    """A criterion is covered when ≥ 50% of its meaningful tokens
    appear in the joined task-title corpus. A 1-token criterion is
    considered covered when that token appears.

    The 50% threshold is intentionally low: this is a coverage
    proxy, not a semantic match. The runner can later replace it
    with a calibrated judge.
    """
    crit_tokens = _meaningful_tokens(criterion)
    if not crit_tokens:
        return False
    title_tokens = _meaningful_tokens(joined_titles)
    if not title_tokens:
        return False
    hits = crit_tokens & title_tokens
    if len(crit_tokens) == 1:
        return bool(hits)
    return len(hits) / len(crit_tokens) >= 0.5


class AcceptanceCoverageScorer:
    """Fraction of the golden ``acceptance_criteria`` whose meaningful
    tokens appear in the engineer's completed-task titles.

    This is a **proxy** for "did the agent's work address each rubric
    point?". The match is token-overlap based and intentionally lax
    (50% threshold); it is not a semantic equivalence test. PR3
    replaces it with a calibrated LLM-as-judge that uses the same
    ``IssueArtifacts`` shape.
    """

    name = "coverage"
    weight = 0.3  # secondary; execution dominates

    def score(self, artifacts: IssueArtifacts) -> Score:
        golden = artifacts.prd_acceptance_criteria
        if not golden:
            # No rubric = trivially "covered". This is a degenerate case
            # that the schema's ``min_length=1`` should prevent, but the
            # scorer is defensive.
            return Score(
                value=1.0,
                passed=True,
                metadata={"reason": "no_acceptance_criteria"},
            )
        joined = " ".join(artifacts.completed_engineer_tasks)
        covered_flags = [_criterion_covered(c, joined) for c in golden]
        covered = sum(covered_flags)
        uncovered = [c for c, ok in zip(golden, covered_flags) if not ok]  # noqa: B905
        return Score(
            value=covered / len(golden),
            passed=covered == len(golden),
            metadata={
                "covered": covered,
                "total": len(golden),
                "uncovered": uncovered,
            },
            notes=(
                None if covered == len(golden) else f"{covered}/{len(golden)} criteria addressed"
            ),
        )


# ---------------------------------------------------------------------------
# Default registry
# ---------------------------------------------------------------------------


def default_registry() -> ScorerRegistry:
    """A fresh :class:`ScorerRegistry` with the PR1 defaults registered.

    Returns a fresh registry on every call so callers can mutate it
    locally (e.g. add a PR3 judge for one run) without leaking into
    the next call.
    """
    reg = ScorerRegistry()
    reg.register(ExecutionScorer())
    reg.register(AcceptanceCoverageScorer())
    return reg
