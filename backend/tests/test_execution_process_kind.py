"""Tests for ExecutionProcess.kind / triggering_message_id (P1 Foundation)."""

from datetime import datetime

import pytest

from app.domain.models import ExecutionProcess


def test_execution_process_defaults_to_initial_kind():
    """New EP without explicit kind defaults to 'initial' with no triggering message."""
    ep = ExecutionProcess(id="ep-1", task_id="t-1", session_id="s-1")
    assert ep.kind == "initial"
    assert ep.triggering_message_id is None


def test_execution_process_accepts_all_four_kinds():
    for kind in ("initial", "rerun", "refine", "chat"):
        ep = ExecutionProcess(id="ep", task_id="t", session_id="s", kind=kind)
        assert ep.kind == kind


def test_execution_process_kind_invalid_value_rejected():
    """Pydantic Literal rejects unknown kind values."""
    with pytest.raises(Exception):  # noqa: B017
        ExecutionProcess(id="ep", task_id="t", session_id="s", kind="bogus")


def test_execution_process_persists_triggering_message_id():
    ep = ExecutionProcess(
        id="ep-1",
        task_id="t-1",
        session_id="s-1",
        kind="chat",
        triggering_message_id="msg-42",
    )
    assert ep.kind == "chat"
    assert ep.triggering_message_id == "msg-42"


# ---------------------------------------------------------------------------
# Storage round-trip (sync sqlite_store)
# ---------------------------------------------------------------------------


def test_sync_store_roundtrips_kind_and_triggering_message_id(tmp_path):
    from app.adapters.sqlite_store import SQLiteStore

    db_path = tmp_path / "test.db"
    store = SQLiteStore(str(db_path))
    now = datetime.now()
    ep = ExecutionProcess(
        id="ep-1",
        task_id="t-1",
        session_id="s-1",
        status="Running",
        kind="chat",
        triggering_message_id="msg-7",
        created_at=now,
        updated_at=now,
    )
    store.save_execution_process(ep)

    loaded = store.load_execution_process("ep-1")
    assert loaded is not None
    assert loaded.kind == "chat"
    assert loaded.triggering_message_id == "msg-7"

    listed = store.list_execution_processes(task_id="t-1")
    assert len(listed) == 1
    assert listed[0].kind == "chat"
    assert listed[0].triggering_message_id == "msg-7"


def test_sync_store_defaults_kind_to_initial_on_load(tmp_path):
    from app.adapters.sqlite_store import SQLiteStore

    db_path = tmp_path / "test.db"
    store = SQLiteStore(str(db_path))
    now = datetime.now()
    ep = ExecutionProcess(
        id="ep-2", task_id="t-1", session_id="s-1", created_at=now, updated_at=now
    )
    store.save_execution_process(ep)
    loaded = store.load_execution_process("ep-2")
    assert loaded.kind == "initial"
    assert loaded.triggering_message_id is None


def test_sync_store_keeps_completed_at_null_for_running_status(tmp_path):
    from app.adapters.sqlite_store import SQLiteStore

    db_path = tmp_path / "running.db"
    store = SQLiteStore(str(db_path))
    now = datetime.now()
    ep = ExecutionProcess(
        id="ep-running-sync",
        task_id="t-1",
        session_id="s-1",
        status="Running",
        created_at=now,
        updated_at=now,
    )
    store.save_execution_process(ep)

    store.update_execution_process_status(
        "ep-running-sync", "Running", exit_code=None, completed_at=None
    )
    loaded = store.load_execution_process("ep-running-sync")

    assert loaded is not None
    assert loaded.status == "Running"
    assert loaded.completed_at is None


def test_sync_store_migrates_legacy_rows_to_initial(tmp_path):
    """Simulate a pre-migration DB (no kind column), then migration should backfill 'initial'."""
    import sqlite3

    db_path = tmp_path / "legacy.db"
    # Build a legacy schema without kind / triggering_message_id
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE execution_processes (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Running',
            exit_code INTEGER,
            started_at TEXT,
            completed_at TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        INSERT INTO execution_processes (id, task_id, session_id, status, created_at, updated_at)
        VALUES ('legacy-ep', 't-1', 's-1', 'Completed', '2026-01-01T00:00:00', '2026-01-01T00:00:00');
        """
    )
    conn.commit()
    conn.close()

    # Now open via SQLiteStore which should run idempotent migration
    from app.adapters.sqlite_store import SQLiteStore

    store = SQLiteStore(str(db_path))
    loaded = store.load_execution_process("legacy-ep")
    assert loaded is not None
    assert loaded.kind == "initial"
    assert loaded.triggering_message_id is None


# ---------------------------------------------------------------------------
# Storage round-trip (async aiosqlite store)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_store_roundtrips_kind_and_triggering_message_id(tmp_path):
    from app.adapters.async_sqlite_store import AsyncSQLiteStore

    db_path = tmp_path / "async_test.db"
    store = AsyncSQLiteStore(str(db_path))
    try:
        now = datetime.now()
        ep = ExecutionProcess(
            id="ep-async-1",
            task_id="t-1",
            session_id="s-1",
            status="Running",
            kind="refine",
            triggering_message_id="msg-async-9",
            created_at=now,
            updated_at=now,
        )
        await store.save_execution_process(ep)

        loaded = await store.load_execution_process("ep-async-1")
        assert loaded is not None
        assert loaded.kind == "refine"
        assert loaded.triggering_message_id == "msg-async-9"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_async_store_defaults_kind_to_initial_on_load(tmp_path):
    from app.adapters.async_sqlite_store import AsyncSQLiteStore

    db_path = tmp_path / "async_test2.db"
    store = AsyncSQLiteStore(str(db_path))
    try:
        now = datetime.now()
        ep = ExecutionProcess(
            id="ep-async-2", task_id="t-1", session_id="s-1", created_at=now, updated_at=now
        )
        await store.save_execution_process(ep)
        loaded = await store.load_execution_process("ep-async-2")
        assert loaded.kind == "initial"
        assert loaded.triggering_message_id is None
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_async_store_keeps_completed_at_null_for_running_status(tmp_path):
    from app.adapters.async_sqlite_store import AsyncSQLiteStore

    db_path = tmp_path / "async_running.db"
    store = AsyncSQLiteStore(str(db_path))
    try:
        now = datetime.now()
        ep = ExecutionProcess(
            id="ep-running-async",
            task_id="t-1",
            session_id="s-1",
            status="Running",
            created_at=now,
            updated_at=now,
        )
        await store.save_execution_process(ep)

        await store.update_execution_process_status(
            "ep-running-async", "Running", exit_code=None, completed_at=None
        )
        loaded = await store.load_execution_process("ep-running-async")

        assert loaded is not None
        assert loaded.status == "Running"
        assert loaded.completed_at is None
    finally:
        await store.close()
