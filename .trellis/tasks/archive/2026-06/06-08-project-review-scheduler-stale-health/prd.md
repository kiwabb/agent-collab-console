# Project Review Scheduler Stale Health

## Problem

Diagnostics can report scheduler errors and running state, but it cannot tell
operators that the project review scheduler stopped completing ticks. For
unattended operation, a scheduler that last completed far beyond its configured
interval should degrade global diagnostics even when no explicit error was
recorded.

## Scope

Add a read-only stale health derivation for `project_review_scheduler` in
`GET /api/diagnostics`.

## Requirements

- If `project_review_scheduler.last_error` is present, keep the existing
  degraded error behavior.
- If `project_review_scheduler.running` is `true` and no error is present, keep
  the existing degraded running behavior.
- If `project_review_scheduler.last_completed_at` is present and older than
  `interval_s * 2`, mark the scheduler check degraded.
- The stale detail must be a short generic message and must not expose project
  names, repo paths, task payloads, prompts, or tracebacks.
- The top-level diagnostics `status` must become `"degraded"` when the scheduler
  stale check is degraded.
- If the scheduler has never completed a tick, do not mark it stale from the
  missing timestamp alone.

## Non-Goals

- No automatic scheduler restart.
- No persistence or history table.
- No frontend changes.
- No wall-clock threshold configuration beyond the existing `interval_s`.

## Acceptance Criteria

- Focused diagnostics tests cover stale, non-stale, never-completed, running,
  and error precedence.
- Existing diagnostics secret-redaction behavior remains covered.
- Backend focused tests pass.
