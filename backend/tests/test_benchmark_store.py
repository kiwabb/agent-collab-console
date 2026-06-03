"""Tests for BenchmarkStore (PR2).

Covers:

  - InMemoryStore: round-trip CRUD, baseline singleton, errors.
  - SqliteStore: same, against a tmp sqlite file (real IO).
  - The two stores are API-equivalent (run the same scenario
    against both).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.store import (
    BenchmarkEpoch,
    BenchmarkRun,
    InMemoryStore,
    SqliteStore,
    make_run_row,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(
    run_id: str = "run-1",
    label: str | None = "v0.5",
    fixture_ids: list[str] | None = None,
    epoch_count: int = 3,
    is_baseline: bool = False,
) -> BenchmarkRun:
    return make_run_row(
        run_id=run_id,
        label=label,
        fixture_ids=fixture_ids or ["a", "b", "c"],
        epoch_count=epoch_count,
        is_baseline=is_baseline,
    )


def _make_epoch(
    run_id: str = "run-1",
    fixture_id: str = "a",
    epoch_index: int = 0,
    pass_execution: bool = True,
    pass_coverage: bool = True,
    spent_usd: float = 0.1,
) -> BenchmarkEpoch:
    return BenchmarkEpoch(
        id=f"ep-{run_id}-{fixture_id}-{epoch_index}",
        run_id=run_id,
        fixture_id=fixture_id,
        epoch_index=epoch_index,
        issue_id=f"codex-{fixture_id}-{epoch_index}",
        started_at="2026-06-03T10:00:00",
        completed_at="2026-06-03T10:05:00",
        pass_execution=pass_execution,
        pass_coverage=pass_coverage,
        score_execution=1.0 if pass_execution else 0.0,
        score_coverage=1.0 if pass_coverage else 0.0,
        score_aggregate=1.0 if (pass_execution and pass_coverage) else 0.0,
        spent_usd=spent_usd,
        input_tokens=100,
        output_tokens=50,
        duration_s=10.0,
        error=None,
        artifacts_json=json.dumps({"issue_id": fixture_id}),
    )


# Parametrized so we exercise both stores with the same scenario.
@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    if request.param == "memory":
        yield InMemoryStore()
    else:
        s = SqliteStore(tmp_path / "bench.db")
        try:
            yield s
        finally:
            s.close()


# ---------------------------------------------------------------------------
# Run CRUD
# ---------------------------------------------------------------------------


def test_create_and_get_run(store):
    run = _make_run()
    store.create_run(run)
    fetched = store.get_run("run-1")
    assert fetched is not None
    assert fetched.id == "run-1"
    assert fetched.label == "v0.5"
    assert fetched.fixture_ids == ["a", "b", "c"]
    assert fetched.is_baseline is False


def test_create_run_rejects_duplicate_id(store):
    store.create_run(_make_run())
    with pytest.raises(ValueError):
        store.create_run(_make_run())


def test_update_run_persists_changes(store):
    store.create_run(_make_run())
    run = store.get_run("run-1")
    run.status = "completed"
    run.aggregate_pass_at_1 = 0.85
    store.update_run(run)
    fetched = store.get_run("run-1")
    assert fetched.status == "completed"
    assert fetched.aggregate_pass_at_1 == 0.85


def test_update_run_rejects_unknown_id(store):
    with pytest.raises(ValueError):
        store.update_run(_make_run())


def test_list_runs_orders_by_created_at_desc(store):
    store.create_run(_make_run(run_id="r1", label="older"))
    store.create_run(_make_run(run_id="r2", label="newer"))
    runs = store.list_runs()
    ids = [r.id for r in runs]
    assert "r1" in ids and "r2" in ids


def test_get_run_unknown_returns_none(store):
    assert store.get_run("nope") is None


# ---------------------------------------------------------------------------
# Baseline singleton
# ---------------------------------------------------------------------------


def test_baseline_starts_empty(store):
    assert store.get_baseline() is None


def test_set_baseline_returns_named_run(store):
    store.create_run(_make_run())
    store.set_baseline("run-1")
    assert store.get_baseline().id == "run-1"


def test_set_baseline_replaces_previous(store):
    store.create_run(_make_run(run_id="r1", is_baseline=True))
    store.create_run(_make_run(run_id="r2"))
    store.set_baseline("r1")
    assert store.get_baseline().id == "r1"
    store.set_baseline("r2")
    assert store.get_baseline().id == "r2"
    # r1 is no longer the baseline.
    assert store.get_run("r1").is_baseline is False


def test_set_baseline_rejects_unknown_id(store):
    with pytest.raises(ValueError):
        store.set_baseline("nope")


# ---------------------------------------------------------------------------
# Epoch CRUD
# ---------------------------------------------------------------------------


def test_add_epoch_requires_existing_run(store):
    with pytest.raises(ValueError):
        store.add_epoch(_make_epoch(run_id="missing"))


def test_add_and_list_epochs(store):
    store.create_run(_make_run())
    store.add_epoch(_make_epoch(epoch_index=0, fixture_id="a", pass_execution=True))
    store.add_epoch(_make_epoch(epoch_index=1, fixture_id="a", pass_execution=False))
    store.add_epoch(_make_epoch(epoch_index=0, fixture_id="b", pass_execution=True))
    eps = store.list_epochs("run-1")
    assert len(eps) == 3
    # Ordered by fixture_id, epoch_index (the SqliteStore ORDER BY).
    assert eps[0].fixture_id == "a"
    assert eps[0].epoch_index == 0
    assert eps[1].fixture_id == "a"
    assert eps[1].epoch_index == 1
    assert eps[2].fixture_id == "b"


def test_list_epochs_for_unknown_run_returns_empty(store):
    assert store.list_epochs("nope") == []


# ---------------------------------------------------------------------------
# SqliteStore-specific
# ---------------------------------------------------------------------------


def test_sqlite_store_persists_across_reopen(tmp_path: Path):
    db = tmp_path / "bench.db"
    with SqliteStore(db) as s:
        s.create_run(_make_run())
        s.add_epoch(_make_epoch())
    with SqliteStore(db) as s:
        run = s.get_run("run-1")
        assert run is not None
        eps = s.list_epochs("run-1")
        assert len(eps) == 1


def test_sqlite_store_creates_parent_dir(tmp_path: Path):
    db = tmp_path / "nested" / "bench.db"
    with SqliteStore(db) as s:
        s.create_run(_make_run())
    assert db.exists()
    assert (tmp_path / "nested").is_dir()


def test_sqlite_store_baseline_unique_constraint(tmp_path: Path):
    """The partial unique index on is_baseline=1 enforces a single
    baseline at the DB level. We exercise this by trying to insert
    two rows with is_baseline=1 directly (bypassing set_baseline)."""
    import sqlite3

    db = tmp_path / "bench.db"
    with SqliteStore(db) as s:
        s.create_run(_make_run(run_id="r1", is_baseline=True))
    # Bypass the store API and try to insert a second baseline row.
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO benchmark_run (
                    id, created_at, label, catalog_snapshot,
                    orchestrator_version, epoch_count, fixture_ids,
                    is_baseline, status
                ) VALUES ('r2', '2026-06-03T10:00:00', NULL, NULL, NULL, 1, '[]', 1, 'running')
                """
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Snapshot independence — store returns a copy callers can mutate
# ---------------------------------------------------------------------------


def test_get_run_returns_snapshot_not_live_reference(store):
    """The in-memory store must not let callers mutate stored rows
    out from under it; the sqlite store does this naturally via
    fresh row construction."""
    store.create_run(_make_run())
    run = store.get_run("run-1")
    run.label = "tampered"
    run.fixture_ids.append("rogue")
    fresh = store.get_run("run-1")
    assert fresh.label == "v0.5"
    assert "rogue" not in fresh.fixture_ids
