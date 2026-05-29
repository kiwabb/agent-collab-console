# brainstorm: frontend visual overhaul

## Goal

Reduce visual clutter in the frontend and make the main collaboration surfaces feel calmer, clearer, and easier to scan without changing product behavior.

## What I already know

* The app is a workbench-style product with dense operational surfaces.
* The main UI clutter seems concentrated in the sidebar, issue detail page, conductor log/stream panels, and agent/project docks.
* Current visuals lean heavily on stacked borders, many small badges, and several competing live/streaming areas.
* Existing pages already have a shared shell and consistent data flow; this is primarily a presentation-layer redesign.

## Assumptions (temporary)

* We will keep the existing routing, data flow, and feature behavior.
* This task is about a large frontend polish pass, not a product re-architecture.
* We should reuse the current design system and components where possible.

## Open Questions

* Should I optimize the whole app shell and all dense panels, or focus the big redesign on the main workbench and issue detail surfaces first?

## Requirements (evolving)

* Simplify visual hierarchy and reduce competing emphasis.
* Make primary actions and current status easier to see at a glance.
* Reduce the number of “boxed” sections and noisy separators where possible.
* Keep the UI responsive and usable on smaller screens.

## Acceptance Criteria (evolving)

* [x] The main app shell reads as one coherent layout instead of separate stacked widgets.
* [x] Dense pages have clearer hierarchy and less border noise.
* [x] Live/streaming panels feel integrated instead of visually fighting the rest of the page.
* [x] No behavior regressions in navigation, task flow, or live updates.

## Definition of Done (team quality bar)

* Tests added/updated where practical
* Lint / typecheck / CI green
* Docs/notes updated if behavior changes
* Rollout/rollback considered if risky

## Out of Scope (explicit)

* Backend/API changes
* New product features
* Major navigation restructuring

## Technical Notes

* Investigated: `frontend/src/app/layout.tsx`
* Investigated: `frontend/src/app/page.tsx`
* Investigated: `frontend/src/features/workbench/components/AppSidebar.tsx`
* Investigated: `frontend/src/features/issues/IssueDetailPage.tsx`
* Investigated: `frontend/src/features/issues/IssueDetailPanel.tsx`
* Investigated: `frontend/src/features/issues/components/LiveThinkingDock.tsx`
* Investigated: `frontend/src/features/workflow/ConductorLogPanel.tsx`
* Investigated: `frontend/src/features/projects/components/ProjectConductorThreadDock.tsx`
* Investigated: `frontend/src/features/workflow/AgentCatalogPanel.tsx`
