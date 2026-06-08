# Self Improvement Benchmark Eval Proposals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic review-only `benchmark_eval` proposal extraction for capability issues that lack benchmark or evaluation evidence.

**Architecture:** Keep extraction inside `backend/app/application/self_improvement_service.py` and reuse the existing proposal ledger, fingerprint, evidence, and save path. Detect capability intent from issue/task text, detect actual benchmark evidence from task payload/results, and emit a single idempotent `benchmark_eval` proposal only when evidence is missing.

**Tech Stack:** Python 3.13, pytest async tests, existing FastAPI/SQLite self-improvement proposal domain models.

---

## File Structure

- Modify `backend/tests/test_self_improvement_service.py` for RED service extraction coverage.
- Modify `backend/app/application/self_improvement_service.py` for deterministic capability/eval classification helpers.
- Modify `backend/tests/test_self_improvement_apply_service.py` for explicit `benchmark_eval` open-PR apply-plan coverage.
- Modify `.trellis/spec/vibe-kanban/backend/database-guidelines.md` and `docs/superpowers/specs/2026-06-08-self-improvement-loop-design.md` to capture the executable extraction contract.

### Task 1: Baseline And RED Service Tests

**Files:**
- Modify: `backend/tests/test_self_improvement_service.py`

- [ ] **Step 1: Run focused baseline**

Run:

```bash
cd backend && python3 -m pytest tests/test_self_improvement_service.py tests/test_self_improvement_apply_service.py tests/test_self_improvement_api.py -v
```

Expected: Existing tests pass before changing behavior.

- [ ] **Step 2: Add failing extraction tests**

Add tests for these behaviors:

```python
@pytest.mark.asyncio
async def test_capability_issue_without_eval_evidence_creates_benchmark_eval_proposal():
    ...
    assert proposal.target_kind == "benchmark_eval"
    assert proposal.fingerprint == "project-1|issue-1|benchmark_eval|missing_capability_eval_contract"
    assert '"codex_issue"' in proposal.evidence_json
    assert '"conductor_task"' in proposal.evidence_json


@pytest.mark.asyncio
async def test_capability_issue_with_eval_evidence_does_not_create_benchmark_eval_proposal():
    ...
    assert proposals == []


@pytest.mark.asyncio
async def test_duplicate_benchmark_eval_matches_save_once_per_issue_rule():
    ...
    assert len(proposals) == 1
```

- [ ] **Step 3: Verify RED**

Run:

```bash
cd backend && python3 -m pytest tests/test_self_improvement_service.py -v
```

Expected: New `benchmark_eval` tests fail because no proposal is emitted yet.

### Task 2: Implement Benchmark Eval Classification

**Files:**
- Modify: `backend/app/application/self_improvement_service.py`

- [ ] **Step 1: Add issue and search helpers**

Add helpers for issue evidence, task payload/result search text, and deterministic keyword matching.

- [ ] **Step 2: Add conservative detection terms**

Capability terms include `capability`, `autonomy`, `autonomous`, `solve rate`, `solve-rate`, `solver`, `swe-bench`, `swebench`, `pass@`, `pass_at`, and `leaderboard`.

Benchmark evidence terms include `benchmark_run`, `benchmark fixture`, `fixture_id`, `pass_at_1`, `pass@1`, `calibration`, `eval run`, `evaluation run`, `benchmark artifact`, and `backend/benchmark`.

- [ ] **Step 3: Emit one task-list-level proposal**

When tasks exist, capability intent is present, and no task payload/result contains benchmark evidence, emit:

```python
target_kind = "benchmark_eval"
rule_id = "missing_capability_eval_contract"
title = "Add benchmark coverage for capability issue"
severity = "medium"
confidence = 0.76
```

Recommendation:

```text
Create or update a reviewed benchmark fixture/eval for this capability issue, attach the run artifact, and use the result as acceptance evidence before repeating similar capability work.
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
cd backend && python3 -m pytest tests/test_self_improvement_service.py -v
```

Expected: All service extraction tests pass.

### Task 3: Apply-Plan Coverage

**Files:**
- Modify: `backend/tests/test_self_improvement_apply_service.py`

- [ ] **Step 1: Add explicit benchmark eval apply-plan test**

Add a test asserting `benchmark_eval` returns `open_pr_task`, `next_action == "open_reviewed_pr"`, and no `patch_file` candidate.

- [ ] **Step 2: Verify apply-plan tests**

Run:

```bash
cd backend && python3 -m pytest tests/test_self_improvement_apply_service.py -v
```

Expected: All apply-plan tests pass without production apply-service changes.

### Task 4: Spec Contract Update

**Files:**
- Modify: `.trellis/spec/vibe-kanban/backend/database-guidelines.md`
- Modify: `docs/superpowers/specs/2026-06-08-self-improvement-loop-design.md`

- [ ] **Step 1: Add benchmark-eval extraction contract**

Update the Review-Only Self-Improvement Proposal Ledger scenario:

- Contracts: capability issues without task-level benchmark/eval evidence create one `benchmark_eval` proposal.
- Validation matrix: explicit benchmark/eval evidence suppresses redundant proposal.
- Good/Base/Bad: include good missing-eval case and bad issue-title-as-evidence case.
- Tests Required: include extraction and apply-plan tests.

- [ ] **Step 2: Verify docs diff**

Run:

```bash
git diff -- .trellis/spec/vibe-kanban/backend/database-guidelines.md docs/superpowers/specs/2026-06-08-self-improvement-loop-design.md
```

Expected: The spec captures executable behavior, not vague aspirations.

### Task 5: Final Verification

**Files:**
- No new edits unless verification finds a defect.

- [ ] **Step 1: Run focused suite**

```bash
cd backend && python3 -m pytest tests/test_self_improvement_service.py tests/test_self_improvement_apply_service.py tests/test_self_improvement_api.py -v
```

- [ ] **Step 2: Run backend suite**

```bash
cd backend && python3 -m pytest -v
```

- [ ] **Step 3: Run compile/import/lint checks**

```bash
cd backend && python3 -m compileall -q app
cd backend && python3 -c "from app.main import app; print(bool(app))"
cd backend && python3 -m ruff check .
git diff --check
```

Expected: pytest, compileall, app import, and diff whitespace checks pass. If `ruff` is unavailable, record the exact command failure.
