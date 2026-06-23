# Project Review Scheduler Status

## Goal

Make the project review scheduler background loop observable so operators and
future autonomous supervisors can tell whether the unattended review loop is
configured, active, succeeding, or repeatedly failing.

## Scope

- Add an application-layer status snapshot for the project review scheduler
  loop.
- Update the scheduler loop to record tick start/completion, success counts,
  failures, and cancellation state.
- Expose the status through `GET /api/diagnostics` without leaking project
  content, repository paths, prompts, or credentials.
- Keep the status in memory for this slice; no persistent schedule/state table.

## Non-Goals

- No UI changes.
- No schedule persistence or per-project schedule configuration.
- No changes to the `ProjectConductor` scheduled-review task semantics.
- No alerting/websocket push in this slice.

## Contracts

- Diagnostics includes a top-level `project_review_scheduler` object.
- The diagnostics object includes only safe operational fields:
  `configured`, `interval_s`, `limit`, `running`, `tick_count`,
  `last_started_at`, `last_completed_at`, `last_error`, and
  `last_summary_counts`.
- The scheduler loop records `running=True` while a tick is in progress and
  returns it to `False` after success or regular exception.
- A successful tick increments `tick_count`, records completion time, clears
  `last_error`, and stores the summary counts.
- A regular tick exception increments `tick_count`, records completion time,
  stores safe error text, and the loop still sleeps/continues.
- `asyncio.CancelledError` still propagates for lifespan shutdown; cancellation
  leaves `running=False` and does not pretend a tick completed successfully.

## Tests

- Unit tests for status transitions on successful tick, failed tick, and
  cancellation.
- Diagnostics test that the new top-level object is present and contains
  configured interval/limit fields.
- Diagnostics test that scheduler status error text is exposed without leaking
  unrelated secrets.
