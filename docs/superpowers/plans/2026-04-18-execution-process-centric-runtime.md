# Execution-Process-Centric Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current task-centric runtime flow with an execution-process-centric runtime flow aligned to the official vibe-kanban architecture.

**Architecture:** Backend runtime state is projected into an `ExecutionProcessView` collection, streamed over one JSON Patch WebSocket rooted at `execution_processes`, and consumed by a frontend runtime store that renders execution processes as the primary live entity. `Task` remains as metadata and grouping, but no longer owns live logs, messages, approvals, or runtime status detail.

**Tech Stack:** FastAPI, Pydantic, SQLite, React 18, Vite, fast-json-patch, Node test runner, pytest

---

## File Structure

### Backend files

- Modify: `backend/app/domain/models.py`
  - Expand `ExecutionProcess` so it can represent the execution-process runtime view cleanly and stop carrying outdated task-bound semantics in docstrings.
- Modify: `backend/app/adapters/sqlite_store.py`
  - Add projection-oriented helpers for loading execution-process-owned logs/messages and session-scoped execution process collections.
- Modify: `backend/app/application/codex_process_manager.py`
  - Emit execution-process-aware events and update execution process state as the primary runtime lifecycle.
- Modify: `backend/app/interfaces/api.py`
  - Add session execution-process snapshot API and make run/message APIs maintain execution process ownership rules.
- Modify: `backend/app/interfaces/codex_ws.py`
  - Rebuild the WebSocket state root from `tasks` to `execution_processes`.
- Create: `backend/app/interfaces/execution_process_views.py`
  - Centralize `ExecutionProcessView` projection building so API and WebSocket code share one view contract.

### Backend tests

- Modify: `backend/tests/test_codex_tasks.py`
  - Update run-path tests to assert execution-process-first semantics.
- Modify: `backend/tests/test_task_message_api.py`
  - Update follow-up message tests to assert execution-process lifecycle changes.
- Create: `backend/tests/test_execution_process_views.py`
  - Cover projection shape and session snapshot behavior.
- Create: `backend/tests/test_execution_process_ws.py`
  - Cover initial `/execution_processes` snapshot and incremental patches.

### Frontend files

- Create: `frontend/src/hooks/applyExecutionProcessPatch.js`
  - Hold the pure patch reducer used by the hook.
- Modify: `frontend/src/hooks/useExecutionProcesses.js`
  - Move runtime state root to `execution_processes` and expose `executionProcesses`.
- Modify: `frontend/src/App.jsx`
  - Switch the app from task-rooted runtime selection to execution-process-rooted runtime selection.
- Modify: `frontend/src/components/CodexTaskList.jsx`
  - Make the list/detail UI consume execution-process-derived runtime data while keeping task metadata affordances.

### Frontend tests

- Create: `frontend/tests/executionProcessPatch.test.js`
  - Use the Node test runner to verify patch application over the execution-process root.

## Task 1: Build the Shared ExecutionProcessView Projection

**Files:**
- Create: `backend/app/interfaces/execution_process_views.py`
- Modify: `backend/app/adapters/sqlite_store.py`
- Modify: `backend/app/domain/models.py`
- Test: `backend/tests/test_execution_process_views.py`

- [ ] **Step 1: Write the failing projection test**

```python
from datetime import datetime

from app.domain.models import CodexTask, CodexTaskMessage, ExecutionProcess, LogEvent
from app.interfaces.execution_process_views import build_execution_process_view


def test_build_execution_process_view_includes_runtime_owned_fields():
    process = ExecutionProcess(
        id="exec-1",
        task_id="task-1",
        session_id="session-1",
        status="Running",
        exit_code=None,
        started_at=datetime(2026, 4, 18, 12, 0, 0),
        completed_at=None,
        created_at=datetime(2026, 4, 18, 12, 0, 0),
        updated_at=datetime(2026, 4, 18, 12, 1, 0),
    )
    task = CodexTask(
        id="task-1",
        session_id="session-1",
        title="Fix websocket model",
        prompt="Align runtime state",
        executor="codex",
        status="running",
        workspace_path="/tmp/task-1",
        created_at=datetime(2026, 4, 18, 11, 59, 0),
        updated_at=datetime(2026, 4, 18, 12, 1, 0),
    )
    messages = [
        CodexTaskMessage(
            id="msg-1",
            task_id="task-1",
            role="assistant",
            content="Working on it",
            created_at=datetime(2026, 4, 18, 12, 0, 30),
        )
    ]
    logs = [
        LogEvent(
            id="log-1",
            session_id="session-1",
            task_id="task-1",
            stream="stdout",
            content="started",
            created_at=datetime(2026, 4, 18, 12, 0, 10),
        )
    ]

    view = build_execution_process_view(process, task, messages, logs)

    assert view["id"] == "exec-1"
    assert view["task_id"] == "task-1"
    assert view["title"] == "Fix websocket model"
    assert view["messages"]["msg-1"]["content"] == "Working on it"
    assert view["logs"][0]["content"] == "started"
    assert view["workspace_path"] == "/tmp/task-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_execution_process_views.py::test_build_execution_process_view_includes_runtime_owned_fields -v`
Expected: FAIL with `ModuleNotFoundError` for `app.interfaces.execution_process_views` or missing `build_execution_process_view`.

- [ ] **Step 3: Write the minimal projection implementation**

```python
from app.domain.models import CodexTask, CodexTaskMessage, ExecutionProcess, LogEvent


def build_execution_process_view(
    process: ExecutionProcess,
    task: CodexTask | None,
    messages: list[CodexTaskMessage],
    logs: list[LogEvent],
) -> dict:
    return {
        "id": process.id,
        "session_id": process.session_id,
        "task_id": process.task_id,
        "status": process.status,
        "exit_code": process.exit_code,
        "title": task.title if task else process.task_id,
        "executor": task.executor if task else "codex",
        "workspace_path": task.workspace_path if task else None,
        "resume_session_id": task.resume_session_id if task else None,
        "created_at": process.created_at.isoformat() if process.created_at else None,
        "started_at": process.started_at.isoformat() if process.started_at else None,
        "updated_at": process.updated_at.isoformat() if process.updated_at else None,
        "completed_at": process.completed_at.isoformat() if process.completed_at else None,
        "messages": {
            message.id: {
                "id": message.id,
                "task_id": message.task_id,
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at.isoformat() if message.created_at else None,
            }
            for message in messages
        },
        "logs": [
            {
                "id": log.id,
                "stream": log.stream,
                "content": log.content,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    }
```

- [ ] **Step 4: Add store helpers that load per-process backing data**

```python
def list_execution_process_runtime_rows(self, session_id: str) -> list[tuple[ExecutionProcess, CodexTask | None, list[CodexTaskMessage], list[LogEvent]]]:
    processes = self.list_execution_processes(session_id=session_id)
    rows = []
    for process in processes:
        task = self.load_codex_task(process.task_id)
        messages = self.list_codex_task_messages(process.task_id)
        logs = self.load_log_events(session_id, task_id=process.task_id, limit=10000)
        rows.append((process, task, messages, logs))
    return rows
```

- [ ] **Step 5: Update the ExecutionProcess model comments to match the new semantics**

```python
class ExecutionProcess(BaseModel):
    """A single runtime execution for a CodexTask.

    ExecutionProcess is the primary live runtime entity for streaming state,
    logs, messages, approvals, and lifecycle updates.
    """
```

- [ ] **Step 6: Run the focused backend tests**

Run: `pytest backend/tests/test_execution_process_views.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/interfaces/execution_process_views.py backend/app/adapters/sqlite_store.py backend/app/domain/models.py backend/tests/test_execution_process_views.py
git commit -m "feat: add execution process view projection"
```

## Task 2: Move the Session Snapshot and WebSocket Stream to `execution_processes`

**Files:**
- Modify: `backend/app/interfaces/codex_ws.py`
- Modify: `backend/app/interfaces/api.py`
- Modify: `backend/tests/test_codex_tasks.py`
- Create: `backend/tests/test_execution_process_ws.py`
- Test: `backend/tests/test_execution_process_ws.py`

- [ ] **Step 1: Write the failing WebSocket snapshot test**

```python
def test_execution_process_ws_initial_snapshot_uses_execution_process_root(client):
    session = client.post("/api/codex/sessions", json={"title": "WS session", "cwd": ""}).json()
    task = client.post(
        f"/api/codex/sessions/{session['id']}/tasks",
        json={"title": "Task", "prompt": "Ping", "executor": "codex"},
    ).json()
    process = client.post(f"/api/codex/tasks/{task['id']}/run").json()

    with client.websocket_connect(f"/sessions/{session['id']}/execution_processes/ws") as ws:
        first = ws.receive_json()

    assert first["JsonPatch"][0]["path"] == "/execution_processes"
    assert process["id"] in first["JsonPatch"][0]["value"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_execution_process_ws.py::test_execution_process_ws_initial_snapshot_uses_execution_process_root -v`
Expected: FAIL because the current stream sends `replace /tasks`.

- [ ] **Step 3: Add the session snapshot endpoint for execution-process views**

```python
@router.get("/sessions/{session_id}/execution_processes")
def get_session_execution_processes(session_id: str):
    rows = codex_store.list_execution_process_runtime_rows(session_id)
    return {
        "execution_processes": {
            process.id: build_execution_process_view(process, task, messages, logs)
            for process, task, messages, logs in rows
        }
    }
```

- [ ] **Step 4: Rewrite `ExecutionProcessStreamManager.get_state()` to build one root**

```python
def get_state(self, session_id: str) -> dict:
    rows = codex_store.list_execution_process_runtime_rows(session_id) if codex_store else []
    execution_processes = {
        process.id: build_execution_process_view(process, task, messages, logs)
        for process, task, messages, logs in rows
    }
    self._states[session_id] = {"execution_processes": execution_processes}
    return self._states[session_id]
```

- [ ] **Step 5: Rewrite initial and incremental patch paths**

```python
initial_patch = [{
    "op": "replace",
    "path": "/execution_processes",
    "value": state["execution_processes"],
}]

patch = [{
    "op": "replace" if process_id in state["execution_processes"] else "add",
    "path": f"/execution_processes/{process_id}",
    "value": process_view,
}]
```

- [ ] **Step 6: Update tests for the new snapshot and patch root**

```python
assert response.json()["execution_processes"][process["id"]]["task_id"] == task["id"]
assert patch["path"].startswith("/execution_processes/")
```

- [ ] **Step 7: Run the focused backend tests**

Run: `pytest backend/tests/test_execution_process_ws.py backend/tests/test_codex_tasks.py -k execution_process -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/interfaces/codex_ws.py backend/app/interfaces/api.py backend/tests/test_execution_process_ws.py backend/tests/test_codex_tasks.py
git commit -m "feat: stream execution processes by session"
```

## Task 3: Make Run and Follow-Up APIs Maintain ExecutionProcess-First Runtime State

**Files:**
- Modify: `backend/app/interfaces/api.py`
- Modify: `backend/app/application/codex_process_manager.py`
- Modify: `backend/tests/test_codex_tasks.py`
- Modify: `backend/tests/test_task_message_api.py`
- Test: `backend/tests/test_codex_tasks.py`
- Test: `backend/tests/test_task_message_api.py`

- [ ] **Step 1: Write the failing follow-up-run test**

```python
def test_follow_up_message_creates_or_updates_execution_process_runtime(client):
    session = client.post("/api/codex/sessions", json={"title": "Follow-up", "cwd": ""}).json()
    task = client.post(
        f"/api/codex/sessions/{session['id']}/tasks",
        json={"title": "Task", "prompt": "Initial", "executor": "codex"},
    ).json()
    process = client.post(f"/api/codex/tasks/{task['id']}/run").json()

    response = client.post(
        f"/api/codex/tasks/{task['id']}/messages",
        json={"content": "Continue"},
    )
    body = response.json()

    assert response.status_code == 201
    assert body["task"]["last_execution_process_id"]
    assert body["task"]["last_execution_process_id"] != process["id"]
```

- [ ] **Step 2: Run the failing test**

Run: `pytest backend/tests/test_task_message_api.py::test_follow_up_message_creates_or_updates_execution_process_runtime -v`
Expected: FAIL because the current follow-up path mutates task state and does not establish a fresh execution-process runtime contract.

- [ ] **Step 3: Create a shared helper that starts an execution process for both run paths**

```python
def _create_execution_process(task) -> ExecutionProcess:
    now = datetime.now()
    process = ExecutionProcess(
        id=str(uuid4()),
        task_id=task.id,
        session_id=task.session_id,
        status="Running",
        exit_code=None,
        started_at=now,
        completed_at=None,
        created_at=now,
        updated_at=now,
    )
    codex_store.save_execution_process(process)
    task.last_execution_process_id = process.id
    task.updated_at = now
    codex_store.save_codex_task(task)
    return process
```

- [ ] **Step 4: Use the helper in both `POST /codex/tasks/{task_id}/run` and `POST /codex/tasks/{task_id}/messages`**

```python
exec_process = _create_execution_process(task)
task.status = "running"
codex_store.save_codex_task(task)
return {"message": message, "task": task, "execution_process": exec_process}
```

- [ ] **Step 5: Update process-manager completion handling to finalize execution processes first**

```python
execution_process_id = task.last_execution_process_id
if execution_process_id:
    self.codex_store.update_execution_process_status(
        execution_process_id,
        "Completed",
        exit_code=0,
        completed_at=datetime.now(),
    )
task.status = "done"
task.result = entry.result_text
self.codex_store.save_codex_task(task)
```

- [ ] **Step 6: Emit execution-process-aware events from notifications**

```python
self._event_bus.append({
    "type": "execution_process_status",
    "execution_process_id": execution_process_id,
    "session_id": task.session_id,
    "task_id": task.id,
    "status": "Completed",
})
```

- [ ] **Step 7: Run the focused backend tests**

Run: `pytest backend/tests/test_codex_tasks.py backend/tests/test_task_message_api.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/interfaces/api.py backend/app/application/codex_process_manager.py backend/tests/test_codex_tasks.py backend/tests/test_task_message_api.py
git commit -m "feat: make execution process the runtime owner"
```

## Task 4: Switch the Frontend Runtime Store to `execution_processes`

**Files:**
- Create: `frontend/src/hooks/applyExecutionProcessPatch.js`
- Modify: `frontend/src/hooks/useExecutionProcesses.js`
- Create: `frontend/tests/executionProcessPatch.test.js`
- Test: `frontend/tests/executionProcessPatch.test.js`

- [ ] **Step 1: Write the failing frontend reducer test**

```js
import test from 'node:test';
import assert from 'node:assert/strict';

import { applyExecutionProcessPatch } from '../src/hooks/applyExecutionProcessPatch.js';

test('applyExecutionProcessPatch stores data under execution_processes', () => {
  const next = applyExecutionProcessPatch(
    { execution_processes: {} },
    [{ op: 'add', path: '/execution_processes/exec-1', value: { id: 'exec-1', status: 'Running' } }],
  );

  assert.equal(next.execution_processes['exec-1'].status, 'Running');
});
```

- [ ] **Step 2: Run the failing frontend test**

Run: `node --test frontend/tests/executionProcessPatch.test.js`
Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `applyExecutionProcessPatch.js`.

- [ ] **Step 3: Add the pure patch reducer**

```js
import { applyPatch } from 'fast-json-patch';

export function applyExecutionProcessPatch(current, patches) {
  const base = current ?? { execution_processes: {} };
  const result = applyPatch(base, patches, false, false);
  return result.newDocument;
}
```

- [ ] **Step 4: Rewrite the hook state contract**

```js
if (!dataRef.current) {
  dataRef.current = { execution_processes: {} };
}

const executionProcesses = data?.execution_processes
  ? Object.values(data.execution_processes).map((process) => ({
      ...process,
      messages: process.messages ? Object.values(process.messages) : [],
      logs: process.logs || [],
    }))
  : [];

return {
  executionProcesses,
  executionProcessesById: data?.execution_processes || {},
  isConnected,
  isInitialized,
  error,
};
```

- [ ] **Step 5: Replace inline patch logic with the tested reducer**

```js
import { applyExecutionProcessPatch } from './applyExecutionProcessPatch';

if (msg.JsonPatch) {
  const next = applyExecutionProcessPatch(dataRef.current, msg.JsonPatch);
  dataRef.current = next;
  setData(next);
}
```

- [ ] **Step 6: Run the focused frontend test**

Run: `node --test frontend/tests/executionProcessPatch.test.js`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/hooks/applyExecutionProcessPatch.js frontend/src/hooks/useExecutionProcesses.js frontend/tests/executionProcessPatch.test.js
git commit -m "feat: switch frontend runtime store to execution processes"
```

## Task 5: Recompose the App and Task UI Around Execution Processes

**Files:**
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/components/CodexTaskList.jsx`
- Modify: `frontend/src/api.js`
- Test: `frontend/tests/executionProcessPatch.test.js`

- [ ] **Step 1: Write the failing runtime-selection test as a pure selection helper**

```js
import test from 'node:test';
import assert from 'node:assert/strict';

import { pickDisplayedTask } from '../src/components/CodexTaskList.jsx';

test('pickDisplayedTask derives detail state from execution process first', () => {
  const task = { id: 'task-1', title: 'Task 1', last_execution_process_id: 'exec-1' };
  const executionProcessesById = {
    'exec-1': { id: 'exec-1', task_id: 'task-1', status: 'Running', logs: [], messages: {} },
  };

  const displayed = pickDisplayedTask(task, executionProcessesById);

  assert.equal(displayed.runtime.id, 'exec-1');
  assert.equal(displayed.status, 'Running');
});
```

- [ ] **Step 2: Run the failing test**

Run: `node --test frontend/tests/executionProcessPatch.test.js`
Expected: FAIL because `pickDisplayedTask` does not exist and the task detail still expects task-owned logs/messages.

- [ ] **Step 3: Add a pure selector to merge task metadata with execution-process runtime**

```js
export function pickDisplayedTask(task, executionProcessesById) {
  const runtime = task?.last_execution_process_id
    ? executionProcessesById[task.last_execution_process_id] ?? null
    : null;

  return {
    ...task,
    status: runtime?.status ?? task?.status ?? 'pending',
    logs: runtime?.logs ?? [],
    messages: runtime?.messages ? Object.values(runtime.messages) : [],
    runtime,
  };
}
```

- [ ] **Step 4: Rewrite `App.jsx` to consume `executionProcesses`**

```jsx
const {
  executionProcesses,
  executionProcessesById,
  isConnected: wsConnected,
  error: wsError,
} = useExecutionProcesses(codexSession?.id);

const displayedTasks = (codexSession?.tasks || []).map((task) =>
  pickDisplayedTask(task, executionProcessesById),
);
```

- [ ] **Step 5: Update the task list and detail components to render derived runtime state**

```jsx
export function CodexTaskDetail({ task, ...props }) {
  const messages = sortTaskMessages(task?.messages || []);
  const logs = normalizeLogs(task?.logs || []);
  const runtimeStatus = task?.runtime?.status || task?.status;
```

- [ ] **Step 6: Keep APIs task-oriented for launch, but prefer execution-process reads for runtime display**

```js
export async function getSessionExecutionProcesses(sessionId) {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}/execution_processes`);
  return handleResponse(response);
}
```

- [ ] **Step 7: Run the frontend verification test**

Run: `node --test frontend/tests/executionProcessPatch.test.js`
Expected: PASS

- [ ] **Step 8: Build the frontend**

Run: `npm run build`
Expected: `vite build` completes successfully

- [ ] **Step 9: Commit**

```bash
git add frontend/src/App.jsx frontend/src/components/CodexTaskList.jsx frontend/src/api.js frontend/tests/executionProcessPatch.test.js
git commit -m "feat: render runtime state from execution processes"
```

## Task 6: Remove New Task-Centric Runtime Paths and Verify End-to-End Behavior

**Files:**
- Modify: `backend/app/interfaces/codex_ws.py`
- Modify: `backend/app/interfaces/api.py`
- Modify: `backend/app/application/codex_process_manager.py`
- Modify: `frontend/src/hooks/useExecutionProcesses.js`
- Modify: `backend/tests/test_codex_tasks.py`
- Modify: `backend/tests/test_task_message_api.py`
- Modify: `backend/tests/test_execution_process_ws.py`
- Test: `backend/tests/test_codex_tasks.py`
- Test: `backend/tests/test_task_message_api.py`
- Test: `backend/tests/test_execution_process_ws.py`
- Test: `frontend/tests/executionProcessPatch.test.js`

- [ ] **Step 1: Write the failing regression test that forbids task-rooted runtime patches**

```python
def test_execution_process_stream_does_not_emit_task_root_paths(client):
    session = client.post("/api/codex/sessions", json={"title": "No task root", "cwd": ""}).json()
    task = client.post(
        f"/api/codex/sessions/{session['id']}/tasks",
        json={"title": "Task", "prompt": "Ping", "executor": "codex"},
    ).json()
    client.post(f"/api/codex/tasks/{task['id']}/run")

    with client.websocket_connect(f"/sessions/{session['id']}/execution_processes/ws") as ws:
        message = ws.receive_json()

    assert all('/tasks/' not in patch['path'] for patch in message['JsonPatch'])
```

- [ ] **Step 2: Run the failing regression test**

Run: `pytest backend/tests/test_execution_process_ws.py::test_execution_process_stream_does_not_emit_task_root_paths -v`
Expected: FAIL until all legacy task-rooted runtime patch paths are removed.

- [ ] **Step 3: Delete or isolate remaining task-rooted runtime patch builders**

```python
# Remove task-rooted patch helpers:
# - update_task_status
# - add_message(task_id scoped patch paths)
# - add_log(task_id scoped patch paths)
# Replace them with execution-process view rebuilds keyed by process id.
```

- [ ] **Step 4: Ensure all event-bus runtime events can be projected into execution-process updates**

```python
if event["type"] in {"execution_process_status", "message_created", "log", "notification"}:
    process_id = event["execution_process_id"]
    process_view = self._build_process_view(process_id)
    await self.publish_patch(session_id, [{
        "op": "replace",
        "path": f"/execution_processes/{process_id}",
        "value": process_view,
    }])
```

- [ ] **Step 5: Run backend verification**

Run: `pytest backend/tests/test_execution_process_views.py backend/tests/test_execution_process_ws.py backend/tests/test_codex_tasks.py backend/tests/test_task_message_api.py -v`
Expected: PASS

- [ ] **Step 6: Run frontend verification**

Run: `node --test frontend/tests/executionProcessPatch.test.js`
Expected: PASS

- [ ] **Step 7: Run final build verification**

Run: `npm run build`
Expected: `vite build` completes successfully

- [ ] **Step 8: Commit**

```bash
git add backend/app/interfaces/codex_ws.py backend/app/interfaces/api.py backend/app/application/codex_process_manager.py frontend/src/hooks/useExecutionProcesses.js backend/tests/test_execution_process_ws.py backend/tests/test_codex_tasks.py backend/tests/test_task_message_api.py frontend/tests/executionProcessPatch.test.js
git commit -m "refactor: remove task-centric runtime patch flow"
```

## Final Verification Checklist

- Run: `pytest backend/tests/test_execution_process_views.py backend/tests/test_execution_process_ws.py backend/tests/test_codex_tasks.py backend/tests/test_task_message_api.py -v`
- Expected:
  - All targeted backend tests pass.
  - Session snapshots are rooted at `execution_processes`.
  - WebSocket patches never use `/tasks/...` for live runtime state.

- Run: `node --test frontend/tests/executionProcessPatch.test.js`
- Expected:
  - Patch reducer and task/runtime selector tests pass.

- Run: `npm run build`
- Expected:
  - Frontend production build completes successfully.
