# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

<!--
Document your project's quality standards here.

Questions to answer:
- What patterns are forbidden?
- What linting rules do you enforce?
- What are your testing requirements?
- What code review standards apply?
-->

(To be filled by the team)

---

## Forbidden Patterns

<!-- Patterns that should never be used and why -->

(To be filled by the team)

---

## Required Patterns

<!-- Patterns that must always be used -->

### Scenario: Safe Operational Diagnostics API

#### 1. Scope / Trigger

- Trigger: adding or changing machine-readable operational endpoints such as `GET /api/diagnostics`.
- These endpoints are cross-cutting support contracts: they inspect storage, runtime catalog, executors, websockets, and environment flags, so they must be safe to paste into support tickets and CI logs.

#### 2. Signatures

- API: `GET /api/diagnostics`
- Implementation location: `backend/app/interfaces/api.py`
- Success status: `200`
- Store unavailable status: `503` with detail `"SQLite store not available"`

#### 3. Contracts

- Top-level response fields: `service`, `status`, `generated_at`, `database`, `runtime_catalog`, `executors`, `websockets`, `config`, `checks`.
- `status` is `"ok"` only when all checks are ok; use `"degraded"` when any check is degraded or errored but the endpoint can still return a snapshot.
- Runtime catalog entries may expose booleans such as `api_endpoint_configured` and `api_key_configured`.
- Runtime catalog entries must not expose raw secret values, raw API keys, bearer tokens, auth headers, or provider credentials.
- Config fields should expose booleans for whether sensitive paths or env values are configured, not their raw values.

#### 4. Validation & Error Matrix

- `codex_store is None` -> HTTP `503`, detail `"SQLite store not available"`.
- Database query raises -> keep HTTP `200`, set `database.status = "error"`, append a database error check, and set top-level `status = "degraded"`.
- Runtime catalog load raises -> keep HTTP `200`, set `runtime_catalog.status = "error"`, append a runtime catalog error check, and set top-level `status = "degraded"`.
- Runtime catalog has no enabled executor -> keep HTTP `200`, append a degraded runtime catalog check, and set top-level `status = "degraded"`.

#### 5. Good/Base/Bad Cases

- Good: report executor availability and `api_key_configured: true` without returning the key.
- Base: return zero counts and empty subscriber counts when no sessions, processes, or websocket subscribers exist.
- Bad: returning `api_key`, `OPENAI_API_KEY`, token strings, workspace root paths, or SQLite paths in the diagnostics payload.

#### 6. Tests Required

- Test that `GET /api/diagnostics` returns all top-level sections.
- Test that a configured runtime API key is represented only by `api_key_configured: true`.
- Test that the raw API key string is absent from the full serialized response body.
- Test the `503` behavior when `codex_store` is unavailable.

#### 7. Wrong vs Correct

Wrong:

```python
{"api_key": executor.api_key, "sqlite_db_path": os.getenv("SQLITE_DB_PATH")}
```

Correct:

```python
{
    "api_key_configured": bool(executor.api_key),
    "sqlite_db_path_configured": bool(os.getenv("SQLITE_DB_PATH")),
}
```

---

## Testing Requirements

<!-- What level of testing is expected -->

(To be filled by the team)

---

## Code Review Checklist

<!-- What reviewers should check -->

(To be filled by the team)
