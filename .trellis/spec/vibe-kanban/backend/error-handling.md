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

## Common Mistakes

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
