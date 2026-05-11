# Development → Testing Transition Implementation Plan

> **For agentic workers:** Implement this plan task-by-task with TDD. Each task follows RED → GREEN → COMMIT, and stops at a QA handoff point. After completing a task, append a status block to `COMMUNICATION.md` and wait for review before starting the next task.

**Goal:** Close the 4-phase pipeline (需求 → 架构 → 开发 → 测试) by adding a `development → testing` transition that derives a single aggregated QA task from completed engineer artifacts and surfaces the QA result on the frontend.

**Non-goals:**
- No new 5th phase. `VALID_ISSUE_PHASES` stays `{requirements, architecture, development, testing}`. QA result lives in `qa_report.json.status`.
- No per-engineer-task QA splitting (one issue → one QA task).
- No new role; reuse existing `QAWorkflow` (already produces `qa_plan.json` + `qa_report.md`).
- No re-running QA semantics beyond what `transition-to-development` already supports (idempotent re-trigger reuses existing role task).

**Architecture context:**
- `IssueArtifactDocuments.engineer_find_artifacts()` already returns `implementation*.md` files.
- `QAWorkflow.persist_result()` already writes `qa/qa_plan.json` and `qa/qa_report.md` and validates schema.
- `RoleWorkflowService` already dispatches `role="qa"`.
- Pattern to mirror: `transition-to-architecture` (single aggregated role task) + `transition-to-development` (multi-task with sequencing). The testing transition follows the **architecture pattern** (single task per issue).

**Tech Stack:** Python (FastAPI, pytest), TypeScript (Next.js, node:test).

---

## Execution Rule

Every task in this plan must stop at a QA handoff point before the next task begins.

- After completing a task, append a status block to `COMMUNICATION.md` listing modified files, test commands, test results, commit message, implementation notes, and blockers.
- After writing that update, stop and wait for Codex QA.
- Do not start the next task until reviewer explicitly approves the current one.
- If a task is partially complete or blocked, write that status into `COMMUNICATION.md` anyway.

---

## File Structure

### New / Modified backend files

- Modify: `backend/app/interfaces/api.py` — add `transition-to-testing` endpoint and helper(s)
- Modify: `backend/tests/test_issue_transition_to_testing.py` — new test file (create)

### New / Modified frontend files

- Modify: `frontend/src/lib/types.ts` — reuse `IssuePhaseTransitionResult` (single-task shape)
- Modify: `frontend/src/lib/api.ts` — add `transitionIssueToTesting()`
- ~~`frontend/src/lib/i18n.ts`~~ — i18n is **out of scope** for this plan; UI strings are hardcoded in zh-CN.
- Modify: `frontend/src/features/workbench/WorkbenchPage.tsx` — add `handleTransitionToTesting`
- Modify: `frontend/src/features/workbench/components/TaskBoard.tsx` — render "提交测试" button, gate on phase + tasks-done predicate
- Modify: `frontend/src/features/workbench/components/RunDetail.tsx` — render `qa_report` status badge when `role === "qa"` and task is done
- Modify: `frontend/src/__tests__/workbenchActions.test.ts` — add `transitionIssueToTesting` API test

### Responsibility boundaries

- `api.py`: state-machine guard, artifact pre-check, single QA task derivation, idempotent reuse.
- `QAWorkflow`: untouched in this plan (its `persist_result` already runs after task completion).
- Frontend `lib/`: pure API shape + i18n.
- Frontend `features/workbench/`: button visibility, dialog reuse, success handler.

---

## Task 1: Lock the transition contract with backend tests (RED)

**Files:**
- Create: `backend/tests/test_issue_transition_to_testing.py`

**Test list (all must initially fail with 404 or assertion mismatch):**

- `test_transition_to_testing_creates_qa_task_when_all_engineer_tasks_done`
  - Arrange: issue with `current_phase="development"`, 2 engineer tasks both `status="done"`, both with `implementation-<id>.md` written, no QA task yet.
  - Act: `POST /api/codex/issues/{id}/transition-to-testing`.
  - Assert: response is 200, `issue.current_phase == "testing"`, `task.role == "qa"`, `task.phase == "testing"`, `task.title.startswith("测试 - ")`, `created is True`, exactly one QA task exists in store for this issue.

- `test_transition_to_testing_rejects_wrong_phase`
  - Arrange: issue with `current_phase="requirements"` (and again with `"architecture"`).
  - Act + Assert: 409 with message about phase.

- `test_transition_to_testing_rejects_running_tasks`
  - Arrange: issue with `current_phase="development"`, all engineer tasks done, but one extra task with `status="running"`.
  - Act + Assert: 409 with running-task message.

- `test_transition_to_testing_rejects_unfinished_engineer_tasks`
  - Arrange: 2 engineer tasks, only one is `done`, other is `pending`. No artifact check should fire first.
  - Act + Assert: 409 with message identifying unfinished engineer task(s).

- `test_transition_to_testing_rejects_missing_implementation_artifacts`
  - Arrange: all engineer tasks `done` but no `implementation*.md` exists on disk.
  - Act + Assert: 409 with message about missing implementation artifacts.

- `test_transition_to_testing_reuses_existing_qa_task`
  - Arrange: a QA task with `role="qa"` already exists for this issue (from a prior trigger), all guards passing.
  - Act + Assert: 200, `created is False`, returned `task.id` matches the existing QA task, no second QA task created.

- `test_transition_to_testing_idempotent_when_already_testing`
  - Arrange: issue with `current_phase="testing"`, existing QA task.
  - Act + Assert: 200, `created is False`, `issue.current_phase == "testing"` unchanged.

- `test_transition_to_testing_returns_404_for_unknown_issue`
  - Arrange: no issue inserted.
  - Act + Assert: 404.

**Steps:**

- [ ] **Step 1: Write failing tests**

Use existing helpers from `tests/test_issue_transition_to_development.py` for fixture wiring (in-memory `codex_store`, workspace setup, engineer task factories). For the artifact-on-disk cases, write `implementation-<task-id>.md` under `<workspace>/issues/<issue_id>/engineer/` using `IssueArtifactDocuments`.

- [ ] **Step 2: Run tests to verify all fail**

```bash
cd backend && python3 -m pytest tests/test_issue_transition_to_testing.py -v
```

Expected: all new tests fail with 404 (endpoint not yet implemented) or 405. The pre-existing transition tests must continue to pass.

- [ ] **Step 3: Commit**

Commit message: `test: lock development→testing transition contract`

### Codex QA gate

- Confirm each guard (wrong phase, running tasks, unfinished engineer tasks, missing artifacts, reuse, idempotency, unknown issue) is independently locked by at least one dedicated test.
- Confirm tests use real `IssueArtifactDocuments` paths so the artifact pre-check is genuinely exercised, not bypassed via mocks.

---

## Task 2: Implement `transition-to-testing` endpoint (GREEN)

**Files:**
- Modify: `backend/app/interfaces/api.py`

**Steps:**

- [ ] **Step 1: Add helper `_has_engineer_artifacts(workspace_path, issue_id) -> tuple[bool, str]`**

Returns `(True, "")` if `IssueArtifactDocuments().engineer_find_artifacts(...)` is non-empty; otherwise `(False, "请先完成开发产物（implementation*.md）后再流转到测试")`.

- [ ] **Step 2: Add helper `_engineer_tasks_all_done(tasks, issue_id) -> tuple[bool, str]`**

Filter `tasks` to `role="engineer"` and `issue_id == issue_id`. Return `(False, message)` if list is empty (cannot QA without engineering work) or any element has `status != "done"`. Message should reference the offending task title to aid debugging.

- [ ] **Step 3: Add endpoint**

```python
@router.post("/codex/issues/{issue_id}/transition-to-testing")
async def transition_codex_issue_to_testing(issue_id: str):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")

    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
    if issue.current_phase not in ["development", "testing"]:
        raise HTTPException(status_code=409, detail="只有开发或测试阶段的 issue 才能流转到测试")

    session = await codex_store.load_codex_session(issue.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{issue.session_id}' not found")

    tasks = await codex_store.list_codex_tasks(session_id=issue.session_id, issue_id=issue_id)
    if any(_is_task_running(task.get("status")) for task in tasks):
        raise HTTPException(status_code=409, detail="当前有任务仍在运行，请等待完成后再流转")

    ok, error_msg = _engineer_tasks_all_done(tasks, issue_id)
    if not ok:
        raise HTTPException(status_code=409, detail=error_msg)

    workspace_path = next(
        (task.get("workspace_path") for task in tasks if task.get("workspace_path")),
        None,
    ) or session.cwd

    ok, error_msg = _has_engineer_artifacts(workspace_path, issue_id)
    if not ok:
        raise HTTPException(status_code=409, detail=error_msg)

    existing_qa_row = next(
        (task for task in tasks if task.get("role") == "qa" and task.get("issue_id") == issue_id),
        None,
    )

    issue.current_phase = "testing"
    issue.updated_at = datetime.now()
    await codex_store.save_codex_issue(issue)

    qa_task = None
    created = False
    if existing_qa_row is not None:
        qa_task = await codex_store.load_codex_task(existing_qa_row["id"])
    else:
        from app.domain.models import CodexTask
        now = datetime.now()
        resolved_executor, resolved_provider, resolved_model, _, _ = await _resolve_runtime_config()
        qa_task = CodexTask(
            id=str(uuid4()),
            session_id=issue.session_id,
            issue_id=issue.id,
            phase="testing",
            title=f"测试 - {issue.title}",
            prompt="请基于当前开发产物对该需求进行 QA 验收。",
            role="qa",
            executor=resolved_executor,
            provider=resolved_provider,
            model=resolved_model,
            status="pending",
            result=None,
            parent_task_id=None,
            task_kind="normal",
            blocked_by_help_id=None,
            workspace_path=workspace_path,
            resume_session_id=None,
            resume_message_id=None,
            created_at=now,
            updated_at=now,
        )
        await codex_store.save_codex_task(qa_task)
        created = True
        await event_bus.append({
            "type": "task_created",
            "task": qa_task.model_dump(mode="json"),
        })

    return {
        "issue": issue.model_dump(mode="json"),
        "task": qa_task.model_dump(mode="json") if qa_task is not None else None,
        "created": created,
    }
```

Order of guards is intentional and is locked by Task 1 tests:

1. issue exists
2. phase in `{development, testing}`
3. session exists
4. no running tasks
5. all engineer tasks done
6. engineer artifacts exist on disk

- [ ] **Step 4: Run tests to verify all pass**

```bash
cd backend && python3 -m pytest tests/test_issue_transition_to_testing.py tests/test_issue_transition_to_development.py tests/test_issue_transition_to_architecture.py -v
```

Expected: all pass, with no regression in the two existing transition test files.

- [ ] **Step 5: Commit**

Commit message: `feat: add development→testing transition with QA task derivation`

### Codex QA gate

- Confirm the guard order matches the test ordering (especially: unfinished engineer tasks should be reported **before** missing artifacts, since unfinished tasks are the more useful signal).
- Confirm `_resolve_runtime_config` is invoked (so QA task respects executor/provider/model defaults).
- Confirm `event_bus` `task_created` event fires so subscribers see the new QA task immediately.

---

## Task 3: Frontend API surface (RED for `transitionIssueToTesting`)

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/__tests__/workbenchActions.test.ts`

**i18n note:** out of scope — all UI copy is hardcoded zh-CN.

**Steps:**

- [ ] **Step 1: Add failing API test**

In `workbenchActions.test.ts`, add a test that mocks `fetch` and asserts `transitionIssueToTesting(issueId)` posts to `/api/codex/issues/${issueId}/transition-to-testing` and parses the response into `IssuePhaseTransitionResult` (the same shape used by `transitionIssueToArchitecture`).

- [ ] **Step 2: Add `transitionIssueToTesting` to `frontend/src/lib/api.ts`**

Mirror `transitionIssueToArchitecture` exactly — same return type `Promise<IssuePhaseTransitionResult>` because the testing transition returns a single task shape.

- [ ] **Step 3: Run tests to verify the new API test passes**

```bash
cd frontend && npm test
```

Expected: all existing tests pass + new `transitionIssueToTesting` test passes.

- [ ] **Step 4: Commit**

Commit message: `feat(frontend): add transitionIssueToTesting API helper`

### Codex QA gate

- Confirm the new API helper has its own dedicated test (not bundled into another test).

---

## Task 4: Frontend transition button + dialog reuse

**Files:**
- Modify: `frontend/src/features/workbench/WorkbenchPage.tsx`
- Modify: `frontend/src/features/workbench/components/TaskBoard.tsx`

**Steps:**

- [ ] **Step 1: In `WorkbenchPage.tsx`, add state + handler**

```tsx
const [isTransitioningToTesting, setIsTransitioningToTesting] = useState(false);

const handleTransitionToTesting = useCallback(async () => {
  if (!currentIssue) return;
  setIsTransitioningToTesting(true);
  try {
    const result = await transitionIssueToTesting(currentIssue.id);
    setIssues((prev) => prev.map((i) => (i.id === result.issue.id ? result.issue : i)));
    if (result.task) {
      setTasks((prev) => {
        const existing = prev.findIndex((t) => t.id === result.task!.id);
        if (existing === -1) return [...prev, result.task!];
        const next = [...prev];
        next[existing] = result.task!;
        return next;
      });
    }
    setTransitionDialogOpen(false);
    toast.success(t("issue.transition.success"));
  } catch (e) {
    toast.error(formatApiError(e));
  } finally {
    setIsTransitioningToTesting(false);
  }
}, [currentIssue, t]);
```

Reuse the existing `transitionDialogOpen` state and the shared transition dialog. The dialog must read its title/body from a `transitionDialogPhase` selector that supports three target phases (`architecture`, `development`, `testing`) — extend the existing logic, do not introduce a parallel dialog state. Reuse the same `closeDialog` exit path that `handleTransitionToDevelopment` uses (this was the source of a prior FAIL — keep dialog state unified).

- [ ] **Step 2: In `TaskBoard.tsx`, add a "提交测试" affordance**

Show button when:
- `currentIssue.current_phase === "development"`, AND
- there is at least one `role="engineer"` task for this issue, AND
- every `role="engineer"` task has `status === "done"`.

If `current_phase === "development"` but engineer tasks are not all done, render the button as **disabled** with hardcoded tooltip text `请先完成所有开发任务` so the user understands why.

Wire up via the new TaskBoard props `showTransitionToTesting`, `canTransitionToTesting`, `isTransitioningToTesting`, `onTransitionToTesting`. Do not duplicate prop wiring — follow the same prop fan-out used by `showTransitionToDevelopment`.

- [ ] **Step 3: Manual verification**

```bash
./dev-local.sh
```

Walk through: create issue → run requirements → transition to architecture → run architect → transition to development → run all engineer tasks → "提交测试" button enables → click → confirm dialog → QA task appears in TaskBoard.

- [ ] **Step 4: Run frontend build + tests**

```bash
cd frontend && npm test && npm run build && npm run lint
```

- [ ] **Step 5: Commit**

Commit message: `feat(frontend): add development→testing transition button and handler`

### Codex QA gate

- Confirm `transitionDialogOpen` is the single source of truth for the dialog (no parallel `transitionToTestingDialogOpen` state).
- Confirm the button is disabled (not hidden) when prerequisites are not yet met, so the user gets feedback.
- Confirm `setTasks` correctly reuses the QA task on idempotent retrigger (no duplicate row in the board).

---

## Task 5: Render QA report status in `RunDetail`

**Files:**
- Modify: `frontend/src/features/workbench/components/RunDetail.tsx`

**Steps:**

- [ ] **Step 1: Read qa_report.json artifact when task is QA + done**

When the selected task has `role === "qa"` and `status === "done"`, fetch the issue artifact `qa/qa_plan.json` (which is what `QAWorkflow.persist_result` writes — the variable name `qa_plan_path` is misleading; it actually stores the structured QA report).

If the file exists and parses, derive `status` from the parsed JSON (`passed` / `failed` / `blocked` / `needs_follow_up`).

- [ ] **Step 2: Render a status badge**

- `passed` → green badge with hardcoded label `测试通过`
- `failed` → red badge with hardcoded label `测试失败`
- `blocked` → orange badge with hardcoded label `测试阻塞`
- `needs_follow_up` → yellow badge with hardcoded label `需要跟进`

Add a `查看测试报告` link that opens the existing artifact viewer for `qa/qa_report.md`. Do not duplicate the artifact viewer — reuse what engineer/architect tasks already use.

- [ ] **Step 3: Manual verification**

End-to-end demo: with a real `codex` runtime, run the QA task and verify the badge + report link surface in `RunDetail`.

- [ ] **Step 4: Run frontend build**

```bash
cd frontend && npm run build && npm run lint
```

- [ ] **Step 5: Commit**

Commit message: `feat(frontend): surface QA report status in RunDetail`

### Codex QA gate

- Confirm the badge color mapping is locked, e.g. by snapshotting the conditional in code review.
- Confirm the artifact viewer link uses the existing fetch pattern (no new ad-hoc fetch).

---

## Task 6: End-to-end verification

**Files:** none new; this is a verification gate.

**Steps:**

- [ ] **Step 1: Run all backend tests**

```bash
cd backend && python3 -m pytest -v
```

Expected: all tests pass, including new `test_issue_transition_to_testing.py`.

- [ ] **Step 2: Run all frontend tests + build + lint**

```bash
cd frontend && npm test && npm run build && npm run lint
```

- [ ] **Step 3: Manual end-to-end**

```bash
./dev-local.sh
```

Use the UI to walk a single issue through all four phases: requirements → architecture → development → testing. Confirm:
- `/api/codex/issues/{id}/transition-to-testing` returns 200 with the expected payload.
- A new QA task appears in the TaskBoard after transition.
- After running the QA task, `qa/qa_report.md` and `qa/qa_plan.json` exist on disk.
- The QA status badge appears in RunDetail.
- Re-triggering the transition does **not** create a duplicate QA task.

- [ ] **Step 4: Commit any final adjustments**

Commit message: `chore: e2e verification for development→testing transition`

### Codex QA gate

- Final review: re-run all tests, then mark this entire plan as DONE in `COMMUNICATION.md`.

---

## Spec Coverage Review

| Spec point | Locked by |
| --- | --- |
| Issue must be in development or testing phase | `test_transition_to_testing_rejects_wrong_phase`, `test_transition_to_testing_idempotent_when_already_testing` |
| No tasks may be running | `test_transition_to_testing_rejects_running_tasks` |
| All engineer tasks must be done | `test_transition_to_testing_rejects_unfinished_engineer_tasks` |
| Implementation artifacts must exist on disk | `test_transition_to_testing_rejects_missing_implementation_artifacts` |
| One QA task per issue (deduped) | `test_transition_to_testing_reuses_existing_qa_task` |
| Successful transition path | `test_transition_to_testing_creates_qa_task_when_all_engineer_tasks_done` |
| Frontend API call shape | `transitionIssueToTesting` test in `workbenchActions.test.ts` |
| Phase stays at testing (no 5th phase) | enforced by `VALID_ISSUE_PHASES` unchanged + `qa_report.status` rendering in Task 5 |

## Placeholder Scan

No placeholders, dummy values, or TODOs are introduced by this plan. The QA prompt (`"请基于当前开发产物对该需求进行 QA 验收。"`) is a real instruction; the QA workflow already enriches the prompt with all upstream artifacts via `QAWorkflow.build_prompt`.

## Type Consistency Review

- Backend: `CodexTask` already supports `role="qa"` and `phase="testing"`; no schema migration needed.
- Frontend: response shape matches `IssuePhaseTransitionResult` (single-task, used by architecture transition).
- No new database columns. No migration script needed.
