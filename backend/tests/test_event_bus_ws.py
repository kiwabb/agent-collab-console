from __future__ import annotations

import asyncio
from datetime import datetime
from typing import cast

import pytest

from app.application.event_bus import EventBus, event_bus
from app.domain.models import LogEvent


def test_event_bus_wraps_events_and_evicts_old_entries():
    bus = EventBus()
    bus._buffer_size = 2
    bus.events.clear()
    bus.events = bus.events.__class__(maxlen=2)

    asyncio.run(bus.append({"type": "issue_created", "issue_id": "a"}))
    asyncio.run(bus.append({"type": "issue_updated", "issue_id": "b"}))
    asyncio.run(bus.append({"type": "issue_deleted", "issue_id": "c"}))

    entries = list(bus.events)
    assert len(entries) == 2
    assert entries[0]["event_id"] == "evt-00000002"
    assert entries[1]["event_id"] == "evt-00000003"
    assert entries[0]["type"] == "issue_updated"
    payload = cast(dict[str, object], entries[1]["payload"])
    assert payload["issue_id"] == "c"


def test_event_bus_replay_from_and_gap_detection():
    bus = EventBus()
    asyncio.run(bus.append({"type": "issue_created", "issue_id": "a"}))
    asyncio.run(bus.append({"type": "issue_updated", "issue_id": "b"}))
    asyncio.run(bus.append({"type": "issue_deleted", "issue_id": "c"}))

    replay, missed = bus.replay_from("evt-00000001")
    assert missed is False
    assert [entry["event_id"] for entry in replay] == ["evt-00000002", "evt-00000003"]

    replay, missed = bus.replay_from("evt-99999999")
    assert replay == []
    assert missed is True


def test_global_events_ws_streams_envelopes_and_resume_gap(client):
    event_bus.events.clear()
    event_bus.subscribers.clear()
    event_bus._event_seq = 0

    with client.websocket_connect("/api/ws/events") as ws:
        asyncio.run(
            event_bus.append({"type": "issue_updated", "issue_id": "issue-1", "status": "open"})
        )
        message = ws.receive_json()
        assert message["type"] == "issue_updated"
        assert message["event_id"] == "evt-00000001"
        assert message["payload"]["issue_id"] == "issue-1"

    with client.websocket_connect("/api/ws/events?last_event_id=evt-missing") as ws:
        message = ws.receive_json()
        assert message["type"] == "resume_gap"
        assert message["payload"]["from_event_id"] == "evt-missing"
        assert message["payload"]["reason"] == "buffer_overflow"


def test_global_events_ws_replays_then_streams_live_without_duplicate(client):
    event_bus.events.clear()
    event_bus.subscribers.clear()
    event_bus._event_seq = 0
    asyncio.run(event_bus.append({"type": "issue_created", "issue_id": "issue-1"}))

    with client.websocket_connect("/api/ws/events?last_event_id=evt-00000001") as ws:
        asyncio.run(
            event_bus.append({"type": "issue_updated", "issue_id": "issue-1", "status": "open"})
        )
        message = ws.receive_json()
        assert message["event_id"] == "evt-00000002"
        assert message["type"] == "issue_updated"
        assert message["payload"]["status"] == "open"


@pytest.mark.asyncio
async def test_event_bus_shutdown_drains_log_queue() -> None:
    persisted: list[str] = []

    class LogStore:
        async def append_log_event(self, event: LogEvent) -> None:
            persisted.append(event.id)

    bus = EventBus()
    bus.set_log_store(LogStore())
    bus.set_loop(asyncio.get_running_loop())
    for index in range(5):
        await bus.queue_log_event(
            LogEvent(
                id=f"log-{index}",
                session_id="workspace-1",
                stream="stdout",
                content=f"line {index}",
                created_at=datetime.now(),
            )
        )

    await bus.shutdown()

    assert persisted == [f"log-{index}" for index in range(5)]
    assert bus._db_queue.empty()
    assert bus._db_worker_task is None


@pytest.mark.asyncio
async def test_event_bus_log_worker_retries_write_failure_without_loss(monkeypatch) -> None:
    persisted: list[str] = []
    failed_once = False

    class FlakyLogStore:
        async def append_log_event(self, event: LogEvent) -> None:
            nonlocal failed_once
            if event.id == "log-failed" and not failed_once:
                failed_once = True
                raise RuntimeError("write failed")
            persisted.append(event.id)

    bus = EventBus()
    monkeypatch.setattr("app.application.timeouts.event_bus_log_retry_delay_s", lambda: 0)
    bus.set_log_store(FlakyLogStore())
    bus.set_loop(asyncio.get_running_loop())
    for event_id in ("log-failed", "log-ok"):
        await bus.queue_log_event(
            LogEvent(
                id=event_id,
                session_id="workspace-1",
                stream="stdout",
                content=event_id,
                created_at=datetime.now(),
            )
        )

    await bus.shutdown()

    assert persisted == ["log-failed", "log-ok"]
