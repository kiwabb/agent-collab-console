# Agent Help Child-Task Design

## Summary

This document defines a first-version collaboration model where a running Codex or Claude task can explicitly request help from the other agent. The request is represented as a blocking child task, not as a direct agent-to-agent socket conversation.

The parent task pauses at the task-flow level, the backend orchestrator creates and runs a child task, and the parent task resumes only after the child task produces a result or failure. This design keeps the existing task/workspace-first product model intact while adding a clear path for cross-agent collaboration.

## Goals

- Add an explicit `request_help` collaboration primitive for running tasks.
- Represent agent-to-agent help as parent/child tasks inside the existing workspace model.
- Keep child-task execution fully observable through normal task logs, status, and result views.
- Make the backend orchestrator the only component that can create help requests, create child tasks, block parent tasks, and resume parent tasks.
- Support both `codex -> claude` and `claude -> codex` blocking help flows.
- Preserve crash recovery and page refresh recovery through persisted task and help-request state.

## Non-Goals

- Natural-language detection of help intent.
- Direct agent-to-agent chat sockets or broker-mediated free conversation.
- Nested help requests in v1.
- Multiple concurrent child help tasks for one parent task in v1.
- Human approval before child-task launch.
- Cross-workspace help requests.
- True process-level suspend/resume of an in-flight CLI turn.
- Deferred tool-return semantics implemented inside the agent runtime itself.

## Product Definition

When a running task needs help from the other agent, it explicitly emits a `request_help` tool call. The backend orchestrator turns that request into a new child task that runs automatically under the target executor. The parent task enters `waiting_for_help`, the child task runs independently, and the parent task resumes later through a continuation execution after the child task completes or fails.

To the user, this appears as one task temporarily blocked on a collaboration child task. To the system, it is a parent task plus a persisted help-request record plus an auto-run child task.

## Core Design Principle

Agents do not communicate with each other directly. They communicate indirectly through the task orchestration system.

That rule is the main architectural constraint for v1:

- agent runtimes express intent
- the backend orchestrator mutates system state
- child tasks execute normally under the target runtime
- parent-task continuation is orchestrated by persisted task state, not by keeping a runtime call stack suspended in memory

## Interaction Model

### Explicit Collaboration Primitive

The only supported collaboration action in v1 is:

```ts
request_help({
  target: "claude" | "codex",
  title: string,
  prompt: string,
  context_summary?: string,
  blocking: true
})
```

Behavioral rules:

- `blocking` is required and must be `true` in v1.
- Only one unresolved help request may exist for a parent task at a time.
- The target executor must differ from the source executor.
- A child help task cannot itself emit another `request_help` in v1.

### User Experience

The user-facing model remains task-first:

- the parent task shows that it is waiting for help
- the help child task appears under the parent task
- the child task has its own logs, status, and result
- when the child finishes, the parent task resumes and its timeline records that the help result was consumed

The UI should not present this as an open-ended chat between two agents. It should present it as a blocked task with a child collaboration run.

## Responsibilities

There are only three valid event senders in this design.

### Parent Agent Runtime

The parent runtime may only:

- emit `tool_call` intent for `request_help`
- stop normal forward progress after that intent is accepted

The parent runtime may not:

- create help-request records
- create child tasks
- mark the parent task blocked or resumed
- send completion events on behalf of the child task

### Backend Orchestrator

The backend orchestrator is the only component allowed to:

- validate a `request_help` call
- create the `help_request` record
- create the child task
- mark the parent task `waiting_for_help`
- auto-start the child task
- observe child completion or failure
- generate parent-facing help events
- enqueue the parent continuation execution
- mark the help request consumed after successful resume input creation

### Child Task Runtime

The child runtime behaves like any other task runtime:

- start the child task
- emit normal execution logs and result events
- complete or fail the child task

The child runtime does not directly message the parent task.

## Event Ownership

The event boundary must remain explicit.

### Agent Intent Event

Emitted by the parent agent runtime:

```json
{
  "type": "tool_call",
  "tool": "request_help",
  "task_id": "task_parent_1",
  "payload": {
    "target": "claude",
    "title": "Review migration plan",
    "prompt": "Please inspect this migration plan for recovery risks.",
    "context_summary": "The current task is splitting the runtime facade and needs resume semantics reviewed.",
    "blocking": true
  }
}
```

This event means "the agent wants help." It does not mean the request has been accepted.

### System Events

Emitted by the backend orchestrator into the parent task event flow:

```json
{
  "type": "help_requested",
  "task_id": "task_parent_1",
  "help_request_id": "hr_123",
  "child_task_id": "task_child_1",
  "target": "claude"
}
```

```json
{
  "type": "task_blocked",
  "task_id": "task_parent_1",
  "reason": "waiting_for_help",
  "help_request_id": "hr_123"
}
```

```json
{
  "type": "help_child_started",
  "task_id": "task_parent_1",
  "help_request_id": "hr_123",
  "child_task_id": "task_child_1",
  "target": "claude"
}
```

```json
{
  "type": "help_completed",
  "task_id": "task_parent_1",
  "help_request_id": "hr_123",
  "child_task_id": "task_child_1",
  "target": "claude",
  "result": {
    "summary": "The plan is broadly sound but resume semantics need to be explicit.",
    "raw_result": "The plan is broadly sound but resume semantics need to be explicit: ..."
  }
}
```

```json
{
  "type": "help_failed",
  "task_id": "task_parent_1",
  "help_request_id": "hr_123",
  "child_task_id": "task_child_1",
  "error": {
    "code": "child_task_failed",
    "message": "Claude execution timed out"
  }
}
```

```json
{
  "type": "task_resumed",
  "task_id": "task_parent_1",
  "help_request_id": "hr_123"
}
```

These events mean "the system has accepted, executed, and reconciled the collaboration request." They are never emitted directly by either agent runtime.

## Blocking And Resume Model

### Why v1 Uses Task-Flow Suspension

V1 does not attempt true process-level suspension. The parent runtime is not kept paused mid-turn with a live stack waiting for a deferred tool return. That approach would introduce fragile in-memory state, harder restart recovery, and stronger coupling to CLI/runtime internals.

Instead, v1 uses task-flow suspension:

- parent execution runs until `request_help`
- the task becomes logically blocked
- child task runs independently
- when the child finishes, the backend creates a continuation payload
- the parent task resumes in a new execution segment

This preserves the user-visible meaning of a blocking call without depending on process-level pause semantics.

### Continuation Contract

The parent task resumes through a continuation input generated by the backend orchestrator. A representative payload is:

```json
{
  "type": "help_result",
  "help_request_id": "hr_123",
  "target": "claude",
  "status": "completed",
  "result": {
    "summary": "The plan is broadly sound but resume semantics need to be explicit.",
    "raw_result": "The plan is broadly sound but resume semantics need to be explicit: ..."
  }
}
```

The backend may inject this into the parent continuation in either of two ways:

- as a structured continuation payload if the runtime can accept it
- as a system-authored continuation message if the runtime only supports message-like re-entry

V1 should prefer the simpler path: system-injected continuation message. This avoids requiring the runtime to support a true deferred tool-result API.

### Resume Semantics

The parent task should move through these states:

- `running`
- `waiting_for_help`
- `ready_to_resume`
- `running`
- `completed` or `failed`

The help request should move through these states:

- `pending`
- `running`
- `completed` or `failed` or `timed_out`
- `consumed`

`consumed` is required so the system can distinguish "child finished" from "parent successfully resumed using that result" and avoid duplicate continuation delivery after a restart.

## Data Model

### Help Requests

Add a persisted `help_requests` table:

```txt
help_requests
- id
- workspace_id
- parent_task_id
- child_task_id
- source_executor
- target_executor
- title
- prompt
- context_summary
- status
- error_message
- continuation_payload
- created_at
- started_at
- completed_at
- timeout_at
- consumed_at
```

### Tasks

Extend the existing task record with a minimal set of fields:

```txt
tasks
- parent_task_id        nullable
- blocked_by_help_id    nullable
- task_kind             normal | help_child
```

Rationale:

- parent/child relationships belong on tasks
- collaboration lifecycle belongs on `help_requests`
- future multiple help requests per parent remain possible without redesigning the schema

## API Design

V1 should add only a small set of collaboration-specific APIs.

### Read APIs

- `GET /api/tasks/{task_id}/help-requests`
- `GET /api/help-requests/{id}`

These endpoints support task-detail rendering, debugging, and recovery visibility.

### Internal Management APIs

- `POST /api/tasks/{task_id}/help-requests`
- `POST /api/help-requests/{id}/complete`

These endpoints are primarily orchestration boundaries, not user-facing frontend entrypoints. The true business entrypoint is the runtime-emitted `tool_call(request_help)` event.

## Execution Flow

The happy-path collaboration sequence is:

1. The parent task runtime emits `tool_call(request_help)`.
2. The backend orchestrator validates the call and creates a `help_request`.
3. The backend orchestrator creates a child task with the target executor and marks it `help_child`.
4. The backend orchestrator emits `help_requested`.
5. The backend orchestrator marks the parent task `waiting_for_help` and emits `task_blocked`.
6. The backend orchestrator auto-starts the child task and emits `help_child_started` to the parent task timeline.
7. The child task runtime executes normally and finishes with its own result or failure.
8. The backend orchestrator observes child completion or failure and records that outcome on the `help_request`.
9. The backend orchestrator creates a continuation payload for the parent task, emits `help_completed` or `help_failed`, and marks the parent task `ready_to_resume`.
10. The backend orchestrator launches the parent continuation execution and emits `task_resumed`.
11. After the continuation input is safely persisted and handed off, the `help_request` becomes `consumed`.

## Failure Handling

V1 should make failure explicit rather than silently failing the parent task.

### Child Task Failure

If the child task fails:

- mark the child task failed using normal task semantics
- emit `help_failed` to the parent task timeline
- resume the parent task with an error-shaped continuation result

This lets the parent executor decide whether to retry, degrade, or fail the overall task.

### Timeout

If the child task exceeds the configured help timeout:

- mark `help_request.status = timed_out`
- emit `help_failed` with `code = timeout`
- resume the parent task with timeout information

### Restart Recovery

Recovery after backend restart should rely on persisted state only:

- parent tasks in `waiting_for_help`
- help requests not yet `consumed`
- child task status and result
- parent tasks in `ready_to_resume`

The system must never depend on an in-memory suspended runtime stack for correctness.

## UI Design

V1 should keep the UI task-first and literal.

### Parent Task View

The parent task detail should show:

- a `Waiting for Help` state
- the target executor
- the linked child task
- timeline entries for `help_requested`, `help_child_started`, `help_completed` or `help_failed`, and `task_resumed`

### Child Task View

The child task should appear as a normal task with a visual `Help Child` distinction:

- its own status
- its own logs
- its own result
- clear linkage back to the parent task

The UI should not present a chat transcript between two agents. It should present task dependency and task recovery.

## Guardrails

The backend orchestrator should reject a help request when:

- `blocking` is absent or false
- source and target executors are the same
- the parent task already has an unresolved help request
- the current task is itself a `help_child`
- the parent task is not in a running state

These restrictions keep the first version bounded and predictable.

## Open Upgrade Path

This v1 design intentionally leaves room for future extensions:

- nested help requests
- multiple concurrent child help tasks
- user approval before dispatch
- richer structured help results
- true deferred tool-result runtime integration
- broader execution-process-centric orchestration if the product later shifts away from task-centric runtime ownership

Those upgrades should build on the persisted `help_request + child task + continuation` model rather than replacing it with direct runtime-to-runtime messaging.

## Decision

V1 collaboration is implemented as an explicit `request_help` tool call that the backend orchestrator converts into an auto-run blocking child task. Parent tasks block at the task-flow level, not at the process level. Child-task completion or failure is persisted and then delivered back to the parent task through a continuation execution.
