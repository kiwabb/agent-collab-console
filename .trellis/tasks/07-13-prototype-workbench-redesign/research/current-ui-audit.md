# Prototype Workbench UI Audit

## Evidence

- Inspected `http://127.0.0.1:4000/projects/09cca906-b5e1-4601-aa7a-14fb58f9f06b/prototypes` at 1440x900 and 390x844 on 2026-07-13.
- Inspected the latest completed plan at `/projects/09cca906-b5e1-4601-aa7a-14fb58f9f06b/prototypes/plans/prototype-plan-6a751e98f0eb41d8a76c560f4374167c`.
- Reviewed `ProjectPrototypesPage.tsx`, `PrototypeCanvas.tsx`, `PrototypePlanReviewPage.tsx`, and `PrototypeGenerationProgressPanel.tsx`.

## Findings

1. The main page presents three unrelated header actions with equal visual weight and repeats the repository path already shown by the project shell.
2. The prototype list only exposes title and version. It omits route, source, updated time, generation state, and selected-page context.
3. Preview, version navigation, iteration input, and destructive action have no stable inspector hierarchy. The primary preview is vertically compressed by controls above and below it.
4. At 390px, the project shell and prototype actions overflow horizontally. The three workbench actions are clipped, and the preview cannot be operated as a coherent mobile surface.
5. The review page keeps showing editable analysis content after a fully successful generation run. It does not navigate to the generated prototypes, so the workflow ends on the wrong page.
6. The completed generation run already contains prototype IDs and version numbers, so successful completion can navigate without changing backend contracts.

## Design Direction

- Treat the page as an operational prototype review workbench, not a gallery or marketing page.
- Desktop layout: compact page rail, dominant preview stage, and inspector for route/version/iteration controls.
- Mobile layout: single column, compact page switcher, preview before secondary metadata, and 44px controls.
- Use existing semantic theme tokens and Lucide icons. Do not introduce a standalone palette, gradients, decorative cards, or nested cards.
- Give one dominant action to project-driven generation. Move less frequent actions into subordinate buttons or an overflow menu.
- Preserve stale preview content on request failures and show explicit errors.

## Navigation Contract

- A newly created analysis plan opens the plan review route.
- While analysis or generation is active, the user remains on the plan route.
- When a generation run transitions to `completed`, navigate once to `/projects/{projectId}/prototypes`.
- Do not auto-navigate for `partial`, `failed`, or `interrupted`; those states require review and retry.
- The main workbench restores a deterministic active prototype and route after its list loads.
