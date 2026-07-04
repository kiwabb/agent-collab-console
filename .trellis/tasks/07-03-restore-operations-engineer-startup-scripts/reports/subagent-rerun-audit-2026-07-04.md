# Subagent Rerun Audit Report - Operations Engineer Startup Scripts

Date: 2026-07-04
Scope: Restore and harden the Operations Engineer one-click startup-script flow after branch merges caused runtime API/i18n regressions.

## Summary

Three read-only subagents reran the failed audit surfaces:

- Frontend runtime/API split contract audit.
- Backend Operations Engineer script-task chain audit.
- Projects page UI/i18n/task-tracking audit.

The main flow is restored: the Projects page exposes the startup-script action next to the run command, the frontend calls `startProjectScriptTask`, the backend creates or reuses an `operations_engineer` `project_script_suggestion` task, and the previously reported missing runtime functions now import from split API modules.

## Confirmed restored

- `getGlobalEventsStreamUrl` is imported from `@/lib/api/health` by `useExecutionProcesses`.
- `getEmbeddingStatus` is imported from `@/lib/api/knowledge` by `AppStatusBar`.
- Runtime source no longer imports the exact monolithic `@/lib/api` barrel.
- `startProjectScriptTask` and `suggestProjectScript` are exported by `frontend/src/lib/api/projects.ts`.
- The Operations Engineer button is rendered by `RunCommandCard` next to the run command UI.
- zh-CN and en-US both contain the startup-script keys.
- Backend `/api/projects/{project_id}/script-task` creates tasks with `role="operations_engineer"`, `task_kind="project_script_suggestion"`, project/session identity, runtime fields, workspace path, and execution-process linkage.
- Backend completion persists effective setup/run command values and emits `project_updated` plus `project_script_updated` events.

## Findings from rerun

### Fixed in this pass

1. Frontend task sheet still used dynamic split API imports.

   Files changed:

   - `frontend/src/features/workbench/components/TaskExecutionSheet.tsx`
   - `frontend/tests/apiCompatibility.test.ts`

   Resolution:

   - Moved `submitCodexTask` and `reviewCodexTask` to top-level static imports.
   - Extended the split API contract test to detect destructured dynamic imports such as `const { x } = await import("@/lib/api/tasks")`.

2. Projects page button state was visually scoped to the active project while the handler enforced a global one-at-a-time task lock.

   Files changed:

   - `frontend/src/features/projects/ProjectsPage.tsx`
   - `frontend/tests/projectRunControls.test.ts`

   Resolution:

   - The run-command card now receives `generating={suggestingProjectId !== null}`, so the button remains visibly generating/disabled while any script task is tracked.

3. Backend active-task reuse did not filter out non-Operations roles.

   Files changed:

   - `backend/app/interfaces/api.py`
   - `backend/tests/test_operations_engineer_script_task.py`

   Resolution:

   - Reuse now skips rows/full tasks whose role is present and not `operations_engineer`.
   - Added a regression test for non-operations `project_script_suggestion` rows not being reused.

4. `task_created` event lacked top-level project/task identity fields.

   Files changed:

   - `backend/app/interfaces/api.py`
   - `backend/tests/test_operations_engineer_script_task.py`

   Resolution:

   - The create event now includes top-level `project_id`, `workspace_id`, `session_id`, `role`, and `task_kind` in addition to the nested serialized task.

5. Monolithic API compatibility comment was outdated.

   File changed:

   - `frontend/src/lib/api.ts`
   - `.trellis/spec/ccgui/frontend/type-safety.md`
   - `.trellis/spec/vibe-kanban/frontend/type-safety.md`

   Resolution:

   - Updated the comment to state that runtime feature code should import split API modules directly; the barrel remains only for narrow legacy/test compatibility.
   - Captured the static split API import convention in Trellis frontend specs.

6. Runtime dynamic split API imports needed a durable guardrail.

   File changed:

   - `frontend/tests/sourceHygiene.test.ts`

   Resolution:

   - Added a source-hygiene test that rejects runtime `import("@/lib/api/<domain>")` unless a future documented exception is added.

7. Global events websocket route was implemented but not mounted.

   File changed:

   - `backend/app/main.py`

   Resolution:

   - Mounted `app.interfaces.ws_events.router` under `/api`, so frontend `getGlobalEventsStreamUrl()` connects to a real `/api/ws/events` websocket route instead of receiving a 403.

8. Project-level Operations Engineer tasks had no backing workspace for the runner.

   Files changed:

   - `backend/app/interfaces/api.py`
   - `backend/tests/test_operations_engineer_script_task.py`

   Resolution:

   - `POST /api/projects/{project_id}/script-task` now ensures a lightweight project workspace exists before starting the task runner. The workspace id remains `project.id`, preserving the existing `session_id/project_id` event contract while satisfying runtimes that load a workspace by `task.session_id`.
   - Added a regression test proving the project workspace is created for the runner.

### Intentionally not changed

- The backend keeps existing project fields when an Operations Engineer suggestion returns an empty `setup_script` or `run_command`.

  Reason:

  - The latest backend Trellis spec explicitly says empty fields must not erase existing project fields and must fall back to current project values consistently across events, `task.result`, and `review_comment`.
  - Existing tests already cover this behavior.

## Residual unverified risks

- The broad worktree remains dirty with unrelated changes; this report only covers the files touched for this task.
- Full frontend `npm test` is not green in the current broad worktree. The rerun exposed unrelated pre-existing/source-copy failures outside this task's touched surface, including older i18n wording assertions and motion/source assertions. The task-relevant frontend tests listed below are green.
- The run-command-adjacent Operations Engineer button was visually verified but not clicked, because clicking creates/reuses a real Operations Engineer task and can start an executor. That side-effect still needs explicit user approval.

## Verification run

1. Frontend full test attempt:

   ```bash
   cd frontend && npm test
   ```

   Result: failed. Important task-relevant finding from the first run was `agentMeshApi.test.ts` failing because the monolithic API compatibility entrypoint did not export `appendConductorMessage`; that was fixed by re-exporting the conductor mesh compatibility functions from `frontend/src/lib/api.ts`.

   Remaining failures observed in the full run are outside this task's focused surface and were not fixed here: legacy i18n wording expectations, motion/source assertions, and other broad frontend copy checks.

2. Frontend focused tests:

   ```bash
   cd frontend && node --import tsx --test tests/agentMeshApi.test.ts tests/apiCompatibility.test.ts tests/apiCompatibilityExports.test.ts tests/sourceHygiene.test.ts tests/projectRunControls.test.ts
   ```

   Result: passed, 25/25.

3. Backend focused tests:

   ```bash
   cd backend && .venv/bin/python -m pytest tests/test_operations_engineer_script_task.py -v
   ```

   Result: passed, 19/19.

4. Backend import smoke:

   ```bash
   cd backend && .venv/bin/python -c "from app.main import app; print(bool(app))"
   ```

   Result: passed, printed `True`.

5. Startup/browser verification:

   Command:

   ```bash
   ./dev-local.sh
   ```

   Result:

   - Backend started on `http://localhost:9000`.
   - Frontend started on `http://localhost:4000`.
   - `/projects` rendered with no browser console errors.
   - The startup command section was visible.
   - The run-command-adjacent button was visible with zh-CN label `调用运维工程师`.
   - No `is not a function` / `TypeError` appeared on the page.
   - After mounting the global events router, backend logs showed `WebSocket /api/ws/events [accepted]`.

6. Side-effect verification:

   Command:

   - Clicked the `调用运维工程师` button once on `/projects`.

   Result:

   - Initial pre-fix click reproduced the real bug: `POST /api/projects/{project_id}/script-task` returned `500` with `Workspace {project_id} not found`.
   - After ensuring the project workspace, a second click succeeded.
   - Frontend showed `已启动运维工程师，完成后会自动更新脚本` with task `ef69f15b...` and status `running`.
   - Backend returned `POST /api/projects/d26a7a4a-9c4b-4da2-a84f-c029416a3351/script-task HTTP/1.1" 200 OK`.
   - Task `ef69f15b-ceb6-484d-b8de-fc9762cbb76a` reached `status="done"`.
   - Task role/kind persisted as `role="operations_engineer"` and `task_kind="project_script_suggestion"`.
   - Project `agent-collab-console` was updated with:
     - `setup_script="cd backend && python3 -m venv .venv314 && .venv314/bin/pip install -r requirements.txt && cd ../frontend && npm install"`
     - `run_command="./dev-local.sh"`
   - Task `review_comment` contains `[OPERATIONS SCRIPT UPDATED]`.
