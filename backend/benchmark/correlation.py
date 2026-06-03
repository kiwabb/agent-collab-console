"""Judge calibration math.

The judge scorer is only useful if its scores correlate with
human judgment. The shipped scorer is *armed but inert* below
the project-standard correlation floor (``|r| < 0.7`` against the
calibration set) — it still scores, but the leaderboard should
not rank on it.

This module provides:

  - ``pearson(xs, ys)`` and ``spearman(xs, ys)``: pure math,
    deterministic, no IO.
  - ``calibration_report(human_scores, judge_scores)`` — both
    correlation coefficients + the verdict (calibrated / needs
    recalibration) under the configurable floor.
  - ``CalibrationSet`` — a tiny in-memory + JSON-on-disk store
    for the hand-labeled calibration items.

The correlation math is the standard textbook Pearson
coefficient; Spearman is the rank-based variant. Both are stable
for n in the dozens (which is the expected size of the
calibration set); a future feature that needs tens of thousands
of items should swap in a streaming implementation.
"""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Pearson + Spearman
# ---------------------------------------------------------------------------


def pearson(xs: list[float], ys: list[float]) -> float:
    """Pearson product-moment correlation coefficient.

    Returns 0.0 when the two series are constant (the textbook
    convention: the correlation is undefined, so we return 0 to
    keep callers off the NaN path; the calibration verdict then
    correctly fails the floor check).
    """
    if len(xs) != len(ys):
        raise ValueError(f"length mismatch: {len(xs)} vs {len(ys)}")
    n = len(xs)
    if n < 2:
        return 0.0
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    denom = math.sqrt(var_x * var_y)
    if denom == 0.0:
        # One or both series is constant → correlation undefined.
        # 0 is the conventional fallback; the verdict will fall
        # below the floor and the judge will be marked uncalibrated.
        return 0.0
    return cov / denom


def _rank(values: list[float]) -> list[float]:
    """Average-rank assignment (handles ties by averaging the
    positions). Standard for Spearman."""
    indexed = sorted(enumerate(values), key=lambda iv: iv[1])
    ranks: list[float | None] = [None] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j) / 2 + 1  # 1-indexed
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return [r for r in ranks]  # type: ignore[misc]


def spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman rank correlation (with average-rank tie handling)."""
    if len(xs) != len(ys):
        raise ValueError(f"length mismatch: {len(xs)} vs {len(ys)}")
    return pearson(_rank(xs), _rank(ys))


# ---------------------------------------------------------------------------
# Calibration set + report
# ---------------------------------------------------------------------------


@dataclass
class CalibrationItem:
    """One hand-labeled calibration example.

    ``human_score`` is the ground-truth 0..1 label a human
    annotator assigned. ``fixture_id`` and ``note`` are for
    humans; the math does not read them.
    """

    id: str
    fixture_id: str | None  # ties to a real or hypothetical golden task
    artifact_excerpt: str  # short, the input the judge sees
    human_score: float
    judge_score: float | None = None  # filled in after a judge run
    note: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "fixture_id": self.fixture_id,
            "artifact_excerpt": self.artifact_excerpt,
            "human_score": self.human_score,
            "judge_score": self.judge_score,
            "note": self.note,
        }


@dataclass
class CalibrationReport:
    """Result of running a judge over the calibration set."""

    n: int
    pearson: float
    spearman: float
    floor: float
    is_calibrated: bool
    weakest_item: str | None  # id of the calibration item with the largest |human - judge| residual

    @property
    def summary(self) -> str:
        verdict = "calibrated" if self.is_calibrated else "needs recalibration"
        return (
            f"n={self.n}  pearson={self.pearson:+.3f}  "
            f"spearman={self.spearman:+.3f}  "
            f"floor={self.floor}  → {verdict}"
        )


def calibration_report(
    items: list[CalibrationItem],
    *,
    floor: float = 0.7,
) -> CalibrationReport:
    """Compute the correlation report from a list of items whose
    ``judge_score`` is already populated.

    ``is_calibrated`` is True iff **both** |pearson| and |spearman|
    clear the floor. The conservative "both" gate is intentional:
    a judge that correlates well on the linear scale but ranks
    items inconsistently (low Spearman) is dangerous to use for
    leaderboard ordering.

    ``n`` is the **total** set size, not the count-with-judge-scores
    (the API surface wants to report "you have 8 calibration items"
    even before the judge has been run on them). The correlation
    math is computed over the items that DO have judge scores
    (the n_judged field, internal to the report).
    """
    n_total = len(items)
    with_scores = [i for i in items if i.judge_score is not None]
    if len(with_scores) < 2:
        return CalibrationReport(
            n=n_total,
            pearson=0.0,
            spearman=0.0,
            floor=floor,
            is_calibrated=False,
            weakest_item=with_scores[0].id if with_scores else None,
        )
    humans = [i.human_score for i in with_scores]
    judges = [i.judge_score for i in with_scores]
    p = pearson(humans, judges)
    s = spearman(humans, judges)
    residuals = [
        (i.id, abs(i.human_score - (i.judge_score or 0.0)))
        for i in with_scores
    ]
    weakest = max(residuals, key=lambda r: r[1])[0] if residuals else None
    return CalibrationReport(
        n=n_total,
        pearson=p,
        spearman=s,
        floor=floor,
        is_calibrated=abs(p) >= floor and abs(s) >= floor,
        weakest_item=weakest,
    )


# ---------------------------------------------------------------------------
# On-disk calibration set (JSON-per-item)
# ---------------------------------------------------------------------------


class CalibrationSet:
    """A small set of ``CalibrationItem``s, loaded from / saved to a
    directory of JSON files (one per item, id-keyed)."""

    def __init__(self, items: list[CalibrationItem] | None = None) -> None:
        self._items: dict[str, CalibrationItem] = {}
        for it in items or []:
            self._items[it.id] = it

    def add(self, item: CalibrationItem) -> None:
        self._items[item.id] = item

    def get(self, item_id: str) -> CalibrationItem | None:
        return self._items.get(item_id)

    def all(self) -> list[CalibrationItem]:
        return list(self._items.values())

    def __len__(self) -> int:
        return len(self._items)

    def to_dir(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        for it in self._items.values():
            (root / f"{it.id}.json").write_text(
                json.dumps(it.to_dict(), indent=2), encoding="utf-8"
            )

    @classmethod
    def from_dir(cls, root: Path) -> "CalibrationSet":
        cs = cls()
        if not root.is_dir():
            return cs
        for path in sorted(root.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            cs.add(
                CalibrationItem(
                    id=data["id"],
                    fixture_id=data.get("fixture_id"),
                    artifact_excerpt=data["artifact_excerpt"],
                    human_score=float(data["human_score"]),
                    judge_score=(
                        float(data["judge_score"])
                        if data.get("judge_score") is not None
                        else None
                    ),
                    note=data.get("note"),
                )
            )
        return cs
