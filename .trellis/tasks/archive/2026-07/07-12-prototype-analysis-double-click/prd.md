# Fix duplicate prototype analysis submission

## Goal

Prevent rapid repeated clicks on the prototype design "Start analysis" action from creating multiple analysis plans before React has rendered the existing loading state.

## What I already know

- The entry point is `ProjectPrototypesPage.handleCreatePlan`.
- The button already uses `disabled={planCreating}` and shows a spinner.
- React state updates do not synchronously guard a second invocation in the same render cycle, so two rapid clicks can call `createPrototypePlan` twice.
- The current working tree contains unrelated in-progress changes that must be preserved.

## Requirements

- Guard the create-plan handler with a synchronous in-flight lock before calling the API.
- Keep the existing disabled button and loading indicator as user feedback.
- Release the lock when the request fails so the user can retry.
- Keep the lock held during successful navigation; do not briefly re-enable the action before leaving the page.
- Do not clear existing data or hide request errors.

## Acceptance Criteria

- [x] Two immediate invocations while the first request is pending result in exactly one create-plan request.
- [x] A failed request releases the guard and a later invocation can retry.
- [x] Existing error toast behavior remains intact.
- [x] The relevant focused frontend test passes.

## Definition of Done

- Focused tests pass.
- The implementation follows the frontend component and state-management guidelines.
- No unrelated working-tree changes are modified.

## Out of Scope

- Backend idempotency keys or API contract changes.
- Changes to reanalysis on the plan review page.
- Refactoring other action handlers.

## Technical Notes

- Relevant implementation: `frontend/src/features/prototype/ProjectPrototypesPage.tsx`.
- Relevant specs: `.trellis/spec/ccgui/frontend/component-guidelines.md`, `.trellis/spec/ccgui/frontend/state-management.md`, and `.trellis/spec/ccgui/frontend/quality-guidelines.md`.
