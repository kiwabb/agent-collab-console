# Component Guidelines

> How components are built in the ccgui frontend package.

---

## Overview

The frontend is a Next.js 15 App Router project using **Tailwind v4** and
**@base-ui/react** (NOT shadcn, NOT radix directly). Components live under
`frontend/src/` and are organized by **feature**, not by type:

- `frontend/src/app/` — App Router pages (route segments only; composition
  goes into `features/.../SomePage.tsx`)
- `frontend/src/features/<area>/<PageOrCard>.tsx` — feature-owned
  components, hooks, and helpers
- `frontend/src/components/` — generic UI primitives (`runtime/`, `ui/`)
- `frontend/src/providers/` — React context providers (`I18nProvider`,
  `ThemeProvider`, `PreferencesProvider`, `ExecutionProcessesContext`)
- `frontend/src/hooks/` — cross-feature hooks (`useBusEventEffect`,
  `useExecutionProcessesContext`)
- `frontend/src/lib/` — pure utilities + API client + types + dictionaries
- `frontend/src/contexts/`, `frontend/src/store/`, `frontend/src/utils/` —
  smaller groupings; colocate to the smallest home that fits

A component is **client** (`"use client"`) when it touches hooks, browser
APIs, or the event bus. Everything else stays a server component.

---

## Component Structure

- **Thin page shells, fat sub-components.** Page files (`*Page.tsx`) are
  composition-only: imports, layout, delegation. Implementation belongs in
  child components that the page imports.
- **Size budget**: page components stay under ~300 lines; if a page grows,
  split header / list / row / footer into sibling files in the same
  directory.
- **One component per file** unless a sub-component is a private helper
  that no other file imports.
- **Co-locate hooks, helpers, and types** with the component that owns
  them, under `frontend/src/features/<area>/<Component>/`. Only promote
  to `lib/` or `hooks/` when a second feature starts importing them.
- **Stateful pure helpers** live in a `*Helpers.ts` / `*Derived.ts` /
  `*State.ts` file next to the consuming component. They get a unit test
  with the same stem — never co-mingle pure logic with JSX.

**Example shape** (real, from the issue-side stack work):

```
frontend/src/features/issues/components/
  IssueSideStack.tsx          # thin composition shell
  BudgetMeter.tsx             # pure presentation component
  useIssueBudget.ts           # data + live-update hook
  deriveBudgetMeterState.ts   # pure state derivation (unit tested)
```

---

## Props Conventions

- **Explicit `interface Props { ... }`** at the top of the file, named
  `Props` (not `IProps` or `XxxProps`). One named interface per file is
  the rule; large variants use a discriminated union.
- **Required props first, optional last**; mark optional props with `?` in
  the type and accept `undefined` explicitly in the destructure.
- **Children are explicit**, not implicit. A wrapper that always wraps a
  `<Card>` body takes `children: React.ReactNode`; a primitive button does
  not expose `as` polymorphism unless there is a real consumer.
- **No `any` in prop types.** Use `unknown` + a type guard, or define a
  narrow union. ESLint enforces this.
- **Function props**: name by what they do (`onSend`, `onIssueUpdated`,
  `onClick`), not by the event (`onClickHandler`). Booleans start with
  `is`/`has`/`should`.
- **Data passed to a list/row component is a row's worth, not a parent's
  full bundle.** Keep each component's prop surface focused on its own
  responsibility (no 9-prop god component).

---

## Styling Patterns

**Tailwind v4** is the only styling tool. Inline class names with `cn()`
from `@/lib/utils` for conditional class composition. CSS variables for
shared colors live in `frontend/src/app/globals.css` under `@theme` —
Tailwind v4 will not find them under `:root` alone.

### Status color tokens (do not hardcode)

`bg-status-done` / `bg-status-failed` / `bg-status-awaiting` / `bg-status-tool`
are the canonical chrome for "this worked / this failed / needs human /
an in-flight tool step". A new component picking one of these states uses
the token, never an inline `bg-green-500`.

### Glass / panel recipes

`enterprise-panel` + `bg-surface/75 backdrop-blur-xl` is the standard panel
chrome. Custom gradients or shadow recipes go through a shared utility
in `globals.css` first; per-component one-offs are a smell.

### Tailwind v4 gotcha (from CLAUDE.md)

`bg-popover` requires an explicit alias in `@theme`:
`--color-popover: var(--popover);`. Defining the variable only in `:root`
will not work — Tailwind v4 resolves utility colors at theme build time.

### Base UI Select gotcha

`Select.Trigger` should pass `alignItemWithTrigger={false}`. Custom
`Icon` / `ItemIndicator` slots take **children** (not render props).

---

## Accessibility

- **Semantic HTML first.** Use `<button>` for actions, `<a>` for
  navigation, `<aside>` / `<section>` for layout, `<header>` for page
  headers. Reach for `div role="..."` only when there is no native
  element.
- **Keyboard operability** is a hard requirement: every interactive
  element must be reachable by Tab, every modal/drawer must restore
  focus on close, the command palette must be openable with a known
  chord and escapable with Escape.
- **ARIA only when necessary.** `aria-label` on icon-only buttons,
  `aria-live` for status banners, `aria-valuenow/min/max` on meters.
  No `role="button"` on a `<div>` that could just be a `<button>`.
- **Reduced motion.** All animations honor `prefers-reduced-motion` —
  no transition that blocks input or delays content reveal.
- **Color is never the only signal.** Status text or icon is mandatory
  even when the color token is already on.

---

## Reference Scenarios (preserved from the original vibe-kanban spec)

<!-- These scenarios were authored against the live frontend code; they are preserved here so vibe-kanban/frontend does not lose information that was specific to this package. -->

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


---

## Common Mistakes

### Scenario: Project Prototype Navigation

- Source-backed prototypes read `route_patterns` from validated
  `source_meta_json` through `safeJsonRecord`; malformed metadata contributes
  no routes.
- The preview host exposes one compact project-route selector and keeps the
  outer project page mounted while switching the active prototype.
- Dynamic patterns such as `/collections/:id` match concrete routes, while an
  exact static route wins over a dynamic sibling.
- The sandbox remains `allow-scripts` without `allow-same-origin`. Its injected
  bridge intercepts internal anchors and `data-prototype-route`, then the host
  accepts messages only from the current iframe's `contentWindow`.
- An unknown route produces a visible error toast; it must not silently leave
  the user on the wrong prototype.

- **Self-referential `useCallback` deps.** Adding a `connect` callback to
  its own dependency array — directly or via a helper. TypeScript catches
  it as `Block-scoped variable used before declaration`; ESLint may pass.
  Fix with a ref bridge (see `hook-guidelines.md`).
- **Inlining derivation in render.** Computing "is this over budget?"
  inside the component body makes the rule untestable and means a sibling
  component that needs the same rule will drift. Extract to
  `deriveXxxState(status)` and unit test it.
- **Hard-coded user-visible strings.** Any zh-CN literal in JSX belongs
  in `frontend/src/lib/i18n.ts` and is looked up via `useI18n().t()`. The
  en-US dictionary is the source of truth for the Settings language
  toggle, and the existing i18n coverage test will fail the build if a
  key is registered in one locale but not the other.
- **Reading the issue status into the polling interval incorrectly.**
  The budget meter polls every 30s **only while the issue is active**;
  once done/idle/abandoned, the meter holds its last value. Don't keep
  the interval running after the user navigates away or the issue
  finishes.
- **"Reasonable" magic numbers in chrome.** A border-width here, a
  shadow opacity there — these become drift magnets. New visual
  patterns go through `globals.css` so the next component picks them up
  by design.
