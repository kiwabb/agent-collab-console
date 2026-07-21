# Frontend Development Guidelines

> ccgui frontend package — best practices, conventions, and "why we
> do it this way" notes for the Next.js 15 + Tailwind v4 + @base-ui
> app under `frontend/`.

---

## Overview

This directory contains guidelines for the ccgui frontend package. The
ccgui package owns the entire user-facing surface of the agent-collab
console: the App Router pages, the feature components, the i18n
dictionaries, the API client, and the typed domain models.

The guidelines are the convention source-of-truth for AI coding
sub-agents (and for new team members) — they document the project's
**actual** patterns, not aspirational ones. A pattern that is
described here must exist in the codebase; a pattern that exists in
the codebase but is not described here is a documentation gap that
should be closed.

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Module organization and file layout | Filled |
| [Component Guidelines](./component-guidelines.md) | Component patterns, props, composition, a11y | Filled |
| [Hook Guidelines](./hook-guidelines.md) | Custom hooks, data fetching, WS event subscription | Filled |
| [State Management](./state-management.md) | Local state, context, server state, polling | Filled |
| [Quality Guidelines](./quality-guidelines.md) | Forbidden / required patterns, tests, review checklist | Filled |
| [Type Safety](./type-safety.md) | Domain types, API typing, no-any, validation | Filled |
| [Observability UI](./observability-ui.md) | Audit Log vs Agent Timeline UI and API contracts | Filled |
| [Structured Prototype Drag Placement](./structured-prototype-drag-placement.md) | Pointer grab offsets, direct DOM ownership, registration-driven Freeform remeasurement | Filled |
| [Structured Prototype Snap Attestation](../../vibe-kanban/backend/structured-prototype-snap-attestation.md) | Cross-layer Freeform replay/evidence/worker contract | Filled |

---

## Stack

- **Next.js 15** App Router
- **TypeScript** strict mode (`noUncheckedIndexedAccess`,
  `exactOptionalPropertyTypes`, `noImplicitReturns`,
  `noUnusedLocals`, `noUnusedParameters`, `noUncheckedSideEffectImports`,
  `noPropertyAccessFromIndexSignature`, `allowUnusedLabels: false`,
  `allowUnreachableCode: false`, `noImplicitOverride`)
- **Tailwind v4** (theme tokens via `@theme` in `globals.css`)
- **@base-ui/react** for Select / Dialog / Tabs (NOT shadcn, NOT
  radix directly)
- **zustand / immer** are in `package.json` but the project does
  not currently use them; new code reaches for local state first
- **node:test** for unit tests, no Jest / Vitest
- **`useI18n()`** for any user-visible string

## Cross-cutting conventions

- **i18n parity**: every key registered in `lib/i18n.ts` must be in
  BOTH the `zh-CN` and `en-US` dictionaries. The Settings language
  toggle is the source of truth; the default locale is `zh-CN`.
- **WS event subscription** is centralized in `useBusEventEffect`.
  Components never call `addEventListener` directly.
- **Pure derivation** is the rule for state-derivation logic. Every
  "is X in state Y?" rule is an exported pure function with a
  unit test, next to the consuming component.

## Cross-references

- Backend conventions for the same package: see
  `.trellis/spec/vibe-kanban/backend/`.
- Gotchas and stack notes (e.g. Tailwind v4 theme tokens, Base UI
  Select render-prop quirks) live in `CLAUDE.md` at the repo root;
  treat that file as the runtime cheat sheet and this directory as
  the design guide.

---

**Language**: All documentation in this directory is written in
**English**, even when the surrounding zh-CN UI copy uses Chinese
keys. The English prose is for AI agents and new contributors; the
zh-CN keys are for the UI.
