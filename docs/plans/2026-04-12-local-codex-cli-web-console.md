# Local Codex CLI Web Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Execute one task at a time and stop for Codex QA after each task.

**Goal:** Build a web console that launches and manages local `codex` CLI sessions, shows real-time logs in the browser, and supports new session creation plus reopening console-managed historical sessions.

**Architecture:** Add a dedicated backend session/process bridge for local Codex CLI, store session metadata in SQLite and logs on disk, and build a frontend terminal workspace with session switching and live log streaming over WebSocket.

**Tech Stack:** Python, FastAPI, sqlite3, pytest, React, Vite, WebSocket, plain CSS

---

## Execution Rule

Every task in this plan must stop at a QA handoff point before the next task begins.

- After completing a task, Claude Code must update `agent-collab-console/COMMUNICATION.md`
- The update must include modified files, test commands, test results, commit message, implementation notes, and blockers
- After writing that update, Claude Code must stop and wait for Codex QA
- Claude Code must not start the next task until Codex explicitly approves the current one
- If a task is only partially complete or blocked, that status must still be written into `agent-collab-console/COMMUNICATION.md`

## Task 34: Add Codex session domain and persistence

**Goal:** Create a dedicated session model and SQLite-backed store for console-managed Codex sessions.

**Files:**
- Create: `agent-collab-console/backend/app/domain/codex_session.py`
- Create: `agent-collab-console/backend/app/adapters/codex_session_store.py`
- Create: `agent-collab-console/backend/tests/test_codex_session_store.py`

### Claude Code deliverable

- A persistent store for Codex session metadata
- Tests proving sessions survive store re-instantiation

### Codex QA

- Reject if sessions are still only in memory
- Reject if restored sessions lose `cwd`, `status`, or `log_path`

## Task 35: Build local Codex process manager

**Goal:** Launch and track local `codex` processes from backend code.

**Files:**
- Create: `agent-collab-console/backend/app/application/codex_process_manager.py`
- Create: `agent-collab-console/backend/tests/test_codex_process_manager.py`

### Claude Code deliverable

- A backend manager that can:
  - check local `codex` availability
  - create a session process
  - write input
  - terminate a process

### Codex QA

- Reject if manager does not keep per-session process ownership
- Reject if process lifecycle cannot be tested with a fake command

## Task 36: Add WebSocket log streaming and session APIs

**Goal:** Expose session lifecycle and live output over FastAPI.

**Files:**
- Update: `agent-collab-console/backend/app/interfaces/api.py`
- Create: `agent-collab-console/backend/app/interfaces/codex_ws.py`
- Update: `agent-collab-console/backend/app/main.py`
- Create: `agent-collab-console/backend/tests/test_codex_api.py`

### Claude Code deliverable

- `GET /api/codex/status`
- `GET /api/codex/sessions`
- `POST /api/codex/sessions`
- `GET /api/codex/sessions/{session_id}`
- `POST /api/codex/sessions/{session_id}/input`
- `POST /api/codex/sessions/{session_id}/terminate`
- `WS /api/codex/sessions/{session_id}/stream`

### Codex QA

- Reject if session creation does not persist metadata
- Reject if live stream is still mocked rather than connected to session log flow

## Task 37: Build the terminal workspace UI

**Goal:** Replace the current collaboration dashboard shell with a Codex terminal workspace.

**Files:**
- Update: `agent-collab-console/frontend/src/App.jsx`
- Create: `agent-collab-console/frontend/src/components/CodexSessionList.jsx`
- Create: `agent-collab-console/frontend/src/components/CodexTerminal.jsx`
- Create: `agent-collab-console/frontend/src/components/CodexComposer.jsx`
- Update: `agent-collab-console/frontend/src/api.js`
- Update: `agent-collab-console/frontend/src/styles.css`

### Claude Code deliverable

- Session list
- New session button
- Terminal log panel
- Input box for active session
- Connection and availability status

### Codex QA

- Reject if UI still centers on old task/run/artifact panels
- Reject if stream is not visibly live in the page

## Task 38: Add session restore and operator controls

**Goal:** Make the console usable across restarts and disconnections.

**Files:**
- Update: backend and frontend files created above
- Create or update tests needed for restore, reconnect, and terminate behavior

### Claude Code deliverable

- Reopen historical console-managed sessions from the UI
- Clear exited/disconnected/running statuses
- Terminate current session from the UI
- Recover session log history when reopening a session

### Codex QA

- Reject if reopening only restores metadata but not log history
- Reject if refresh kills the active process unexpectedly

## Task 41: Guard local startup against wrong backend port

**Goal:** Prevent the local frontend from silently connecting to the wrong service on port `8000`.

**Files:**
- Update: `agent-collab-console/dev-local.sh`
- Update: `agent-collab-console/README.md`

### Claude Code deliverable

- The local startup script checks whether ports `8000` and `5173` are already occupied before starting
- If `8000` is occupied, the script exits with a clear explanation that the frontend proxy may connect to the wrong backend
- README explains why a wrong service on `8000` can cause the UI to flash and then fail

### Codex QA

- Reject if startup still proceeds when `8000` is occupied
- Reject if the error message is vague about why the wrong backend breaks the UI

## Task 42: Make Codex session loading resilient to bad API responses

**Goal:** Ensure the frontend does not crash when API responses are malformed or come from the wrong backend.

**Files:**
- Update: `agent-collab-console/frontend/src/App.jsx`
- Update: `agent-collab-console/frontend/src/components/CodexSessionList.jsx`

### Claude Code deliverable

- `loadCodexSessions()` and related status loading paths safely handle unexpected response shapes
- The Codex session list component tolerates non-array input without crashing
- The page stays renderable even when `/api/codex/*` returns an incompatible payload

### Codex QA

- Reject if a non-array sessions payload can still crash render
- Reject if the UI still goes blank instead of falling back to a safe empty/error state

## Task 43: Improve local runtime diagnostics in the UI

**Goal:** Help the user understand whether the problem is backend reachability, wrong backend routing, or missing local `codex`.

**Files:**
- Update: `agent-collab-console/frontend/src/App.jsx`
- Update: `agent-collab-console/frontend/src/components/CodexSessionList.jsx`
- Update: `agent-collab-console/frontend/src/styles.css`

### Claude Code deliverable

- The Codex terminal area shows a clear diagnostic message when:
  - the backend is unreachable
  - the backend responds with the wrong shape
  - the backend is reachable but `codex` is unavailable
- The message is visible without opening browser devtools

### Codex QA

- Reject if `Unavailable` still appears without enough explanation
- Reject if the user must inspect network logs to understand the failure mode

## Task 44: Add a local runtime troubleshooting section to README

**Goal:** Document the real-world local startup issues we discovered during debugging.

**Files:**
- Update: `agent-collab-console/README.md`

### Claude Code deliverable

- README includes a troubleshooting section for:
  - checking `codex` in the local shell
  - checking which process owns port `8000`
  - checking which process owns port `5173`
  - diagnosing black screen, `Unavailable`, and empty session list behavior

### Codex QA

- Reject if the troubleshooting section does not cover the actual failure modes already observed
- Reject if the instructions are too vague to follow directly from a terminal

## Task 45: Auto-launch Codex on session creation

**Goal:** Make `New Session` immediately create a live, usable Codex session instead of leaving it in `disconnected`.

**Files:**
- Update: `agent-collab-console/backend/app/interfaces/api.py`
- Update: `agent-collab-console/backend/app/application/codex_process_manager.py`
- Update: `agent-collab-console/frontend/src/App.jsx`
- Update: `agent-collab-console/frontend/src/components/CodexSessionList.jsx`
- Update: `agent-collab-console/backend/tests/test_codex_api.py`

### Claude Code deliverable

- Creating a Codex session immediately launches the local `codex` process
- The newly created session becomes the active session in the UI
- The happy path no longer requires a separate manual `Launch` click for a fresh session

### Codex QA

- Reject if `New Session` can still leave the user in a dead `disconnected` state on the normal path
- Reject if create success is reported before launch actually succeeds or fails

## Task 46: Make Web terminal input/output reliably conversational

**Goal:** Ensure the user can type into the web UI and receive live Codex output as a real conversation loop.

**Files:**
- Update: `agent-collab-console/backend/app/application/codex_process_manager.py`
- Update: `agent-collab-console/backend/app/interfaces/codex_ws.py`
- Update: `agent-collab-console/frontend/src/components/CodexTerminal.jsx`
- Update: `agent-collab-console/frontend/src/components/CodexComposer.jsx`
- Update: `agent-collab-console/backend/tests/test_codex_process_manager.py`
- Update: `agent-collab-console/backend/tests/test_codex_api.py`

### Claude Code deliverable

- Web input is written to the active Codex PTY reliably
- Codex stdout continues to stream back to the page after input is sent
- The UI can demonstrate at least one full round trip: user input -> Codex output

### Codex QA

- Reject if input is only echoed locally but not delivered to the process
- Reject if output stops after the first message or requires a page refresh

## Task 47: Clean up Codex child processes on backend shutdown

**Goal:** Prevent orphan Codex processes from surviving backend exit or reload and burning CPU.

**Files:**
- Update: `agent-collab-console/backend/app/application/codex_process_manager.py`
- Update: `agent-collab-console/backend/app/main.py`
- Update: `agent-collab-console/backend/tests/test_codex_process_manager.py`
- Update: `agent-collab-console/README.md`

### Claude Code deliverable

- Backend shutdown terminates all active Codex child processes it launched
- Uvicorn reload / local script stop no longer leaves orphan `codex` processes behind
- README briefly documents the cleanup behavior and what to do if a stale process is found

### Codex QA

- Reject if child processes still survive backend shutdown
- Reject if cleanup only handles the currently selected session instead of all active sessions

## Task 48: Prove the minimal web-chat happy path end to end

**Goal:** Validate the product’s first truly useful workflow: create a session in the web UI, send input, and receive Codex output.

**Files:**
- Update tests needed across backend/frontend files above
- Update: `agent-collab-console/README.md`

### Claude Code deliverable

- A documented happy path for:
  - start local services
  - create a new Codex session
  - send one message
  - observe streamed output
- Automated tests or a tight manual verification note that proves this loop works

### Codex QA

- Reject if the app still requires hidden/manual recovery steps to start a basic session
- Reject if the documented happy path cannot be followed directly from the local UI

## Task 49: Isolate backend tests from real Codex processes

**Goal:** Ensure running backend tests never launches the real local `codex` binary or leaves CPU-burning orphan processes.

**Files:**
- Update: `agent-collab-console/backend/tests/test_codex_api.py`
- Update: `agent-collab-console/backend/tests/test_codex_process_manager.py`
- Update: `agent-collab-console/backend/app/bootstrap.py`
- Update: `agent-collab-console/README.md`

### Claude Code deliverable

- API tests use a fake/test process manager instead of the real `CodexProcessManager`
- Tests no longer depend on whether `codex` is installed locally
- Running `pytest` does not launch real `codex` processes on the machine

### Codex QA

- Reject if backend tests still call the real `codex` binary
- Reject if tests still use `skip when codex unavailable` as a substitute for isolation

## Task 50: Make TestClient lifecycle deterministic

**Goal:** Ensure FastAPI startup/shutdown and cleanup paths run reliably inside tests.

**Files:**
- Update: `agent-collab-console/backend/tests/test_codex_api.py`
- Update any shared test helpers needed

### Claude Code deliverable

- Replace module-level/global `TestClient(app)` usage with fixture/context-managed client lifecycle
- Cleanup hooks run deterministically for each relevant test scope
- Test structure no longer relies on implicit global app state across test functions

### Codex QA

- Reject if a module-level `TestClient(app)` still drives the Codex API tests
- Reject if lifecycle cleanup remains best-effort rather than deterministic

## Task 51: Add a test-safe Codex process mode

**Goal:** Provide an explicit backend testing mode where Codex session creation uses a harmless fake process manager.

**Files:**
- Update: `agent-collab-console/backend/app/bootstrap.py`
- Update: `agent-collab-console/backend/app/interfaces/api.py`
- Update tests/docs as needed

### Claude Code deliverable

- A clear testing mode toggle or dependency override path for Codex session/process handling
- Session API behavior remains testable without ever touching the real local `codex` binary
- The separation between production/local runtime and tests is obvious in code

### Codex QA

- Reject if test safety still depends on ambient machine state
- Reject if production and test process wiring are still entangled

## Task 52: Document safe test execution and orphan recovery

**Goal:** Make it obvious how to run tests safely and how to clean up if stale Codex processes already exist.

**Files:**
- Update: `agent-collab-console/README.md`

### Claude Code deliverable

- README explains that tests must not launch real Codex
- README includes a short orphan cleanup section with the exact recovery commands
- The testing section distinguishes unit/API tests from any future real integration tests

### Codex QA

- Reject if the docs still imply ordinary `pytest` may touch the real Codex runtime
- Reject if stale-process cleanup instructions are vague

## Task 53: Isolate test SQLite state from local runtime data

**Goal:** Ensure ordinary backend tests never write Codex sessions into the local development database or pollute the real session list in the web UI.

**Files:**
- Update: `agent-collab-console/backend/app/bootstrap.py`
- Update: `agent-collab-console/backend/tests/conftest.py`
- Update tests/docs as needed

### Claude Code deliverable

- Backend tests use a dedicated temporary SQLite path instead of the default `backend/console.db`
- Local runtime keeps using the normal dev database path
- Running `pytest` no longer creates persistent sessions that appear in the real web UI later

### Codex QA

- Reject if tests still write into the same SQLite file used by local development
- Reject if the separation depends on manual cleanup instead of automatic test configuration

## Task 54: Add an operator control to delete all Codex sessions

**Goal:** Give the user a safe way to clear accumulated Codex sessions from the console without manually deleting the SQLite file.

**Files:**
- Update: `agent-collab-console/backend/app/interfaces/api.py`
- Update: `agent-collab-console/frontend/src/App.jsx`
- Update any Codex session UI components needed
- Update tests/docs as needed

### Claude Code deliverable

- A backend endpoint or service path that deletes all console-managed Codex sessions
- A frontend control for `Delete All Sessions`
- The action is explicit and not easy to trigger by accident

### Codex QA

- Reject if delete-all can fire accidentally without a clear user action
- Reject if the frontend button exists but the backend path is missing or untested

## Task 55: Prove test-created sessions no longer leak into the real UI

**Goal:** Verify the root problem is actually fixed: after running tests, opening the local web app should not show test-generated session clutter.

**Files:**
- Update tests/docs as needed across files above

### Claude Code deliverable

- A verification path showing tests use isolated storage and local runtime session lists stay clean
- A brief README note if the verification requires a specific command or env var

### Codex QA

- Reject if the proof still relies on “delete the DB first” instead of true isolation
- Reject if local session lists can still be polluted by normal test runs

## Task 56: Replace PTY/TUI runtime with `codex exec --json` chat execution

**Goal:** Stop relying on the fragile interactive Codex TUI path and make the web app capable of stable single-turn chat by invoking `codex exec --json`.

**Files:**
- Update: `agent-collab-console/backend/app/application/codex_process_manager.py`
- Update: `agent-collab-console/backend/app/interfaces/api.py`
- Update tests/docs as needed

### Claude Code deliverable

- Codex session execution no longer launches the interactive TUI by default
- Sending input from the web UI triggers a `codex exec --json` style execution path
- Backend captures structured output and stores it as session log/message content
- The previous `TERM=dumb` / `Continue anyway? [y/N]` startup blocker is no longer on the happy path

### Codex QA

- Reject if the app still depends on the interactive TUI for the normal chat flow
- Reject if sending one message can still die on the TUI confirmation/panic path

## Task 57: Ship a minimal but real web chat loop on top of `codex exec`

**Goal:** Make the web UI actually usable for back-and-forth Codex interaction, even if the first version is request/response rather than full streaming TUI emulation.

**Files:**
- Update: `agent-collab-console/frontend/src/App.jsx`
- Update: `agent-collab-console/frontend/src/components/CodexTerminal.jsx`
- Update: `agent-collab-console/frontend/src/components/CodexComposer.jsx`
- Update any backend/frontend files needed

### Claude Code deliverable

- New session -> send one prompt -> receive Codex answer works end to end in the normal UI
- The UI clearly distinguishes user input from Codex output
- Empty/waiting states match the new request/response model instead of pretending a TUI stream is active when it is not

### Codex QA

- Reject if the user still cannot reliably send one prompt and get one Codex answer in the browser
- Reject if the UI still primarily reflects the old TUI-based mental model

## Task 58: Prove the new `codex exec` web-chat happy path end to end

**Goal:** Demonstrate that the new architecture actually fixes the original usability problem: the user can open the page, create a session, send a message, and get a response without manual recovery steps.

**Files:**
- Update tests/docs as needed across backend/frontend
- Update: `agent-collab-console/README.md`

### Claude Code deliverable

- A documented happy path for the new web chat model
- Automated tests and/or a tight verification script that proves a session can answer one prompt
- Documentation no longer points users toward the broken PTY/TUI-first flow as the main path

### Codex QA

- Reject if the documented happy path still depends on hidden terminal interaction or manual `y/N` recovery
- Reject if the proof only shows backend pieces working separately rather than one usable end-to-end flow

---

## Reset Direction: One `codex exec` per turn

**Why this reset is needed:**

- Real QA proved the current long-lived process model is still wrong for `codex exec --json`
- The process starts, stdin/stdout exist, but writing follow-up input into a running process does not yield a recognisable reply event
- The product should stop modeling a Codex session as a persistent interactive CLI process

**Runtime decision for MVP:**

- Use one isolated `codex exec --json "<full prompt>"` subprocess per user turn
- Pass the full prompt as a command argument
- Run that subprocess under PTY semantics in the current environment
- Do not depend on writing prompt text to `stdin` of a long-lived `codex exec --json` process

**Rejected options for MVP:**

- `codex exec --json` with long-lived pipes + post-launch stdin writes
  - rejected because real QA showed it starts but does not produce a recognisable reply event for follow-up input
- fully non-PTY execution as the baseline assumption
  - not accepted yet because the team has not reproduced a stable end-to-end app path without PTY
  - keep this as a follow-up investigation, not the current MVP contract

**New model:**

- A session is a persisted chat history container, not a live Codex process owner
- Each user message triggers one fresh `codex exec --json <prompt>` execution
- The backend stores the user message, runs Codex once, parses structured output, stores the assistant reply, and returns or streams progress back to the UI
- Session status becomes request-oriented (`idle`, `responding`, `done`, `failed`) rather than process-oriented (`running`, `disconnected`)

**Out of scope for this reset:**

- No persistent stdin-driven Codex process
- No `Launch Session` mental model on the main path
- Full removal of PTY from the runtime path

## Task 59: Replace long-lived session runtime with per-turn `codex exec` jobs

**Goal:** Refactor the backend so sending one message launches one isolated `codex exec --json` job and stores the result into session history.

**Files:**
- Update: `agent-collab-console/backend/app/application/codex_process_manager.py`
- Update: `agent-collab-console/backend/app/domain/codex_session.py`
- Update: `agent-collab-console/backend/app/interfaces/api.py`
- Update tests/docs as needed

### Claude Code deliverable

- Session creation no longer auto-launches a long-lived Codex subprocess
- Sending a message triggers a one-shot PTY-backed `codex exec --json "<full prompt>"` execution
- The backend persists:
  - the user message
  - the assistant reply
  - execution status and errors
- The old `launch` mental model is removed or clearly deprecated from the happy path

### Codex QA

- Reject if the backend still depends on keeping a Codex process alive between turns
- Reject if one send action does not map cleanly to one isolated PTY-backed `codex exec --json` execution

## Task 60: Rebuild the web UI around request/response chat instead of session launch

**Goal:** Make the frontend reflect the correct product model: open a session, send a message, wait for a reply, view history.

**Files:**
- Update: `agent-collab-console/frontend/src/App.jsx`
- Update: `agent-collab-console/frontend/src/components/CodexSessionList.jsx`
- Update: `agent-collab-console/frontend/src/components/CodexTerminal.jsx`
- Update: `agent-collab-console/frontend/src/components/CodexComposer.jsx`
- Update: `agent-collab-console/frontend/src/api.js`
- Update: `agent-collab-console/frontend/src/styles.css`

### Claude Code deliverable

- The main user flow becomes:
  - create/open session
  - send prompt
  - see pending state
  - receive assistant reply
- The UI no longer asks the user to `Launch` a session on the main path
- Status copy and empty states align with chat history, not terminal process ownership

### Codex QA

- Reject if the page still behaves like a terminal controller first and a chat UI second
- Reject if the main path still requires a launch step before a user can ask Codex something

## Task 61: Prove one-turn web chat works end to end under the new runtime model

**Goal:** Produce a hard proof that the browser flow actually works with the per-turn execution model.

**Files:**
- Update tests/docs as needed across backend/frontend
- Update: `agent-collab-console/README.md`

### Claude Code deliverable

- A verification path that proves:
  - create session
  - send one prompt
  - receive one assistant reply
- README explains the new happy path without referencing the retired long-lived launch workflow
- Tests or verification scripts no longer assume a long-lived Codex subprocess or stdin-driven follow-up writes
- The real-runtime verification path is documented as a manual smoke check, not a default every-change test step

### Codex QA

- Reject if proof still depends on process launch semantics that no longer belong to the product
- Reject if the final verification cannot demonstrate an actual assistant reply event end to end
- Reject if the docs imply `verify_happy_path.py` should run on every routine QA pass
