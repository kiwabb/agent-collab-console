from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import logging
import sys
import traceback as _traceback

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    stream=sys.stderr,
)

logger = logging.getLogger(__name__)

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
    # Close async store connection to avoid "threads can only be started once" on restart
    try:
        from app.bootstrap import async_store
        if async_store is not None and hasattr(async_store, 'close'):
            await async_store.close()
    except Exception:
        pass


app = FastAPI(title="Agent Collaboration Console", lifespan=lifespan)


# FastAPI / Starlette already provide good defaults for HTTPException and
# RequestValidationError (they produce structured {"detail": ...} JSON).
# We only override the catch-all so a 500 includes the real error type and
# message — otherwise frontend toasts show "Internal Server Error" which
# makes user-reported bugs impossible to diagnose remotely.
@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.error("Unhandled exception on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"{type(exc).__name__}: {exc}",
            "traceback": _traceback.format_exception_only(type(exc), exc),
        },
    )


app.include_router(api_router)
app.include_router(codex_ws_router, prefix="/api")  # Add prefix here
app.include_router(sse_router)