# Prototype Design Workbench Redesign

## Goal

Replace the current fragmented prototype UI with a coherent operational workbench and close the workflow gap between project analysis, batch generation, and reviewing the generated pages.

## Requirements

- Redesign the prototype main page around a preview-first information hierarchy.
- Present project title, prototype count, selected page context, route, source type, current version, and update time without repeating the full repository path in the feature header.
- Provide a compact, scannable page rail with clear active state, route, version, and source indicator.
- Make the generated HTML preview the dominant desktop surface.
- Move version selection, iteration instruction, generation state, and destructive actions into a stable inspector/control region.
- Preserve the existing Preview/Code modes and cross-prototype route navigation.
- Make project-driven generation the dominant page action; subordinate manual creation, latest-plan access, and batch regeneration.
- Keep existing create, regenerate-all, iterate, delete, version history, preview, code, and route-navigation capabilities functional.
- On mobile, use a single-column layout with no page-level horizontal overflow and at least 44px touch targets.
- When a batch generation run reaches `completed`, automatically navigate exactly once from the plan page to the prototype main page.
- Keep users on the plan page for `partial`, `failed`, and `interrupted` runs so recovery remains available.
- Use existing semantic theme tokens, current typography, existing UI primitives, and Lucide icons.
- Keep errors visible and preserve previously loaded data on transient failures.

## Acceptance Criteria

- [ ] At 1440x900, the selected prototype preview is visible in the first viewport and occupies the largest workbench region.
- [ ] At 1440x900, all primary workbench actions are visible without horizontal overflow.
- [ ] At 390x844, the prototype page has no document-level horizontal overflow.
- [ ] At 390x844, users can switch pages, switch Preview/Code mode, choose routes and versions, and open iteration controls.
- [ ] Each prototype entry exposes title, route when available, current version, and source kind with an unambiguous active state.
- [ ] The selected prototype header exposes route, version, update time, and preview/code mode without duplicating the same information in multiple regions.
- [ ] Successful project generation navigates once to `/projects/{projectId}/prototypes` after the completed snapshot is accepted.
- [ ] Partial or failed generation remains on the plan route and retains retry controls and failure details.
- [ ] Existing prototype navigation and plan review tests pass, with focused coverage for the completion navigation rule.
- [ ] Frontend typecheck, focused lint/format checks, and browser desktop/mobile verification pass.

## Definition of Done

- The redesigned workbench is implemented in the existing prototype feature boundary.
- Relevant translations exist in both Chinese and English.
- Focused automated tests cover the navigation rule and stable presentation contracts.
- Desktop and mobile browser screenshots show a usable, non-overlapping layout.

## Technical Approach

- Keep `ProjectPrototypesPage` as the data owner and selection coordinator.
- Decompose presentation into small local components only where it removes JSX/state complexity.
- Keep `PrototypeCanvas` responsible for selected prototype preview, versions, iteration, and delete behavior, but reorganize it into preview stage plus inspector.
- Add a pure generation-completion navigation predicate/helper and consume it from `PrototypePlanReviewPage` with a ref guard so repeated SSE/poll snapshots do not navigate more than once.
- Reuse the current `Prototype`, `PrototypeDetail`, and generation run contracts; no backend schema change is required.

## Decision (ADR-lite)

**Context**: The existing two-column page treats the prototype list and preview as peer cards and leaves generation completion on the review page. This obscures the primary task and breaks workflow continuity.

**Decision**: Use a desktop-first three-region workbench with preview as the center of gravity, collapse it to one column on small screens, and make successful generation completion return to the workbench automatically.

**Consequences**: The prototype feature becomes denser and easier to scan. `ProjectPrototypesPage` and `PrototypeCanvas` need substantial JSX changes, but backend contracts and generation behavior remain unchanged. Failed runs remain intentionally on the review page.

## Out of Scope

- Backend prototype or generation schema changes.
- Changes to generated HTML content or the admin-demo application's own UI.
- Replacing the global project shell navigation.
- Multi-user collaboration, comments, or prototype approval workflow.
- New image generation or visual asset pipeline.

## Research References

- [`research/current-ui-audit.md`](research/current-ui-audit.md) - live desktop/mobile audit and the selected operational workbench direction.

## Technical Notes

- Preserve all existing unrelated working-tree changes.
- Follow `.trellis/spec/ccgui/frontend/` guidance and the repository defensive-programming rules.
- Main implementation files are expected under `frontend/src/features/prototype/`, plus i18n dictionaries and focused tests.
