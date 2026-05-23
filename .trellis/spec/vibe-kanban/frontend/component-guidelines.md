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
