# Codex Task Workspace

> **Product model**: This MVP is a Codex task workspace, not a general-purpose Codex chat client. A task owns its prompt, execution status, logs, and result. Each task run is an isolated `codex exec --json` execution. Sessions are workspaces that group related tasks together.

A local-first web console for creating Codex tasks, executing them, and observing results. The backend accesses your local `codex` command directly.

## Architecture

- **Backend**: Python, FastAPI, Pydantic
- **Frontend**: React, Vite
- **Persistence**: SQLite for task workspaces, Codex sessions, and execution log history
- **Execution**: Each task run = one `codex exec --json "<prompt>"` subprocess; prompts are passed as command arguments (not stdin), using pipes for stdout/stderr

## Recommended Run Mode

Use local startup by default.

This project currently works best when:

- the backend runs on your host machine
- the frontend runs on your host machine
- the backend can execute your local `codex` command directly

Docker is no longer the recommended primary workflow for Codex terminal usage, because a backend container does not automatically have access to your host `codex` binary.

## One-Command Local Startup

From the project root:

```bash
cd /Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console
./dev-local.sh
```

The script will:

- verify that `codex`, `uvicorn`, and `npm` are available
- start the backend on `http://localhost:8000`
- start the frontend on `http://localhost:5173`
- keep both processes in the foreground
- stop both processes when you press `Ctrl+C`

Before using it, make sure:

```bash
which codex
cd /Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/frontend && npm install
cd /Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/backend && pip install -r requirements.txt
```

**Port conflicts:** If ports 8000 or 5173 are already in use, the script exits with an error. Port 8000 conflict is especially important — the Vite dev server proxies `/api` to `localhost:8000`, so if another service is running on 8000 the frontend will silently connect to the wrong backend and the page may go blank or show errors.

## Codex Availability

The task workspace depends on the backend being able to run:

```bash
codex
```

If this command is not available in your local shell, the UI will show Codex as unavailable and task execution will fail.

## Worker Adapter Configuration

By default, the system runs with **FakeClaudeAdapter** and **FakeCodexAdapter** that return mock results for safe demo/testing.

To enable real CLI execution:

```bash
REAL_CLI=true uvicorn app.main:app --reload --port 8000
```

With `REAL_CLI=true`, both adapters use subprocess execution. Configure their commands via environment variables:

```bash
# Configure the worker (Claude Code) command
export CLAUDE_CMD="python3 -c \"print('task completed')\""

# Configure the master (Codex) command
export CODEX_CMD="python3 -c \"print('planned')\""

# Start with real adapters
REAL_CLI=true uvicorn app.main:app --reload --port 8000
```

The `CLAUDE_CMD` and `CODEX_CMD` values are shell-style command strings (parsed with `shlex.split`), so quotes and arguments work as expected.

## Manual Local Run

### Backend

```bash
cd /Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd /Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/frontend
npm install
npm run dev
```

## Local Demo

Happy path — create and run a task:

1. Start both services: `./dev-local.sh` (or run backend + frontend manually).
2. Open [http://localhost:5173](http://localhost:5173).
3. The page shows `Codex Task Workspace`.
4. In the sidebar, click **+ New Session** to create a workspace.
5. Click **+ New Task** in the task panel.
6. Enter a **title** (e.g., "Plan auth module") and a **prompt** (e.g., "Write a small Python auth module with JWT support").
7. Click **Create Task**.
8. Click **Run** on the task card — the backend executes `codex exec --json "<prompt>"`.
9. Watch **Logs** stream in the detail panel.
10. When the task completes, the **Result** panel shows the final output.
11. Optionally click **Continue** on a completed task to create a follow-up task with the previous result pre-filled.

In a healthy local path, Codex produces output in about 20-30 seconds (model loading, skill loading are the main factors).

## Troubleshooting

### Page is blank or shows a backend error

The frontend proxies `/api` to `localhost:8000`. If another service is running on port 8000, the frontend connects to the wrong backend and the page may go blank.

**Check who is on port 8000:**
```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

**Fix:** Stop the conflicting service on port 8000, or run the backend on a different port and update the Vite proxy target.

### Backend unreachable

The page shows a "Backend unreachable" diagnostic. The backend is not running or port 8000 is blocked.

**Check if backend is running:**
```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

**Fix:** Run `./dev-local.sh` (or start the backend manually on port 8000).

### Wrong backend service

The page shows "Wrong Backend Service". The service at port 8000 exists but is not the Agent Collaboration Console backend.

**Verify the backend is correct:**
```bash
curl http://localhost:8000/api/health
# Should return: {"service": "agent-collab-console", "version": "1.0"}
```

**Fix:** Make sure only one service is running on port 8000 — the correct backend. Restart the backend.

### Codex not available

The workspace shows "Codex not available" in blue. The backend is reachable but the `codex` command is not found in the shell environment.

**Check if `codex` is in your PATH:**
```bash
which codex
```

**Fix:** Install `codex` and make sure it is in your `PATH`.

### Port 8000 or 5173 already in use

The startup script exits with a port conflict error before starting.

**Check port 8000:**
```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

**Check port 5173:**
```bash
lsof -nP -iTCP:5173 -sTCP:LISTEN
```

**Fix:** Stop the existing service on the conflicting port, or run that service on a different port.

### Session list is empty

The sidebar shows "No sessions" even after the backend is running.

**Check if the backend is correct:**
```bash
curl http://localhost:8000/api/health
```

**Check if the SQLite store has sessions:**
```bash
curl http://localhost:8000/api/codex/sessions
```

**Fix:** If the backend is wrong (not agent-collab-console), restart on port 8000 with the correct backend. If the backend is correct but sessions are still empty, the store may be fresh — create a new session.

### Task execution fails

Task stays in "running" and then shows "failed", or no logs appear.

**Check `codex` availability:**
```bash
which codex
```

**Fix:** Make sure `codex` is available in your shell environment.

### Logs not appearing

Logs pane stays empty after running a task.

**Check WebSocket connection:** The log stream should show live output as Codex produces it.

**Fix:** Refresh the task to re-fetch logs, or check the backend logs for errors.

## API Endpoints

### Collaboration (legacy)
- `POST /api/sessions` - Create a new session
- `POST /api/sessions/{session_id}/tasks` - Add a task to a session
- `POST /api/tasks/{task_id}/run` - Execute a task
- `POST /api/tasks/{task_id}/approval` - Request approval for a task

### Codex Task Workspace
- `POST /api/codex/sessions` - Create a new task workspace
- `GET /api/codex/sessions` - List all workspaces
- `POST /api/codex/tasks` - Create a new task in a workspace (`parent_task_id` optional for continuations)
- `GET /api/codex/tasks` - List all tasks (optional `?session_id=` filter)
- `POST /api/codex/tasks/{task_id}/run` - Execute a task (blocks until completion)
- `GET /api/codex/tasks/{task_id}/logs` - Get logs for a task run

## Testing

### Running Tests

```bash
cd backend
python3 -m pytest -v
```

### Test Safety Guarantee

Ordinary pytest runs (`python3 -m pytest`) are fully test-safe and **never touch the real Codex runtime**:

- **Process isolation** — `CODEX_LAUNCH_ENABLED=false` forces `MockCodexProcessManager` in all tests. No real `codex` subprocess is ever spawned.
- **Availability isolation** — `force_codex_available` fixture patches `check_codex_available()` to always return `True`. Tests do not skip based on whether `codex` is installed on the host machine.

This means tests run identically on machines with or without `codex` installed. The two-layer isolation guarantees that even if a test calls `POST /api/codex/sessions`, it will use the mock process manager and not the real one.

### Future Integration Tests

Tests that need to exercise the real `CodexProcessManager` with actual `codex` subprocesses (end-to-end or smoke tests) should be placed in a separate `tests/integration/` directory and run with `CODEX_LAUNCH_ENABLED=true REAL_CLI=true`. These are not run by the default `python3 -m pytest` command.

### `verify_happy_path.py` Is a Manual Smoke Check

`backend/verify_happy_path.py` is **not** part of the normal test suite.

Use it only when you explicitly want to verify the real Codex runtime path end to end:

- create/open a session
- send one prompt
- wait for a real Codex reply

This script is intentionally slower than ordinary tests because it talks to the real `codex` runtime and may take tens of seconds or longer depending on upstream conditions.

Recommended workflow:

1. During normal development, run only:
   ```bash
   cd backend
   python3 -m pytest -v
   ```
2. Only when validating the real Codex path, run:
   ```bash
   cd backend
   CODEX_LAUNCH_ENABLED=true python3 verify_happy_path.py
   ```

Do **not** treat `verify_happy_path.py` as a must-run step for every code change.

### Orphan Process Recovery

Each task run spawns one `codex exec --json` subprocess. If a subprocess escapes its lifecycle (e.g., due to an interrupted backend or a long-running task that exceeds the 600s timeout), it may appear as a leftover process.

```bash
# Find orphan codex processes
ps -Ao pid,ppid,stat,%cpu,command | rg '/Users/zhoujiaangyao/.npm-global/bin/codex|codex-darwin-arm64/vendor/.*/codex/codex'

# Kill by exact path
pkill -f '/Users/zhoujiaangyao/.npm-global/bin/codex'
pkill -f 'codex-darwin-arm64/vendor/.*/codex/codex'
```

Since tests use `MockCodexProcessManager`, ordinary pytest runs cannot create orphans. These commands are for recovering after running the backend with real Codex execution.

## Docker Status

Docker files are still present for experimentation, but Docker is not the recommended runtime for real local Codex execution.

Why:

- the backend container does not automatically have your host `codex` binary
- terminal WebSocket behavior needs separate Docker-specific proxy handling
- local startup gives the most reliable Codex experience right now

## Project Structure

```
agent-collab-console/
├── backend/
│   ├── app/
│   │   ├── domain/         # Session and log models
│   │   ├── application/    # Codex process lifecycle
│   │   ├── adapters/       # SQLite persistence and CLI adapters
│   │   └── interfaces/     # FastAPI routes and WebSocket streaming
│   └── tests/
├── frontend/
│   └── src/
│       └── components/     # Codex terminal workspace UI
├── dev-local.sh
├── docker-compose.yml
└── README.md
```
