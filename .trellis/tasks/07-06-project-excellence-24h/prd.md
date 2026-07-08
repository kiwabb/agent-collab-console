# 24-Hour Project Excellence Pass

## Goal

Use a sustained 24-hour-or-longer improvement window to make Agent Collaboration Console more stable, maintainable, and demonstrably closer to release quality. The work should be evidence-driven: inspect the repo, protect existing user/WIP changes, run quality gates, fix high-value issues, and record what was learned.

## What I Already Know

- The user explicitly authorized a broad improvement pass and requested that the work window not be less than 24 hours.
- The project is a local-first multi-agent operations console with a FastAPI/Pydantic/SQLite backend and Next.js/React/TypeScript frontend.
- Quality gates documented in `README.md` include frontend TypeScript, frontend tests, frontend lint, and backend pytest.
- The working tree already contains substantial uncommitted work, especially around code-driven prototype generation, runtime prototype capture, prototype UI/API/types/tests, audit role chains, resume/workbench/project UI, and i18n.
- Current Trellis state has no previous current task for this thread, but five active in-progress tasks exist. This task should not silently absorb unrelated WIP without understanding it.
- The largest active WIP appears tied to `.trellis/tasks/07-03-code-driven-generate-all-prototypes/`, whose PRD already records many completed acceptance criteria and runtime E2E evidence.

## Assumptions

- The best first improvement is not random feature expansion; it is stabilizing and validating the current high-value WIP already in the working tree.
- Existing uncommitted changes may be user work or previous AI work and must be preserved unless a fix requires touching them.
- Broad refactors are out of scope unless they directly unblock tests, type checks, correctness, reliability, or maintainability.
- Because the user delegated planning, proceed with conservative engineering judgment and ask only if a preference decision materially changes risk.

## Requirements

- Establish a baseline by inventorying dirty files, active Trellis tasks, relevant docs, package scripts, and quality gates.
- Run targeted quality checks first, then broaden to full frontend/backend gates as failures are resolved.
- Prioritize fixes in this order:
  1. broken tests, type errors, import/runtime errors, or API contract drift;
  2. data integrity, local-first trust boundary, generated artifact safety, and recovery-path bugs;
  3. UX defects in already-touched user workflows;
  4. low-risk cleanup that reduces duplication or future debugging cost.
- Preserve existing WIP semantics. Do not revert unrelated changes and do not fold unknown dirty files into commits without explicit confirmation.
- Keep changes tightly scoped and follow existing frontend/backend patterns.
- Maintain or improve tests for any behavior changed.
- Update Trellis specs or task notes when the work reveals a reusable convention, pitfall, or quality rule.
- Avoid committing until a coherent commit plan can distinguish this session's edits from pre-existing dirty files.

## Acceptance Criteria

- [ ] Baseline report exists under this task describing current dirty state, test scripts, and initial quality gate results.
- [ ] Any failing targeted gate caused by the current implementation is either fixed or documented with a clear blocker and reproduction command.
- [ ] Frontend TypeScript and relevant frontend node tests pass for touched areas, or a precise blocker is recorded.
- [ ] Backend pytest passes for touched areas, or a precise blocker is recorded.
- [ ] Full project gates are attempted once targeted gates are stable, with results recorded.
- [ ] No user/WIP changes are reverted or silently discarded.
- [ ] Improvements include at least one concrete code/test/doc/spec change beyond planning, unless baseline shows a larger unresolved blocker that must be reported first.
- [ ] A final handoff summarizes what improved, what remains risky, and the next best tasks.

## Definition Of Done

- Tests added or updated where behavior changes.
- Typecheck/lint/test evidence recorded in task reports.
- Docs, PRD, or specs updated if behavior or conventions change.
- Git status reviewed and a commit plan prepared for user confirmation if commits are appropriate.

## Technical Approach

1. Inventory and baseline:
   - inspect dirty diffs by subsystem;
   - map dirty files to active Trellis tasks where possible;
   - run quick static/test checks to identify current breakage.
2. Stabilize current WIP:
   - start with the prototype generation/runtime-capture surface because it dominates the dirty diff and has existing tests;
   - fix contract drift across backend service, API, frontend types, i18n, and tests.
3. Broaden quality:
   - run frontend TypeScript/tests/lint and backend pytest;
   - fix high-signal failures;
   - document remaining failures that are unrelated or too large for the current slice.
4. Polish and preserve:
   - improve docs/specs around discovered conventions;
   - keep git operations explicit and avoid mixing unknown WIP into commits.

## Expansion Sweep

### Future Evolution

- This pass can become a recurring project-health loop: baseline, fix, verify, record, repeat.
- The task should leave behind reusable quality notes so later agents can continue without rediscovering the same constraints.

### Related Scenarios

- Existing active tasks around prototypes, audit logs, and startup scripts should remain separately understandable.
- Generated prototype/runtime evidence workflows should stay consistent with local-first safety constraints and EventSource API patterns.

### Failure And Edge Cases

- Full gates may fail because of pre-existing WIP; record exact commands and distinguish failures caused by this session from inherited failures.
- Long-running browser/runtime/LLM flows can be flaky; prefer deterministic unit/contract tests first, then representative browser evidence.
- Local generated caches such as `frontend/tsconfig.tsbuildinfo` should not be treated as source improvements.

## Out Of Scope

- Rewriting the architecture from scratch.
- Large speculative UI redesign unrelated to existing workflows.
- Destructive git cleanup, force resets, or discarding dirty files.
- Pushing, publishing, or changing production-like credentials.
- Running arbitrary external services beyond the local development/test commands needed for verification.

## Technical Notes

- Primary repo files inspected so far: `README.md`, `frontend/package.json`, `backend/pyproject.toml`, active Trellis task PRDs, and `git diff --stat`.
- Dominant dirty area: `.trellis/tasks/07-03-code-driven-generate-all-prototypes/`, backend prototype services/API/tests, and frontend prototype API/UI/type/i18n tests.
- Relevant shared guide: `.trellis/spec/guides/index.md`.
