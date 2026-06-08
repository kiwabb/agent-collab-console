# Project Review Scheduler

## Goal

Move scheduled project reviews one step closer to unattended operation by adding a backend scheduler service that can run one bounded review tick across projects and reuse the existing `ProjectConductor` scheduled-review path.

## Requirements

1. The scheduler tick lists projects from the store and starts a `scheduled_review` conductor task for each selected project.
2. Each project review reuses `ProjectConductor.handle_task(...)` so GitHub PR follow-up and auto-merge behavior added in earlier slices is preserved.
3. The tick returns an observable summary with per-project `done` / `failed` statuses, task ids, and conductor results or safe error text.
4. A failure for one project is isolated: subsequent projects still run, and the tick itself returns a summary instead of raising.
5. The tick supports a bounded `limit` so future background loops can cap work per scan.

## Acceptance Criteria

- A focused backend test proves the scheduler tick creates scheduled-review conductor tasks for listed projects.
- A focused backend test proves project failures are reported while later projects still run.
- A focused backend test proves the `limit` bounds project selection.
- Backend import smoke succeeds.

## Non-Goals

- Do not add a persistent schedule table in this slice.
- Do not add frontend controls in this slice.
- Do not tune cadence or startup wiring beyond what is needed for the tested scheduler tick.
