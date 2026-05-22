from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import StatisticsError, quantiles
from typing import Any


@dataclass(frozen=True)
class EstimateResult:
    p50_ms: int | None = None
    p95_ms: int | None = None
    n_samples: int = 0

    def to_dict(self) -> dict[str, int | None]:
        return asdict(self)


class PhaseDurationEstimator:
    """Caches conductor phase duration percentiles derived from transition logs."""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._cache: dict[str, EstimateResult] | None = None

    async def estimate(self, phase: str) -> EstimateResult:
        estimates = await self.all_estimates()
        return estimates.get(phase, EstimateResult())

    async def all_estimates(self) -> dict[str, EstimateResult]:
        if self._cache is not None:
            return self._cache
        list_logs = getattr(self._store, "list_conductor_state_logs", None)
        if not callable(list_logs):
            self._cache = {}
            return self._cache
        rows = await list_logs(None, limit=0, descending=False)
        buckets: dict[str, list[int]] = {}
        for index, row in enumerate(rows or []):
            next_row = rows[index + 1] if index + 1 < len(rows) else None
            if row.transition_at is None or next_row is None or next_row.transition_at is None:
                continue
            duration_ms = max(1, int((next_row.transition_at - row.transition_at).total_seconds() * 1000))
            buckets.setdefault(row.to_phase, []).append(duration_ms)
        self._cache = {
            phase: EstimateResult(
                p50_ms=_percentile(durations, 50),
                p95_ms=_percentile(durations, 95),
                n_samples=len(durations),
            )
            for phase, durations in buckets.items()
        }
        return self._cache

    def invalidate(self) -> None:
        self._cache = None


_ESTIMATORS: dict[int, PhaseDurationEstimator] = {}


def get_phase_duration_estimator(store: Any) -> PhaseDurationEstimator:
    key = id(store)
    estimator = _ESTIMATORS.get(key)
    if estimator is None:
        estimator = PhaseDurationEstimator(store)
        _ESTIMATORS[key] = estimator
    return estimator


def _percentile(values: list[int], percentile: int) -> int | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    if percentile <= 0:
        return ordered[0]
    if percentile >= 100:
        return ordered[-1]
    try:
        return int(round(quantiles(ordered, n=100, method="inclusive")[percentile - 1]))
    except StatisticsError:
        return ordered[-1]
