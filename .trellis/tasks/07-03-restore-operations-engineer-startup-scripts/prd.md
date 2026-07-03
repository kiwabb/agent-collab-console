# Restore Operations Engineer Startup Script Generation

## Goal

Restore the Operations Engineer role as the one-click path for generating project setup/startup scripts. Users should be able to click the project settings button near the run command, start a real `operations_engineer` task, and have the completed task update `project.setup_script` and `project.run_command` with live UI refresh and localized copy.

## Requirements

- Projects settings must expose the startup-script generation action next to the run command field.
- The action must call a real backend task endpoint rather than only a synchronous suggestion helper.
- Backend must create or reuse a `CodexTask` with `role="operations_engineer"`, `task_kind="project_script_suggestion"`, `project_id`, workspace path, runtime config, and execution process linkage.
- The Operations Engineer task prompt must preserve the setup/run command context supplied by the current request, including explicit empty strings, and remain compatible with older prompt formats.
- Duplicate clicks while an operations task is pending/running/responding must reuse the existing task.
- Operations Engineer completion must parse structured output or fall back to repo inference, then persist `setup_script` and `run_command` on the project.
- Store read/write paths must preserve `project_id`, `provider`, and `model` so task/project associations survive round-trip.
- Backend events must include enough project identity for frontend listeners to refresh project data.
- Frontend event handling must map project update/script update events to `projects:changed`.
- The standalone `/projects` page must still refresh long-running Operations Engineer tasks even when it is not wrapped in the global execution-process WebSocket provider.
- Loading/toast handling must be task-specific so unrelated project tasks do not clear or duplicate the Operations Engineer feedback.
- Polling fallback must stop with visible feedback if the returned task id does not reach a terminal state within the configured polling window.
- Terminal task status derivation must live in a pure frontend helper with focused unit coverage.
- User-visible strings must exist in zh-CN and en-US dictionaries.
- Existing runtime exports used by the app shell must remain available, including global events stream URL and embedding status APIs.

## Acceptance Criteria

- [ ] Clicking the run-command adjacent button starts or reuses an Operations Engineer task through `/api/projects/{project_id}/script-task`.
- [ ] The created Operations Engineer task receives the request's current setup/run command context without replacing explicit empty strings with stale database values.
- [ ] A running duplicate request returns the existing task with `reused=true`.
- [ ] Completed Operations Engineer output updates the project's setup script and run command.
- [ ] If the model output is empty or not parseable as the expected JSON, repository inference is attempted before failing.
- [ ] `project_updated` or `project_script_updated` events refresh Projects UI without manual reload.
- [ ] `/projects` falls back to polling the returned task id until the Operations Engineer task reaches a terminal state.
- [ ] Duplicate WebSocket/polling terminal notifications for the same task do not produce duplicate failure toasts.
- [ ] Polling timeout clears the loading state and shows a failure toast instead of silently stopping.
- [ ] `describeScriptTaskTerminalStatus` correctly classifies success, failure, and active statuses.
- [ ] The front-end no longer throws missing-function runtime errors for `getGlobalEventsStreamUrl` or `getEmbeddingStatus`.
- [ ] i18n keys for the operation exist in both zh-CN and en-US.
- [ ] Backend import/syntax smoke passes for the touched orchestration/API/store modules.
- [ ] Frontend type/build smoke passes or remaining failures are documented with exact blockers.

## Definition of Done

- Code changes are implemented across backend API, store, role workflow, event flow, frontend API/types, project UI, and i18n.
- Focused verification has been run where practical.
- Known residual risks are documented before commit.
- Work is committed after the user approves the commit plan.

## Technical Approach

Use an async task endpoint for the one-click operation. The endpoint creates a durable operations task and starts it via the existing task runner. `RoleWorkflowService` builds an operations-specific prompt, persists parsed or inferred suggestions, saves the project, and emits project update/script update events. The task runner remains responsible for `task_status` events. The frontend calls the new endpoint from the Projects page, keeps a project-scoped loading state, and refreshes from event bus updates plus delayed fallbacks.

The task prompt stores the current request's setup/run command context as JSON and falls back to parsing the older `Existing setup_script/run_command` prompt shape for compatibility with already-created tasks. Explicit empty strings are preserved instead of falling back to stale project values.

The Projects page also polls the returned task id while the Operations Engineer task is running. This is required because `/projects` is not always mounted inside `ExecutionProcessesProvider`, so WebSocket task-status events are not guaranteed on that route. Terminal task handling is de-duplicated by task id.

## Decision (ADR-lite)

Context: The old project script button path behaved like a direct suggestion service and did not reflect the user's designed Operations Engineer role.

Decision: Make the button start a real `operations_engineer` `CodexTask` while preserving the old synchronous suggestion endpoint for compatibility.

Consequences: The workflow is more observable and consistent with role orchestration, but correctness now depends on cross-layer task fields, event payloads, and runtime task completion behavior.

## Out of Scope

- Redesigning the full Projects page layout.
- Replacing the existing runtime catalog or task runner architecture.
- Removing the legacy synchronous `/script-suggestion` endpoint.
- Fully solving unrelated command-palette or prototype-generation changes already present in the worktree.

## Technical Notes

- Backend API: `backend/app/interfaces/api.py`.
- Role persistence: `backend/app/application/role_workflow_service.py`.
- Built-in role seed/catalog: `backend/app/application/agent_seed.py`.
- Store parity: `backend/app/adapters/async_sqlite_store.py`, `backend/app/adapters/sqlite_store.py`.
- Frontend Projects UI: `frontend/src/features/projects/ProjectsPage.tsx`.
- Frontend API/types/i18n: `frontend/src/lib/api.ts`, `frontend/src/lib/types.ts`, `frontend/src/lib/i18n*.ts`.
- Event refresh: `frontend/src/providers/ExecutionProcessesProvider.tsx`, `frontend/src/contexts/ExecutionProcessesContext.tsx`.
- Cross-layer spec context: `.trellis/spec/guides/cross-layer-thinking-guide.md`.
