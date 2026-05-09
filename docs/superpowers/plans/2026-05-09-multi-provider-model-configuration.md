# Multi-Provider Model Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add unified task execution configuration with `executor -> provider -> model`, global runtime catalog management, run-time overrides, and persisted execution snapshots.

**Architecture:** Keep the existing top-level runtime split between `codex` and `claude`, but introduce a shared runtime-catalog layer that resolves executor/provider/model selections into validated runtime settings. Tasks persist default selections, runs persist actual execution snapshots, and the frontend uses a shared three-level selector plus a global configuration page.

**Tech Stack:** FastAPI, Pydantic, SQLite, Next.js, TypeScript, existing Codex/Claude runtimes

---

## Summary

- Extend task data from a single `executor` field to a unified execution configuration: `executor`, `provider`, and `model`.
- Add a global runtime catalog API and SQLite-backed storage for configuring executors, providers, models, defaults, command templates, and environment templates.
- Allow issue creation, task creation, initial run, and rerun to use task defaults or per-run overrides, with overrides written back to the task.
- Preserve current runtime dispatch through `codex` and `claude`, but inject resolved command arguments and environment overrides from the runtime catalog.
- Record actual run-time execution snapshots on each `ExecutionProcess` so the UI and logs can show what was truly executed.

## Implementation Changes

### Backend data and persistence

- Extend `backend/app/domain/models.py`:
  - Add `provider: str | None = None` and `model: str | None = None` to `CodexTask`.
  - Add execution snapshot fields to `ExecutionProcess` or its frontend-facing view:
    - `executor: str | None = None`
    - `provider: str | None = None`
    - `model: str | None = None`
  - Add Pydantic models for runtime catalog data:
    - `RuntimeModelConfig`
    - `RuntimeProviderConfig`
    - `RuntimeExecutorConfig`
    - `RuntimeCatalog`
- Extend both SQLite stores:
  - `backend/app/adapters/sqlite_store.py`
  - `backend/app/adapters/async_sqlite_store.py`
- Add migrations for:
  - `codex_tasks.provider`
  - `codex_tasks.model`
  - execution-process snapshot columns if stored directly
  - a new global table for runtime catalog storage, either:
    - `runtime_catalog_settings`
    - or `system_settings` with one row keyed as `runtime_catalog`
- Add default bootstrap behavior so a fresh DB gets a valid runtime catalog with:
  - `codex` executor present
  - `claude` executor present
  - each executor has at least one enabled provider
  - each provider has at least one enabled model
  - each executor has a valid default provider/model chain

### Backend runtime catalog service

- Add a dedicated application service, e.g. `backend/app/application/runtime_catalog_service.py`, responsible for:
  - loading the catalog from storage
  - validating uniqueness and cross-references
  - normalizing defaults
  - resolving effective run configuration from:
    - run override
    - task default
    - executor default
  - rendering restricted templates for command args and environment overrides
- Supported template placeholders in v1:
  - `{model}`
  - `{provider}`
  - `{workspace_cwd}`
  - `{task_id}`
- Reject invalid templates or selections:
  - unknown executor/provider/model
  - provider not belonging to executor
  - model not belonging to provider
  - disabled executor/provider/model selected as default
  - duplicate IDs within the same scope
- Keep this service pure and reusable by API handlers and task runner code.

### Backend API changes

- Extend request/response contracts in `backend/app/interfaces/api.py`:
  - `CreateTaskRequest` gains `provider` and `model`
  - `UpdateCodexTaskRequest` gains `provider` and `model`
  - add a run override request body for `POST /api/codex/tasks/{task_id}/run`
- Add runtime catalog endpoints:
  - `GET /api/runtime-catalog`
  - `PUT /api/runtime-catalog`
  - optional `POST /api/runtime-catalog/validate`
- API behavior:
  - task creation fills missing provider/model from the executor defaults
  - patching a task validates the resulting executor/provider/model combination before saving
  - running a task resolves effective config in priority order:
    - explicit run override
    - task default
    - executor default
  - if run override differs from task default, persist the new task default before launch
- Keep `POST /api/codex/tasks/{task_id}/request-help` unchanged for v1:
  - `target_executor` remains the only user-supplied routing field
  - helper tasks use the target executor’s default provider/model from the runtime catalog

### Backend task runner and runtimes

- Update `backend/app/application/codex_task_runner.py`:
  - resolve the effective execution config before launching
  - persist the resolved executor/provider/model onto the new `ExecutionProcess`
  - continue to prepend the collaboration hint only when effective executor is `codex`
- Update `backend/app/application/codex_process_manager.py`:
  - keep runtime selection keyed by executor
  - accept resolved command-argument and environment-override payloads
- Update:
  - `backend/app/application/codex_app_server_runtime.py`
  - `backend/app/application/claude_process_runtime.py`
- New behavior:
  - command base still comes from the executor runtime
  - provider-specific command arguments and env overrides are injected after resolution
  - runtime no longer depends only on fixed env vars like `CODEX_APP_SERVER_MODEL` or static `CLAUDE_CMD`
  - runtime must tolerate a provider/model-configured run without breaking legacy defaults
- Keep a compatibility path:
  - if a task has no provider/model and no override, executor defaults from the runtime catalog are used

### Frontend types, APIs, and state

- Extend `frontend/src/lib/types.ts`:
  - `CodexTask.provider`
  - `CodexTask.model`
  - `ExecutionProcess.executor`
  - `ExecutionProcess.provider`
  - `ExecutionProcess.model`
  - runtime catalog request/response types
- Extend `frontend/src/lib/api.ts`:
  - runtime catalog fetch and save functions
  - include `provider` and `model` in create-task and patch-task requests
  - add run override payload for `runCodexTask`
- Update workbench helper flows in:
  - `frontend/src/features/workbench/workbenchActions.ts`
  - `frontend/src/features/workbench/WorkbenchPage.tsx`
- Ensure these flows use a shared execution-config object rather than only executor.

### Frontend UI

- Replace the two-option executor toggle in the main execution flows with a three-level selector component:
  - executor select
  - provider select
  - model select
- Reuse existing UI primitives in `frontend/src/components/ui/select.tsx`.
- Add a new reusable component, e.g. `frontend/src/components/runtime/ExecutionConfigSelector.tsx`.
- Use it in:
  - `frontend/src/features/issues/IssueGrid.tsx`
  - `frontend/src/features/tasks/TaskBoard.tsx`
  - `frontend/src/features/runs/RunDetail.tsx`
  - any task creation / initial run / rerun flow in `WorkbenchPage`
- Interaction rules:
  - changing executor resets provider/model to that executor’s defaults
  - changing provider resets model to that provider’s default
  - disabled providers/models do not appear in normal selection UIs
  - if a selected task points to an invalid or disabled config, the UI displays the fallback that will be used and updates on next save/run
- Add a global runtime configuration page or panel:
  - view current executors/providers/models
  - edit labels and IDs
  - edit defaults
  - edit command templates
  - edit env templates
  - enable/disable providers/models
- Keep the first version pragmatic:
  - no drag-and-drop ordering
  - no per-workspace overrides
  - no secret management UI beyond plain env key/value templates already stored in config

### Execution-process and detail display

- Update execution-process views:
  - `backend/app/interfaces/execution_process_views.py`
  - `frontend` consumers of process payloads
- Show actual run snapshot in the run detail panel:
  - executor
  - provider
  - model
- Task cards may continue to show only executor for density, but detail views should expose provider/model clearly.

## Test Plan

### Backend tests

- Update task API tests in `backend/tests/test_codex_tasks.py`:
  - create task with explicit executor/provider/model
  - create task with missing provider/model and verify defaults applied
  - patch task executor/provider/model combinations
  - reject invalid provider/model combinations
  - run task with overrides and verify task defaults are updated
  - verify execution process snapshot stores resolved config
- Add runtime catalog tests:
  - load default catalog
  - save valid catalog
  - reject duplicate IDs
  - reject broken defaults
  - reject cross-executor provider/model references
  - fallback to executor defaults when task config is missing
- Add help-request coverage:
  - help child task uses target executor default provider/model
- Add runtime wiring tests:
  - codex runtime receives resolved model/env overrides
  - claude runtime receives resolved model/env overrides

### Frontend tests

- Extend `frontend/tests/workbenchActions.test.ts`:
  - create issue with full execution config
  - rerun with updated execution config
- Add selector tests:
  - executor change resets provider/model
  - provider change resets model
  - disabled options excluded
  - fallback applied when config becomes invalid
- Extend API contract tests where applicable for runtime catalog fetch/save and run overrides.

### Manual verification

- Create a new issue using a non-default provider/model and verify the task stores it.
- Run the task and confirm run detail shows the selected executor/provider/model.
- Rerun the task with a different provider/model and verify:
  - the task default updates
  - the new execution process keeps the actual snapshot
  - older execution processes still show their original snapshot
- Disable a provider in the config UI and confirm future runs fall back to the executor default provider/model.

## Assumptions

- The runtime catalog is global for the whole console, not workspace-specific.
- Storage is SQLite-backed, consistent with current task/session persistence.
- v1 keeps `codex` and `claude` as the only top-level executors.
- v1 keeps help-request routing at the executor level only.
- v1 supports only restricted placeholder rendering and does not allow arbitrary shell logic in templates.
