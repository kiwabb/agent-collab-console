# Error Handling

> How errors are handled in the vibe-kanban backend package.

---

## Overview

The backend has **three layers of error handling**, each with a
distinct shape:

1. **Service / domain layer** — typed exceptions (`ProjectError`,
   `WorktreeError`, `GitError`, `SkillError`, ...). These are the
   "expected business error" cases and are caught at the transport
   boundary to produce a typed HTTP response.
2. **Transport / HTTP layer** — `fastapi.HTTPException` with a
   status code and a `detail` string. The shape is
   `{ "detail": "..." }` (FastAPI default). The router
   (`interfaces/api.py`) is the only place that knows the HTTP
   shape; services do not.
3. **Background loops** — the conductor and other long-running
   coroutines **do not** raise into the loop body. They catch
   exceptions, persist a `failed` row in `conductor_tasks` with
   the traceback in `result_json`, and emit a
   `conductor_state_violation` / `conductor_status` event. The
   loop survives a failed dispatch.

The rule is: **typed errors at the boundary, background failures
at the loop, HTTP-shaped errors at the transport**.

---

## Error Types

The project defines a small set of typed exceptions in
`application/`. Each module that owns a cohesive use case owns its
error type:

| Module | Error | Typical HTTP shape |
|--------|-------|-------------------|
| `project_service.py` | `ProjectError` | 400 / 404 / 409 |
| `worktree_manager.py` | `WorktreeError` | 500 (with safe detail) |
| `git_service.py` | `GitError` | 500 (with safe detail) |
| `skill_service.py` | `SkillError` | 400 |
| `product_manager_service.py` | `ProductManagerArtifactError` | 500 (artifact schema problem) |

All of these inherit from a common `AppError` (when present) or
`Exception` (when not). They carry a human-readable message and
optionally a structured `payload` for the transport layer to pick
up.

**Naming**: `XxxError`, never `XxxException`. The repository uses
`Error` consistently; tests and downstream code match.

---

## Error Handling Patterns

### Service → transport

```python
# application/project_service.py
class ProjectError(Exception):
    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code

# interfaces/api.py
try:
    project = await project_service.create(...)
except ProjectError as exc:
    raise HTTPException(status_code=400, detail=exc.message) from exc
```

The transport layer is the only place that knows the HTTP status
mapping. Tests for the service assert the `ProjectError`; tests
for the endpoint assert the `HTTPException`.

### Background loops

```python
# application/conductor_main_loop.py
try:
    result = await dispatch_subagent(...)
except Exception as exc:  # noqa: BLE001 — boundary catch by design
    log.exception("dispatch failed for issue %s", issue.id)
    await store.save_conductor_task(
        CodexTask(..., status="failed", result_json={"traceback": traceback.format_exc()})
    )
    await event_bus.append({"type": "conductor_status", "status": "failed", ...})
    # continue the loop — the next turn decides
```

The conductor **never** lets an exception escape its iteration
boundary. The loop is the supervisor; the supervisor never
crashes.

### Pydantic validation

`fastapi.HTTPException(status_code=422, detail=...)` is the default
shape for Pydantic validation failures. The frontend reads the
`detail` array shape; see `formatApiErrorDetail` in
`frontend/src/lib/utils.tsx` and the corresponding test.

### Async cleanup

When an `async with` block or a `try/finally` is used to clean
up a resource, exceptions in the cleanup body are **logged and
swallowed** — they do not mask the original exception. Use
`contextlib.suppress` for known-benign cases.

---

## API Error Responses

The shape is the FastAPI default:

```json
{ "detail": "Issue 'i-123' not found" }
```

For validation errors (`422`), the `detail` is an array of
field-level errors. Frontend format helper:
`formatApiErrorDetail(detail) => string` in
`frontend/src/lib/utils.tsx`.

**Status code conventions** (project-wide):

| Code | When |
|------|------|
| `200` | OK (the default for GETs and most PATCH/POSTs) |
| `201` | Resource created (POST that returns a `CodexIssue` etc.) |
| `400` | Bad request body (validation, Pydantic) |
| `404` | The addressed resource does not exist (issue, task, run, ...) |
| `409` | Conflict (state transition not allowed, duplicate create) |
| `422` | Pydantic validation (FastAPI default; rarely raised manually) |
| `500` | Internal error — the message is safe to surface |
| `503` | The store / service is unavailable (e.g. `codex_store is None`) |

The `503` case is the only one the project raises with a
predictable shape. It indicates "the server is not ready", not
"the request was bad"; the frontend treats it as transient.

---

## Scenario: Fail-Closed Agent Governance Gates

### 1. Scope / Trigger

- Trigger: changing any code that decides whether to launch more agent work:
  conductor `dispatch_subagent`, conductor `dispatch_batch`, specialist child
  launch, per-role redispatch caps, budget gates, or role-concurrency gates.
- These gates protect cost, concurrency, and runaway retry loops. If the gate's
  own state cannot be read, launching the work is unsafe.

### 2. Signatures

- Conductor tools:
  - `dispatch_subagent({ role, prompt?, prev_node_key? }) -> JsonObject`
  - `dispatch_batch({ agents: [{ role, prompt?, prev_node_key? }] }) -> JsonObject`
- Governance helpers:
  - `compute_issue_budget_status(store, issue) -> IssueBudgetStatus`
  - `store.load_workflow_graph_for_issue(issue_id) -> WorkflowGraph | None`
  - `RoleConcurrencyLimiter.acquire(role, timeout=0) -> bool`
  - `RoleConcurrencyLimiter.release(role) -> None`
- Failure result shape for tool-level gate unavailability:
  `{"status":"failed","gate":"budget|redispatch_budget|workflow_graph", "error": str, "details": str}`.
- Specialist failure exception:
  `SpecialistGovernanceError(message, gate="budget|concurrency", detail=str)`.

### 3. Contracts

- Dispatch gates are **fail-closed**:
  - Budget-status computation error -> refuse launch.
  - Workflow graph load error for redispatch/finalize governance -> refuse launch
    or finalize.
  - Role-concurrency limiter error -> refuse specialist launch.
- Over-budget is a normal refusal, not an internal crash.
- Busy role (`acquire(...)` returns `False`) preserves the existing
  `SpecialistOrchestratorError` max-concurrency refusal.
- Specialist role slots are held for the child lifetime, not just probed at
  launch. Release the slot on child terminal completion and on startup failure.
- Best-effort logging/event mirroring may swallow after logging, but the gate
  decision itself must not degrade to "allow".

### 4. Validation & Error Matrix

- `compute_issue_budget_status(...)` raises -> conductor returns
  `status="failed", gate="budget"`; specialist raises
  `SpecialistGovernanceError(gate="budget")`.
- `load_workflow_graph_for_issue(...)` raises while checking redispatch cap ->
  conductor returns `status="failed", gate="redispatch_budget"` before creating
  tasks/worktrees.
- `RoleConcurrencyLimiter.acquire(...)` raises -> specialist raises
  `SpecialistGovernanceError(gate="concurrency")` before creating a child task.
- `RoleConcurrencyLimiter.acquire(...)` returns `False` -> specialist raises the
  normal busy-role `SpecialistOrchestratorError` and creates no child task.
- Child start fails after slot acquire -> parent/child rollback path releases the
  role slot.
- Child reaches terminal status -> completion path releases the role slot.

### 5. Good/Base/Bad Cases

- Good: a DB error while reading budget returns a structured refusal and emits a
  governance-unavailable event; no new task/worktree is created.
- Good: two concurrent `specialist:security_reviewer` launches cannot both pass
  the cap; the first holds the role slot until its child completes.
- Base: issue has `budget_usd=0` (unlimited) -> budget gate succeeds.
- Bad: `except Exception: return None` in a gate where `None` means "no problem".
- Bad: acquiring and immediately releasing a specialist role slot before the
  child is actually running; that only probes capacity and does not enforce it.

### 6. Tests Required

- Backend pytest for conductor budget failure:
  `backend/tests/test_conductor_governance_fail_closed.py` asserts
  `gate == "budget"` and no worktree/task is prepared.
- Backend pytest for conductor graph failure:
  assert `gate == "redispatch_budget"` and no worktree/task is prepared.
- Backend pytest for specialist budget/concurrency failures:
  `backend/tests/test_specialist_governance_fail_closed.py` asserts no child is
  created and parent remains runnable.
- Backend pytest for specialist slot lifetime:
  same-role second launch is refused until the first child reaches terminal
  completion or startup rollback releases the slot.

### 7. Wrong vs Correct

Wrong:

```python
try:
    budget_status = await compute_issue_budget_status(store, issue)
except Exception:
    return None  # None means "dispatch may proceed"
```

Correct:

```python
try:
    budget_status = await compute_issue_budget_status(store, issue)
except Exception as exc:
    return await governance_failure(tool="dispatch_batch", gate="budget", error=exc)
```

Wrong:

```python
acquired = await limiter.acquire(role, timeout=0)
if acquired:
    limiter.release(role)  # releases before child lifetime is protected
```

Correct:

```python
acquired = await limiter.acquire(role, timeout=0)
if not acquired:
    raise SpecialistOrchestratorError("role is at max concurrency")
# Hold slot while child is in flight; release on child terminal/startup rollback.
```



- **Catching `Exception` too early.** A service that swallows
  everything to "always return a value" hides bugs. Catch the
  typed errors that the use case actually anticipates, and let
  unexpected exceptions propagate to the loop boundary or the
  transport layer where they can be logged with a traceback.
- **Returning HTTP-shaped errors from services.** A `dict(detail=...)`
  return value from a service is a leak. The service should
  raise a typed exception; the transport layer maps it.
- **`raise HTTPException(...)` from a service.** The same leak,
  in the other direction. Services are transport-agnostic.
- **Exposing internal details in 5xx messages.** A 500 with
  `detail="Traceback: ..."` is a security smell. The project's
  pattern is: log the traceback server-side, return a short
  message that is safe to surface.
- **Empty `except:`** (catches `BaseException` including
  `KeyboardInterrupt` and `SystemExit`). Use
  `except Exception:` and prefer typed exceptions when they exist.
- **Re-raising without `from`.** `raise X from exc` preserves
  the chain. The CI lint catches bare `raise` inside an
  `except` block.
- **Forgetting to close the async store in tests.** The async
  SQLite store holds an open connection; a missing `close()` in
  `finally` shows up as a `RuntimeError: Event loop is closed`
  on the next test that opens the same path. Use the
  `async with AsyncSQLiteStore(...)` form when available.
