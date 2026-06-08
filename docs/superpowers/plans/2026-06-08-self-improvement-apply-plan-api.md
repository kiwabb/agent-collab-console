# Self-Improvement Apply Plan API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dry-run API that turns accepted self-improvement proposals into structured apply plans without mutating files or proposal status.

**Architecture:** Put deterministic plan construction in `backend/app/application/self_improvement_apply_service.py`, then expose it through a project-scoped FastAPI endpoint beside the existing proposal routes. The API owns HTTP validation and project scoping; the service owns target-kind-specific plan shape.

**Tech Stack:** FastAPI, Pydantic v2 request/response dictionaries, pytest.

---

### Task 1: Apply Plan Builder

**Files:**
- Create: `backend/app/application/self_improvement_apply_service.py`
- Create: `backend/tests/test_self_improvement_apply_service.py`

- [ ] **Step 1: Write failing service tests**

Add tests proving:
- `project_memory` proposals produce a `.agent-collab/team_notes.md` append-markdown candidate.
- non-memory proposals produce an `open_pr_task` candidate, not a direct file patch.

Run:

```bash
python3 -m pytest backend/tests/test_self_improvement_apply_service.py -q
```

Expected: fail because `app.application.self_improvement_apply_service` does not exist.

- [ ] **Step 2: Implement minimal service**

Create `build_self_improvement_apply_plan(proposal) -> dict` with `mode`, `target_kind`, `can_auto_apply`, `summary`, `steps`, `candidate_changes`, `risk`, and `next_action`.

- [ ] **Step 3: Verify service tests pass**

Run:

```bash
python3 -m pytest backend/tests/test_self_improvement_apply_service.py -q
```

Expected: pass.

### Task 2: API Endpoint

**Files:**
- Modify: `backend/app/interfaces/api.py`
- Modify: `backend/tests/test_self_improvement_api.py`

- [ ] **Step 1: Write failing API tests**

Add tests proving:
- accepted `project_memory` proposal returns dry-run plan with proposal payload.
- accepted non-memory proposal returns PR/task plan.
- `proposed`, `rejected`, and `applied` return `409`.
- unknown/cross-project proposal returns `404`.
- `codex_store is None` returns `503`.
- endpoint does not change proposal status.

Run:

```bash
python3 -m pytest backend/tests/test_self_improvement_api.py -q
```

Expected: fail because the route does not exist.

- [ ] **Step 2: Implement endpoint**

Add `POST /api/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/apply-plan`. Reuse `_self_improvement_proposal_to_dict`, `load_project`, and `load_self_improvement_proposal`. Require `proposal.status == "accepted"` and call `build_self_improvement_apply_plan`.

- [ ] **Step 3: Verify API tests pass**

Run:

```bash
python3 -m pytest backend/tests/test_self_improvement_api.py -q
```

Expected: pass.

### Task 3: Spec And Verification

**Files:**
- Modify: `.trellis/spec/vibe-kanban/backend/database-guidelines.md`

- [ ] **Step 1: Update backend contract**

Extend the self-improvement proposal ledger section with the apply-plan endpoint, dry-run response contract, and non-mutation guarantees.

- [ ] **Step 2: Run verification**

Run:

```bash
python3 -m pytest backend/tests/test_self_improvement_apply_service.py backend/tests/test_self_improvement_api.py backend/tests/test_self_improvement_store.py backend/tests/test_self_improvement_service.py backend/tests/test_self_improvement_seal.py -q
python3 -m py_compile backend/app/application/self_improvement_apply_service.py backend/app/interfaces/api.py
cd backend && python3 -c "from app.main import app; print(app is not None)"
git diff --check
```

Expected: all commands pass. If `ruff` is unavailable locally, record that rather than claiming lint passed.
