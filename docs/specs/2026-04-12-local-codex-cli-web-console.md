# Local Codex CLI Web Console MVP

## Goal

Build a local-first web console that can send prompts to local `codex` from the browser and show the reply inside a console-managed chat session. The user should be able to open the page, create or reopen a console-managed session, send one prompt, and receive one Codex response without touching a terminal.

## Product Summary

This is not a multi-agent orchestration dashboard yet. The product is a web chat wrapper around local Codex execution.

The first version should provide:

- detection of local `codex` CLI availability
- creation of a new console-managed Codex session
- persistence of console-managed session metadata
- one-shot `codex exec --json` execution per user turn
- persistence of user/assistant messages and execution outcomes
- switching between historical console-managed sessions

The first version should not provide:

- Claude Code integration
- automatic task decomposition
- native import of Codex's own hidden internal history store
- multi-agent routing
- approval workflows from the old collaboration-console flow

## Primary User Flow

1. User opens the web console.
2. Frontend checks backend status.
3. Backend reports whether local `codex` is available.
4. User chooses:
   - create a new session
   - open an existing console-managed session
5. User types a prompt and presses send.
6. Backend launches one isolated `codex exec --json <prompt>` job for that turn.
7. Backend stores:
   - the user message
   - the assistant reply
   - execution status or error
8. Frontend shows the updated chat history.

## Architecture

### 1. Session Registry

Owns session metadata:

- `id`
- `title`
- `status`
- `cwd`
- `created_at`
- `last_active_at`
- `log_path`
- `process_state`

The registry manages only sessions created through this console.

### 2. Codex Execution Runner

Owns one-shot local execution per user turn.

Responsibilities:

- verify that `codex` is available on the machine
- build a full prompt from session history plus the new user message
- run `codex exec --json <prompt>` as a fresh subprocess for each turn
- parse structured output and extract the assistant reply
- return success or failure for that turn

### 3. Message/Event Gateway

Owns stream fanout.

Responsibilities:

- persist user and assistant messages
- optionally publish in-flight execution progress to the frontend
- keep the UI updated with request/response state rather than terminal ownership

### 4. Persistence Layer

The first version should use:

- SQLite for session metadata
- SQLite for message history and execution state

This keeps implementation simple while making session recovery possible without relying on a live terminal process.

## Frontend Shape

The frontend should behave like a chat workspace, not like a terminal emulator.

### Main layout

- left sidebar: session list and new session button
- main panel: chat history for the selected session
- bottom input area: send one prompt
- top status bar: Codex availability and request state

### Expected interactions

- create session
- switch session
- send prompt
- see `responding` / `done` / `failed` status clearly
- reopen history without reattaching to a live process

## Backend Interfaces

### REST

- `GET /api/codex/status`
- `GET /api/codex/sessions`
- `POST /api/codex/sessions`
- `GET /api/codex/sessions/{session_id}`
- `POST /api/codex/sessions/{session_id}/input`
- `GET /api/codex/sessions/{session_id}/messages`

Streaming is optional for the first stable version. A simple request/response path is acceptable if it produces one reliable assistant reply per turn.

## Data Model

### CodexSession

- `id: str`
- `title: str`
- `cwd: str`
- `status: str`
- `created_at: datetime`
- `last_active_at: datetime`
- `last_error: str | null`

### SessionMessage

- `session_id: str`
- `role: str`
- `content: str`
- `created_at: datetime`

## Constraints

- first version should manage only sessions started by this console
- frontend should not talk to `codex` directly; all execution must go through backend
- one user send action should map to one Codex execution
- the happy path currently depends on PTY-backed execution in this environment

## Risks

### `codex exec` invocation mode

For this MVP, the currently validated execution path is:

- one user turn maps to one isolated `codex exec --json` subprocess
- the subprocess is started under PTY semantics
- the prompt is still passed as a command argument

At this stage, the MVP should assume PTY is required in the current environment.

The MVP should not rely on:

- keeping a long-lived `codex exec --json` subprocess alive between turns
- writing follow-up messages to subprocess stdin after launch

This decision is based on real QA evidence:

- long-lived stdin-driven execution did not yield recognisable reply events
- non-PTY assumptions did not hold reliably in the app runtime
- PTY is the only implementation path the team has been able to run successfully in the current MVP codebase

Non-PTY execution remains an open investigation, not the baseline assumption for this version.

### Session resume semantics

The first version should resume console-managed history only, not arbitrary external Codex sessions.

## Success Criteria

The MVP is successful when:

- opening the page shows whether local `codex` is available
- the user can create a new Codex session from the page
- the user can send one prompt and receive one Codex reply in the browser
- the user can reopen a previous console-managed session
- message history survives backend restarts
