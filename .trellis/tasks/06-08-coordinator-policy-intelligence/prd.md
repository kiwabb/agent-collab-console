# Coordinator Policy Intelligence Phase

## Goal

Make the issue Conductor better at choosing the right workflow size before it
dispatches agents. The immediate problem is that Conductor can execute parallel
fan-out well, but it does not clearly distinguish "this simple task explicitly
asked for parallelism" from "this simple task should be handled by one engineer."

The next phase should add a small, testable scheduling-policy layer that steers
PM / architect / engineer / QA / batch decisions and explains the reason.

## What I Already Know

- The current Conductor prompt already contains broad rules:
  - use PM for unclear requirements;
  - use architect for cross-layer/risky changes;
  - use engineer for code changes;
  - use QA before success;
  - use `dispatch_batch` only for independent work.
- `dispatch_batch` is already robust: isolated worktrees, partial join, merge,
  conflict reporting, budget-aware concurrency downscale, role retry budget.
- Budget pressure can reduce batch concurrency, but healthy budget does not stop
  unnecessary fan-out.
- Real run `c13b189c...` used 3 engineers because the issue description
  explicitly said to "Dispatch all three engineers in parallel as one batch."
  That was correct for a parallel-swarm validation issue, but it exposes that
  the product needs clearer policy and explanation.
- UI work has made batch-derived engineer tasks visible, so the next phase can
  focus on backend decision quality rather than merely presentation.

## Assumptions

- We should not remove `dispatch_batch`; it is valuable when work is truly
  independent or explicitly requested.
- The first implementation should be deterministic and testable without running
  an LLM.
- The LLM should still be allowed to make nuanced decisions, but the prompt
  should include a stable policy recommendation and require explicit reasoning
  when overriding it.

## Requirements

1. Add a pure orchestration-policy classifier for issue title/description.
   - Detect explicit parallel/batch requests.
   - Detect trivial/single-slice work.
   - Detect independent multi-slice work.
   - Detect ambiguity that should start with PM.
   - Detect risk/cross-layer/public-contract cues that should start with
     architect.
2. Render the classifier result into the Conductor prompt as a new
   `## ORCHESTRATION POLICY` block.
3. Policy defaults:
   - explicit parallel + independent slices -> batch allowed;
   - trivial work without explicit parallel -> prefer one engineer;
   - ambiguous requirements -> PM first;
   - risky/cross-layer work -> architect first;
   - implementation still requires QA before success.
4. Preserve existing budget semantics:
   - budget can downscale concurrency;
   - budget must not hard-kill the loop;
   - the new policy must not increase `MAX_PARALLEL_DISPATCH_PER_BATCH`.
5. Make the policy testable with unit tests around prompt rendering and
   classification examples.

## Acceptance Criteria

- [x] A trivial single-file/focused issue without explicit parallel language
      produces a policy that recommends one engineer and discourages batch.
- [x] The same style of trivial issue with explicit "parallel/batch" language
      and independent slices allows batch fan-out.
- [x] Ambiguous requirement text recommends PM before implementation.
- [x] Cross-layer/risky/public API/migration language recommends architect.
- [x] `build_issue_conductor_prompt(...)` includes the policy block.
- [x] Existing Conductor prompt tests and dispatch/budget tests still pass.
- [x] Backend tests cover the classifier and prompt injection.

## Out Of Scope

- Replacing the LLM planner with a full deterministic workflow engine.
- Removing `dispatch_batch`.
- Changing the worktree merge strategy.
- Changing UI beyond whatever is needed to expose a policy reason later.
- Hard-stopping the Conductor on budget pressure.

## Technical Notes

- Likely new helper: `backend/app/application/conductor_policy.py`.
- Likely integration point: `build_issue_conductor_prompt(...)` in
  `backend/app/application/conductor_main_loop.py`.
- Relevant specs:
  - `.trellis/spec/vibe-kanban/backend/index.md`
  - `.trellis/spec/vibe-kanban/backend/quality-guidelines.md`
  - `.trellis/spec/vibe-kanban/backend/testing-guidelines.md`
  - `.trellis/spec/guides/cross-layer-thinking-guide.md`
- Research notes:
  - `.trellis/tasks/06-08-coordinator-policy-intelligence/research/current-conductor-policy-baseline.md`

## Recommended MVP

Implement the deterministic classifier and prompt block first. This gives us a
fast quality improvement, a stable test surface, and a clear foundation for a
later runtime tool guard or UI decision-explanation panel.

## Implementation Summary

- Added `backend/app/application/conductor_policy.py`.
- Injected `## ORCHESTRATION POLICY` into the Conductor prompt.
- Added classifier and prompt injection tests in
  `backend/tests/test_conductor_policy.py`.
- Verified related dispatch and budget behavior still passes.
