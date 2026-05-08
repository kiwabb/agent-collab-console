# Requirements To Architecture Transition Design

## Summary

Add a dedicated "流转到架构" action to the issue detail view so a user can explicitly move an issue from the requirements phase into the architecture phase after reviewing the generated requirements artifacts.

The action should:

- only appear for issues currently in the `requirements` phase
- require a lightweight confirmation
- update the issue phase to `architecture`
- create one `architect` task for the issue
- not automatically run the new task

This keeps stage advancement explicit and low-risk while removing the current manual two-step flow of changing phase and then creating the next task separately.

## Goals

- make phase advancement from requirements to architecture obvious and intentional
- reduce manual coordination work after a PRD is accepted
- preserve user control over when architecture execution actually starts
- fit the current issue detail layout without introducing new navigation patterns

## Non-Goals

- automatic phase advancement after PM completion
- automatic execution of the architect task
- generic workflow automation across all phases
- redesign of the full issue detail panel

## Recommended Approach

Use a dedicated backend transition endpoint and a single contextual button in the issue detail footer.

Why this approach:

- keeps the user action explicit
- avoids fragile front-end orchestration across multiple API calls
- allows the backend to validate phase, artifacts, and duplicate-task conditions in one place
- matches the existing detail-panel pattern where the main workflow actions live at the bottom

## Alternatives Considered

### Option 1: Footer transition button plus backend transition endpoint

This is the recommended option.

Pros:

- clear user intent
- backend can handle all validation atomically
- minimal UI surface area
- easy to reason about and test

Cons:

- adds one more button to the footer action area

### Option 2: Put the transition action inside the phase selector

Pros:

- visually close to the phase concept

Cons:

- mixes state selection with workflow actions
- increases the chance of accidental stage changes
- makes the phase selector harder to scan

### Option 3: Auto-create architect task when the user manually changes phase

Pros:

- fewer visible controls

Cons:

- surprises users because a passive state change also creates work
- makes "change phase" and "create next task" inseparable
- harder to explain and test

## UX Design

### Placement

Place the "流转到架构" button in the issue detail footer action area, adjacent to the existing primary "run current phase" button.

The footer already acts as the action zone for the selected issue. Keeping the transition button there maintains a clear hierarchy:

- primary action: run the current phase role
- secondary action: advance the workflow to the next stage

### Visibility Rules

Show the transition button only when all of the following are true:

- the issue is in `requirements`
- there is no actively running task for the issue

Hide the button for all non-requirements phases.

### Enabled/Disabled Rules

Enable the button when the issue has at least one requirements artifact:

- `requirement.md`, or
- `prd.json`, or
- `prd.md`

Disable the button otherwise, with a short explanation that requirements output must exist first.

Disable the button while the transition request is in flight.

### Confirmation

Clicking the button opens a lightweight confirmation dialog.

Recommended copy:

- Title: `流转到架构阶段`
- Body: `确认将该需求流转到架构阶段，并创建一条 Architect 任务？`
- Confirm button: `确认流转`
- Cancel button: `取消`

### Success Result

After confirmation succeeds:

- the current issue updates to `architecture`
- a new architect task appears in the task list
- the footer primary action naturally changes to the architecture-stage run button
- the view stays on the current issue detail page

No auto-navigation into the newly created task is required.

## Backend Design

### New Endpoint

Add a dedicated endpoint:

- `POST /api/codex/issues/{issue_id}/transition-to-architecture`

This endpoint is responsible for the full transition flow.

### Request

No request body is required.

The issue id in the path is sufficient.

### Response

Return a payload containing:

- the updated issue
- the created architect task
- an indicator describing whether the task was newly created or already existed

Suggested shape:

```json
{
  "issue": { "...": "updated issue" },
  "task": { "...": "architect task" },
  "created": true
}
```

### Validation Rules

The endpoint must:

1. verify the issue exists
2. verify the issue is currently in `requirements`
3. verify there is no running task for the issue
4. verify at least one requirements artifact exists
5. check whether an architect task for this issue already exists

### Duplicate Architect Task Handling

If an architect task already exists for the issue, do not create another one.

Instead:

- keep the issue in or move it to `architecture`
- return the existing architect task
- return `created: false`

This avoids duplicate planning work and makes the transition action idempotent enough for repeated clicks.

### Task Creation Rules

The created task should use:

- `role = "architect"`
- `phase = "architecture"`
- `executor = "codex"` by default unless the existing issue/task creation flow already dictates a different workspace-level default
- `issue_id = current issue id`
- `title = "架构 - {issue.title}"`
- `prompt = "请基于当前需求产物进行架构设计。"`

The prompt should remain simple because the role workflow service already builds the managed architect prompt from the issue artifacts.

### Persistence and Events

The endpoint should:

- save the updated issue phase
- save the architect task if created
- emit the same issue/task events used elsewhere so the frontend state stays consistent

At minimum:

- issue update event for refreshed issue state
- task created event if a new architect task is generated

## Frontend Design

### Issue Detail Panel

Update the issue detail panel footer to support a secondary action button for requirements-stage transition.

Behavior:

- when `issue.current_phase === "requirements"`, render the secondary button
- on click, open the confirmation dialog
- on confirm, call the new transition API
- update local `issues` and `tasks` state using the response
- refresh artifacts if needed

### Loading and Error States

During submission:

- disable both confirm and cancel actions within the modal if desired, or at minimum disable confirm
- prevent repeated requests

If the request fails:

- keep the user on the same issue
- show the existing error channel with a concise message

If the backend returns an existing architect task:

- treat it as a successful transition
- optionally show a short message that the architecture task already existed

## Data Flow

1. User opens an issue in the requirements phase.
2. User clicks "流转到架构".
3. Frontend opens confirmation dialog.
4. User confirms.
5. Frontend calls `POST /api/codex/issues/{issue_id}/transition-to-architecture`.
6. Backend validates the issue and requirement artifacts.
7. Backend updates the issue phase and creates or returns the architect task.
8. Frontend merges the updated issue and task into local state.
9. Issue detail panel rerenders in the architecture phase.

## Error Handling

### Backend Errors

- `404` if the issue does not exist
- `409` if the issue is not in the requirements phase
- `409` if a task is currently running for the issue
- `409` if requirements artifacts are missing

### Frontend Handling

Map these errors to human-readable messages. Keep them short and action-oriented.

Examples:

- `只有需求阶段的 issue 才能流转到架构`
- `当前有任务仍在运行，请等待完成后再流转`
- `请先生成需求产物后再流转到架构`

## Testing Strategy

### Backend Tests

- transition succeeds from requirements and creates one architect task
- transition moves the issue phase to architecture
- transition fails for non-requirements issues
- transition fails when a task is still running
- transition fails when no requirements artifact exists
- transition returns the existing architect task instead of creating duplicates

### Frontend Tests

- button only appears in requirements phase
- button is disabled when artifacts are missing
- confirmation dialog opens and closes correctly
- successful transition updates displayed issue phase
- successful transition adds or reveals the architect task

## Scope Check

This is a focused single-feature change. It is small enough for one implementation plan and does not need decomposition.

## Ambiguity Resolution

The only non-obvious product choice was whether transition should also auto-run architect. This spec fixes that explicitly:

- transition creates the architect task
- transition does not auto-run it

That behavior should remain stable unless the product requirement changes later.
