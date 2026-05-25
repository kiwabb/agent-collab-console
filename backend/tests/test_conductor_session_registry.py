"""Tests for ConductorSessionRegistry — one live session per issue."""
from __future__ import annotations

import asyncio

import pytest

from app.application.conductor_session_registry import ConductorSessionRegistry


async def _sleep_forever() -> None:
    await asyncio.Event().wait()


async def test_try_start_registers_and_returns_handle():
    reg = ConductorSessionRegistry()
    handle = await reg.try_start("issue-1", _sleep_forever)
    assert handle is not None
    assert handle.issue_id == "issue-1"
    assert reg.is_alive("issue-1")
    await reg.stop("issue-1")


async def test_try_start_is_idempotent_while_alive():
    reg = ConductorSessionRegistry()
    first = await reg.try_start("issue-1", _sleep_forever)
    second = await reg.try_start("issue-1", _sleep_forever)
    assert first is not None
    assert second is None  # already live -> skip
    assert len(reg.list_all()) == 1
    await reg.stop("issue-1")


async def test_deregisters_when_task_finishes():
    reg = ConductorSessionRegistry()

    async def _quick() -> None:
        return None

    handle = await reg.try_start("issue-1", _quick)
    assert handle is not None
    await handle.task  # let it finish
    # done_callback runs on the event loop; yield once so it fires.
    await asyncio.sleep(0)
    assert not reg.is_alive("issue-1")
    # A fresh start is now allowed.
    again = await reg.try_start("issue-1", _sleep_forever)
    assert again is not None
    await reg.stop("issue-1")


async def test_stop_cancels_and_deregisters():
    reg = ConductorSessionRegistry()
    handle = await reg.try_start("issue-1", _sleep_forever)
    assert handle is not None
    stopped = await reg.stop("issue-1")
    assert stopped is True
    assert not reg.is_alive("issue-1")
    assert await reg.stop("issue-1") is False  # nothing left


async def test_bind_conductor_task_and_is_conductor_task_alive():
    reg = ConductorSessionRegistry()
    await reg.try_start("issue-1", _sleep_forever)
    await reg.bind_conductor_task("issue-1", "ct-123")
    assert reg.is_conductor_task_alive("issue-1", "ct-123") is True
    # A different (older) conductor_task id is NOT the live one.
    assert reg.is_conductor_task_alive("issue-1", "ct-OLD") is False
    await reg.stop("issue-1")
    assert reg.is_conductor_task_alive("issue-1", "ct-123") is False
