from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.application.conductor_main_loop import LEGAL_TRANSITIONS, transition_conductor_phase
from app.application.phase_duration_estimator import get_phase_duration_estimator
from app.domain.models import ConductorTask


@pytest.mark.asyncio
async def test_transition_records_state_log_and_updates_estimates(tmp_path):
    store = AsyncSQLiteStore(tmp_path / "console.db")
    event_bus = MagicMock()
    event_bus.append = AsyncMock()
    task = ConductorTask(
        id="task-1",
        project_id="proj-1",
        task_kind="issue",
        issue_id="issue-1",
        payload={},
        status="running",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    estimator = get_phase_duration_estimator(store)

    await transition_conductor_phase(
        store=store,
        event_bus=event_bus,
        issue_id="issue-1",
        conductor_task=task,
        phase="awaiting_llm",
        status="running",
        estimator=estimator,
    )
    await transition_conductor_phase(
        store=store,
        event_bus=event_bus,
        issue_id="issue-1",
        conductor_task=task,
        phase="streaming_llm",
        status="running",
        estimator=estimator,
    )
    await transition_conductor_phase(
        store=store,
        event_bus=event_bus,
        issue_id="issue-1",
        conductor_task=task,
        phase="dispatching_subagent",
        detail="engineer",
        status="running",
        estimator=estimator,
    )

    entries = await store.list_conductor_state_logs("issue-1", limit=10, descending=False)
    estimate = await estimator.estimate("awaiting_llm")
    await store.close()

    assert [entry.to_phase for entry in entries] == ["awaiting_llm", "streaming_llm", "dispatching_subagent"]
    assert entries[0].duration_ms is None
    assert entries[1].duration_ms is not None and entries[1].duration_ms >= 1
    assert all(entry.is_legal for entry in entries)
    assert estimate.n_samples == 1
    assert estimate.p50_ms is not None and estimate.p50_ms >= 1


@pytest.mark.asyncio
async def test_illegal_transition_emits_warning_event_and_persists_flag(tmp_path):
    store = AsyncSQLiteStore(tmp_path / "console.db")
    event_bus = MagicMock()
    event_bus.append = AsyncMock()
    task = ConductorTask(
        id="task-2",
        project_id="proj-1",
        task_kind="issue",
        issue_id="issue-2",
        payload={"phase": "done", "detail": "all set"},
        status="done",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    await transition_conductor_phase(
        store=store,
        event_bus=event_bus,
        issue_id="issue-2",
        conductor_task=task,
        phase="awaiting_llm",
        status="running",
        estimator=get_phase_duration_estimator(store),
    )

    entries = await store.list_conductor_state_logs("issue-2", limit=10, descending=False)
    await store.close()

    assert len(entries) == 1
    assert entries[0].is_legal is False
    assert any(
        call.args[0].get("type") == "conductor_state_violation"
        and call.args[0].get("from_phase") == "done"
        and call.args[0].get("to_phase") == "awaiting_llm"
        for call in event_bus.append.call_args_list
    )


def test_legal_transitions_cover_expected_phases():
    assert set(LEGAL_TRANSITIONS) == {
        "awaiting_llm",
        "streaming_llm",
        "dispatching_subagent",
        "awaiting_subagent",
        "awaiting_user_clarification",
        "paused",
        "done",
        "failed",
        "stalled",
    }
    assert "streaming_llm" in LEGAL_TRANSITIONS["awaiting_llm"]
    assert "awaiting_llm" in LEGAL_TRANSITIONS["paused"]


@pytest.mark.asyncio
async def test_recovery_marks_expired_running_conductor_stalled(tmp_path):
    from app.application.conductor_recovery import recover_orphaned_conductors

    store = AsyncSQLiteStore(tmp_path / "console.db")
    event_bus = MagicMock()
    event_bus.append = AsyncMock()
    stale_seen = datetime.now() - timedelta(minutes=10)
    task = ConductorTask(
        id="task-stale",
        project_id="proj-1",
        task_kind="issue",
        issue_id="issue-stale",
        payload={"phase": "awaiting_llm", "detail": None},
        status="running",
        lease_owner="old-process",
        heartbeat_at=stale_seen,
        created_at=stale_seen,
        updated_at=stale_seen,
    )
    await store.save_conductor_task(task)

    recovered = await recover_orphaned_conductors(
        store,
        event_bus=event_bus,
        current_owner="new-process",
        stale_after_s=60,
    )

    loaded = await store.load_conductor_task("task-stale")
    entries = await store.list_conductor_state_logs("issue-stale", limit=10, descending=False)
    await store.close()

    assert recovered == 1
    assert loaded is not None
    assert loaded.status == "stalled"
    assert loaded.payload["phase"] == "stalled"
    assert loaded.payload["stalled_reason"] == "orphaned_conductor_runner"
    assert "old-process" in (loaded.result_json or "")
    assert entries[-1].to_phase == "stalled"
    assert any(
        call.args[0].get("type") == "conductor_status"
        and call.args[0].get("phase") == "stalled"
        for call in event_bus.append.call_args_list
    )


@pytest.mark.asyncio
async def test_recovery_keeps_fresh_running_conductor(tmp_path):
    from app.application.conductor_recovery import recover_orphaned_conductors

    store = AsyncSQLiteStore(tmp_path / "console.db")
    fresh_seen = datetime.now()
    task = ConductorTask(
        id="task-fresh",
        project_id="proj-1",
        task_kind="issue",
        issue_id="issue-fresh",
        payload={"phase": "awaiting_llm"},
        status="running",
        lease_owner="this-process",
        heartbeat_at=fresh_seen,
        created_at=fresh_seen,
        updated_at=fresh_seen,
    )
    await store.save_conductor_task(task)

    recovered = await recover_orphaned_conductors(
        store,
        event_bus=None,
        current_owner="this-process",
        stale_after_s=60,
    )

    loaded = await store.load_conductor_task("task-fresh")
    await store.close()

    assert recovered == 0
    assert loaded is not None
    assert loaded.status == "running"
    assert loaded.payload["phase"] == "awaiting_llm"


@pytest.mark.asyncio
async def test_startup_recovery_marks_dead_foreign_owner_stalled(tmp_path, monkeypatch):
    from app.application import conductor_recovery

    store = AsyncSQLiteStore(tmp_path / "console.db")
    fresh_seen = datetime.now()
    task = ConductorTask(
        id="task-dead-owner",
        project_id="proj-1",
        task_kind="issue",
        issue_id="issue-dead-owner",
        payload={"phase": "awaiting_llm"},
        status="running",
        lease_owner="pid:424242:old-owner",
        heartbeat_at=fresh_seen,
        lease_expires_at=fresh_seen + timedelta(minutes=5),
        created_at=fresh_seen,
        updated_at=fresh_seen,
    )
    await store.save_conductor_task(task)
    monkeypatch.setattr(conductor_recovery.os, "kill", lambda pid, sig: (_ for _ in ()).throw(ProcessLookupError()))

    recovered = await conductor_recovery.recover_orphaned_conductors(
        store,
        event_bus=None,
        current_owner="pid:999999:new-owner",
        stale_after_s=60,
        recover_foreign_owner=True,
    )

    loaded = await store.load_conductor_task("task-dead-owner")
    await store.close()

    assert recovered == 1
    assert loaded is not None
    assert loaded.status == "stalled"
    assert loaded.payload["previous_lease_owner"] == "pid:424242:old-owner"


@pytest.mark.asyncio
async def test_startup_recovery_keeps_live_foreign_owner_with_fresh_lease(tmp_path, monkeypatch):
    from app.application import conductor_recovery

    store = AsyncSQLiteStore(tmp_path / "console.db")
    fresh_seen = datetime.now()
    task = ConductorTask(
        id="task-live-owner",
        project_id="proj-1",
        task_kind="issue",
        issue_id="issue-live-owner",
        payload={"phase": "awaiting_llm"},
        status="running",
        lease_owner="pid:424242:other-owner",
        heartbeat_at=fresh_seen,
        lease_expires_at=fresh_seen + timedelta(minutes=5),
        created_at=fresh_seen,
        updated_at=fresh_seen,
    )
    await store.save_conductor_task(task)
    monkeypatch.setattr(conductor_recovery.os, "kill", lambda pid, sig: None)

    recovered = await conductor_recovery.recover_orphaned_conductors(
        store,
        event_bus=None,
        current_owner="pid:999999:new-owner",
        stale_after_s=0,
        recover_foreign_owner=True,
    )

    loaded = await store.load_conductor_task("task-live-owner")
    await store.close()

    assert recovered == 0
    assert loaded is not None
    assert loaded.status == "running"
    assert loaded.payload["phase"] == "awaiting_llm"


@pytest.mark.asyncio
async def test_recovery_ignores_paused_and_terminal_conductors(tmp_path):
    from app.application.conductor_recovery import recover_orphaned_conductors

    store = AsyncSQLiteStore(tmp_path / "console.db")
    stale_seen = datetime.now() - timedelta(minutes=10)
    for task_id, status in [
        ("task-paused", "paused"),
        ("task-done", "done"),
        ("task-failed", "failed"),
        ("task-stalled", "stalled"),
    ]:
        await store.save_conductor_task(
            ConductorTask(
                id=task_id,
                project_id="proj-1",
                task_kind="issue",
                issue_id=f"issue-{task_id}",
                payload={"phase": status},
                status=status,
                lease_owner="old-process",
                heartbeat_at=stale_seen,
                created_at=stale_seen,
                updated_at=stale_seen,
            )
        )

    recovered = await recover_orphaned_conductors(
        store,
        event_bus=None,
        current_owner="new-process",
        stale_after_s=60,
    )

    loaded = [
        await store.load_conductor_task(task_id)
        for task_id in ["task-paused", "task-done", "task-failed", "task-stalled"]
    ]
    await store.close()

    assert recovered == 0
    assert [task.status for task in loaded if task is not None] == [
        "paused",
        "done",
        "failed",
        "stalled",
    ]
