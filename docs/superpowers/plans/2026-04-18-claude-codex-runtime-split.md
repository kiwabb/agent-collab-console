# Claude And Codex Runtime Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate Claude's persistent stdin/stream-json runtime from Codex's app-server runtime without changing the backend API contract.

**Architecture:** Keep a single public manager entrypoint for the API layer, but turn it into a thin facade that routes to two independent runtime implementations: one dedicated to Codex app-server/approval handling and one dedicated to Claude persistent stdin/session resume handling. Shared persistence and event-bus behavior stay consistent, but executor-specific process lifecycle logic no longer lives in one mixed class.

**Tech Stack:** FastAPI, Python 3.14, SQLite-backed store, subprocess, threading, pytest

---

### Task 1: Lock The Runtime Split With Tests

**Files:**
- Modify: `backend/tests/test_codex_process_manager.py`

- [ ] **Step 1: Add a failing facade-routing test**

```python
def test_manager_routes_claude_and_codex_to_different_runtimes(store, tmp_path):
    from app.application.codex_process_manager import CodexProcessManager

    mgr = CodexProcessManager(codex_store=store, log_store=store, data_dir=str(tmp_path))

    assert mgr._claude_runtime is not mgr._codex_runtime
```

- [ ] **Step 2: Run the focused test and confirm it fails**

Run: `cd backend && PYTHONPATH=. python3.14 -m pytest tests/test_codex_process_manager.py -k different_runtimes -q`
Expected: FAIL because the facade has not been split yet

- [ ] **Step 3: Add a failing delegation test for Claude write_input**

```python
def test_manager_delegates_claude_write_input_to_claude_runtime(store, tmp_path):
    from app.application.codex_process_manager import CodexProcessManager

    mgr = CodexProcessManager(codex_store=store, log_store=store, data_dir=str(tmp_path))
    calls = []

    class StubClaudeRuntime:
        def write_input(self, **kwargs):
            calls.append(kwargs)
            return "responding"

    mgr._claude_runtime = StubClaudeRuntime()

    result = mgr.write_input("session-1", "hello", wait=False, executor="claude")

    assert result == "responding"
    assert calls and calls[0]["executor"] == "claude"
```

- [ ] **Step 4: Run the focused delegation test and confirm it fails**

Run: `cd backend && PYTHONPATH=. python3.14 -m pytest tests/test_codex_process_manager.py -k delegates_claude_write_input -q`
Expected: FAIL because the facade still implements the Claude path itself

- [ ] **Step 5: Commit the red tests**

```bash
git add backend/tests/test_codex_process_manager.py docs/superpowers/plans/2026-04-18-claude-codex-runtime-split.md
git commit -m "test: lock runtime split facade behavior"
```

### Task 2: Extract Shared Runtime Types

**Files:**
- Create: `backend/app/application/process_runtime_common.py`
- Modify: `backend/app/application/codex_process_manager.py`
- Test: `backend/tests/test_codex_process_manager.py`

- [ ] **Step 1: Create the shared runtime types file**

```python
from dataclasses import dataclass, field
import subprocess
import threading


@dataclass
class ProcessEntry:
    proc: subprocess.Popen
    output_thread: threading.Thread | None
    alive: bool
    session_id: str
    executor: str
    cwd: str
    resume_session_id: str | None
    resume_message_id: str | None = None
    pending_waiters: list = field(default_factory=list)
    result_text: str | None = None
```

- [ ] **Step 2: Update imports in the facade to use the shared ProcessEntry**

```python
from app.application.process_runtime_common import ProcessEntry
```

- [ ] **Step 3: Run the existing Claude tests**

Run: `cd backend && PYTHONPATH=. python3.14 -m pytest tests/test_codex_process_manager.py -k claude -q`
Expected: PASS

- [ ] **Step 4: Commit the shared type extraction**

```bash
git add backend/app/application/process_runtime_common.py backend/app/application/codex_process_manager.py backend/tests/test_codex_process_manager.py
git commit -m "refactor: extract shared process runtime types"
```

### Task 3: Extract Claude Runtime

**Files:**
- Create: `backend/app/application/claude_process_runtime.py`
- Modify: `backend/app/application/codex_process_manager.py`
- Test: `backend/tests/test_codex_process_manager.py`

- [ ] **Step 1: Move Claude-only process lifecycle into a dedicated class**

```python
class ClaudeProcessRuntime:
    def __init__(self, codex_store, log_store, data_dir=None, event_bus=None):
        ...

    def write_input(self, *, session_id, input_text, wait=True, task_id=None, executor="claude", resume_session_id=None, resume_message_id=None, cwd=None):
        ...
```

- [ ] **Step 2: Keep Claude-specific helpers inside the new runtime**

```python
def _write_claude_input(...): ...
def _spawn_claude_process(...): ...
def _build_claude_command(...): ...
def _encode_claude_input(...): ...
def _capture_on_reader(...): ...
def _persist_reader_metadata(...): ...
```

- [ ] **Step 3: Turn `CodexProcessManager` into a facade for Claude traffic**

```python
class CodexProcessManager:
    def __init__(...):
        self._claude_runtime = ClaudeProcessRuntime(...)

    def write_input(...):
        if executor == "claude":
            return self._claude_runtime.write_input(...)
```

- [ ] **Step 4: Run Claude-focused tests**

Run: `cd backend && PYTHONPATH=. python3.14 -m pytest tests/test_codex_process_manager.py -k claude -q`
Expected: PASS

- [ ] **Step 5: Commit the Claude extraction**

```bash
git add backend/app/application/claude_process_runtime.py backend/app/application/codex_process_manager.py backend/tests/test_codex_process_manager.py
git commit -m "refactor: extract claude process runtime"
```

### Task 4: Extract Codex App-Server Runtime

**Files:**
- Create: `backend/app/application/codex_app_server_runtime.py`
- Modify: `backend/app/application/codex_process_manager.py`
- Test: `backend/tests/test_codex_process_manager.py`

- [ ] **Step 1: Move Codex app-server and approval logic into a dedicated class**

```python
class CodexAppServerRuntime:
    def __init__(self, codex_store, log_store, data_dir=None, event_bus=None):
        ...
        self._app_server_clients = {}
        self._pending_approvals = {}
```

- [ ] **Step 2: Move Codex-only helpers**

```python
def _spawn_app_server_process(...): ...
def _make_app_server_notification_callback(...): ...
def resolve_approval(...): ...
def get_pending_approvals(...): ...
```

- [ ] **Step 3: Delegate Codex behavior from the facade**

```python
class CodexProcessManager:
    def __init__(...):
        self._codex_runtime = CodexAppServerRuntime(...)

    def write_input(...):
        if executor == "codex":
            return self._codex_runtime.write_input(...)
```

- [ ] **Step 4: Run Codex-focused manager/API tests**

Run: `cd backend && PYTHONPATH=. python3.14 -m pytest tests/test_codex_process_manager.py tests/test_codex_api.py -q`
Expected: PASS with existing skips only

- [ ] **Step 5: Commit the Codex extraction**

```bash
git add backend/app/application/codex_app_server_runtime.py backend/app/application/codex_process_manager.py backend/tests/test_codex_process_manager.py backend/tests/test_codex_api.py
git commit -m "refactor: extract codex app-server runtime"
```

### Task 5: Stabilize Bootstrap And Full Regression

**Files:**
- Modify: `backend/app/bootstrap.py`
- Modify: `backend/app/interfaces/api.py`
- Test: `backend/tests/test_task_message_api.py`
- Test: `backend/tests/test_codex_process_manager.py`
- Test: `backend/tests/test_codex_api.py`

- [ ] **Step 1: Keep bootstrap returning the same public manager type**

```python
def get_codex_process_manager():
    global codex_process_manager
    if codex_process_manager is None:
        from app.application.codex_process_manager import CodexProcessManager
        codex_process_manager = CodexProcessManager(...)
    return codex_process_manager
```

- [ ] **Step 2: Keep mock mode unchanged for tests and API wait semantics**

```python
wait_for_completion = isinstance(mgr, MockCodexProcessManager)
```

- [ ] **Step 3: Run the full regression set serially**

Run: `cd backend && PYTHONPATH=. python3.14 -m pytest tests/test_task_message_api.py tests/test_codex_process_manager.py tests/test_codex_api.py -q`
Expected: `43 passed, 3 skipped` or better

- [ ] **Step 4: Inspect the final diff**

Run: `git diff -- backend/app/bootstrap.py backend/app/application/codex_process_manager.py backend/app/application/claude_process_runtime.py backend/app/application/codex_app_server_runtime.py backend/app/application/process_runtime_common.py backend/tests/test_codex_process_manager.py backend/tests/test_task_message_api.py backend/tests/test_codex_api.py`
Expected: only runtime-split related changes

- [ ] **Step 5: Commit the integrated split**

```bash
git add backend/app/bootstrap.py backend/app/interfaces/api.py backend/app/application/codex_process_manager.py backend/app/application/claude_process_runtime.py backend/app/application/codex_app_server_runtime.py backend/app/application/process_runtime_common.py backend/tests/test_codex_process_manager.py backend/tests/test_task_message_api.py backend/tests/test_codex_api.py docs/superpowers/plans/2026-04-18-claude-codex-runtime-split.md
git commit -m "refactor: split claude and codex execution runtimes"
```
