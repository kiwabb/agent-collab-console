import inspect
import logging
import sys
import traceback as _traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    stream=sys.stderr,
)

logger = logging.getLogger(__name__)

from app.interfaces.api import router as api_router
from app.interfaces.codex_ws import router as codex_ws_router
from app.interfaces.sse import router as sse_router
from app.interfaces.ws_events import router as ws_events_router

# Capture startup time once at module load — used by /api/codex/version
_started_at = datetime.now(UTC).isoformat()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup: set the event loop on the global event bus so it can receive events from threads
    import asyncio

    from app.application.event_bus import event_bus
    event_bus.set_loop(asyncio.get_running_loop())

    try:
        from app.application.audit_logger import audit_logger

        audit_logger.set_loop(asyncio.get_running_loop())
    except Exception as exc:
        logger.warning("Audit logger init failed: %s", exc)

    try:
        from app.application import timeouts

        timeouts.validate(strict=False)
    except Exception as exc:
        logger.warning("timeout config validation errored: %s", exc)

    try:
        from app.bootstrap import async_store

        if async_store is not None:
            recovered = 0
            for proc in await async_store.list_execution_processes():
                if str(proc.status).lower() != "running":
                    continue
                await async_store.update_execution_process_status(
                    proc.id,
                    status="Failed",
                    exit_code=-1,
                    completed_at=datetime.now(),
                )
                if proc.task_id:
                    codex_task = await async_store.load_codex_task(proc.task_id)
                    if codex_task is not None and codex_task.status in ("responding", "running"):
                        codex_task.status = "failed"
                        codex_task.result = (
                            (codex_task.result or "")
                            + "\n\n[recovery] Backend was restarted while this task was running; "
                            + "the subprocess was killed and this task was marked failed on boot."
                        ).strip()
                        codex_task.updated_at = datetime.now()
                        await async_store.save_codex_task(codex_task)
                recovered += 1
            if recovered:
                logger.info("Recovered %d orphan execution processes from previous run", recovered)
    except Exception as exc:
        logger.warning("Orphan recovery failed: %s", exc)

    try:
        from app.application.conductor_lease import get_conductor_lease_owner
        from app.application.conductor_recovery import recover_orphaned_conductors
        from app.application.event_bus import _workflow_task_dispatcher
        from app.bootstrap import async_store

        if async_store is not None:
            recovered = await recover_orphaned_conductors(
                async_store,
                event_bus=event_bus,
                current_owner=get_conductor_lease_owner(),
                stale_after_s=0,
                recover_foreign_owner=True,
                auto_restart=True,
                task_dispatcher_fn=_workflow_task_dispatcher,
            )
            if recovered:
                logger.info(
                    "Recovered and relaunched %d orphan conductor task(s) from previous run",
                    recovered,
                )
    except Exception as exc:
        logger.warning("Conductor orphan recovery failed: %s", exc)
    # Recover specialist parents stuck in waiting_for_specialist with terminal/missing children.
    try:
        from app.application.conductor_recovery import recover_stuck_specialist_parents
        from app.bootstrap import async_store as _spec_store

        if _spec_store is not None:
            unstuck = await recover_stuck_specialist_parents(_spec_store, event_bus=event_bus)
            if unstuck:
                logger.info("Recovered %d stuck specialist parent task(s)", unstuck)
    except Exception as exc:
        logger.warning("Specialist parent recovery failed: %s", exc)
    # Seed built-in workflow agents (idempotent — only creates missing rows).
    try:
        from app.application.agent_seed import seed_builtin_agents
        from app.bootstrap import WORKFLOW_DAG_ENABLED, async_store
        if async_store is not None:
            created = await seed_builtin_agents(async_store)
            if created:
                logger.info("Seeded %d built-in workflow agents", created)
        # PR5: when DAG mode is on, backfill 4-phase graphs for legacy issues
        # so the new UI can render them without a special case.
        if WORKFLOW_DAG_ENABLED and async_store is not None:
            from app.application.four_phase_preset import (
                backfill_graphs_for_existing_issues,
                ensure_four_phase_preset,
            )
            await ensure_four_phase_preset(async_store)
            migrated = await backfill_graphs_for_existing_issues(async_store)
            if migrated:
                logger.info("Backfilled %d legacy issues with 4-phase preset graph", migrated)
    except Exception as exc:
        logger.warning("Failed to seed built-in agents: %s", exc)

    watchdog_task: asyncio.Task[None] | None = None
    conductor_watchdog_task: asyncio.Task[None] | None = None
    project_review_scheduler_task: asyncio.Task[None] | None = None
    self_improvement_proposal_scheduler_task: asyncio.Task[None] | None = None

    try:
        from app.application.stall_watchdog import run as _run_watchdog
        from app.bootstrap import async_store, get_codex_process_manager
        from app.interfaces.api import _run_task_with_user_content

        if async_store is not None:
            watchdog_task = asyncio.create_task(
                _run_watchdog(async_store, get_codex_process_manager, _run_task_with_user_content),
                name="stall-watchdog",
            )
    except Exception as exc:
        logger.warning("Failed to start stall watchdog: %s", exc)

    try:
        from app.application.conductor_recovery import run_watchdog as _run_conductor_watchdog
        from app.application.event_bus import _workflow_task_dispatcher
        from app.bootstrap import async_store

        if async_store is not None:
            conductor_watchdog_task = asyncio.create_task(
                _run_conductor_watchdog(
                    async_store,
                    event_bus=event_bus,
                    task_dispatcher_fn=_workflow_task_dispatcher,
                ),
                name="conductor-recovery-watchdog",
            )
    except Exception as exc:
        logger.warning("Failed to start conductor recovery watchdog: %s", exc)

    try:
        from app.application.project_review_scheduler import run_project_review_scheduler_loop
        from app.bootstrap import async_store

        if async_store is not None:
            project_review_scheduler_task = asyncio.create_task(
                run_project_review_scheduler_loop(async_store, event_bus=event_bus),
                name="project-review-scheduler",
            )
    except Exception as exc:
        logger.warning("Failed to start project review scheduler: %s", exc)

    try:
        from app.application.self_improvement_proposal_scheduler import (
            run_self_improvement_proposal_scheduler_loop,
        )
        from app.bootstrap import async_store
        from app.interfaces.api import activate_self_improvement_proposal_task

        if async_store is not None:
            self_improvement_proposal_scheduler_task = asyncio.create_task(
                run_self_improvement_proposal_scheduler_loop(
                    async_store,
                    activate_fn=activate_self_improvement_proposal_task,
                    event_bus=event_bus,
                ),
                name="self-improvement-proposal-scheduler",
            )
    except Exception as exc:
        logger.warning("Failed to start self-improvement proposal scheduler: %s", exc)
    yield
    # Shutdown: terminate all running Codex processes via formal terminate_all() interface
    # This avoids orphan child processes when the backend exits
    for background_task in (
        watchdog_task,
        conductor_watchdog_task,
        project_review_scheduler_task,
        self_improvement_proposal_scheduler_task,
    ):
        if background_task is None:
            continue
        background_task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await background_task
    try:
        from app.bootstrap import codex_process_manager
        if codex_process_manager is not None:
            result = codex_process_manager.terminate_all()
            if inspect.isawaitable(result):
                await result
    except Exception:
        logger.debug("codex process manager shutdown failed", exc_info=True)
    try:
        from app.application.project_run_manager import project_run_manager

        await project_run_manager.shutdown_all()
    except Exception:
        logger.debug("project run manager shutdown failed", exc_info=True)
    try:
        from app.application.audit_logger import audit_logger

        await audit_logger.shutdown()
    except Exception:
        logger.debug("audit logger shutdown failed", exc_info=True)
    # Close async store connection to avoid "threads can only be started once" on restart
    try:
        from app.bootstrap import async_store
        if async_store is not None and hasattr(async_store, 'close'):
            await async_store.close()
    except Exception:
        logger.debug("async store shutdown failed", exc_info=True)


app = FastAPI(title="Agent Collaboration Console", lifespan=lifespan)

# Initialize app.state.started_at as early as possible so it is available even
# when the app is instantiated directly (e.g., in TestClient session fixtures
# that do not explicitly enter the lifespan context).
app.state.started_at = _started_at


# FastAPI / Starlette already provide good defaults for HTTPException and
# RequestValidationError (they produce structured {"detail": ...} JSON).
# We only override the catch-all so a 500 includes the real error type and
# message — otherwise frontend toasts show "Internal Server Error" which
# makes user-reported bugs impossible to diagnose remotely.
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
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
app.include_router(ws_events_router, prefix="/api")
app.include_router(sse_router)
