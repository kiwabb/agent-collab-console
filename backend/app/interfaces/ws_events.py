from __future__ import annotations  # noqa: I001

import asyncio  # noqa: I001, RUF100
import contextlib
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.application.event_bus import event_bus


router = APIRouter()


@router.websocket("/ws/events")
async def global_events_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    queue = event_bus.subscribe()
    last_event_id = websocket.query_params.get("last_event_id")
    replay, missed = event_bus.replay_from(last_event_id)
    sent_event_ids: set[str] = set()
    send_lock = asyncio.Lock()
    if missed:
        gap = {
            "v": 1,
            "ts": datetime.now().isoformat(),
            "event_id": "resume-gap",
            "type": "resume_gap",
            "payload": {
                "from_event_id": last_event_id,
                "reason": "buffer_overflow",
            },
        }
        sent_event_ids.add("resume-gap")
        async with send_lock:
            await websocket.send_json(gap)
    else:
        for envelope in replay:
            if envelope.get("event_id"):
                sent_event_ids.add(str(envelope["event_id"]))
            async with send_lock:
                await websocket.send_json(envelope)

    last_pong_at = asyncio.get_running_loop().time()

    async def sender() -> None:
        while True:
            envelope = await queue.get()
            event_id = str(envelope.get("event_id") or "")
            if event_id and event_id in sent_event_ids:
                continue
            if event_id:
                sent_event_ids.add(event_id)
            async with send_lock:
                await websocket.send_json(envelope)

    async def receiver() -> None:
        nonlocal last_pong_at
        while True:
            message = await websocket.receive_text()
            if message == "pong":
                last_pong_at = asyncio.get_running_loop().time()

    async def heartbeat() -> None:
        nonlocal last_pong_at
        while True:
            await asyncio.sleep(30)
            async with send_lock:
                await websocket.send_json(
                    {
                        "v": 1,
                        "ts": datetime.now().isoformat(),
                        "event_id": "ping",
                        "type": "ping",
                        "payload": {},
                    }
                )
            if asyncio.get_running_loop().time() - last_pong_at > 60:
                await websocket.close(code=1011, reason="pong timeout")
                return

    tasks: list[asyncio.Task[None]] = [
        asyncio.create_task(sender()),
        asyncio.create_task(receiver()),
        asyncio.create_task(heartbeat()),
    ]
    try:
        await asyncio.gather(*tasks)
    except WebSocketDisconnect:
        pass
    finally:
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect):
                await task
        event_bus.unsubscribe(queue)
