# Agent quality loop — verification of candidate net-new sub-pieces

## Goal

Deepen the agent quality loop (Phase C). Before scoping, each candidate
sub-piece was verified against current code (the codebase is mature; prior
sessions over-reported gaps). This PRD records that verification first, then
converges on what — if anything — is genuinely net-new.

## Verification of the 4 candidates (2026-06-03, against current code)

### (1) Closed-loop self-heal (QA fail → auto engineer refine → re-QA) — ALREADY EXISTS ❌

- `qa_workflow.py:241` — a real command FAILURE forces `task.status="failed"`
  (never trusts the LLM self-report) and writes a failure narrative.
- `workflow_scheduler.on_task_completed` signals `TaskCompletionRegistry`; the
  **Conductor LLM** then decides the next move (re-dispatch engineer / clarify /
  finalize), informed by the QA failure narrative + `execution_results`.
- `conductor_tools._check_redispatch_budget` already provides a **bounded** rework
  loop (initial + a few reworks → `retries_exhausted`); `WorkflowNode.max_retries`.
- **Conclusion**: the self-heal loop exists, Conductor-LLM-mediated + bounded.
  Making it *deterministic / skip-the-LLM* would be an **anti-goal** — it
  violates the system's core "no fixed DAG, Conductor decides each step"
  philosophy. NOT a gap.

### (2) Auto test generation — PARTIAL gap ✅ (smaller than framed)

- The engineer role CAN be told to write tests (`engineer_workflow.py:232`
  `'实现单元测试' = Test code ONLY`), and QA runs `recommended_commands`.
- But there is **no systematic / automatic** test-generation step in the loop,
  and **no dedicated test-author specialist** (the 10 specialists are all
  reviewers: a11y / api-contract / code / dep / doc / i18n / log / migration /
  perf / security).
- **Conclusion**: genuine net-new, but scoped — the *capability* exists; the
  *systematic gating* into the quality loop does not.

### (3) Cross-issue learning upgrade — MOSTLY EXISTS ✅ (only retrieval is net-new)

- `project_memory_service` appends a **deterministic** (no-LLM) summary block per
  issue, and **already has `maybe_distill` / `needs_distillation`** — an LLM
  distillation that compresses accumulated blocks past a threshold.
- What is NOT present: **retrieval-based selective injection**. Today the whole
  `team_notes.md` is injected as "TEAM CONTEXT" into every role prompt; there is
  no per-issue relevance retrieval.
- **Conclusion**: modest net-new — only the retrieval/selection layer.

### (4) Wire specialist mesh into the Conductor main flow — ANTI-GOAL ❌

- `specialist_orchestrator.py:4` explicitly: specialists run "**without waiting
  for the Conductor**" via parent-pause / child-run / parent-resume, mesh depth
  ≤ 2, Engineer/QA self-triggered.
- This decoupling is **intentional** (avoids a Conductor round-trip for
  in-flight expert help). Routing it back through the Conductor would be a
  regression, not an enhancement. NOT a gap.

## Honest conclusion

Of the 4 candidates, **2 are non-gaps / anti-goals (1, 4)** and **2 are real but
modest (2 test-gen, 3 retrieval)**. "Phase C as a big net-new phase" does **not**
hold — the agent quality loop is already deep. This is the 3rd/4th confirmation
of the 2026-05-31 assessment that gap-filling big phases are exhausted.

→ Recommend NOT manufacturing a large phase. Either scope a focused, honest
mini-phase on (2) or (3), or pivot (e.g. D productization, or stop here).

## Open Questions

- (Q1) Given verification, scope a focused phase on (2) test-gen, (3) retrieval
  learning, pivot to D, or stop? — needs user decision.

## Out of Scope (explicit)

- Deterministic auto-rework that bypasses Conductor decision-making (anti-goal).
- Routing specialist mesh through the Conductor (anti-goal).

## Technical Notes

- `backend/app/application/qa_workflow.py:241` failure → failed status.
- `backend/app/application/workflow_scheduler.py:95` `on_task_completed` → registry signal → Conductor LLM decides.
- `backend/app/application/conductor_tools.py:18-90` `_check_redispatch_budget` bounded rework.
- `backend/app/application/engineer_workflow.py:232` engineer can write tests on instruction.
- `backend/app/application/project_memory_service.py:327-372` `needs_distillation` / `maybe_distill` LLM distillation already present.
- `backend/app/application/specialist_orchestrator.py:4` mesh intentionally bypasses Conductor.
