# Backend Development Guidelines

> Best practices for backend development in the agent-collab console
> backend (the FastAPI + aiosqlite app under `backend/`).

---

## Overview

This directory contains guidelines for the backend. The backend is
the **vibe-kanban** package — the Python app that owns the API,
the database, the conductor, and the project memory. The "vibe-
kanban" name is a legacy from the project's earliest scope; the
running app is the agent-collab console backend.

The guidelines are the convention source-of-truth for AI coding
sub-agents. They document the project's **actual** patterns
(visible in `backend/app/`), not aspirational ones. A pattern
described here must exist in the codebase; a pattern that exists
in the codebase but is not described here is a documentation gap
that should be closed.

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Layered module organization (domain / application / adapters / interfaces) | Filled |
| [Database Guidelines](./database-guidelines.md) | aiosqlite store patterns, migrations, durable leases | Filled |
| [Error Handling](./error-handling.md) | Typed errors, transport mapping, background loop safety | Filled |
| [Project Resume API Contract](./project-resume-api.md) | Project-level resume markdown storage and PDF import API contract | Filled |
| [MCP Management Contract](./mcp-management.md) | Framework-owned MCP registry, catalog API, redacted audit, and Settings UI | Filled |
| [External Prototype Agent](./external-prototype-agent.md) | Project-scoped local Agent pairing, Skill packaging, MCP read/propose tools, and Studio proposal integration | Filled |
| [Structured Prototype Reusable Components](./structured-prototype-reusable-components.md) | Detached component definitions, deterministic cloning, editor placement, AI scope, and MCP command parity | Filled |
| [Structured Prototype Snap Attestation](./structured-prototype-snap-attestation.md) | Shared TypeScript replay authority, evidence v2, checked worker, recovery, and timeout contract | Filled |
| [Quality Guidelines](./quality-guidelines.md) | Forbidden / required patterns, tests, run kinds, QA workflow | Filled |
| [Logging Guidelines](./logging-guidelines.md) | stdlib logging, level conventions, what not to log | Filled |
| [Observability Guidelines](./observability-guidelines.md) | Audit log, Agent Timeline, and trace/span contracts | Filled |

---

## Stack

- **Python 3.12+** with `from __future__ import annotations` at
  the top of every module.
- **FastAPI** for HTTP, native **asyncio** for the conductor +
  WS event bus.
- **aiosqlite** (async) and **sqlite3** (sync, for tests) as the
  storage layer. There is no ORM; SQL lives in
  `adapters/async_sqlite_store.py` and is reached through typed
  methods.
- **Pydantic v2** for request / response models in
  `interfaces/api.py`. Domain models in `domain/models.py` are
  **dataclasses**, not Pydantic models.
- **pytest** with `asyncio_mode=auto` (every test is async by
  default). The `@pytest.mark.slow` marker opts into long
  integration tests; `pytest -v` skips them by default
  (`addopts = "-m 'not slow'"` in `pytest.ini`).
- **concurrent.futures / asyncio.gather** for the parallel
  dispatch (`MAX_PARALLEL_DISPATCH_PER_BATCH` in `timeouts.py`).

## Cross-cutting conventions

- **All concurrency / cost / timeout / feature-flag knobs** live in
  `application/timeouts.py` and are read through typed accessors
  (`timeouts.default_issue_budget_usd()`,
  `timeouts.budget_soft_warn_ratio()`, ...). Env parsing, defaults,
  coercion, and invalid-value fallback stay inside those accessors.
  Feature code never reaches into env vars directly.
- **The store is the only place that writes SQL.** A service
  that needs to read a row goes through a typed store method,
  not a hand-rolled query.
- **The conductor is the supervisor.** Its iteration body never
  raises into the loop; failures are persisted as a `failed`
  conductor task with a traceback in `result_json`, and the
  next turn is decided by the LLM.
- **QA workflow is real.** The QA agent runs the
  `recommended_commands` it proposes; a non-zero exit forces
  `failed` regardless of the LLM's self-report. Lying about a
  green test is the failure mode the system was built to
  prevent.

## Cross-references

- Frontend conventions for the same product: see
  `.trellis/spec/ccgui/frontend/`.
- Stack notes and gotchas (e.g. `timeouts.validate()` invariants,
  the cost-aware scheduling knobs, the WS event envelope shape)
  live in `CLAUDE.md` at the repo root.

---

**Language**: All documentation in this directory is written in
**English**.
