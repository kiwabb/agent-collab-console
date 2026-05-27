"""Phase 3 — structured observability events.

GAP I: stall lifecycle events on the bus.
GAP K: codex app-server that fails to start is detected fast (not after the
full turn budget) and emits a structured `executor_failed_to_start` event.
"""
from __future__ import annotations

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_emit_stall_event_goes_to_global_bus():
    from app.application import stall_watchdog

    captured = []
    fake_bus = MagicMock()
    fake_bus.append = AsyncMock(side_effect=lambda e: captured.append(e))

    with patch("app.application.event_bus.event_bus", fake_bus):
        await stall_watchdog._emit_stall_event(
            "stall_detected", task_id="t1", role="qa", executor="codex", silence_s=200.0
        )

    assert captured and captured[0]["type"] == "stall_detected"
    assert captured[0]["role"] == "qa"
    assert captured[0]["silence_s"] == 200.0


@pytest.mark.asyncio
async def test_initialize_or_fail_fast_detects_early_exit():
    """A dead app-server (initialize hangs, process already exited) must fail
    fast and emit executor_failed_to_start — not hang the turn budget."""
    from app.application.codex_app_server_runtime import CodexAppServerRuntime

    runtime = CodexAppServerRuntime.__new__(CodexAppServerRuntime)
    events = []
    runtime._event_bus = MagicMock()
    runtime._event_bus.append = AsyncMock(side_effect=lambda e: events.append(e))

    # initialize() never returns (simulates waiting for a dead process).
    client = MagicMock()
    async def _hang():
        await asyncio.Event().wait()
    client.initialize = AsyncMock(side_effect=_hang)
    client.initialized = AsyncMock()

    # proc already exited with a non-zero code; stderr has the crash reason.
    proc = MagicMock()
    proc.returncode = 2
    async def _wait():
        return 2
    proc.wait = _wait
    proc.stderr = MagicMock()
    proc.stderr.read = AsyncMock(return_value=b"error: unexpected argument '--bad'")

    with patch("app.application.timeouts.codex_handshake_timeout_s", return_value=1):
        with pytest.raises(RuntimeError, match="failed to start"):
            await runtime._initialize_or_fail_fast(client, proc, "ws-1", "task-1")

    assert any(
        e.get("type") == "executor_failed_to_start" and e.get("reason") == "exited"
        for e in events
    )
    evt = next(e for e in events if e.get("type") == "executor_failed_to_start")
    assert evt["returncode"] == 2
    assert "unexpected argument" in evt["stderr"]


@pytest.mark.asyncio
async def test_initialize_or_fail_fast_happy_path():
    """A healthy handshake completes without emitting a failure event."""
    from app.application.codex_app_server_runtime import CodexAppServerRuntime

    runtime = CodexAppServerRuntime.__new__(CodexAppServerRuntime)
    events = []
    runtime._event_bus = MagicMock()
    runtime._event_bus.append = AsyncMock(side_effect=lambda e: events.append(e))

    client = MagicMock()
    client.initialize = AsyncMock(return_value={})
    client.initialized = AsyncMock(return_value=True)

    proc = MagicMock()
    proc.returncode = None
    async def _wait_forever():
        await asyncio.Event().wait()
    proc.wait = _wait_forever
    proc.stderr = MagicMock()

    await runtime._initialize_or_fail_fast(client, proc, "ws-1", "task-1")

    assert not any(e.get("type") == "executor_failed_to_start" for e in events)
    client.initialize.assert_awaited()
    client.initialized.assert_awaited()
