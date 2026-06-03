# Frontend Development Guidelines

> cc-switch package — placeholder index. This package is not in
> active use; see each file's "Status: Not in active use" header.

---

## Overview

The cc-switch spec was scaffolded by `trellis init` as one of the
four default packages (ccgui / MetaGPT / cc-switch / vibe-kanban).
In this repository the **only** packages that appear in real tasks
are `ccgui` (frontend) and `vibe-kanban` (backend). The cc-switch
package is reserved for a future code area that has not yet been
opened.

This index is preserved so the spec tree is complete. It is not a
contract.

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Module organization and file layout | Placeholder |
| [Component Guidelines](./component-guidelines.md) | Component patterns, props, composition | Placeholder |
| [Hook Guidelines](./hook-guidelines.md) | Custom hooks, data fetching patterns | Placeholder |
| [State Management](./state-management.md) | Local state, global state, server state | Placeholder |
| [Quality Guidelines](./quality-guidelines.md) | Code standards, forbidden patterns | Placeholder |
| [Type Safety](./type-safety.md) | Type patterns, validation | Placeholder |

---

## Where the real conventions live

- Frontend conventions for the **actual** frontend in this repo:
  `.trellis/spec/ccgui/frontend/`.
- Backend conventions: `.trellis/spec/vibe-kanban/backend/`.

## When to fill this package

Replace this file with real content the first time a task is
created with `"package": "cc-switch"`. Until then, leave it as a
marker.

---

**Language**: All documentation in this directory should be
written in **English** (matches the rest of the spec tree).
