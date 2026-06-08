# Self Improvement Project Memory Apply Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first reviewed application path for accepted `project_memory` self-improvement proposals.

**Architecture:** Keep `apply-plan` as the non-mutating dry-run contract. Add a hash-gated service that rebuilds the current dry-run candidate, verifies the caller reviewed that exact content, appends it to `.agent-collab/team_notes.md`, and asks the store to mark the proposal `applied`. The HTTP route maps typed service errors to existing FastAPI status conventions.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, pytest, sqlite-backed store methods already present.

---

### Task 1: Service Contract

**Files:**
- Modify: `backend/tests/test_self_improvement_apply_service.py`
- Modify: `backend/app/application/self_improvement_apply_service.py`

- [ ] **Step 1: Write failing service tests**

Add tests that import `apply_project_memory_proposal`, `hash_apply_candidate_content`, and `SelfImprovementApplyError`.

```python
def test_hash_apply_candidate_content_uses_sha256_hex():
    assert hash_apply_candidate_content("hello\n") == (
        "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163faba36543"
        "54ddf9d241a"
    )


def test_apply_project_memory_proposal_appends_reviewed_candidate(tmp_path):
    proposal = _proposal()
    plan = build_self_improvement_apply_plan(proposal)
    content = plan["candidate_changes"][0]["content"]
    result = apply_project_memory_proposal(
        project_repo_path=str(tmp_path),
        proposal=proposal,
        reviewed_content_sha256=hash_apply_candidate_content(content),
    )
    assert result.path == ".agent-collab/team_notes.md"
    assert result.content_sha256 == hash_apply_candidate_content(content)
    assert result.already_present is False
    assert (tmp_path / ".agent-collab/team_notes.md").read_text() == content
```

Add matching tests for duplicate marker idempotence, hash mismatch, unsupported target kind, invalid proposal status, and missing repo path.

- [ ] **Step 2: Run service tests and verify RED**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_self_improvement_apply_service.py -v
```

Expected: imports for the new symbols fail.

- [ ] **Step 3: Implement minimal service**

In `self_improvement_apply_service.py`, add:

```python
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


class SelfImprovementApplyError(Exception):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True)
class SelfImprovementApplyResult:
    path: str
    content_sha256: str
    already_present: bool
    bytes_written: int

    def to_dict(self) -> dict[str, str | bool | int]:
        return {
            "path": self.path,
            "content_sha256": self.content_sha256,
            "already_present": self.already_present,
            "bytes_written": self.bytes_written,
        }
```

Add `hash_apply_candidate_content(content: str) -> str` and `apply_project_memory_proposal(...) -> SelfImprovementApplyResult`.

The apply function must:

- require `proposal.status == "accepted"`;
- require `proposal.target_kind == "project_memory"`;
- rebuild the dry-run plan and select the single `append_markdown` candidate;
- reject when `reviewed_content_sha256` differs from the rebuilt content hash;
- require an existing `project_repo_path`;
- append to `.agent-collab/team_notes.md`;
- skip duplicate writes when `<!-- self-improvement-proposal:{proposal.id} -->` is already present;
- trim with `project_memory.trim_to_cap(...)` before writing.

- [ ] **Step 4: Run service tests and verify GREEN**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_self_improvement_apply_service.py -v
```

Expected: service tests pass.

### Task 2: HTTP Endpoint

**Files:**
- Modify: `backend/tests/test_self_improvement_api.py`
- Modify: `backend/app/interfaces/api.py`

- [ ] **Step 1: Write failing API tests**

Add tests for:

- accepted `project_memory` proposal + matching hash appends memory and returns `proposal.status == "applied"`;
- duplicate apply does not duplicate the marker;
- mismatched hash returns `409` and writes nothing;
- non-memory target returns `409`;
- non-accepted statuses return `409`;
- missing/cross-project proposal returns `404`;
- unavailable store returns `503`;
- unusable repo path returns `500` and leaves the proposal accepted.

- [ ] **Step 2: Run API tests and verify RED**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_self_improvement_api.py -v
```

Expected: `/apply` route returns `404` or imports are missing.

- [ ] **Step 3: Implement endpoint**

Add request model near the status update request:

```python
class SelfImprovementProposalApplyRequest(BaseModel):
    content_sha256: str = Field(min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")
```

Add route:

```python
@router.post("/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/apply")
async def codex_project_self_improvement_proposal_apply(
    project_id: str,
    proposal_id: str,
    request: SelfImprovementProposalApplyRequest,
):
    ...
```

The route should load project and proposal with the same `503`/`404` checks as
`apply-plan`, call `apply_project_memory_proposal(...)`, then call
`codex_store.update_self_improvement_proposal_status(proposal_id, "applied")`.
Map service errors by code:

- `invalid_status`, `unsupported_target`, `hash_mismatch` -> `409`;
- `repo_unavailable` -> `500`.

Return:

```python
{
    "proposal": _self_improvement_proposal_to_dict(updated),
    "application": result.to_dict(),
}
```

- [ ] **Step 4: Run API tests and verify GREEN**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_self_improvement_api.py -v
```

Expected: API tests pass.

### Task 3: Specs And Verification

**Files:**
- Modify: `.trellis/spec/vibe-kanban/backend/database-guidelines.md`

- [ ] **Step 1: Update backend self-improvement contract**

Document the reviewed apply API:

- signature and request/response shape;
- hash-gated project-memory-only behavior;
- error matrix;
- idempotent duplicate marker behavior;
- explicit bad case for applying non-memory targets or applying without a reviewed content hash.

- [ ] **Step 2: Run focused and broad checks**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_self_improvement_apply_service.py tests/test_self_improvement_api.py -v
.venv/bin/python -m pytest -v
.venv/bin/python -m ruff check .
.venv/bin/python -c "from app.main import app; print(bool(app))"
```

Expected: tests and import smoke pass. If ruff is unavailable, record the exact error.

- [ ] **Step 3: Diff hygiene**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; dirty files are only this task's planned files.

### Self-Review

Spec coverage:

- PRD requirements map to Task 1 service tests, Task 2 endpoint tests, and Task 3 spec updates.
- No schema migration is needed because application metadata is returned in the response and proposal status already exists.
- Higher-risk targets remain out of scope and conflict instead of writing files.

Placeholder scan: no TBD/TODO placeholders are present.

Type consistency:

- `content_sha256` is the request field.
- `SelfImprovementApplyResult.to_dict()` is the API response source.
- Service errors use `code` strings that the HTTP route maps at the boundary.
