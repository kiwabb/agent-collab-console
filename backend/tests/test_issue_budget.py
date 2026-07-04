"""Per-issue budget awareness (cost-aware conductor scheduling, PR2).

Covers:
  - issue.budget_usd round-trip (sync + async stores)
  - idempotent migration (legacy DB with no budget_usd column)
  - budget resolution: unset -> global default; explicit -> override
  - issue spend aggregation: only completed runs are summed
  - timeouts knob invariants
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from uuid import uuid4

import pytest

from app.application import timeouts
from app.domain.models import CodexIssue, CodexTask, ExecutionProcess


def _make_issue(budget_usd: float | None = None) -> CodexIssue:
    now = datetime.now()
    return CodexIssue(
        id=str(uuid4()),
        session_id="sess-budget",
        project_id="proj-budget",
        title="Budgeted issue",
        description="desc",
        status="open",
        budget_usd=budget_usd,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Model + resolution
# ---------------------------------------------------------------------------


def test_issue_budget_defaults_to_none():
    issue = CodexIssue(id="i", session_id="s", title="t")
    assert issue.budget_usd is None


def test_resolve_issue_budget_unset_uses_global_default():
    assert timeouts.resolve_issue_budget_usd(None) == timeouts.default_issue_budget_usd()


def test_resolve_issue_budget_explicit_overrides_default():
    assert timeouts.resolve_issue_budget_usd(2.5) == 2.5


def test_resolve_issue_budget_zero_means_no_ceiling():
    # 0 is an explicit value (not None), so it is preserved as "no ceiling".
    assert timeouts.resolve_issue_budget_usd(0.0) == 0.0


# ---------------------------------------------------------------------------
# Sync store round-trip + migration
# ---------------------------------------------------------------------------


def test_sync_store_roundtrips_budget(tmp_path):
    from app.adapters.sqlite_store import SQLiteStore

    store = SQLiteStore(str(tmp_path / "budget.db"))
    issue = _make_issue(budget_usd=7.25)
    store.save_codex_issue(issue)

    loaded = store.load_codex_issue(issue.id)
    assert loaded is not None
    assert loaded.budget_usd == 7.25

    # Unset budget round-trips as None (not 0/global-default at storage layer).
    issue2 = _make_issue(budget_usd=None)
    store.save_codex_issue(issue2)
    loaded2 = store.load_codex_issue(issue2.id)
    assert loaded2 is not None
    assert loaded2.budget_usd is None


def test_sync_store_migrates_legacy_issue_without_budget_column(tmp_path):
    """A pre-migration DB without budget_usd opens cleanly and reports None."""
    db_path = tmp_path / "legacy_budget.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE codex_issues (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            current_phase TEXT NOT NULL DEFAULT 'requirements',
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT,
            updated_at TEXT
        );
        INSERT INTO codex_issues (id, session_id, title, current_phase, status, created_at, updated_at)
        VALUES ('legacy-i', 's-1', 'old issue', 'requirements', 'open', '2026-01-01T00:00:00', '2026-01-01T00:00:00');
        """
    )
    conn.commit()
    conn.close()

    from app.adapters.sqlite_store import SQLiteStore

    store = SQLiteStore(str(db_path))
    loaded = store.load_codex_issue("legacy-i")
    assert loaded is not None
    assert loaded.budget_usd is None

    # Re-opening the same DB must not raise (migration is idempotent).
    store2 = SQLiteStore(str(db_path))
    again = store2.load_codex_issue("legacy-i")
    assert again is not None
    assert again.budget_usd is None


# ---------------------------------------------------------------------------
# Async store round-trip + migration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_store_roundtrips_budget(tmp_path):
    from app.adapters.async_sqlite_store import AsyncSQLiteStore

    store = AsyncSQLiteStore(str(tmp_path / "budget_async.db"))
    try:
        issue = _make_issue(budget_usd=3.5)
        await store.save_codex_issue(issue)
        loaded = await store.load_codex_issue(issue.id)
        assert loaded is not None
        assert loaded.budget_usd == 3.5

        issue2 = _make_issue(budget_usd=None)
        await store.save_codex_issue(issue2)
        loaded2 = await store.load_codex_issue(issue2.id)
        assert loaded2 is not None
        assert loaded2.budget_usd is None

        listed = await store.list_codex_issues(session_id="sess-budget")
        by_id = {r["id"]: r for r in listed}
        assert by_id[issue.id]["budget_usd"] == 3.5
        assert by_id[issue2.id]["budget_usd"] is None
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_async_store_budget_migration_is_idempotent(tmp_path):
    """Re-opening the same DB re-runs ALTER ... ADD COLUMN budget_usd without error.

    Note: the async store performs a one-time legacy-data wipe for rows missing
    project_id (schema version < 2), so we exercise migration idempotency by
    persisting a real row, then re-opening the store (which re-runs migrations)
    and confirming the row + new column survive.
    """
    from app.adapters.async_sqlite_store import AsyncSQLiteStore

    db_path = tmp_path / "idempotent_budget_async.db"
    store = AsyncSQLiteStore(str(db_path))
    try:
        issue = _make_issue(budget_usd=6.5)
        await store.save_codex_issue(issue)
    finally:
        await store.close()

    # Second open re-runs migrations against an existing budget_usd column.
    store2 = AsyncSQLiteStore(str(db_path))
    try:
        loaded = await store2.load_codex_issue(issue.id)
        assert loaded is not None
        assert loaded.budget_usd == 6.5
    finally:
        await store2.close()


# ---------------------------------------------------------------------------
# Spend aggregation: only completed runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aggregate_issue_spend_sums_only_completed_runs(tmp_path):
    from app.adapters.async_sqlite_store import AsyncSQLiteStore
    from app.application.budget_service import aggregate_issue_spend_usd

    store = AsyncSQLiteStore(str(tmp_path / "spend.db"))
    try:
        issue = _make_issue(budget_usd=10.0)
        await store.save_codex_issue(issue)

        task = CodexTask(
            id="task-1",
            session_id=issue.session_id,
            project_id=issue.project_id,
            issue_id=issue.id,
            title="impl",
            prompt="do it",
        )
        await store.save_codex_task(task)

        now = datetime.now()
        # Completed runs: counted.
        await store.save_execution_process(
            ExecutionProcess(
                id="ep-done-1",
                task_id=task.id,
                session_id=issue.session_id,
                status="Completed",
                total_cost_usd=1.50,
                created_at=now,
                updated_at=now,
            )
        )
        await store.save_execution_process(
            ExecutionProcess(
                id="ep-failed-1",
                task_id=task.id,
                session_id=issue.session_id,
                status="Failed",
                total_cost_usd=0.25,
                created_at=now,
                updated_at=now,
            )
        )
        await store.save_execution_process(
            ExecutionProcess(
                id="ep-killed-1",
                task_id=task.id,
                session_id=issue.session_id,
                status="Killed",
                total_cost_usd=0.25,
                created_at=now,
                updated_at=now,
            )
        )
        await store.save_execution_process(
            ExecutionProcess(
                id="ep-cancelled-1",
                task_id=task.id,
                session_id=issue.session_id,
                status="Cancelled",
                total_cost_usd=0.50,
                created_at=now,
                updated_at=now,
            )
        )
        # Running run: NOT counted (cost not yet final).
        await store.save_execution_process(
            ExecutionProcess(
                id="ep-running-1",
                task_id=task.id,
                session_id=issue.session_id,
                status="Running",
                total_cost_usd=99.0,
                created_at=now,
                updated_at=now,
            )
        )
        # Completed run with no cost recorded: contributes 0.
        await store.save_execution_process(
            ExecutionProcess(
                id="ep-done-nocost",
                task_id=task.id,
                session_id=issue.session_id,
                status="Completed",
                total_cost_usd=None,
                created_at=now,
                updated_at=now,
            )
        )

        spend = await aggregate_issue_spend_usd(store, issue.id)
        assert spend == pytest.approx(2.5)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_compute_budget_status_unset_uses_global_default(tmp_path):
    from app.adapters.async_sqlite_store import AsyncSQLiteStore
    from app.application.budget_service import compute_issue_budget_status

    store = AsyncSQLiteStore(str(tmp_path / "status.db"))
    try:
        issue = _make_issue(budget_usd=None)
        await store.save_codex_issue(issue)

        status = await compute_issue_budget_status(store, issue)
        assert status.budget_source == "default"
        assert status.budget_usd == timeouts.default_issue_budget_usd()
        assert status.spent_usd == 0.0
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_compute_budget_status_explicit_override(tmp_path):
    from app.adapters.async_sqlite_store import AsyncSQLiteStore
    from app.application.budget_service import compute_issue_budget_status

    store = AsyncSQLiteStore(str(tmp_path / "status2.db"))
    try:
        issue = _make_issue(budget_usd=4.0)
        await store.save_codex_issue(issue)
        status = await compute_issue_budget_status(store, issue)
        assert status.budget_source == "issue"
        assert status.budget_usd == 4.0
        assert status.has_ceiling
        assert status.remaining_usd == 4.0
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_compute_budget_status_reserves_running_process_estimate(tmp_path, monkeypatch):
    from app.adapters.async_sqlite_store import AsyncSQLiteStore
    from app.application.budget_service import compute_issue_budget_status

    monkeypatch.setenv("EST_COST_PER_AGENT_USD", "0.75")
    store = AsyncSQLiteStore(str(tmp_path / "reserved.db"))
    try:
        issue = _make_issue(budget_usd=2.0)
        await store.save_codex_issue(issue)
        task = CodexTask(
            id="task-running",
            session_id=issue.session_id,
            project_id=issue.project_id,
            issue_id=issue.id,
            title="impl",
            prompt="do it",
        )
        await store.save_codex_task(task)
        now = datetime.now()
        await store.save_execution_process(
            ExecutionProcess(
                id="ep-running",
                task_id=task.id,
                session_id=issue.session_id,
                status="Running",
                total_cost_usd=99.0,
                created_at=now,
                updated_at=now,
            )
        )

        status = await compute_issue_budget_status(store, issue)

        assert status.spent_usd == 0.0
        assert status.reserved_usd == pytest.approx(0.75)
        assert status.effective_spend_usd == pytest.approx(0.75)
        assert status.remaining_usd == pytest.approx(1.25)
    finally:
        await store.close()


def test_budget_status_no_ceiling_when_budget_zero():
    from app.application.budget_service import IssueBudgetStatus

    status = IssueBudgetStatus(
        issue_id="i",
        spent_usd=3.0,
        budget_usd=0.0,
        budget_source="default",
        soft_warn_ratio=0.8,
    )
    assert not status.has_ceiling
    assert status.remaining_usd is None
    assert status.used_ratio is None
    assert not status.soft_warn
    assert not status.over_budget


def test_budget_status_soft_warn_and_over_budget_flags():
    from app.application.budget_service import IssueBudgetStatus

    warn = IssueBudgetStatus(
        "i", spent_usd=8.5, budget_usd=10.0, budget_source="issue", soft_warn_ratio=0.8
    )
    assert warn.soft_warn
    assert not warn.over_budget

    over = IssueBudgetStatus(
        "i", spent_usd=10.0, budget_usd=10.0, budget_source="issue", soft_warn_ratio=0.8
    )
    assert over.soft_warn
    assert over.over_budget


def test_render_budget_summary_includes_spend_budget_remaining():
    from app.application.budget_service import IssueBudgetStatus, render_budget_summary

    status = IssueBudgetStatus(
        "i", spent_usd=2.0, budget_usd=10.0, budget_source="issue", soft_warn_ratio=0.8
    )
    text = render_budget_summary(status)
    assert "COST / BUDGET" in text
    assert "$2.0000" in text
    assert "$10.0000" in text
    assert "$8.0000" in text  # remaining


def test_render_budget_summary_no_ceiling():
    from app.application.budget_service import IssueBudgetStatus, render_budget_summary

    status = IssueBudgetStatus(
        "i", spent_usd=1.0, budget_usd=0.0, budget_source="default", soft_warn_ratio=0.8
    )
    text = render_budget_summary(status)
    assert "unlimited" in text.lower()


# ---------------------------------------------------------------------------
# timeouts knob invariants
# ---------------------------------------------------------------------------


def test_budget_defaults_pass_invariants():
    assert timeouts.budget_soft_warn_ratio() == timeouts.DEFAULT_BUDGET_SOFT_WARN_RATIO
    assert timeouts.default_issue_budget_usd() == timeouts.DEFAULT_ISSUE_BUDGET_USD
    assert timeouts.check_invariants() == []


def test_budget_soft_warn_ratio_out_of_range_trips_invariant(monkeypatch):
    monkeypatch.setenv("BUDGET_SOFT_WARN_RATIO", "1.5")
    violations = timeouts.check_invariants()
    assert any("BUDGET_SOFT_WARN_RATIO" in v for v in violations)

    monkeypatch.setenv("BUDGET_SOFT_WARN_RATIO", "0")
    violations = timeouts.check_invariants()
    assert any("BUDGET_SOFT_WARN_RATIO" in v for v in violations)


def test_negative_default_budget_trips_invariant(monkeypatch):
    monkeypatch.setenv("DEFAULT_ISSUE_BUDGET_USD", "-1")
    violations = timeouts.check_invariants()
    assert any("DEFAULT_ISSUE_BUDGET_USD" in v for v in violations)
