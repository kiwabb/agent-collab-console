# Workflow Failed Node Auto Retry

## Goal

Move the issue workflow closer to unattended recovery by letting the backend
automatically retry a failed workflow node once before leaving the node failed
for Conductor or a human operator. This addresses the walkthrough finding that
a single transient executor crash can leave the DAG stuck until someone calls a
manual run endpoint.

## What I Already Know

* `docs/walkthrough-report.md` flags failed-node recovery as a Moonshot gap:
  a failed DAG node required manual API calls, and the scheduler should retry
  once before bubbling up.
* `backend/app/application/workflow_scheduler.py` already reacts to terminal
  task status and mirrors it to the `WorkflowNode`.
* `WorkflowNode` already has `retries` and `max_retries` fields, so this slice
  can avoid a schema change.
* `CodexTask` stores the workflow node id, role, prompt, executor/provider/model
  settings, and review comments needed to create a retry task.
* Existing `/tasks/{id}/rerun` behavior is user-driven; this slice is scheduler
  driven and must remain bounded.

## Assumptions

* The first automatic retry should reuse the same workflow node and create a
  fresh `CodexTask` linked to that node.
* The retry should keep the original prompt and execution settings, while
  appending safe failure context to `review_comment`.
* If dispatching the retry itself fails, the original failed state should remain
  observable rather than being hidden.
* The feature is backend-only; no DAG retry button or frontend state changes in
  this slice.

## Requirements

1. When a workflow-backed task finishes with `failed` or `error`, and its node
   has retries remaining, the scheduler creates a fresh retry task for the same
   workflow node instead of immediately marking the node failed.
2. The node retry counter increments and the node remains actionable
   (`status="running"` with the new task id) while the retry task is dispatched.
3. The retry task inherits project/session/issue/role/prompt/executor/provider
   and model settings from the failed task, and its `review_comment` includes a
   short auto-retry note plus the previous task result if available.
4. The retry path emits observable events:
   * `workflow_node_retrying` with issue id, node id/key, previous task id,
     retry task id, and retry/max counts.
   * `task_status` for the retry task.
5. The retry path is best-effort. If creating or dispatching the retry fails,
   the scheduler marks the node failed as it does today and emits/logs failure
   evidence.
6. Once retries are exhausted, existing failed-node behavior remains unchanged:
   node status becomes `failed`, Conductor completion signaling still happens,
   and phase advancement does not treat the node as done.

## Acceptance Criteria

* A focused backend test proves a first failed workflow task creates and
  dispatches a retry task, increments node retries, and does not mark the node
  failed.
* A focused backend test proves retry exhaustion preserves existing failed-node
  behavior.
* A focused backend test proves retry dispatch failure falls back to marking the
  node failed.
* Existing artifact validation signal tests still pass.
* Backend import smoke succeeds.

## Out of Scope

* Frontend Retry button or node context menu.
* Configurable retry backoff/cadence.
* Changing Conductor role re-dispatch policy.
* Retrying tasks without a workflow node.
* Retrying deterministic QA command failures more than the node budget.

## Technical Notes

* Likely implementation file:
  `backend/app/application/workflow_scheduler.py`.
* Likely test file:
  `backend/tests/test_workflow_scheduler_auto_retry.py`.
* Existing related tests:
  `backend/tests/test_artifact_validation_signal.py`,
  `backend/tests/test_task_rerun_endpoint.py`,
  `backend/tests/test_task_dispatcher.py`.
* Backend spec index:
  `.trellis/spec/vibe-kanban/backend/index.md`.
