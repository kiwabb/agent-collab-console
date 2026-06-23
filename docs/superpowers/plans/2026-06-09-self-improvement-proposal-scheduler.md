# Self-Improvement Proposal Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically activate and start accepted non-memory self-improvement proposals from a backend scheduler.

**Architecture:** Add a small application-layer scheduler mirroring `project_review_scheduler`: a pure tick scans accepted proposals, skips unsafe/already-started rows, calls an injected activation function with `start_conductor=True`, and records a status snapshot. Wire that loop into lifespan and diagnostics through the same supervisor-check path used by the project review scheduler.

**Tech Stack:** Python 3.13+, FastAPI lifespan, asyncio, Pydantic/domain dataclasses, pytest.

---

## File Map

- Create `backend/app/application/self_improvement_proposal_scheduler.py`
  - Scheduler protocols, result/summary dataclasses, status snapshot, tick, loop.
- Create `backend/tests/test_self_improvement_proposal_scheduler.py`
  - Unit tests for tick selection, failure isolation, limits, loop/status behavior.
- Modify `backend/app/application/timeouts.py`
  - Add scheduler interval/limit defaults and accessors.
- Modify `backend/tests/test_timeouts.py`
  - Add defaults/env/fallback coverage for new knobs.
- Modify `backend/app/interfaces/api.py`
  - Add diagnostics snapshot/check.
  - Extract endpoint body into a reusable activation helper callable from lifespan/scheduler wiring.
- Modify `backend/tests/test_diagnostics_api.py`
  - Add snapshot/default checks and degraded states for the new scheduler.
- Modify `backend/app/main.py`
  - Start/cancel the new scheduler loop as a named background task.
- Modify `backend/tests/test_lifespan_shutdown.py`
  - Assert startup/shutdown handles `self-improvement-proposal-scheduler`.
- Modify `.trellis/spec/vibe-kanban/backend/database-guidelines.md`
  - Document the accepted-proposal scheduler contract and tests.

---

### Task 1: Scheduler Tick RED Tests

**Files:**
- Create: `backend/tests/test_self_improvement_proposal_scheduler.py`

- [ ] **Step 1: Write proposal/event helpers and first failing activation test**

```python
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from app.domain.models import SelfImprovementApplicationEvent, SelfImprovementProposal
from app.application.self_improvement_proposal_scheduler import run_self_improvement_proposal_tick


def _proposal(
    proposal_id: str,
    *,
    project_id: str = "project-1",
    target_kind: str = "runtime_tooling",
    status: str = "accepted",
) -> SelfImprovementProposal:
    return SelfImprovementProposal(
        id=proposal_id,
        project_id=project_id,
        issue_id=f"issue-{proposal_id}",
        target_kind=target_kind,
        title=f"Proposal {proposal_id}",
        recommendation="Open a follow-up task.",
        status=status,
        fingerprint=f"{project_id}|issue-{proposal_id}|{target_kind}|rule",
        created_at=datetime(2026, 6, 9, 9, 0, 0),
    )


def _event(
    proposal: SelfImprovementProposal,
    *,
    action: str = "start_conductor",
    status: str = "succeeded",
) -> SelfImprovementApplicationEvent:
    return SelfImprovementApplicationEvent(
        id=f"event-{proposal.id}",
        proposal_id=proposal.id,
        project_id=proposal.project_id,
        issue_id=proposal.issue_id,
        target_kind=proposal.target_kind,
        action=action,
        status=status,
        result_json="{}",
        created_at=datetime(2026, 6, 9, 9, 1, 0),
    )


class _Store:
    def __init__(self, proposals, events=None) -> None:
        self.proposals = list(proposals)
        self.events = events or {}
        self.list_calls = []

    async def list_self_improvement_proposals(self, *, project_id=None, issue_id=None, status=None, limit=None):
        self.list_calls.append({"project_id": project_id, "issue_id": issue_id, "status": status, "limit": limit})
        rows = [proposal for proposal in self.proposals if status is None or proposal.status == status]
        return rows[:limit] if limit is not None else rows

    async def list_self_improvement_application_events(self, *, project_id=None, proposal_id=None, limit=None):
        rows = list(self.events.get(proposal_id, []))
        return rows[:limit] if limit is not None else rows


@pytest.mark.asyncio
async def test_self_improvement_proposal_tick_activates_eligible_accepted_non_memory_proposals():
    proposal = _proposal("proposal-1")
    calls = []

    async def activate(project_id: str, proposal_id: str, *, start_conductor: bool):
        calls.append((project_id, proposal_id, start_conductor))
        return {"activation": {"conductor": {"started": True, "already_running": False}}}

    summary = await run_self_improvement_proposal_tick(_Store([proposal]), activate_fn=activate, limit=10)

    assert calls == [("project-1", "proposal-1", True)]
    assert summary.to_dict()["counts"] == {"started": 1}
    assert summary.results[0].proposal_id == "proposal-1"
```

- [ ] **Step 2: Run RED**

Run: `cd backend && python3 -m pytest tests/test_self_improvement_proposal_scheduler.py::test_self_improvement_proposal_tick_activates_eligible_accepted_non_memory_proposals -v`

Expected: import failure for `app.application.self_improvement_proposal_scheduler`.

---

### Task 2: Minimal Scheduler Module

**Files:**
- Create: `backend/app/application/self_improvement_proposal_scheduler.py`

- [ ] **Step 1: Implement dataclasses and tick enough to pass first test**

Implement:
- `SelfImprovementProposalSchedulerResult`
- `SelfImprovementProposalSchedulerSummary`
- `run_self_improvement_proposal_tick(...)`

Rules:
- Query `list_self_improvement_proposals(status="accepted", limit=limit)`.
- For each proposal, call `activate_fn(proposal.project_id, proposal.id, start_conductor=True)`.
- Status should be `"started"` when the activation payload has `activation.conductor.started == True`, `"already_running"` when `already_running == True`, otherwise `"activated"`.

- [ ] **Step 2: Run GREEN**

Run: `cd backend && python3 -m pytest tests/test_self_improvement_proposal_scheduler.py::test_self_improvement_proposal_tick_activates_eligible_accepted_non_memory_proposals -v`

Expected: pass.

---

### Task 3: Tick Filtering and Failure Isolation

**Files:**
- Modify: `backend/tests/test_self_improvement_proposal_scheduler.py`
- Modify: `backend/app/application/self_improvement_proposal_scheduler.py`

- [ ] **Step 1: Add RED tests**

Add tests:
- `test_self_improvement_proposal_tick_skips_project_memory`
- `test_self_improvement_proposal_tick_skips_already_started_proposals`
- `test_self_improvement_proposal_tick_isolates_activation_failures`
- `test_self_improvement_proposal_tick_honors_limit`

Expected statuses:
- `skipped_project_memory`
- `skipped_already_started`
- `failed`
- normal eligible status from Task 2.

- [ ] **Step 2: Run RED group**

Run: `cd backend && python3 -m pytest tests/test_self_improvement_proposal_scheduler.py -k "skips or isolates or honors" -v`

Expected: failures because filtering/failure logic is missing.

- [ ] **Step 3: Implement filtering/failure logic**

Rules:
- Skip `proposal.target_kind == "project_memory"`.
- Load application events with `project_id=proposal.project_id`, `proposal_id=proposal.id`, `limit=100`.
- Skip when any event has `action == "start_conductor"` and `status == "succeeded"`.
- Catch `Exception` per proposal, log `proposal_id` and `project_id`, append failed result, continue.
- Do not catch `asyncio.CancelledError`.

- [ ] **Step 4: Run GREEN group**

Run: `cd backend && python3 -m pytest tests/test_self_improvement_proposal_scheduler.py -k "skips or isolates or honors" -v`

Expected: pass.

---

### Task 4: Scheduler Loop and Status Snapshot

**Files:**
- Modify: `backend/tests/test_self_improvement_proposal_scheduler.py`
- Modify: `backend/app/application/self_improvement_proposal_scheduler.py`

- [ ] **Step 1: Add loop/status RED tests**

Mirror `test_project_review_scheduler.py`:
- loop repeats after each sleep;
- loop survives a tick exception;
- loop propagates cancellation from tick;
- status records successful tick;
- status records failed tick;
- status clears running on tick cancellation.

- [ ] **Step 2: Run RED**

Run: `cd backend && python3 -m pytest tests/test_self_improvement_proposal_scheduler.py -k "loop or status" -v`

Expected: failures for missing `run_self_improvement_proposal_scheduler_loop`, status reset/get helpers, and status dataclass.

- [ ] **Step 3: Implement loop/status**

Implement:
- `SelfImprovementProposalSchedulerStatus`
- `_scheduler_status`
- `reset_self_improvement_proposal_scheduler_status()`
- `get_self_improvement_proposal_scheduler_status()`
- `run_self_improvement_proposal_scheduler_loop(...)`

Use `timeouts.self_improvement_proposal_interval_s()` and
`timeouts.self_improvement_proposal_limit()`.

- [ ] **Step 4: Run GREEN**

Run: `cd backend && python3 -m pytest tests/test_self_improvement_proposal_scheduler.py -v`

Expected: all scheduler tests pass.

---

### Task 5: Timeout Knobs

**Files:**
- Modify: `backend/app/application/timeouts.py`
- Modify: `backend/tests/test_timeouts.py`

- [ ] **Step 1: Add RED timeout assertions**

Update default-value test and add a new test:

```python
def test_self_improvement_proposal_scheduler_knobs(monkeypatch):
    monkeypatch.setenv("SELF_IMPROVEMENT_PROPOSAL_INTERVAL_S", "222.5")
    monkeypatch.setenv("SELF_IMPROVEMENT_PROPOSAL_LIMIT", "9")
    assert timeouts.self_improvement_proposal_interval_s() == 222.5
    assert timeouts.self_improvement_proposal_limit() == 9

    monkeypatch.setenv("SELF_IMPROVEMENT_PROPOSAL_INTERVAL_S", "0")
    monkeypatch.setenv("SELF_IMPROVEMENT_PROPOSAL_LIMIT", "0")
    assert timeouts.self_improvement_proposal_interval_s() == timeouts.DEFAULT_SELF_IMPROVEMENT_PROPOSAL_INTERVAL_S
    assert timeouts.self_improvement_proposal_limit() == 1
```

- [ ] **Step 2: Run RED**

Run: `cd backend && python3 -m pytest tests/test_timeouts.py -k "self_improvement_proposal or default_values or invalid_env" -v`

Expected: missing accessor/default failures.

- [ ] **Step 3: Implement defaults/accessors**

Add defaults near project review scheduler knobs:
- `DEFAULT_SELF_IMPROVEMENT_PROPOSAL_INTERVAL_S = 3600.0`
- `DEFAULT_SELF_IMPROVEMENT_PROPOSAL_LIMIT = 25`
- `self_improvement_proposal_interval_s()`
- `self_improvement_proposal_limit()`

Add both to `timeout_values()`.

- [ ] **Step 4: Run GREEN**

Run: `cd backend && python3 -m pytest tests/test_timeouts.py -v`

Expected: pass.

---

### Task 6: Diagnostics

**Files:**
- Modify: `backend/app/interfaces/api.py`
- Modify: `backend/tests/test_diagnostics_api.py`

- [ ] **Step 1: Add RED diagnostics tests**

Add coverage analogous to project review scheduler:
- default snapshot includes `self_improvement_proposal_scheduler`;
- running state degrades;
- stale state degrades;
- recent/never-completed state does not degrade.

- [ ] **Step 2: Run RED**

Run: `cd backend && python3 -m pytest tests/test_diagnostics_api.py -k "self_improvement_proposal_scheduler or operational_snapshot" -v`

Expected: failures because diagnostics does not include the new snapshot/check.

- [ ] **Step 3: Wire diagnostics**

In `api.py`:
- import `get_self_improvement_proposal_scheduler_status`;
- append `_supervisor_status_check("self_improvement_proposal_scheduler", ...)`;
- include top-level response field.

Use generic details:
- running: `"Self-improvement proposal scheduler is running"`
- stale: `"Self-improvement proposal scheduler has not completed recently"`

- [ ] **Step 4: Run GREEN**

Run: `cd backend && python3 -m pytest tests/test_diagnostics_api.py -v`

Expected: pass.

---

### Task 7: API Helper and Lifespan Wiring

**Files:**
- Modify: `backend/app/interfaces/api.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_lifespan_shutdown.py`

- [ ] **Step 1: Add RED lifespan assertions**

Update `test_lifespan_recovers_conductors_and_runs_watchdog` to monkeypatch
`app.application.self_improvement_proposal_scheduler.run_self_improvement_proposal_scheduler_loop`
and assert:
- `"self-improvement-proposal-scheduler"` appears in created task names;
- that fake task is cancelled on shutdown.

- [ ] **Step 2: Run RED**

Run: `cd backend && python3 -m pytest tests/test_lifespan_shutdown.py -v`

Expected: failure because lifespan does not start the new task.

- [ ] **Step 3: Extract reusable activation helper**

In `api.py`, extract endpoint body to:

```python
async def activate_self_improvement_proposal_task(
    project_id: str,
    proposal_id: str,
    *,
    start_conductor: bool = False,
) -> dict:
    ...
```

The endpoint should parse the request body and return:

```python
return await activate_self_improvement_proposal_task(
    project_id,
    proposal_id,
    start_conductor=start_conductor,
)
```

- [ ] **Step 4: Wire lifespan**

In `main.py`:
- add `self_improvement_proposal_scheduler_task`;
- import scheduler loop and API activation helper;
- start the named task with `activate_fn=activate_self_improvement_proposal_task`;
- cancel/await it during shutdown.

- [ ] **Step 5: Run GREEN**

Run: `cd backend && python3 -m pytest tests/test_lifespan_shutdown.py tests/test_self_improvement_api.py -k "activate_task or lifespan" -v`

Expected: pass.

---

### Task 8: Spec Update and Final Verification

**Files:**
- Modify: `.trellis/spec/vibe-kanban/backend/database-guidelines.md`

- [ ] **Step 1: Update ledger scenario**

Document:
- scheduler trigger/scope;
- accepted-only, non-memory-only contract;
- already-started skip rule;
- no status mutation / no direct application;
- status/diagnostics fields;
- validation matrix and required tests.

- [ ] **Step 2: Run focused tests**

Run:

```bash
cd backend && python3 -m pytest \
  tests/test_self_improvement_proposal_scheduler.py \
  tests/test_self_improvement_api.py \
  tests/test_diagnostics_api.py \
  tests/test_lifespan_shutdown.py \
  tests/test_timeouts.py \
  -v
```

Expected: pass.

- [ ] **Step 3: Run backend quality checks**

Run:

```bash
cd backend && python3 -m pytest -v
cd backend && python3 -m compileall -q app
cd backend && python3 -c "from app.main import app; print(bool(app))"
cd backend && python3 -m ruff check .
git diff --check
```

Record exact `ruff` result if unavailable.

- [ ] **Step 4: Commit**

Commit:

```bash
git add \
  .trellis/tasks/06-09-self-improvement-proposal-scheduler \
  .trellis/spec/vibe-kanban/backend/database-guidelines.md \
  backend/app/application/self_improvement_proposal_scheduler.py \
  backend/app/application/timeouts.py \
  backend/app/interfaces/api.py \
  backend/app/main.py \
  backend/tests/test_self_improvement_proposal_scheduler.py \
  backend/tests/test_diagnostics_api.py \
  backend/tests/test_lifespan_shutdown.py \
  backend/tests/test_timeouts.py \
  docs/superpowers/plans/2026-06-09-self-improvement-proposal-scheduler.md
git commit -m "feat: schedule self-improvement proposal activation"
```
