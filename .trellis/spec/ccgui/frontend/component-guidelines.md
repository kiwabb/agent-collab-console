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

### Scheduling motion convention

Conductor, dispatch, policy-routing, and active tool surfaces use semantic
motion rather than generic pulsing. The contract is:

- Gate the motion behind real scheduling state (running conductor phase,
  `dispatch_batch`, active tool call, streaming project conductor, loading
  routing policy, or `batch_allowed` policy); do not animate idle/history-only
  cards just to add decoration.
- Reuse `AgentThinkingIndicator` with the matching phase:
  `thinking` for policy/LLM analysis, `dispatching` for sub-agent dispatch,
  `tool` for active tool work, and `streaming` for token streams.
- Mark essential feedback with `motion-essential` and pair the active surface
  with the existing `animate-shimmer-sweep` top scan line. Do not introduce a
  new animation name or one-off duration unless it becomes a shared utility in
  `globals.css`.
- Give the animated surface a stable `data-density` value so source-contract
  tests and browser checks can prove the mounted component did not regress.
- Avoid `animate-pulse` on scheduling surfaces; it reads as a generic loading
  placeholder instead of intelligent routing.

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

### Scenario: Prototype Workbench and Generation Completion

#### 1. Scope / Trigger

- Trigger: changing the project prototype main page, its responsive layout,
  plan generation completion behavior, or prototype list metadata.

#### 2. Signatures

- Page coordinator: `ProjectPrototypesPage({ projectId, project })`.
- Page rail: `PrototypePageRail({ prototypes, activeId, onSelect, onCreate })`.
- Preview work area: `PrototypeCanvas({ prototype, versions, routeTargets,
  activeRoutePattern, onNavigate, onVersionsChanged, onPrototypeDeleted })`.
- Completion rule:
  `shouldOpenPrototypeWorkbench(run, navigationRunId) -> boolean`.

#### 3. Contracts

- Desktop uses three operational regions: a compact page rail, a dominant
  preview/code stage, and an inspector for version history, iteration, and
  destructive actions. The preview is the largest region.
- Small screens keep the same information order but render one column. The
  page rail becomes horizontally scrollable and the document itself must not
  overflow horizontally.
- Each page row exposes title, first validated route pattern, current version,
  source kind, and an `aria-current` active state.
- Project-driven generation is the one primary action. Manual creation,
  latest-plan access, and batch regeneration remain available as subordinate
  actions.
- A plan page tracks the `run_id` returned by the generation or retry request.
  It navigates to `/projects/{projectId}/prototypes` only when that exact run
  reaches `completed`.
- Loading an already-completed historical plan never auto-navigates. An active
  run recovered after reload may become the tracked navigation run.
- `partial`, `failed`, and `interrupted` runs remain on the plan page so retry
  controls and failure details stay available.
- Prototype list/detail refresh failures preserve the last valid list and
  preview and render explicit recovery feedback.

#### 4. Validation & Error Matrix

- Tracked run becomes `completed` -> navigate once to the workbench.
- Completed run ID differs from the tracked ID -> remain on the plan page.
- Historical completed run loads with no tracked ID -> remain on the plan page.
- Tracked run becomes `partial`, `failed`, or `interrupted` -> remain and show
  recovery UI.
- List/detail refresh fails -> preserve stale data, log with identity/context,
  and show a visible retry/error message.
- Unknown preview route -> retain the current prototype and show the existing
  route-not-found toast.

#### 5. Good/Base/Bad Cases

- Good: a new three-page generation reaches `completed` and returns to a
  workbench where all three route-backed pages are immediately selectable.
- Base: opening "latest plan" for a historical completed run leaves the review
  page visible.
- Base: a 390 CSS-pixel viewport scrolls page choices horizontally while the
  main preview and inspector remain a single readable column.
- Bad: `useEffect(() => run?.status === "completed" && navigate(), [run])`,
  because historical completed plans become impossible to inspect.
- Bad: clearing `prototypes` or `detail` after a transient refresh error.

#### 6. Tests Required

- Pure tests cover tracked completed, untracked completed, wrong run ID,
  partial, and null run inputs.
- Source/component tests assert the page rail exposes route/source/version,
  active selection, mobile horizontal scrolling, and desktop preview-first
  grid tracks.
- Browser checks cover page selection, Preview/Code switching, route selection,
  historical completed-plan access, and no document overflow on desktop and
  narrow viewports.

#### 7. Wrong vs Correct

Wrong:

```tsx
useEffect(() => {
  if (generationRun?.status === "completed") {
    window.location.assign(`/projects/${projectId}/prototypes`);
  }
}, [generationRun, projectId]);
```

Correct:

```tsx
useEffect(() => {
  if (!shouldOpenPrototypeWorkbench(generationRun, navigationRunIdRef.current)) return;
  if (navigatedRunIdRef.current === generationRun.id) return;
  navigatedRunIdRef.current = generationRun.id;
  window.location.assign(`/projects/${projectId}/prototypes`);
}, [generationRun, projectId]);
```
