# Implementation Diff Completion Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fail and auto-retry workflow-backed Engineer nodes when the persisted Engineer report proves a claim-vs-real-diff contradiction.

**Architecture:** Add a scheduler-level completion guard in `WorkflowScheduler.on_task_completed()` before the task status is mapped onto the workflow node. Reuse the existing Engineer reconciliation signal instead of recomputing git diff or adding schema fields, then fall through to the existing failed-node auto-retry path.

**Tech Stack:** Python 3.13, asyncio, pytest, existing `WorkflowScheduler`, existing `EngineerWorkflow` framework notes.

---

### Task 1: Red Test For Auto-Retrying Diff-Guarded Engineer Completion

**Files:**
- Modify: `backend/tests/test_workflow_scheduler_auto_retry.py`
- Modify: `backend/app/application/workflow_scheduler.py`

- [ ] **Step 1: Write the failing test**

Add a test that builds a `done` Engineer task with `_subagent_doc.qa_notes` containing the existing Engineer framework note:

```python
class _EngineerDoc:
    qa_notes = [
        "[framework] Engineer claimed status=completed with changed_files=['app.py'] "
        "but git diff against the base branch shows no file changes. Downgraded to partial pending real implementation."
    ]
```

Call `WorkflowScheduler.on_task_completed(task)` with retry budget available and assert:

```python
assert len(dispatched) == 1
retry_task = dispatched[0]
assert retry_task.parent_task_id == "task-done"
assert "diff completion guard" in (retry_task.review_comment or "").lower()
assert store.update_workflow_node.await_args.kwargs["status"] == "running"
assert any(event.get("type") == "workflow_node_diff_guard_failed" for event in events)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest backend/tests/test_workflow_scheduler_auto_retry.py::test_done_engineer_with_diff_guard_failure_auto_retries_before_node_done -q
```

Expected: FAIL because the scheduler currently marks the node `done` and does not dispatch a retry.

- [ ] **Step 3: Implement minimal guard**

In `workflow_scheduler.py`, add:

```python
ENGINEER_ROLES = {"engineer", "engineer_frontend", "engineer_backend"}
```

Before mapping the terminal node update, detect `task.status == "done"` and role in `ENGINEER_ROLES`. If `_subagent_doc.qa_notes` contains both `Engineer claimed status=` and `git diff against the base branch shows no file changes`, set:

```python
task.status = "failed"
task.result = "<short framework failure>"
task.review_comment = "<short corrective retry context>"
terminal = "failed"
```

Emit `workflow_node_diff_guard_failed` best-effort, then allow existing `_maybe_auto_retry_failed_node()` to run.

- [ ] **Step 4: Run test to verify it passes**

Run the same targeted test. Expected: PASS.

### Task 2: Regression Tests For Legal Empty Diff And Non-Engineer Tasks

**Files:**
- Modify: `backend/tests/test_workflow_scheduler_auto_retry.py`

- [ ] **Step 1: Add legal-empty-diff test**

Add a `done` Engineer task whose `_subagent_doc.qa_notes` is empty and assert `store.update_workflow_node` receives `status="done"` and no retry task is dispatched.

- [ ] **Step 2: Add non-Engineer guard text test**

Add a `done` QA task with the same note text and assert the scheduler does not fail or retry it.

- [ ] **Step 3: Run focused scheduler tests**

Run:

```bash
python3 -m pytest backend/tests/test_workflow_scheduler_auto_retry.py -q
```

Expected: all tests pass.

### Task 3: Spec And Verification

**Files:**
- Modify: `.trellis/spec/vibe-kanban/backend/quality-guidelines.md`

- [ ] **Step 1: Update backend quality contract**

Add a short scenario documenting that scheduler-level Engineer diff completion guard turns deterministic claim-vs-real-diff contradictions into failed workflow node completions so existing auto-retry can self-heal.

- [ ] **Step 2: Run relevant regression suite**

Run:

```bash
python3 -m pytest backend/tests/test_workflow_scheduler_auto_retry.py backend/tests/test_engineer_workflow.py backend/tests/test_review_guard.py backend/tests/test_qa_workflow.py -q
python3 -m py_compile backend/app/application/workflow_scheduler.py
git diff --check
```

Expected: tests pass, compile passes, diff check clean.
