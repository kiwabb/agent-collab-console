# Backend Development Guidelines

> MetaGPT package — placeholder index. This package is not in
> active use; see each file's "Status: Not in active use" header.

---

## Overview

The MetaGPT spec was scaffolded by `trellis init` as one of the
four default packages (ccgui / MetaGPT / cc-switch / vibe-kanban).
In this repository the **only** packages that appear in real tasks
are `ccgui` (frontend) and `vibe-kanban` (backend). The MetaGPT
package is reserved for a future code area that has not yet been
opened.

This index is preserved so the spec tree is complete. It is not a
contract.

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Module organization and file layout | Placeholder |
| [Database Guidelines](./database-guidelines.md) | ORM patterns, queries, migrations | Placeholder |
| [Error Handling](./error-handling.md) | Error types, handling strategies | Placeholder |
| [Quality Guidelines](./quality-guidelines.md) | Code standards, forbidden patterns | Placeholder |
| [Logging Guidelines](./logging-guidelines.md) | Structured logging, log levels | Placeholder |

---

## Where the real conventions live

- Backend conventions for the **actual** backend in this repo:
  `.trellis/spec/vibe-kanban/backend/`.
- Frontend conventions: `.trellis/spec/ccgui/frontend/`.

## When to fill this package

Replace this file with real content the first time a task is
created with `"package": "MetaGPT"`. Until then, leave it as a
marker.

---

**Language**: All documentation in this directory should be
written in **English** (matches the rest of the spec tree).
