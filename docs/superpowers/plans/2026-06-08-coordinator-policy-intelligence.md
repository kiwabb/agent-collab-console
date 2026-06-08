# Coordinator Policy Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a conservative, testable Conductor policy layer that records why a Conductor turn should call or skip the LLM and turns repeated routing failures into review-only self-improvement proposals.

**Architecture:** Create a pure `conductor_policy` application module with stable reason codes, wire it into `run_issue_conductor_loop(...)` as best-effort evidence before the LLM loop, and extend `self_improvement_service` to classify Conductor policy failures. Keep policy mutations review-only; failures fall back to today's Conductor behavior.

**Tech Stack:** Python dataclasses, FastAPI backend application layer, existing Conductor turn/event persistence, pytest async tests, SQLite-backed proposal ledger.

---

## File Structure

- Create `backend/app/application/conductor_policy.py`
  - Owns `ConductorPolicyDecision`, `decide_conductor_policy(...)`,
    `render_conductor_policy_hint(...)`, and compact evidence helpers.
- Modify `backend/app/application/conductor_main_loop.py`
  - Loads recent conductor turns and workflow graph best-effort.
  - Records a `policy_decision` turn/event.
  - Injects `## POLICY HINT` when the decision is `call_llm` with a prompt hint.
  - Uses a safe LLM fallback for narrow `skip_llm` decisions so the LLM callable is not invoked.
- Modify `backend/app/application/self_improvement_service.py`
  - Adds `conductor_policy` proposal extraction for repeated routing/policy failures.
- Add `backend/tests/test_conductor_policy.py`
  - Pure policy tests.
- Update `backend/tests/test_run_issue_conductor_loop.py`
  - Integration tests for policy recording, prompt hint injection, and safe skip.
- Update `backend/tests/test_self_improvement_service.py`
  - Proposal extraction tests for conductor policy evidence.
- Update `.trellis/tasks/06-08-coordinator-policy-intelligence/prd.md`
  - Mark acceptance criteria complete after implementation and verification.

---

### Task 1: Pure Conductor Policy Classifier

**Files:**
- Create: `backend/app/application/conductor_policy.py`
- Test: `backend/tests/test_conductor_policy.py`

- [ ] **Step 1: Write failing tests for first turn, risky evidence, and safe skip**

```python
from datetime import datetime

from app.application.conductor_policy import decide_conductor_policy
from app.domain.models import CodexIssue, ConductorTask, ConductorTurn


def _issue():
    return CodexIssue(
        id="issue-1",
        session_id="session-1",
        project_id="project-1",
        title="Add endpoint",
        description="Return JSON",
        status="in_progress",
        created_at=datetime(2026, 6, 8, 10, 0, 0),
        updated_at=datetime(2026, 6, 8, 10, 0, 0),
    )


def _task():
    return ConductorTask(
        id="ct-1",
        project_id="project-1",
        issue_id="issue-1",
        task_kind="issue",
        status="running",
        payload={"phase": "awaiting_llm"},
        created_at=datetime(2026, 6, 8, 10, 0, 0),
        updated_at=datetime(2026, 6, 8, 10, 0, 0),
    )


def _turn(kind, payload, index=0):
    return ConductorTurn(
        id=f"turn-{index}",
        conductor_task_id="ct-1",
        issue_id="issue-1",
        turn_index=index,
        sub_index=0,
        kind=kind,
        payload_json=payload,
        created_at=datetime(2026, 6, 8, 10, 0, 0),
    )


def test_first_turn_calls_llm():
    decision = decide_conductor_policy(_issue(), _task(), recent_turns=[], graph=None)
    assert decision.action == "call_llm"
    assert decision.reason_code == "first_decision"


def test_risky_tool_result_calls_llm_with_hint():
    decision = decide_conductor_policy(
        _issue(),
        _task(),
        recent_turns=[
            _turn(
                "tool_result",
                '{"name":"dispatch_subagent","result":{"status":"retries_exhausted","role":"engineer"}}',
            )
        ],
        graph=None,
    )
    assert decision.action == "call_llm"
    assert decision.reason_code == "role_retries_exhausted"
    assert "engineer" in decision.prompt_hint


def test_repeated_low_signal_finalize_skips_llm():
    decision = decide_conductor_policy(
        _issue(),
        _task(),
        recent_turns=[
            _turn("finalize", '{"status":"done","answer":"already complete"}', index=0),
            _turn("finalize", '{"status":"done","answer":"already complete"}', index=1),
        ],
        graph=None,
    )
    assert decision.action == "skip_llm"
    assert decision.reason_code == "recent_safe_finalize"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=backend ../backend/.venv/bin/python -m pytest backend/tests/test_conductor_policy.py -q
```

Expected: FAIL because `app.application.conductor_policy` does not exist.

- [ ] **Step 3: Implement minimal classifier**

Create `backend/app/application/conductor_policy.py` with:

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ConductorPolicyDecision:
    action: str
    reason_code: str
    reason: str
    prompt_hint: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "prompt_hint": self.prompt_hint,
            "evidence": self.evidence,
        }


def _payload(turn: object) -> dict[str, Any]:
    raw = getattr(turn, "payload_json", None)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": str(raw)}
    return data if isinstance(data, dict) else {"value": data}


def decide_conductor_policy(issue, conductor_task, *, recent_turns: list[object], graph=None, budget_status=None) -> ConductorPolicyDecision:
    if not recent_turns:
        return ConductorPolicyDecision(
            action="call_llm",
            reason_code="first_decision",
            reason="No recent conductor turns exist; the initial decision needs the Conductor LLM.",
        )
    for turn in reversed(recent_turns[-8:]):
        if getattr(turn, "kind", "") != "tool_result":
            continue
        payload = _payload(turn)
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        status = str(result.get("status") or "").lower()
        role = str(result.get("role") or payload.get("role") or "")
        if status == "retries_exhausted":
            return ConductorPolicyDecision(
                action="call_llm",
                reason_code="role_retries_exhausted",
                reason=f"Role {role or 'unknown'} exhausted its dispatch budget.",
                prompt_hint=f"Role {role or 'unknown'} already exhausted its dispatch budget; do not redispatch it. Choose a different role, ask the user, or finalize blocked work.",
                evidence=[{"kind": "turn", "id": getattr(turn, "id", None), "status": status, "role": role}],
            )
    finalize_count = sum(
        1
        for turn in recent_turns[-3:]
        if getattr(turn, "kind", "") == "finalize" and str(_payload(turn).get("status") or "").lower() == "done"
    )
    if finalize_count >= 2:
        return ConductorPolicyDecision(
            action="skip_llm",
            reason_code="recent_safe_finalize",
            reason="Recent conductor evidence already finalized successfully; avoid a redundant LLM turn.",
            evidence=[{"kind": "recent_finalize_count", "count": finalize_count}],
        )
    return ConductorPolicyDecision(
        action="call_llm",
        reason_code="default_call_llm",
        reason="No conservative skip rule matched.",
    )


def render_conductor_policy_hint(decision: ConductorPolicyDecision) -> str:
    if decision.action != "call_llm" or not decision.prompt_hint:
        return ""
    return f"\n\n## POLICY HINT\nReason: {decision.reason_code}\n{decision.prompt_hint}"
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
PYTHONPATH=backend ../backend/.venv/bin/python -m pytest backend/tests/test_conductor_policy.py -q
```

Expected: PASS.

---

### Task 2: Wire Policy Evidence Into Conductor Loop

**Files:**
- Modify: `backend/app/application/conductor_main_loop.py`
- Test: `backend/tests/test_run_issue_conductor_loop.py`

- [ ] **Step 1: Add failing integration tests**

Add tests that:

1. Patch `decide_conductor_policy` to return `call_llm` with `prompt_hint`.
2. Assert the prompt passed to `call_conductor_llm` contains `## POLICY HINT`.
3. Assert a `policy_decision` turn/event is recorded.
4. Patch `decide_conductor_policy` to return `skip_llm`.
5. Assert `call_conductor_llm` is not called and the loop returns `done`.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=backend ../backend/.venv/bin/python -m pytest backend/tests/test_run_issue_conductor_loop.py -q
```

Expected: FAIL because policy decision is not wired.

- [ ] **Step 3: Implement best-effort policy collection and prompt hint**

In `run_issue_conductor_loop(...)`:

- Import `ConductorPolicyDecision`, `decide_conductor_policy`, and
  `render_conductor_policy_hint`.
- Add helpers that load recent turns if the store exposes
  `list_conductor_turns`, else return `[]`.
- Before building the final prompt, compute a policy decision best-effort.
- Append `render_conductor_policy_hint(decision)` to the prompt.
- Record a `policy_decision` turn via `persist_turn(...)` after
  `persist_turn` is defined and before `run_conductor_loop(...)`.
- If `decision.action == "skip_llm"`, use an LLM callable that immediately
  returns a `finalize_task` tool use with answer `decision.reason`.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
PYTHONPATH=backend ../backend/.venv/bin/python -m pytest backend/tests/test_run_issue_conductor_loop.py -q
```

Expected: PASS.

---

### Task 3: Extract Conductor Policy Self-Improvement Proposals

**Files:**
- Modify: `backend/app/application/self_improvement_service.py`
- Test: `backend/tests/test_self_improvement_service.py`

- [ ] **Step 1: Add failing tests for conductor policy proposals**

Add tests using `MemoryStore` and `_task(...)` fixtures:

```python
@pytest.mark.asyncio
async def test_retries_exhausted_creates_conductor_policy_proposal():
    store = MemoryStore(
        tasks=[
            _task(
                "task-1",
                result_json={
                    "tool_events": [
                        {
                            "name": "dispatch_subagent",
                            "result": {"status": "retries_exhausted", "role": "engineer"},
                        }
                    ]
                },
            )
        ]
    )

    proposals = await extract_self_improvement_proposals(_issue(), store)

    policy = [p for p in proposals if p.target_kind == "conductor_policy"]
    assert len(policy) == 1
    assert policy[0].fingerprint == "project-1|issue-1|conductor_policy|role_retries_exhausted"
    assert "engineer" in policy[0].evidence_json
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
PYTHONPATH=backend ../backend/.venv/bin/python -m pytest backend/tests/test_self_improvement_service.py::test_retries_exhausted_creates_conductor_policy_proposal -q
```

Expected: FAIL because no `conductor_policy` proposal is emitted.

- [ ] **Step 3: Implement proposal extraction**

In `_classify_tasks(...)`, parse `tool_events` from task result JSON and create
proposals for:

- `status == "retries_exhausted"` -> rule `role_retries_exhausted`.
- `status == "role_busy"` -> rule `role_busy_loop`.
- `merge_status == "conflict"` -> rule `dispatch_batch_conflict`.
- `status == "artifact_invalid"` -> rule `artifact_invalid_loop`.

Use `_proposal(...)` with `target_kind="conductor_policy"`, severity `medium`,
confidence `0.78`, and evidence from `_task_evidence(...)`.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
PYTHONPATH=backend ../backend/.venv/bin/python -m pytest backend/tests/test_self_improvement_service.py -q
```

Expected: PASS.

---

### Task 4: Focused Verification and Task PRD Update

**Files:**
- Modify: `.trellis/tasks/06-08-coordinator-policy-intelligence/prd.md`

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
PYTHONPATH=backend ../backend/.venv/bin/python -m pytest \
  backend/tests/test_conductor_policy.py \
  backend/tests/test_run_issue_conductor_loop.py \
  backend/tests/test_self_improvement_service.py \
  backend/tests/test_self_improvement_store.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Update PRD acceptance checkboxes**

Mark accepted criteria complete only after the focused tests pass.

- [ ] **Step 3: Commit implementation**

Run:

```bash
git add backend/app/application/conductor_policy.py \
  backend/app/application/conductor_main_loop.py \
  backend/app/application/self_improvement_service.py \
  backend/tests/test_conductor_policy.py \
  backend/tests/test_run_issue_conductor_loop.py \
  backend/tests/test_self_improvement_service.py \
  .trellis/tasks/06-08-coordinator-policy-intelligence/prd.md
git commit -m "feat: add conductor policy intelligence"
```
