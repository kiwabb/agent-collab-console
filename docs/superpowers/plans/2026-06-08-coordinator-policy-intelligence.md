# Coordinator Policy Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic Conductor scheduling-policy layer that steers trivial, ambiguous, risky, and explicitly parallel issues before the LLM dispatches agents.

**Architecture:** Put pure classification and rendering in a new `backend/app/application/conductor_policy.py` module, then inject the rendered block from `build_issue_conductor_prompt(...)`. Keep runtime dispatch behavior unchanged in this MVP; this phase guides the Conductor and gives us a tested policy surface.

**Tech Stack:** Python 3.13, dataclasses, pytest, existing Conductor prompt helpers.

---

### Task 1: Policy Classifier

**Files:**
- Create: `backend/app/application/conductor_policy.py`
- Test: `backend/tests/test_conductor_policy.py`

- [x] **Step 1: Write failing tests**

```python
from app.application.conductor_policy import classify_issue_orchestration


def test_trivial_single_file_prefers_single_engineer():
    policy = classify_issue_orchestration(
        "Fix typo",
        "Change one string in README.md.",
    )
    assert policy.recommendation == "single_engineer"
    assert policy.batch_allowed is False
    assert "trivial" in policy.signals


def test_explicit_parallel_independent_slices_allows_batch():
    policy = classify_issue_orchestration(
        "Create three independent modules in parallel",
        "Create module_a.py, module_b.py, module_c.py. Dispatch all three engineers in parallel as one batch.",
    )
    assert policy.recommendation == "batch_allowed"
    assert policy.batch_allowed is True
    assert "explicit_parallel" in policy.signals
    assert "independent_slices" in policy.signals
```

- [x] **Step 2: Run tests and confirm failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_conductor_policy.py -v`

Expected: import failure because `conductor_policy.py` does not exist.

- [x] **Step 3: Implement classifier**

Create a frozen dataclass `OrchestrationPolicy` with `recommendation`, `batch_allowed`, `signals`, and `guidance`. Implement keyword-based classification for explicit parallel, trivial, ambiguity, risk, and independent slices.

- [x] **Step 4: Run focused tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_conductor_policy.py -v`

Expected: all classifier tests pass.

### Task 2: Prompt Injection

**Files:**
- Modify: `backend/app/application/conductor_main_loop.py`
- Test: existing/new assertions in `backend/tests/test_conductor_policy.py`

- [x] **Step 1: Add prompt test**

```python
from types import SimpleNamespace
from app.application.conductor_main_loop import build_issue_conductor_prompt


def test_prompt_includes_orchestration_policy_block():
    prompt = build_issue_conductor_prompt(
        issue=SimpleNamespace(title="Fix typo", description="Change one string in README.md."),
        project_context="",
        budget_context="",
        language_directive="",
    )
    assert "## ORCHESTRATION POLICY" in prompt
    assert "Recommended default: single engineer" in prompt
    assert "Do not use dispatch_batch" in prompt
```

- [x] **Step 2: Run test and confirm failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_conductor_policy.py::test_prompt_includes_orchestration_policy_block -v`

Expected: assertion failure because prompt has no policy block.

- [x] **Step 3: Inject rendered policy**

Import `render_orchestration_policy_block` and include it in `build_issue_conductor_prompt(...)` after project/budget context and before `## Your Job`.

- [x] **Step 4: Run focused tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_conductor_policy.py -v`

Expected: classifier and prompt tests pass.

### Task 3: Regression Lane

**Files:**
- No new production files unless tests reveal a defect.

- [x] **Step 1: Run related Conductor tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_conductor_policy.py tests/test_conductor_dispatch_batch.py tests/test_dispatch_batch_budget_concurrency.py -v`

Expected: all pass.

- [x] **Step 2: Run import smoke**

Run: `cd backend && .venv/bin/python -c "from app.main import app"`

Expected: exit code 0.

---

## Self-Review

- PRD requirement 1 maps to Task 1.
- PRD requirement 2 maps to Task 2.
- PRD policy defaults map to classifier test cases and rendered guidance.
- Existing budget and dispatch runtime behavior remain unchanged; Task 3 covers related dispatch/budget regressions.
