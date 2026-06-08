# Coordinator Policy Intelligence Design

## Status

Draft for review. Do not implement until approved.

## Objective

The next Moonshot step is to make the Conductor less like a chat loop and more
like a policy-aware coordinator. It should spend LLM calls when the issue state
contains meaningful routing risk, skip low-value calls when evidence is safe,
and leave durable evidence that can feed the review-only self-improvement
proposal ledger.

## Design Options

### Option 1: Prompt-only policy guidance

Add more instructions to the existing Conductor prompt.

Pros: tiny implementation, low risk.

Cons: does not reduce calls, does not create structured evidence, and cannot
reliably power proposal fingerprints.

### Option 2: Deterministic policy decision layer

Add a small backend policy module that classifies each issue-turn as
`call_llm` or `skip_llm`, with reason codes and optional prompt hints. The
Conductor loop records the decision before the LLM step. Risky evidence forces
`call_llm`; only conservative low-signal evidence can skip.

Pros: testable, observable, cheaper, and directly feeds review-only learning.

Cons: requires careful integration to avoid changing terminal loop behavior.

### Option 3: Full adaptive policy engine

Persist rolling per-project policy state, tune thresholds from benchmark
results, and auto-update Conductor prompts/policies.

Pros: closest to the Moonshot end state.

Cons: too much trust surface for one slice; auto-mutation needs proposal review,
rollback, audit, and operator controls first.

## Recommended Approach

Use Option 2.

The policy layer should be deterministic, small, and explicitly conservative.
It should improve autonomy by removing obviously wasteful calls and improve
self-improvement by producing stable evidence, while keeping all policy changes
review-only.

## Architecture

Add `backend/app/application/conductor_policy.py`.

Core types:

* `ConductorPolicyDecision`
  * `action`: `"call_llm"` or `"skip_llm"`
  * `reason_code`: stable snake-case code
  * `reason`: human-readable explanation
  * `prompt_hint`: optional short guidance for the Conductor prompt
  * `evidence`: compact list of evidence dicts

Core function:

* `decide_conductor_policy(issue, conductor_task, recent_turns, graph, budget_status=None)`

The function is pure over its inputs. It does not read/write the database or
call an LLM. Integration code gathers best-effort evidence and falls back to
`call_llm` if evidence loading fails.

## Initial Rules

Call the LLM when:

* this is the first meaningful Conductor decision for the issue.
* any recent tool result has `status` in `failed`, `stalled`,
  `artifact_invalid`, `retries_exhausted`, `role_busy`, or
  `merge_status=conflict`.
* the issue is over budget or at a soft warning.
* the conductor phase transition evidence indicates illegal/stalled/failed
  orchestration.

Skip the LLM only when:

* recent evidence shows repeated low-signal turns with no failed/stalled/error
  tool result.
* the previous Conductor answer already finalized or safely proceeded.
* there is no pending user interjection, no budget warning, and no graph
  risk signal.

The first implementation may only skip a narrow subset. That is acceptable:
false negatives cost money; false positives can break autonomy.

## Integration

In `run_issue_conductor_loop(...)`, gather recent conductor turns and graph
state before constructing or calling the LLM. Record the policy decision via
the existing turn/event path, using a new turn kind such as
`policy_decision`.

If `action == "call_llm"`, append `prompt_hint` to the prompt under a
`## POLICY HINT` section.

If `action == "skip_llm"`, return a structured fallback LLM response that calls
`finalize_task` or emits a no-op safe status, depending on where the loop is.
The first slice should prefer safe finalization only when the issue evidence is
already terminal-success-like; otherwise it should call the LLM.

## Self-Improvement

Extend `self_improvement_service` so conductor task/turn evidence creates
`target_kind="conductor_policy"` proposals for:

* repeated `retries_exhausted`.
* repeated `role_busy` for the same role.
* dispatch-batch merge conflicts.
* repeated `artifact_invalid` for the same role.
* illegal/stalled/failed phase transitions that recovery later repairs.

Proposal fingerprints should use the existing convention:

`project_id|issue_id|conductor_policy|<reason_code>`

The recommendation should ask an operator to review and update Conductor policy
or prompt contracts. It must not apply changes automatically.

## Testing

Add focused tests:

* Pure policy tests for first-turn, risky evidence, and safe skip cases.
* Loop integration test proving policy evidence is recorded and risky evidence
  injects a prompt hint.
* Loop integration test proving a safe skip avoids the LLM callable.
* Self-improvement tests proving conductor-policy proposals are idempotent and
  evidence-backed.

## Safety

The policy layer is best-effort. If evidence loading or classification fails,
the Conductor should call the LLM exactly as it does today.

No specs, prompts, runtime settings, or source files are auto-mutated by the
policy layer. Learning remains review-only through the proposal ledger.

