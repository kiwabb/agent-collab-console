"""Recovery watchdog must not reap or duplicate a live in-process conductor."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.application import conductor_recovery
from app.application.conductor_lease import get_conductor_lease_owner
from app.application.conductor_recovery import _is_stale, recover_orphaned_conductors
from app.application.conductor_session_registry import ConductorSessionRegistry
from app.domain.models import ConductorTask


def _make_ct(*, issue_id: str, status: str = "running", expired: bool = True) -> ConductorTask:
    now = datetime.now()
    return ConductorTask(
        id=str(uuid4()),
        project_id="proj-1",
        task_kind="issue",
        issue_id=issue_id,
        payload={"phase": "awaiting_subagent", "detail": "engineer"},
        status=status,
        lease_owner=get_conductor_lease_owner(),
        heartbeat_at=now - timedelta(seconds=400) if expired else now,
        lease_expires_at=now - timedelta(seconds=200) if expired else now + timedelta(seconds=200),
        created_at=now - timedelta(seconds=400),
        updated_at=now - timedelta(seconds=400),
    )


async def _sleep_forever() -> None:
    await asyncio.Event().wait()


def test_is_stale_false_for_live_same_process_session():
    """An expired lease is NOT stale if the loop is still live in this process."""
    issue_id = "issue-live"
    ct = _make_ct(issue_id=issue_id, expired=True)
    reg = ConductorSessionRegistry.instance()
    # Simulate a live session bound to this exact conductor_task id.
    reg._sessions[issue_id] = MagicMock(
        issue_id=issue_id,
        conductor_task_id=ct.id,
        task=MagicMock(done=MagicMock(return_value=False)),
    )
    try:
        assert _is_stale(
            ct,
            now=datetime.now(),
            stale_after_s=180,
            current_owner=get_conductor_lease_owner(),
            recover_foreign_owner=False,
        ) is False
    finally:
        reg._sessions.pop(issue_id, None)


def test_is_stale_true_for_expired_lease_without_live_session():
    ct = _make_ct(issue_id="issue-dead", expired=True)
    assert _is_stale(
        ct,
        now=datetime.now(),
        stale_after_s=180,
        current_owner=get_conductor_lease_owner(),
        recover_foreign_owner=False,
    ) is True


async def test_recover_marks_stalled_but_skips_relaunch_when_live_session_exists():
    """A stale OLD row is cleaned up, but no duplicate loop is launched while a
    live session for the same issue still runs."""
    issue_id = "issue-x"
    old_ct = _make_ct(issue_id=issue_id, expired=True)  # superseded, not bound

    store = MagicMock()
    store.list_conductor_tasks = AsyncMock(return_value=[old_ct])
    store.save_conductor_task = AsyncMock()
    store.load_codex_issue = AsyncMock(return_value=MagicMock(status="open", project_id="proj-1"))

    reg = ConductorSessionRegistry.instance()
    # A live session exists for the issue under a DIFFERENT conductor_task id.
    handle = await reg.try_start(issue_id, _sleep_forever)
    await reg.bind_conductor_task(issue_id, "ct-NEW-and-live")

    with patch.object(conductor_recovery, "transition_conductor_phase", new=AsyncMock()), \
         patch.object(conductor_recovery, "get_phase_duration_estimator", return_value=MagicMock()), \
         patch("app.application.conductor_main_loop.run_issue_conductor_loop", new=AsyncMock()) as relaunch:
        recovered = await recover_orphaned_conductors(
            store,
            current_owner=get_conductor_lease_owner(),
            stale_after_s=180,
            recover_foreign_owner=False,
            auto_restart=True,
        )

    try:
        assert recovered == 1  # the old row was marked stalled
        relaunch.assert_not_called()  # but no duplicate loop launched
        assert reg.is_alive(issue_id)  # the live session is untouched
    finally:
        await reg.stop(issue_id)
