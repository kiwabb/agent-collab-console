# Directory Structure

> How frontend code is organized in the vibe-kanban package.

---

## Overview

The frontend is a Next.js 14 App Router project. Code is organized by
**feature**, not by type. There is no `src/components/Button.tsx`
sitting next to `src/features/.../Button.tsx`; a component is filed
under the feature that owns it. When two features need the same
component, it is promoted to `frontend/src/components/ui/` or
`frontend/src/lib/`.

A new feature area gets its own folder under
`frontend/src/features/<area>/` and grows there. Cross-feature
promotions go through `frontend/src/hooks/`, `frontend/src/lib/`, or
`frontend/src/providers/` — never through a hidden dependency on a
sibling feature.

---

## Directory Layout

```
frontend/
├── src/
│   ├── app/                       # Next.js App Router pages (route segments)
│   │   ├── layout.tsx             #   global shell, providers
│   │   ├── page.tsx               #   root landing
│   │   ├── issues/[id]/page.tsx   #   /issues/:id  (issue detail)
│   │   ├── projects/[id]/...      #   /projects/:id
│   │   └── ...
│   ├── features/                  # feature-owned components / hooks / helpers
│   │   ├── issues/
│   │   │   ├── IssueDetailPage.tsx        # composition shell
│   │   │   └── components/                # private to the feature
│   │   │       ├── BudgetMeter.tsx
│   │   │       ├── useIssueBudget.ts
│   │   │       └── ...
│   │   ├── projects/
│   │   ├── workbench/
│   │   └── ...
│   ├── components/                # cross-feature primitives only
│   │   ├── runtime/
│   │   └── ui/
│   ├── contexts/                  # React contexts that don't fit under a feature
│   ├── hooks/                     # cross-feature hooks (useBusEventEffect, ...)
│   ├── lib/                       # pure utilities + API client + types + i18n
│   │   ├── api.ts                 #   typed fetchers
│   │   ├── types.ts               #   shared domain types
│   │   ├── i18n.ts                #   zh-CN / en-US dictionaries
│   │   ├── utils.ts               #   cn(), formatters
│   │   └── ...
│   ├── providers/                 # I18nProvider / ThemeProvider / PreferencesProvider
│   ├── store/                     # tiny ad-hoc stores (rare)
│   └── utils/                     # legacy alias; prefer lib/utils
├── tests/                         # node:test unit tests (NOT co-located .test.tsx)
├── public/                        # static assets
├── package.json
├── tsconfig.json
├── next.config.js
└── tailwind.config / globals.css  # Tailwind v4 — see @theme aliases
```

---

## Module Organization

### `app/<route>/page.tsx`

- The **only** file the route segment needs to ship.
- Imports the feature page component (e.g.
  `import { IssueDetailPage } from "@/features/issues/IssueDetailPage"`)
  and renders it inside any layout chrome.
- Composes providers, fetches data the route MUST have before render,
  and applies route-level metadata. No JSX for sub-components.

### `features/<area>/`

- The feature owns its **page component** (if any), its
  **sub-components**, **hooks**, **pure helpers**, and **types**.
- If a sub-component is reusable by another feature, **promote** it:
  - to `components/ui/` if it is a generic primitive
  - to `lib/` if it is a pure utility
  - to `hooks/` if it is a stateful cross-feature hook
- A feature that grows to ~30+ files should split its
  `components/` subdirectory into the feature's own sub-areas.

### `components/`

- Only true primitives (no business logic, no domain types).
- `components/runtime/` — runtime-agnostic UI surfaces that don't
  import feature types.
- `components/ui/` — visual primitives (Button, Card, etc.). The
  project uses `@base-ui/react`; wrap those in `components/ui/`.

### `lib/`

- Pure modules with **no React**.
- `lib/api.ts` is the **only** place that calls `fetch` directly.
  Everything else imports the typed function.
- `lib/i18n.ts` is the **only** place that defines locale strings.
- `lib/types.ts` holds **shared** domain types; feature-local types
  live with the feature.

### `providers/`

- React context providers mounted in `app/layout.tsx`.
- A new provider is rare — only for true app-wide concerns (theme,
  locale, workspace, live event stream).

### `hooks/`

- Cross-feature hooks. A hook that is only used by one feature stays
  inside the feature folder.

### `tests/`

- `node:test` unit tests for the pure helpers in `lib/` and the
  pure derivation logic that lives in `features/.../components/`.
- Co-located `.test.tsx` is **not** used. Test files reference source
  files by relative import.

---

## Naming Conventions

- **Folders**: lowercase with dashes only when unavoidable
  (`features/workbench/components/CommandPalette.tsx`). Prefer
  camelCase: `features/issueCommandCenter/` not
  `features/issue-command-center/`.
- **Components**: PascalCase (`BudgetMeter.tsx`,
  `IssueSideStack.tsx`). One named export per file; default exports
  are reserved for `app/**/page.tsx` and `layout.tsx`.
- **Hooks**: `useXxx.ts`, lowercase camel after the `use` prefix.
- **Pure helpers**: `deriveXxxState.ts` / `xxxHelpers.ts` / `xxxUtils.ts`.
  Pick one suffix and stay consistent inside a directory.
- **Types**: `interface Foo` (not `type Foo` for record-like shapes;
  `type` for unions and mapped types). One type per file is rare —
  colocate with the consuming component.
- **Tests**: `tests/<sourceFileStem>.test.ts`. `BudgetMeter.tsx` →
  `tests/budgetMeter.test.ts`. Test files for a single component sit
  under `tests/` (top level), not next to the source.

---

## Examples

- **Workbench surface area** — `frontend/src/features/workbench/`
  shows the pattern: one folder for the feature, sub-components in a
  `components/` subfolder, types inlined, no business logic outside
  the folder.
- **Issues detail page** — `frontend/src/features/issues/`:
  `IssueDetailPage.tsx` is the thin shell, `components/` holds the
  pieces (SideStack, BudgetMeter, Timeline, Diff, etc.). Hooks and
  pure derivations sit next to the component that owns them.
- **Budget meter** — `features/issues/components/BudgetMeter.tsx` +
  `useIssueBudget.ts` + the pure `deriveBudgetMeterState` in
  `BudgetMeter.tsx` (with its own `tests/budgetMeter.test.ts`).
- **Cross-feature data flow** — the live event bus. WS messages go
  through `EventBus` (server) and `useBusEventEffect` (client). A
  panel that wants to react to `budget_warning` writes a hook in its
  own feature folder and uses `busEventMatchers` to filter.
