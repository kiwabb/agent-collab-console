# Agent Help Child-Task Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add blocking `request_help` collaboration so a running Codex or Claude task can create an auto-run child task for the other executor, wait on it, and resume through a continuation execution.

**Architecture:** Keep the task/workspace-first product model. Persist help requests in SQLite, route all status changes through a dedicated backend help orchestrator, and resume parent tasks through a reusable task-runner service rather than process-level suspension. Runtime readers stay responsible for parsing executor events, but they hand normalized help intent to the orchestrator instead of mutating parent/child relationships directly.

**Tech Stack:** FastAPI, Pydantic, SQLite, Python 3.14, React, Vite, pytest

---

## File Structure

### Backend Domain And Persistence

- Modify: `backend/app/domain/models.py`
  Add `HelpRequest` plus minimal `CodexTask` fields for `task_kind` and `blocked_by_help_id`.
- Modify: `backend/app/adapters/sqlite_store.py`
  Add `help_requests` table and CRUD/list/update helpers for help orchestration.
- Modify: `backend/tests/test_models.py`
  Lock model defaults and serialization for help request/task-link fields.
- Modify: `backend/tests/test_codex_tasks.py`
  Lock API-visible task/help behavior.

### Backend Runtime And Orchestration

- Create: `backend/app/application/codex_task_runner.py`
  Shared backend entrypoint for starting a task execution or continuation execution without duplicating logic in `api.py`.
- Create: `backend/app/application/help_orchestrator.py`
  Own validation, child-task creation, parent blocking, child completion reconciliation, continuation payload creation, and parent resume.
- Create: `backend/app/application/help_event_parser.py`
  Normalize runtime-emitted `request_help` tool events from Codex and Claude into one backend contract.
- Modify: `backend/app/application/process_runtime_common.py`
  Detect Claude `request_help` tool events and hand them to the orchestrator.
- Modify: `backend/app/application/codex_app_server_runtime.py`
  Detect Codex `request_help` tool events and hand them to the orchestrator.
- Modify: `backend/app/bootstrap.py`
  Wire the task runner and help orchestrator as shared services.
- Modify: `backend/tests/test_codex_process_manager.py`
  Lock runtime parsing/dispatch for `request_help`.
- Create: `backend/tests/test_help_orchestrator.py`
  Lock parent/child orchestration, completion, failure, and restart-safe state transitions.

### Backend API

- Modify: `backend/app/interfaces/api.py`
  Expose help-request read APIs, move run logic to the task runner, and add orchestration hooks needed for child-task completion and parent resume.
- Modify: `backend/tests/test_codex_api.py`
  Lock help-request endpoints and execution-process interactions.
- Modify: `backend/tests/test_task_message_api.py`
  Lock continuation execution and message/history behavior after a help resume.

### Frontend

- Modify: `frontend/src/api.js`
  Fetch task-linked help requests.
- Modify: `frontend/src/components/CodexTaskList.jsx`
  Show `Waiting for Help`, child-task linkage, and help timeline entries.
- Modify: `frontend/src/utils/codexLogNormalizer.js`
  Normalize `help_requested`, `help_child_started`, `help_completed`, `help_failed`, and `task_resumed`.
- Modify: `frontend/src/styles.css`
  Style blocked state, help child indicators, and help timeline entries.

## Task 1: Lock Help Persistence And API Shape With Red Tests

**Files:**
- Modify: `backend/tests/test_models.py`
- Modify: `backend/tests/test_codex_tasks.py`
- Modify: `backend/tests/test_codex_api.py`

- [ ] **Step 1: Add a failing model test for `HelpRequest` defaults**

```python
from datetime import datetime

from app.domain.models import HelpRequest


def test_help_request_defaults():
    help_request = HelpRequest(
        id="hr-1",
        workspace_id="sess-1",
        parent_task_id="task-parent",
        child_task_id="task-child",
        source_executor="codex",
        target_executor="claude",
        title="Review plan",
        prompt="Inspect the migration plan",
        status="pending",
        created_at=datetime.now(),
    )

    assert help_request.context_summary is None
    assert help_request.error_message is None
    assert help_request.continuation_payload is None
    assert help_request.consumed_at is None
```

- [ ] **Step 2: Add a failing task API test for help-request listing**

```python
def test_get_task_help_requests_returns_parent_linked_requests(client):
    session = client.post("/api/codex/sessions", json={"title": "Help Session", "cwd": "/tmp"}).json()
    parent = client.post(
        "/api/codex/tasks",
        json={"session_id": session["id"], "title": "Parent", "prompt": "Need help", "executor": "codex"},
    ).json()

    store = __import__("app.bootstrap", fromlist=["codex_store"]).codex_store
    from app.domain.models import HelpRequest
    from datetime import datetime

    store.save_help_request(HelpRequest(
        id="hr-1",
        workspace_id=session["id"],
        parent_task_id=parent["id"],
        child_task_id="task-child",
        source_executor="codex",
        target_executor="claude",
        title="Review",
        prompt="Inspect",
        status="running",
        created_at=datetime.now(),
    ))

    response = client.get(f"/api/codex/tasks/{parent['id']}/help-requests")

    assert response.status_code == 200
    assert response.json()[0]["id"] == "hr-1"
    assert response.json()[0]["parent_task_id"] == parent["id"]
```

- [ ] **Step 3: Add a failing task test for new child-task fields**

```python
def test_create_help_child_task_persists_task_kind_and_block_link(client):
    session = client.post("/api/codex/sessions", json={"title": "Child Session", "cwd": "/tmp"}).json()

    response = client.post(
        "/api/codex/tasks",
        json={
            "session_id": session["id"],
            "title": "Claude child",
            "prompt": "Inspect the risk",
            "parent_task_id": "task-parent",
            "executor": "claude",
            "task_kind": "help_child",
            "blocked_by_help_id": "hr-1",
        },
    )

    assert response.status_code == 201
    assert response.json()["task_kind"] == "help_child"
    assert response.json()["blocked_by_help_id"] == "hr-1"
```

- [ ] **Step 4: Run the targeted red tests**

Run: `cd backend && PYTHONPATH=. python3 -m pytest tests/test_models.py tests/test_codex_tasks.py tests/test_codex_api.py -k "help_request or help_requests or task_kind" -v`
Expected: FAIL with missing `HelpRequest`, missing store helpers, and missing `/help-requests` endpoint.

- [ ] **Step 5: Commit the red tests**

```bash
git add backend/tests/test_models.py backend/tests/test_codex_tasks.py backend/tests/test_codex_api.py
git commit -m "test: lock help request persistence and api shape"
```

## Task 2: Add HelpRequest Persistence And Task Link Fields

**Files:**
- Modify: `backend/app/domain/models.py`
- Modify: `backend/app/adapters/sqlite_store.py`
- Modify: `backend/tests/test_models.py`
- Modify: `backend/tests/test_codex_tasks.py`

- [ ] **Step 1: Add the new domain model and task fields**

```python
class HelpRequest(BaseModel):
    id: str
    workspace_id: str
    parent_task_id: str
    child_task_id: str
    source_executor: str
    target_executor: str
    title: str
    prompt: str
    context_summary: str | None = None
    status: str = "pending"
    error_message: str | None = None
    continuation_payload: dict | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    timeout_at: datetime | None = None
    consumed_at: datetime | None = None


class CodexTask(BaseModel):
    ...
    task_kind: str = "normal"
    blocked_by_help_id: str | None = None
```

- [ ] **Step 2: Add SQLite schema and CRUD helpers**

```python
CREATE TABLE IF NOT EXISTS help_requests (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    parent_task_id TEXT NOT NULL,
    child_task_id TEXT NOT NULL,
    source_executor TEXT NOT NULL,
    target_executor TEXT NOT NULL,
    title TEXT NOT NULL,
    prompt TEXT NOT NULL,
    context_summary TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    continuation_payload TEXT,
    created_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    timeout_at TEXT,
    consumed_at TEXT
);
```

```python
def save_help_request(self, help_request: HelpRequest):
    conn.execute(
        """INSERT OR REPLACE INTO help_requests (
            id, workspace_id, parent_task_id, child_task_id, source_executor, target_executor,
            title, prompt, context_summary, status, error_message, continuation_payload,
            created_at, started_at, completed_at, timeout_at, consumed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (...),
    )

def list_help_requests(self, *, parent_task_id: str | None = None, child_task_id: str | None = None):
    ...

def load_help_request(self, help_request_id: str) -> HelpRequest | None:
    ...
```

- [ ] **Step 3: Extend existing task persistence queries**

```python
INSERT OR REPLACE INTO codex_tasks (
    id, session_id, title, prompt, executor, status, result, parent_task_id,
    workspace_path, resume_session_id, resume_message_id, last_execution_process_id,
    task_kind, blocked_by_help_id, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
```

```python
task = CodexTask(
    ...
    task_kind=row["task_kind"] or "normal",
    blocked_by_help_id=row["blocked_by_help_id"],
)
```

- [ ] **Step 4: Run the targeted green tests**

Run: `cd backend && PYTHONPATH=. python3 -m pytest tests/test_models.py tests/test_codex_tasks.py tests/test_codex_api.py -k "help_request or help_requests or task_kind" -v`
Expected: PASS.

- [ ] **Step 5: Commit the persistence layer**

```bash
git add backend/app/domain/models.py backend/app/adapters/sqlite_store.py backend/tests/test_models.py backend/tests/test_codex_tasks.py backend/tests/test_codex_api.py
git commit -m "feat: persist help requests and task link fields"
```

## Task 3: Extract A Reusable Codex Task Runner

**Files:**
- Create: `backend/app/application/codex_task_runner.py`
- Modify: `backend/app/bootstrap.py`
- Modify: `backend/app/interfaces/api.py`
- Modify: `backend/tests/test_codex_api.py`
- Modify: `backend/tests/test_task_message_api.py`

- [ ] **Step 1: Add a failing API test that exercises a shared runner path**

```python
def test_help_resume_uses_same_execution_runner_as_task_run(client, monkeypatch):
    import app.interfaces.api as api_module

    called = {}

    class StubRunner:
        def start_task_run(self, task, *, prompt_override=None, resume_session_id=None, resume_message_id=None):
            called["task_id"] = task.id
            called["prompt_override"] = prompt_override
            called["resume_session_id"] = resume_session_id
            return {"id": "proc-1", "task_id": task.id, "status": "Running"}

    monkeypatch.setattr(api_module, "task_runner", StubRunner())

    session = client.post("/api/codex/sessions", json={"title": "Runner", "cwd": "/tmp"}).json()
    task = client.post("/api/codex/tasks", json={"session_id": session["id"], "title": "Task", "prompt": "hello"}).json()

    response = client.post(f"/api/codex/tasks/{task['id']}/run")

    assert response.status_code == 200
    assert called["task_id"] == task["id"]
    assert called["prompt_override"] is None
```

- [ ] **Step 2: Create the task runner service**

```python
class CodexTaskRunner:
    def __init__(self, codex_store, event_bus, process_manager_factory):
        self.codex_store = codex_store
        self.event_bus = event_bus
        self._process_manager_factory = process_manager_factory

    def start_task_run(self, task, *, prompt_override=None, resume_session_id=None, resume_message_id=None):
        prompt_text = prompt_override or task.prompt
        ...
        return exec_process
```

- [ ] **Step 3: Move duplicated run logic out of `api.py`**

```python
task_runner = CodexTaskRunner(
    codex_store=codex_store,
    event_bus=event_bus,
    process_manager_factory=get_codex_process_manager,
)
```

```python
@router.post("/codex/tasks/{task_id}/run")
def run_codex_task(task_id: str):
    task = codex_store.load_codex_task(task_id)
    ...
    return task_runner.start_task_run(task)
```

- [ ] **Step 4: Run the runner-focused tests**

Run: `cd backend && PYTHONPATH=. python3 -m pytest tests/test_codex_api.py tests/test_task_message_api.py -k "runner or execution_process" -v`
Expected: PASS.

- [ ] **Step 5: Commit the runner extraction**

```bash
git add backend/app/application/codex_task_runner.py backend/app/bootstrap.py backend/app/interfaces/api.py backend/tests/test_codex_api.py backend/tests/test_task_message_api.py
git commit -m "refactor: extract reusable codex task runner"
```

## Task 4: Add Help Orchestrator And Continuation Resume

**Files:**
- Create: `backend/app/application/help_orchestrator.py`
- Modify: `backend/app/bootstrap.py`
- Modify: `backend/app/interfaces/api.py`
- Create: `backend/tests/test_help_orchestrator.py`
- Modify: `backend/tests/test_codex_api.py`

- [ ] **Step 1: Add a failing orchestrator test for parent block + child auto-run**

```python
from datetime import datetime

from app.domain.models import CodexTask


def test_request_help_creates_child_task_and_blocks_parent(store, tmp_path):
    from app.application.help_orchestrator import HelpOrchestrator

    started = {}

    class StubRunner:
        def start_task_run(self, task, **kwargs):
            started["task_id"] = task.id
            return {"id": "proc-child-1", "task_id": task.id, "status": "Running"}

    parent = CodexTask(
        id="task-parent",
        session_id="sess-1",
        title="Parent",
        prompt="Need help",
        executor="codex",
        status="running",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    store.save_codex_task(parent)

    orchestrator = HelpOrchestrator(codex_store=store, event_bus=[], task_runner=StubRunner())
    help_request = orchestrator.request_help(
        parent_task_id="task-parent",
        target_executor="claude",
        title="Review plan",
        prompt="Inspect the plan",
        context_summary="Focus on resume semantics",
    )

    updated_parent = store.load_codex_task("task-parent")
    child = store.load_codex_task(help_request.child_task_id)

    assert updated_parent.status == "waiting_for_help"
    assert updated_parent.blocked_by_help_id == help_request.id
    assert child.task_kind == "help_child"
    assert child.parent_task_id == "task-parent"
    assert started["task_id"] == child.id
```

- [ ] **Step 2: Implement the orchestrator core**

```python
class HelpOrchestrator:
    def __init__(self, codex_store, event_bus, task_runner):
        self.codex_store = codex_store
        self.event_bus = event_bus
        self.task_runner = task_runner

    def request_help(self, *, parent_task_id, target_executor, title, prompt, context_summary=None):
        parent = self._load_running_parent(parent_task_id)
        child = self._create_child_task(parent, target_executor, title, prompt)
        help_request = self._create_help_request(parent, child, target_executor, prompt, context_summary, title)
        self._mark_parent_waiting(parent, help_request.id)
        self._emit_parent_event("help_requested", parent, help_request, child)
        self.task_runner.start_task_run(child)
        self._emit_parent_event("help_child_started", parent, help_request, child)
        return help_request
```

- [ ] **Step 3: Add completion and failure reconciliation**

```python
def complete_help_request(self, help_request_id: str, *, child_status: str, child_result: str | None):
    help_request = self.codex_store.load_help_request(help_request_id)
    parent = self.codex_store.load_codex_task(help_request.parent_task_id)
    payload = self._build_continuation_payload(help_request, child_status, child_result)
    help_request.status = "completed" if child_status == "done" else "failed"
    help_request.continuation_payload = payload
    self.codex_store.save_help_request(help_request)
    parent.status = "ready_to_resume"
    self.codex_store.save_codex_task(parent)
    self.task_runner.start_task_run(parent, prompt_override=self._build_continuation_prompt(payload))
```

- [ ] **Step 4: Add and run orchestrator tests**

Run: `cd backend && PYTHONPATH=. python3 -m pytest tests/test_help_orchestrator.py tests/test_codex_api.py -k "request_help or waiting_for_help or ready_to_resume" -v`
Expected: PASS.

- [ ] **Step 5: Commit the orchestrator**

```bash
git add backend/app/application/help_orchestrator.py backend/app/bootstrap.py backend/app/interfaces/api.py backend/tests/test_help_orchestrator.py backend/tests/test_codex_api.py
git commit -m "feat: add help orchestrator and continuation resume"
```

## Task 5: Detect Runtime `request_help` Events And Bridge Them Into The Orchestrator

**Files:**
- Create: `backend/app/application/help_event_parser.py`
- Modify: `backend/app/application/process_runtime_common.py`
- Modify: `backend/app/application/codex_app_server_runtime.py`
- Modify: `backend/app/bootstrap.py`
- Modify: `backend/tests/test_codex_process_manager.py`

- [ ] **Step 1: Add a failing Claude runtime parser test**

```python
def test_claude_reader_dispatches_request_help_to_orchestrator(store, tmp_path):
    from app.application.codex_process_manager import CodexProcessManager
    from app.application.process_runtime_common import ProcessEntry

    mgr = CodexProcessManager(codex_store=store, log_store=store, data_dir=str(tmp_path))
    calls = []

    class StubHelpOrchestrator:
        def request_help_from_runtime(self, **kwargs):
            calls.append(kwargs)

    mgr._claude_runtime.help_orchestrator = StubHelpOrchestrator()
    entry = ProcessEntry(proc=None, output_thread=None, alive=True, session_id="sess-1", executor="claude", cwd=str(tmp_path), resume_session_id=None)

    mgr._claude_runtime._capture_on_reader(
        "sess-1",
        '{"type":"tool_use","tool_name":"request_help","input":{"target":"codex","title":"Review","prompt":"Inspect","blocking":true}}',
        entry,
        "task-1",
    )

    assert calls[0]["task_id"] == "task-1"
    assert calls[0]["target_executor"] == "codex"
```

- [ ] **Step 2: Create the normalized event parser**

```python
def parse_help_request_event(payload: dict, *, executor: str) -> dict | None:
    tool_name = payload.get("tool_name") or payload.get("tool")
    if tool_name != "request_help":
        return None
    tool_input = payload.get("input") or payload.get("payload") or {}
    if tool_input.get("blocking") is not True:
        return None
    return {
        "target_executor": tool_input["target"],
        "title": tool_input["title"],
        "prompt": tool_input["prompt"],
        "context_summary": tool_input.get("context_summary"),
        "source_executor": executor,
    }
```

- [ ] **Step 3: Dispatch parsed events from both runtimes**

```python
help_event = parse_help_request_event(parsed, executor=entry.executor)
if help_event and task_id and self.help_orchestrator is not None:
    self.help_orchestrator.request_help_from_runtime(
        task_id=task_id,
        session_id=session_id,
        **help_event,
    )
    entry.alive = False
    return
```

```python
parsed_payload = {"tool": "request_help", "payload": params} if method in ("tool_call", "tool/call") else ...
help_event = parse_help_request_event(parsed_payload, executor="codex")
if help_event and task_id and self.help_orchestrator is not None:
    self.help_orchestrator.request_help_from_runtime(task_id=task_id, session_id=session_id, **help_event)
    return False
```

- [ ] **Step 4: Run the runtime bridge tests**

Run: `cd backend && PYTHONPATH=. python3 -m pytest tests/test_codex_process_manager.py -k "request_help" -v`
Expected: PASS.

- [ ] **Step 5: Commit the runtime bridge**

```bash
git add backend/app/application/help_event_parser.py backend/app/application/process_runtime_common.py backend/app/application/codex_app_server_runtime.py backend/app/bootstrap.py backend/tests/test_codex_process_manager.py
git commit -m "feat: bridge runtime request_help events to orchestrator"
```

## Task 6: Add Help APIs And Frontend Blocked-State UI

**Files:**
- Modify: `backend/app/interfaces/api.py`
- Modify: `frontend/src/api.js`
- Modify: `frontend/src/utils/codexLogNormalizer.js`
- Modify: `frontend/src/components/CodexTaskList.jsx`
- Modify: `frontend/src/styles.css`
- Modify: `backend/tests/test_codex_api.py`

- [ ] **Step 1: Add a failing frontend-oriented API test**

```python
def test_get_help_requests_returns_parent_and_child_metadata(client):
    session = client.post("/api/codex/sessions", json={"title": "UI Help", "cwd": "/tmp"}).json()
    parent = client.post("/api/codex/tasks", json={"session_id": session["id"], "title": "Parent", "prompt": "Need help"}).json()

    response = client.get(f"/api/codex/tasks/{parent['id']}/help-requests")

    assert response.status_code == 200
    assert isinstance(response.json(), list)
```

- [ ] **Step 2: Add backend read endpoints**

```python
@router.get("/codex/tasks/{task_id}/help-requests")
def get_task_help_requests(task_id: str):
    task = codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return codex_store.list_help_requests(parent_task_id=task_id)


@router.get("/codex/help-requests/{help_request_id}")
def get_help_request(help_request_id: str):
    help_request = codex_store.load_help_request(help_request_id)
    if help_request is None:
        raise HTTPException(status_code=404, detail="Help request not found")
    return help_request
```

- [ ] **Step 3: Add frontend fetch and rendering hooks**

```javascript
export async function getTaskHelpRequests(taskId) {
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}/help-requests`);
  if (!response.ok) return [];
  return response.json();
}
```

```javascript
if (task?.status === "waiting_for_help") {
  badges.push(<span key="waiting" className="codex-status-badge status-waiting">Waiting for Help</span>);
}

const helpChildren = allTasks.filter((candidate) => candidate.parent_task_id === task?.id && candidate.task_kind === "help_child");
```

```javascript
if (entry.type === "help") {
  return (
    <div key={entry.id} className={`codex-log-entry codex-log-help codex-log-help-${entry.variant}`}>
      <span className="codex-log-help-label">{entry.label}</span>
      <span>{entry.content}</span>
    </div>
  );
}
```

- [ ] **Step 4: Run backend and frontend verification**

Run: `cd backend && PYTHONPATH=. python3 -m pytest tests/test_codex_api.py tests/test_codex_tasks.py -k "help_requests or waiting_for_help" -v`
Expected: PASS.

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Commit the UI slice**

```bash
git add backend/app/interfaces/api.py frontend/src/api.js frontend/src/utils/codexLogNormalizer.js frontend/src/components/CodexTaskList.jsx frontend/src/styles.css backend/tests/test_codex_api.py
git commit -m "feat: show help child tasks and blocked state in ui"
```

## Task 7: Full Regression And Recovery Checks

**Files:**
- Modify: `backend/tests/test_help_orchestrator.py`
- Modify: `backend/tests/test_codex_process_manager.py`
- Modify: `backend/tests/test_codex_api.py`

- [ ] **Step 1: Add a restart-safety test for unconsumed help results**

```python
def test_completed_help_request_stays_ready_to_resume_until_consumed(store, tmp_path):
    from app.application.help_orchestrator import HelpOrchestrator
    ...
    assert store.load_help_request(help_request.id).status == "completed"
    assert store.load_help_request(help_request.id).consumed_at is None
    assert store.load_codex_task(parent.id).status == "ready_to_resume"
```

- [ ] **Step 2: Run the full backend suite for touched areas**

Run: `cd backend && PYTHONPATH=. python3 -m pytest tests/test_models.py tests/test_codex_api.py tests/test_codex_process_manager.py tests/test_codex_tasks.py tests/test_task_message_api.py tests/test_help_orchestrator.py -v`
Expected: PASS.

- [ ] **Step 3: Run frontend build one more time**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Update docs if implementation drifted from the spec**

```markdown
If any endpoint names, task states, or event names differ from the spec, update:
- docs/superpowers/specs/2026-04-19-agent-help-child-task-design.md
```

- [ ] **Step 5: Commit the regression pass**

```bash
git add backend/tests/test_help_orchestrator.py backend/tests/test_codex_process_manager.py backend/tests/test_codex_api.py docs/superpowers/specs/2026-04-19-agent-help-child-task-design.md
git commit -m "test: verify help child-task flow end to end"
```

## Self-Review

### Spec Coverage

- Explicit `request_help` primitive is covered by Task 5.
- `help_requests` persistence and parent/child task fields are covered by Task 2.
- Backend orchestrator ownership is covered by Task 4.
- Task-flow suspension and continuation resume are covered by Tasks 3 and 4.
- Read APIs and task-first UI presentation are covered by Task 6.
- Recovery and `consumed` semantics are covered by Task 7.

### Placeholder Scan

- No `TODO`, `TBD`, or deferred implementation placeholders remain.
- Each task includes concrete files, test commands, and commit commands.
- Code-changing steps define class/function names that are reused consistently in later tasks.

### Type Consistency

- `HelpRequest`, `task_kind`, and `blocked_by_help_id` are introduced in Task 2 and reused consistently afterward.
- `CodexTaskRunner.start_task_run(...)` is introduced in Task 3 and reused by the orchestrator in Task 4.
- `HelpOrchestrator.request_help_from_runtime(...)` and `complete_help_request(...)` are introduced before runtime integration and recovery tasks reference them.
