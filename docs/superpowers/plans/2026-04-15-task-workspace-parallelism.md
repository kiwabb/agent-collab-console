# Task Workspace Parallelism Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each task own its own copied workspace directory so tasks can run independently and in parallel without git worktrees.

**Architecture:** The backend will create a dedicated workspace directory for every Codex task, seeded from the project root or cloned from a parent task's workspace when continuing work. Task execution will run inside the task's workspace path, and process tracking will be task-scoped instead of session-scoped so multiple tasks can run at once without sharing a cwd or subprocess. The frontend will keep the task workspace as the primary workflow and expose workspace metadata on each task card/detail view.

**Tech Stack:** Python, FastAPI, sqlite3, shutil, pytest, React, Vite

---

### Task 1: Add task workspace metadata and a workspace manager

**Files:**
- Update: `backend/app/domain/models.py`
- Update: `backend/app/adapters/sqlite_store.py`
- Create: `backend/app/application/workspace_manager.py`
- Update tests: `backend/tests/test_codex_tasks.py` or create `backend/tests/test_task_workspaces.py`

- [ ] **Step 1: Write the failing test**

```python
def test_task_creation_assigns_workspace_path(client):
    session = client.post("/api/codex/sessions", json={"title": "WS", "cwd": "/tmp"}).json()
    task = client.post("/api/codex/tasks", json={
        "session_id": session["id"],
        "title": "Task A",
        "prompt": "say hello",
    }).json()

    assert task["workspace_path"]
    assert task["workspace_path"].endswith(task["id"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd /Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/backend
python3 -m pytest tests/test_codex_tasks.py -v
```

Expected: the new workspace assertion fails because tasks do not yet store `workspace_path`.

- [ ] **Step 3: Write the minimal implementation**

```python
class CodexTask(BaseModel):
    id: str
    session_id: str
    title: str
    prompt: str
    status: str = "pending"
    result: str | None = None
    parent_task_id: str | None = None
    workspace_path: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
```

```python
class WorkspaceManager:
    def __init__(self, source_root: str, workspace_root: str):
        self.source_root = Path(source_root)
        self.workspace_root = Path(workspace_root)

    def create_workspace(self, task_id: str, parent_workspace_path: str | None = None) -> str:
        target = self.workspace_root / task_id
        if target.exists():
            return str(target)
        source = Path(parent_workspace_path) if parent_workspace_path else self.source_root
        shutil.copytree(source, target, ignore=shutil.ignore_patterns(
            ".git", ".worktrees", "worktrees", "node_modules", "dist", "__pycache__", ".pytest_cache", ".DS_Store"
        ))
        return str(target)
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
cd /Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/backend
python3 -m pytest tests/test_codex_tasks.py -v
```

Expected: the workspace-path assertions pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/models.py backend/app/adapters/sqlite_store.py backend/app/application/workspace_manager.py backend/tests/test_codex_tasks.py
git commit -m "feat: add task workspace metadata"
```

### Task 2: Run every task in its own workspace and allow parallel execution

**Files:**
- Update: `backend/app/bootstrap.py`
- Update: `backend/app/interfaces/api.py`
- Update: `backend/app/application/codex_process_manager.py`
- Update tests: `backend/tests/test_codex_process_manager.py`, `backend/tests/test_codex_api.py`

- [ ] **Step 1: Write the failing test**

```python
def test_two_tasks_can_run_in_parallel(client):
    session = client.post("/api/codex/sessions", json={"title": "Parallel", "cwd": "/tmp"}).json()
    task_a = client.post("/api/codex/tasks", json={"session_id": session["id"], "title": "A", "prompt": "task a"}).json()
    task_b = client.post("/api/codex/tasks", json={"session_id": session["id"], "title": "B", "prompt": "task b"}).json()

    assert task_a["workspace_path"] != task_b["workspace_path"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd /Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/backend
python3 -m pytest tests/test_codex_api.py tests/test_codex_process_manager.py -v
```

Expected: tasks still share a session-scoped process/cwd and the parallelism assertions fail.

- [ ] **Step 3: Write the minimal implementation**

```python
def create_codex_task(request: CreateTaskRequest):
    task_id = str(uuid4())
    workspace_path = workspace_manager.create_workspace(
        task_id,
        parent_workspace_path=parent_task.workspace_path if parent_task_id else None,
    )
    task = CodexTask(..., workspace_path=workspace_path)
    codex_store.save_codex_task(task)
    return task
```

```python
def run_codex_task(task_id: str):
    task = codex_store.load_codex_task(task_id)
    result = process_manager.run_task(
        task_id=task.id,
        cwd=task.workspace_path,
        prompt=task.prompt,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
cd /Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/backend
python3 -m pytest tests/test_codex_api.py tests/test_codex_process_manager.py -v
```

Expected: two tasks can be started independently, each with its own workspace path, and task status/logs remain isolated.

- [ ] **Step 5: Commit**

```bash
git add backend/app/bootstrap.py backend/app/interfaces/api.py backend/app/application/codex_process_manager.py backend/tests/test_codex_api.py backend/tests/test_codex_process_manager.py
git commit -m "feat: run codex tasks in isolated workspaces"
```

### Task 3: Make the frontend present tasks as workspace-backed parallel work items

**Files:**
- Update: `frontend/src/App.jsx`
- Update: `frontend/src/api.js`
- Update: `frontend/src/components/CodexTaskList.jsx`
- Update: `frontend/src/styles.css`
- Remove stale main-path components if unused: `frontend/src/components/TaskBoard.jsx`, `frontend/src/components/ReplayPanel.jsx`, `frontend/src/components/RunTimeline.jsx`, `frontend/src/components/ApprovalDrawer.jsx`, `frontend/src/components/SessionList.jsx`, `frontend/src/components/SessionPanel.jsx`, `frontend/src/components/MessageTimeline.jsx`

- [ ] **Step 1: Write the failing test**

```python
def test_task_card_shows_workspace_path():
    task = {"id": "t1", "title": "Task A", "status": "pending", "workspace_path": "/tmp/ws/t1"}
    assert "workspace_path" in task
```

- [ ] **Step 2: Run the build to capture current UI baseline**

Run:

```bash
cd /Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/frontend
npm run build
```

Expected: build currently passes, but the UI does not yet surface workspace metadata or clearly support parallel task work.

- [ ] **Step 3: Write the minimal implementation**

```jsx
<div className="task-meta">
  <span className="task-workspace">{task.workspace_path}</span>
</div>
```

```jsx
<button className="btn-run-task" onClick={() => onRun(task.id)} disabled={task.status === "running"}>
  {task.status === "running" ? "Running" : "Run"}
</button>
```

- [ ] **Step 4: Run the build to verify it passes**

Run:

```bash
cd /Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/frontend
npm run build
```

Expected: the task board renders workspace metadata cleanly and the build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.jsx frontend/src/api.js frontend/src/components/CodexTaskList.jsx frontend/src/styles.css frontend/src/components/TaskBoard.jsx frontend/src/components/ReplayPanel.jsx frontend/src/components/RunTimeline.jsx frontend/src/components/ApprovalDrawer.jsx frontend/src/components/SessionList.jsx frontend/src/components/SessionPanel.jsx frontend/src/components/MessageTimeline.jsx
git commit -m "feat: present codex tasks as workspace-backed work items"
```

### Task 4: Verify the one-task-one-workspace flow end to end and document it

**Files:**
- Update: `README.md`
- Update: `COMMUNICATION.md`
- Update tests as needed

- [ ] **Step 1: Write the failing smoke check**

```python
def test_smoke_two_tasks_use_distinct_workspaces(client):
    session = client.post("/api/codex/sessions", json={"title": "Smoke", "cwd": "/tmp"}).json()
    task_a = client.post("/api/codex/tasks", json={"session_id": session["id"], "title": "A", "prompt": "hello"}).json()
    task_b = client.post("/api/codex/tasks", json={"session_id": session["id"], "title": "B", "prompt": "world"}).json()
    assert task_a["workspace_path"] != task_b["workspace_path"]
```

- [ ] **Step 2: Run the backend smoke tests**

Run:

```bash
cd /Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/backend
python3 -m pytest tests/test_codex_api.py tests/test_codex_tasks.py tests/test_codex_process_manager.py -v
```

- [ ] **Step 3: Update the docs**

```md
Each task runs in its own workspace directory so tasks can execute in parallel without git worktrees.
```

- [ ] **Step 4: Run the frontend build again**

Run:

```bash
cd /Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/frontend
npm run build
```

- [ ] **Step 5: Commit**

```bash
git add README.md COMMUNICATION.md backend/tests frontend/src
git commit -m "docs: define task workspace parallelism"
```
