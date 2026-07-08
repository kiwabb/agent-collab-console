# Quality Guidelines

> Code quality standards for the ccgui frontend package.

---

## Overview

The bar is **"a senior engineer can read the diff in one pass and
trust it."** A change that touches a feature must be reviewable in
under 10 minutes; a change that touches shared infrastructure must
be reviewable in under 20. The toolchain enforces most of the
mechanical rules (lint, typecheck, build, tests), so the reviewer's
job is mostly about shape, naming, and the things the tools cannot
see (state derivation, race conditions, i18n parity).

Every PR must pass, locally, in this order:

```bash
cd frontend
npm audit --registry=https://registry.npmjs.org
npm run typecheck        # strict TypeScript profile, 0 errors
npm test                 # node:test, 100% pass
npm run lint             # 0 warnings
npm run build            # 0 errors, no new console errors at runtime
npm run format:check     # Prettier check for runtime and test TypeScript files
```

A PR that hasn't run all six is not ready for review.

When a `next dev` server is actively serving browser verification from
`frontend/.next`, do not run `npm run build` against that same live
directory. Stop the dev server first, or run the build from an isolated
temporary copy that reuses `node_modules` but has its own `.next`; otherwise
the production build can replace dev artifacts mid-request and produce
spurious 500s such as missing `vendor-chunks` files.

### Scenario: Frontend Stack Version Contract

#### 1. Scope / Trigger

- Trigger: changing `frontend/package.json` framework dependencies or any
  frontend stack description under `.trellis/spec/ccgui/frontend/` or
  `.trellis/spec/vibe-kanban/frontend/`.
- Stack docs are executable guidance for future agents; stale Next/Tailwind/Base
  UI versions can lead to wrong implementation patterns.

#### 2. Signatures

- Dependency source: `frontend/package.json`.
- Canonical specs:
  `.trellis/spec/ccgui/frontend/index.md`,
  `component-guidelines.md`, and `directory-structure.md`.
- Mirror specs:
  `.trellis/spec/vibe-kanban/frontend/index.md`,
  `component-guidelines.md`, and `directory-structure.md`.
- Regression test: `frontend/tests/sourceHygiene.test.ts`, test name
  `frontend stack docs match package versions`.

#### 3. Contracts

- The documented Next.js major version must match the `next` dependency major
  in `frontend/package.json`.
- The documented Tailwind major version must match the `tailwindcss`
  dependency major in `frontend/package.json`.
- Specs that describe the component stack must mention `@base-ui/react` when
  that dependency is present in `frontend/package.json`.
- Both ccgui and vibe-kanban frontend specs must be updated together.
- The current frontend stack is Next.js 15 App Router, Tailwind v4, and
  `@base-ui/react`.

#### 4. Validation & Error Matrix

- `package.json` has `next` outside major 15 -> source hygiene test fails.
- `package.json` has `tailwindcss` outside major 4 -> source hygiene test
  fails.
- `package.json` lacks `@base-ui/react` while stack specs still describe Base
  UI -> source hygiene test fails.
- Any listed frontend spec lacks `Next.js 15`, `Tailwind v4`, or
  `@base-ui/react` -> source hygiene test fails.
- Any listed frontend spec still says `Next.js 14` / `Next 14` -> source
  hygiene test fails.
- Any listed frontend spec still says `Tailwind v3` / `Tailwind CSS v3` ->
  source hygiene test fails.

#### 5. Good/Base/Bad Cases

- Good: package dependencies are `next: ^15.x`, `tailwindcss: ^4.x`, and
  `@base-ui/react`, and every listed stack spec says `Next.js 15`,
  `Tailwind v4`, and `@base-ui/react`.
- Base: a future upgrade to Next 16 or Tailwind 5 updates package, specs, and
  the source hygiene expectation in one change.
- Bad: upgrading `next` / `tailwindcss` or swapping the component primitive
  library while leaving Trellis specs on the old stack.

#### 6. Tests Required

- `cd frontend && node --import tsx --test tests/sourceHygiene.test.ts`.
- Full frontend `npm audit --registry=https://registry.npmjs.org`,
  `npm run typecheck`, `npm test`, `npm run lint`,
  `npm run build`, and `npm run format:check` for stack/tooling changes.

#### 7. Wrong vs Correct

Wrong:

```json
{ "next": "^15.0.0", "tailwindcss": "^4.0.0" }
```

with a spec that says `Next.js 14 App Router` or `Tailwind v3`.

Correct:

```json
{ "next": "^15.0.0", "tailwindcss": "^4.0.0", "@base-ui/react": "^1.4.1" }
```

with specs that say `Next.js 15 App Router`, `Tailwind v4`, and
`@base-ui/react`.

---

### Scenario: Frontend Dependency Audit Boundary

#### 1. Scope / Trigger

- Trigger: changing `frontend/package.json`, `frontend/package-lock.json`,
  npm `overrides`, or moving packages between `dependencies` and
  `devDependencies`.
- Dependency placement is a release-quality contract: production installs
  should not include CLI-only generators, scaffolding tools, or test runners
  that are never imported by runtime code.

#### 2. Signatures

- Dependency source: `frontend/package.json`.
- Lock source: `frontend/package-lock.json`.
- Production audit command:
  `cd frontend && npm audit --omit=dev --registry=https://registry.npmjs.org`.
- Full audit command:
  `cd frontend && npm audit --registry=https://registry.npmjs.org`.
- Runtime import check:
  `rg -n "from ['\"]<package>|import\\(['\"]<package>|\\b<package>\\b" frontend/src frontend/app`.

#### 3. Contracts

- Runtime framework/library packages used by app code stay in
  `dependencies`.
- CLI-only generators such as `shadcn`, test runners such as `tsx`, formatters,
  linters, and build-only helpers stay in `devDependencies` unless runtime code
  imports them.
- Use exact npm `overrides` only for transitive security patches inside the same
  compatible major line, and keep each override narrow enough that `npm ls`
  explains why it exists.
- Do not follow `npm audit fix` when it suggests downgrading the framework
  across incompatible majors; inspect the dependency tree first.
- The default npm mirror may not implement audit endpoints. Use the official npm
  registry for audit evidence.

#### 4. Validation & Error Matrix

- A known CLI/build/test-only package appears under `dependencies` -> the
  `CLI and build tools stay out of production dependencies` source hygiene test
  fails; move it to `devDependencies` after confirming no runtime import exists.
- `npm audit --omit=dev` reports high/critical vulnerabilities -> identify the
  production parent with `npm ls <package>` before changing versions.
- `npm audit fix` suggests an incompatible framework downgrade -> reject the
  automatic fix and apply a targeted package update or override instead.
- Adding or changing a `postcss`/Next/Tailwind override -> `npm run build` must
  pass, because the compiler path is the real compatibility check.

#### 5. Good/Base/Bad Cases

- Good: `shadcn` lives in `devDependencies`, runtime code does not import it,
  and production audit excludes its MCP/Hono/Express CLI tree.
- Base: `next` stays in `dependencies`, but `@next/swc-wasm-nodejs`, `tsx`, and
  format/lint tooling stay in `devDependencies`.
- Bad: a generator package is in `dependencies`, causing production audit to
  report vulnerabilities from packages that never ship in the running app.

#### 6. Tests Required

- `cd frontend && npm audit --omit=dev --registry=https://registry.npmjs.org`.
- `cd frontend && npm audit --registry=https://registry.npmjs.org` when adding
  or changing overrides.
- `cd frontend && node --import tsx --test tests/sourceHygiene.test.ts` to
  enforce dependency placement and runtime import boundaries.
- `cd frontend && npm ls <changed-package> <vulnerable-transitive-package>` to
  prove the resolved tree.
- Full frontend `npm audit --registry=https://registry.npmjs.org`,
  `npm run typecheck`, `npm test`, `npm run lint`,
  `npm run build`, and `npm run format:check` for dependency graph changes.

#### 7. Wrong vs Correct

Wrong:

```json
{
  "dependencies": {
    "next": "^15.5.20",
    "shadcn": "^4.13.0"
  }
}
```

Correct:

```json
{
  "dependencies": {
    "next": "^15.5.20"
  },
  "devDependencies": {
    "shadcn": "^4.13.0"
  }
}
```

---

## Forbidden Patterns

- **`any`** in TypeScript. The `no-explicit-any` ESLint rule
  enforces this. Use `unknown` + a type guard, or define a narrow
  union. The exception is bridging a third-party type we cannot
  change — narrow as soon as you cross the bridge.
- **Hard-coded user-visible strings** in JSX. Every zh-CN literal
  in a component must be looked up via `useI18n().t("key")`. The
  build runs an i18n coverage test that fails if a key is in one
  dictionary but not the other.
- **Ad hoc debug output in runtime source.** Do not ship
  `console.log(...)`, `console.debug(...)`, `console.warn(...)`, or
  `debugger` in `frontend/src`. The source-hygiene test enforces this.
  Existing `console.error(...)` paths are reserved for explicit degradation /
  failure reporting where the UI intentionally continues.
- **Legacy JS/JSX source files.** Runtime source and node tests live in
  `.ts` / `.tsx` files so strict TypeScript, source-hygiene, and import
  contract tests see them. Do not add new `.js` or `.jsx` files under
  `frontend/src` or `frontend/tests`.
- **Polling a value the WS already streams.** If a server event
  carries the value, do not add a poll on top. The poll is for
  values whose growth is silent below a threshold (budget spend
  before soft-warn) — never a substitute for the event stream.
- **`useEffect` to "sync" two pieces of state.** The correct
  pattern is `useMemo` or an inline expression. Effects are for
  side effects.
- **`fetch(...)` outside `lib/api.ts`.** The API client owns
  request shape, dedup, and error normalization. A bare `fetch`
  in a feature is a code smell.
- **Self-referential `useCallback` deps.** TypeScript catches this
  with `Block-scoped variable used before declaration`; ESLint may
  pass. The fix is a ref bridge (see `hook-guidelines.md`).
- **Promoting feature-local logic to `lib/` prematurely.** Move
  to `lib/` when a second feature imports it, not on day one.
- **Magic numbers in chrome** (border widths, shadow opacities,
  animation durations). New visual patterns go through
  `globals.css` first so the next component picks them up by
  design.
- **Six top-level tabs on `/issues/[id]`.** This was the old
  design and the spec explicitly forbids reintroducing it (see
  `component-guidelines.md`, Issue Command Center scenario).

---

## Required Patterns

- **Pure derivation alongside the component.** Every state-derivation
  rule (e.g. "is this issue over budget?", "what's the next action
  on this issue?") lives as an exported pure function next to the
  component, and has a unit test. The component is the renderer;
  the derivation is the rule.
- **Typed API fetches.** A new endpoint gets a typed function in
  `lib/api.ts` and a typed domain type in `lib/types.ts` (or a
  feature-local type if not shared). The shape is declared once.
- **Stateful pure helpers** get unit tests with the same stem.
  `BudgetMeter.tsx` → `tests/budgetMeter.test.ts`. The test file
  is in `tests/`, not next to the component.
- **i18n keys registered in BOTH locales** at the same time. The
  en-US dictionary is the source of truth for the Settings
  language toggle; the zh-CN dictionary is the default locale.
- **WS event subscription** via `useBusEventEffect` with a
  `busEventMatchers` predicate and a `throttleMs >= 600` when
  the same panel re-renders many cards in a burst.
- **Cleanup on unmount.** Any custom subscription, timer, or
  socket must return a cleanup that detaches it. The
  `useBusEventEffect` hook handles its own timer cleanup; do not
  add parallel subscriptions without a paired teardown.

---

## Testing Requirements

- **Pure logic must have unit tests.** Any exported function in
  `lib/` or any pure helper next to a component is testable and
  must be tested. Aim for **behavior**, not implementation
  (derive the state from inputs, assert the result).
- **Threshold tests for derivation logic.** When a rule has a
  threshold (soft-warn at 80%, over at 100%, etc.), the test must
  cover below / at / above. Defensive clamping is its own test.
- **API client tests** mock `globalThis.fetch` and assert the
  URL + method + body shape. The fixture style is
  `withMockFetch(...)` (see any existing test in
  `frontend/tests/`).
- **Source-contract tests assert semantics, not Prettier layout.** When
  a test reads source to prove a motion, import, i18n, or API-split
  contract, use the shared source-test helpers (for example
  `readCompactSource`) and assert stable tokens such as `data-density`,
  `motion-essential`, named imports, or fallback icons. Do not require a
  ternary JSX expression, import quote style, or component props to stay
  on one physical line; formatting-only changes must not break behavior
  contracts.
- **Indexed test assertions prove the fixture shape first.** With
  `noUncheckedIndexedAccess` enabled, tests that need the first result,
  first fetch call, or Nth parsed row use the shared test assertion helper
  (for example `at(items, 0, "fetch call")`) before reading fields. Do not
  scatter `items[0]!` through tests; the assertion message should explain
  which fixture item was expected.
- **Browser verification mocks must satisfy typed API shapes.** When
  a local mock backend drives a real page such as `/issues/[id]`,
  return the exact fields declared in `lib/api.ts` / `lib/types.ts`.
  For issue detail verification, `CodexCostStats.est_cost_usd`,
  `CodexCostStats.pricing.input_per_m`,
  `CodexCostStats.pricing.output_per_m`,
  `PipelineStagesResponse.total_duration_seconds`, and
  `IssueDiffResult.diff` are real UI inputs; omitting them can crash
  status-bar, diff, or right-rail surfaces and invalidate the browser
  result.
- **Browser verification must target a mounted component.** Before
  spending time on DOM or screenshot checks, confirm the route still
  renders the component under test. For example, `/issues/[id]/workflow`
  currently redirects to `/issues/[id]`, so legacy `DagTab` /
  `ConductorLogPanel` changes are proven by source contracts and build
  checks unless that route is reintroduced or a real harness mounts them.
- **No snapshot tests.** They drift; the i18n coverage test and
  the per-feature derivation tests do the work snapshots would.
- **i18n coverage test** (existing) verifies that the zh-CN and
  en-US dictionaries have the same key set. New keys must keep
  this property.

---

## Code Review Checklist

A reviewer should be able to answer YES to **all** of the
following before approving:

- [ ] The change is **scope-limited**: no incidental refactors in
      the same diff, no drive-by reformatting.
- [ ] Every new component is **typed end-to-end** (no `any`, no
      loose `Record<string, unknown>` for shape-bearing data).
- [ ] Every new string is in **both dictionaries**; the i18n
      coverage test passes.
- [ ] Any new **WS event subscription** uses `useBusEventEffect`
      with a matcher, not a raw `addEventListener`.
- [ ] Any new **state-derivation rule** has a unit test that
      covers below / at / above the threshold.
- [ ] Any new **endpoint** has a typed client function and a
      typed return shape.
- [ ] The diff is **readable in one pass** (no nested ternaries,
      no 5-prop god components, no copy-paste boilerplate that
      should be a helper).
- [ ] `npm audit --registry=https://registry.npmjs.org` /
      `npm run typecheck` / `npm test` / `npm run lint` /
      `npm run build` / `npm run format:check` all green
      locally, with the actual command output attached to the PR
      or task handoff.
- [ ] The change does not introduce a new external dependency
      without a sentence explaining why.
