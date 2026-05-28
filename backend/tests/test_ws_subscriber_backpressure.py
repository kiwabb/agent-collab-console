"""Backpressure tests for the WebSocket broadcast layer.

A slow / half-open subscriber must NEVER block the producer that fans out to
the other subscribers, and must be evicted (force-reconnect) on overflow.
"""
from __future__ import annotations

import asyncio

import pytest

from app.interfaces.codex_ws import (
    ExecutionProcessLogStreamManager,
    ExecutionProcessMessageStreamManager,
    WsSubscriber,
    _PONG,
    _QUEUE_CLOSED,
)


class FakeWebSocket:
    """Records send_json/send_text and can be told to block forever on send."""

    def __init__(self, *, block: bool = False):
        self.sent: list = []
        self.text_sent: list = []
        self.closed_with: tuple | None = None
        self._block = block
        self._gate = asyncio.Event()  # never set when block=True → send hangs

    async def send_json(self, payload):
        if self._block:
            await self._gate.wait()
        self.sent.append(payload)

    async def send_text(self, text):
        if self._block:
            await self._gate.wait()
        self.text_sent.append(text)

    async def close(self, code: int = 1000, reason: str = ""):
        self.closed_with = (code, reason)


@pytest.mark.asyncio
async def test_slow_subscriber_does_not_block_fast_subscriber():
    """publish_log to a mix of fast + never-draining subscribers must return
    immediately (producer never awaits a socket)."""
    mgr = ExecutionProcessLogStreamManager()
    fast = WsSubscriber(FakeWebSocket(), maxsize=1024)
    slow = WsSubscriber(FakeWebSocket(block=True), maxsize=1024)
    mgr.subscribe("p1", fast)
    mgr.subscribe("p1", slow)

    for i in range(50):
        # Each publish must complete near-instantly regardless of the slow sub.
        await asyncio.wait_for(mgr.publish_log("p1", {"i": i}), timeout=0.1)

    # The producer enqueued to both queues without awaiting either socket.
    assert fast.queue.qsize() == 50
    assert slow.queue.qsize() == 50


@pytest.mark.asyncio
async def test_overflow_evicts_slow_client():
    """A subscriber whose queue fills is dropped from the manager set, marked
    closed, and gets the non-1000 evict code so the frontend reconnects."""
    mgr = ExecutionProcessLogStreamManager()
    slow = WsSubscriber(FakeWebSocket(block=True), maxsize=4)
    mgr.subscribe("p1", slow)

    for i in range(4):
        await mgr.publish_log("p1", {"i": i})  # fills the queue (4 frames)
    assert slow in mgr._subscribers["p1"]

    # 5th frame overflows → subscriber evicted.
    await mgr.publish_log("p1", {"i": 4})
    assert "p1" not in mgr._subscribers or slow not in mgr._subscribers.get("p1", set())
    assert slow._closed is True
    assert slow.evict_code == 1011


@pytest.mark.asyncio
async def test_finished_flushes_in_order_then_closes_1000():
    """publish_finished enqueues {finished:true} after pending frames, and the
    sender flushes everything in order then closes cleanly with 1000."""
    mgr = ExecutionProcessLogStreamManager()
    ws = FakeWebSocket()
    sub = WsSubscriber(ws, maxsize=1024)
    mgr.subscribe("p1", sub)

    sender = asyncio.create_task(sub.run_sender())

    await mgr.publish_log("p1", {"line": 1})
    await mgr.publish_log("p1", {"line": 2})
    await mgr.publish_finished("p1")

    await asyncio.wait_for(sender, timeout=1)

    assert ws.sent == [{"line": 1}, {"line": 2}, {"finished": True}]
    assert ws.closed_with == (1000, "finished")


@pytest.mark.asyncio
async def test_pong_routed_through_queue_single_writer():
    """The _PONG sentinel makes the sender send_text('pong') — keeping the
    sender as the socket's sole writer (no race with a receiver)."""
    ws = FakeWebSocket()
    sub = WsSubscriber(ws, maxsize=16)
    sender = asyncio.create_task(sub.run_sender())

    sub.try_put(_PONG)
    sub.try_put({"hello": "world"})
    sub.close_after_flush(code=1000, reason="finished")

    await asyncio.wait_for(sender, timeout=1)
    assert ws.text_sent == ["pong"]
    assert ws.sent == [{"hello": "world"}]
    assert ws.closed_with == (1000, "finished")


@pytest.mark.asyncio
async def test_message_delta_carries_type_and_seq():
    """publish_delta must enqueue a frame tagged type=message_delta preserving
    seq/delta_text (frontend dedupes by seq)."""
    mgr = ExecutionProcessMessageStreamManager()
    sub = WsSubscriber(FakeWebSocket(), maxsize=16)
    mgr.subscribe("p1", sub)

    await mgr.publish_delta("p1", {"seq": 3, "delta_text": "hi"})
    frame = sub.queue.get_nowait()
    assert frame["type"] == "message_delta"
    assert frame["seq"] == 3
    assert frame["delta_text"] == "hi"


@pytest.mark.asyncio
async def test_try_put_returns_false_after_overflow():
    """Once overflowed, try_put keeps returning False and the subscriber is
    marked closed. Buffered frames remain drainable."""
    sub = WsSubscriber(FakeWebSocket(block=True), maxsize=2)
    assert sub.try_put({"a": 1}) is True
    assert sub.try_put({"a": 2}) is True
    assert sub.try_put({"a": 3}) is False  # overflow (queue full, sentinel dropped)
    assert sub.try_put({"a": 4}) is False  # stays closed
    assert sub._closed is True
    assert sub.queue.get_nowait() == {"a": 1}
    assert sub.queue.get_nowait() == {"a": 2}


@pytest.mark.asyncio
async def test_running_sender_closes_on_overflow_even_when_queue_was_full():
    """When overflow happens on a full queue (sentinel can't be enqueued), a
    sender that later drains a frame still sees _closed and closes with 1011."""

    class GatedWebSocket(FakeWebSocket):
        def __init__(self):
            super().__init__()
            self.release = asyncio.Event()

        async def send_json(self, payload):
            await self.release.wait()  # hold until released, then drain fast
            self.sent.append(payload)

    ws = GatedWebSocket()
    sub = WsSubscriber(ws, maxsize=2)
    sender = asyncio.create_task(sub.run_sender())

    # Fill the queue while the sender is gated, then overflow it.
    assert sub.try_put({"a": 1}) is True
    assert sub.try_put({"a": 2}) is True
    # Sender may have pulled one into send_json; push until overflow.
    while sub.try_put({"a": 9}) is not False:
        pass
    assert sub._closed is True

    ws.release.set()  # let the sender drain
    await asyncio.wait_for(sender, timeout=1)
    assert ws.closed_with == (1011, "overflow")
