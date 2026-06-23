# Current Conductor Policy Baseline

## Evidence Inspected

- `backend/app/application/conductor_main_loop.py`
  - `build_issue_conductor_prompt(...)` owns the issue-level operating contract.
  - It already says to choose the smallest reliable workflow, skip PM when explicit,
    skip architect for tiny fixes, run engineer for code changes, run QA before
    success, and use `dispatch_batch` only for independent work.
  - It does not provide a deterministic preflight classification or an explicit
    fan-out decision rubric.
- `backend/app/application/conductor_tools.py`
  - `dispatch_batch` implements real parallel fan-out with isolated per-agent
    worktrees, per-role retry budget, upstream flush, batch graph tagging,
    partial join, sequential merge, conflict reporting, and cleanup paths.
  - Budget-aware concurrency can reduce the effective semaphore cap, but it does
    not decide whether a batch should exist in the first place.
- `backend/app/application/timeouts.py`
  - `MAX_PARALLEL_DISPATCH_PER_BATCH` caps batch width.
  - `budget_supported_concurrency(...)` only lowers concurrency under budget
    pressure; healthy budgets leave configured parallelism unchanged.
- Real issue `c13b189c-4da4-4627-a661-181b01d4443b`
  - Description explicitly said: "Dispatch all three engineers in parallel as one
    batch."
  - Conductor correctly followed that explicit instruction with one
    `dispatch_batch` containing three engineer prompts, then QA, then finalize.

## Baseline Behavior

The current system is strong at executing a chosen workflow once the LLM decides
to dispatch. The weaker point is policy explanation and deterministic steering
before dispatch:

- The prompt contains broad guidance, but there is no structured "task looks
  trivial / ambiguous / risky / explicitly parallel" classification.
- A healthy budget never discourages unnecessary fan-out.
- `dispatch_batch` has runtime safety checks, but not a policy-level "is this
  fan-out justified?" gate.
- UI now shows batch-derived engineer rows, but the backend still does not expose
  a concise decision policy reason like "parallel allowed because user explicitly
  requested it" vs. "single engineer recommended because work is trivial."

## Opportunity

The next phase should make Conductor's scheduling decisions more legible and less
wasteful:

1. Compute a lightweight orchestration policy before the LLM turn.
2. Inject that policy into the prompt as a stable, tested block.
3. Use the policy to steer batch use:
   - Explicit parallel request + independent work = batch allowed.
   - Trivial work without explicit parallel request = prefer one engineer.
   - Ambiguous scope = PM first.
   - Cross-layer/risky/public-contract work = architect before implementation.
4. Keep the LLM in charge of nuanced exceptions, but force it to explain when it
   overrides the default.
