"""GAP F: the stall-watchdog nudge result must be recovered + persisted,
not silently dropped because the nudge ran as kind="chat"."""

from __future__ import annotations  # noqa: I001

from datetime import datetime

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.application.stall_watchdog import _recover_nudge_result
from app.domain.models import CodexTask


def _task(status: str = "failed", result: str = "") -> CodexTask:
    return CodexTask(
        id="task-n",
        session_id="sess-1",
        issue_id="issue-1",
        title="Issue",
        prompt="x",
        role="qa",
        status=status,
        result=result,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


@pytest.mark.asyncio
async def test_recovers_and_marks_done_when_nudge_produced_result():
    task = _task(status="failed")

    async def fake_refresh(t):
        # Simulate refresh_task_result extracting the nudge's final report.
        t.result = '{"status":"passed","summary":"recovered"}'

    store = MagicMock()
    store.load_codex_task = AsyncMock(return_value=task)
    store.save_codex_task = AsyncMock()
    pm = MagicMock()
    pm.refresh_task_result = AsyncMock(side_effect=fake_refresh)

    await _recover_nudge_result(store, pm, "task-n")

    assert task.status == "done"
    store.save_codex_task.assert_awaited()


@pytest.mark.asyncio
async def test_stays_failed_when_nudge_produced_nothing():
    task = _task(status="failed")

    async def fake_refresh(t):
        t.result = ""  # nothing usable recovered

    store = MagicMock()
    store.load_codex_task = AsyncMock(return_value=task)
    store.save_codex_task = AsyncMock()
    pm = MagicMock()
    pm.refresh_task_result = AsyncMock(side_effect=fake_refresh)

    await _recover_nudge_result(store, pm, "task-n")

    assert task.status == "failed"


@pytest.mark.asyncio
async def test_noop_when_task_already_terminal_done():
    task = _task(status="done", result="already there")
    store = MagicMock()
    store.load_codex_task = AsyncMock(return_value=task)
    store.save_codex_task = AsyncMock()
    pm = MagicMock()
    pm.refresh_task_result = AsyncMock()

    await _recover_nudge_result(store, pm, "task-n")

    pm.refresh_task_result.assert_not_called()


@pytest.mark.asyncio
async def test_recovers_from_shared_failure_status():
    task = _task(status="error")

    async def fake_refresh(t):
        t.result = '{"status":"passed","summary":"recovered after error"}'

    store = MagicMock()
    store.load_codex_task = AsyncMock(return_value=task)
    store.save_codex_task = AsyncMock()
    pm = MagicMock()
    pm.refresh_task_result = AsyncMock(side_effect=fake_refresh)

    recovered = await _recover_nudge_result(store, pm, "task-n")

    assert recovered is True
    assert task.status == "done"


@pytest.mark.asyncio
async def test_qa_downgrade_is_not_reported_as_recovered():
    task = _task(status="failed")

    async def fake_refresh(t):
        t.status = "failed"
        t.result = '{"status":"unverified","execution_results":[]}'

    store = MagicMock()
    store.load_codex_task = AsyncMock(return_value=task)
    store.save_codex_task = AsyncMock()
    pm = MagicMock()
    pm.refresh_task_result = AsyncMock(side_effect=fake_refresh)

    recovered = await _recover_nudge_result(store, pm, "task-n")

    assert recovered is False
    assert task.status == "failed"
    store.save_codex_task.assert_awaited_once_with(task)
