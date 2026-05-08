# Architecture To Development Breakdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a MetaGPT-aligned `architecture -> development` flow that creates split development tasks from architect output instead of jumping directly into a single engineer run.

**Architecture:** Keep the existing four issue phases (`requirements`, `architecture`, `development`, `testing`) unchanged. Implement a dedicated backend transition endpoint that consumes architect artifacts, especially `implementation_plan.json`, validates them, updates the issue to `development`, and creates one engineer task per implementation item. Do not add a new issue phase or auto-run any engineer task.

**Tech Stack:** FastAPI, Pydantic, SQLite store, React, TypeScript, node:test, pytest

---

## File Structure

### Backend

- Modify: `backend/app/interfaces/api.py`
  - Add `POST /api/codex/issues/{issue_id}/transition-to-development`
  - Add helpers to validate architect artifacts and parse `implementation_plan.json`
- Modify: `backend/app/application/issue_artifact_documents.py`
  - Add a shared helper for locating architect breakdown input if needed by tests and API
- Modify: `backend/app/domain/models.py`
  - Only if needed for any new response model fields; otherwise keep existing `CodexTask` shape
- Create: `backend/tests/test_issue_transition_to_development.py`
  - Lock the new transition behavior end to end

### Frontend

- Modify: `frontend/src/lib/api.ts`
  - Add `transitionIssueToDevelopment(issueId)`
- Modify: `frontend/src/lib/types.ts`
  - Reuse existing `IssuePhaseTransitionResult` if response shape matches; otherwise extend it
- Modify: `frontend/src/lib/i18n.ts`
  - Add copy for `流转到开发`
- Modify: `frontend/src/features/workbench/WorkbenchPage.tsx`
  - Compute `canTransitionToDevelopment`
  - Call the new transition endpoint
  - Merge multiple returned engineer tasks into local task state
- Modify: `frontend/src/features/tasks/TaskBoard.tsx`
  - Generalize the transition button/dialog to support `architecture -> development`
- Modify: `frontend/tests/workbenchActions.test.ts`
  - Lock the new frontend API call and returned multi-task payload

## Behavior Contract

- `architecture -> development` is allowed only when:
  - issue exists
  - issue `current_phase == "architecture"`
  - no task under the issue is `running` or `responding`
  - architect artifacts exist
  - `implementation_plan.json` contains at least one valid implementation item
- Architect artifacts required for transition:
  - `system_design.json`
  - `implementation_plan.json`
- `implementation_plan.json` is treated as the canonical split source.
- Each item in `implementation_plan.json` creates one `engineer` task with:
  - `phase = "development"`
  - `role = "engineer"`
  - `executor = "codex"` by default
  - `title = "开发 - {issue.title} - {item.title}"`
  - `prompt` built from the item title + description, with a short instruction to implement that slice using current issue artifacts
- The endpoint must be idempotent enough to avoid duplicate engineer tasks:
  - if an engineer task already exists for the same issue and same normalized item title, return the existing task instead of creating a second one
- The endpoint updates issue phase to `development` only after artifact validation and task derivation succeed.
- No engineer task is auto-run.

## Task 1: Lock Backend Transition Contract With Tests

**Files:**
- Create: `backend/tests/test_issue_transition_to_development.py`
- Reference: `backend/tests/test_issue_transition_to_architecture.py`

- [ ] **Step 1: Write the failing test for successful transition**

```python
def test_transition_to_development_updates_issue_and_creates_engineer_tasks(client, monkeypatch, tmp_path):
    session, issue, architect_task = build_architecture_issue_bundle(tmp_path)
    create_architecture_artifacts(
        tmp_path,
        issue.id,
        implementation_tasks=[
            {"title": "Build UI shell", "description": "Implement page layout", "priority": "P1"},
            {"title": "Wire API client", "description": "Connect fetch layer", "priority": "P1"},
        ],
    )
    store = TransitionStoreStub(issue=issue, session=session, tasks=[architect_task])
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-development")

    assert response.status_code == 200
    payload = response.json()
    assert payload["issue"]["current_phase"] == "development"
    assert payload["created"] is True
    assert len(payload["tasks"]) == 2
    assert payload["tasks"][0]["role"] == "engineer"
    assert payload["tasks"][0]["phase"] == "development"
```

- [ ] **Step 2: Write the failing validation tests**

```python
def test_transition_to_development_rejects_missing_architecture_artifacts(client, monkeypatch, tmp_path):
    session, issue, architect_task = build_architecture_issue_bundle(tmp_path)
    store = TransitionStoreStub(issue=issue, session=session, tasks=[architect_task])
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-development")

    assert response.status_code == 409
    assert "架构产物" in response.json()["detail"]


def test_transition_to_development_reuses_existing_engineer_tasks(client, monkeypatch, tmp_path):
    session, issue, architect_task = build_architecture_issue_bundle(tmp_path)
    create_architecture_artifacts(
        tmp_path,
        issue.id,
        implementation_tasks=[{"title": "Build UI shell", "description": "Implement page layout", "priority": "P1"}],
    )
    existing = architect_task.model_copy(
        update={
            "id": "task-eng-1",
            "phase": "development",
            "role": "engineer",
            "title": f"开发 - {issue.title} - Build UI shell",
            "prompt": "Implement Build UI shell",
            "status": "pending",
        }
    )
    store = TransitionStoreStub(issue=issue, session=session, tasks=[architect_task, existing])
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-development")

    assert response.status_code == 200
    payload = response.json()
    assert payload["created"] is False
    assert len(payload["tasks"]) == 1
    assert payload["tasks"][0]["id"] == "task-eng-1"
```

- [ ] **Step 3: Run the backend test file to verify RED**

Run:

```bash
cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/test_issue_transition_to_development.py -q
```

Expected: FAIL because `/transition-to-development` does not exist yet.

## Task 2: Implement Backend Transition And Task Derivation

**Files:**
- Modify: `backend/app/interfaces/api.py`
- Modify: `backend/app/application/issue_artifact_documents.py`
- Create or Modify: `backend/tests/test_issue_transition_to_development.py`

- [ ] **Step 1: Add helper to load and validate architect split input**

```python
def _load_implementation_tasks(workspace_path: str | None, issue_id: str) -> list[dict]:
    if not workspace_path:
        return []
    issue_root = Path(workspace_path) / "issues" / issue_id
    design_path = issue_root / "system_design.json"
    plan_path = issue_root / "implementation_plan.json"
    if not design_path.exists() or not plan_path.exists():
        return []
    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    normalized = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        description = str(item.get("description") or "").strip()
        priority = str(item.get("priority") or "P1").strip() or "P1"
        if not title:
            continue
        normalized.append({"title": title, "description": description, "priority": priority})
    return normalized
```

- [ ] **Step 2: Add the new transition endpoint**

```python
@router.post("/codex/issues/{issue_id}/transition-to-development")
async def transition_codex_issue_to_development(issue_id: str):
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.current_phase != "architecture":
        raise HTTPException(status_code=409, detail="只有架构阶段的 issue 才能流转到开发")

    session = await codex_store.load_codex_session(issue.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    tasks = await codex_store.list_codex_tasks(session_id=issue.session_id, issue_id=issue_id)
    if any(_is_task_running(task.get("status")) for task in tasks):
        raise HTTPException(status_code=409, detail="当前有任务仍在运行，请等待完成后再流转")

    workspace_path = next((task.get("workspace_path") for task in tasks if task.get("workspace_path")), None) or session.cwd
    implementation_tasks = _load_implementation_tasks(workspace_path, issue_id)
    if not implementation_tasks:
        raise HTTPException(status_code=409, detail="请先生成架构拆分产物后再流转到开发")
```

- [ ] **Step 3: Derive and persist engineer tasks**

```python
    existing_rows = [task for task in tasks if task.get("role") == "engineer" and task.get("issue_id") == issue_id]
    existing_by_title = {str(task.get("title") or "").strip().lower(): task for task in existing_rows}

    engineer_tasks = []
    created_any = False
    for item in implementation_tasks:
        task_title = f"开发 - {issue.title} - {item['title']}"
        task_prompt = f"请实现以下开发任务：{item['title']}\n\n任务描述：{item['description']}\n\n优先级：{item['priority']}"
        existing_row = existing_by_title.get(task_title.strip().lower())
        if existing_row is not None:
            engineer_task = await codex_store.load_codex_task(existing_row["id"])
        else:
            engineer_task = CodexTask(
                id=str(uuid4()),
                session_id=issue.session_id,
                issue_id=issue.id,
                phase="development",
                title=task_title,
                prompt=task_prompt,
                role="engineer",
                executor="codex",
                status="pending",
                result=None,
                parent_task_id=None,
                task_kind="normal",
                blocked_by_help_id=None,
                workspace_path=workspace_path,
                resume_session_id=None,
                resume_message_id=None,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            await codex_store.save_codex_task(engineer_task)
            created_any = True
        engineer_tasks.append(engineer_task)

    issue.current_phase = "development"
    issue.updated_at = datetime.now()
    await codex_store.save_codex_issue(issue)
    return {
        "issue": issue.model_dump(mode="json"),
        "tasks": [task.model_dump(mode="json") for task in engineer_tasks],
        "created": created_any,
    }
```

- [ ] **Step 4: Run backend tests to verify GREEN**

Run:

```bash
cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/test_issue_transition_to_development.py -q
```

Expected: PASS.

## Task 3: Add Frontend Architecture-To-Development Transition

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/i18n.ts`
- Modify: `frontend/src/features/workbench/WorkbenchPage.tsx`
- Modify: `frontend/src/features/tasks/TaskBoard.tsx`
- Modify: `frontend/tests/workbenchActions.test.ts`

- [ ] **Step 1: Write the failing frontend API test**

```typescript
test("transitionIssueToDevelopment posts to the development transition endpoint", async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];

  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        issue: {
          id: "issue-1",
          session_id: "ws-1",
          title: "Add dashboard",
          description: "Build dashboard",
          current_phase: "development",
          status: "open",
          created_at: null,
          updated_at: null,
        },
        tasks: [],
        created: true,
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    const result = await transitionIssueToDevelopment("issue-1");
    assert.equal(result.issue.current_phase, "development");
    assert.equal(String(calls[0].input), "/api/codex/issues/issue-1/transition-to-development");
    assert.equal(calls[0].init?.method, "POST");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
```

- [ ] **Step 2: Run frontend tests to verify RED**

Run:

```bash
cd frontend && npm test -- workbenchActions.test.ts
```

Expected: FAIL because `transitionIssueToDevelopment` does not exist yet.

- [ ] **Step 3: Add API/type/i18n support**

```typescript
export interface IssuePhaseMultiTaskTransitionResult {
  issue: CodexIssue;
  tasks: CodexTask[];
  created: boolean;
}

export async function transitionIssueToDevelopment(issueId: string): Promise<IssuePhaseMultiTaskTransitionResult> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/transition-to-development`, {
    method: "POST",
  });
  return handleResponse<IssuePhaseMultiTaskTransitionResult>(response);
}
```

- [ ] **Step 4: Wire the button into the workbench**

```tsx
const showTransitionToDevelopment = currentIssue?.current_phase === "architecture";
const canTransitionToDevelopment =
  currentIssue?.current_phase === "architecture" &&
  !hasActiveIssueTask &&
  hasArchitectureArtifacts &&
  !isTransitioningToDevelopment;

async function handleTransitionToDevelopment() {
  if (!currentIssue) return;
  setIsTransitioningToDevelopment(true);
  try {
    const result = await transitionIssueToDevelopment(currentIssue.id);
    setIssues((prev) => prev.map((issue) => (issue.id === result.issue.id ? result.issue : issue)));
    setTasks((prev) => {
      const byId = new Map(prev.map((task) => [task.id, task]));
      for (const task of result.tasks) byId.set(task.id, task);
      return Array.from(byId.values());
    });
    const freshArtifacts = await getCodexIssueArtifacts(currentIssue.id);
    setArtifacts(freshArtifacts);
  } finally {
    setIsTransitioningToDevelopment(false);
  }
}
```

- [ ] **Step 5: Generalize the transition button copy**

```tsx
showTransitionToArchitecture={currentIssue?.current_phase === "requirements"}
showTransitionToDevelopment={currentIssue?.current_phase === "architecture"}
transitionLabel={currentIssue?.current_phase === "architecture" ? t("issue.transition.toDevelopment") : t("issue.transition.toArchitecture")}
```

- [ ] **Step 6: Run frontend tests to verify GREEN**

Run:

```bash
cd frontend && npm test
```

Expected: PASS.

## Task 4: End-To-End Verification

**Files:**
- Verify existing backend/frontend changes only

- [ ] **Step 1: Run backend verification**

```bash
cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/test_issue_transition_to_development.py tests/test_issue_transition_to_architecture.py -q
```

Expected: PASS.

- [ ] **Step 2: Run frontend verification**

```bash
cd frontend && npm test
```

Expected: PASS.

- [ ] **Step 3: Manual workflow check**

1. Create or open an issue in `architecture`.
2. Confirm `system_design.json` and `implementation_plan.json` exist under `issues/<issue_id>/`.
3. Click `流转到开发`.
4. Verify issue phase becomes `development`.
5. Verify one engineer task is created per `implementation_plan.json` item.
6. Verify no engineer task auto-runs.
7. Retry the transition and verify no duplicate engineer tasks are created.

## Assumptions

- No new issue phase is added; `project_manager` is not introduced as a visible workflow stage in this iteration.
- The existing architect artifact `implementation_plan.json` is the authoritative split input for development task creation.
- Engineer task deduplication is title-based on normalized `开发 - {issue.title} - {item.title}`.
- The transition response for development returns `tasks: CodexTask[]`, not a single `task`.
