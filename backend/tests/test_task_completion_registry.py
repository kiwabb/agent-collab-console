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
