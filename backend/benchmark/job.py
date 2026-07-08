"""In-memory job registry for the benchmark runner.

The benchmark run is slow (real Conductor over N epochs) so the
API surfaces it as a **job**: the POST endpoint returns 202
Accepted with a job id immediately, and the run proceeds in a
background asyncio task. Clients poll GET /runs/{id} for
status / completion.

This module is the smallest possible thing that gets the job
semantics right:

  - one ``Job`` per trigger (id, kind, status, timestamps,
    optional error).
  - one ``JobRegistry`` that holds them by id and is
    process-local. Restart loses in-flight jobs (the conductor
    itself is in-memory; this matches that contract).
  - a tiny ``start_job`` helper that schedules the coroutine
    on the running event loop and tracks the resulting task.

The frontend (PR4) will poll this directly. The persistence
side — the *BenchmarkRun* row that survives a restart — is in
:mod:`benchmark.store`; the *Job* here is the ephemeral "I am
running this run right now" record, which is fine to lose.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from inspect import isawaitable

logger = logging.getLogger(__name__)


# Status lifecycle:
#
#   pending → running → (completed | failed)
#
# Cancellation is not in scope (the runner is offline batch; an
# operator who wants to abort kills the process). The job system
# only needs the four states above to drive the UI's spinner.
JOB_STATUS_PENDING = "pending"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"


@dataclass
class Job:
    id: str
    kind: str  # e.g. "benchmark_run"
    status: str
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    # The "thing the job produces" — for a benchmark run, the run id.
    result_ref: str | None = None
    error: str | None = None
    # Progress hints (0..1). For benchmark runs the runner sets
    # this to (epoch_index / total_epochs) as it goes.
    progress: float = 0.0
    # Free-form metadata the job producer wants to surface (e.g.
    # the candidate label for a benchmark run).
    meta: dict[str, object] = field(default_factory=dict)


type CompletionCallback[ResultT] = Callable[
    [Job, ResultT | None, BaseException | None], object | Awaitable[object]
]


class JobRegistry:
    """In-memory job tracker. Thread-unsafe by design (FastAPI is
    single-threaded under asyncio)."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def create(self, kind: str, *, meta: dict[str, object] | None = None) -> Job:
        job = Job(
            id=f"job-{uuid.uuid4().hex[:8]}",
            kind=kind,
            status=JOB_STATUS_PENDING,
            created_at=datetime.now().isoformat(timespec="seconds"),
            meta=meta or {},
        )
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def update(self, job: Job) -> None:
        if job.id not in self._jobs:
            raise KeyError(f"job {job.id!r} not registered")
        self._jobs[job.id] = job

    def list(self) -> list[Job]:
        return list(self._jobs.values())


# Module-level singleton — matches the project's pattern for
# `event_bus` and `codex_store`. Reset only on backend restart.
REGISTRY = JobRegistry()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


async def start_job[ResultT](
    registry: JobRegistry,
    job: Job,
    coro: Callable[[], Awaitable[ResultT]],
    *,
    on_complete: CompletionCallback[ResultT] | None = None,
) -> None:
    """Schedule ``coro`` as a background asyncio task and update
    ``job`` as it goes.

    ``on_complete`` is called with (job, result, exc) when the
    coroutine returns or raises. It may be either sync or
    ``async``; an async callback is awaited. It runs in the event
    loop's context (NOT in a thread); callers must keep it short
    and non-blocking.
    """
    job.status = JOB_STATUS_RUNNING
    job.started_at = _now()
    registry.update(job)

    async def _maybe_await(
        cb: CompletionCallback[ResultT],
        result: ResultT | None,
        exc: BaseException | None,
    ) -> None:
        """Call a (possibly async) callback, swallowing any exception."""
        try:
            ret = cb(job, result, exc)
            if isawaitable(ret):
                await ret
        except Exception:
            logger.debug("benchmark job callback failed: job_id=%s", job.id, exc_info=True)

    async def _runner() -> None:
        try:
            result = await coro()
        except BaseException as exc:  # noqa: BLE001, RUF100
            job.status = JOB_STATUS_FAILED
            job.completed_at = _now()
            job.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            registry.update(job)
            if on_complete is not None:
                await _maybe_await(on_complete, None, exc)
            return
        job.status = JOB_STATUS_COMPLETED
        job.completed_at = _now()
        job.progress = 1.0
        registry.update(job)
        if on_complete is not None:
            await _maybe_await(on_complete, result, None)

    # Fire-and-forget. The task reference is dropped on the
    # floor — the coroutine holds its own state via the registry
    # + the benchmark store. (For a production deployment with
    # lease-based recovery, we'd keep the task in a set and
    # restart on boot; out of scope for PR3.)
    asyncio.create_task(_runner())  # noqa: RUF006


# ---------------------------------------------------------------------------
# Progress hook — used by the runner to update the job as it goes
# ---------------------------------------------------------------------------


def make_progress_updater(registry: JobRegistry, job: Job) -> Callable[[int, int], None]:
    """Return a ``(epoch_index, total_epochs) -> None`` callback the
    runner can call after every epoch to update the job's
    progress. Stored in the runner's ``options.meta['progress_cb']``
    slot by the API layer."""

    def _update(epoch_index: int, total_epochs: int) -> None:
        if total_epochs <= 0:
            return
        job.progress = min(1.0, (epoch_index + 1) / total_epochs)
        registry.update(job)

    return _update
