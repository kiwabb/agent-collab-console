# Self-Improvement Application Audit Rollback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a durable application event ledger and reversible rollback for reviewed `project_memory` self-improvement applications.

**Architecture:** Keep SQL in the async/sync stores, represent event rows as a domain dataclass, keep file mutation in `self_improvement_apply_service.py`, and let `interfaces/api.py` map service errors to HTTP while recording event rows after project/proposal resolution.

**Tech Stack:** Python 3.13, dataclasses, FastAPI, aiosqlite/sqlite3, pytest.

---

### Task 1: Application Event Store

**Files:**
- Modify: `backend/app/domain/models.py`
- Modify: `backend/app/adapters/async_sqlite_store.py`
- Modify: `backend/app/adapters/sqlite_store.py`
- Test: `backend/tests/test_self_improvement_store.py`

- [ ] **Step 1: Write failing async/sync store tests**

Add a `_application_event(...)` helper returning `SelfImprovementApplicationEvent`, then add tests that save three events and assert newest-first order, `project_id` filter, `proposal_id` filter, and `limit`.

Run:

```bash
cd backend
python3 -m pytest tests/test_self_improvement_store.py::test_async_store_saves_lists_filters_and_limits_self_improvement_application_events tests/test_self_improvement_store.py::test_sync_store_saves_lists_filters_and_limits_self_improvement_application_events -v
```

Expected: import or attribute failure because `SelfImprovementApplicationEvent` and store methods do not exist yet.

- [ ] **Step 2: Add the event dataclass**

Add near `SelfImprovementProposal`:

```python
@dataclass
class SelfImprovementApplicationEvent:
    """Durable audit row for reviewed self-improvement apply/rollback attempts."""

    id: str
    proposal_id: str
    project_id: str
    issue_id: str
    target_kind: str
    action: str
    status: str
    path: str | None = None
    content_sha256: str | None = None
    result_json: str = "{}"
    error: str | None = None
    created_at: datetime | None = None
```

- [ ] **Step 3: Add table, indexes, and row mappings**

In both stores, create `self_improvement_application_events` with the dataclass fields, indexes `idx_self_improvement_application_events_project_created` and `idx_self_improvement_application_events_proposal_created`, and methods:

```python
save_self_improvement_application_event(event) -> None
list_self_improvement_application_events(project_id=None, proposal_id=None, limit=None)
```

Order lists by `created_at DESC, id DESC`; clamp `limit` to `1..100` like the proposal list.

- [ ] **Step 4: Verify green**

Run:

```bash
cd backend
python3 -m pytest tests/test_self_improvement_store.py -v
```

Expected: all store tests pass.

### Task 2: Rollback Service

**Files:**
- Modify: `backend/app/application/self_improvement_apply_service.py`
- Test: `backend/tests/test_self_improvement_apply_service.py`

- [ ] **Step 1: Write failing rollback service tests**

Add tests for:

```python
rollback_project_memory_proposal(project_repo_path=str(tmp_path), proposal=proposal)
```

Cases:
- removes only the `<!-- self-improvement-proposal:{id} -->` block and preserves surrounding notes;
- idempotently returns `already_absent=True` when marker is absent;
- rejects non-`applied` status with `code="invalid_status"`;
- rejects non-`project_memory` target with `code="unsupported_target"`;
- rejects missing repo path with `code="repo_unavailable"`.

Run:

```bash
cd backend
python3 -m pytest tests/test_self_improvement_apply_service.py::test_rollback_project_memory_proposal_removes_marker_block tests/test_self_improvement_apply_service.py::test_rollback_project_memory_proposal_is_idempotent_when_marker_absent -v
```

Expected: import failure because rollback helper does not exist.

- [ ] **Step 2: Implement rollback result and helper**

Add `SelfImprovementRollbackResult` with `path`, `content_sha256`, `already_absent`, and `bytes_written`, plus `to_dict()`.

Implement `rollback_project_memory_proposal(...)` using the same `MEMORY_DIR_NAME` and `MEMORY_FILE_NAME` constants. Remove from the proposal marker through the next `<!-- self-improvement-proposal:` marker or EOF, normalize to one trailing newline, and hash the removed block content when present.

- [ ] **Step 3: Verify green**

Run:

```bash
cd backend
python3 -m pytest tests/test_self_improvement_apply_service.py -v
```

Expected: all service tests pass.

### Task 3: API Event Listing, Apply Audit, and Rollback

**Files:**
- Modify: `backend/app/interfaces/api.py`
- Test: `backend/tests/test_self_improvement_api.py`

- [ ] **Step 1: Write failing API tests**

Add tests for:
- successful apply records a `succeeded` `apply` event with `path`, `content_sha256`, and JSON `result`;
- failed apply after resolution records a `failed` `apply` event and leaves proposal accepted;
- `GET /applications` returns newest-first project-scoped events;
- rollback removes marker, marks proposal `accepted`, and records `succeeded` `rollback`;
- rollback idempotence records `already_absent: true`;
- rollback rejects non-memory target/non-applied status with `409`;
- rollback/store unavailable/unknown project/proposal/cross-project keep existing `503`/`404` shapes.

Run:

```bash
cd backend
python3 -m pytest tests/test_self_improvement_api.py::test_project_self_improvement_proposal_applications_endpoint_lists_project_scoped_events tests/test_self_improvement_api.py::test_project_self_improvement_proposal_rollback_removes_memory_block_and_marks_accepted -v
```

Expected: route not found or missing store method.

- [ ] **Step 2: Add API serializers and event recorder**

Add `_self_improvement_application_event_to_dict(event)` that parses `result_json` into `result` and returns `created_at` as ISO text.

Add an async helper that builds a `SelfImprovementApplicationEvent` with `uuid4().hex`, saves it through the store, and records `result_json=json.dumps(result, sort_keys=True)`.

- [ ] **Step 3: Add applications endpoint**

Route:

```python
@router.get("/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/applications")
```

It must check store, project, proposal, cross-project proposal, then return:

```python
{"applications": [_self_improvement_application_event_to_dict(event) for event in events]}
```

- [ ] **Step 4: Wrap apply endpoint with event recording**

After project/proposal resolution, record:
- `action="apply"`, `status="succeeded"` after status update succeeds;
- `action="apply"`, `status="failed"` inside `except SelfImprovementApplyError` before raising HTTP `409`/`500`.

- [ ] **Step 5: Add rollback endpoint**

Route:

```python
@router.post("/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/rollback")
```

It must call `rollback_project_memory_proposal`, record rollback success, update proposal back to `accepted`, and return `{proposal, rollback}`. On `SelfImprovementApplyError`, record a failed rollback event after resolution and do not update proposal status.

- [ ] **Step 6: Verify green**

Run:

```bash
cd backend
python3 -m pytest tests/test_self_improvement_api.py -v
```

Expected: API tests pass.

### Task 4: Backend Spec Contract

**Files:**
- Modify: `.trellis/spec/vibe-kanban/backend/database-guidelines.md`

- [ ] **Step 1: Update self-improvement ledger scenario**

Extend the existing seven-section scenario with:
- `self_improvement_application_events` schema and store APIs;
- applications list endpoint;
- rollback endpoint;
- success/failure event contracts;
- rollback status/target/idempotence matrix;
- tests required for event store, API apply audit, applications list, and rollback.

- [ ] **Step 2: Verify doc has no placeholder language**

Run:

```bash
rg -n "TODO|TBD|placeholder" .trellis/spec/vibe-kanban/backend/database-guidelines.md
```

Expected: no matches introduced by this task.

### Task 5: Final Verification

**Files:**
- All touched files.

- [ ] **Step 1: Focused tests**

Run:

```bash
cd backend
python3 -m pytest tests/test_self_improvement_store.py tests/test_self_improvement_apply_service.py tests/test_self_improvement_api.py -v
```

- [ ] **Step 2: Full backend and smoke checks**

Run:

```bash
cd backend
python3 -m pytest -v
python3 -m compileall -q app
python3 -c "from app.main import app; print(bool(app))"
python3 -m ruff check .
```

If ruff is unavailable, record the exact failure.

- [ ] **Step 3: Diff hygiene**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; dirty files are only this task's code/spec/task artifacts.
