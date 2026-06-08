# Project Review Background Loop

## Goal

Run the project review scheduler tick from a real backend background loop so
scheduled project health reviews can happen without an operator manually
triggering each scan.

## Scope

- Add an application-layer loop beside `run_project_review_tick`.
- Wire that loop into FastAPI lifespan startup and shutdown.
- Keep all cadence and work-bound knobs in `app.application.timeouts`.
- Preserve the existing tick contract: project enumeration goes through the
  typed store API, each project is delegated to `ProjectConductor`, and
  per-project failures remain isolated.

## Non-Goals

- No persistent schedule table.
- No UI for configuring schedules.
- No benchmark integration in this slice.
- No changes to GitHub PR follow-up internals.

## Contracts

- The loop calls the scheduler tick, then sleeps for the configured cadence.
- A tick-level unexpected exception is logged and the next cycle still runs.
- `asyncio.CancelledError` is allowed to propagate so lifespan shutdown can
  stop the task promptly.
- The loop accepts injected tick and sleep callables for deterministic tests.
- Lifespan creates a named `project-review-scheduler` task when the async store
  is available, and cancels/awaits it during shutdown.

## Tests

- Scheduler loop repeats according to injected sleep cadence.
- Scheduler loop survives a tick exception and continues.
- Scheduler loop propagates cancellation.
- Lifespan starts the named background task and cancels it on shutdown.
