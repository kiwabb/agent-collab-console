"""Tests for TaskCompletionRegistry."""
from __future__ import annotations

import asyncio
import pytest

from app.application.task_completion_registry import TaskCompletionRegistry


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset singleton between tests."""
    TaskCompletionRegistry._instance = None
    yield
    TaskCompletionRegistry._instance = None


@pytest.mark.asyncio
async def test_register_and_signal():
    """test_register_and_signal: register task_id, signal it, wait_for returns result."""
    reg = TaskCompletionRegistry.get()
    task_id = "task-abc-123"
    reg.register(task_id)
    assert reg.is_registered(task_id)

    expected = {"status": "done", "role": "engineer"}

    async def _signal_after():
        await asyncio.sleep(0.01)
        reg.signal(task_id, expected)

    asyncio.create_task(_signal_after())
    result = await reg.wait_for(task_id, timeout=2.0)
    assert result == expected


@pytest.mark.asyncio
async def test_wait_for_timeout():
    """test_wait_for_timeout: signal never fires, wait_for raises TimeoutError."""
    reg = TaskCompletionRegistry.get()
    task_id = "task-timeout-999"
    reg.register(task_id)

    with pytest.raises(TimeoutError):
        await reg.wait_for(task_id, timeout=0.05)


@pytest.mark.asyncio
async def test_is_registered():
    """test_is_registered: check before/after register."""
    reg = TaskCompletionRegistry.get()
    task_id = "task-check-456"
    assert not reg.is_registered(task_id)
    reg.register(task_id)
    assert reg.is_registered(task_id)

    # After wait_for completes, the event is cleaned up
    async def _signal():
        await asyncio.sleep(0.01)
        reg.signal(task_id, {"done": True})

    asyncio.create_task(_signal())
    await reg.wait_for(task_id, timeout=2.0)
    # After wait_for, the event is popped
    assert not reg.is_registered(task_id)


@pytest.mark.asyncio
async def test_singleton():
    """TaskCompletionRegistry is a process-level singleton."""
    reg1 = TaskCompletionRegistry.get()
    reg2 = TaskCompletionRegistry()
    assert reg1 is reg2


@pytest.mark.asyncio
async def test_wait_for_active_extends_while_progressing():
    """A slow but still-active task is not abandoned: it keeps being waited on
    past idle_timeout as long as activity_age stays small, and resolves on
    signal."""
    reg = TaskCompletionRegistry.get()
    task_id = "task-slow-but-alive"
    reg.register(task_id)

    expected = {"status": "passed", "role": "qa"}

    async def _signal_after():
        await asyncio.sleep(0.25)  # > idle_timeout, but task is "active"
        reg.signal(task_id, expected)

    asyncio.create_task(_signal_after())
    # idle_timeout tiny, but activity_age always reports "just active" (0.0),
    # so it must NOT time out before the signal arrives.
    result = await reg.wait_for_active(
        task_id,
        idle_timeout=0.05,
        hard_timeout=5.0,
        activity_age=lambda _tid: 0.0,
        poll=0.02,
    )
    assert result == expected


@pytest.mark.asyncio
async def test_wait_for_active_times_out_when_idle():
    """A genuinely stalled task (no recent activity) times out at idle_timeout
    even though the hard ceiling is far away."""
    reg = TaskCompletionRegistry.get()
    task_id = "task-stalled"
    reg.register(task_id)

    with pytest.raises(TimeoutError):
        await reg.wait_for_active(
            task_id,
            idle_timeout=0.05,
            hard_timeout=10.0,
            activity_age=lambda _tid: 999.0,  # always "idle for 999s"
            poll=0.02,
        )


@pytest.mark.asyncio
async def test_late_signal_after_timeout_does_not_orphan_result():
    """If a dispatch times out (its event is popped) and the subagent later
    completes, the late signal must NOT leave an entry stranded in `_results`
    forever — `signal` with no waiter is a no-op."""
    reg = TaskCompletionRegistry.get()
    task_id = "task-late-completer"
    reg.register(task_id)

    with pytest.raises(TimeoutError):
        await reg.wait_for(task_id, timeout=0.02)

    # The subagent finishes after the conductor already gave up.
    reg.signal(task_id, {"status": "done", "role": "qa"})

    assert task_id not in reg._results
    assert task_id not in reg._events


@pytest.mark.asyncio
async def test_signal_before_register_is_not_lost_wait_for():
    """CORE RACE REGRESSION: a task that completes instantly (signal fires
    BEFORE register) must not have its result dropped. The buffered result is
    drained on register so wait_for returns it immediately instead of stalling
    until timeout."""
    reg = TaskCompletionRegistry.get()
    task_id = "task-instant"
    expected = {"status": "done", "role": "engineer"}

    # Signal arrives FIRST, before anyone registers (instant fail-fast / completion).
    reg.signal(task_id, expected)
    assert not reg.is_registered(task_id)

    # Now the dispatcher registers and waits — must get the buffered result fast.
    reg.register(task_id)
    result = await reg.wait_for(task_id, timeout=0.5)
    assert result == expected


@pytest.mark.asyncio
async def test_signal_before_register_is_not_lost_wait_for_active():
    """CORE RACE REGRESSION (dispatch path): wait_for_active also surfaces a
    result buffered by a signal that beat register — no idle/hard timeout."""
    reg = TaskCompletionRegistry.get()
    task_id = "task-instant-active"
    expected = {"status": "done", "role": "qa"}

    reg.signal(task_id, expected)
    reg.register(task_id)

    result = await reg.wait_for_active(
        task_id,
        idle_timeout=0.05,
        hard_timeout=0.5,
        activity_age=lambda _tid: 999.0,  # "idle" — would time out if not buffered
        poll=0.02,
    )
    assert result == expected


@pytest.mark.asyncio
async def test_wait_for_active_drains_pending_when_never_registered():
    """If wait_for_active is called on a task that was never explicitly
    registered but already has a buffered result, it returns it instead of
    raising LookupError."""
    reg = TaskCompletionRegistry.get()
    task_id = "task-pending-only"
    expected = {"status": "done"}
    reg.signal(task_id, expected)

    result = await reg.wait_for_active(
        task_id, idle_timeout=1.0, hard_timeout=1.0
    )
    assert result == expected


@pytest.mark.asyncio
async def test_register_is_idempotent_and_preserves_set_event():
    """Re-registering a task_id must not clobber an already-set event/result
    (the _run_single_dispatch idempotent safety-net re-register)."""
    reg = TaskCompletionRegistry.get()
    task_id = "task-idempotent"
    expected = {"status": "done"}

    reg.register(task_id)
    reg.signal(task_id, expected)  # event now set, result stored
    reg.register(task_id)          # second register must NOT reset it

    result = await reg.wait_for(task_id, timeout=0.5)
    assert result == expected


@pytest.mark.asyncio
async def test_pending_buffer_is_bounded():
    """A flood of signals for tasks that are NEVER registered must not grow the
    pending buffer without bound (eviction keeps it within _PENDING_MAX)."""
    reg = TaskCompletionRegistry.get()
    for i in range(reg._PENDING_MAX + 50):
        reg.signal(f"never-registered-{i}", {"i": i})
    assert len(reg._pending) <= reg._PENDING_MAX


@pytest.mark.asyncio
async def test_pending_buffer_prunes_stale_entries(monkeypatch):
    """Stale buffered results (older than TTL) are pruned on the next signal."""
    reg = TaskCompletionRegistry.get()
    reg.signal("old-task", {"v": 1})
    # Age the existing entry beyond the TTL.
    result, _ = reg._pending["old-task"]
    reg._pending["old-task"] = (result, reg._pending["old-task"][1] - reg._PENDING_TTL_S - 1.0)
    # A fresh signal triggers a prune that evicts the stale one.
    reg.signal("new-task", {"v": 2})
    assert "old-task" not in reg._pending
    assert "new-task" in reg._pending


@pytest.mark.asyncio
async def test_wait_for_active_hard_ceiling():
    """Without activity info, only the hard ceiling applies."""
    reg = TaskCompletionRegistry.get()
    task_id = "task-runaway"
    reg.register(task_id)

    with pytest.raises(TimeoutError):
        await reg.wait_for_active(
            task_id,
            idle_timeout=100.0,
            hard_timeout=0.1,
            activity_age=lambda _tid: None,  # unknown → idle check skipped
            poll=0.02,
        )
