from __future__ import annotations

import asyncio

from app.application.event_bus import EventBus, event_bus


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
    assert entries[1]["payload"]["issue_id"] == "c"


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
