# MetaGPT Role Workflow Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the backend role workflow behave like a real MetaGPT-style role pipeline, where managed roles get role-specific prompts, artifact persistence happens on completion instead of on reads, and the tests prove the role contracts end to end.

**Architecture:** `RoleWorkflowService` should be the single source of truth for managed-role prompt construction and artifact persistence. `CodexTaskRunner` should ask that service for managed-role prompts and call it once when a managed task completes, while `GET /codex/issues/{issue_id}/artifacts` becomes a pure read path over already materialized files. This keeps runtime behavior deterministic and avoids hidden write side effects in the artifact endpoint.

**Tech Stack:** FastAPI, Pydantic, SQLite, Python 3.14, pytest

---

## File Structure

### Backend runtime and API

- Modify: `backend/app/application/codex_task_runner.py`
  - Route managed roles through `RoleWorkflowService` instead of special-casing only `product_manager`.
  - Persist managed-role artifacts once at task completion.
- Modify: `backend/app/application/role_workflow_service.py`
  - Keep prompt building and artifact persistence as the shared managed-role contract.
- Modify: `backend/app/interfaces/api.py`
  - Pass the shared `RoleWorkflowService` into the task runner.
  - Remove artifact materialization from the read-only `/artifacts` endpoint.
- Modify: `backend/app/bootstrap.py`
  - Create a module-level `RoleWorkflowService` instance and pass it into the bootstrapped task runner so runtime and API use the same contract.

### Backend tests

- Modify: `backend/tests/test_codex_task_runner.py`
  - Add a regression test that proves managed roles use the shared role workflow prompt path.
  - Add a regression test that proves managed-role artifact persistence runs on completion.
- Create: `backend/tests/test_task_runner_wiring.py`
  - Prove both runner construction sites pass the shared `RoleWorkflowService` into `CodexTaskRunner`.
- Create: `backend/tests/test_codex_issue_artifacts.py`
  - Lock the artifact endpoint as read-only and ensure it does not call persistence helpers.

## Task 1: Route All Managed Roles Through `RoleWorkflowService`

**Files:**
- Modify: `backend/app/application/codex_task_runner.py`
- Modify: `backend/app/interfaces/api.py`
- Modify: `backend/app/bootstrap.py`
- Modify: `backend/tests/test_codex_task_runner.py`

- [ ] **Step 1: Write the failing test**

```python
import json

from datetime import datetime

from app.domain.models import CodexSession, CodexTask


def test_codex_task_runner_uses_role_workflow_service_for_managed_roles(tmp_path):
    from app.application.codex_task_runner import CodexTaskRunner

    calls = []

    class FakeStore:
        def __init__(self):
            self.workspace = CodexSession(
                id="sess-1",
                title="Workspace",
                cwd=str(tmp_path),
                status="idle",
                created_at=datetime.now(),
                last_active_at=datetime.now(),
            )
            self.task = None
            self.process = None

        def save_execution_process(self, process):
            self.process = process

        def save_codex_task(self, task):
            self.task = task

        def load_codex_task(self, task_id):
            return self.task if self.task and self.task.id == task_id else None

        def load_codex_workspace(self, workspace_id):
            return self.workspace if self.workspace.id == workspace_id else None

        def update_execution_process_status(self, process_id, status, exit_code=None, completed_at=None):
            if self.process and self.process.id == process_id:
                self.process.status = status

    class FakeManager:
        def write_input(self, workspace_id, prompt_text, wait, task_id, executor, resume_session_id, resume_message_id, cwd):
            calls.append((executor, prompt_text))
            runner.codex_store.task.result = json.dumps(
                {
                    "language": "en",
                    "project_name": "Workspace",
                    "issue_id": "issue-1",
                    "issue_title": "Design system",
                    "architecture_summary": "API-first architecture",
                    "components": ["AuthService"],
                    "data_models": ["User"],
                    "interfaces": ["REST"],
                    "data_flow": "Client -> API -> DB",
                    "implementation_tasks": [{"title": "Build auth", "description": "Implement auth", "priority": "P1"}],
                    "risks": [],
                    "open_questions": [],
                },
                ensure_ascii=False,
            )
            return "done"

    class FakeRoleWorkflowService:
        def build_prompt(self, task, workspace_title=None):
            return f"[{task.role}] {workspace_title} {task.prompt}"

        def is_managed_role(self, role):
            return role in {"product_manager", "architect", "engineer", "qa"}

        def persist_result(self, task, workspace_title=None):
            calls.append(("persist", task.role))

    runner = CodexTaskRunner(
        codex_store=FakeStore(),
        event_bus=[],
        process_manager_factory=lambda: FakeManager(),
        mock_manager_cls=type("MockMgr", (), {}),
        refresh_task_result=lambda task: None,
        role_workflow_service=FakeRoleWorkflowService(),
    )

    task = CodexTask(
        id="task-1",
        session_id="sess-1",
        issue_id="issue-1",
        title="Design system",
        prompt="Build the workflow",
        role="architect",
        executor="codex",
        status="pending",
        workspace_path=str(tmp_path / "task-1"),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    runner.start_task_run(task)

    assert calls[0][0] == "codex"
    assert calls[0][1].startswith("[architect] Workspace")
    assert ("persist", "architect") in calls
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_codex_task_runner.py -k managed_roles -v`

Expected: FAIL because `CodexTaskRunner` still special-cases only the PM prompt path and does not call the injected shared role workflow service for all managed roles, so the architect test stays on the generic prompt path.

- [ ] **Step 3: Write the minimal implementation**

```python
from app.application.role_workflow_service import RoleWorkflowService


class CodexTaskRunner:
    def __init__(..., role_workflow_service=None):
        ...
        self._role_workflow_service = role_workflow_service or RoleWorkflowService()

    def _build_prompt_text(...):
        if prompt_override is None:
            workspace = self.codex_store.load_codex_workspace(task.session_id) if self.codex_store is not None else None
            workspace_title = workspace.title if workspace is not None else None
            managed_prompt = self._role_workflow_service.build_prompt(task, workspace_title=workspace_title)
            if managed_prompt is not None:
                return managed_prompt
        ...

    def start_task_run(...):
        ...
        self._refresh_task_result(task)
        self.codex_store.save_codex_task(task)
        if task.status == "done" and self._role_workflow_service.is_managed_role(task.role):
            workspace = self.codex_store.load_codex_workspace(task.session_id) if self.codex_store is not None else None
            workspace_title = workspace.title if workspace is not None else None
            self._role_workflow_service.persist_result(task, workspace_title=workspace_title)
```

```python
# backend/app/interfaces/api.py and backend/app/bootstrap.py
task_runner = CodexTaskRunner(
    codex_store=codex_store,
    event_bus=event_bus,
    process_manager_factory=get_codex_process_manager,
    mock_manager_cls=MockCodexProcessManager,
    refresh_task_result=refresh_task_result,
    help_orchestrator_factory=None,
    role_workflow_service=role_workflow_service,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_codex_task_runner.py -k managed_roles -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/application/codex_task_runner.py backend/app/interfaces/api.py backend/app/bootstrap.py backend/tests/test_codex_task_runner.py
git commit -m "feat: route managed roles through shared workflow service"
```

## Task 2: Make Artifact Reads Pure and Keep Persistence on Completion

**Files:**
- Modify: `backend/app/interfaces/api.py`
- Modify: `backend/app/application/codex_task_runner.py`
- Modify: `backend/tests/test_codex_issue_artifacts.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime

from app.domain.models import CodexTask


def test_get_codex_issue_artifacts_does_not_persist_or_mutate_task(client, tmp_path):
    session = client.post("/api/codex/sessions", json={"title": "Artifacts", "cwd": "/tmp"}).json()
    issue = client.post(
        "/api/codex/issues",
        json={"session_id": session["id"], "title": "Login", "description": "Add login"},
    ).json()

    store = __import__("app.bootstrap", fromlist=["codex_store"]).codex_store
    workspace = tmp_path / "task-arch-1"
    issue_root = workspace / "issues" / issue["id"]
    issue_root.mkdir(parents=True)
    (issue_root / "system_design.json").write_text(
        '{"project_name":"Artifacts","issue_id":"issue-1","issue_title":"Design login","architecture_summary":"API-first architecture","components":["AuthService"],"data_models":["User"],"interfaces":["REST"],"data_flow":"Client -> API -> DB","implementation_tasks":[{"title":"Build auth","description":"Implement auth","priority":"P1"}],"risks":[],"open_questions":[]}',
        encoding="utf-8",
    )
    (issue_root / "system_design.md").write_text("# System Design\n", encoding="utf-8")
    task = CodexTask(
        id="task-arch-1",
        session_id=session["id"],
        issue_id=issue["id"],
        phase="architecture",
        title="Design login",
        prompt="Design the login flow",
        role="architect",
        executor="codex",
        status="done",
        result='{"language":"zh-CN","project_name":"Artifacts","issue_id":"issue-1","issue_title":"Design login","architecture_summary":"API","components":["Auth"],"data_models":["User"],"interfaces":["REST"],"data_flow":"Client -> API","implementation_tasks":[{"title":"Build auth","description":"Implement it","priority":"P1"}],"risks":[],"open_questions":[]}',
        workspace_path=str(workspace),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    store.save_codex_task(task)
    original_updated_at = task.updated_at

    response = client.get(f"/api/codex/issues/{issue['id']}/artifacts")

    assert response.status_code == 200
    assert store.load_codex_task(task.id).updated_at == original_updated_at
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_codex_issue_artifacts.py -v`

Expected: FAIL because the endpoint still calls `persist_result()` during the read path and can mutate task state while loading artifacts.

- [ ] **Step 3: Write the minimal implementation**

```python
# backend/app/interfaces/api.py
@router.get("/codex/issues/{issue_id}/artifacts")
def get_codex_issue_artifacts(issue_id: str):
    ...
    for task_payload in tasks:
        if task_payload.get("status") != "done":
            continue
        task = codex_store.load_codex_task(task_payload["id"])
        if task is None or not task.result:
            continue
        role = getattr(task, "role", None)
        if not role_workflow_service.is_managed_role(role):
            continue
        # Read-only endpoint: do not persist or rewrite artifacts here.
        # Return files already created by task completion.
```

```python
# backend/app/application/codex_task_runner.py
if task.status == "done" and self._role_workflow_service.is_managed_role(task.role):
    workspace = self.codex_store.load_codex_workspace(task.session_id) if self.codex_store is not None else None
    workspace_title = workspace.title if workspace is not None else None
    self._role_workflow_service.persist_result(task, workspace_title=workspace_title)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_codex_issue_artifacts.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/application/codex_task_runner.py backend/app/interfaces/api.py backend/tests/test_codex_issue_artifacts.py
git commit -m "feat: make issue artifacts endpoint read only"
```

## Task 3: Verify Runner Wiring Uses the Shared Service Everywhere

**Files:**
- Create: `backend/tests/test_task_runner_wiring.py`
- Modify: `backend/app/interfaces/api.py`
- Modify: `backend/app/bootstrap.py`

- [ ] **Step 1: Write the failing test**

```python
def test_api_runner_wiring_passes_shared_role_workflow_service(monkeypatch):
    import app.interfaces.api as api

    captured = {}

    class FakeRunner:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

    monkeypatch.setattr(api, "CodexTaskRunner", FakeRunner)
    api.task_runner = None

    api._get_task_runner()

    assert captured["kwargs"]["role_workflow_service"] is api.role_workflow_service


def test_bootstrap_runner_wiring_passes_shared_role_workflow_service(monkeypatch):
    import app.bootstrap as bootstrap

    captured = {}

    class FakeRunner:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

    monkeypatch.setattr(bootstrap, "CodexTaskRunner", FakeRunner)
    bootstrap.task_runner = None

    bootstrap.get_task_runner(refresh_task_result=lambda task: None)

    assert captured["kwargs"]["role_workflow_service"] is bootstrap.role_workflow_service
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_task_runner_wiring.py -v`

Expected: FAIL because neither runner construction site currently passes `role_workflow_service` into `CodexTaskRunner`.

- [ ] **Step 3: Write the minimal implementation**

```python
# backend/app/interfaces/api.py
task_runner = CodexTaskRunner(
    codex_store=codex_store,
    event_bus=event_bus,
    process_manager_factory=get_codex_process_manager,
    mock_manager_cls=MockCodexProcessManager,
    refresh_task_result=_refresh_task_result,
    help_orchestrator_factory=lambda: get_help_orchestrator(_refresh_task_result),
    role_workflow_service=role_workflow_service,
)
```

```python
# backend/app/bootstrap.py
from app.application.role_workflow_service import RoleWorkflowService

role_workflow_service = RoleWorkflowService()
task_runner = CodexTaskRunner(
    codex_store=codex_store,
    event_bus=event_bus,
    process_manager_factory=get_codex_process_manager,
    mock_manager_cls=MockCodexProcessManager,
    refresh_task_result=refresh_task_result,
    help_orchestrator_factory=None,
    role_workflow_service=role_workflow_service,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_task_runner_wiring.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/interfaces/api.py backend/app/bootstrap.py backend/tests/test_task_runner_wiring.py
git commit -m "test: verify shared role workflow service wiring"
```

## Self-Review Checklist

- The plan covers every part of the requested MetaGPT-style role alignment:
  - shared role prompt routing
  - artifact persistence timing
  - read-only artifact reads
  - coverage for all managed roles
- There are no placeholder steps such as `TODO`, `TBD`, or `write tests for above`.
- The file names are consistent across the tasks:
  - `CodexTaskRunner` is the runtime entry point.
  - `RoleWorkflowService` is the role contract boundary.
  - `GET /codex/issues/{issue_id}/artifacts` becomes read-only.
- The plan is scoped to one backend subsystem and does not pull in unrelated frontend work.
