# Self-Improvement Proposal Review API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe backend status-review API for self-improvement proposals.

**Architecture:** Keep proposal review status transitions at the HTTP boundary, and keep stores as typed persistence helpers. The API verifies the project, loads the proposal, enforces the transition matrix, updates only `status` and `updated_at`, then returns the existing proposal serialization shape.

**Tech Stack:** FastAPI, Pydantic v2, async/sync SQLite stores, pytest.

---

### Task 1: Store Load And Status Update

**Files:**
- Modify: `backend/tests/test_self_improvement_store.py`
- Modify: `backend/app/adapters/async_sqlite_store.py`
- Modify: `backend/app/adapters/sqlite_store.py`

- [ ] **Step 1: Write failing store tests**

Add tests that save a proposal, load it by id, update its status, and assert every non-status field is preserved while `updated_at` advances.

Run:

```bash
python3 -m pytest backend/tests/test_self_improvement_store.py -q
```

Expected: fail because `load_self_improvement_proposal` and `update_self_improvement_proposal_status` do not exist.

- [ ] **Step 2: Implement minimal store methods**

Add `load_self_improvement_proposal(proposal_id: str)` and `update_self_improvement_proposal_status(proposal_id: str, status: str)` to both stores. Each method selects named columns, maps rows to `SelfImprovementProposal`, and updates only `status` plus `updated_at`.

- [ ] **Step 3: Verify store tests pass**

Run:

```bash
python3 -m pytest backend/tests/test_self_improvement_store.py -q
```

Expected: pass.

### Task 2: PATCH Review Endpoint

**Files:**
- Modify: `backend/tests/test_self_improvement_api.py`
- Modify: `backend/app/interfaces/api.py`

- [ ] **Step 1: Write failing API tests**

Add tests for:
- `proposed -> accepted`
- `proposed -> rejected`
- `accepted -> applied`
- idempotent repeat of the current status
- invalid `rejected -> accepted` returns `409`
- unknown project/proposal returns `404`

Run:

```bash
python3 -m pytest backend/tests/test_self_improvement_api.py -q
```

Expected: fail because the PATCH route does not exist.

- [ ] **Step 2: Implement API transition guard**

Add a Pydantic body with `status: Literal["proposed", "accepted", "rejected", "applied"]`, a small transition helper, and `PATCH /api/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}`. The endpoint must return `503` when the store is unavailable, `404` for unknown project/proposal or cross-project proposals, and `409` for illegal transitions.

- [ ] **Step 3: Verify API tests pass**

Run:

```bash
python3 -m pytest backend/tests/test_self_improvement_api.py -q
```

Expected: pass.

### Task 3: Contract Documentation And Verification

**Files:**
- Modify: `.trellis/spec/vibe-kanban/backend/database-guidelines.md`

- [ ] **Step 1: Update backend contract**

Extend the review-only proposal ledger section with the new store methods, PATCH API, transition matrix, and the guarantee that status review does not mutate memory, specs, policies, tools, or code.

- [ ] **Step 2: Run focused verification**

Run:

```bash
python3 -m pytest backend/tests/test_self_improvement_store.py backend/tests/test_self_improvement_api.py backend/tests/test_self_improvement_service.py backend/tests/test_self_improvement_seal.py -q
python3 -m py_compile backend/app/interfaces/api.py backend/app/adapters/async_sqlite_store.py backend/app/adapters/sqlite_store.py
cd backend && python3 -c "from app.main import app; print(app is not None)"
git diff --check
```

Expected: all commands pass. If `ruff` is unavailable locally, record that rather than pretending lint ran.
