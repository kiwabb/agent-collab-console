from __future__ import annotations

from datetime import datetime
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
    }
    assert "streaming_llm" in LEGAL_TRANSITIONS["awaiting_llm"]
    assert "awaiting_llm" in LEGAL_TRANSITIONS["paused"]
