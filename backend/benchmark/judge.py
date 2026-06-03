"""LLM-as-judge scorer for soft artifacts (PM / architect deliverables).

The execution + coverage scorers from PR1 are deterministic given
their inputs. The judge is the **stochastic** third layer — useful
for grading the parts of an issue that cannot be reduced to a
command exit code: the quality of a PRD's acceptance criteria, an
architect's design rationale, whether the engineer's completed
work addresses each rubric point.

Tradeoffs the judge carries (per the task research):

  - **Non-determinism**: the model output is stochastic; the
    methodology handles this by running the judge N times and
    reporting mean + stderr (the calibration step in
    :mod:`benchmark.correlation` does exactly that).
  - **Position / verbosity / self-preference bias**: the prompt is
    kept short and demands a single 0..1 number, which mitigates
    but does not eliminate these.
  - **Calibration**: a judge is only useful if its scores
    correlate with human judgment. The shipped scorer **requires
    a calibration set** (see :mod:`benchmark.correlation`) and
    self-deactivates when the correlation drops below the
    project-standard threshold (|r| < 0.7).

The scorer is **pluggable**: it accepts any callable that takes a
judge prompt and returns a string parseable as a number 0..1.
The production code path plugs in the project's model catalog
(``runtime_catalog_settings``); the unit tests plug in a fixed
fake. This keeps the scorer deterministic in CI without mocking
the LLM client.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from .scorers import ScorerRegistry
from .types import IssueArtifacts, Score


# A "judge backend" is a callable: prompt -> raw response string.
# The real path uses the project's model catalog; tests inject a
# fixed-response stub. Keeping this as a Protocol (not an ABC)
# keeps the test surface flat.
@runtime_checkable
class JudgeBackend(Protocol):
    def __call__(self, prompt: str) -> str: ...


@dataclass
class JudgeResult:
    """Raw output of one judge call, before the score is normalized."""

    raw: str
    value: float | None  # None when the response is unparseable
    explanation: str | None = None


# --- the judge prompt ------------------------------------------------------

# Kept deliberately short: long prompts amplify verbosity bias.
# The prompt asks for a single number and a one-line reason; both
# are extracted by ``_parse_score``.
_JUDGE_PROMPT_TEMPLATE = """\
You are scoring the quality of a software-engineering artifact
against a rubric. Return a single number between 0.0 and 1.0
(inclusive) on the first line, then one short sentence of
explanation on the second line. Do not include any other text.

Rubric (acceptance criteria from the golden task):
{criteria}

Artifact (engineer's completed work + the issue it was solving):
- Issue title: {issue_title}
- Completed task titles: {task_titles}
- QA real-command results: {qa_results}

Score this artifact on how well it addresses the rubric. \
0.0 = none of the criteria are addressed; 1.0 = all criteria are \
addressed with high quality.
"""


# --- the parser ------------------------------------------------------------

# Strict: first non-empty line, either an integer, decimal, or the
# substring before the first whitespace/comma. The regex anchors on
# the start so a noisy explanation line that happens to contain a
# number does not win. We capture the sign separately so a model
# that emits a negative probe ("-0.1") is recognised as a negative
# intent and clamped to 0 below.
_SCORE_LINE = re.compile(
    r"^\s*(?P<sign>-?)(?P<score>(?:0(?:\.\d+)?|1(?:\.0+)?|0?\.\d+|[01]))\b"
)


def _parse_score(raw: str) -> JudgeResult:
    """Extract the score from a judge response.

    Returns ``value=None`` when the response is unparseable; the
    scorer treats that as 0.0 + a "needs calibration" note rather
    than crashing.
    """
    if not raw:
        return JudgeResult(raw=raw, value=None, explanation="empty response")
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _SCORE_LINE.match(line)
        if m:
            try:
                v = float(m.group("score"))
            except ValueError:
                return JudgeResult(raw=raw, value=None, explanation=f"non-numeric score: {line!r}")
            sign = m.group("sign")
            if sign == "-":
                v = -v
            # Clamp into [0, 1] — defensive against "-0.1" (negative
            # probe), "0.999999" (model rounding), and "1.0001"
            # (model looseness with the "between 0.0 and 1.0"
            # instruction).
            v = max(0.0, min(1.0, v))
            explanation = raw[raw.index(line) + len(line):].strip() or None
            return JudgeResult(raw=raw, value=v, explanation=explanation)
    return JudgeResult(raw=raw, value=None, explanation="no parseable score line")


# --- the scorer ------------------------------------------------------------


# Default: the judge self-deactivates below this |Pearson r| threshold
# against the calibration set. The 0.7 floor matches the project
# research's "non-trivial correlation" cutoff (the standard "use
# LLM-as-judge" literature uses 0.5–0.7; we pick the upper end
# because the alternative is silent garbage on the leaderboard).
DEFAULT_CORRELATION_FLOOR = 0.7


class LLMJudgeScorer:
    """LLM-as-judge scorer over the soft artifacts of an issue run.

    The scorer asks the judge backend to grade the engineer's
    work against the golden task's acceptance criteria. The score
    is the parsed 0..1 number from the first line of the response.

    When the judge returns an unparseable response, the scorer
    records ``value=0.0`` and surfaces the raw text in
    ``metadata`` so the operator can see the problem in the run
    record. It does NOT crash the run; the run completes with
    the judge marked as failed.
    """

    name = "judge"
    weight = 0.5  # secondary + soft; execution still dominates

    def __init__(
        self,
        backend: JudgeBackend,
        *,
        issue_title: str = "(no title)",
        is_calibrated: bool = True,
    ) -> None:
        self._backend = backend
        self._issue_title = issue_title
        # When the calibration check fails, the scorer is "armed
        # but inert": it still scores, but flips ``passed`` to
        # False and notes that the score is untrusted. The leaderboard
        # should not surface uncalibrated judge scores as a
        # ranking signal.
        self._is_calibrated = is_calibrated

    def score(self, artifacts: IssueArtifacts) -> Score:
        prompt = _JUDGE_PROMPT_TEMPLATE.format(
            criteria="\n".join(f"- {c}" for c in artifacts.prd_acceptance_criteria)
            or "(no rubric provided)",
            issue_title=self._issue_title,
            task_titles=", ".join(artifacts.completed_engineer_tasks) or "(none)",
            qa_results=", ".join(
                f"{r.command}->exit={r.exit_code}" for r in artifacts.qa_results
            )
            or "(no qa runs)",
        )
        raw = self._backend(prompt)
        parsed = _parse_score(raw)
        if parsed.value is None:
            return Score(
                value=0.0,
                passed=False,
                metadata={
                    "reason": "unparseable_judge_response",
                    "raw_first_line": raw.splitlines()[0] if raw else "",
                },
                notes="judge returned an unparseable response; treated as 0.0",
            )
        return Score(
            value=parsed.value,
            # An uncalibrated judge never "passes" by definition —
            # we don't want it to lift a candidate above the
            # baseline by accident.
            passed=parsed.value >= 0.8 and self._is_calibrated,
            metadata={
                "raw": raw,
                "explanation": parsed.explanation,
                "is_calibrated": self._is_calibrated,
            },
            notes=(
                parsed.explanation
                if parsed.explanation
                else ("judge score" if self._is_calibrated else "judge score (uncalibrated)")
            ),
        )


# --- a built-in "fixed" backend for tests + dry-runs -----------------------


class FixedResponseBackend:
    """A backend that ignores the prompt and returns a fixed string.

    Useful for unit tests (lock the judge to a known response) and
    for the CLI ``--dry-judge`` smoke flag (skip the LLM call in CI).
    """

    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self._response


# --- factory for the production path --------------------------------------


def default_registry_with_judge(
    backend: JudgeBackend,
    *,
    is_calibrated: bool = True,
    judge_issue_title: str = "(no title)",
) -> ScorerRegistry:
    """Build the registry with the judge wired in, on top of the
    PR1 defaults. Convenience for the API/CLI layer that needs the
    full scorer set."""
    from .scorers_impl import AcceptanceCoverageScorer, ExecutionScorer

    reg = ScorerRegistry()
    reg.register(ExecutionScorer())
    reg.register(AcceptanceCoverageScorer())
    reg.register(
        LLMJudgeScorer(
            backend,
            issue_title=judge_issue_title,
            is_calibrated=is_calibrated,
        )
    )
    return reg
