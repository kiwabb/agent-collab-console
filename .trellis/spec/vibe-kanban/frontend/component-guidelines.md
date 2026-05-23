# Component Guidelines

> How components are built in this project.

---

## Overview

<!--
Document your project's component conventions here.

Questions to answer:
- What component patterns do you use?
- How are props defined?
- How do you handle composition?
- What accessibility standards apply?
-->

(To be filled by the team)

---

## Component Structure

<!-- Standard structure of a component file -->

### Scenario: Workspace Console Scheduler Surface

#### Scope / Trigger

- Trigger: changing `/workspaces/[wsId]` or `frontend/src/features/workspaces/WorkspaceConsole.tsx`.
- The workspace console is a scheduler overview, not an issue detail page.

#### Required Structure

- Keep `WorkspaceConsole.tsx` as a thin data-loading shell under 300 lines.
- Put header actions in `WorkspaceConsoleHeader.tsx`.
- Put list/empty/loading states in `IssueListPanel.tsx`.
- Put row-level status, phase progress, role chip, and open behavior in `IssueRow.tsx`.
- Reuse `NewIssueDialog` for issue creation instead of adding another composer.

#### Forbidden Patterns

- Do not reintroduce a right-side run detail column on the workspace page.
- Do not add issue chat/refine controls to the workspace page; those belong under `/issues/[id]`.
- Do not make row click select inline detail. Row click should navigate to `/issues/[id]`.
- Do not pass large prop bundles into list components; keep each component's props focused on its own responsibility.

### Scenario: Project Workspaces Management Surface

#### Scope / Trigger

- Trigger: changing `/projects/[id]`, `/projects/[id]/conductor`, or components under `frontend/src/features/projects/`.
- Project pages have two sibling responsibilities: workspace management and project-level Conductor conversation.

#### Required Structure

- Keep workspace CRUD, KPIs, search, and workspace table on `/projects/[id]`.
- Keep the full `ProjectConductorPage` on `/projects/[id]/conductor`.
- Share project Hero and secondary navigation through `ProjectShell`.
- Secondary navigation should use `next/link` and `usePathname` so active state, deep links, and browser navigation remain correct.

#### Forbidden Patterns

- Do not embed `ProjectConductorPage` directly in `ProjectWorkspacesPage`.
- Do not push the primary `+ New workspace` action below a full Conductor panel or other heavy conversation surface.
- Do not rewrite `ProjectConductorPage` just to move where it mounts; keep project conductor behavior reusable.

### Scenario: Issue Command Center

#### Scope / Trigger

- Trigger: changing `/issues/[id]`, `frontend/src/features/issues/IssueDetailPage.tsx`, or issue detail components.
- The issue detail page is a Conductor command center, not a multi-tab workspace.

#### Required Structure

- Keep `IssueDetailPage.tsx` as a thin composition shell under 200 lines.
- Put the top issue/conductor state in `StatusStrip`.
- Put unaddressed failures in `LatestFailureAlert`.
- Use `DecisionTimeline` and `TimelineRow` as the primary work history, with thinking turns collapsed by default.
- Put lower-priority surfaces in accordions: artifacts, diff, and mesh.
- Keep live user steering in a sticky `CommandCenterChatBar`; `[CLARIFY]` answers should flow through the conductor message endpoint.
- Keep WebSocket connectivity feedback in `WsConnectionBanner`.

#### Forbidden Patterns

- Do not reintroduce six top-level tabs or `?tab=` navigation on `/issues/[id]`.
- Do not make DAG, task runs, artifacts, diff, or collaboration the primary navigation model.
- Do not put conductor state toast subscriptions directly into the page shell; keep them in focused hooks such as `useConductorPhase`.
- Do not grow `IssueDetailPage.tsx` with drawer, timeline, or panel implementation details.

---

## Props Conventions

<!-- How props should be defined and typed -->

(To be filled by the team)

---

## Styling Patterns

<!-- How styles are applied (CSS modules, styled-components, Tailwind, etc.) -->

(To be filled by the team)

---

## Accessibility

<!-- A11y requirements and patterns -->

(To be filled by the team)

---

## Common Mistakes

<!-- Component-related mistakes your team has made -->

(To be filled by the team)
