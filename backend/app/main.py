from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.interfaces.api import router as api_router
from app.interfaces.codex_ws import router as codex_ws_router
from app.interfaces.sse import router as sse_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: set the event loop on the global event bus so it can receive events from threads
    import asyncio
    from app.application.event_bus import event_bus
    event_bus.set_loop(asyncio.get_running_loop())
    yield
    # Shutdown: terminate all running Codex processes via formal terminate_all() interface
    # This avoids orphan child processes when the backend exits
    try:
        from app.bootstrap import codex_process_manager
        if codex_process_manager is not None:
            codex_process_manager.terminate_all()
    except Exception:
        pass


app = FastAPI(title="Agent Collaboration Console", lifespan=lifespan)
app.include_router(api_router)
app.include_router(codex_ws_router, prefix="/api")  # Add prefix here
app.include_router(sse_router)
