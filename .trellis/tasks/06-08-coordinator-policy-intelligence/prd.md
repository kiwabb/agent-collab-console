# brainstorm: coordinator policy intelligence

## Goal

Make the issue Conductor more policy-aware without reducing trust. This slice
adds deterministic policy intelligence around Conductor LLM usage: the system
should know when a turn is worth an LLM call, explain why a call was skipped or
allowed, and turn repeated policy/routing failures into review-only
self-improvement proposals.

This advances the Moonshot autonomy goal by making orchestration cheaper, more
observable, and more capable of learning from stalled or wasteful issue loops.

## What I Already Know

* `docs/CONDUCTOR.md` lists trigger gating, historical context, sample
  efficiency, and policy learning as deferred Conductor work.
* `backend/app/application/conductor_main_loop.py` builds one large prompt and
  currently calls the Conductor LLM each loop turn unless no LLM is configured.
* `run_conductor_loop(...)` already records `llm_request`, `llm_response`,
  `tool_use`, `tool_result`, and `finalize` turns.
* `backend/app/application/conductor_tools.py` already enforces several
  runtime policies, including per-role redispatch limits, role-busy handling,
  dispatch batch concurrency, and budget-supported fan-out.
* `backend/app/application/self_improvement_service.py` now writes
  review-only proposals for QA failures and runtime failures after issue seal.
* The first self-improvement PR deliberately avoids auto-mutating specs,
  prompts, policy, memory, or code.

## Assumptions

* The first coordinator-policy slice should be deterministic and review-only.
* It should not silently change `.trellis/spec/`, prompts, model settings, or
  runtime policy.
* Conductor must remain best-effort: policy intelligence failure must not block
  issue completion.
* The implementation should stay backend-first; frontend UI can read existing
  events/proposals later.

## Requirements

* Add a small policy-decision module for Conductor issue turns.
* Derive a policy decision from current issue/task/graph evidence before a
  Conductor LLM turn.
* Represent at least:
  * `call_llm`: the turn needs the Conductor LLM.
  * `skip_llm`: the turn is low-value and can avoid an LLM call.
  * `policy_hint`: short text explaining evidence that should be injected into
    the Conductor prompt when an LLM call is allowed.
* Record the policy decision as durable turn/event evidence so operators and
  tests can see why the Conductor called or skipped the LLM.
* Keep skip behavior conservative:
  * Do not skip the initial Conductor decision for a live issue.
  * Do not skip when a subagent failed, stalled, returned invalid artifacts,
    exhausted retries, hit role-busy, hit dispatch merge conflicts, or budget
    warnings/over-budget evidence exists.
  * Skipping is only allowed for low-signal repeated proceed/finalize-like
    situations where recent evidence shows no policy risk.
* Extend self-improvement extraction to create `conductor_policy` proposals
  when conductor evidence shows repeated role redispatch exhaustion, role-busy
  loops, invalid artifacts, dispatch-batch conflicts, or illegal/blocked phase
  transitions.
* Add focused backend tests for policy classification, prompt/event wiring, and
  self-improvement proposal extraction.

## Acceptance Criteria

* [ ] A pure function or small service class classifies Conductor policy
      decisions from issue/task/turn evidence without requiring an LLM.
* [ ] Policy decisions include stable reason codes suitable for tests,
      proposal fingerprints, and event/audit payloads.
* [ ] `run_issue_conductor_loop(...)` records policy evidence without changing
      terminal issue sealing semantics.
* [ ] Low-risk skip decisions avoid an LLM call while still recording a
      `conductor_turn`/event that explains the skip.
* [ ] Risky evidence produces `call_llm` with prompt guidance, not a skip.
* [ ] Self-improvement extraction emits idempotent `conductor_policy`
      proposals for repeated routing/policy failures.
* [ ] Existing Conductor behavior remains backward-compatible when no policy
      evidence exists.
* [ ] Focused backend tests pass.

## Definition of Done

* Backend tests added/updated for the new policy module and integration points.
* Existing focused Conductor and self-improvement tests pass.
* Full backend test suite passes or any unrelated failure is documented with
  evidence.
* `.trellis/spec/` is updated only if the implementation teaches a reusable
  convention.
* No automatic policy/spec/prompt mutation is introduced in this slice.

## Out of Scope

* Auto-applying self-improvement proposals.
* Frontend proposal inbox or Conductor policy dashboard.
* Model tiering, prompt caching, or external memory APIs.
* Replacing the Conductor tool loop architecture.
* Running public SWE-bench evaluations in this task.

## Technical Notes

* Relevant docs: `docs/CONDUCTOR.md`,
  `docs/superpowers/specs/2026-06-08-self-improvement-loop-design.md`.
* Research baseline:
  `.trellis/tasks/06-08-coordinator-policy-intelligence/research/current-conductor-policy-baseline.md`.
* Likely backend files:
  * `backend/app/application/conductor_main_loop.py`
  * `backend/app/application/conductor_tools.py`
  * `backend/app/application/self_improvement_service.py`
  * `backend/app/domain/models.py`
  * `backend/tests/test_conductor_main_loop.py`
  * `backend/tests/test_self_improvement_service.py`
* Existing turn kinds are already persisted through `persist_turn(...)`.
* Existing proposal fingerprints are
  `project_id|issue_id|target_kind|rule_id`.
