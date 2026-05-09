import asyncio
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.application.event_bus import event_bus


router = APIRouter(prefix="/api")


@router.get("/events")
async def events():
    async def event_generator():
        queue = event_bus.subscribe()
        try:
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            event_bus.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
