# Current Conductor Policy Baseline

## Evidence Inspected

- `docs/CONDUCTOR.md`
  - Deferred items include trigger gating, historical context, retry on
    transient LLM failure, model tiering, prompt caching, multi-issue learning,
    sample efficiency, and clarification triage.
  - The most immediate trust-safe items are trigger gating and structured
    learning evidence; model/prompt auto-tuning is intentionally later.
- `backend/app/application/conductor_main_loop.py`
  - `run_issue_conductor_loop(...)` builds the issue Conductor prompt inline and
    calls `run_conductor_loop(...)`.
  - `run_conductor_loop(...)` records `llm_request`, `llm_response`,
    `tool_use`, `tool_result`, and `finalize` turns.
  - The loop currently has no deterministic policy decision before an LLM
    request. It always asks the Conductor LLM unless no LLM is configured.
  - Cost and budget context are already injected into the prompt, and budget
    warnings emit structured events, but budget evidence does not decide whether
    an LLM call is worth making.
- `backend/app/application/conductor_tools.py`
  - Tool-level runtime guards already exist: per-role redispatch budget,
    role-busy handling, batch concurrency caps, budget-supported concurrency,
    batch merge conflict reporting, and cleanup paths.
  - These guards return structured tool results that can be mined as policy
    evidence.
- `backend/app/application/self_improvement_service.py`
  - The new proposal ledger writes review-only proposals for QA failures and
    runtime failures.
  - It does not yet classify Conductor policy/routing evidence such as
    `retries_exhausted`, `role_busy`, `artifact_invalid`, or batch conflicts.

## Baseline Behavior

The current system is good at executing a workflow once the Conductor LLM has
chosen tools. It is weaker at deciding when a Conductor LLM turn is worthwhile
and at preserving stable, reviewable reasons for routing/policy failures.

The useful evidence already exists in three places:

1. Conductor turn records.
2. Conductor tool results.
3. Terminal issue sealing and self-improvement proposal extraction.

The missing layer is a deterministic policy classifier that reads that evidence
and emits stable reason codes.

## Opportunity

The next phase should add a small, pure policy layer before the Conductor LLM
call:

1. Gather recent turn/tool/graph/budget evidence best-effort.
2. Classify the turn as `call_llm` or `skip_llm`.
3. Record the policy decision as durable evidence.
4. Inject a short prompt hint when risky evidence requires an LLM call.
5. Extend self-improvement extraction to turn repeated policy failures into
   `conductor_policy` proposals.

The first implementation should be conservative. False negatives only cost an
extra LLM call; false positives could break autonomous completion.
