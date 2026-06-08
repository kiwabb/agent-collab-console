# Implementation Diff Completion Guard

## Goal

Move the existing real-codegen guard earlier in the workflow lifecycle: when an implementation workflow node finishes with a report that claims changed files but the real git diff is empty, the scheduler should treat the node as failed and let the workflow auto-retry immediately. This closes the gap where a bad Engineer run can still advance the node to `done` and wait for review/QA to catch the contradiction.

## What I Already Know

* The Moonshot direction prioritizes unattended issue-to-merged-PR autonomy, including self-healing when a workflow step silently fails.
* Recent work added automatic retry for failed workflow nodes, so this task should preferably fail/retry a bad implementation node instead of only recording a passive warning.
* `05-30-engineer-real-codegen-architect-review-diff-vs-plan-guard` already added Engineer prompt hardening, Engineer result reconciliation, Architect Review diff-vs-claim/plan guard, and QA soft git cross-check.
* `EngineerWorkflow.persist_result()` currently downgrades a false `completed` or `partial` report to `partial`, clears `changed_files`, and adds a `[framework]` QA note, but it does not make the task terminal status fail.
* `WorkflowScheduler.on_task_completed()` maps `task.status == "done"` to `node.status == "done"` unless an artifact validation marker is present; it does not inspect the Engineer document's framework notes.
* `engineer_workflow.git_changed_files()` is the shared source of truth for real changed files and already ignores issue artifacts under `issues/`.
* `WorkflowScheduler._maybe_auto_retry_failed_node()` already creates a retry task when a workflow node becomes failed and still has retry budget.

## Assumptions (Temporary)

* The MVP should focus on managed Engineer roles (`engineer`, `engineer_frontend`, `engineer_backend`) attached to workflow nodes.
* The guard should only hard-fail claim-vs-reality contradictions that are already deterministic: Engineer claimed changed files, but real git diff was empty.
* Honest zero-diff outcomes, such as already-implemented work with `changed_files=[]`, should remain legal and must not be failed.
* The guard should reuse existing retry behavior by converting the current completion into a failed terminal state before the node is marked done.
* The guard should not introduce a new LLM call or a new git parser.

## Open Questions

* No blocking product question remains. The design choice is to classify guarded nodes by task role because `CodexTask.role` already distinguishes Engineer roles and avoids adding schema fields.

## Requirements (Evolving)

* Detect a workflow-backed Engineer task whose persisted report contains a framework diff contradiction.
* Convert that task completion to a failure before the workflow node is marked `done`.
* Reuse existing workflow node auto-retry when retry budget remains.
* Emit an observable event/log signal explaining the diff completion guard failure.
* Preserve existing behavior for review, planning, QA, documentation, bookkeeping, and honest already-implemented Engineer tasks where no code diff may be legitimate.
* Cover the behavior with focused backend tests.

## Acceptance Criteria (Evolving)

* [x] An Engineer workflow task with a framework note saying it claimed changed files but git diff was empty is converted to failed before node completion.
* [x] That failed completion triggers existing workflow node auto-retry when retry budget remains.
* [x] The retry task review comment includes the diff guard failure context so the next Engineer run knows why it is retrying.
* [x] An honest already-implemented Engineer task with `changed_files=[]` and no framework contradiction still completes normally.
* [x] A non-Engineer workflow task with similar text in its result is not blocked by this guard.
* [x] Tests cover fail, allow, non-Engineer allow, and retry integration cases.

## Definition of Done (Team Quality Bar)

* Tests added or updated for the backend scheduler/completion path.
* Lint, type-check, or equivalent compile checks run where available.
* Full relevant backend test subset passes.
* Specs updated if this introduces a new workflow contract.
* Rollout and rollback behavior considered.

## Out of Scope (Explicit)

* Replacing the existing Architect Review diff guard.
* Full semantic diff-vs-plan matching across all languages.
* UI controls for configuring the guard.
* New workflow node schema fields.
* SWE-bench evaluation harness changes.
* Changing GitHub PR merge behavior.

## Technical Notes

* Primary implementation target: `backend/app/application/workflow_scheduler.py`.
* Primary test target: `backend/tests/test_workflow_scheduler_auto_retry.py` or a sibling focused scheduler test.
* Existing source of truth for real diff: `backend/app/application/engineer_workflow.py::git_changed_files`.
* Existing persisted contradiction text comes from `EngineerWorkflow._apply_diff_cross_check()` as a `[framework]` QA note and then the rendered implementation markdown.
* Existing review guard remains valuable downstream; this task makes the scheduler fail earlier so retry happens before review/QA.
* Relevant specs: `.trellis/spec/vibe-kanban/backend/index.md`, `.trellis/spec/vibe-kanban/backend/quality-guidelines.md`, and shared code-reuse/cross-layer thinking guides.

## Proposed Design

### Recommended Approach: Scheduler-Level Completion Guard

When `WorkflowScheduler.on_task_completed()` sees a workflow-backed managed Engineer task that is otherwise terminal `done`, it should inspect the attached persisted Engineer document (`task._subagent_doc`) or the task result context for the framework diff contradiction generated by `EngineerWorkflow`. If present, it should mutate the completion to `failed`, set a concise framework failure result/review comment, emit a `workflow_node_diff_guard_failed` event, and then fall through to the existing failed-node retry path.

Why this is the best MVP: it reuses the already-tested Engineer diff cross-check, requires no schema migration, and composes directly with the newly merged auto-retry behavior.

### Alternatives Considered

1. Make `EngineerWorkflow.persist_result()` set `task.status = "failed"` directly.
   This is earlier, but it couples artifact persistence to task lifecycle state and may surprise callers that use `persist_result()` for backfill.

2. Recompute `git_changed_files()` inside the scheduler for every Engineer completion.
   This is deterministic, but it duplicates logic already applied in `EngineerWorkflow` and risks changing the legal empty-diff boundary.

3. Wait for Architect Review/QA guards.
   This already exists, but it delays self-healing and can advance workflow state farther than necessary.
