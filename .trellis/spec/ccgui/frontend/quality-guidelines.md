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
npm test                 # node:test, 100% pass
npm run lint             # 0 warnings
npm run build            # 0 errors, no new console errors at runtime
```

A PR that hasn't run all three is not ready for review.

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
- [ ] `npm test` / `npm run lint` / `npm run build` all green
      locally, with the actual command output attached to the PR
      or task handoff.
- [ ] The change does not introduce a new external dependency
      without a sentence explaining why.
