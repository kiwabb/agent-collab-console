# Directory Structure

> How backend code is organized in the vibe-kanban backend package.

---

## Overview

The backend is a **FastAPI + aiosqlite** project, not a framework
project. Code is organized by **layer**, not by feature: the
project's mental model is "domain models in `domain/`, application
services in `application/`, persistence in `adapters/`, transport in
`interfaces/`". A new feature area (e.g. budget governance, codex
issues, the conductor) typically spans all four layers, and a
reviewer should be able to find a change in each layer by following
a stable convention.

There is **no DDD-style bounded context** here. The codex / conductor
/ project subsystems share the same store and the same models. A
feature area grows by adding a new service in `application/`, a new
endpoint in `interfaces/api.py`, and a new store method in
`adapters/async_sqlite_store.py` — not by creating a new top-level
package.

---

## Directory Layout

```
backend/
├── app/
│   ├── bootstrap.py              # singleton wiring (store, services, event bus)
│   ├── application/              # use-case orchestration (no I/O imports leak here)
│   │   ├── conductor_main_loop.py
│   │   ├── conductor_tools.py
│   │   ├── budget_service.py     # per-issue budget governance (PR2/PR3)
│   │   ├── role_workflow_service.py
│   │   ├── product_manager_service.py
│   │   ├── timeouts.py           # all concurrency / cost / timeout knobs
│   │   ├── worktree_manager.py
│   │   ├── git_service.py
│   │   └── ...
│   ├── domain/                   # pure dataclasses + enums (no I/O)
│   │   └── models.py             # CodexIssue, CodexTask, ExecutionProcess, RuntimeCatalog, ...
│   ├── adapters/                 # I/O boundary (db, http, fs, external CLI)
│   │   ├── async_sqlite_store.py # the only place SQL is written
│   │   ├── sqlite_store.py       # sync variant for tests + scripts
│   │   ├── codex_runtime.py
│   │   ├── claude_runtime.py
│   │   ├── mock_runtime.py
│   │   └── ...
│   ├── interfaces/               # transport boundary (HTTP / WS)
│   │   ├── api.py                # the FastAPI router; all /api/codex/* + /api/ws/events
│   │   ├── execution_process_views.py
│   │   └── event_bus.py          # in-process ring buffer that the global WS drains
│   ├── project_conductor.py      # cross-issue / project-level Conductor
│   ├── specialist_orchestrator.py
│   ├── audit/                    # audit_log model + sink
│   └── main.py                   # FastAPI app factory + lifespan
├── tests/                        # pytest (asyncio mode = auto)
│   ├── conftest.py
│   ├── test_*.py                 # 1 file per service / endpoint area
│   └── ...
├── scripts/                      # one-off scripts (rare; not for production)
├── requirements.txt
└── console.db                    # local dev sqlite (not committed)
```

---

## Module Organization

### `domain/`

- Pure dataclasses (`CodexIssue`, `CodexTask`, `ExecutionProcess`,
  `RuntimeCatalog`, `Agent`, `WorkflowGraph`, `WorkflowNode`...).
- Pure enums (status, phase, executor, role).
- **No I/O imports**. If you need to load or save, that's a
  store / service concern, not a domain one.
- Dataclasses, not Pydantic models, for the core domain. Pydantic
  models are reserved for HTTP request/response shapes (in
  `interfaces/api.py`).

### `application/`

- Use-case orchestration. A service in `application/` may import
  from `domain/`, `adapters/`, and other `application/` modules.
- Services own **decisions** (e.g. `budget_service.compute_issue_budget_status`
  decides which budget applies and aggregates spend).
- Services **do not** import from `interfaces/`. The transport layer
  is the only thing that imports the application layer's public
  functions.
- `timeouts.py` lives here on purpose — concurrency and cost knobs
  are domain-shaped, not config-shaped. Read them through the
  `timeouts.X()` accessors; do not call `os.getenv` from
  feature code.

### `adapters/`

- I/O boundary. Anything that touches the database, the filesystem,
  an external CLI, or the network lives here.
- `async_sqlite_store.py` is the **only** file that writes SQL.
  All other modules go through the typed methods
  (`load_codex_issue`, `list_codex_tasks`, `save_execution_process`,
  etc.).
- The sync `sqlite_store.py` exists for tests and one-off scripts;
  the async variant is the production path.

### `interfaces/`

- Transport. The FastAPI router in `api.py` is the only HTTP entry
  point; `event_bus.py` is the WS ring buffer that the global
  `/api/ws/events` drains.
- Request/response models are **Pydantic** `BaseModel` subclasses
  defined at the top of `api.py` (or in a sibling
  `*_views.py` for the truly complex ones).
- `execution_process_views.py` is the example of a view-module
  that builds a typed shape for the frontend from the
  internal domain types.

### `bootstrap.py`

- Singleton wiring. Holds the store, services, event bus,
  process manager, worktree manager, and the like. The
  application modules do not import from `bootstrap`; the
  router (`interfaces/api.py`) does.
- New singletons are rare. The existing pattern is: build the
  dependency in `bootstrap.py`, import it as a module-level
  symbol in `api.py`.

---

## Naming Conventions

- **Files / modules**: snake_case (`conductor_main_loop.py`,
  `budget_service.py`, `worktree_manager.py`).
- **Classes**: PascalCase (`CodexIssue`, `ConductorLoop`).
- **Functions / methods**: snake_case. Async functions are
  declared with `async def` and named by their effect
  (`compute_issue_budget_status`, `dispatch_subagent`).
- **Pure dataclasses** with a clear noun (`IssueBudgetStatus`,
  `CandidateModelPrice`) and a `@dataclass(frozen=True)` when
  the shape is meant to be immutable.
- **Service modules** end in `_service.py` (budget_service,
  project_service, etc.) when they own a single cohesive use
  case. Modules that own a more complex orchestrator (the
  conductor) drop the suffix (`conductor_main_loop.py`).
- **Test files** mirror the source: `test_budget_service` →
  `tests/test_budget_steering.py`, `test_conductor_budget_injection.py`.
  Endpoint tests are filed under `tests/test_<endpoint>.py`
  (e.g. `tests/test_issue_budget_endpoint.py`).

---

## Examples

- **Per-issue budget governance** is a clean example of a
  cross-layer feature:
  - `domain/models.py` — `CodexIssue.budget_usd` field
  - `application/budget_service.py` — `compute_issue_budget_status`,
    `IssueBudgetStatus` (the dataclass + its `to_dict()` JSON
    shape), `render_budget_summary` (the COST/BUDGET block
    injected into the conductor prompt)
  - `adapters/async_sqlite_store.py` — `load_codex_issue`,
    `list_codex_tasks`, `list_execution_processes`
  - `interfaces/api.py` — `GET /api/codex/issues/{id}/budget`,
    reusing `compute_issue_budget_status`
  - `application/timeouts.py` — the `DEFAULT_ISSUE_BUDGET_USD`
    and `BUDGET_SOFT_WARN_RATIO` knobs (read through
    accessors, never `os.getenv` from feature code)
- **Conductor orchestration** is a more complex example:
  `application/conductor_main_loop.py` (the loop),
  `application/conductor_tools.py` (the tool surface the
  LLM drives), `interfaces/api.py` (the message / pause /
  resume / state endpoints). All three import from
  `bootstrap.py` for their dependencies.

A new feature that does not fit any of these layers cleanly is a
good prompt for a refactor — a fourth layer usually means a fourth
mental model, and we want the codebase to keep the existing four.
