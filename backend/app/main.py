from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import inspect
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
from app.interfaces.ws_events import router as ws_events_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: set the event loop on the global event bus so it can receive events from threads
    import asyncio
    from app.application.event_bus import event_bus
    event_bus.set_loop(asyncio.get_running_loop())

    # Start the unified audit-log drain worker (PR1). The store is wired in
    # bootstrap; setting the loop here spins up the background writer.
    from app.application.audit_logger import audit_logger
    audit_logger.set_loop(asyncio.get_running_loop())

    # Wire the benchmark harness singletons (PR3). The benchmark
    # store is a separate sqlite file (default: backend/benchmark.db)
    # so the production console.db is untouched. The JobRegistry
    # is in-process and resets on backend restart (matches the
    # conductor's lease-based recovery model).
    try:
        from benchmark import api as benchmark_api
        from benchmark.store import SqliteStore as _BenchStore
        from benchmark.job import JobRegistry as _BenchJobRegistry
        benchmark_api.init_for_app(
            store=_BenchStore(benchmark_api.DEFAULT_DB_PATH),
            registry=_BenchJobRegistry(),
        )
    except Exception as exc:  # noqa: BLE001 — benchmark is optional
        logger.warning("Benchmark harness init failed (routes will 503): %s", exc)

    # Validate the timeout ladder (single source of truth in app.application.timeouts).
    # Logs every invariant violation at ERROR level so a bad env combo (e.g. a
    # lease TTL longer than the subagent idle budget, which would cause orphan
    # relaunches) is loud at boot rather than a subtle runtime bug. Non-strict so
    # a misconfig doesn't brick the server.
    try:
        from app.application import timeouts
        timeouts.validate(strict=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("timeout config validation errored: %s", exc)

    # Recover orphan execution_processes left over from a previous backend
    # process. Under `uvicorn --reload` the parent gets SIGKILLed mid-stream
    # and child SDK subprocesses die — the DB rows stay `status=Running`
    # forever, blocking the task from progressing. On boot, mark any such
    # row as `Failed` (with a recovery note) and propagate to the parent
    # task so the UI shows the failure and Retry becomes available.
    try:
        from app.bootstrap import async_store
        from datetime import datetime
        if async_store is not None:
            orphans = await async_store.list_execution_processes()
            recovered = 0
            for proc in orphans:
                if str(proc.status).lower() != "running":
                    continue
                await async_store.update_execution_process_status(
                    proc.id, status="Failed", exit_code=-1, completed_at=datetime.now(),
                )
                # Mark the parent task so the UI surfaces a terminal state.
                if proc.task_id:
                    task = await async_store.load_codex_task(proc.task_id)
                    if task is not None and task.status in ("responding", "running"):
                        task.status = "failed"
                        task.result = (
                            (task.result or "")
                            + "\n\n[recovery] Backend was restarted while this task was running; "
                            + "the subprocess was killed and this task was marked failed on boot."
                        ).strip()
                        task.updated_at = datetime.now()
                        await async_store.save_codex_task(task)
                recovered += 1
            if recovered:
                logger.info("Recovered %d orphan execution processes from previous run", recovered)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Orphan recovery failed: %s", exc)

    try:
        from app.bootstrap import async_store
        from app.application.conductor_lease import get_conductor_lease_owner
        from app.application.conductor_recovery import recover_orphaned_conductors
        from app.application.event_bus import _workflow_task_dispatcher
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
                logger.info("Recovered and relaunched %d orphan conductor task(s) from previous run", recovered)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Conductor orphan recovery failed: %s", exc)

    # Seed built-in workflow agents (idempotent — only creates missing rows).
    try:
        from app.bootstrap import async_store, WORKFLOW_DAG_ENABLED
        from app.application.agent_seed import seed_builtin_agents
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
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to seed built-in agents: %s", exc)

    # Spawn the stall watchdog: nudges agents that go silent past the
    # threshold. Gated by CODEX_STALL_WATCHDOG (default on); the watchdog
    # itself exits cleanly if the env disables it.
    watchdog_task: asyncio.Task | None = None
    conductor_watchdog_task: asyncio.Task | None = None
    project_review_scheduler_task: asyncio.Task | None = None
    self_improvement_proposal_scheduler_task: asyncio.Task | None = None
    try:
        from app.bootstrap import async_store, get_codex_process_manager
        from app.application.stall_watchdog import run as _run_watchdog
        from app.interfaces.api import _run_task_with_user_content
        if async_store is not None:
            watchdog_task = asyncio.create_task(
                _run_watchdog(async_store, get_codex_process_manager, _run_task_with_user_content),
                name="stall-watchdog",
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to start stall watchdog: %s", exc)

    try:
        from app.bootstrap import async_store
        from app.application.conductor_recovery import run_watchdog as _run_conductor_watchdog
        from app.application.event_bus import _workflow_task_dispatcher
        if async_store is not None:
            conductor_watchdog_task = asyncio.create_task(
                _run_conductor_watchdog(
                    async_store,
                    event_bus=event_bus,
                    task_dispatcher_fn=_workflow_task_dispatcher,
                ),
                name="conductor-recovery-watchdog",
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to start conductor recovery watchdog: %s", exc)

    try:
        from app.bootstrap import async_store
        from app.application.project_review_scheduler import run_project_review_scheduler_loop
        if async_store is not None:
            project_review_scheduler_task = asyncio.create_task(
                run_project_review_scheduler_loop(async_store, event_bus=event_bus),
                name="project-review-scheduler",
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to start project review scheduler: %s", exc)

    try:
        from app.bootstrap import async_store
        from app.application.self_improvement_proposal_scheduler import (
            run_self_improvement_proposal_scheduler_loop,
        )
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
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to start self-improvement proposal scheduler: %s", exc)

    yield
    # Shutdown: terminate all running Codex processes via formal terminate_all() interface
    # This avoids orphan child processes when the backend exits
    if watchdog_task is not None:
        watchdog_task.cancel()
        try:
            await watchdog_task
        except (asyncio.CancelledError, Exception):
            pass
    if conductor_watchdog_task is not None:
        conductor_watchdog_task.cancel()
        try:
            await conductor_watchdog_task
        except (asyncio.CancelledError, Exception):
            pass
    if project_review_scheduler_task is not None:
        project_review_scheduler_task.cancel()
        try:
            await project_review_scheduler_task
        except (asyncio.CancelledError, Exception):
            pass
    if self_improvement_proposal_scheduler_task is not None:
        self_improvement_proposal_scheduler_task.cancel()
        try:
            await self_improvement_proposal_scheduler_task
        except (asyncio.CancelledError, Exception):
            pass
    try:
        from app.bootstrap import codex_process_manager
        if codex_process_manager is not None:
            result = codex_process_manager.terminate_all()
            if inspect.isawaitable(result):
                await result
    except Exception:
        pass
    # Kill any project dev-server processes so we never leak orphans on restart.
    try:
        from app.application.project_run_manager import project_run_manager
        await project_run_manager.shutdown_all()
    except Exception:
        pass
    # Flush + stop the audit-log drain worker before closing the store so any
    # queued audit rows land instead of being dropped on shutdown.
    try:
        from app.application.audit_logger import audit_logger
        await audit_logger.shutdown()
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
app.include_router(ws_events_router, prefix="/api")
