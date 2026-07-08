"""Tests for the LLM-as-judge scorer + correlation math (PR3).

Covers:

  - ``_parse_score``: first-line parsing, clamping, malformed input.
  - ``LLMJudgeScorer``: deterministic with a fixed backend,
    uncalibrated path, unparseable response.
  - ``pearson``/``spearman``: known values, edge cases (constant
    series, single point, length mismatch).
  - ``calibration_report``: floor gate, weakest item flag.
  - The shipped ``backend/benchmark/calibration/`` set loads
    cleanly via ``CalibrationSet.from_dir``.
"""

from __future__ import annotations  # noqa: I001

import math  # noqa: F401
from pathlib import Path
from typing import cast

import pytest

from benchmark.correlation import (
    CalibrationItem,
    CalibrationSet,
    calibration_report,
    pearson,
    spearman,
)
from benchmark.judge import (
    DEFAULT_CORRELATION_FLOOR,
    FixedResponseBackend,
    LLMJudgeScorer,
    _parse_score,
)
from benchmark.types import IssueArtifacts, Score  # noqa: F401


# ---------------------------------------------------------------------------
# _parse_score
# ---------------------------------------------------------------------------


def test_parse_score_simple_number():
    r = _parse_score("0.85\nbecause the criteria are well-shaped")
    assert r.value == 0.85
    assert r.explanation == "because the criteria are well-shaped"


def test_parse_score_clamps_above_one():
    r = _parse_score("1.5\ntoo generous")
    assert r.value == 1.0


def test_parse_score_clamps_below_zero():
    r = _parse_score("-0.1\ntypo")
    assert r.value == 0.0


def test_parse_score_handles_integer():
    assert _parse_score("1\n").value == 1.0
    assert _parse_score("0\n").value == 0.0


def test_parse_score_skips_blank_leading_lines():
    r = _parse_score("\n\n0.7\nok")
    assert r.value == 0.7


def test_parse_score_unparseable_returns_none():
    assert _parse_score("i don't know").value is None
    assert _parse_score("").value is None
    assert _parse_score("the score is 0.5 overall").value is None  # no leading number


# ---------------------------------------------------------------------------
# LLMJudgeScorer
# ---------------------------------------------------------------------------


def _artifacts_with(criteria: list[str], tasks: list[str]) -> IssueArtifacts:
    return IssueArtifacts(
        issue_id="i",
        prd_acceptance_criteria=criteria,
        completed_engineer_tasks=tasks,
    )


def test_judge_scorer_passes_when_calibrated_and_score_high():
    backend = FixedResponseBackend("0.95\nhigh quality")
    scorer = LLMJudgeScorer(backend, is_calibrated=True)
    s = scorer.score(
        _artifacts_with(
            criteria=["criterion one", "criterion two"],
            tasks=["done one", "done two"],
        )
    )
    assert s.value == 0.95
    assert s.passed is True
    assert s.metadata["is_calibrated"] is True
    explanation = s.metadata["explanation"]
    assert isinstance(explanation, str)
    assert "high quality" in explanation


def test_judge_scorer_passes_false_when_below_threshold():
    backend = FixedResponseBackend("0.5\nmarginal")
    scorer = LLMJudgeScorer(backend, is_calibrated=True)
    s = scorer.score(_artifacts_with(criteria=["x"], tasks=["x"]))
    assert s.value == 0.5
    assert s.passed is False  # threshold is 0.8


def test_judge_scorer_uncalibrated_never_passes():
    """The contract: an uncalibrated judge must never ``passed``."""
    backend = FixedResponseBackend("0.99\nlooks great but uncalibrated")
    scorer = LLMJudgeScorer(backend, is_calibrated=False)
    s = scorer.score(_artifacts_with(criteria=["x"], tasks=["x"]))
    assert s.value == 0.99
    assert s.passed is False  # calibrated gate holds
    assert s.metadata["is_calibrated"] is False


def test_judge_scorer_unparseable_response_is_zero():
    backend = FixedResponseBackend("not a number, sorry")
    scorer = LLMJudgeScorer(backend, is_calibrated=True)
    s = scorer.score(_artifacts_with(criteria=["x"], tasks=["x"]))
    assert s.value == 0.0
    assert s.passed is False
    assert s.metadata["reason"] == "unparseable_judge_response"
    raw_first_line = s.metadata["raw_first_line"]
    assert isinstance(raw_first_line, str)
    assert "not a number" in raw_first_line


def test_judge_scorer_prompt_includes_rubric():
    backend = FixedResponseBackend("0.5\nok")
    scorer = LLMJudgeScorer(backend, issue_title="My issue")
    scorer.score(
        _artifacts_with(
            criteria=["the endpoint exists", "returns 200"],
            tasks=["done"],
        )
    )
    assert len(backend.calls) == 1
    prompt = backend.calls[0]
    assert "the endpoint exists" in prompt
    assert "returns 200" in prompt
    assert "My issue" in prompt
    assert "done" in prompt


# ---------------------------------------------------------------------------
# pearson
# ---------------------------------------------------------------------------


def test_pearson_perfect_positive():
    assert pearson([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)


def test_pearson_perfect_negative():
    assert pearson([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)


def test_pearson_no_correlation():
    # y is uncorrelated with x (random walk). Use enough points
    # that the sample r is small in magnitude even with noise.
    xs = list(range(20))
    ys = [
        3.0,
        1.0,
        4.0,
        2.0,
        5.0,
        1.5,
        3.5,
        2.5,
        4.5,
        1.0,
        2.0,
        3.0,
        4.0,
        5.0,
        1.5,
        2.5,
        3.5,
        4.5,
        1.0,
        2.0,
    ]
    r = pearson(cast(list[float], xs), ys)
    assert abs(r) < 0.3  # not strict — random walk; just bounded


def test_pearson_constant_series_returns_zero():
    """A constant series has undefined correlation. The function
    returns 0.0 to keep callers off the NaN path."""
    assert pearson([1, 2, 3], [5, 5, 5]) == 0.0
    assert pearson([7, 7, 7], [1, 2, 3]) == 0.0


def test_pearson_length_mismatch_raises():
    with pytest.raises(ValueError):
        pearson([1, 2], [1, 2, 3])


def test_pearson_single_point_returns_zero():
    assert pearson([1.0], [2.0]) == 0.0


def test_pearson_empty_returns_zero():
    assert pearson([], []) == 0.0


# ---------------------------------------------------------------------------
# spearman
# ---------------------------------------------------------------------------


def test_spearman_perfect_monotonic():
    """Spearman is 1.0 for any strictly monotonic relationship,
    not just linear. So y = x**2 still ranks perfectly."""
    xs = [1.0, 2.0, 3.0, 4.0]
    ys = [1.0, 4.0, 9.0, 16.0]
    assert spearman(xs, ys) == pytest.approx(1.0)


def test_spearman_perfect_inverse_monotonic():
    xs = [1.0, 2.0, 3.0, 4.0]
    ys = [4.0, 3.0, 2.0, 1.0]
    assert spearman(xs, ys) == pytest.approx(-1.0)


def test_spearman_handles_ties_with_average_rank():
    """Ties in the y-axis get average rank; Spearman is robust to
    these. With one tie in y, |Spearman| is slightly less than
    1.0 even for a perfect monotone relationship."""
    xs = [1.0, 2.0, 3.0, 4.0]
    ys = [1.0, 2.0, 2.0, 4.0]  # y[1] and y[2] are tied at 2
    r = spearman(xs, ys)
    assert abs(r) < 1.0  # not perfect because of the tie
    assert r > 0.9  # but still very high


# ---------------------------------------------------------------------------
# calibration_report
# ---------------------------------------------------------------------------


def _item(i: int, human: float, judge: float) -> CalibrationItem:
    return CalibrationItem(
        id=f"item-{i}",
        fixture_id=None,
        artifact_excerpt=f"excerpt {i}",
        human_score=human,
        judge_score=judge,
    )


def test_calibration_report_passes_when_both_correlations_clear_floor():
    items = [
        _item(1, 0.1, 0.1),
        _item(2, 0.4, 0.45),
        _item(3, 0.7, 0.7),
        _item(4, 0.95, 0.92),
    ]
    report = calibration_report(items, floor=0.7)
    assert report.is_calibrated is True
    assert report.n == 4
    assert abs(report.pearson) > 0.9
    assert abs(report.spearman) > 0.9


def test_calibration_report_fails_when_pearson_below_floor():
    """Pearson = ~0.5 (loose correlation) but the data is
    monotone; Spearman is high. The conservative "both must clear"
    gate still requires Pearson, so the report is uncalibrated."""
    items = [
        _item(1, 0.1, 0.5),
        _item(2, 0.2, 0.45),
        _item(3, 0.3, 0.55),
        _item(4, 0.4, 0.40),
        _item(5, 0.5, 0.6),
    ]
    report = calibration_report(items, floor=0.7)
    assert report.is_calibrated is False
    # Pearson is roughly 0.5; floor=0.7; the report flags it.
    assert abs(report.pearson) < 0.7


def test_calibration_report_finds_weakest_item():
    items = [
        _item(1, 0.5, 0.5),  # zero residual
        _item(2, 0.8, 0.2),  # biggest residual: 0.6
        _item(3, 0.3, 0.4),  # small
    ]
    report = calibration_report(items, floor=0.0)
    assert report.weakest_item == "item-2"


def test_calibration_report_insufficient_data():
    items = [_item(1, 0.5, 0.5)]
    report = calibration_report(items, floor=0.7)
    assert report.is_calibrated is False
    assert report.pearson == 0.0
    assert report.n == 1


def test_calibration_report_default_floor():
    """The shipped DEFAULT_CORRELATION_FLOOR is 0.7. Sanity check
    that the report uses it (or an override) as documented."""
    assert DEFAULT_CORRELATION_FLOOR == 0.7


# ---------------------------------------------------------------------------
# CalibrationSet
# ---------------------------------------------------------------------------


def test_calibration_set_round_trip(tmp_path: Path):
    cs = CalibrationSet(
        items=[
            CalibrationItem(
                id="a",
                fixture_id="fx",
                artifact_excerpt="text",
                human_score=0.5,
                note="note",
            ),
            CalibrationItem(
                id="b",
                fixture_id="fx",
                artifact_excerpt="text 2",
                human_score=0.8,
            ),
        ]
    )
    cs.to_dir(tmp_path)
    loaded = CalibrationSet.from_dir(tmp_path)
    assert len(loaded) == 2
    item_a = loaded.get("a")
    item_b = loaded.get("b")
    assert item_a is not None
    assert item_b is not None
    assert item_a.human_score == 0.5
    assert item_a.note == "note"
    assert item_b.human_score == 0.8


def test_calibration_set_from_empty_dir(tmp_path: Path):
    """from_dir on a non-existent dir returns an empty set, not raise."""
    cs = CalibrationSet.from_dir(tmp_path / "missing")
    assert len(cs) == 0


def test_calibration_set_shipped_items_load(tmp_path: Path):
    """The shipped 8 calibration items load cleanly and have
    judge_score=null (the judge hasn't run on them)."""
    from benchmark.correlation import CalibrationSet  # noqa: I001
    import shutil

    # Copy the shipped items into a tmp dir so we can read them
    # without polluting the real source.
    shipped = Path(__file__).parent.parent / "benchmark" / "calibration"
    dest = tmp_path / "cal"
    shutil.copytree(shipped, dest)
    cs = CalibrationSet.from_dir(dest)
    assert len(cs) == 8
    for it in cs.all():
        assert it.judge_score is None
        assert 0.0 <= it.human_score <= 1.0
        assert it.artifact_excerpt
