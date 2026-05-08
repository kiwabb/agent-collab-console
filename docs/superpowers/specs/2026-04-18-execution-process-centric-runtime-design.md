# Execution-Process-Centric Runtime Design

## Summary

This document defines a full migration from the current task-centric runtime model to an execution-process-centric runtime model aligned with the official vibe-kanban source approach. The goal is to make `ExecutionProcess` the only live runtime entity used for streaming state, logs, messages, approvals, and lifecycle transitions, while reducing `Task` to a stable metadata and grouping layer.

The design explicitly avoids a compatibility-first or minimum-change approach. The target architecture replaces task-rooted runtime state with execution-process-rooted runtime state across backend projections, WebSocket patches, frontend stores, and UI composition.

## Goals

- Make `ExecutionProcess` the single source of truth for runtime state.
- Align the WebSocket patch stream root with `execution_processes`.
- Align frontend state and hooks with `execution_processes` instead of `tasks`.
- Keep `Task` as a container, launch entry, and grouping/indexing concept rather than a live runtime projection.
- Preserve a usable task-based launch API where helpful, but ensure it returns and depends on `ExecutionProcess`.

## Non-Goals

- Keeping task-centric runtime fields as first-class long-term state.
- Preserving every current API payload shape unchanged.
- Building a dual-model runtime where tasks and execution processes both own live state.
- Matching the official repository file-for-file. The goal is semantic and architectural alignment, not textual cloning.

## Current Problems

The current application has already moved partway toward execution processes, but the runtime model is still split:

- `POST /codex/tasks/{task_id}/run` returns an `ExecutionProcess`.
- `Task` stores `last_execution_process_id`.
- The frontend already consumes a JSON Patch WebSocket stream.

However, the live state root is still task-centric:

- Backend WebSocket state is rooted at `tasks`.
- Patch updates are emitted under `/tasks/...`.
- Frontend hooks still maintain `tasks` and `tasksById`.
- Runtime details such as logs, messages, and status are still understood as task-owned state.

This creates a mixed model where `ExecutionProcess` exists as an object, but `Task` still behaves like the real runtime entity. That mismatch is the main source of drift from the official source architecture.

## Target Architecture

### Core Domain Model

The runtime hierarchy becomes:

- `Session`
  - Owns and lists many `ExecutionProcess` instances.
- `ExecutionProcess`
  - Owns lifecycle state, timestamps, runtime metadata, logs, messages, approvals, and exit/result data.
- `Task`
  - Owns user-facing intent and grouping metadata.
  - References related execution processes.
  - May expose `last_execution_process_id` as an index, but does not own live runtime state.

### Runtime Ownership Rules

- All live run state belongs to `ExecutionProcess`.
- All streamable logs belong to `ExecutionProcess`.
- All conversation or agent output shown in the run detail belongs to `ExecutionProcess`.
- All approval requests and approval outcomes belong to `ExecutionProcess`.
- `Task` can summarize or point to execution processes, but cannot be the source of live run truth.

This is the key invariant for the migration. Any new feature that introduces live runtime data must attach it to `ExecutionProcess`.

## Backend Design

### Execution Process View

The backend should expose a normalized `ExecutionProcessView` projection as the streamable frontend-facing model. That view should include, at minimum:

- `id`
- `session_id`
- `task_id`
- `status`
- `title` or derived display label
- `created_at`
- `started_at`
- `updated_at`
- `completed_at`
- `workspace_path`
- `resume_session_id`
- `pid` or process metadata when available
- `exit_code`
- `error`
- `messages`
- `logs`
- `approval_state` or approval items

The exact field names can follow local conventions, but the projection must be coherent enough that the frontend never needs to merge task state, log state, and message state from separate roots to render a run.

### Repository and Service Boundaries

Recommended backend responsibilities:

- `TaskRepository`
  - Stores task metadata and task-to-execution-process relationships.
- `ExecutionProcessRepository`
  - Stores execution process records and execution-process-owned runtime data.
- `ExecutionProcessProjection`
  - Builds a JSON-serializable frontend view from runtime data.
- `ExecutionProcessEventStream`
  - Emits snapshot and patch updates for execution process projections.

The event stream boundary is important: frontend consumers should subscribe to projected execution process state, not to low-level domain events.

### Event Categories

Different backend events can still exist internally, but they must all converge into execution-process projection updates:

- Lifecycle events
  - Created, queued, running, completed, failed, canceled.
- Log events
  - stdout, stderr, structured logs, agent tool output.
- Message events
  - user message, assistant message, system message, internal markers used in the run detail.
- Approval events
  - approval requested, resolved, denied, expired.
- Metadata events
  - workspace creation, process attachment, resume linkage, exit code updates.

The frontend should not consume these categories independently. The WebSocket layer should emit patches against `execution_processes` after projection.

### API and WebSocket Semantics

#### Launching

`POST /codex/tasks/{task_id}/run` can remain as the primary launch endpoint, but its semantics must be explicit:

- The endpoint creates a new `ExecutionProcess`.
- The response body is the created `ExecutionProcess` or `ExecutionProcessView`.
- Any task updates caused by launching are secondary metadata updates, not the source of runtime truth.

#### Snapshot Endpoint

The session-level read model should support an execution-process snapshot endpoint:

- `GET /api/sessions/{session_id}/execution_processes`

This endpoint returns the current execution process collection for the session, ready for initial load or recovery.

#### WebSocket Endpoint

The session-level stream should be execution-process-rooted:

- `WS /api/sessions/{session_id}/execution_processes/ws`

Its payload contract should follow this model:

- Initial sync sends `replace /execution_processes` with the current map.
- Incremental updates use:
  - `add /execution_processes/<id>`
  - `replace /execution_processes/<id>/...`
  - `remove /execution_processes/<id>`

Task patches should not be multiplexed into this stream.

## Frontend Design

### Primary Hook Contract

The frontend should expose a single session runtime hook centered on execution processes:

- `useExecutionProcesses(sessionId)`

It should own a state root like:

```js
{
  execution_processes: {
    [id]: ExecutionProcessView
  }
}
```

The hook should return:

- `executionProcesses`
- `executionProcessesById`
- `isConnected`
- `connectionState`
- `error`

It should not return `tasks` as the runtime model.

### Patch Application

The WebSocket layer should only transport JSON Patch payloads. Business interpretation belongs in the store or view layer, not in the transport layer.

The reducer or patch application mechanism should operate over the `execution_processes` root only. If the project later replaces the current patch application helper with an immer-style reducer closer to the official source, that is acceptable and encouraged, but the architectural requirement is more important than the exact library choice:

- one patch stream
- one runtime root
- one store contract

### UI Composition

The UI should be recomposed around execution processes:

- Session runtime list
  - Lists execution processes, not tasks pretending to be runs.
- Run detail panel
  - Reads directly from one `ExecutionProcessView`.
- Task views
  - Become metadata/grouping views that summarize or filter related execution processes.

This changes the data flow from:

- `session -> tasks -> current execution`

to:

- `session -> execution processes`
- `task -> derived grouping or filtering view`

That simplification is one of the main benefits of the migration.

## Migration Strategy

The migration should be executed in a fixed order. The goal is not to preserve the old architecture; the goal is to avoid an uncontrolled rewrite.

### Phase 1: Establish ExecutionProcessView

Create the backend projection that can fully represent a run without reading task-owned runtime state.

Exit criteria:

- A single execution process projection can drive a detail view.
- Status, logs, messages, approvals, and completion state are all available from the projection.

### Phase 2: Switch the WebSocket Stream Root

Move the session WebSocket stream to `execution_processes`.

Exit criteria:

- Initial sync sends `replace /execution_processes`.
- Incremental updates only patch `execution_processes`.
- The stream no longer relies on `/tasks/...` patches for runtime updates.

### Phase 3: Switch the Frontend Runtime Store

Update the frontend hook and consuming components to treat `execution_processes` as the primary runtime state.

Exit criteria:

- Main runtime pages render from `executionProcesses`.
- Components no longer require task-owned runtime state to display a running process.
- Reconnect and refresh behavior rebuild from execution-process snapshots cleanly.

### Phase 4: Downgrade Task to Metadata

Remove or deprecate task fields that duplicate live runtime state.

Candidate removals or downgrades include:

- live task status fields
- task-owned message collections
- task-owned log collections
- any task-level "current run" payloads that duplicate execution process state

Exit criteria:

- `Task` is no longer a live runtime entity.
- New runtime features attach to `ExecutionProcess` only.

## Compatibility Policy

This migration intentionally does not optimize for long-term dual-model compatibility.

Temporary compatibility is acceptable only while a downstream consumer is being moved in the same migration sequence. New behavior must not be added to the old task-centric runtime path.

That means:

- no new task-rooted patch types
- no new task-owned runtime fields
- no new frontend features that depend on task-centric live state

If a short-lived adapter is needed during migration, it should be isolated and explicitly marked for deletion after the frontend store switch.

## Error Handling and Recovery

The execution-process-centric design must support the following operational behavior:

- Refreshing a session reconstructs runtime state from the execution process snapshot.
- WebSocket reconnect uses the latest execution process snapshot plus fresh patches.
- A failed process still retains its logs, messages, and failure metadata in the execution process detail.
- A task can show the last or active execution process without reconstructing runtime state from multiple stores.

This prevents the current class of bugs where a reconnect or partial update can leave task state, logs, and messages out of sync.

## Verification Criteria

The migration is complete only when all of the following are true:

1. Creating a run produces a new `ExecutionProcess` that can be rendered without task patches.
2. Logs, messages, approvals, lifecycle state, and exit status for a run are readable from one execution process detail source.
3. Session refresh rebuilds runtime state from execution process snapshots.
4. WebSocket reconnect does not require task-rooted runtime reconciliation.
5. Task views, if retained, show derived state from execution processes rather than owning live runtime state.
6. There are no new backend or frontend runtime features that treat `Task` as the primary live runtime entity.

## Risks

### Scope Risk

This migration affects backend models, stream contracts, frontend stores, and UI composition. It is larger than a local refactor and should be planned as a cross-cutting runtime migration.

### Temporary Duplication Risk

During the migration window, the codebase may briefly contain both task-centric and execution-process-centric paths. This is acceptable only if there is a strict removal path and no new features are added to the old model.

### Testing Risk

If tests remain task-shaped while the runtime becomes execution-process-shaped, they will either mask regressions or become misleading. The implementation plan must move tests to the new runtime shape in parallel with code changes.

## Open Decisions Already Resolved

The following design questions are resolved for this migration:

- The migration is full-architecture alignment, not a minimum-change patch.
- `ExecutionProcess` is the only live runtime entity.
- `Task` remains as metadata and grouping, not as live runtime truth.
- The WebSocket patch root becomes `execution_processes`.
- The frontend primary runtime store becomes `execution_processes`.
- Temporary compatibility is allowed only as a bounded migration tactic, not as an end state.

## Implementation Planning Readiness

This design is intentionally scoped to one migration stream: replace the task-centric runtime model with an execution-process-centric runtime model aligned to the official source architecture. It is ready to be broken into an implementation plan covering backend projection work, stream contract changes, frontend state migration, UI adaptation, test migration, and old-path cleanup.
