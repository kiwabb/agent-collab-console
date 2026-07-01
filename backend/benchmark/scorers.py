"""Scorer registry + Scorer protocol.

A ``Scorer`` is a stateless callable that turns a run's
:class:`IssueArtifacts` into a :class:`Score`. The registry lets a
caller (the runner in PR2, the unit tests in this PR) wire up the
default set or a custom set without scattering import chains.

Adding a new scorer:

  1. Subclass :class:`Scorer` (or implement the protocol directly) and
     give it a unique ``name`` and a ``weight`` (used by
     :func:`aggregate_weighted`).
  2. Register it on a fresh :class:`ScorerRegistry` (typically
     :data:`default_registry`).
  3. Unit-test the scorer against a hand-built ``IssueArtifacts`` so
     the contract is locked down before the runner feeds it real data.

Why a Protocol and not an ABC: scorers are stateless value-in-value-out
functions; the protocol lets tests pass plain functions or lambdas as
``Scorer`` instances when the full class is overkill.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .types import IssueArtifacts, Score


@runtime_checkable
class Scorer(Protocol):
    """Stateless scorer. Implementations are typically classes for
    readability, but plain functions / lambdas that match the protocol
    also work."""

    name: str
    weight: float

    def score(self, artifacts: IssueArtifacts) -> Score: ...


@dataclass
class ScorerEntry:
    """A registered scorer with its name and weight, kept together
    so the runner can read either without re-querying the registry."""

    scorer: Scorer
    weight: float = 1.0

    def score(self, artifacts: IssueArtifacts) -> Score:
        return self.scorer.score(artifacts)


class ScorerRegistry:
    """In-process registry mapping scorer name -> ``ScorerEntry``.

    Lookups by name are O(1). Registration is O(1) and overwrites a
    prior entry with the same name (intentional: lets a caller layer
    a "PR3 judge" on top of the PR1 defaults without rebuilding the
    registry from scratch).
    """

    def __init__(self) -> None:
        self._entries: dict[str, ScorerEntry] = {}

    def register(self, scorer: Scorer, *, weight: float | None = None) -> None:
        if not scorer.name:
            raise ValueError("scorer.name must be non-empty")
        w = weight if weight is not None else scorer.weight
        if w < 0:
            raise ValueError(f"scorer {scorer.name!r} weight must be >= 0, got {w}")
        self._entries[scorer.name] = ScorerEntry(scorer=scorer, weight=w)

    def get(self, name: str) -> ScorerEntry:
        try:
            return self._entries[name]
        except KeyError as exc:
            raise KeyError(
                f"no scorer registered under {name!r}; known: {sorted(self._entries)}"
            ) from exc

    def all(self) -> list[ScorerEntry]:
        return list(self._entries.values())

    def weights(self) -> dict[str, float]:
        return {name: entry.weight for name, entry in self._entries.items()}

    def score(self, artifacts: IssueArtifacts) -> dict[str, Score]:
        """Score one issue under every registered scorer.

        The order of the returned dict is the registration order; this
        is stable enough for tests and for the JSON-serializable run
        record. The runner can then pass the result to
        :func:`aggregate_weighted`.
        """
        return {name: entry.score(artifacts) for name, entry in self._entries.items()}

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._entries
