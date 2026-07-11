"""Persistence for benchmark runs.

The benchmark harness needs to record:

  - Each ``BenchmarkRun`` (one per CLI invocation) with metadata
    (label, epoch count, fixture set, baseline flag, status).
  - Each ``BenchmarkEpoch`` (one per (run, fixture, epoch_index))
    with the pass/fail booleans, scores, cost, tokens, duration,
    and the full ``IssueArtifacts`` snapshot for debugging.

The store is **separate from the production ``console.db``**: the
benchmark DB lives at ``backend/benchmark.db`` by default and
uses its own schema. This keeps the production migration surface
clean and lets operators blow away the benchmark DB without
touching the conductor / codex state.

Two implementations:

  - :class:`InMemoryStore` — for unit tests. Zero IO, thread-safe
    by virtue of the single-threaded test runner.
  - :class:`SqliteStore` — for prod. Uses ``sqlite3`` directly
    (sync, in the CLI process). The CLI is offline batch, so a
    sync interface is fine; the conductor's async store is
    unaffected.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import asdict, dataclass, field  # noqa: F401
from datetime import datetime
from pathlib import Path
from typing import Iterable, Protocol, runtime_checkable  # noqa: F401, UP035

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Row types
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkRun:
    id: str
    created_at: str  # ISO-8601
    label: str | None
    catalog_snapshot: str | None  # JSON
    orchestrator_version: str | None
    epoch_count: int
    fixture_ids: list[str]  # stored as JSON
    is_baseline: bool
    is_synthetic: bool
    status: str  # "running" | "completed" | "failed"
    notes: str | None = None
    # Aggregate (filled in on completion):
    aggregate_pass_at_1: float | None = None
    aggregate_pass_at_1_stderr: float | None = None
    cost_total_usd: float | None = None
    cost_per_issue_usd: float | None = None
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    total_duration_s: float | None = None


@dataclass
class BenchmarkEpoch:
    id: str
    run_id: str
    fixture_id: str
    epoch_index: int
    issue_id: str | None
    started_at: str | None
    completed_at: str | None
    pass_execution: bool
    pass_coverage: bool
    score_execution: float
    score_coverage: float
    score_aggregate: float
    spent_usd: float
    input_tokens: int
    output_tokens: int
    duration_s: float
    error: str | None
    artifacts_json: str | None  # JSON dump for debug


# ---------------------------------------------------------------------------
# Store protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class BenchmarkStore(Protocol):
    """The minimal surface the runner needs.

    The runner inserts runs up front, appends epoch rows as they
    complete, and finalises the run with aggregate metrics at the
    end. Reads are used by the leaderboard / diff view (PR4).
    """

    def create_run(self, run: BenchmarkRun) -> None: ...
    def update_run(self, run: BenchmarkRun) -> None: ...
    def get_run(self, run_id: str) -> BenchmarkRun | None: ...
    def list_runs(self) -> list[BenchmarkRun]: ...
    def get_baseline(self) -> BenchmarkRun | None: ...
    def set_baseline(self, run_id: str) -> None: ...
    def add_epoch(self, epoch: BenchmarkEpoch) -> None: ...
    def list_epochs(self, run_id: str) -> list[BenchmarkEpoch]: ...
    def close(self) -> None: ...


# ---------------------------------------------------------------------------
# In-memory store (for tests)
# ---------------------------------------------------------------------------


class InMemoryStore:
    """A trivial thread-safe in-memory store. State is lost on close()."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, BenchmarkRun] = {}
        self._epochs: dict[str, list[BenchmarkEpoch]] = {}  # run_id -> epochs
        self._baseline_id: str | None = None

    def _snapshot_run(self, run: BenchmarkRun) -> BenchmarkRun:
        # dataclasses.replace-style deep-ish copy: callers should not
        # be able to mutate stored rows out from under us.
        return BenchmarkRun(
            id=run.id,
            created_at=run.created_at,
            label=run.label,
            catalog_snapshot=run.catalog_snapshot,
            orchestrator_version=run.orchestrator_version,
            epoch_count=run.epoch_count,
            fixture_ids=list(run.fixture_ids),
            is_baseline=run.is_baseline,
            is_synthetic=run.is_synthetic,
            status=run.status,
            notes=run.notes,
            aggregate_pass_at_1=run.aggregate_pass_at_1,
            aggregate_pass_at_1_stderr=run.aggregate_pass_at_1_stderr,
            cost_total_usd=run.cost_total_usd,
            cost_per_issue_usd=run.cost_per_issue_usd,
            total_input_tokens=run.total_input_tokens,
            total_output_tokens=run.total_output_tokens,
            total_duration_s=run.total_duration_s,
        )

    def _snapshot_epoch(self, epoch: BenchmarkEpoch) -> BenchmarkEpoch:
        return BenchmarkEpoch(
            id=epoch.id,
            run_id=epoch.run_id,
            fixture_id=epoch.fixture_id,
            epoch_index=epoch.epoch_index,
            issue_id=epoch.issue_id,
            started_at=epoch.started_at,
            completed_at=epoch.completed_at,
            pass_execution=epoch.pass_execution,
            pass_coverage=epoch.pass_coverage,
            score_execution=epoch.score_execution,
            score_coverage=epoch.score_coverage,
            score_aggregate=epoch.score_aggregate,
            spent_usd=epoch.spent_usd,
            input_tokens=epoch.input_tokens,
            output_tokens=epoch.output_tokens,
            duration_s=epoch.duration_s,
            error=epoch.error,
            artifacts_json=epoch.artifacts_json,
        )

    def create_run(self, run: BenchmarkRun) -> None:
        with self._lock:
            if run.is_baseline and run.is_synthetic:
                raise ValueError("synthetic benchmark runs cannot be baselines")
            if run.id in self._runs:
                raise ValueError(f"run {run.id!r} already exists")
            self._runs[run.id] = self._snapshot_run(run)
            self._epochs[run.id] = []

    def update_run(self, run: BenchmarkRun) -> None:
        with self._lock:
            if run.is_baseline and run.is_synthetic:
                raise ValueError("synthetic benchmark runs cannot be baselines")
            if run.id not in self._runs:
                raise ValueError(f"run {run.id!r} does not exist")
            self._runs[run.id] = self._snapshot_run(run)

    def get_run(self, run_id: str) -> BenchmarkRun | None:
        with self._lock:
            r = self._runs.get(run_id)
            return self._snapshot_run(r) if r else None

    def list_runs(self) -> list[BenchmarkRun]:
        with self._lock:
            return [self._snapshot_run(r) for r in self._runs.values()]

    def get_baseline(self) -> BenchmarkRun | None:
        with self._lock:
            if self._baseline_id is None:
                return None
            r = self._runs.get(self._baseline_id)
            return self._snapshot_run(r) if r else None

    def set_baseline(self, run_id: str) -> None:
        with self._lock:
            if run_id not in self._runs:
                raise ValueError(f"run {run_id!r} does not exist")
            if self._runs[run_id].is_synthetic:
                raise ValueError("synthetic benchmark runs cannot be baselines")
            # Clear the prior baseline row's flag (the snapshot model
            # means we need to overwrite the stored row, not the
            # caller's local copy).
            if self._baseline_id is not None and self._baseline_id != run_id:
                prior = self._runs[self._baseline_id]
                self._runs[self._baseline_id] = BenchmarkRun(
                    **{**asdict(prior), "is_baseline": False}
                )
            # Set the new baseline row's flag.
            new = self._runs[run_id]
            self._runs[run_id] = BenchmarkRun(**{**asdict(new), "is_baseline": True})
            self._baseline_id = run_id

    def add_epoch(self, epoch: BenchmarkEpoch) -> None:
        with self._lock:
            if epoch.run_id not in self._runs:
                raise ValueError(f"run {epoch.run_id!r} does not exist")
            self._epochs[epoch.run_id].append(self._snapshot_epoch(epoch))

    def list_epochs(self, run_id: str) -> list[BenchmarkEpoch]:
        with self._lock:
            return [self._snapshot_epoch(e) for e in self._epochs.get(run_id, [])]

    def close(self) -> None:
        # No-op for in-memory.
        pass


# ---------------------------------------------------------------------------
# SQLite store
# ---------------------------------------------------------------------------


_SCHEMA = """
CREATE TABLE IF NOT EXISTS benchmark_run (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    label TEXT,
    catalog_snapshot TEXT,
    orchestrator_version TEXT,
    epoch_count INTEGER NOT NULL,
    fixture_ids TEXT NOT NULL,
    is_baseline INTEGER NOT NULL DEFAULT 0,
    is_synthetic INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    notes TEXT,
    aggregate_pass_at_1 REAL,
    aggregate_pass_at_1_stderr REAL,
    cost_total_usd REAL,
    cost_per_issue_usd REAL,
    total_input_tokens INTEGER,
    total_output_tokens INTEGER,
    total_duration_s REAL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_benchmark_run_one_baseline
    ON benchmark_run (is_baseline) WHERE is_baseline = 1;

CREATE TABLE IF NOT EXISTS benchmark_epoch (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES benchmark_run(id) ON DELETE CASCADE,
    fixture_id TEXT NOT NULL,
    epoch_index INTEGER NOT NULL,
    issue_id TEXT,
    started_at TEXT,
    completed_at TEXT,
    pass_execution INTEGER NOT NULL,
    pass_coverage INTEGER NOT NULL,
    score_execution REAL NOT NULL,
    score_coverage REAL NOT NULL,
    score_aggregate REAL NOT NULL,
    spent_usd REAL NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    duration_s REAL NOT NULL,
    error TEXT,
    artifacts_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_benchmark_epoch_run
    ON benchmark_epoch (run_id, fixture_id, epoch_index);
"""


def _row_to_run(row: sqlite3.Row) -> BenchmarkRun:
    return BenchmarkRun(
        id=row["id"],
        created_at=row["created_at"],
        label=row["label"],
        catalog_snapshot=row["catalog_snapshot"],
        orchestrator_version=row["orchestrator_version"],
        epoch_count=row["epoch_count"],
        fixture_ids=json.loads(row["fixture_ids"]),
        is_baseline=bool(row["is_baseline"]),
        is_synthetic=bool(row["is_synthetic"]),
        status=row["status"],
        notes=row["notes"],
        aggregate_pass_at_1=row["aggregate_pass_at_1"],
        aggregate_pass_at_1_stderr=row["aggregate_pass_at_1_stderr"],
        cost_total_usd=row["cost_total_usd"],
        cost_per_issue_usd=row["cost_per_issue_usd"],
        total_input_tokens=row["total_input_tokens"],
        total_output_tokens=row["total_output_tokens"],
        total_duration_s=row["total_duration_s"],
    )


def _row_to_epoch(row: sqlite3.Row) -> BenchmarkEpoch:
    return BenchmarkEpoch(
        id=row["id"],
        run_id=row["run_id"],
        fixture_id=row["fixture_id"],
        epoch_index=row["epoch_index"],
        issue_id=row["issue_id"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        pass_execution=bool(row["pass_execution"]),
        pass_coverage=bool(row["pass_coverage"]),
        score_execution=row["score_execution"],
        score_coverage=row["score_coverage"],
        score_aggregate=row["score_aggregate"],
        spent_usd=row["spent_usd"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        duration_s=row["duration_s"],
        error=row["error"],
        artifacts_json=row["artifacts_json"],
    )


class SqliteStore:
    """Sync sqlite3-backed BenchmarkStore. One file = one DB."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # ``check_same_thread=False`` so the CLI can hand the
        # connection across threads if a future change adds async
        # dispatch; the CLI today is single-threaded.
        self._conn = sqlite3.connect(
            str(self._path),
            detect_types=sqlite3.PARSE_DECLTYPES,
            check_same_thread=False,
        )
        # FK enforcement is OFF by default in sqlite3. Turn it on so
        # the benchmark_epoch.run_id FK fires (without this, an
        # epoch with a missing run_id silently inserts).
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(benchmark_run)")}
        if "is_synthetic" not in columns:
            self._conn.execute(
                "ALTER TABLE benchmark_run ADD COLUMN is_synthetic INTEGER NOT NULL DEFAULT 0"
            )
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            logger.debug("benchmark sqlite close failed", exc_info=True)

    def __enter__(self) -> "SqliteStore":  # noqa: UP037
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _run_params(self, r: BenchmarkRun) -> tuple[object, ...]:
        return (
            r.id,
            r.created_at,
            r.label,
            r.catalog_snapshot,
            r.orchestrator_version,
            r.epoch_count,
            json.dumps(r.fixture_ids),
            1 if r.is_baseline else 0,
            1 if r.is_synthetic else 0,
            r.status,
            r.notes,
            r.aggregate_pass_at_1,
            r.aggregate_pass_at_1_stderr,
            r.cost_total_usd,
            r.cost_per_issue_usd,
            r.total_input_tokens,
            r.total_output_tokens,
            r.total_duration_s,
        )

    def create_run(self, run: BenchmarkRun) -> None:
        if run.is_baseline and run.is_synthetic:
            raise ValueError("synthetic benchmark runs cannot be baselines")
        # SQLite raises IntegrityError on duplicate id, but the
        # in-memory store raises ValueError — keep the API uniform.
        existing = self._conn.execute(
            "SELECT 1 FROM benchmark_run WHERE id = ?", (run.id,)
        ).fetchone()
        if existing is not None:
            raise ValueError(f"run {run.id!r} already exists")
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO benchmark_run (
                    id, created_at, label, catalog_snapshot,
                    orchestrator_version, epoch_count, fixture_ids,
                    is_baseline, is_synthetic, status, notes,
                    aggregate_pass_at_1, aggregate_pass_at_1_stderr,
                    cost_total_usd, cost_per_issue_usd,
                    total_input_tokens, total_output_tokens,
                    total_duration_s
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._run_params(run),
            )

    def update_run(self, run: BenchmarkRun) -> None:
        if run.is_baseline and run.is_synthetic:
            raise ValueError("synthetic benchmark runs cannot be baselines")
        with self._conn:
            cur = self._conn.execute(
                """
                UPDATE benchmark_run SET
                    label = ?, catalog_snapshot = ?, orchestrator_version = ?,
                    epoch_count = ?, fixture_ids = ?, is_baseline = ?, is_synthetic = ?,
                    status = ?, notes = ?,
                    aggregate_pass_at_1 = ?, aggregate_pass_at_1_stderr = ?,
                    cost_total_usd = ?, cost_per_issue_usd = ?,
                    total_input_tokens = ?, total_output_tokens = ?,
                    total_duration_s = ?
                WHERE id = ?
                """,
                (
                    run.label,
                    run.catalog_snapshot,
                    run.orchestrator_version,
                    run.epoch_count,
                    json.dumps(run.fixture_ids),
                    1 if run.is_baseline else 0,
                    1 if run.is_synthetic else 0,
                    run.status,
                    run.notes,
                    run.aggregate_pass_at_1,
                    run.aggregate_pass_at_1_stderr,
                    run.cost_total_usd,
                    run.cost_per_issue_usd,
                    run.total_input_tokens,
                    run.total_output_tokens,
                    run.total_duration_s,
                    run.id,
                ),
            )
            if cur.rowcount == 0:
                raise ValueError(f"run {run.id!r} does not exist")

    def get_run(self, run_id: str) -> BenchmarkRun | None:
        row = self._conn.execute("SELECT * FROM benchmark_run WHERE id = ?", (run_id,)).fetchone()
        return _row_to_run(row) if row else None

    def list_runs(self) -> list[BenchmarkRun]:
        rows = self._conn.execute("SELECT * FROM benchmark_run ORDER BY created_at DESC").fetchall()
        return [_row_to_run(r) for r in rows]

    def get_baseline(self) -> BenchmarkRun | None:
        row = self._conn.execute("SELECT * FROM benchmark_run WHERE is_baseline = 1").fetchone()
        return _row_to_run(row) if row else None

    def set_baseline(self, run_id: str) -> None:
        # Validate existence first; the partial unique index would
        # also catch this but the message is opaque.
        existing = self._conn.execute(
            "SELECT is_synthetic FROM benchmark_run WHERE id = ?", (run_id,)
        ).fetchone()
        if existing is None:
            raise ValueError(f"run {run_id!r} does not exist")
        if bool(existing["is_synthetic"]):
            raise ValueError("synthetic benchmark runs cannot be baselines")
        with self._conn:
            # Clear any existing baseline first (the partial unique
            # index would block two baselines anyway, but being
            # explicit makes the transaction intent clear).
            self._conn.execute("UPDATE benchmark_run SET is_baseline = 0")
            self._conn.execute(
                "UPDATE benchmark_run SET is_baseline = 1 WHERE id = ?",
                (run_id,),
            )

    def add_epoch(self, epoch: BenchmarkEpoch) -> None:
        # Validate the FK at the Python layer (with PRAGMA foreign_keys
        # = ON the DB would also catch this, but the IntegrityError
        # message is opaque). Same uniform ValueError the in-memory
        # store raises.
        existing = self._conn.execute(
            "SELECT 1 FROM benchmark_run WHERE id = ?", (epoch.run_id,)
        ).fetchone()
        if existing is None:
            raise ValueError(f"run {epoch.run_id!r} does not exist")
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO benchmark_epoch (
                    id, run_id, fixture_id, epoch_index, issue_id,
                    started_at, completed_at,
                    pass_execution, pass_coverage,
                    score_execution, score_coverage, score_aggregate,
                    spent_usd, input_tokens, output_tokens, duration_s,
                    error, artifacts_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    epoch.id,
                    epoch.run_id,
                    epoch.fixture_id,
                    epoch.epoch_index,
                    epoch.issue_id,
                    epoch.started_at,
                    epoch.completed_at,
                    1 if epoch.pass_execution else 0,
                    1 if epoch.pass_coverage else 0,
                    epoch.score_execution,
                    epoch.score_coverage,
                    epoch.score_aggregate,
                    epoch.spent_usd,
                    epoch.input_tokens,
                    epoch.output_tokens,
                    epoch.duration_s,
                    epoch.error,
                    epoch.artifacts_json,
                ),
            )

    def list_epochs(self, run_id: str) -> list[BenchmarkEpoch]:
        rows = self._conn.execute(
            """
            SELECT * FROM benchmark_epoch
            WHERE run_id = ?
            ORDER BY fixture_id, epoch_index
            """,
            (run_id,),
        ).fetchall()
        return [_row_to_epoch(r) for r in rows]


# ---------------------------------------------------------------------------
# Helpers — build rows from a finished run
# ---------------------------------------------------------------------------


def make_run_row(
    *,
    run_id: str,
    label: str | None,
    fixture_ids: list[str],
    epoch_count: int,
    is_baseline: bool = False,
    is_synthetic: bool = False,
    status: str = "running",
    notes: str | None = None,
    catalog_snapshot: str | None = None,
    orchestrator_version: str | None = None,
) -> BenchmarkRun:
    """Convenience constructor for the runner. The aggregate fields
    are filled in by the runner at completion; the row is created
    up front so the store has a stable id before any epoch rows
    land (the ``benchmark_epoch.run_id`` FK needs it)."""
    return BenchmarkRun(
        id=run_id,
        created_at=datetime.now().isoformat(timespec="seconds"),
        label=label,
        catalog_snapshot=catalog_snapshot,
        orchestrator_version=orchestrator_version,
        epoch_count=epoch_count,
        fixture_ids=list(fixture_ids),
        is_baseline=is_baseline,
        is_synthetic=is_synthetic,
        status=status,
        notes=notes,
    )
