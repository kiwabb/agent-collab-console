"""Loader for checked-in golden fixtures.

Fixtures live at ``backend/benchmark/golden/<id>.json`` (one file per
golden issue). The loader is lazy by default so unit tests can build
a temp directory of fixtures and load only those. The default
discovery root is the package's own ``golden/`` directory.

The loader **validates every file at load time** via the Pydantic
``GoldenIssue`` schema. A malformed fixture fails loudly on import —
we never want a typo to silently drop a fixture from the leaderboard.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .golden_schema import GoldenIssue


# Default fixture directory, derived from this file's location so the
# loader works whether the package is installed editable or vendored.
DEFAULT_GOLDEN_DIR: Path = Path(__file__).parent / "golden"


class GoldenFixtureError(ValueError):
    """Raised when a checked-in fixture is malformed.

    Wraps the underlying Pydantic validation error so the test can
    match on a single exception type and still see the original
    message via ``__cause__``.
    """


def _read_one(path: Path) -> GoldenIssue:
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    try:
        return GoldenIssue.model_validate(data)
    except Exception as exc:
        raise GoldenFixtureError(
            f"fixture {path.name!r} failed schema validation: {exc}"
        ) from exc


def load_golden(path: Path) -> GoldenIssue:
    """Load and validate a single fixture file."""
    return _read_one(path)


def load_all(
    root: Path | None = None,
    *,
    ids: Iterable[str] | None = None,
) -> list[GoldenIssue]:
    """Load every fixture under ``root`` (default: the package's golden
    directory) and return them in stable order (by ``id``).

    Args:
        root: directory containing ``<id>.json`` files. Defaults to
            :data:`DEFAULT_GOLDEN_DIR`.
        ids: optional whitelist. When set, only fixtures whose id is
            in the whitelist are returned (the others are still
            validated, to catch typos early).

    Returns:
        The validated fixtures, sorted by ``id`` for stable
        iteration in tests and in the runner's per-epoch schedule.
    """
    root = root or DEFAULT_GOLDEN_DIR
    if not root.is_dir():
        raise GoldenFixtureError(f"golden fixture directory not found: {root}")
    wanted = set(ids) if ids is not None else None
    out: list[GoldenIssue] = []
    for path in sorted(root.glob("*.json")):
        # Even fixtures outside the whitelist are validated (so a typo
        # in the whitelist doesn't mask a malformed file).
        fixture = _read_one(path)
        if wanted is not None and fixture.id not in wanted:
            continue
        out.append(fixture)
    out.sort(key=lambda f: f.id)
    return out


def ids(root: Path | None = None) -> list[str]:
    """Return the ids of every checked-in fixture (stable order)."""
    return [f.id for f in load_all(root)]
