# Requirements To Architecture Transition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a manual "流转到架构" workflow that moves an issue from requirements to architecture and creates one architect task without auto-running it.

**Architecture:** Add a dedicated backend transition endpoint that validates phase, running-task state, and requirements artifacts before updating the issue and creating or reusing an architect task. Extend the issue detail footer with a secondary button and confirmation dialog that calls the new endpoint and merges the updated issue/task state into the existing workbench stores.

**Tech Stack:** FastAPI, async SQLite store, React, TypeScript, existing issue/task APIs, Tailwind UI primitives

---

### Task 1: Add backend transition tests first

**Files:**
- Create: `backend/tests/test_issue_transition_to_architecture.py`
- Reference: `backend/app/interfaces/api.py`

- [ ] **Step 1: Write the failing backend tests**

```python
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.domain.models import CodexIssue, CodexSession, CodexTask
import app.interfaces.api as api_module
from app.main import app


class TransitionStoreStub:
    def __init__(self, *, issue, session, tasks, artifact_names):
        self.issue = issue
        self.session = session
        self.tasks = {task.id: task for task in tasks}
        self.saved_issue = None
        self.saved_task = None
        self.artifact_names = artifact_names

    async def load_codex_issue(self, issue_id: str):
        return self.issue if issue_id == self.issue.id else None

    async def load_codex_session(self, session_id: str):
        return self.session if session_id == self.session.id else None

    async def load_codex_workspace(self, session_id: str):
        return self.session if session_id == self.session.id else None

    async def save_codex_issue(self, issue):
        self.issue = issue
        self.saved_issue = issue

    async def list_codex_tasks(self, session_id: str | None = None, issue_id: str | None = None):
        result = []
        for task in self.tasks.values():
            if session_id is not None and task.session_id != session_id:
                continue
            if issue_id is not None and task.issue_id != issue_id:
                continue
            result.append({
                "id": task.id,
                "session_id": task.session_id,
                "issue_id": task.issue_id,
                "phase": task.phase,
                "title": task.title,
                "prompt": task.prompt,
                "role": task.role,
                "executor": task.executor,
                "status": task.status,
                "workspace_path": task.workspace_path,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            })
        return result

    async def save_codex_task(self, task):
        self.tasks[task.id] = task
        self.saved_task = task


@pytest.fixture
def client():
    return TestClient(app)


def build_issue_bundle():
    now = datetime.now()
    session = CodexSession(
        id="ws-1",
        title="Workspace",
        cwd="/tmp/ws-1",
        created_at=now,
        last_active_at=now,
    )
    issue = CodexIssue(
        id="issue-1",
        session_id=session.id,
        title="需求 - 购物车",
        current_phase="requirements",
        status="open",
        created_at=now,
        updated_at=now,
    )
    pm_task = CodexTask(
        id="task-pm-1",
        session_id=session.id,
        issue_id=issue.id,
        phase="requirements",
        title="需求 - 购物车",
        prompt="请整理需求",
        role="product_manager",
        executor="codex",
        status="done",
        workspace_path="/tmp/ws-1",
        created_at=now,
        updated_at=now,
    )
    return session, issue, pm_task


def test_transition_to_architecture_updates_issue_and_creates_task(client, monkeypatch):
    session, issue, pm_task = build_issue_bundle()
    store = TransitionStoreStub(
        issue=issue,
        session=session,
        tasks=[pm_task],
        artifact_names={"requirement.md", "prd.json", "prd.md"},
    )
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-architecture")

    assert response.status_code == 200
    payload = response.json()
    assert payload["created"] is True
    assert payload["issue"]["current_phase"] == "architecture"
    assert payload["task"]["role"] == "architect"
    assert payload["task"]["phase"] == "architecture"
    assert payload["task"]["title"] == f"架构 - {issue.title}"


def test_transition_to_architecture_returns_existing_architect_task(client, monkeypatch):
    session, issue, pm_task = build_issue_bundle()
    architect_task = CodexTask(
        id="task-arch-1",
        session_id=session.id,
        issue_id=issue.id,
        phase="architecture",
        title=f"架构 - {issue.title}",
        prompt="请基于当前需求产物进行架构设计。",
        role="architect",
        executor="codex",
        status="pending",
        workspace_path="/tmp/ws-1",
        created_at=pm_task.created_at,
        updated_at=pm_task.updated_at,
    )
    store = TransitionStoreStub(
        issue=issue,
        session=session,
        tasks=[pm_task, architect_task],
        artifact_names={"requirement.md"},
    )
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-architecture")

    assert response.status_code == 200
    payload = response.json()
    assert payload["created"] is False
    assert payload["task"]["id"] == architect_task.id


def test_transition_to_architecture_rejects_running_issue_task(client, monkeypatch):
    session, issue, pm_task = build_issue_bundle()
    running_task = pm_task.model_copy(update={"id": "task-live-1", "status": "running"})
    store = TransitionStoreStub(
        issue=issue,
        session=session,
        tasks=[pm_task, running_task],
        artifact_names={"requirement.md"},
    )
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-architecture")

    assert response.status_code == 409
    assert "运行" in response.json()["detail"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/test_issue_transition_to_architecture.py -q`
Expected: FAIL because the transition endpoint does not exist yet.

- [ ] **Step 3: Add one more failing test for missing requirements artifacts**

```python
def test_transition_to_architecture_rejects_missing_requirement_artifacts(client, monkeypatch):
    session, issue, pm_task = build_issue_bundle()
    store = TransitionStoreStub(
        issue=issue,
        session=session,
        tasks=[pm_task],
        artifact_names=set(),
    )
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-architecture")

    assert response.status_code == 409
    assert "需求产物" in response.json()["detail"]
```

- [ ] **Step 4: Re-run tests and confirm red**

Run: `cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/test_issue_transition_to_architecture.py -q`
Expected: FAIL with 404 or missing route assertions.

- [ ] **Step 5: Commit the failing tests**

```bash
git add backend/tests/test_issue_transition_to_architecture.py
git commit -m "test: cover requirements-to-architecture transition"
```

### Task 2: Implement the backend transition endpoint

**Files:**
- Modify: `backend/app/interfaces/api.py`
- Test: `backend/tests/test_issue_transition_to_architecture.py`

- [ ] **Step 1: Add helper functions for transition validation**

Insert helpers near the other issue/task helpers in `backend/app/interfaces/api.py`:

```python
def _has_requirements_artifacts(workspace_path: str | None, issue_id: str) -> bool:
    if not workspace_path:
        return False
    issue_root = Path(workspace_path) / "issues" / issue_id
    if not issue_root.exists() or not issue_root.is_dir():
        return False
    names = {"requirement.md", "prd.json", "prd.md"}
    return any((issue_root / name).exists() for name in names)


def _is_task_running(status: str | None) -> bool:
    return str(status or "").lower() in {"running", "responding"}
```

- [ ] **Step 2: Add the transition endpoint**

Add this route in `backend/app/interfaces/api.py` near the other issue endpoints:

```python
@router.post("/codex/issues/{issue_id}/transition-to-architecture")
async def transition_codex_issue_to_architecture(issue_id: str):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")

    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.current_phase != "requirements":
        raise HTTPException(status_code=409, detail="只有需求阶段的 issue 才能流转到架构")

    session = await codex_store.load_codex_session(issue.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    tasks = await codex_store.list_codex_tasks(session_id=issue.session_id, issue_id=issue_id)
    if any(_is_task_running(task.get("status")) for task in tasks):
        raise HTTPException(status_code=409, detail="当前有任务仍在运行，请等待完成后再流转")

    workspace_path = None
    for task_row in tasks:
        candidate = task_row.get("workspace_path")
        if candidate:
            workspace_path = candidate
            break
    workspace_path = workspace_path or session.cwd

    if not _has_requirements_artifacts(workspace_path, issue_id):
        raise HTTPException(status_code=409, detail="请先生成需求产物后再流转到架构")

    existing_architect_row = next(
        (
            task for task in tasks
            if task.get("role") == "architect" and task.get("issue_id") == issue_id
        ),
        None,
    )

    issue.current_phase = "architecture"
    issue.updated_at = datetime.now()
    await codex_store.save_codex_issue(issue)

    architect_task = None
    created = False
    if existing_architect_row is not None:
        architect_task = await codex_store.load_codex_task(existing_architect_row["id"])
    else:
        architect_task = CodexTask(
            id=str(uuid4()),
            session_id=issue.session_id,
            issue_id=issue.id,
            phase="architecture",
            title=f"架构 - {issue.title}",
            prompt="请基于当前需求产物进行架构设计。",
            role="architect",
            executor="codex",
            status="pending",
            result=None,
            parent_task_id=None,
            task_kind="normal",
            blocked_by_help_id=None,
            workspace_path=session.cwd or workspace_path,
            resume_session_id=None,
            resume_message_id=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        await codex_store.save_codex_task(architect_task)
        created = True

    return {
        "issue": issue.model_dump(mode="json"),
        "task": architect_task.model_dump(mode="json") if architect_task else None,
        "created": created,
    }
```

- [ ] **Step 3: Emit the same event types the frontend already understands**

Extend the endpoint to publish issue and task events:

```python
    await event_bus.append({
        "type": "issue_updated",
        "issue": issue.model_dump(mode="json"),
        "session_id": issue.session_id,
    })

    if created:
        await event_bus.append({
            "type": "task_created",
            "task": architect_task.model_dump(mode="json"),
        })
```

If `issue_updated` is not currently handled anywhere, keep the event anyway for consistency and rely on the direct API response for immediate UI state.

- [ ] **Step 4: Run backend tests and make them pass**

Run: `cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/test_issue_transition_to_architecture.py -q`
Expected: PASS

- [ ] **Step 5: Commit the backend endpoint**

```bash
git add backend/app/interfaces/api.py backend/tests/test_issue_transition_to_architecture.py
git commit -m "feat: add requirements-to-architecture transition endpoint"
```

### Task 3: Add frontend API coverage for the transition call

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/types.ts`
- Test: `frontend/tests/workbenchActions.test.ts`

- [ ] **Step 1: Add the transition response type**

In `frontend/src/lib/types.ts`, add:

```ts
export interface IssuePhaseTransitionResult {
  issue: CodexIssue;
  task: CodexTask | null;
  created: boolean;
}
```

- [ ] **Step 2: Add the API function**

In `frontend/src/lib/api.ts`, add:

```ts
export async function transitionIssueToArchitecture(issueId: string): Promise<IssuePhaseTransitionResult> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/transition-to-architecture`, {
    method: "POST",
  });
  return handleResponse<IssuePhaseTransitionResult>(response);
}
```

- [ ] **Step 3: Add a failing API behavior test**

Append a focused test in `frontend/tests/workbenchActions.test.ts`:

```ts
test("transitionIssueToArchitecture posts to the dedicated issue transition endpoint", async () => {
  let requestedUrl = "";
  let requestedMethod = "";

  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    requestedUrl = String(input);
    requestedMethod = init?.method || "GET";
    return new Response(JSON.stringify({
      issue: { id: "issue-1", session_id: "ws-1", title: "需求", description: null, current_phase: "architecture", status: "open", created_at: null, updated_at: null },
      task: { id: "task-1", session_id: "ws-1", issue_id: "issue-1", phase: "architecture", title: "架构 - 需求", prompt: "请基于当前需求产物进行架构设计。", role: "architect", executor: "codex", status: "pending", result: null, parent_task_id: null, task_kind: "normal", blocked_by_help_id: null, resume_session_id: null, resume_message_id: null, workspace_path: "/tmp/ws-1", last_execution_process_id: null, created_at: null, updated_at: null },
      created: true,
    }), { status: 200 });
  }) as typeof fetch;

  await transitionIssueToArchitecture("issue-1");

  assert.equal(requestedMethod, "POST");
  assert.equal(requestedUrl.endsWith("/api/codex/issues/issue-1/transition-to-architecture"), true);
});
```

- [ ] **Step 4: Run frontend test and make it pass**

Run: `cd frontend && npm test -- workbenchActions.test.ts`
Expected: PASS

- [ ] **Step 5: Commit the frontend API support**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/types.ts frontend/tests/workbenchActions.test.ts
git commit -m "feat: add issue transition API client"
```

### Task 4: Add the issue detail transition UI and confirmation flow

**Files:**
- Modify: `frontend/src/features/issues/IssueDetailPanel.tsx`
- Modify: `frontend/src/features/workbench/WorkbenchPage.tsx`
- Modify: `frontend/src/lib/i18n.ts`
- Test: `frontend/tests/workbenchActions.test.ts`

- [ ] **Step 1: Extend the issue detail props**

Update `IssueDetailPanelProps` in `frontend/src/features/issues/IssueDetailPanel.tsx`:

```ts
interface IssueDetailPanelProps {
  issue: CodexIssue | null;
  tasks: CodexTask[];
  artifacts: Artifact[];
  isRunning: boolean;
  onRunPhaseRole: (phase: string, role: string) => void;
  onChangePhase: (phase: string) => void;
  onTransitionToArchitecture: () => void;
  isTransitioningToArchitecture: boolean;
}
```

- [ ] **Step 2: Compute visibility and enabled state in the panel**

Inside `IssueDetailPanel`, add:

```ts
  const requirementsArtifactNames = new Set(reqArtifacts.map((artifact) => artifact.name));
  const hasRequirementsArtifacts =
    requirementsArtifactNames.has("requirement.md") ||
    requirementsArtifactNames.has("prd.json") ||
    requirementsArtifactNames.has("prd.md");
  const showTransitionButton = phase === "requirements";
  const canTransitionToArchitecture = showTransitionButton && !isRunning && hasRequirementsArtifacts;
```

- [ ] **Step 3: Render the secondary button above the existing primary footer button**

Replace the footer action block with:

```tsx
      <div className="p-6 border-t border-border-subtle bg-surface/60 backdrop-blur-xl space-y-3">
        {showTransitionButton && (
          <button
            onClick={onTransitionToArchitecture}
            disabled={!canTransitionToArchitecture || isTransitioningToArchitecture}
            className={cn(
              "w-full flex items-center justify-center gap-3 px-6 py-3 text-[11px] font-bold uppercase tracking-[0.18em] rounded-xl border transition-all",
              canTransitionToArchitecture && !isTransitioningToArchitecture
                ? "bg-surface-raised text-foreground border-border-subtle hover:bg-surface-hover hover:border-border-strong"
                : "bg-surface-input text-text-muted border-border-subtle opacity-60 cursor-not-allowed"
            )}
            title={!hasRequirementsArtifacts ? t("issue.transition.requiresArtifacts") : undefined}
          >
            <span>
              {isTransitioningToArchitecture ? t("issue.transition.loading") : t("issue.transition.toArchitecture")}
            </span>
          </button>
        )}
        <button
          onClick={() => onRunPhaseRole(phase, config.role)}
          disabled={isRunning}
          className="w-full flex items-center justify-center gap-3 px-6 py-4 text-xs font-bold uppercase tracking-[0.2em] rounded-xl bg-brand text-background hover:bg-brand/90 disabled:opacity-50 transition-all shadow-lg shadow-brand/20 group relative overflow-hidden"
        >
          ...
        </button>
      </div>
```

- [ ] **Step 4: Add translation keys**

In `frontend/src/lib/i18n.ts`, add both Chinese and English keys:

```ts
"issue.transition.toArchitecture": "流转到架构",
"issue.transition.loading": "流转中",
"issue.transition.requiresArtifacts": "请先生成需求产物后再流转到架构",
"issue.transition.confirmTitle": "流转到架构阶段",
"issue.transition.confirmBody": "确认将该需求流转到架构阶段，并创建一条 Architect 任务？",
"issue.transition.confirmAction": "确认流转",
```

and:

```ts
"issue.transition.toArchitecture": "Transition To Architecture",
"issue.transition.loading": "Transitioning",
"issue.transition.requiresArtifacts": "Generate requirements artifacts before transitioning to architecture",
"issue.transition.confirmTitle": "Transition To Architecture",
"issue.transition.confirmBody": "Move this issue to the architecture phase and create one Architect task?",
"issue.transition.confirmAction": "Confirm Transition",
```

- [ ] **Step 5: Wire the action in the workbench page**

In `frontend/src/features/workbench/WorkbenchPage.tsx`:

```ts
  const [isTransitioningToArchitecture, setIsTransitioningToArchitecture] = useState(false);
  const [showTransitionConfirm, setShowTransitionConfirm] = useState(false);
```

Add the handler:

```ts
  async function handleTransitionToArchitecture() {
    if (!currentIssue) return;
    setIsTransitioningToArchitecture(true);
    try {
      const result = await transitionIssueToArchitecture(currentIssue.id);
      setIssues((prev) => prev.map((issue) => (issue.id === result.issue.id ? result.issue : issue)));
      if (result.task) {
        setTasks((prev) => {
          const existing = prev.some((task) => task.id === result.task!.id);
          return existing ? prev.map((task) => (task.id === result.task!.id ? result.task! : task)) : [...prev, result.task!];
        });
      }
      const freshArtifacts = await getCodexIssueArtifacts(currentIssue.id);
      setArtifacts(freshArtifacts);
      setShowTransitionConfirm(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to transition issue to architecture");
    } finally {
      setIsTransitioningToArchitecture(false);
    }
  }
```

Pass props to `IssueDetailPanel`:

```tsx
onTransitionToArchitecture={() => setShowTransitionConfirm(true)}
isTransitioningToArchitecture={isTransitioningToArchitecture}
```

- [ ] **Step 6: Add a confirmation dialog in the workbench page**

Render a dialog near the existing dialogs:

```tsx
      <Dialog open={showTransitionConfirm} onOpenChange={setShowTransitionConfirm}>
        <DialogContent className="sm:max-w-md" showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>{t("issue.transition.confirmTitle")}</DialogTitle>
            <DialogDescription>{t("issue.transition.confirmBody")}</DialogDescription>
          </DialogHeader>
          <DialogFooter className="sm:justify-end">
            <Button type="button" variant="outline" onClick={() => setShowTransitionConfirm(false)} disabled={isTransitioningToArchitecture}>
              {t("issue.cancel")}
            </Button>
            <Button type="button" onClick={handleTransitionToArchitecture} disabled={isTransitioningToArchitecture}>
              {isTransitioningToArchitecture ? t("issue.transition.loading") : t("issue.transition.confirmAction")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
```

- [ ] **Step 7: Add a focused frontend behavior test**

Add to `frontend/tests/workbenchActions.test.ts`:

```ts
test("requirements issue shows the transition action and opens confirmation flow", async () => {
  const issue = {
    id: "issue-1",
    session_id: "ws-1",
    title: "需求",
    description: null,
    current_phase: "requirements",
    status: "open",
    created_at: null,
    updated_at: null,
  };

  assert.equal(issue.current_phase, "requirements");
  assert.equal(PHASE_CONFIG[issue.current_phase as keyof typeof PHASE_CONFIG].role, "product_manager");
});
```

This test is intentionally small if the current frontend test harness is limited. If the repo already supports component rendering tests, replace it with a real render test against `IssueDetailPanel`.

- [ ] **Step 8: Run frontend tests and verify green**

Run: `cd frontend && npm test -- workbenchActions.test.ts`
Expected: PASS

- [ ] **Step 9: Commit the transition UI**

```bash
git add frontend/src/features/issues/IssueDetailPanel.tsx frontend/src/features/workbench/WorkbenchPage.tsx frontend/src/lib/i18n.ts frontend/tests/workbenchActions.test.ts
git commit -m "feat: add transition-to-architecture issue action"
```

### Task 5: Verify end-to-end behavior and polish failure messaging

**Files:**
- Modify: `frontend/src/features/workbench/WorkbenchPage.tsx`
- Modify: `backend/app/interfaces/api.py`
- Test: `backend/tests/test_issue_transition_to_architecture.py`

- [ ] **Step 1: Improve backend error messages if tests show ambiguity**

Keep the messages explicit:

```python
raise HTTPException(status_code=409, detail="只有需求阶段的 issue 才能流转到架构")
raise HTTPException(status_code=409, detail="当前有任务仍在运行，请等待完成后再流转")
raise HTTPException(status_code=409, detail="请先生成需求产物后再流转到架构")
```

- [ ] **Step 2: Verify the issue detail page naturally switches to architecture mode**

Run the app and confirm:

```bash
cd frontend && npm run build
cd ../backend && PYTHONPATH=. ./.venv/bin/pytest tests/test_issue_transition_to_architecture.py tests/test_async_refresh_task_result.py tests/test_issue_artifact_backfill.py -q
```

Expected:

- frontend build succeeds
- backend tests all pass

- [ ] **Step 3: Smoke-test the real flow manually**

Manual checklist:

```text
1. Open a requirements-phase issue with requirement artifacts.
2. Confirm the "流转到架构" button is visible.
3. Click it and verify the confirmation dialog appears.
4. Confirm the action.
5. Verify the issue phase changes to architecture.
6. Verify one architect task appears and is pending.
7. Verify the primary footer button now matches the architecture stage.
8. Retry the transition and verify no duplicate architect task is created.
```

- [ ] **Step 4: Commit any final polish**

```bash
git add backend/app/interfaces/api.py frontend/src/features/workbench/WorkbenchPage.tsx
git commit -m "fix: polish architecture transition messaging"
```

## Spec Coverage Check

- Dedicated manual transition button: covered in Task 4
- Requirements-only visibility: covered in Task 4
- Confirmation dialog: covered in Task 4
- Backend dedicated endpoint: covered in Task 2
- Phase update to architecture: covered in Task 2
- Architect task creation without auto-run: covered in Task 2
- Duplicate architect task handling: covered in Tasks 1 and 2
- Requirements artifact gating: covered in Tasks 1, 2, and 4
- Running-task gating: covered in Tasks 1 and 2

## Placeholder Scan

No `TODO`, `TBD`, or deferred pseudo-steps remain. Commands, files, and target code blocks are all explicit. The only intentionally flexible point is whether the frontend test remains logic-level or becomes a render-level test depending on the repo’s current test harness; the plan explicitly says to prefer a render test if supported.

## Type Consistency Check

- backend endpoint path is consistently `POST /api/codex/issues/{issue_id}/transition-to-architecture`
- response type is consistently `{ issue, task, created }`
- created task consistently uses `role = "architect"` and `phase = "architecture"`
- frontend action name is consistently `transitionIssueToArchitecture`
