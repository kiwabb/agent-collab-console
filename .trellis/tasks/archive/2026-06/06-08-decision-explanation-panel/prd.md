# Decision Explanation Panel

## Goal

Make Conductor decisions more product-visible by adding a compact issue-detail
panel that explains the current orchestration policy: recommended workflow,
whether parallel batch is allowed, which signals were detected, and what the
Conductor should do next.

## What I Already Know

- The backend now has a deterministic orchestration classifier in
  `backend/app/application/conductor_policy.py`.
- The classifier is injected into the Conductor prompt, but users cannot see
  that policy directly in the product UI.
- The issue detail page already has a dense right rail in
  `IssueSideStack.tsx` for insights such as acceptance, telemetry, activity,
  and similar issues.
- Existing frontend conventions require typed API functions in `lib/api.ts`,
  shared response types in `lib/types.ts`, i18n parity, and pure derivation
  tests for display rules.

## Assumptions

- The panel should be informational, not a new control surface.
- The backend should remain the source of truth for policy classification; the
  frontend should not reimplement the scheduling heuristics.
- The panel should describe current policy for the issue title/description. It
  does not need to replay old historical decisions or mutate existing runs.

## Requirements

1. Add a backend issue endpoint that returns the orchestration policy for an
   issue in a stable JSON shape.
2. Add a typed frontend API client and shared TypeScript response type.
3. Add a right-rail decision explanation card on the issue detail page.
4. The card must show:
   - recommended default;
   - batch allowed yes/no;
   - detected signals;
   - short guidance bullets.
5. The card must be compact, operations-console styled, responsive, and not add
   a fifth top-level tab.
6. The card must use `useI18n()` for all user-visible strings with zh-CN/en-US
   parity.
7. Refresh the policy when the issue is updated or steered.
8. Add tests for backend shape, frontend API client shape, and display
   derivation.

## Acceptance Criteria

- [x] `GET /api/codex/issues/{issue_id}/orchestration-policy` returns a 200
      JSON payload for existing issues and 404 for missing issues.
- [x] A trivial issue payload recommends `single_engineer`, `batch_allowed=false`,
      and includes guidance.
- [x] An explicit independent parallel issue payload recommends
      `batch_allowed`, `batch_allowed=true`, and includes
      `explicit_parallel` / `independent_slices` signals.
- [x] Issue detail right rail renders a decision explanation card using the new
      typed client.
- [x] Frontend tests cover card derivation and API client URL/shape.
- [x] Backend focused tests pass.
- [x] Frontend focused tests, lint, and a safe build/type check pass.
- [x] Browser DOM/screenshot check passes: the issue detail page renders the
      decision explanation panel, browser console errors are empty, and the
      default 1280px viewport has no horizontal overflow.

## Verification Notes

- Continuation verification on 2026-06-08:
  - Backend focused policy tests: `python3 -m pytest backend/tests/test_conductor_policy.py backend/tests/test_conductor_policy_endpoint.py -q` -> `10 passed`.
  - Frontend node tests: `npm test -- decisionExplanationPanel.test.ts issueCommandCenter.test.ts` -> `161 passed`.
  - Frontend lint: `npm run lint` -> no ESLint warnings or errors. Note: `next lint` prints a Next 16 deprecation warning.
  - Frontend build/type check: `npm run build` -> succeeded.
  - Backend expanded runtime tests: `python3 -m pytest backend/tests/test_budget_supported_concurrency.py backend/tests/test_conductor_dispatch_batch.py backend/tests/test_dispatch_batch_budget_concurrency.py backend/tests/test_llm_runner_streaming.py backend/tests/test_projects_api.py backend/tests/test_subagent_result_builder.py backend/tests/test_swarm_integration.py backend/tests/test_worktree_claude_hooks.py backend/tests/test_worktree_manager.py backend/tests/test_ws_subscriber_backpressure.py backend/tests/test_agent_process_environment.py -q` -> `114 passed`.
- Backend focused tests: `backend/tests/test_conductor_policy_endpoint.py` passed.
- Backend import smoke: `from app.main import app` passed.
- Frontend focused/full node tests: `161 passed`.
- Frontend lint: no warnings or errors.
- Frontend build: `next build` succeeded.
- Runtime API checks:
  - `http://127.0.0.1:9000/api/codex/issues/c13b189c-4da4-4627-a661-181b01d4443b/orchestration-policy`
  - `http://127.0.0.1:4000/api/codex/issues/c13b189c-4da4-4627-a661-181b01d4443b/orchestration-policy`
- Browser check:
  - Opened `http://127.0.0.1:4000/issues/c13b189c-4da4-4627-a661-181b01d4443b`.
  - Found exactly one `[data-decision-explanation-panel]`.
  - Panel text includes `决策解释`, `允许并行批处理`, `明确要求并行`, and `独立切片`.
  - Console error log count: `0`.
  - Layout metrics: `innerWidth=1280`, `scrollWidth=1280`, `hasHorizontalOverflow=false`.
  - Screenshot evidence: `/tmp/decision-explanation-panel.png`.

## Out Of Scope

- Editing or re-running existing historical Conductor turns.
- Adding a runtime hard guard that blocks `dispatch_batch`.
- New database columns or migrations.
- A full decision audit timeline redesign.

## Technical Notes

- Backend integration point: `backend/app/interfaces/api.py`.
- Backend policy source: `backend/app/application/conductor_policy.py`.
- Frontend integration point: `frontend/src/features/issues/components/IssueSideStack.tsx`.
- Likely new frontend component: `DecisionExplanationCard.tsx`.
- Relevant specs:
  - `.trellis/spec/ccgui/frontend/index.md`
  - `.trellis/spec/ccgui/frontend/component-guidelines.md`
  - `.trellis/spec/ccgui/frontend/hook-guidelines.md`
  - `.trellis/spec/ccgui/frontend/quality-guidelines.md`
  - `.trellis/spec/ccgui/frontend/type-safety.md`
  - `.trellis/spec/vibe-kanban/backend/index.md`
  - `.trellis/spec/vibe-kanban/backend/quality-guidelines.md`
  - `.trellis/spec/vibe-kanban/backend/error-handling.md`
  - `.trellis/spec/guides/cross-layer-thinking-guide.md`
  - `.trellis/spec/guides/code-reuse-thinking-guide.md`
