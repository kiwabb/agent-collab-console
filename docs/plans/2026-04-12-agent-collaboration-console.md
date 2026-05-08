# Agent Collaboration Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first collaboration console MVP where Codex acts as master planner/reviewer, Claude Code acts as worker implementer, and a human must approve before code submission.

**Architecture:** Create a new `agent-collab-console` app with a FastAPI backend, a React/Vite frontend, and an in-memory persistence layer first. The backend owns sessions, tasks, runs, artifacts, approvals, and state transitions; the frontend shows a control console for one running session; adapters are stubbed first and upgraded to controlled CLI execution after the orchestration flow is stable.

**Tech Stack:** Python, FastAPI, Pydantic, pytest, React, Vite, plain CSS, fetch/SSE

---

## Execution Rule

Every task in this plan must stop at a QA handoff point before the next task begins.

- After completing a task, Claude Code must update `agent-collab-console/COMMUNICATION.md`
- The update must include modified files, test commands, test results, commit message, implementation notes, and blockers
- After writing that update, Claude Code must stop and wait for Codex QA
- Claude Code must not start the next task until Codex explicitly approves the current one
- If a task is only partially complete or blocked, that status must still be written into `agent-collab-console/COMMUNICATION.md`

## File Structure

### New app root

- `agent-collab-console/backend/app/main.py`
- `agent-collab-console/backend/app/interfaces/api.py`
- `agent-collab-console/backend/app/interfaces/sse.py`
- `agent-collab-console/backend/app/domain/models.py`
- `agent-collab-console/backend/app/domain/states.py`
- `agent-collab-console/backend/app/application/session_service.py`
- `agent-collab-console/backend/app/application/orchestration_service.py`
- `agent-collab-console/backend/app/application/approval_service.py`
- `agent-collab-console/backend/app/application/event_bus.py`
- `agent-collab-console/backend/app/adapters/base.py`
- `agent-collab-console/backend/app/adapters/fake_codex_adapter.py`
- `agent-collab-console/backend/app/adapters/fake_claude_adapter.py`
- `agent-collab-console/backend/tests/test_models.py`
- `agent-collab-console/backend/tests/test_session_service.py`
- `agent-collab-console/backend/tests/test_orchestration_service.py`
- `agent-collab-console/backend/tests/test_api.py`
- `agent-collab-console/frontend/src/main.jsx`
- `agent-collab-console/frontend/src/App.jsx`
- `agent-collab-console/frontend/src/api.js`
- `agent-collab-console/frontend/src/styles.css`
- `agent-collab-console/frontend/src/components/SessionPanel.jsx`
- `agent-collab-console/frontend/src/components/TaskBoard.jsx`
- `agent-collab-console/frontend/src/components/RunTimeline.jsx`
- `agent-collab-console/frontend/src/components/ApprovalDrawer.jsx`

### Supporting files

- `agent-collab-console/backend/requirements.txt`
- `agent-collab-console/frontend/package.json`
- `agent-collab-console/README.md`

### Responsibility boundaries

- `domain/*`: pure types, enums, and state rules
- `application/*`: orchestration logic and approval rules
- `adapters/*`: tool-specific agent execution bridges
- `interfaces/*`: FastAPI routes and streaming
- `frontend/src/components/*`: focused UI panels, one responsibility per file

## Task 1: Scaffold the backend domain model

**Files:**
- Create: `agent-collab-console/backend/app/domain/models.py`
- Create: `agent-collab-console/backend/app/domain/states.py`
- Create: `agent-collab-console/backend/tests/test_models.py`
- Create: `agent-collab-console/backend/requirements.txt`

- [ ] **Step 1: Write the failing model tests**

```python
from app.domain.models import Session, Task, Approval, AgentRun
from app.domain.states import SessionState


def test_session_defaults_to_draft():
    session = Session(id="s1", title="Build login flow")
    assert session.state == SessionState.DRAFT
    assert session.tasks == []


def test_approval_defaults_to_pending():
    approval = Approval(id="a1", session_id="s1", task_id="t1", action="submit_code")
    assert approval.status == "pending"


def test_agent_run_tracks_role_and_status():
    run = AgentRun(id="r1", task_id="t1", agent_id="claude", role="worker")
    assert run.status == "running"
    assert run.role == "worker"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-collab-console/backend && pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Write minimal domain implementation**

```python
from enum import StrEnum


class SessionState(StrEnum):
    DRAFT = "draft"
    ANALYZING = "analyzing"
    PLANNED = "planned"
    IMPLEMENTING = "implementing"
    VERIFYING = "verifying"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
```

```python
from pydantic import BaseModel, Field

from app.domain.states import SessionState


class Task(BaseModel):
    id: str
    session_id: str
    title: str
    assignee: str | None = None
    status: str = "pending"


class AgentRun(BaseModel):
    id: str
    task_id: str
    agent_id: str
    role: str
    status: str = "running"


class Approval(BaseModel):
    id: str
    session_id: str
    task_id: str
    action: str
    status: str = "pending"


class Session(BaseModel):
    id: str
    title: str
    state: SessionState = SessionState.DRAFT
    tasks: list[Task] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent-collab-console/backend && pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-collab-console/backend
git commit -m "feat: scaffold collaboration domain models"
```

### Claude Code deliverable

- Domain models and passing backend model tests

### Codex QA

- Check enum names exactly match the spec states
- Check defaults match the intended master-worker workflow
- Reject if state names or approval defaults drift

## Task 2: Build session and task orchestration services

**Files:**
- Create: `agent-collab-console/backend/app/application/session_service.py`
- Create: `agent-collab-console/backend/app/application/orchestration_service.py`
- Create: `agent-collab-console/backend/app/application/event_bus.py`
- Create: `agent-collab-console/backend/tests/test_session_service.py`
- Create: `agent-collab-console/backend/tests/test_orchestration_service.py`

- [ ] **Step 1: Write the failing service tests**

```python
from app.application.session_service import SessionService
from app.application.orchestration_service import OrchestrationService


def test_create_session_returns_draft_session():
    service = SessionService()
    session = service.create_session("Implement audit log")
    assert session.title == "Implement audit log"
    assert session.state == "draft"


def test_master_plan_creates_worker_task():
    session_service = SessionService()
    event_bus = []
    orchestration = OrchestrationService(session_service, event_bus)
    session = session_service.create_session("Build audit log")
    task = orchestration.plan_task(session.id, "Design API", "claude")
    assert task.assignee == "claude"
    assert task.status == "pending"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-collab-console/backend && pytest tests/test_session_service.py tests/test_orchestration_service.py -v`
Expected: FAIL with missing service classes

- [ ] **Step 3: Write minimal services**

```python
from uuid import uuid4

from app.domain.models import Session


class SessionService:
    def __init__(self):
        self.sessions: dict[str, Session] = {}

    def create_session(self, title: str) -> Session:
        session = Session(id=str(uuid4()), title=title)
        self.sessions[session.id] = session
        return session

    def get_session(self, session_id: str) -> Session:
        return self.sessions[session_id]
```

```python
from uuid import uuid4

from app.domain.models import Task


class OrchestrationService:
    def __init__(self, session_service, event_bus):
        self.session_service = session_service
        self.event_bus = event_bus

    def plan_task(self, session_id: str, title: str, assignee: str) -> Task:
        session = self.session_service.get_session(session_id)
        task = Task(
            id=str(uuid4()),
            session_id=session_id,
            title=title,
            assignee=assignee,
        )
        session.tasks.append(task)
        self.event_bus.append({"type": "task.assigned", "task_id": task.id})
        return task
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent-collab-console/backend && pytest tests/test_session_service.py tests/test_orchestration_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-collab-console/backend
git commit -m "feat: add session and orchestration services"
```

### Claude Code deliverable

- In-memory session store, task planning flow, event emission

### Codex QA

- Check that orchestration creates task artifacts through one service boundary
- Check that `task.assigned` is emitted consistently
- Reject if services mix HTTP concerns into application logic

## Task 3: Add approval gate and state transitions

**Files:**
- Create: `agent-collab-console/backend/app/application/approval_service.py`
- Modify: `agent-collab-console/backend/app/application/orchestration_service.py`
- Create: `agent-collab-console/backend/tests/test_approval_service.py`

- [ ] **Step 1: Write the failing approval tests**

```python
from app.application.approval_service import ApprovalService
from app.application.session_service import SessionService


def test_request_submission_approval_moves_session_to_waiting():
    session_service = SessionService()
    session = session_service.create_session("Build dashboard")
    approval_service = ApprovalService(session_service)
    approval = approval_service.request_submission(session.id, "task-1")
    assert approval.status == "pending"
    assert session_service.get_session(session.id).state == "awaiting_approval"


def test_reject_submission_returns_to_implementing():
    session_service = SessionService()
    session = session_service.create_session("Build dashboard")
    approval_service = ApprovalService(session_service)
    approval = approval_service.request_submission(session.id, "task-1")
    approval_service.reject(approval.id)
    assert session_service.get_session(session.id).state == "implementing"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-collab-console/backend && pytest tests/test_approval_service.py -v`
Expected: FAIL with missing approval service

- [ ] **Step 3: Write minimal approval logic**

```python
from uuid import uuid4

from app.domain.models import Approval
from app.domain.states import SessionState


class ApprovalService:
    def __init__(self, session_service):
        self.session_service = session_service
        self.approvals: dict[str, Approval] = {}

    def request_submission(self, session_id: str, task_id: str) -> Approval:
        session = self.session_service.get_session(session_id)
        session.state = SessionState.AWAITING_APPROVAL
        approval = Approval(
            id=str(uuid4()),
            session_id=session_id,
            task_id=task_id,
            action="submit_code",
        )
        self.approvals[approval.id] = approval
        return approval

    def approve(self, approval_id: str) -> Approval:
        approval = self.approvals[approval_id]
        approval.status = "approved"
        self.session_service.get_session(approval.session_id).state = SessionState.APPROVED
        return approval

    def reject(self, approval_id: str) -> Approval:
        approval = self.approvals[approval_id]
        approval.status = "rejected"
        self.session_service.get_session(approval.session_id).state = SessionState.IMPLEMENTING
        return approval
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent-collab-console/backend && pytest tests/test_approval_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-collab-console/backend
git commit -m "feat: add approval gate for code submission"
```

### Claude Code deliverable

- Approval request and approve/reject flow wired to session state

### Codex QA

- Check the only guarded action in V1 is `submit_code`
- Check rejection returns to `implementing`, not `draft`
- Reject if final submission can happen without approval

## Task 4: Introduce fake adapters and end-to-end orchestration loop

**Files:**
- Create: `agent-collab-console/backend/app/adapters/base.py`
- Create: `agent-collab-console/backend/app/adapters/fake_codex_adapter.py`
- Create: `agent-collab-console/backend/app/adapters/fake_claude_adapter.py`
- Modify: `agent-collab-console/backend/app/application/orchestration_service.py`
- Modify: `agent-collab-console/backend/tests/test_orchestration_service.py`

- [ ] **Step 1: Write the failing adapter orchestration test**

```python
from app.adapters.fake_codex_adapter import FakeCodexAdapter
from app.adapters.fake_claude_adapter import FakeClaudeAdapter
from app.application.orchestration_service import OrchestrationService
from app.application.session_service import SessionService


def test_run_worker_task_collects_worker_output():
    session_service = SessionService()
    session = session_service.create_session("Build login")
    event_bus = []
    orchestration = OrchestrationService(
        session_service=session_service,
        event_bus=event_bus,
        master_adapter=FakeCodexAdapter(),
        worker_adapter=FakeClaudeAdapter(),
    )
    task = orchestration.plan_task(session.id, "Implement login API", "claude")
    result = orchestration.run_task(task.id)
    assert result["agent_id"] == "claude"
    assert result["status"] == "completed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-collab-console/backend && pytest tests/test_orchestration_service.py -v`
Expected: FAIL with missing adapters or `run_task`

- [ ] **Step 3: Write minimal adapter contract**

```python
from typing import Protocol


class AgentAdapter(Protocol):
    agent_id: str
    role: str

    def execute(self, task_title: str) -> dict: ...
```

```python
class FakeCodexAdapter:
    agent_id = "codex"
    role = "master"

    def execute(self, task_title: str) -> dict:
        return {"agent_id": self.agent_id, "role": self.role, "status": "completed", "summary": f"Planned: {task_title}"}
```

```python
class FakeClaudeAdapter:
    agent_id = "claude"
    role = "worker"

    def execute(self, task_title: str) -> dict:
        return {"agent_id": self.agent_id, "role": self.role, "status": "completed", "summary": f"Implemented: {task_title}"}
```

- [ ] **Step 4: Add orchestration run path**

```python
    def run_task(self, task_id: str) -> dict:
        for session in self.session_service.sessions.values():
            for task in session.tasks:
                if task.id == task_id:
                    result = self.worker_adapter.execute(task.title)
                    task.status = "completed"
                    self.event_bus.append({"type": "run.completed", "task_id": task.id, "agent_id": result["agent_id"]})
                    return result
        raise KeyError(task_id)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd agent-collab-console/backend && pytest tests/test_orchestration_service.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add agent-collab-console/backend
git commit -m "feat: add fake agent adapters for orchestration loop"
```

### Claude Code deliverable

- Fake adapters proving the master-worker orchestration path before real CLI bridging

### Codex QA

- Check adapter interface is small and replaceable
- Check worker execution is routed through adapter, not hardcoded in service
- Reject if fake adapters leak test-only logic into route handlers

## Task 5: Expose backend APIs and streaming updates

**Files:**
- Create: `agent-collab-console/backend/app/interfaces/api.py`
- Create: `agent-collab-console/backend/app/interfaces/sse.py`
- Create: `agent-collab-console/backend/app/main.py`
- Create: `agent-collab-console/backend/tests/test_api.py`

- [ ] **Step 1: Write the failing API test**

```python
from fastapi.testclient import TestClient

from app.main import app


def test_create_session_endpoint():
    client = TestClient(app)
    response = client.post("/api/sessions", json={"title": "Build approvals"})
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Build approvals"
    assert body["state"] == "draft"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-collab-console/backend && pytest tests/test_api.py -v`
Expected: FAIL with missing FastAPI app

- [ ] **Step 3: Write minimal API surface**

```python
from fastapi import APIRouter
from pydantic import BaseModel

from app.bootstrap import session_service


router = APIRouter(prefix="/api")


class CreateSessionRequest(BaseModel):
    title: str


@router.post("/sessions", status_code=201)
def create_session(request: CreateSessionRequest):
    return session_service.create_session(request.title)
```

```python
from fastapi import FastAPI

from app.interfaces.api import router as api_router


app = FastAPI(title="Agent Collaboration Console")
app.include_router(api_router)
```

- [ ] **Step 4: Add bootstrap container**

```python
from app.application.session_service import SessionService


session_service = SessionService()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd agent-collab-console/backend && pytest tests/test_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add agent-collab-console/backend
git commit -m "feat: expose collaboration session API"
```

### Claude Code deliverable

- Running backend with create-session API and bootstrap wiring

### Codex QA

- Check HTTP layer depends on services, not vice versa
- Check API returns spec-aligned state names
- Reject if SSE wiring blocks request thread or mixes transport with domain logic

## Task 6: Build the console frontend shell

**Files:**
- Create: `agent-collab-console/frontend/package.json`
- Create: `agent-collab-console/frontend/src/main.jsx`
- Create: `agent-collab-console/frontend/src/App.jsx`
- Create: `agent-collab-console/frontend/src/api.js`
- Create: `agent-collab-console/frontend/src/styles.css`
- Create: `agent-collab-console/frontend/src/components/SessionPanel.jsx`
- Create: `agent-collab-console/frontend/src/components/TaskBoard.jsx`
- Create: `agent-collab-console/frontend/src/components/RunTimeline.jsx`
- Create: `agent-collab-console/frontend/src/components/ApprovalDrawer.jsx`

- [ ] **Step 1: Write the failing UI smoke test or manual acceptance target**

Run: `cd agent-collab-console/frontend && npm run build`
Expected: FAIL because the frontend app does not exist yet

- [ ] **Step 2: Create the API helper**

```javascript
const API_BASE = "http://localhost:8000/api";

export async function createSession(title) {
  const response = await fetch(`${API_BASE}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  return response.json();
}
```

- [ ] **Step 3: Create the first App shell**

```javascript
import { useState } from "react";
import { createSession } from "./api";

export default function App() {
  const [title, setTitle] = useState("");
  const [session, setSession] = useState(null);

  async function handleCreateSession(event) {
    event.preventDefault();
    const nextSession = await createSession(title);
    setSession(nextSession);
  }

  return (
    <main className="page">
      <section className="hero">
        <h1>Agent Collaboration Console</h1>
        <form onSubmit={handleCreateSession}>
          <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Describe the software task" />
          <button type="submit">Create Session</button>
        </form>
      </section>
      {session ? <pre>{JSON.stringify(session, null, 2)}</pre> : null}
    </main>
  );
}
```

- [ ] **Step 4: Add the four focused panels**

```javascript
export function SessionPanel({ session }) {
  return <section><h2>Session</h2><p>{session.title}</p><p>{session.state}</p></section>;
}
```

```javascript
export function TaskBoard({ tasks }) {
  return <section><h2>Tasks</h2>{tasks.map((task) => <p key={task.id}>{task.title}</p>)}</section>;
}
```

```javascript
export function RunTimeline({ runs }) {
  return <section><h2>Runs</h2>{runs.map((run) => <p key={run.id}>{run.agent_id}:{run.status}</p>)}</section>;
}
```

```javascript
export function ApprovalDrawer({ approval }) {
  return <section><h2>Approval</h2><p>{approval ? approval.status : "No approval pending"}</p></section>;
}
```

- [ ] **Step 5: Run build to verify it passes**

Run: `cd agent-collab-console/frontend && npm install && npm run build`
Expected: PASS with Vite build output

- [ ] **Step 6: Commit**

```bash
git add agent-collab-console/frontend
git commit -m "feat: add collaboration console frontend shell"
```

### Claude Code deliverable

- Working frontend shell that can create a session and display console panels

### Codex QA

- Check the UI is a control console, not a generic chatbot
- Check component boundaries stay focused
- Reject if state management is spread across too many components too early

## Task 7: Replace fake worker path with controlled CLI adapter

**Files:**
- Modify: `agent-collab-console/backend/app/adapters/base.py`
- Create: `agent-collab-console/backend/app/adapters/claude_cli_adapter.py`
- Create: `agent-collab-console/backend/app/adapters/codex_cli_adapter.py`
- Modify: `agent-collab-console/backend/app/application/orchestration_service.py`
- Modify: `agent-collab-console/backend/tests/test_orchestration_service.py`

- [ ] **Step 1: Write the failing adapter test around subprocess execution**

```python
from app.adapters.claude_cli_adapter import ClaudeCliAdapter


def test_cli_adapter_parses_completed_run():
    adapter = ClaudeCliAdapter(command=["python3", "-c", "print('done')"])
    result = adapter.execute("Implement login")
    assert result["status"] == "completed"
    assert "done" in result["summary"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-collab-console/backend && pytest tests/test_orchestration_service.py -v`
Expected: FAIL with missing CLI adapter

- [ ] **Step 3: Implement a minimal subprocess-backed adapter**

```python
import subprocess


class ClaudeCliAdapter:
    agent_id = "claude"
    role = "worker"

    def __init__(self, command: list[str]):
        self.command = command

    def execute(self, task_title: str) -> dict:
        completed = subprocess.run(self.command, capture_output=True, text=True, check=True)
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "status": "completed",
            "summary": completed.stdout.strip() or task_title,
        }
```

- [ ] **Step 4: Run tests to verify the adapter passes**

Run: `cd agent-collab-console/backend && pytest tests/test_orchestration_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-collab-console/backend
git commit -m "feat: add subprocess-backed CLI adapters"
```

### Claude Code deliverable

- First real CLI bridge path behind the same adapter contract

### Codex QA

- Check real adapter stays behind the same interface as fake adapters
- Check command execution is isolated in adapter layer
- Reject if orchestration service starts building shell commands itself

## Task 8: Final integration, documentation, and operator walkthrough

**Files:**
- Create: `agent-collab-console/README.md`
- Modify: `agent-collab-console/backend/tests/test_api.py`
- Modify: `agent-collab-console/frontend/src/App.jsx`

- [ ] **Step 1: Write the failing end-to-end acceptance target**

Run: `cd agent-collab-console/backend && pytest tests/test_api.py -k approval -v`
Expected: FAIL because the create -> plan -> run -> approval flow is incomplete

- [ ] **Step 2: Add one end-to-end API test**

```python
def test_session_can_reach_awaiting_approval(client):
    session = client.post("/api/sessions", json={"title": "Build login"}).json()
    task = client.post(f"/api/sessions/{session['id']}/tasks", json={"title": "Implement login API"}).json()
    client.post(f"/api/tasks/{task['id']}/run")
    approval = client.post(f"/api/tasks/{task['id']}/approval").json()
    assert approval["status"] == "pending"
```

- [ ] **Step 3: Document local startup and demo flow**

```markdown
## Local Run

### Backend

```bash
cd agent-collab-console/backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd agent-collab-console/frontend
npm install
npm run dev
```

### Demo

1. Create a session
2. Add a task
3. Run the worker adapter
4. Request approval
5. Approve or reject from the console
```

- [ ] **Step 4: Run final checks**

Run: `cd agent-collab-console/backend && pytest -v`
Expected: PASS

Run: `cd agent-collab-console/frontend && npm run build`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-collab-console
git commit -m "feat: deliver agent collaboration console mvp"
```

### Claude Code deliverable

- Runnable MVP with README and one happy-path operator walkthrough

### Codex QA

- Check spec coverage against session, task, adapter, approval, and UI requirements
- Check the README demo matches actual available API and UI behavior
- Reject if the happy path is documented but not executable

## Spec Coverage Review

- Session management: covered by Tasks 1, 2, 5, and 8
- Master-worker orchestration: covered by Tasks 2, 4, and 7
- Approval gateway: covered by Task 3 and surfaced in Tasks 6 and 8
- Console UI: covered by Task 6
- Internal event model: covered by Task 2 and expanded as adapters mature
- Failure and recoverability baseline: partially covered by Tasks 3, 4, and 7; advanced retry UI can wait until after MVP

## Placeholder Scan

- No `TBD`, `TODO`, or deferred implementation markers remain in this plan
- Each task includes concrete files, commands, and minimal code targets

## Type Consistency Review

- Session state names use the spec-aligned values from Task 1 onward
- Approval action name remains `submit_code` throughout
- Master agent remains `codex`, worker agent remains `claude` throughout

## Task 9: Package the project for Docker deployment

**Files:**
- Create: `agent-collab-console/backend/Dockerfile`
- Create: `agent-collab-console/frontend/Dockerfile`
- Create: `agent-collab-console/docker-compose.yml`
- Modify: `agent-collab-console/README.md`
- Create: `agent-collab-console/.dockerignore`

- [ ] **Step 1: Write the failing deployment acceptance target**

Run: `cd agent-collab-console && docker compose config`
Expected: FAIL because Docker files do not exist yet

- [ ] **Step 2: Add backend Docker image**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend /app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Add frontend Docker image**

```dockerfile
FROM node:20-alpine AS build

WORKDIR /app
COPY frontend/package*.json /app/
RUN npm install
COPY frontend /app
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
```

- [ ] **Step 4: Add compose file and ignore rules**

```yaml
services:
  backend:
    build:
      context: .
      dockerfile: backend/Dockerfile
    ports:
      - "8000:8000"
    environment:
      REAL_CLI: "false"

  frontend:
    build:
      context: .
      dockerfile: frontend/Dockerfile
    ports:
      - "5173:80"
    depends_on:
      - backend
```

```gitignore
node_modules
dist
__pycache__
.pytest_cache
```

- [ ] **Step 5: Document Docker startup flow**

```markdown
## Docker Run

```bash
cd agent-collab-console
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend: http://localhost:8000
```

- [ ] **Step 6: Run deployment verification**

Run: `cd agent-collab-console && docker compose config`
Expected: PASS

Run: `cd agent-collab-console && docker compose build`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add agent-collab-console
git commit -m "feat: add docker deployment for collaboration console"
```

### Claude Code deliverable

- Backend and frontend can be built and started through Docker Compose

### Codex QA

- Check Docker paths are correct relative to project root
- Check frontend and backend ports match the README
- Reject if Docker Compose cannot build both services from a clean checkout

## Task 10: Add frontend task creation and action controls

**Files:**
- Modify: `agent-collab-console/frontend/src/App.jsx`
- Modify: `agent-collab-console/frontend/src/api.js`
- Modify: `agent-collab-console/frontend/src/components/TaskBoard.jsx`
- Modify: `agent-collab-console/frontend/src/components/ApprovalDrawer.jsx`
- Modify: `agent-collab-console/frontend/src/styles.css`

- [ ] **Step 1: Write the failing UX acceptance target**

Run: Start the app and create a session.
Expected: There is no way to create a task, run a task, or request approval from the UI yet.

- [ ] **Step 2: Add frontend API helpers**

```javascript
export async function createTask(sessionId, title, assignee = "claude") {
  const response = await fetch(`/api/sessions/${sessionId}/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, assignee }),
  });
  return response.json();
}

export async function runTask(taskId) {
  const response = await fetch(`/api/tasks/${taskId}/run`, { method: "POST" });
  return response.json();
}

export async function requestApproval(taskId) {
  const response = await fetch(`/api/tasks/${taskId}/approval`, { method: "POST" });
  return response.json();
}
```

- [ ] **Step 3: Add task creation UI and wire task actions**

```javascript
const [taskTitle, setTaskTitle] = useState("");

async function handleCreateTask(event) {
  event.preventDefault();
  const nextTask = await createTask(session.id, taskTitle);
  setTasks((current) => [...current, nextTask]);
  setTaskTitle("");
}
```

```javascript
async function handleRunTask(taskId) {
  const run = await runTask(taskId);
  setRuns((current) => [...current, { id: `${taskId}-run`, ...run }]);
  setTasks((current) =>
    current.map((task) => (task.id === taskId ? { ...task, status: "completed" } : task)),
  );
}
```

```javascript
async function handleRequestApproval(taskId) {
  const nextApproval = await requestApproval(taskId);
  setApproval(nextApproval);
  setSession((current) => ({ ...current, state: "awaiting_approval" }));
}
```

- [ ] **Step 4: Upgrade TaskBoard and ApprovalDrawer into interactive panels**

```javascript
export function TaskBoard({ tasks, onRunTask, onRequestApproval }) {
  return (
    <section>
      <h2>Tasks</h2>
      {tasks.map((task) => (
        <div key={task.id}>
          <p>{task.title}</p>
          <p>{task.status}</p>
          <button onClick={() => onRunTask(task.id)}>Run</button>
          <button onClick={() => onRequestApproval(task.id)}>Request Approval</button>
        </div>
      ))}
    </section>
  );
}
```

- [ ] **Step 5: Verify the manual happy path**

Run:
1. Create session
2. Create task
3. Run task
4. Request approval

Expected:
- Task appears in UI
- Run appears in UI
- Approval appears in UI
- Session state changes to `awaiting_approval`

- [ ] **Step 6: Run build verification**

Run: `cd agent-collab-console/frontend && npm run build`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add agent-collab-console/frontend
git commit -m "feat: add interactive task controls to frontend console"
```

### Claude Code deliverable

- A frontend that can create tasks, run tasks, and request approval without leaving the page

### Codex QA

- Check the UI now supports the real happy path instead of stopping at session creation
- Check task actions call real backend APIs
- Reject if action buttons only mutate local state without hitting the server

## Task 11: Add backend read APIs for session detail and workflow state

**Files:**
- Modify: `agent-collab-console/backend/app/interfaces/api.py`
- Modify: `agent-collab-console/backend/app/application/session_service.py`
- Modify: `agent-collab-console/backend/tests/test_api.py`

- [ ] **Step 1: Write the failing API read test**

```python
def test_get_session_returns_tasks_and_state():
    session = client.post("/api/sessions", json={"title": "Build login"}).json()
    client.post(f"/api/sessions/{session['id']}/tasks", json={"title": "Implement login API"})
    response = client.get(f"/api/sessions/{session['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == session["id"]
    assert len(body["tasks"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_api.py -v`
Expected: FAIL with missing GET endpoint

- [ ] **Step 3: Add session detail lookup**

```python
@router.get("/sessions/{session_id}")
def get_session(session_id: str):
    try:
        return session_service.get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-collab-console/backend
git commit -m "feat: add session detail API for frontend refresh"
```

### Claude Code deliverable

- A backend GET API that lets the frontend re-read session state after mutations

### Codex QA

- Check the read API reflects the same in-memory state mutated by create/run/approval actions
- Reject if frontend still has to guess task or approval state

## Task 12: Add approval decision endpoints and UI controls

**Files:**
- Modify: `agent-collab-console/backend/app/interfaces/api.py`
- Modify: `agent-collab-console/backend/tests/test_api.py`
- Modify: `agent-collab-console/frontend/src/api.js`
- Modify: `agent-collab-console/frontend/src/components/ApprovalDrawer.jsx`
- Modify: `agent-collab-console/frontend/src/App.jsx`

- [ ] **Step 1: Write the failing approval action test**

```python
def test_approval_can_be_approved():
    session = client.post("/api/sessions", json={"title": "Build login"}).json()
    task = client.post(f"/api/sessions/{session['id']}/tasks", json={"title": "Implement login API"}).json()
    approval = client.post(f"/api/tasks/{task['id']}/approval").json()
    response = client.post(f"/api/approvals/{approval['id']}/approve")
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_api.py -v`
Expected: FAIL with missing approval decision endpoint

- [ ] **Step 3: Add backend approval decision routes**

```python
@router.post("/approvals/{approval_id}/approve")
def approve(approval_id: str):
    return approval_service.approve(approval_id)


@router.post("/approvals/{approval_id}/reject")
def reject(approval_id: str):
    return approval_service.reject(approval_id)
```

- [ ] **Step 4: Add frontend approve/reject actions**

```javascript
export async function approve(approvalId) {
  const response = await fetch(`/api/approvals/${approvalId}/approve`, { method: "POST" });
  return response.json();
}

export async function reject(approvalId) {
  const response = await fetch(`/api/approvals/${approvalId}/reject`, { method: "POST" });
  return response.json();
}
```

- [ ] **Step 5: Wire ApprovalDrawer buttons**

```javascript
export function ApprovalDrawer({ approval, onApprove, onReject }) {
  if (!approval) {
    return <section><h2>Approval</h2><p>No approval pending</p></section>;
  }

  return (
    <section>
      <h2>Approval</h2>
      <p>{approval.status}</p>
      <button onClick={() => onApprove(approval.id)}>Approve</button>
      <button onClick={() => onReject(approval.id)}>Reject</button>
    </section>
  );
}
```

- [ ] **Step 6: Verify the approval state flow manually**

Expected:
- Clicking `Approve` updates approval status to `approved`
- Clicking `Reject` updates approval status to `rejected`
- Session state changes accordingly

- [ ] **Step 7: Run verification**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_api.py -v`
Expected: PASS

Run: `cd agent-collab-console/frontend && npm run build`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add agent-collab-console/backend agent-collab-console/frontend
git commit -m "feat: add approval decision flow to console"
```

### Claude Code deliverable

- An approval UI that can approve or reject a pending code submission request

### Codex QA

- Check approval buttons call backend APIs rather than mutating local state only
- Check session state follows approval outcome
- Reject if reject flow does not return to `implementing`

## Task 13: Replace SSE placeholder with minimal live event stream

**Files:**
- Modify: `agent-collab-console/backend/app/interfaces/sse.py`
- Modify: `agent-collab-console/backend/app/application/event_bus.py`
- Modify: `agent-collab-console/frontend/src/App.jsx`
- Modify: `agent-collab-console/frontend/src/api.js`

- [ ] **Step 1: Write the failing live-update acceptance target**

Run the app in two browser tabs.
Expected: State changes in one tab do not appear in the other because `/api/events` is still a placeholder.

- [ ] **Step 2: Add an in-memory event feed**

```python
class EventBus:
    def __init__(self):
        self.events: list[dict[str, Any]] = []

    def append(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def list_events(self) -> list[dict[str, Any]]:
        return self.events
```

- [ ] **Step 3: Turn `/api/events` into a simple SSE endpoint**

```python
from fastapi.responses import StreamingResponse


@router.get("/events")
def events():
    async def event_stream():
        for event in event_bus.list_events():
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

- [ ] **Step 4: Add frontend event subscription**

```javascript
useEffect(() => {
  const source = new EventSource("/api/events");
  source.onmessage = () => {
    if (session) {
      loadSession(session.id);
    }
  };
  return () => source.close();
}, [session]);
```

- [ ] **Step 5: Verify live refresh**

Expected:
- Session/task/approval changes refresh without page reload

- [ ] **Step 6: Run verification**

Run: `cd agent-collab-console/frontend && npm run build`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add agent-collab-console/backend agent-collab-console/frontend
git commit -m "feat: add minimal live event stream for console updates"
```

### Claude Code deliverable

- A minimal SSE-backed refresh loop so the console updates after actions

### Codex QA

- Check `/api/events` is no longer a pure placeholder
- Check frontend subscriptions are cleaned up on unmount
- Reject if the stream exists but no real state refresh happens

## Task 14: Add artifact and message timeline domain support

**Files:**
- Modify: `agent-collab-console/backend/app/domain/models.py`
- Modify: `agent-collab-console/backend/app/application/orchestration_service.py`
- Modify: `agent-collab-console/backend/app/interfaces/api.py`
- Modify: `agent-collab-console/backend/tests/test_models.py`
- Modify: `agent-collab-console/backend/tests/test_api.py`

- [ ] **Step 1: Write the failing model/API tests**

```python
def test_session_can_hold_artifacts_and_messages():
    session = Session(id="s1", title="Build auth")
    assert session.artifacts == []
    assert session.messages == []
```

```python
def test_run_task_creates_message_and_artifact():
    session = client.post("/api/sessions", json={"title": "Build auth"}).json()
    task = client.post(f"/api/sessions/{session['id']}/tasks", json={"title": "Implement login API"}).json()
    client.post(f"/api/tasks/{task['id']}/run")
    refreshed = client.get(f"/api/sessions/{session['id']}").json()
    assert len(refreshed["messages"]) >= 1
    assert len(refreshed["artifacts"]) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_models.py tests/test_api.py -v`
Expected: FAIL because artifacts/messages do not exist yet

- [ ] **Step 3: Add Artifact and Message models**

```python
class Artifact(BaseModel):
    id: str
    task_id: str
    kind: str
    content: str


class Message(BaseModel):
    id: str
    task_id: str
    agent_id: str
    role: str
    content: str
```

- [ ] **Step 4: Attach artifacts/messages to Session and create them during runs**

```python
class Session(BaseModel):
    id: str
    title: str
    state: SessionState = SessionState.DRAFT
    tasks: list[Task] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)
```

```python
message = Message(...)
artifact = Artifact(...)
session.messages.append(message)
session.artifacts.append(artifact)
```

- [ ] **Step 5: Add API response coverage**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_models.py tests/test_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add agent-collab-console/backend
git commit -m "feat: add artifact and message timeline data model"
```

### Claude Code deliverable

- Backend session state now includes artifacts and agent message timeline entries

### Codex QA

- Check artifact/message creation is driven by real task execution events
- Reject if timeline data is fabricated only in the UI

## Task 15: Expose artifact and message timeline APIs

**Files:**
- Modify: `agent-collab-console/backend/app/interfaces/api.py`
- Modify: `agent-collab-console/backend/tests/test_api.py`

- [ ] **Step 1: Write the failing timeline API tests**

```python
def test_get_session_messages():
    session = client.post("/api/sessions", json={"title": "Build auth"}).json()
    task = client.post(f"/api/sessions/{session['id']}/tasks", json={"title": "Implement login API"}).json()
    client.post(f"/api/tasks/{task['id']}/run")
    response = client.get(f"/api/sessions/{session['id']}/messages")
    assert response.status_code == 200
    assert len(response.json()) >= 1
```

```python
def test_get_session_artifacts():
    session = client.post("/api/sessions", json={"title": "Build auth"}).json()
    task = client.post(f"/api/sessions/{session['id']}/tasks", json={"title": "Implement login API"}).json()
    client.post(f"/api/tasks/{task['id']}/run")
    response = client.get(f"/api/sessions/{session['id']}/artifacts")
    assert response.status_code == 200
    assert len(response.json()) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_api.py -v`
Expected: FAIL with missing timeline endpoints

- [ ] **Step 3: Add timeline endpoints**

```python
@router.get("/sessions/{session_id}/messages")
def get_session_messages(session_id: str):
    return session_service.get_session(session_id).messages


@router.get("/sessions/{session_id}/artifacts")
def get_session_artifacts(session_id: str):
    return session_service.get_session(session_id).artifacts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-collab-console/backend
git commit -m "feat: expose artifact and message timeline APIs"
```

### Claude Code deliverable

- Frontend-readable APIs for agent timeline and artifacts

### Codex QA

- Check timeline endpoints reflect backend state, not duplicated transient cache

## Task 16: Show artifact and message timeline in the console UI

**Files:**
- Create: `agent-collab-console/frontend/src/components/MessageTimeline.jsx`
- Create: `agent-collab-console/frontend/src/components/ArtifactPanel.jsx`
- Modify: `agent-collab-console/frontend/src/api.js`
- Modify: `agent-collab-console/frontend/src/App.jsx`
- Modify: `agent-collab-console/frontend/src/styles.css`

- [ ] **Step 1: Write the failing UX acceptance target**

Run the app after task execution.
Expected: There is still no visible agent message timeline or artifact panel.

- [ ] **Step 2: Add frontend timeline API helpers**

```javascript
export async function getSessionMessages(sessionId) {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}/messages`);
  return response.json();
}

export async function getSessionArtifacts(sessionId) {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}/artifacts`);
  return response.json();
}
```

- [ ] **Step 3: Add timeline components**

```javascript
export function MessageTimeline({ messages }) {
  return (
    <section>
      <h2>Messages</h2>
      {messages.map((message) => (
        <div key={message.id}>
          <strong>{message.agent_id}</strong>
          <p>{message.content}</p>
        </div>
      ))}
    </section>
  );
}
```

```javascript
export function ArtifactPanel({ artifacts }) {
  return (
    <section>
      <h2>Artifacts</h2>
      {artifacts.map((artifact) => (
        <div key={artifact.id}>
          <strong>{artifact.kind}</strong>
          <pre>{artifact.content}</pre>
        </div>
      ))}
    </section>
  );
}
```

- [ ] **Step 4: Wire App state and layout**

Expected:
- After running a task, timeline and artifact panels show backend-derived content
- Existing console layout expands without collapsing into a generic chat screen

- [ ] **Step 5: Run verification**

Run: `cd agent-collab-console/frontend && npm run build`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add agent-collab-console/frontend
git commit -m "feat: add artifact and message timeline panels"
```

### Claude Code deliverable

- A console UI that shows agent output as timeline entries and artifacts

### Codex QA

- Check the UI now communicates agent activity, not just task status
- Reject if artifact/message panels are disconnected from backend data

## Task 17: Add Codex planning path before worker execution

**Files:**
- Modify: `agent-collab-console/backend/app/adapters/fake_codex_adapter.py`
- Modify: `agent-collab-console/backend/app/application/orchestration_service.py`
- Modify: `agent-collab-console/backend/tests/test_orchestration_service.py`

- [ ] **Step 1: Write the failing planning-flow test**

```python
def test_plan_task_records_master_message_before_worker_run():
    session_service = SessionService()
    session = session_service.create_session("Build auth")
    orchestration = OrchestrationService(
        session_service=session_service,
        event_bus=[],
        master_adapter=FakeCodexAdapter(),
        worker_adapter=FakeClaudeAdapter(),
    )
    task = orchestration.plan_task(session.id, "Implement login API", "claude")
    assert session.messages[0].agent_id == "codex"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_orchestration_service.py -v`
Expected: FAIL because planning does not yet emit master output

- [ ] **Step 3: Add master planning output**

```python
planning_result = self.master_adapter.execute(title)
session.messages.append(
    Message(
        id=str(uuid4()),
        task_id=task.id,
        agent_id=planning_result["agent_id"],
        role=planning_result["role"],
        content=planning_result["summary"],
    )
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_orchestration_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-collab-console/backend
git commit -m "feat: record Codex planning output before worker execution"
```

### Claude Code deliverable

- Task planning now visibly includes a Codex master step before Claude worker execution

### Codex QA

- Check planning output is captured as a real message entry from the master agent
- Reject if the worker still appears to execute with no master orchestration evidence

## Task 18: Add run history domain support and read APIs

**Files:**
- Modify: `agent-collab-console/backend/app/domain/models.py`
- Modify: `agent-collab-console/backend/app/application/orchestration_service.py`
- Modify: `agent-collab-console/backend/app/interfaces/api.py`
- Modify: `agent-collab-console/backend/tests/test_models.py`
- Modify: `agent-collab-console/backend/tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_session_can_hold_runs():
    session = Session(id="s1", title="Build auth")
    assert session.runs == []
```

```python
def test_run_task_persists_run_history():
    session = client.post("/api/sessions", json={"title": "Build auth"}).json()
    task = client.post(f"/api/sessions/{session['id']}/tasks", json={"title": "Implement login API"}).json()
    client.post(f"/api/tasks/{task['id']}/run")
    refreshed = client.get(f"/api/sessions/{session['id']}").json()
    assert len(refreshed["runs"]) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_models.py tests/test_api.py -v`
Expected: FAIL because session run history does not exist yet

- [ ] **Step 3: Add run history to Session**

```python
class Session(BaseModel):
    ...
    runs: list[AgentRun] = Field(default_factory=list)
```

- [ ] **Step 4: Persist run records during execution**

```python
run = AgentRun(
    id=str(uuid4()),
    task_id=task.id,
    agent_id=result["agent_id"],
    role=result["role"],
    status=result["status"],
)
session.runs.append(run)
```

- [ ] **Step 5: Add run history API**

```python
@router.get("/sessions/{session_id}/runs")
def get_session_runs(session_id: str):
    return session_service.get_session(session_id).runs
```

- [ ] **Step 6: Re-run tests**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_models.py tests/test_api.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add agent-collab-console/backend
git commit -m "feat: add persistent run history to session state"
```

### Claude Code deliverable

- Run history becomes real backend state instead of remaining mostly frontend-local

### Codex QA

- Check `RunTimeline` can eventually be driven by backend state
- Reject if runs are still only ephemeral frontend state

## Task 19: Wire RunTimeline to backend run history

**Files:**
- Modify: `agent-collab-console/frontend/src/api.js`
- Modify: `agent-collab-console/frontend/src/App.jsx`
- Modify: `agent-collab-console/frontend/src/components/RunTimeline.jsx`

- [ ] **Step 1: Write the failing UX acceptance target**

Run a task and refresh the page.
Expected: Run history disappears because it is still frontend-local.

- [ ] **Step 2: Add frontend run history API helper**

```javascript
export async function getSessionRuns(sessionId) {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}/runs`);
  return response.json();
}
```

- [ ] **Step 3: Load and refresh runs from backend**

Expected:
- After task execution, `runs` comes from backend `getSessionRuns()`
- SSE refresh also updates `runs`

- [ ] **Step 4: Rebuild frontend**

Run: `cd agent-collab-console/frontend && npm run build`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-collab-console/frontend
git commit -m "feat: drive run timeline from backend state"
```

### Claude Code deliverable

- The run timeline survives refresh and reflects backend truth

### Codex QA

- Check `RunTimeline` is now backed by the server, not just local optimistic state

## Task 20: Replace fake planning/execution summary with structured artifacts

**Files:**
- Modify: `agent-collab-console/backend/app/application/orchestration_service.py`
- Modify: `agent-collab-console/backend/app/domain/models.py`
- Modify: `agent-collab-console/backend/tests/test_api.py`

- [ ] **Step 1: Write the failing artifact-structure test**

```python
def test_run_task_creates_typed_artifacts():
    session = client.post("/api/sessions", json={"title": "Build auth"}).json()
    task = client.post(f"/api/sessions/{session['id']}/tasks", json={"title": "Implement login API"}).json()
    client.post(f"/api/tasks/{task['id']}/run")
    artifacts = client.get(f"/api/sessions/{session['id']}/artifacts").json()
    assert artifacts[0]["kind"] in {"plan", "execution_result"}
```

- [ ] **Step 2: Run tests to verify it fails**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_api.py -v`
Expected: FAIL because artifacts are too generic

- [ ] **Step 3: Make planning and execution artifacts distinct**

```python
planning_artifact = Artifact(..., kind="plan", content=planning_result["summary"])
execution_artifact = Artifact(..., kind="execution_result", content=result["summary"])
```

- [ ] **Step 4: Re-run tests**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-collab-console/backend
git commit -m "feat: distinguish planning and execution artifacts"
```

### Claude Code deliverable

- Artifacts become semantically useful instead of generic output blobs

### Codex QA

- Check timeline and artifact panels can now distinguish planning from execution

## Task 21: Add configurable real adapter command wiring

**Files:**
- Modify: `agent-collab-console/backend/app/bootstrap.py`
- Modify: `agent-collab-console/README.md`
- Create: `agent-collab-console/backend/tests/test_bootstrap.py`

- [ ] **Step 1: Write the failing config expectation**

```python
def test_real_cli_uses_command_env(monkeypatch):
    monkeypatch.setenv("REAL_CLI", "true")
    monkeypatch.setenv("CLAUDE_CLI_COMMAND", "python3 -c print('worker')")
    monkeypatch.setenv("CODEX_CLI_COMMAND", "python3 -c print('planner')")
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_bootstrap.py -v`
Expected: FAIL because adapter commands are still hardcoded

- [ ] **Step 3: Read commands from env**

```python
claude_command = shlex.split(os.getenv("CLAUDE_CLI_COMMAND", "python3 -c print('task completed')"))
codex_command = shlex.split(os.getenv("CODEX_CLI_COMMAND", "python3 -c print('planned task')"))
```

- [ ] **Step 4: Wire master and worker adapters through config**

Expected:
- Fake mode remains safe default
- Real mode can be configured without code edits

- [ ] **Step 5: Update README**

Document:
- `REAL_CLI=true`
- `CLAUDE_CLI_COMMAND=...`
- `CODEX_CLI_COMMAND=...`

- [ ] **Step 6: Re-run tests**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_bootstrap.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add agent-collab-console/backend agent-collab-console/README.md
git commit -m "feat: add configurable real adapter command wiring"
```

### Claude Code deliverable

- Real adapter mode can be pointed at actual local commands without changing source code

### Codex QA

- Check config is explicit and safe by default
- Reject if real adapter wiring still requires hardcoded command edits

## Task 22: Make planning output structured and reusable

**Files:**
- Modify: `agent-collab-console/backend/app/application/orchestration_service.py`
- Modify: `agent-collab-console/backend/app/domain/models.py`
- Modify: `agent-collab-console/backend/tests/test_orchestration_service.py`

- [ ] **Step 1: Write the failing planning-structure test**

```python
def test_plan_task_creates_structured_plan_artifact():
    session = session_service.create_session("Build auth")
    task = session_service.add_task(session.id, "Implement login API")
    orchestration_service.plan_task(task.id)
    plan = session.artifacts[0]
    assert plan.kind == "plan"
    assert isinstance(plan.content, dict)
    assert "summary" in plan.content
    assert "next_steps" in plan.content
```

- [ ] **Step 2: Run tests to verify it fails**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_orchestration_service.py -v`
Expected: FAIL because planning output is still stored as plain text

- [ ] **Step 3: Normalize planning output**

Expected:
- `plan_task()` stores a structured `plan` artifact
- plan content includes at least:
  - `summary`
  - `next_steps`
  - `task_title`

- [ ] **Step 4: Re-run tests**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_orchestration_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-collab-console/backend
git commit -m "feat: store structured planning artifacts"
```

### Claude Code deliverable

- Planning artifacts become machine-readable inputs for downstream worker execution

### Codex QA

- Check planning output is structured enough to be passed into the worker path without prompt scraping

## Task 23: Pass master planning context into worker execution

**Files:**
- Modify: `agent-collab-console/backend/app/application/orchestration_service.py`
- Modify: `agent-collab-console/backend/app/adapters/fake_claude_adapter.py`
- Modify: `agent-collab-console/backend/app/adapters/claude_cli_adapter.py`
- Modify: `agent-collab-console/backend/tests/test_orchestration_service.py`

- [ ] **Step 1: Write the failing context-handoff test**

```python
def test_run_task_passes_latest_plan_to_worker():
    session = session_service.create_session("Build auth")
    task = session_service.add_task(session.id, "Implement login API")
    orchestration_service.plan_task(task.id)
    orchestration_service.run_task(task.id)
    assert fake_worker.last_payload["plan"]["summary"]
```

- [ ] **Step 2: Run tests to verify it fails**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_orchestration_service.py -v`
Expected: FAIL because worker execution currently only receives task title / plain input

- [ ] **Step 3: Build a minimal handoff payload**

Expected payload:
- `task_id`
- `task_title`
- `plan`
- `session_id`

Implementation note:
- Keep adapter API small; prefer `execute(payload: dict)` over adding many positional params

- [ ] **Step 4: Re-run tests**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_orchestration_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-collab-console/backend
git commit -m "feat: pass planning context into worker execution"
```

### Claude Code deliverable

- Worker execution finally reflects a real master -> worker handoff instead of two disconnected steps

### Codex QA

- Check worker input now carries explicit planning context from Codex

## Task 24: Expose run detail payloads and agent roles in the API

**Files:**
- Modify: `agent-collab-console/backend/app/interfaces/api.py`
- Modify: `agent-collab-console/backend/tests/test_api.py`

- [ ] **Step 1: Write the failing run-detail API test**

```python
def test_get_runs_returns_agent_role_and_summary():
    session = client.post("/api/sessions", json={"title": "Build auth"}).json()
    task = client.post(f"/api/sessions/{session['id']}/tasks", json={"title": "Implement login API"}).json()
    client.post(f"/api/tasks/{task['id']}/run")
    runs = client.get(f"/api/sessions/{session['id']}/runs").json()
    assert runs[0]["agent_id"]
    assert runs[0]["role"]
    assert runs[0]["summary"]
```

- [ ] **Step 2: Run tests to verify it fails**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_api.py -v`
Expected: FAIL because run payloads are still too thin for a real collaboration timeline

- [ ] **Step 3: Expand run serialization**

Expected:
- run API returns enough data for UI rendering:
  - `agent_id`
  - `role`
  - `summary`
  - `status`
  - `task_id`

- [ ] **Step 4: Re-run tests**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-collab-console/backend
git commit -m "feat: expose richer run details in api"
```

### Claude Code deliverable

- The frontend can distinguish master planning activity from worker execution activity

### Codex QA

- Check run APIs now support a true multi-agent timeline instead of generic run rows

## Task 25: Surface master-worker collaboration in the console UI

**Files:**
- Modify: `agent-collab-console/frontend/src/App.jsx`
- Modify: `agent-collab-console/frontend/src/components/RunTimeline.jsx`
- Modify: `agent-collab-console/frontend/src/components/MessageTimeline.jsx`
- Modify: `agent-collab-console/frontend/src/components/ArtifactPanel.jsx`
- Modify: `agent-collab-console/frontend/src/api.js`

- [ ] **Step 1: Define the failing UI expectation**

Expected UI behavior:
- planning message clearly labeled as `Codex / master`
- execution message clearly labeled as `Claude / worker`
- artifacts show `plan` vs `execution_result`
- run timeline distinguishes planning vs execution rows

- [ ] **Step 2: Build the UI updates**

Expected:
- role badges or labels for `master` / `worker`
- artifact kind labels
- timeline rows that are readable without opening JSON blobs

- [ ] **Step 3: Validate**

Run: `cd agent-collab-console/frontend && npm run build`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add agent-collab-console/frontend
git commit -m "feat: visualize master worker collaboration in console"
```

### Claude Code deliverable

- A demo user can now visibly understand who planned, who executed, and what artifacts were produced

### Codex QA

- Check the UI now reads like a collaboration console, not just a generic task runner

## Task 26: Parse structured CLI output into normalized agent results

**Files:**
- Modify: `agent-collab-console/backend/app/adapters/claude_cli_adapter.py`
- Modify: `agent-collab-console/backend/app/adapters/codex_cli_adapter.py`
- Modify: `agent-collab-console/backend/tests/test_cli_adapter.py`

- [ ] **Step 1: Write the failing parsing test**

```python
def test_claude_cli_adapter_parses_json_output():
    adapter = ClaudeCliAdapter(command=["python3", "-c", "print('{\"summary\":\"done\",\"artifacts\":[{\"kind\":\"execution_result\",\"content\":\"ok\"}]}')"])
    result = adapter.execute({"task_title": "Implement login API"})
    assert result["summary"] == "done"
    assert result["artifacts"][0]["kind"] == "execution_result"
```

- [ ] **Step 2: Run tests to verify it fails**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_cli_adapter.py -v`
Expected: FAIL because adapters currently treat stdout as plain text

- [ ] **Step 3: Add normalized parsing logic**

Expected:
- adapters accept plain text as fallback
- if stdout is JSON, parse:
  - `summary`
  - `artifacts`
  - `status`

- [ ] **Step 4: Re-run tests**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_cli_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-collab-console/backend
git commit -m "feat: parse structured cli output"
```

### Claude Code deliverable

- Real CLI adapters can consume more than a single raw stdout string

### Codex QA

- Check adapters now support both structured JSON output and safe plain-text fallback

## Task 27: Persist sessions and runs with SQLite

**Files:**
- Modify: `agent-collab-console/backend/app/application/session_service.py`
- Modify: `agent-collab-console/backend/app/bootstrap.py`
- Create: `agent-collab-console/backend/app/adapters/sqlite_store.py`
- Modify: `agent-collab-console/backend/tests/test_session_service.py`

- [ ] **Step 1: Write the failing persistence test**

```python
def test_session_service_restores_saved_session(tmp_path):
    store = SQLiteStore(tmp_path / "console.db")
    service = SessionService(store=store)
    session = service.create_session("Build auth")
    restored = SessionService(store=store).get_session(session.id)
    assert restored.title == "Build auth"
```

- [ ] **Step 2: Run tests to verify it fails**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_session_service.py -v`
Expected: FAIL because sessions are currently memory-only

- [ ] **Step 3: Introduce a minimal SQLite store**

Expected:
- persist sessions
- persist tasks
- persist runs
- store can reload them on service bootstrap

- [ ] **Step 4: Re-run tests**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_session_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-collab-console/backend
git commit -m "feat: persist collaboration state with sqlite"
```

### Claude Code deliverable

- Sessions survive process restarts instead of resetting to an empty in-memory state

### Codex QA

- Check the persistence layer is minimal and doesn’t leak SQL concerns across the app

## Task 28: Add session list and switching in the console UI

**Files:**
- Modify: `agent-collab-console/backend/app/interfaces/api.py`
- Modify: `agent-collab-console/backend/tests/test_api.py`
- Modify: `agent-collab-console/frontend/src/App.jsx`
- Create: `agent-collab-console/frontend/src/components/SessionList.jsx`
- Modify: `agent-collab-console/frontend/src/api.js`

- [ ] **Step 1: Write the failing session-list expectation**

Expected:
- backend exposes a session list API
- frontend can render multiple sessions and switch between them

- [ ] **Step 2: Implement session listing**

Expected:
- `GET /api/sessions`
- list shows title, state, and id

- [ ] **Step 3: Implement frontend switching**

Expected:
- left-side or top-side session list
- clicking a session refreshes tasks, runs, messages, artifacts, approval

- [ ] **Step 4: Validate**

Run:
- `cd agent-collab-console/backend && python3 -m pytest tests/test_api.py -v`
- `cd agent-collab-console/frontend && npm run build`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent-collab-console/backend agent-collab-console/frontend
git commit -m "feat: add session list and switching"
```

### Claude Code deliverable

- The console becomes usable for more than one collaboration session

### Codex QA

- Check session switching reloads server state instead of mixing local stale state

## Task 29: Add collaboration replay view from messages, runs, and artifacts

**Files:**
- Modify: `agent-collab-console/frontend/src/App.jsx`
- Create: `agent-collab-console/frontend/src/components/ReplayPanel.jsx`
- Modify: `agent-collab-console/frontend/src/styles.css`

- [ ] **Step 1: Define the replay expectation**

Expected:
- user can review a completed session as an ordered sequence
- replay combines:
  - planning messages
  - worker runs
  - artifacts

- [ ] **Step 2: Build a minimal replay panel**

Expected:
- chronological merged view
- clear labels for message / run / artifact
- optimized for reading, not editing

- [ ] **Step 3: Validate**

Run: `cd agent-collab-console/frontend && npm run build`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add agent-collab-console/frontend
git commit -m "feat: add collaboration replay panel"
```

### Claude Code deliverable

- The console gains a real review / audit surface instead of isolated panels only

### Codex QA

- Check replay reads like a coherent collaboration story, not a dump of disconnected records

## Task 30: Add created_at timestamps across collaboration records

**Files:**
- Modify: `agent-collab-console/backend/app/domain/models.py`
- Modify: `agent-collab-console/backend/app/application/orchestration_service.py`
- Modify: `agent-collab-console/backend/app/application/approval_service.py`
- Modify: `agent-collab-console/backend/app/adapters/sqlite_store.py`
- Modify: `agent-collab-console/backend/tests/test_orchestration_service.py`
- Modify: `agent-collab-console/backend/tests/test_session_service.py`

- [ ] **Step 1: Write the failing timestamp expectation**

```python
def test_run_records_created_at():
    ...
    orchestration.run_task(task.id)
    assert session.runs[0].created_at is not None
    assert session.messages[0].created_at is not None
```

- [ ] **Step 2: Run tests to verify it fails**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_orchestration_service.py tests/test_session_service.py -v`
Expected: FAIL because records currently have no timestamps

- [ ] **Step 3: Add timestamps to collaboration records**

Expected:
- `Message.created_at`
- `AgentRun.created_at`
- `Artifact.created_at`
- `Approval.created_at`

- [ ] **Step 4: Persist and restore timestamps**

Expected:
- SQLite round-trip preserves timestamps

- [ ] **Step 5: Re-run tests**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_orchestration_service.py tests/test_session_service.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add agent-collab-console/backend
git commit -m "feat: add timestamps to collaboration records"
```

### Claude Code deliverable

- Core collaboration records become orderable and auditable

### Codex QA

- Check timestamps exist for replay/audit, not just sessions

## Task 31: Make replay truly time-ordered

**Files:**
- Modify: `agent-collab-console/frontend/src/components/ReplayPanel.jsx`
- Modify: `agent-collab-console/frontend/src/styles.css`

- [ ] **Step 1: Define the failing replay expectation**

Expected:
- Replay sorts by `created_at`
- Items from different tasks can interleave naturally
- Entries still show task title and type

- [ ] **Step 2: Implement timestamp-based replay ordering**

Expected:
- merged array from messages/runs/artifacts/approvals if available
- sorted by timestamp ascending
- stable fallback when timestamps tie

- [ ] **Step 3: Validate**

Run: `cd agent-collab-console/frontend && npm run build`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add agent-collab-console/frontend
git commit -m "feat: order replay by timestamps"
```

### Claude Code deliverable

- Replay reads like an actual collaboration timeline instead of grouped output

### Codex QA

- Check replay is now truly chronological and still readable with multiple tasks

## Task 32: Track approval history and show it in replay

**Files:**
- Modify: `agent-collab-console/backend/app/domain/models.py`
- Modify: `agent-collab-console/backend/app/application/approval_service.py`
- Modify: `agent-collab-console/backend/app/interfaces/api.py`
- Modify: `agent-collab-console/backend/tests/test_api.py`
- Modify: `agent-collab-console/frontend/src/App.jsx`
- Modify: `agent-collab-console/frontend/src/components/ReplayPanel.jsx`

- [ ] **Step 1: Write the failing approval-history test**

```python
def test_approval_history_records_decision_events():
    ...
    client.post(f"/api/tasks/{task['id']}/approval")
    client.post(f"/api/approvals/{approval['id']}/approve")
    history = client.get(f"/api/sessions/{session['id']}/approval-history").json()
    assert len(history) >= 2
```

- [ ] **Step 2: Run tests to verify it fails**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_api.py -v`
Expected: FAIL because only current approval state exists

- [ ] **Step 3: Add approval history records**

Expected:
- record `requested`
- record `approved`
- record `rejected`
- associate with session/task

- [ ] **Step 4: Show approval history in replay**

Expected:
- replay includes approval steps inline with other activity

- [ ] **Step 5: Re-run tests / build**

Run:
- `cd agent-collab-console/backend && python3 -m pytest tests/test_api.py -v`
- `cd agent-collab-console/frontend && npm run build`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add agent-collab-console/backend agent-collab-console/frontend
git commit -m "feat: add approval history to replay"
```

### Claude Code deliverable

- Approval becomes part of the collaboration story instead of a transient side panel state

### Codex QA

- Check approval replay is complete enough to audit who asked, who approved, and when

## Task 33: Add failure states and recovery actions

**Files:**
- Modify: `agent-collab-console/backend/app/domain/states.py`
- Modify: `agent-collab-console/backend/app/application/orchestration_service.py`
- Modify: `agent-collab-console/backend/app/interfaces/api.py`
- Modify: `agent-collab-console/backend/tests/test_orchestration_service.py`
- Modify: `agent-collab-console/frontend/src/components/TaskBoard.jsx`
- Modify: `agent-collab-console/frontend/src/components/RunTimeline.jsx`
- Modify: `agent-collab-console/frontend/src/styles.css`

- [ ] **Step 1: Write the failing failure-flow test**

```python
def test_run_failure_marks_task_blocked():
    ...
    failing_worker = ...
    with pytest.raises(...):
        orchestration.run_task(task.id)
    assert task.status == "blocked"
```

- [ ] **Step 2: Run tests to verify it fails**

Run: `cd agent-collab-console/backend && python3 -m pytest tests/test_orchestration_service.py -v`
Expected: FAIL because failures are not modeled cleanly yet

- [ ] **Step 3: Add minimal recovery model**

Expected:
- failed run becomes visible
- task can become `blocked`
- API supports retry

- [ ] **Step 4: Add frontend visibility**

Expected:
- blocked/failed state visible in task board and run timeline
- retry action available

- [ ] **Step 5: Re-run tests / build**

Run:
- `cd agent-collab-console/backend && python3 -m pytest tests/test_orchestration_service.py -v`
- `cd agent-collab-console/frontend && npm run build`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add agent-collab-console/backend agent-collab-console/frontend
git commit -m "feat: add failure states and recovery actions"
```

### Claude Code deliverable

- The console can represent blocked work and basic retry/recovery paths

### Codex QA

- Check failure handling improves operator control instead of hiding broken runs
