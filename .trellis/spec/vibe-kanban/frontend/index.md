# Frontend Development Guidelines

> vibe-kanban frontend package — alias spec. The frontend code
> this would cover is **the same** as `.trellis/spec/ccgui/frontend/`
> (Next.js 14 + Tailwind v4 + @base-ui/react). This directory is
> preserved for compatibility with tasks that used
> `"package": "vibe-kanban"` historically; new frontend tasks
> should use `"package": "ccgui"`.

---

## Overview

The vibe-kanban frontend package spec is **an alias for the
ccgui/frontend spec**. The repository has one frontend codebase
under `frontend/`, and both `ccgui` and `vibe-kanban` package
labels refer to the same set of conventions.

**Canonical home**: `.trellis/spec/ccgui/frontend/`. Read that
directory for the actual guidelines. The files in this directory
are kept in sync (currently a copy with a subtitle patch).

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Module organization and file layout | Mirror of ccgui/frontend |
| [Component Guidelines](./component-guidelines.md) | Component patterns, props, composition, a11y | Mirror of ccgui/frontend + preserved Scenarios |
| [Hook Guidelines](./hook-guidelines.md) | Custom hooks, data fetching, WS event subscription | Mirror of ccgui/frontend |
| [State Management](./state-management.md) | Local state, context, server state, polling | Mirror of ccgui/frontend |
| [Quality Guidelines](./quality-guidelines.md) | Forbidden / required patterns, tests, review checklist | Mirror of ccgui/frontend |
| [Type Safety](./type-safety.md) | Domain types, API typing, no-any, validation | Mirror of ccgui/frontend |

---

## Maintenance

When `ccgui/frontend/<file>.md` is updated, mirror the change into
the matching `vibe-kanban/frontend/<file>.md` (only the
"in the ccgui frontend package" → "in the vibe-kanban frontend
package" subtitle differs). The two should not drift.

If a future codebase split creates a real second frontend under
a separate tree, move the vibe-kanban package out of the alias
role and into its own content.

---

**Language**: All documentation in this directory is written in
**English**.
