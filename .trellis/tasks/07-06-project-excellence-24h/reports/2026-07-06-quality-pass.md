# 2026-07-06 Quality Pass

## Scope

This report records the first stabilization pass for the 24-hour project excellence task. The pass focused on restoring deterministic backend and frontend quality gates while preserving the large pre-existing WIP in the working tree.

## Commands And Results

- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 2 warnings in 64.20s`
- `cd backend && .venv/bin/python -m pytest tests/test_run_issue_conductor_loop.py tests/test_specialist_orchestrator.py tests/test_timeouts.py -q`
  - Result: `231 passed in 9.03s`
- `cd backend && .venv/bin/python -c "from app.main import app; print('backend import ok')"`
  - Result: `backend import ok`
- `cd frontend && npm test`
  - Result: `319 passed`
- `cd frontend && npx tsc --noEmit --pretty false`
  - Result: passed
- `cd frontend && npm run lint`
  - Result: passed, `No ESLint warnings or errors`
- `cd backend && .venv/bin/python -m ruff check .`
  - Result: failed with 543 existing lint issues. This is still open project debt and should not be represented as green.

## Fixes Completed

- Restored backend conductor and specialist orchestration behavior around batch dispatch cleanup, budget enforcement, end-turn protocol balance, terminal sealing, task status events, persisted child results, and retry failure sealing.
- Fixed `dispatch_batch` physical cleanup to use the internal `worktree_key` instead of the user-facing `agent_key`, preventing failed or no-op parallel agents from leaking swarm worktrees when the two keys differ.
- Restored compatibility behavior for narrow test stores that do not expose every production store method.
- Added regression coverage for conductor loop, specialist orchestration, and timeout-related behavior.
- Restored frontend dependency installation by refreshing `frontend/package-lock.json`, including the missing Prettier lock entry.
- Fixed frontend hook dependency warnings in the workbench page while preserving memoized live task/log/message behavior.
- Added safer command handling for `true` / `false` so command-failure tests exercise real non-zero command failures instead of command refusal behavior.

## Residual Risks

- Backend `ruff check .` is now green after the scoped lint burn-down. Earlier
  failed `ruff` entries remain in this report as historical baseline evidence;
  use the latest command results below as the current state.
- The working tree contains many unrelated WIP files from active Trellis tasks. Do not commit or revert those without explicit classification and confirmation.
- `frontend/tsconfig.tsbuildinfo` is a generated file and is currently dirty. Treat it as generated build output unless a later check proves it needs to be intentionally tracked.

## Next Best Targets

1. Reduce backend lint debt in touched files only, starting with files changed during this excellence pass.
2. Capture reusable conventions in `.trellis/spec/` for conductor budget accounting, end-turn/tool-result protocol balance, dispatch batch budget gates, and specialist persisted-result source-of-truth behavior.
3. Re-run full frontend and backend gates after each scoped fix batch and append evidence to this task.

## Follow-up Evidence

- `cd backend && .venv/bin/python -m ruff check app/application/conductor_tools.py app/application/worktree_manager.py app/application/self_improvement_service.py app/application/worktree_claude_hooks.py app/interfaces/codex_ws.py tests/test_conductor_dispatch_batch.py`
  - Result: passed
- `cd backend && .venv/bin/python -m pytest tests/test_conductor_dispatch_batch.py tests/test_dispatch_batch_budget_concurrency.py -q`
  - Result: `18 passed in 0.69s`
- `cd backend && .venv/bin/python -m pytest tests/test_worktree_manager.py -q`
  - Result: `22 passed in 13.67s`
- `cd backend && .venv/bin/python -m pytest tests/test_run_issue_conductor_loop.py tests/test_specialist_orchestrator.py tests/test_timeouts.py tests/test_conductor_dispatch_batch.py tests/test_dispatch_batch_budget_concurrency.py tests/test_worktree_manager.py -q`
  - Result: `98 passed in 14.40s`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 2 warnings in 60.47s`
- `cd backend && .venv/bin/python -c "from app.main import app; print('backend import ok')"`
  - Result: `backend import ok`
- `cd backend && .venv/bin/python -m ruff check . --select F821 --output-format concise`
  - Result: passed, all undefined-name findings cleared
- `cd backend && .venv/bin/python -m ruff check . --statistics`
  - Result: failed as expected on remaining lint debt, now `456 errors` total
- `cd backend && .venv/bin/python -c "from app.main import app; from app.adapters.async_sqlite_store import AsyncSQLiteStore; from app.adapters.sqlite_store import SQLiteStore; from app.application import process_runtime_common; print('imports ok')"`
  - Result: `imports ok`
- `cd backend && .venv/bin/python -m pytest tests/test_prototypes_api.py tests/test_prototype_service.py tests/test_run_issue_conductor_loop.py -q`
  - Result: `69 passed in 10.73s`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 2 warnings in 55.35s`
- `cd backend && .venv/bin/python -m ruff check . --select F401,F841,F821 --output-format concise`
  - Result: passed, all undefined-name / unused-import / unused-variable findings cleared
- `cd backend && .venv/bin/python -m pytest tests/test_browser_smoke_endpoint.py tests/test_codex_version_endpoint.py tests/test_prototype_service.py tests/test_prototypes_api.py tests/test_codex_tasks.py -q`
  - Result: `62 passed, 77 skipped in 21.77s`
- `cd backend && .venv/bin/python -m ruff check . --statistics`
  - Result: failed as expected on remaining lint debt, now `443 errors` total
- `cd backend && .venv/bin/python -c "from app.main import app; from app.interfaces.api import router; print('backend import ok')"`
  - Result: `backend import ok`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 2 warnings in 51.46s`
- `cd backend && .venv/bin/python -m ruff check . --select B007,B905,SIM103,F401,F841,F821 --output-format concise`
  - Result: passed
- `cd backend && .venv/bin/python -m pytest tests/test_runtime_catalog.py tests/test_codex_tasks.py tests/test_prototypes_api.py -q`
  - Result: `48 passed, 77 skipped in 8.73s`
- `cd backend && .venv/bin/python -c "from app.main import app; from app.application.process_runtime_common import is_workspace_console_task; print('backend import ok')"`
  - Result: `backend import ok`
- `cd backend && .venv/bin/python -m ruff check . --statistics`
  - Result: failed as expected on remaining lint debt, now `440 errors` total
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 2 warnings in 58.06s`
- `cd backend && .venv/bin/python -m ruff check app/interfaces/api.py --select W293,W292 --fix`
  - Result: `15 fixed, 0 remaining`
- `cd backend && .venv/bin/python -m ruff check . --select W293,W292 --output-format concise`
  - Result: passed
- `cd backend && .venv/bin/python -m ruff check . --statistics`
  - Result: failed as expected on remaining lint debt, now `425 errors` total
- `cd backend && .venv/bin/python -c "from app.main import app; print('backend import ok')"`
  - Result: `backend import ok`
- `cd backend && .venv/bin/python -m pytest tests/test_browser_smoke_endpoint.py tests/test_codex_version_endpoint.py tests/test_runtime_catalog.py tests/test_prototypes_api.py -q`
  - Result: `51 passed in 8.71s`
- `cd backend && .venv/bin/python -m ruff check . --select UP017,W293,W292,B007,B905,SIM103,F401,F841,F821 --output-format concise`
  - Result: passed
- `cd backend && .venv/bin/python -m ruff check . --statistics`
  - Result: failed as expected on remaining lint debt, now `424 errors` total
- `cd backend && .venv/bin/python -c "from app.main import app; from app.application.runtime_prototype_capture import RuntimePrototypeCaptureService; print('imports ok')"`
  - Result: `imports ok`
- `cd backend && .venv/bin/python -m pytest tests/test_codex_version_endpoint.py tests/test_prototype_service.py tests/test_prototypes_api.py -q`
  - Result: `61 passed in 10.86s`
- `cd backend && .venv/bin/python -m ruff check . --select SIM118 --output-format concise`
  - Result: failed with 92 findings, intentionally not auto-fixed because the findings are mostly `sqlite3.Row` / `aiosqlite.Row` key checks where `key in row` could change semantics.
- `cd backend && .venv/bin/python -m ruff check . --select E702 --output-format concise`
  - Result: passed
- `cd backend && .venv/bin/python -m pytest tests/test_workflow_scheduler_auto_retry.py tests/test_run_issue_conductor_loop.py tests/test_conductor_dispatch_batch.py -q`
  - Result: `26 passed in 0.63s`
- `cd backend && .venv/bin/python -m ruff check . --select E702,SIM108,SIM401,SIM102 --output-format concise`
  - Result: passed
- `cd backend && .venv/bin/python -m pytest tests/test_codex_task_runner.py tests/test_project_script_suggestions.py tests/test_codex_tasks.py tests/test_prototypes_api.py -q`
  - Result: `37 passed, 77 skipped in 5.35s`
- `cd backend && .venv/bin/python -m ruff check . --statistics`
  - Result: failed as expected on remaining lint debt, now `409 errors` total
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 2 warnings in 48.67s`
- `cd backend && .venv/bin/python -m ruff check app/interfaces/api.py --select B904 --output-format concise`
  - Result: passed, `api.py` no longer has bare HTTP raises inside `except` blocks.
- `cd backend && .venv/bin/python -m ruff check . --select B904 --output-format concise`
  - Result: passed, all backend `B904` findings cleared.
- `cd backend && .venv/bin/python -c "from app.main import app; print('backend import ok')"`
  - Result: `backend import ok`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_api.py tests/test_projects_api.py tests/test_codex_api.py tests/test_request_help_endpoint.py tests/test_task_send_endpoint.py tests/test_task_rerun_endpoint.py tests/test_task_refine_endpoint.py tests/test_task_chat_endpoint.py tests/test_runtime_catalog_api_contract.py`
  - Initial result before project/issue git lifecycle fix: failed with 12 `tests/test_projects_api.py` failures around soft abandon, missing-worktree diff recovery, issue reset, conductor restart missing-repo guard, and project remote-status/pull routes.
  - Final result after fix: `70 passed in 16.80s`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_projects_api.py`
  - Result after fix: `34 passed in 14.89s`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result after fix: `1073 passed, 77 skipped, 165 deselected, 2 warnings in 53.52s`
- `cd backend && .venv/bin/python -m ruff check . --statistics`
  - Result: failed as expected on remaining lint debt, now `346 errors` total. `B904` is no longer present; remaining findings are `SIM105` 148, `SIM118` 92, `RUF100` 37, `E402` 32, `I001` 25, `RUF001` 9, and one each of `RUF002`, `RUF022`, `UP037`.
- `git diff --check -- backend/app/interfaces/api.py .trellis/spec/vibe-kanban/backend/quality-guidelines.md .trellis/tasks/07-06-project-excellence-24h/reports/2026-07-06-quality-pass.md`
  - Result: passed, no whitespace errors.
- `cd backend && .venv/bin/python -m ruff check . --output-format concise | rg 'RUF100'`
  - Initial result: 37 current-config `RUF100` findings in backend lint output. A broader `--select RUF100` showed hundreds of historical suppressions for non-enabled rules, so this pass intentionally fixed only the findings emitted by the current project lint configuration.
  - Final result after cleanup: no `RUF100` lines.
- `cd backend && .venv/bin/python -m ruff check . --statistics`
  - Result: failed as expected on remaining lint debt, now `309 errors` total. `RUF100` is no longer present; remaining findings are `SIM105` 148, `SIM118` 92, `E402` 32, `I001` 25, `RUF001` 9, and one each of `RUF002`, `RUF022`, `UP037`.
- `cd backend && .venv/bin/python -c "from app.main import app; from app.adapters.async_sqlite_store import AsyncSQLiteStore; from app.adapters.sqlite_store import SQLiteStore; from app.interfaces import sse; print('imports ok')"`
  - Result: `imports ok`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_prototype_service.py tests/test_prototypes_api.py tests/test_audit_logger.py tests/test_role_workflow_service.py tests/test_task_dispatcher.py tests/test_lifespan_shutdown.py`
  - Result: `95 passed, 1 warning in 11.88s`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 2 warnings in 53.24s`
- `git diff --check -- backend/app/adapters/async_sqlite_store.py backend/app/adapters/sqlite_store.py backend/app/application/audit_logger.py backend/app/application/role_workflow_service.py backend/app/application/runtime_prototype_capture.py backend/app/application/task_dispatcher.py backend/app/interfaces/sse.py backend/app/main.py backend/tests/test_prototype_service.py backend/tests/test_prototypes_api.py .trellis/tasks/07-06-project-excellence-24h/reports/2026-07-06-quality-pass.md`
  - Result: passed, no whitespace errors.
- `cd backend && .venv/bin/python -m ruff check app/interfaces/api.py app/main.py --select SIM105 --output-format concise`
  - Result: passed after converting best-effort cleanup/shutdown `try/except/pass` blocks to `contextlib.suppress(...)`.
- `cd backend && .venv/bin/python -m ruff check . --statistics`
  - Result: failed as expected on remaining lint debt, now `296 errors` total. `SIM105` dropped from 148 to 135; remaining findings are `SIM105` 135, `SIM118` 92, `E402` 32, `I001` 25, `RUF001` 9, and one each of `RUF002`, `RUF022`, `UP037`.
- `cd backend && .venv/bin/python -c "from app.main import app; from app.interfaces.api import router; print('backend import ok')"`
  - Result: `backend import ok`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_projects_api.py tests/test_codex_api.py tests/test_lifespan_shutdown.py tests/test_prototypes_api.py tests/test_prototype_service.py`
  - Result: `98 passed in 26.45s`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 2 warnings in 49.02s`
- `git diff --check -- backend/app/interfaces/api.py backend/app/main.py .trellis/tasks/07-06-project-excellence-24h/reports/2026-07-06-quality-pass.md`
  - Result: passed, no whitespace errors.
- `cd backend && .venv/bin/python -m ruff check app/application/process_runtime_common.py --select SIM105 --output-format concise`
  - Result: passed after converting the file's suppressible best-effort cleanup / event-emission `try/except/pass` blocks to `contextlib.suppress(...)`.
- `cd backend && .venv/bin/python -m ruff check app/application/process_runtime_common.py --output-format concise`
  - Result: passed after also replacing the file's ambiguous fullwidth punctuation in the structured-JSON fallback message.
- `cd backend && .venv/bin/python -c "from app.main import app; from app.application.process_runtime_common import BaseProcessRuntime; print('imports ok')"`
  - Result: `imports ok`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_message_streaming.py tests/test_async_refresh_task_result.py tests/test_reader_loop_finalize.py tests/test_task_chat_endpoint.py tests/test_timeouts.py`
  - Result: `64 passed in 2.92s`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 2 warnings in 55.50s`
- `cd backend && .venv/bin/python -m ruff check . --statistics`
  - Result: failed as expected on remaining lint debt, now `278 errors` total. `SIM105` dropped from 135 to 120; remaining findings are `SIM105` 120, `SIM118` 92, `E402` 32, `I001` 25, `RUF001` 6, and one each of `RUF002`, `RUF022`, `UP037`.
- `git diff --check -- backend/app/application/process_runtime_common.py`
  - Result: passed, no whitespace errors.
- `cd backend && .venv/bin/python -m ruff check app/adapters/sqlite_store.py --select SIM105 --output-format concise`
  - Result: failed as expected on remaining migration lint debt, but sync store `SIM105` dropped from 67 to 53 after converting rollback guards and a small conductor/workflow migration batch to `contextlib.suppress(...)`.
- `cd backend && .venv/bin/python -c "from app.adapters.sqlite_store import SQLiteStore; from app.adapters.async_sqlite_store import AsyncSQLiteStore; print('store imports ok')"`
  - Result: `store imports ok`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_operations_engineer_script_task.py tests/test_audit_logger.py tests/test_subagent_result_builder.py tests/test_workflow_node_batch_key.py tests/test_team_notes.py tests/test_knowledge_index.py`
  - Result: `64 passed in 1.65s`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 2 warnings in 57.20s`
- `cd backend && .venv/bin/python -m ruff check . --statistics`
  - Result: failed as expected on remaining lint debt, now `266 errors` total. `SIM105` dropped from 120 to 108; remaining findings are `SIM105` 108, `SIM118` 92, `E402` 32, `I001` 25, `RUF001` 6, and one each of `RUF002`, `RUF022`, `UP037`.
- `git diff --check -- backend/app/adapters/sqlite_store.py`
  - Result: passed, no whitespace errors.
- `cd backend && .venv/bin/python -m ruff check app/adapters/async_sqlite_store.py --select SIM105 --output-format concise`
  - Result: failed as expected on remaining migration lint debt, but async store `SIM105` dropped from 55 to 47 after converting targeted project/prototype/git/DAG/conductor migration loops to `contextlib.suppress(...)`.
- `cd backend && .venv/bin/python -c "from app.adapters.async_sqlite_store import AsyncSQLiteStore; print('async store import ok')"`
  - Result: `async store import ok`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_project_service.py tests/test_projects_api.py tests/test_prototype_service.py tests/test_prototypes_api.py tests/test_workflow_node_batch_key.py tests/test_team_notes.py tests/test_knowledge_index.py tests/test_audit_logger.py`
  - Result: `136 passed in 27.34s`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 2 warnings in 50.22s`
- `cd backend && .venv/bin/python -m ruff check . --statistics`
  - Result: failed as expected on remaining lint debt, now `258 errors` total. `SIM105` dropped from 108 to 100; remaining findings are `SIM105` 100, `SIM118` 92, `E402` 32, `I001` 25, `RUF001` 6, and one each of `RUF002`, `RUF022`, `UP037`.
- `git diff --check -- backend/app/adapters/async_sqlite_store.py backend/app/adapters/sqlite_store.py .trellis/tasks/07-06-project-excellence-24h/reports/2026-07-06-quality-pass.md`
  - Result: passed, no whitespace errors.
- `cd backend && .venv/bin/python -m ruff check . --select RUF001,RUF002 --output-format concise`
  - Result: passed after replacing the remaining ambiguous Unicode punctuation/symbols in backend production code.
- `cd backend && .venv/bin/python -c "from app.main import app; from app.interfaces.api import router; from app.adapters.async_sqlite_store import AsyncSQLiteStore; print('imports ok')"`
  - Result: `imports ok`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_task_refine_endpoint.py tests/test_task_send_endpoint.py tests/test_api.py tests/test_codex_tasks.py tests/test_project_service.py`
  - Result: `19 passed, 77 skipped in 1.10s`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 2 warnings in 53.20s`
- `cd backend && .venv/bin/python -m ruff check . --statistics`
  - Result: failed as expected on remaining lint debt, now `251 errors` total. `RUF001` and `RUF002` are no longer present; remaining findings are `SIM105` 100, `SIM118` 92, `E402` 32, `I001` 25, and one each of `RUF022`, `UP037`.
- `git diff --check -- backend/app/adapters/async_sqlite_store.py backend/app/interfaces/api.py .trellis/tasks/07-06-project-excellence-24h/reports/2026-07-06-quality-pass.md`
  - Result: passed, no whitespace errors.
- `cd backend && .venv/bin/python -m ruff check . --select RUF022,UP037 --output-format concise`
  - Result: passed after sorting `app.application.audit.__all__` and removing the unnecessary quoted return annotation in `RuntimePrototypeEvidence.from_payload`.
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_audit_logger.py tests/test_prototype_service.py tests/test_prototypes_api.py`
  - Result: `77 passed in 11.42s`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 2 warnings in 50.22s`
- `cd backend && .venv/bin/python -m ruff check . --statistics`
  - Result: failed as expected on remaining lint debt, now `249 errors` total. `RUF022` and `UP037` are no longer present; remaining findings are `SIM105` 100, `SIM118` 92, `E402` 32, and `I001` 25.
- `git diff --check -- backend/app/application/audit/__init__.py backend/app/application/prototype_service.py .trellis/tasks/07-06-project-excellence-24h/reports/2026-07-06-quality-pass.md`
  - Result: passed, no whitespace errors.
- `cd backend && .venv/bin/python -m ruff check app/adapters/async_sqlite_store.py --select SIM105 --unsafe-fixes --fix`
  - Result: `Found 47 errors (47 fixed, 0 remaining).` The generated diff only converted idempotent migration `try/except aiosqlite.OperationalError/pass` blocks to `contextlib.suppress(aiosqlite.OperationalError)`.
- `cd backend && .venv/bin/python -m ruff check app/adapters/async_sqlite_store.py --select SIM105 --output-format concise`
  - Result: passed
- `cd backend && .venv/bin/python -c "from app.adapters.async_sqlite_store import AsyncSQLiteStore; print('async store import ok')"`
  - Result: `async store import ok`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_project_service.py tests/test_projects_api.py tests/test_prototype_service.py tests/test_prototypes_api.py tests/test_workflow_node_batch_key.py tests/test_team_notes.py tests/test_knowledge_index.py tests/test_audit_logger.py tests/test_task_chat_endpoint.py`
  - Result: `145 passed in 28.29s`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 2 warnings in 48.80s`
- `cd backend && .venv/bin/python -m ruff check . --statistics`
  - Result: failed as expected on remaining lint debt, now `202 errors` total. `SIM105` dropped from 100 to 53; remaining findings are `SIM118` 92, `SIM105` 53, `E402` 32, and `I001` 25.
- `git diff --check -- backend/app/adapters/async_sqlite_store.py`
  - Result: passed, no whitespace errors.
- `cd backend && .venv/bin/python -m ruff check app/adapters/sqlite_store.py --select SIM105 --unsafe-fixes --fix`
  - Result: fixed 23 suppressible migration blocks automatically; 30 comment-bearing duplicate-column blocks remained for manual cleanup.
- `cd backend && .venv/bin/python -m ruff check app/adapters/sqlite_store.py --select SIM105 --output-format concise`
  - Result: passed after manually converting the remaining sync-store duplicate-column migration guards to `contextlib.suppress(sqlite3.OperationalError)`.
- `cd backend && .venv/bin/python -c "from app.adapters.sqlite_store import SQLiteStore; from app.adapters.async_sqlite_store import AsyncSQLiteStore; print('store imports ok')"`
  - Result: `store imports ok`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_operations_engineer_script_task.py tests/test_audit_logger.py tests/test_subagent_result_builder.py tests/test_workflow_node_batch_key.py tests/test_team_notes.py tests/test_knowledge_index.py tests/test_project_service.py tests/test_projects_api.py`
  - Result: `103 passed in 20.26s`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 2 warnings in 61.85s`
- `cd backend && .venv/bin/python -m ruff check . --statistics`
  - Result: failed as expected on remaining lint debt, now `149 errors` total. `SIM105` is no longer present; remaining findings are `SIM118` 92, `E402` 32, and `I001` 25.
- `git diff --check -- backend/app/adapters/sqlite_store.py backend/app/adapters/async_sqlite_store.py`
  - Result: passed, no whitespace errors.
- `cd backend && .venv/bin/python -m ruff check . --select I001 --fix`
  - Result: `Found 25 errors (25 fixed, 0 remaining).` The generated diff only sorted/merged import blocks and preserved lazy/local import boundaries.
- `cd backend && .venv/bin/python -m ruff check . --select I001 --output-format concise`
  - Result: passed
- `cd backend && .venv/bin/python -c "from app.main import app; from app.interfaces.api import router; from app.interfaces import sse; from app.application.runtime_catalog_service import RuntimeCatalogService; print('imports ok')"`
  - Result: `imports ok`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_api.py tests/test_projects_api.py tests/test_runtime_catalog.py tests/test_runtime_catalog_api_contract.py tests/test_prototype_service.py tests/test_prototypes_api.py tests/test_audit_logger.py tests/test_lifespan_shutdown.py tests/test_conductor_subagent_timeout.py`
  - Result: `140 passed in 35.58s`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 2 warnings in 61.74s`
- `cd backend && .venv/bin/python -m ruff check . --statistics`
  - Result: failed as expected on remaining lint debt, now `124 errors` total. `I001` is no longer present; remaining findings are `SIM118` 92 and `E402` 32.
- `git diff --check -- backend/app backend/tests .trellis/tasks/07-06-project-excellence-24h/reports/2026-07-06-quality-pass.md`
  - Result: passed, no whitespace errors.
- `cd backend && .venv/bin/python -m ruff check . --select E402 --output-format concise`
  - Result: passed after moving module docstrings before `from __future__ import annotations` in audit/runtime helper modules and moving the runtime-catalog API imports in `interfaces/api.py` to the top-level import block.
- `cd backend && .venv/bin/python -c "from app.main import app; from app.interfaces.api import router, _get_runtime_catalog_service; print('imports ok')"`
  - Result: `imports ok`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_api.py tests/test_runtime_catalog.py tests/test_runtime_catalog_api_contract.py tests/test_audit_logger.py tests/test_prototypes_api.py tests/test_lifespan_shutdown.py`
  - Result: `70 passed in 6.91s`
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 2 warnings in 77.73s`
- `cd backend && .venv/bin/python -m ruff check . --statistics`
  - Result before `SIM118` helper cleanup: failed with only `SIM118` remaining (`92` findings).
- `cd backend && .venv/bin/python -m ruff check . --select SIM118 --output-format concise`
  - Result: passed after adding `_row_has_key(row, key)` helpers in sync/async SQLite stores and replacing row column-presence checks with the helper. The helper keeps the prior `row.keys()` column-name semantics, with one documented `noqa: SIM118` per store.
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_operations_engineer_script_task.py tests/test_audit_logger.py tests/test_subagent_result_builder.py tests/test_workflow_node_batch_key.py tests/test_team_notes.py tests/test_knowledge_index.py tests/test_project_service.py tests/test_projects_api.py tests/test_task_chat_endpoint.py tests/test_prototypes_api.py tests/test_prototype_service.py`
  - Result: `171 passed in 32.08s`
- `cd backend && .venv/bin/python -m ruff check .`
  - Result: passed, all backend ruff findings cleared.
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 2 warnings in 58.67s`
- `git diff --check -- backend/app/adapters/async_sqlite_store.py backend/app/adapters/sqlite_store.py backend/app backend/tests .trellis/tasks/07-06-project-excellence-24h/reports/2026-07-06-quality-pass.md`
  - Result: passed, no whitespace errors.
- `git diff --check -- .trellis/spec/vibe-kanban/backend/database-guidelines.md .trellis/tasks/07-06-project-excellence-24h/reports/2026-07-06-quality-pass.md backend/app/adapters/async_sqlite_store.py backend/app/adapters/sqlite_store.py`
  - Result: passed, no whitespace errors.
- `cd frontend && npx tsc --noEmit --pretty false`
  - Result: passed.
- `cd frontend && npm run test`
  - Result: passed, `319` tests passed. Output included npm's existing `allowBuilds` config warning and Node's `DEP0205` warning from the `tsx` loader.
- `cd frontend && npm run lint`
  - Result: passed, no ESLint warnings or errors. Output included Next's `next lint` deprecation warning.
- `cd frontend && npm run build`
  - Result: passed. Next.js compiled successfully, generated `16/16` static pages, and printed the route-size table. Output included npm's existing `allowBuilds` config warning, Node's `DEP0205` warning, and the existing localStorage experimental warning during static generation.
- `git diff --check -- .trellis/tasks/07-06-project-excellence-24h/reports/2026-07-06-quality-pass.md frontend`
  - Result: passed, no whitespace errors.

## Spec Updates

- Updated `.trellis/spec/vibe-kanban/backend/quality-guidelines.md` with the `dispatch_batch` lineage rule: returned payloads keep user-facing `agent_key`, while failed/no-op/merged physical cleanup uses `worktree_key` when present.
- Updated `.trellis/spec/vibe-kanban/backend/quality-guidelines.md` with the project git lifecycle API contract: remote-status/pull, missing-worktree diff recovery, soft abandon vs finalize cleanup, reset missing-repo safety, and conductor restart repo guards.
- Updated `.trellis/spec/vibe-kanban/backend/database-guidelines.md` with the SQLite Row column-presence convention: use store-local `_row_has_key(row, "column")` instead of changing `key in row.keys()` to `key in row`.

## 2026-07-06 Late Backend Contract Recheck

- Restored and reverified project run API routes in `backend/app/interfaces/api.py`:
  - `POST /api/projects/{project_id}/run/start`
  - `POST /api/projects/{project_id}/run/stop`
  - `GET /api/projects/{project_id}/run/status`
  - `GET /api/projects/{project_id}/run/logs`
- `ProjectRunError` now maps to HTTP `409` with a machine-readable `detail.reason`
  and optional `detail.pattern`, preserving the service-layer typed-error
  boundary.
- Updated `backend/tests/test_swarm_integration.py` for current worktree naming
  and the current `dispatch_batch` hard budget-gate contract.
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_project_run.py`
  - Result: `8 passed`.
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_swarm_integration.py`
  - Result: `10 passed`.
- `cd backend && .venv/bin/python -m pytest -q -m slow --tb=short --disable-warnings`
  - Result: `165 passed, 1150 deselected`.
- `cd backend && .venv/bin/python -m ruff check .`
  - Result: passed.
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 3 warnings in 93.52s`.

## 2026-07-06 Type And Format Baseline

- `cd frontend && npm run format:check`
  - Result: failed on existing repository-wide Prettier baseline, reporting
    `Code style issues found in 190 files`. This is intentionally recorded as
    a baseline instead of running `prettier --write`, because the working tree
    contains broad unrelated WIP and a global formatting rewrite would obscure
    behavioral review.
- `cd backend && .venv/bin/python -m mypy app --show-error-codes --no-pretty`
  - Result: failed on the current backend type baseline with
    `359 errors in 43 files (checked 107 source files)`.
  - High-volume groups include async/sync store union typing in
    `interfaces/api.py`, scheduler/service attribute typing, and historical
    `Any` returns across application services.
- Tightened the new runtime prototype capture path:
  - Added a `RuntimeCaptureService` protocol at the `PrototypeService`
    dependency boundary.
  - Cast the Playwright viewport to its typed `ViewportSize` at the local
    browser adapter boundary.
  - Rewrote `estimated_agent_cost_usd()` legacy-env narrowing so mypy can prove
    the value passed to `float()` is a string.
- `cd backend && .venv/bin/python -m mypy app/application/timeouts.py --show-error-codes --no-pretty`
  - Result: passed for `timeouts.py`; output still notes unused mypy override
    sections in `pyproject.toml`.
- `cd backend && .venv/bin/python -m mypy app/application/runtime_prototype_capture.py app/application/prototype_service.py --show-error-codes --no-pretty`
  - Result: still fails because mypy recursively checks existing dependency
    debt in `runtime_catalog_service.py`, `async_sqlite_store.py`, and
    `llm_runner.py`; no remaining errors are reported in the two target files.
- Re-running full backend mypy after the narrow fixes reduced the baseline from
  `359 errors in 43 files` to `356 errors in 40 files`.
- `cd backend && .venv/bin/python -m ruff check app/application/runtime_prototype_capture.py app/application/prototype_service.py app/application/timeouts.py`
  - Result: passed.
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_prototype_service.py tests/test_prototypes_api.py tests/test_timeouts.py tests/test_budget_supported_concurrency.py tests/test_conductor_dispatch_batch.py`
  - Result: `105 passed`.
- `cd backend && .venv/bin/python -m ruff check .`
  - Result: passed.
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 3 warnings in 74.07s`.

## 2026-07-06 Async Singleton Type Tightening

- Tightened two process-singleton async coordination helpers without changing
  behavior:
  - `backend/app/application/task_completion_registry.py` now declares its
    singleton instance attributes at class scope, so mypy can see `_events`,
    `_results`, `_aliases`, and `_pending`.
  - `backend/app/application/role_concurrency.py` now declares its semaphore
    map and pinned limit, and annotates the async context manager as
    `AsyncIterator[bool]`.
- `cd backend && .venv/bin/python -m mypy app/application/task_completion_registry.py app/application/role_concurrency.py --show-error-codes --no-pretty`
  - Result: passed for both source files; output still notes unused mypy
    override sections in `pyproject.toml`.
- `cd backend && .venv/bin/python -m ruff check app/application/task_completion_registry.py app/application/role_concurrency.py`
  - Result: passed.
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_task_completion_registry.py tests/test_role_concurrency.py tests/test_conductor_subagent_timeout.py tests/test_conductor_dispatch_batch.py tests/test_dispatch_batch_budget_concurrency.py`
  - Result: `38 passed`.
- Re-running full backend mypy after this tightening reduced the baseline to
  `313 errors in 38 files (checked 107 source files)`, down from the earlier
  `359 errors in 43 files`.
- Updated `.trellis/spec/vibe-kanban/backend/quality-guidelines.md` with the
  singleton `__new__` typing convention: declare instance attributes at class
  scope before assigning them on the newly-created singleton object.
- `cd backend && .venv/bin/python -m ruff check .`
  - Result: passed.
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 3 warnings in 66.55s`.

## 2026-07-06 Clarification Type Guard Cleanup

- Tightened `backend/app/application/clarification.py` by replacing an unused
  `type: ignore` with an explicit `isinstance(rc, str)` guard before slicing
  the `[CLARIFY]` review comment.
- `cd backend && .venv/bin/python -m mypy app/application/clarification.py --show-error-codes --no-pretty`
  - Result: passed; output still notes unused mypy override sections in
    `pyproject.toml`.
- `cd backend && .venv/bin/python -m ruff check app/application/clarification.py`
  - Result: passed.
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_qa_workflow.py tests/test_engineer_workflow.py tests/test_subagent_result_builder.py tests/test_conductor_main_loop.py`
  - Result: `90 passed`.
- Re-running full backend mypy after this cleanup reduced the baseline to
  `311 errors in 37 files (checked 107 source files)`.
- `cd backend && .venv/bin/python -m ruff check .`
  - Result: passed.
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 3 warnings in 65.12s`.

## 2026-07-06 Runtime Catalog Type Narrowing

- Tightened `backend/app/application/runtime_catalog_service.py` without
  changing catalog behavior:
  - `load_catalog()` now gives the store-returned catalog an explicit
    `RuntimeCatalog | None` type before the default-catalog fallback.
  - Default provider/model validation uses local `default_provider_id`,
    `default_provider`, and `default_model_id` names to avoid cross-scope type
    reuse.
  - The model whitelist branch asserts `provider is not None` after provider
    resolution has guaranteed it.
- `cd backend && .venv/bin/python -m mypy app/application/runtime_catalog_service.py --show-error-codes --no-pretty`
  - Result: passed; output still notes unused mypy override sections in
    `pyproject.toml`.
- `cd backend && .venv/bin/python -m ruff check app/application/runtime_catalog_service.py`
  - Result: passed.
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_runtime_catalog.py tests/test_runtime_catalog_api_contract.py tests/test_codex_version_endpoint.py`
  - Result: `28 passed`.
- Re-running full backend mypy after this cleanup reduced the baseline to
  `307 errors in 36 files (checked 107 source files)`.
- `cd backend && .venv/bin/python -m ruff check .`
  - Result: passed.
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 3 warnings in 65.54s`.

## 2026-07-06 Conductor Session Registry Typing

- Tightened `backend/app/application/conductor_session_registry.py`:
  - `try_start()` now accepts a coroutine factory instead of any awaitable,
    matching what `asyncio.create_task()` actually requires.
  - The live task handle is typed as `asyncio.Task[object]`.
  - The done callback is a named function instead of a lambda, so mypy can infer
    the callback shape while preserving the same deregistration behavior.
- `cd backend && .venv/bin/python -m mypy app/application/conductor_session_registry.py --show-error-codes --no-pretty`
  - Result: passed; output still notes unused mypy override sections in
    `pyproject.toml`.
- `cd backend && .venv/bin/python -m ruff check app/application/conductor_session_registry.py`
  - Result: passed.
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_conductor_session_registry.py tests/test_conductor_recovery.py tests/test_run_issue_conductor_loop.py`
  - Result: `22 passed`.
- Re-running full backend mypy after this cleanup reduced the baseline to
  `304 errors in 35 files (checked 107 source files)`.
- `cd backend && .venv/bin/python -m ruff check .`
  - Result: passed.
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 165 deselected, 3 warnings in 52.82s`.

## 2026-07-06 API Store Protocol And Workflow DAG Compatibility

- Continued the larger backend API type-safety refactor in
  `backend/app/interfaces/api.py`:
  - Introduced a structural `CodexApiStore` protocol for the async API store
    surface while preserving the module-level `codex_store` monkeypatch seam
    used by tests.
  - Replaced several direct global `codex_store` uses with local
    `_require_codex_store()` references at transport boundaries.
  - Split generic JSON-list parsing from self-improvement evidence JSON object
    parsing to avoid helper name collision and ambiguous return types.
  - Added explicit payload typing for pipeline stages, activity events,
    execution-process message/log helpers, and project service accessors.
  - Preserved the operations script-task narrow test-store fallback by using
    typed callable protocols for optional workspace load/save methods.
- Restored compatibility for the workflow DAG API surface:
  - Added `backend/app/application/workflow_orchestrator.py` with deterministic
    built-in-agent DAG proposal and DAG validation.
  - Reintroduced `materialize_graph_from_dag()` and `WorkflowScheduler.start_graph()`
    compatibility in the current Conductor-era scheduler module.
  - Reworked replan confirm/reject endpoints to use the current store contract
    directly instead of calling removed scheduler methods.
  - Added a regression test proving `/plan`, `/graph` save/get, and
    `/graph/start` work together for a real project/workspace/issue.
- `cd backend && .venv/bin/python -m ruff check app/interfaces/api.py app/application/workflow_scheduler.py app/application/workflow_orchestrator.py tests/test_projects_api.py`
  - Result: passed.
- `cd backend && .venv/bin/python -m mypy app/interfaces/api.py app/application/workflow_scheduler.py app/application/workflow_orchestrator.py --show-error-codes --no-pretty`
  - Result: no errors were reported in the three target files; mypy still
    reports existing dependency debt elsewhere.
- `cd backend && .venv/bin/python -m pytest -q tests/test_projects_api.py::test_workflow_plan_and_graph_endpoints_materialize_compatible_dag --tb=short --disable-warnings`
  - Result: `1 passed`.
- `cd backend && .venv/bin/python -m pytest -q tests/test_operations_engineer_script_task.py --tb=short --disable-warnings`
  - Result: `19 passed`.
- `cd backend && .venv/bin/python -m pytest -q tests/test_projects_api.py tests/test_agents_api.py tests/test_pipeline_stages.py tests/test_task_statuses.py tests/test_workflow_scheduler_auto_retry.py tests/test_artifact_validation_signal.py --tb=short --disable-warnings`
  - Result: `71 passed`.
- `cd backend && .venv/bin/python -c "from app.main import app; print('import-ok')"`
  - Result: passed with `import-ok`.
- `cd backend && .venv/bin/python -m ruff check .`
  - Result: passed.
- `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
  - Result: `1073 passed, 77 skipped, 166 deselected in 56.28s`.
- `cd backend && .venv/bin/python -m mypy app --show-error-codes --no-pretty`
  - Result: still fails, now at `125 errors in 34 files (checked 108 source
    files)`. This is the current type-debt trend metric, not a green gate yet.
- Updated `.trellis/spec/vibe-kanban/backend/quality-guidelines.md` with the
  optional API store capability convention: when endpoint tests intentionally
  use a narrow store stub, preserve existing `getattr` / `callable` fallbacks
  and type them with a small callable Protocol rather than converting them into
  unconditional full-store method calls.
- Final quick re-checks after the spec update and script-task fallback fix:
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q tests/test_operations_engineer_script_task.py tests/test_projects_api.py::test_workflow_plan_and_graph_endpoints_materialize_compatible_dag --tb=short --disable-warnings`
    - Result: `20 passed`.

## 2026-07-06 LLM And Conductor Type Boundary Cleanup

- Tightened `backend/app/application/llm_runner.py` and
  `backend/app/application/conductor_llm.py`:
  - Added a `ResolvedRuntimeExecutor` value so executor selection carries the
    runtime guarantee that `api_endpoint` and `api_key` are non-empty.
  - Typed runtime catalog inputs and reused the resolved executor for
    auto-plan, streaming context, and conductor LLM context creation.
  - Normalized `response.json()` at the HTTP boundary before returning or
    mutating message payload dictionaries.
  - Replaced awaitable duck checks for delta callbacks with a typed helper.
- Tightened `backend/app/application/conductor_tools.py`,
  `backend/app/application/conductor_main_loop.py`, and
  `backend/app/domain/models.py`:
  - Added typed pre-dispatch result handling and typed callback awaiting.
  - Made the conductor loop's `_maybe_await` generic so tool and LLM return
    values keep their shape through dynamic boundaries.
  - Made persisted turn kinds use `ConductorTurnKind` and added the already
    persisted `policy_decision` kind to the domain literal.
- Tightened `backend/app/application/project_conductor.py` and
  `backend/app/application/knowledge_index_service.py`:
  - Annotated project-conductor result/event payloads at the dict boundary and
    cast loaded conductor state from the store boundary.
  - Added a `SearchHit` alias for knowledge-index RRF merge results and
    normalized SQLite row values / merge keys.
- Targeted checks:
  - `cd backend && .venv/bin/python -m mypy app/application/llm_runner.py app/application/conductor_llm.py --show-error-codes --no-pretty`
    - Result: passed.
  - `cd backend && .venv/bin/python -m ruff check app/application/llm_runner.py app/application/conductor_llm.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_llm_runner_streaming.py tests/test_conductor_openai_adapter.py tests/test_conductor_main_loop.py tests/test_run_issue_conductor_loop.py tests/test_prototypes_api.py tests/test_prototype_service.py tests/test_project_script_suggestions.py tests/test_audit_logger.py`
    - Result: `145 passed in 23.37s`.
  - `cd backend && .venv/bin/python -m mypy app/domain/models.py app/application/conductor_tools.py app/application/conductor_main_loop.py --follow-imports=skip --show-error-codes --no-pretty`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_run_issue_conductor_loop.py tests/test_conductor_main_loop.py tests/test_conductor_recovery.py tests/test_audit_logger.py`
    - Result: `73 passed in 1.87s`.
  - `cd backend && .venv/bin/python -m mypy app/application/project_conductor.py --show-error-codes --no-pretty`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_project_conductor.py tests/test_run_issue_conductor_loop.py`
    - Result: `17 passed in 2.77s`.
  - `cd backend && .venv/bin/python -m mypy app/application/knowledge_index_service.py --follow-imports=skip --show-error-codes --no-pretty`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_knowledge_index.py`
    - Result: `11 passed in 0.44s`.
- Full backend checks after the cleanup:
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1073 passed, 77 skipped, 166 deselected, 3 warnings in 62.49s`.
  - `cd backend && .venv/bin/python -m mypy app --show-error-codes --no-pretty`
    - Result: still fails, now at `81 errors in 27 files (checked 108 source
      files)`. This continues the type-debt trend from `125 errors in 34 files`
      before this cleanup.
- Updated `.trellis/spec/vibe-kanban/backend/quality-guidelines.md` with the
  conductor turn kind convention: when a `conductor_turns.kind` value is
  persisted and tested, keep `ConductorTurnKind` in `domain/models.py` in sync
  instead of loosening conductor call sites back to plain `str`.

## 2026-07-06 Product / Architect / Role Workflow Type Cleanup

- Tightened ProductManager and Architect artifact persistence:
  - `ArchitectWorkflow.persist_result()` now advertises its actual return
    contract: normal architect tasks return `SystemDesignDocument`; review tasks
    return `ReviewReportDocument`.
  - `ProductManagerService` keeps old `development_task_list` fallback support
    at the raw JSON dict boundary instead of reading a field that is not part of
    `ProductRequirementDocument`.
  - Dynamic document/router path returns are cast only at the `Path` /
    `RequirementRoute` boundary.
- Tightened `RoleWorkflowService.persist_result()`:
  - The per-role `doc` value is now `object | None`, so product, architect,
    engineer, QA, and specialist documents no longer force one another into the
    first branch's type.
  - `written_files` is read as a dynamic artifact boundary and validated as a
    list before persistence/indexing.
  - Prompt/memory helpers that may come from dynamic modules are normalized to
    `str` at the service boundary.
- Targeted checks:
  - `cd backend && .venv/bin/python -m ruff check app/application/role_workflow_service.py app/application/product_manager_service.py app/application/architect_workflow.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_pipeline_stages.py tests/test_architect_workflow.py tests/test_codex_tasks.py tests/test_subagent_result_builder.py`
    - Result: `24 passed, 77 skipped in 0.57s`.
  - `cd backend && .venv/bin/python -m mypy app --show-error-codes --no-pretty`
    - Result: still fails, now at `71 errors in 24 files (checked 108 source
      files)`.
- Full backend checks after this slice:
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1073 passed, 77 skipped, 166 deselected, 4 warnings in 100.42s`.

## 2026-07-06 Team Notes State Update Cleanup

- Tightened `backend/app/application/team_notes_service.py`:
  - Removed stale private-helper `type: ignore[attr-defined]` comments now that
    `ProjectMemoryService` exposes those helpers to mypy.
  - Replaced the `deleted_at=...` sentinel default with an explicit
    `update_deleted_at` flag so `_upsert_state()` can distinguish “preserve the
    current deleted state” from “set deleted_at to None”.
- Targeted checks:
  - `cd backend && .venv/bin/python -m ruff check app/application/team_notes_service.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/application/team_notes_service.py --show-error-codes --no-pretty`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_team_notes.py tests/test_project_conductor.py tests/test_run_issue_conductor_loop.py`
    - Result: `24 passed in 1.61s`.
- Full backend checks after this cleanup:
  - `cd backend && .venv/bin/python -m mypy app --show-error-codes --no-pretty`
    - Result: still fails, now at `67 errors in 23 files (checked 108 source
      files)`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1073 passed, 77 skipped, 166 deselected, 3 warnings in 57.09s`.

## 2026-07-06 Help Continuation Payload Typing

- Tightened `backend/app/application/help_orchestrator.py`:
  - `_build_continuation_payload()` now returns `dict[str, Any]` and annotates
    its local payload accordingly, matching the real nested `result` / `error`
    payload shape.
- Targeted checks:
  - `cd backend && .venv/bin/python -m ruff check app/application/help_orchestrator.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/application/help_orchestrator.py --show-error-codes --no-pretty`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_help_orchestrator.py tests/test_request_help_endpoint.py tests/test_codex_tasks.py`
    - Result: `14 passed, 77 skipped in 0.49s`.
- Full backend checks after this cleanup:
  - `cd backend && .venv/bin/python -m mypy app --show-error-codes --no-pretty`
    - Result: still fails, now at `65 errors in 22 files (checked 108 source
      files)`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1073 passed, 77 skipped, 166 deselected, 3 warnings in 55.57s`.

## 2026-07-06 Backend Mypy Burn-down To Zero

- Continued the backend type-debt burn-down from the previous `65 errors` /
  `60 errors` slices to a zero-error backend application + benchmark gate.
- Tightened `backend/app/application/skill_service.py`:
  - Replaced the class-scope `list` builtin shadowing problem with module-level
    aliases and typed import result payloads.
  - Removed `Any` from frontmatter parsing/import result boundaries in favor of
    `object` and `TypedDict` shapes.
- Tightened store/runtime/worktree boundaries:
  - `async_sqlite_store.py`: normalized dynamic SQL params and made
    `update_workflow_node(completed_at=...)` validate the datetime/None sentinel
    boundary.
  - `worktree_manager.py`: narrowed swarm agent spec dictionaries, issue branch
    locals, cleanup keys, and merge SHA propagation.
  - `process_runtime_common.py`, `codex_app_server_runtime.py`,
    `claude_process_runtime.py`, `codex_process_manager.py`,
    `codex_task_runner.py`, `main.py`: typed execution-process kinds, runtime
    watchdog metadata, subprocess pipe guards, optional task ids, and background
    task shutdown variables.
- Tightened event/WS/subagent/benchmark surfaces:
  - `event_bus.py` and `ws_events.py`: guarded string fields from dynamic event
    envelopes before calling WS stream managers.
  - `subagent_result_builder.py`: kept dataclass artifact serialization typed.
  - `benchmark/*`: updated stale conductor/API calls, current store object/dict
    access, singleton typing, Pydantic request typing, and calibration score
    narrowing.
- Updated `.trellis/spec/vibe-kanban/backend/quality-guidelines.md` with the
  runtime-entry scratch-state convention: shared `AsyncProcessEntry` state must
  be declared on the dataclass instead of attached ad hoc from a specific
  runtime.
- Targeted checks:
  - `cd backend && .venv/bin/python -m mypy app/application/skill_service.py --show-error-codes --no-pretty`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest tests/test_worktree_manager.py -q --tb=short --disable-warnings`
    - Result: `22 passed in 12.75s`.
  - `cd backend && .venv/bin/python -m pytest tests/test_reader_loop_finalize.py tests/test_message_streaming.py tests/test_async_refresh_task_result.py tests/test_task_chat_endpoint.py -q --tb=short --disable-warnings`
    - Result: `36 passed in 3.11s`.
  - `cd backend && .venv/bin/python -m pytest tests/test_event_bus_ws.py tests/test_message_streaming.py tests/test_subagent_result_builder.py tests/test_agent_catalog.py tests/test_cli_control_payload.py -q --tb=short --disable-warnings`
    - Result: `38 passed in 1.80s`.
  - `cd backend && .venv/bin/python -m pytest tests/test_codex_task_runner.py tests/test_async_refresh_task_result.py tests/test_task_refine_endpoint.py tests/test_task_rerun_endpoint.py tests/test_task_send_endpoint.py -q --tb=short --disable-warnings`
    - Result: `36 passed in 1.56s`.
  - `cd backend && .venv/bin/python -m pytest tests/test_agent_process_environment.py tests/test_lifespan_shutdown.py tests/test_message_streaming.py tests/test_async_refresh_task_result.py tests/test_task_chat_endpoint.py -q --tb=short --disable-warnings`
    - Result: `37 passed in 1.75s`.
  - `cd backend && .venv/bin/python -m pytest tests/test_benchmark_*.py -q --tb=short --disable-warnings`
    - Result: `165 passed in 2.79s`.
- Full backend checks after this burn-down:
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 122 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: final rerun passed, `1073 passed, 77 skipped, 166 deselected, 3 warnings in 85.98s`.
    - Note: one intermediate full run hit a transient failure in
      `tests/test_project_script_suggestions.py::test_verify_project_launch_reaches_local_http_server`;
      the exact test passed immediately when rerun in isolation, and the next
      full backend run passed.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, printed `Agent Collaboration Console`.

## 2026-07-06 Frontend Source-Contract Test Hardening

- Refactored frontend source-contract tests so semantic assertions survive
  harmless Prettier layout changes:
  - Added `frontend/tests/sourceTestUtils.ts` with `readSource`,
    `compactSource`, and `readCompactSource`.
  - Migrated motion/source-contract tests from local `readFileSync` helpers to
    `readCompactSource` where they assert source tokens rather than exact JSX
    line wrapping.
  - Kept the contract checks for `data-density`, `motion-essential`,
    `AgentThinkingIndicator`, split API imports, and spinner regressions, while
    allowing equivalent ternary formatting and quote style.
  - Ran Prettier over `frontend/tests/**/*.{ts,tsx}` after the helper migration.
- Initial check:
  - `cd frontend && npm test`
    - Result: failed with 31 source-contract failures, mostly exact one-line
      JSX / import quote assumptions after formatting.
- Final checks:
  - `cd frontend && npm test`
    - Result: passed, `319 passed, 0 failed`.
  - `cd frontend && npx tsc --noEmit`
    - Result: passed.
  - `cd frontend && npx prettier --write 'tests/**/*.{ts,tsx}'`
    - Result: passed.
  - `git diff --check -- frontend/tests .trellis/tasks/07-06-project-excellence-24h/reports/2026-07-06-quality-pass.md`
    - Result: passed, no whitespace errors.

## 2026-07-06 Frontend Full Gate Rerun

- Full frontend gates after the source-contract test hardening:
  - `cd frontend && npm test`
    - Result: passed, `319 passed, 0 failed`.
  - `cd frontend && npx tsc --noEmit`
    - Result: passed.
  - `cd frontend && npm run lint`
    - Result: passed, `No ESLint warnings or errors`. Next reports that
      `next lint` is deprecated for Next.js 16 migration, but the current
      project command is still green.
  - `cd frontend && npm run build`
    - Result: passed. Build compiled successfully, generated 16 static pages,
      and completed route optimization. It emitted a Node experimental warning
      about localStorage during static generation, but no build error.
  - `cd frontend && npm run format:check`
    - Result: passed, `All matched files use Prettier code style!`.
- Spec update:
  - Added a source-contract testing convention to
    `.trellis/spec/ccgui/frontend/quality-guidelines.md` and mirrored it in
    `.trellis/spec/vibe-kanban/frontend/quality-guidelines.md`: tests that read
    source should assert semantic tokens, not Prettier-sensitive line wrapping
    or quote style.
  - `git diff --check -- .trellis/spec/ccgui/frontend/quality-guidelines.md .trellis/spec/vibe-kanban/frontend/quality-guidelines.md .trellis/tasks/07-06-project-excellence-24h/reports/2026-07-06-quality-pass.md`
    - Result: passed, no whitespace errors.

## 2026-07-06 Backend Current Full Gate Rerun

- Current backend gates after the frontend test/spec pass:
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 122 source files`.
    - Note: mypy emitted informational notes that some untyped function bodies
      are not checked under the current project config; no errors were emitted.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: passed, `1073 passed, 77 skipped, 166 deselected, 3 warnings in 99.69s`.

## 2026-07-06 Frontend Lint CLI Modernization

- Replaced the deprecated `next lint` package script with `eslint .`, using
  the existing flat `eslint.config.js` configuration.
- Fixed the only warning surfaced by the direct ESLint CLI by naming the
  `postcss.config.mjs` default export before exporting it.
- Checks:
  - `cd frontend && npx eslint .`
    - Initial result: exited `0` but emitted one warning for anonymous default
      export in `postcss.config.mjs`.
  - `cd frontend && npm run lint`
    - Final result: passed with no warnings. The script now runs `eslint .`.
  - `cd frontend && npx tsc --noEmit`
    - Result: passed.
  - `cd frontend && npm test`
    - Result: passed, `319 passed, 0 failed`.
  - `cd frontend && npm run build`
    - Result: passed. Build compiled successfully and generated 16 static
      pages; the same Node localStorage experimental warning remains
      non-blocking.

## 2026-07-06 Frontend `noUncheckedIndexedAccess` Enablement

- Context:
  - The frontend spec already described the TypeScript stack as strict with
    `noUncheckedIndexedAccess`, but `frontend/tsconfig.json` still had the
    option disabled.
  - A trial run with `cd frontend && npx tsc --noEmit --noUncheckedIndexedAccess true --pretty false`
    exposed unchecked array/index access across runtime code and tests.
- Runtime hardening:
  - Added explicit guards around diff parsing, split diff row construction,
    conductor decision timeline turns, conductor log timeline entries, focus
    trapping, paste image data URLs, swipe touch events, lazy-load intersection
    entries, toast cleanup, agent message scanning, inbox trend buckets,
    runtime catalog provider edits, prototype selection, task/run selection,
    workbench store patching, and workflow graph queue traversal.
  - These changes avoid assuming `array[index]`, regex capture groups, or
    object-map lookups are always present.
- Test hardening:
  - Added `frontend/tests/testAssertions.ts` with `at(items, index, label)` for
    tests that intentionally require a fixture row, fetch call, parsed diff
    file, or normalized log entry to exist.
  - Migrated API, diff parser, log normalizer, prototype brief, task selection,
    execution-process patch, and conversation-detail tests away from unchecked
    `items[0]` field access.
- Config/spec update:
  - Set `frontend/tsconfig.json` `noUncheckedIndexedAccess` to `true`.
  - Added the indexed test assertion convention to
    `.trellis/spec/ccgui/frontend/quality-guidelines.md` and mirrored it in
    `.trellis/spec/vibe-kanban/frontend/quality-guidelines.md`.
- Checks:
  - `cd frontend && npx tsc --noEmit --noUncheckedIndexedAccess true --pretty false`
    - Result: passed before flipping the tsconfig default.
  - `cd frontend && npx tsc --noEmit --pretty false`
    - Result: passed after enabling `noUncheckedIndexedAccess` in tsconfig.
  - `cd frontend && npm test`
    - Result: passed, `319 passed, 0 failed`.
  - `cd frontend && npm run lint`
    - Result: passed with no warnings.
  - `cd frontend && npm run build`
    - Result: passed. Build compiled successfully and generated 16 static
      pages; the same Node localStorage experimental warning remains
      non-blocking.
  - `cd frontend && npm run format:check`
    - Initial result: failed on `src/features/runs/RunDetail.tsx`.
    - Fix: `cd frontend && npx prettier --write src/features/runs/RunDetail.tsx`.
    - Final result: passed, `All matched files use Prettier code style!`.
  - `git diff --check`
    - Result: passed, no whitespace errors.

## 2026-07-06 Frontend Typecheck Script And Gate Documentation

- Context:
  - The frontend now has a much stricter default TypeScript profile, but the
    package scripts did not expose a stable `typecheck` command.
  - README and frontend quality specs still documented `npx tsc --noEmit` or
    omitted typecheck / format from the required local gate list.
- Tooling update:
  - Added `frontend/package.json` script:
    `typecheck: "tsc --noEmit --pretty false"`.
  - Updated `README.md` frontend quality gates to use `npm run typecheck`,
    `npm test`, `npm run lint`, `npm run build`, and `npm run format:check`.
  - Updated `.trellis/spec/ccgui/frontend/quality-guidelines.md` and the
    `vibe-kanban` frontend mirror so future agents treat all five frontend
    commands as the local readiness gate.
- Checks:
  - `cd frontend && npm run typecheck`
    - Result: passed.

## 2026-07-06 Cross-Stack Gate Rerun

- Frontend status after the strict TypeScript and unused-code passes:
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm test`
    - Result: passed, `319 passed, 0 failed`.
  - `cd frontend && npm run lint`
    - Result: passed with no warnings.
  - `cd frontend && npm run build`
    - Result: passed. Build compiled successfully and generated 16 static
      pages; the existing Node localStorage experimental warning remains
      non-blocking.
  - `cd frontend && npm run format:check`
    - Result: passed, `All matched files use Prettier code style!`.
- Backend status after the frontend quality pass:
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 122 source files`.
    - Note: mypy still emits informational notes that some untyped function
      bodies are not checked under the current config; no errors were emitted.
  - `cd backend && .venv/bin/python -c "from app.main import app; print('backend import ok')"`
    - Result: `backend import ok`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1073 passed, 77 skipped, 166 deselected, 3 warnings in 78.13s`.
- Repository hygiene:
  - `git diff --check`
    - Result: passed, no whitespace errors.

## 2026-07-06 Frontend Side-Effect Import And Dead-Code Compiler Guards

- Context:
  - After `noImplicitReturns` was green, trial strictness checks showed
    `allowUnusedLabels: false` and `allowUnreachableCode: false` were already
    clean.
  - `noUncheckedSideEffectImports` surfaced missing type declarations for CSS
    side-effect imports such as `@/app/globals.css`,
    `highlight.js/styles/github-dark.css`, and `reactflow/dist/style.css`.
- Runtime/type boundary hardening:
  - Added `frontend/global.d.ts` with a CSS module declaration so intentional
    style side-effect imports are visible to TypeScript.
  - Set `frontend/tsconfig.json` `noUncheckedSideEffectImports` to `true`.
  - Set `allowUnusedLabels` and `allowUnreachableCode` to `false`.
- Spec update:
  - Updated `.trellis/spec/ccgui/frontend/type-safety.md` and the
    `vibe-kanban` frontend mirror to include the new compiler guards in the
    default strict TypeScript profile.
- Checks:
  - `cd frontend && npx tsc --noEmit --noUncheckedSideEffectImports true --pretty false`
    - Initial result: failed on CSS side-effect imports without declarations.
    - Final result: passed after adding `frontend/global.d.ts` and enabling
      the option in tsconfig.
  - `cd frontend && npx tsc --noEmit --allowUnusedLabels false --pretty false`
    - Result: passed before flipping the tsconfig default.
  - `cd frontend && npx tsc --noEmit --allowUnreachableCode false --pretty false`
    - Result: passed before flipping the tsconfig default.
  - `cd frontend && npm test`
    - Result: passed, `319 passed, 0 failed`.
  - `cd frontend && npm run lint`
    - Result: passed with no warnings.
  - `cd frontend && npm run format:check`
    - Result: passed, `All matched files use Prettier code style!`.
  - `cd frontend && npm run build`
    - Result: passed. Build compiled successfully and generated 16 static
      pages; the existing Node localStorage experimental warning remains
      non-blocking.
  - `git diff --check`
    - Result: passed, no whitespace errors.

## 2026-07-06 Frontend `noPropertyAccessFromIndexSignature` Enablement

- Context:
  - Trial run:
    `cd frontend && npx tsc --noEmit --noPropertyAccessFromIndexSignature true --pretty false`.
  - Initial result: failed with 294 `TS4111` findings across 22 files.
  - The findings were concentrated at dynamic JSON/event boundaries:
    `codexLogNormalizer`, conductor decision timelines, conductor log panels,
    tool blocks, skill import metadata, agent status parsing, audit log payload
    labels, project conductor thread metadata, provider local-storage parsing,
    and environment-variable access.
- Runtime/type boundary hardening:
  - Converted all index-signature property reads from dot access to explicit
    bracket access, including optional-chain reads such as `payload?.["type"]`.
  - This makes every dynamic payload boundary visually distinct from typed
    domain-object access and lets TypeScript reject accidental future
    `record.foo` reads.
- Config/spec update:
  - Set `frontend/tsconfig.json` `noPropertyAccessFromIndexSignature` to
    `true`.
  - Updated `.trellis/spec/ccgui/frontend/index.md`,
    `.trellis/spec/ccgui/frontend/type-safety.md`, and the `vibe-kanban`
    frontend mirror to include the new compiler guard.
- Checks:
  - `cd frontend && npx tsc --noEmit --noPropertyAccessFromIndexSignature true --pretty false`
    - Initial result: failed with 294 findings across 22 files.
    - Final result: passed after converting dynamic payload property reads.
  - `cd frontend && npx tsc --noEmit --pretty false`
    - Result: passed after enabling the option in tsconfig.
  - `cd frontend && npm test`
    - Result: passed, `319 passed, 0 failed`.
  - `cd frontend && npm run lint`
    - Result: passed with no warnings.
  - `cd frontend && npm run format:check`
    - Result: passed, `All matched files use Prettier code style!`.
  - `cd frontend && npm run build`
    - Result: passed. Build compiled successfully and generated 16 static
      pages; the existing Node localStorage experimental warning remains
      non-blocking.
  - `git diff --check`
    - Result: passed, no whitespace errors.

## 2026-07-06 Frontend Unused Code Compiler Guards

- Context:
  - Trial run:
    `cd frontend && npx tsc --noEmit --noUnusedLocals true --noUnusedParameters true --pretty false`.
  - Initial result: failed with 61 unused-local / unused-parameter findings
    across 21 files.
- Cleanup and behavior fixes:
  - Removed clearly unused imports, local helpers, local state, and test
    fixture factories across shared UI components, benchmarks, help, issues,
    runs, settings, tasks, workbench, hooks, and tests.
  - Preserved public prop/interface shapes where values look like extension
    points, such as `RunDetail` review/executor props, while avoiding unused
    destructuring inside the component body.
  - Wired the workbench command palette state into the actual
    `CommandPalette` component via `open` / `onOpenChange`; previously the
    keyboard shortcut and toolbar button only updated local state that the
    palette did not read.
  - Completed `useSwipeGesture`'s dormant vertical swipe and `enabled` options
    by tracking `currentY`, invoking `onSwipeUp` / `onSwipeDown`, and passing
    `enabled` through `SwipeableCard`.
- Config/spec update:
  - Set `frontend/tsconfig.json` `noUnusedLocals` and `noUnusedParameters` to
    `true`.
  - Updated `.trellis/spec/ccgui/frontend/index.md`,
    `.trellis/spec/ccgui/frontend/type-safety.md`, and the `vibe-kanban`
    frontend mirror to include both compiler guards.
- Checks:
  - `cd frontend && npx tsc --noEmit --noUnusedLocals true --noUnusedParameters true --pretty false`
    - Initial result: failed with 61 findings across 21 files.
    - Final result: passed after cleanup and small wiring fixes.
  - `cd frontend && npx tsc --noEmit --pretty false`
    - Result: passed after enabling the options in tsconfig.
  - `cd frontend && npm test`
    - Result: passed, `319 passed, 0 failed`.
  - `cd frontend && npm run lint`
    - Result: passed with no warnings.
  - `cd frontend && npm run format:check`
    - Result: passed, `All matched files use Prettier code style!`.
  - `cd frontend && npm run build`
    - Result: passed. Build compiled successfully and generated 16 static
      pages; the existing Node localStorage experimental warning remains
      non-blocking.
  - `git diff --check`
    - Result: passed, no whitespace errors.

## 2026-07-06 Frontend `noImplicitReturns` Enablement

- Context:
  - After `exactOptionalPropertyTypes` was green, the next tractable
    TypeScript strictness gate was `noImplicitReturns`.
  - A trial run with `cd frontend && npx tsc --noEmit --noImplicitReturns true --pretty false`
    found five real control-flow gaps in effects and optional callbacks.
- Runtime hardening:
  - Made no-cleanup `useEffect` branches explicitly return `undefined` in
    the auto-save indicator, command palette focus/search effects, and
    workbench connection-status effect.
  - Made optional submit/delete callbacks return an explicit no-op when their
    guarded entity is absent.
- Config/spec update:
  - Set `frontend/tsconfig.json` `noImplicitReturns` to `true`.
  - Updated `.trellis/spec/ccgui/frontend/type-safety.md` and the
    `vibe-kanban` frontend mirror to list `noImplicitReturns` as part of the
    default strict TypeScript profile.
- Checks:
  - `cd frontend && npx tsc --noEmit --noImplicitReturns true --pretty false`
    - Initial result: failed on five implicit return paths.
    - Final result: passed after enabling `noImplicitReturns` in tsconfig.
  - `cd frontend && npm test`
    - Result: passed, `319 passed, 0 failed`.
  - `cd frontend && npm run lint`
    - Result: passed with no warnings.
  - `cd frontend && npm run format:check`
    - Result: passed, `All matched files use Prettier code style!`.
  - `cd frontend && npm run build`
    - Result: passed. Build compiled successfully and generated 16 static
      pages; the existing Node localStorage experimental warning remains
      non-blocking.
  - `git diff --check`
    - Result: passed, no whitespace errors.

## 2026-07-06 Frontend `exactOptionalPropertyTypes` Enablement

- Context:
  - After `noUncheckedIndexedAccess` was green, the next high-value frontend
    strictness gate was `exactOptionalPropertyTypes`.
  - A trial run with `cd frontend && npx tsc --noEmit --exactOptionalPropertyTypes true --pretty false`
    exposed optional-property drift in component props, API request builders,
    log normalization types, task/run override payloads, and tests.
- Runtime and API hardening:
  - Updated optional UI prop types that intentionally pass through
    `undefined` to declare `?: T | undefined`.
  - Converted API/request payload creation toward conditional object spreading
    so absent optional fields are omitted rather than serialized as explicit
    `undefined`.
  - Tightened normalized log/task/project types where explicit undefined can
    flow through UI state, while preserving plain optional fields for
    backend-omitted data.
- Config/spec update:
  - Set `frontend/tsconfig.json` `exactOptionalPropertyTypes` to `true`.
  - Added the exact optional property convention to
    `.trellis/spec/ccgui/frontend/type-safety.md` and mirrored it in
    `.trellis/spec/vibe-kanban/frontend/type-safety.md`.
- Checks:
  - `cd frontend && npx tsc --noEmit --exactOptionalPropertyTypes true --pretty false`
    - Result: passed before flipping the tsconfig default.
  - `cd frontend && npx tsc --noEmit --pretty false`
    - Result: passed after enabling `exactOptionalPropertyTypes` in tsconfig.
  - `cd frontend && npm test`
    - Initial result: failed one stale source-contract assertion that still
      expected `loadingMotionPhase?: string;`.
    - Fix: updated `tests/dagTabMotion.test.ts` to assert the new explicit
      `| undefined` pass-through prop types.
    - Final result: passed, `319 passed, 0 failed`.
  - `cd frontend && npm run lint`
    - Result: passed with no warnings.
  - `cd frontend && npm run format:check`
    - Initial result: failed on four source files with formatting drift after
      the strictness edits.
    - Fix: `cd frontend && npx prettier --write src/features/issues/IssueCard.tsx src/features/issues/SortableIssueCard.tsx src/features/workbench/WorkbenchShell.tsx src/lib/codexLogNormalizer.ts tests/dagTabMotion.test.ts`.
    - Final result: passed, `All matched files use Prettier code style!`.
  - `cd frontend && npm run build`
    - Result: passed. Build compiled successfully and generated 16 static
      pages; the existing Node localStorage experimental warning remains
      non-blocking.
  - `git diff --check`
    - Result: passed, no whitespace errors.

## 2026-07-06 Backend `check_untyped_defs` Enablement

- Context:
  - The next high-leverage backend type gate was checking function bodies even
    where legacy definitions still lack complete annotations.
  - Set `backend/pyproject.toml` default mypy `check_untyped_defs = true` and
    mirrored it in the `app.*` override so untyped application bodies are no
    longer skipped.
- Runtime and typing hardening:
  - Removed redundant `cast(...)` calls from `ProductManagerService` now that
    local return types infer cleanly.
  - Guarded `ClaudeProcessRuntime.write_input_async()` against a closed or
    missing subprocess `stdin`, using the existing respawn-on-broken-pipe path
    instead of relying on `AttributeError`.
  - Typed the lazy bootstrap `codex_process_manager` singleton as either the
    real manager or the mock manager, preserving the lazy import boundary.
- Docs/spec update:
  - Updated backend quality gates in `README.md` and
    `.trellis/spec/vibe-kanban/backend/quality-guidelines.md` so ruff, mypy,
    import smoke, and full pytest are the documented backend default.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Initial result after enabling the gate: failed with six findings.
    - Final result: passed, `Success: no issues found in 122 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m pytest tests/test_agent_process_environment.py tests/test_lifespan_shutdown.py tests/test_codex_tasks.py -q`
    - Combined run printed `4 passed, 77 skipped`, then required interrupt
      during Python thread shutdown. Split reruns exited cleanly:
      `2 passed`, `2 passed`, and `77 skipped`.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1073 passed, 77 skipped, 166 deselected, 3 warnings in 60.77s`.

## 2026-07-06 Backend Strict Module Graduation Batch

- Context:
  - After backend function bodies were checked by default, the next durable
    step was graduating small, stable modules into the per-module strict mypy
    list instead of only relying on the wider baseline.
  - Selected modules with limited surface area and clear payload boundaries:
    adapter result types, fake/CLI adapters, task serialization,
    help-event parsing, and QA failure narrative formatting.
- Type/API hardening:
  - Added shared `AgentArtifact`, `AgentResult`, and `WorkerTaskPayload`
    TypedDicts in `app.adapters.base`.
  - Converted fake and CLI adapters from bare `dict` returns to the shared
    result type.
  - Added JSON field coercion helpers so CLI JSON output is treated as
    `object` until fields pass narrow guards.
  - Typed `serialize_task_payload()` against `CodexTask`.
  - Typed `parse_help_request_event()` with a `HelpRequestEvent` shape and
    string guards for executor/title/prompt fields.
  - Typed QA failure summary inputs as `dict[str, object]` and converted list
    fields through a small guard before rendering.
- Config update:
  - Added eight modules to the strict mypy override list:
    `app.adapters.base`, `app.adapters.claude_cli_adapter`,
    `app.adapters.codex_cli_adapter`, `app.adapters.fake_claude_adapter`,
    `app.adapters.fake_codex_adapter`, `app.application.help_event_parser`,
    `app.application.qa_failure_summary`, and
    `app.application.task_serialization`.
- Spec update:
  - Added the backend convention "Narrow External JSON Before Typed Payloads"
    to `.trellis/spec/vibe-kanban/backend/quality-guidelines.md`.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/task_serialization.py app/application/qa_failure_summary.py app/application/help_event_parser.py app/adapters/base.py app/adapters/fake_codex_adapter.py app/adapters/fake_claude_adapter.py app/adapters/claude_cli_adapter.py app/adapters/codex_cli_adapter.py --strict --follow-imports=skip --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 8 source files`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 122 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m pytest tests/test_help_orchestrator.py tests/test_qa_workflow.py tests/test_run_issue_conductor_loop.py -q`
    - Result: `52 passed in 1.01s`.
  - `cd backend && .venv/bin/python -m pytest tests/test_orchestration_service_statuses.py tests/test_operations_engineer_script_task.py -q`
    - Result: `21 passed in 0.66s`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1073 passed, 77 skipped, 166 deselected, 3 warnings in 60.11s`.

## 2026-07-06 Backend Domain Model Strict Graduation

- Context:
  - A real-import strict probe showed many otherwise-small application modules
    were blocked by bare JSON payload fields in `app.domain.models`.
  - The domain model is a central type dependency, so tightening it removes a
    broader class of false-positive strict failures and catches unsafe payload
    reads in application code.
- Type hardening:
  - Changed unshaped JSON payload fields from bare `dict` / `list[dict]` to
    `dict[str, object]` / `list[dict[str, object]]`:
    `AgentRun.payload`, `SubAgentResult.artifact_json`,
    `SubAgentResult.qa_commands`, `SubAgentResult.critique`,
    `HelpRequest.continuation_payload`, `Agent.input_schema`,
    `Agent.output_schema`, and `ConductorTask.payload`.
  - Fixed the paused Conductor resume path to pass `resume_detail` only when it
    is a non-empty string; previously the untyped payload allowed arbitrary
    objects to flow into the status detail parameter.
- Config update:
  - Added `app.domain.models` and `app.domain.states` to the strict mypy
    override list.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/domain/models.py --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m mypy app/domain/states.py --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 122 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m pytest tests/test_conductor_state_machine.py tests/test_run_issue_conductor_loop.py tests/test_project_conductor.py tests/test_subagent_result_builder.py tests/test_orchestration_service_statuses.py -q`
    - Result: `35 passed in 1.83s`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1073 passed, 77 skipped, 166 deselected, 3 warnings in 57.04s`.

## 2026-07-06 Backend Application Strict Graduation Batch 2

- Context:
  - After domain model payloads were typed, a second batch of small application
    modules could graduate into the strict mypy list.
  - The first default-config run surfaced missing annotations in four modules;
    those were fixed rather than removing the modules from the graduation list.
- Type/runtime hardening:
  - Added strict signatures to clarification helpers using a minimal task
    Protocol while keeping document input as `object` plus `getattr(...)` so
    role documents without the optional field remain tolerated.
  - Added a `SessionStore` Protocol to `SessionService`.
  - Fixed `SessionService` to support both async and sync store methods through
    `_maybe_await()`; this matches the existing bootstrap fallback where the
    effective store can be async or sync.
  - Typed `ApprovalService` against `SessionService`, `Session`, and `Approval`.
  - Typed the agent seeding store boundary with `AgentSeedStore`.
- Config update:
  - Added nine modules to the strict mypy override list:
    `app.application.agent_seed`, `app.application.approval_service`,
    `app.application.clarification`, `app.application.product_manager_router`,
    `app.application.resume_service`, `app.application.role_concurrency`,
    `app.application.session_service`, `app.application.task_status_events`,
    and `app.application.task_statuses`.
- Spec update:
  - Added a database guideline warning against blindly awaiting store methods
    in services that intentionally support both `AsyncSQLiteStore` and the
    sync `SQLiteStore` fallback.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Initial result after adding the modules: failed with 9 missing-annotation
      findings, then 2 boundary findings.
    - Final result: passed, `Success: no issues found in 122 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m pytest tests/test_session_service.py tests/test_approval_service.py tests/test_orchestration_service.py tests/test_orchestration_service_statuses.py tests/test_agent_catalog.py tests/test_agents_api.py -q`
    - Result: `20 passed in 2.43s`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1073 passed, 77 skipped, 166 deselected, 3 warnings in 59.82s`.

## 2026-07-06 Backend Strict Graduation Batch 3

- Context:
  - After Batch 2 and the domain model cleanup, a fresh strict probe using an
    empty mypy config identified additional modules that already satisfy strict
    typing without code changes.
- Config update:
  - Added the following modules to the strict mypy override list:
    `app.domain.ports`, `app.application.conductor_lease`,
    `app.application.conductor_session_registry`,
    `app.application.github_pr_followup`,
    `app.application.product_manager_documents`,
    `app.application.self_improvement_proposal_scheduler`,
    `app.application.self_improvement_service`,
    `app.application.task_completion_registry`, and
    `app.application.workflow_orchestrator`.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 122 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m pytest tests/test_conductor_session_registry.py tests/test_self_improvement_service.py tests/test_self_improvement_proposal_scheduler.py tests/test_project_conductor.py tests/test_agent_catalog.py -q`
    - Result: `42 passed in 3.85s`.
  - `git diff --check`
    - Result: passed, no whitespace errors.

## 2026-07-06 Backend Strict Graduation Batch 4

- Context:
  - The next strict probe targeted four 1-error modules with meaningful
    boundaries: process stream reading, runtime catalog persistence,
    Conductor task dispatch, and execution-process API views.
- Type/runtime hardening:
  - Typed project script subprocess log readers as
    `asyncio.StreamReader | None`.
  - Added `RuntimeCatalogStore` Protocol and made API runtime-catalog service
    construction require `_require_codex_store()`, preserving the established
    503 store-unavailable boundary.
  - Added minimal `DispatchRoleStore`, `DispatchEventBus`, and
    `TaskDispatcherFn` types to `task_dispatcher.dispatch_role()`.
  - Broadened task dispatcher execution from coroutine-only to any awaitable
    result via `inspect.isawaitable()`.
  - Typed `build_execution_process_view()` as `dict[str, object]`.
- Config update:
  - Added four modules to the strict mypy override list:
    `app.application.project_script_suggestions`,
    `app.application.runtime_catalog_service`,
    `app.application.task_dispatcher`, and
    `app.interfaces.execution_process_views`.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/project_script_suggestions.py app/application/runtime_catalog_service.py app/application/task_dispatcher.py app/interfaces/execution_process_views.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 4 source files`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Initial result after adding the modules: failed on two runtime catalog
      API store boundary errors.
    - Final result: passed, `Success: no issues found in 122 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m pytest tests/test_project_script_suggestions.py tests/test_runtime_catalog.py tests/test_task_dispatcher.py tests/test_task_dispatcher_start_failure.py -q`
    - Result: `52 passed in 2.83s`.
  - `cd backend && .venv/bin/python -m pytest tests/test_diagnostics_api.py tests/test_execution_process_kind.py tests/test_codex_tasks.py -q`
    - Result: `24 passed, 77 skipped in 1.19s`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1073 passed, 77 skipped, 166 deselected, 3 warnings in 64.24s`.

## 2026-07-06 Backend Strict Graduation Batch 5

- Context:
  - The next 2-error strict candidates were small modules with clear runtime
    boundaries: code prototype source discovery, Conductor pause control, and
    Claude hook injection into worktrees.
- Type/runtime hardening:
  - Typed `CodePrototypeCandidate.to_dict()` and the source-file iterator.
  - Typed Conductor pause registry in-flight LLM tasks as `asyncio.Task[object]`.
  - Reworked worktree Claude settings merge to treat `settings.json` as
    external JSON: confirm dict/list shapes before reading nested hook fields.
- Config update:
  - Added three modules to the strict mypy override list:
    `app.application.code_prototype_discovery`,
    `app.application.conductor_pause_registry`, and
    `app.application.worktree_claude_hooks`.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/code_prototype_discovery.py app/application/conductor_pause_registry.py app/application/worktree_claude_hooks.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 3 source files`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 122 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m pytest tests/test_prototype_service.py tests/test_worktree_claude_hooks.py tests/test_run_issue_conductor_loop.py -q`
    - Result: `59 passed in 7.23s`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1073 passed, 77 skipped, 166 deselected, 3 warnings in 72.59s`.

## 2026-07-06 Project Gate Refresh

- Context:
  - After multiple backend strictness batches, reran the documented frontend
    gates to keep the task report's project-level evidence current.
- Checks:
  - `cd frontend && npm run typecheck`
    - Result: passed. npm emitted the existing `allowBuilds` config warning.
  - `cd frontend && npm test`
    - Result: `319 passed, 0 failed`. Node emitted the existing
      `module.register()` deprecation warning.
  - `cd frontend && npm run lint`
    - Result: passed.

## 2026-07-07 Frontend Consolidated Quality Gate Batch 80

- Consolidated verification after the JSON boundary sweep, legacy JS cleanup,
  debug-output hygiene, and TypeScript-only source hygiene.
- Checks:
  - `cd frontend && npm test`
    - Result: `370` tests passed.
  - `cd frontend && npm run format:check`
    - Result: passed.
  - `cd frontend && npm run build`
    - Result: passed. Existing npm `allowBuilds` and Node
      `module.register()` warnings remain non-fatal.

## 2026-07-07 Frontend TypeScript-Only Source-Hygiene Batch 79

- Source hygiene:
  - Extended `frontend/tests/sourceHygiene.test.ts` so `frontend/src` and
    `frontend/tests` reject new `.js` / `.jsx` files.
  - Updated ccgui and vibe-kanban frontend quality specs to document that
    runtime source and node tests live in `.ts` / `.tsx` so strict TypeScript
    and source-hygiene checks cover them.
- Checks:
  - `cd frontend && node --import tsx --test tests/sourceHygiene.test.ts`
    - Result: `20` tests passed.
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm run build`
    - Result: passed. Next.js compiled successfully and generated 16 static
      pages; the existing Node localStorage experimental warning remains
      non-blocking.
  - `cd frontend && npm run format:check`
    - Result: passed, `All matched files use Prettier code style!`.
  - `git diff --check`
    - Result: passed, no whitespace errors.

## 2026-07-06 Backend Strict Graduation Batch 6

- Context:
  - Continued the backend strictness burn-down with modules that sit on runtime
    boundaries: token usage extraction/pricing, four-phase preset backfill, and
    orchestration service payloads.
- Type/runtime hardening:
  - Promoted external usage payload extraction to `object` + narrow dict guards.
  - Added shared `read_usage_int()` / `read_usage_float()` helpers so runtime
    process usage persistence no longer converts arbitrary `object` values
    inline.
  - Typed four-phase preset storage with a narrow structural Protocol.
  - Typed orchestration event bus and adapter boundaries, including artifact
    content coercion into the domain `PlanDetails` model when needed.
  - Added a real `AsyncSQLiteStore` regression test for four-phase preset
    insertion, graph backfill, node/edge ordering, and idempotence.
- Config update:
  - Added three modules to the strict mypy override list:
    `app.application.usage_utils`, `app.application.four_phase_preset`, and
    `app.application.orchestration_service`.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/usage_utils.py app/application/four_phase_preset.py app/application/orchestration_service.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 3 source files`.
  - `cd backend && .venv/bin/python -m mypy app/application/usage_utils.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result after adding usage coercion helpers: passed, `Success: no issues
      found in 1 source file`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Initial result after enabling checked bodies exposed
      `process_runtime_common.py` usage coercion errors.
    - Final result: passed, `Success: no issues found in 122 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, printed `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest tests/test_per_model_pricing.py tests/test_four_phase_preset.py tests/test_orchestration_service.py tests/test_orchestration_service_statuses.py tests/test_agent_catalog.py -q`
    - Result: `33 passed in 2.15s`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 3 warnings in 68.31s`.

## 2026-07-06 Backend Strict Graduation Batch 7

- Context:
  - Instead of only chasing isolated 1-error files, scanned remaining
    application modules for shared strictness blockers. The largest low-risk
    hotspots were the unified audit writer/recorders and Engineer/QA specialist
    request payloads.
- Type/runtime hardening:
  - Typed the audit writer queue as `asyncio.Queue[AuditLog | None]` and added
    an `AuditLogStore` Protocol for the async store boundary.
  - Fixed bootstrap wiring so the audit background worker only receives
    `AsyncSQLiteStore`; the worker awaits `save_audit_log()`, so wiring the sync
    fallback store would be a runtime bug.
  - Typed `record_command_execs()` command result rows as
    `list[dict[str, Any]]`.
  - Added a shared `SpecialistCallRequest` Pydantic model and used it in both
    Engineer and QA report schemas.
  - Updated `RoleWorkflowService` to consume `SpecialistCallRequest` as the main
    path while preserving the older dict fallback.
  - Finished strict typing for `EngineerWorkflow`, including `CodexTask`
    boundaries, report helper signatures, and payload-key normalization.
- Config update:
  - Added five modules to the strict mypy override list:
    `app.application.audit.writer`, `app.application.audit.recorders`,
    `app.application.audit_logger`, `app.application.engineer_workflow`, and
    `app.application.specialist_requests`.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/audit/writer.py app/application/audit/recorders.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 2 source files`.
  - `cd backend && .venv/bin/python -m mypy app/application/engineer_workflow.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m mypy app/application/specialist_requests.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Initial result after typing the audit store boundary exposed the
      bootstrap sync-store wiring issue.
    - Final result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, printed `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest tests/test_audit_logger.py tests/test_engineer_workflow.py tests/test_qa_workflow.py tests/test_specialist_orchestrator.py tests/test_specialist_orchestrator_start_failure.py -q`
    - Result: `84 passed in 2.11s`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 3 warnings in 65.18s`.

## 2026-07-06 Backend Strict Graduation Batch 8

- Context:
  - A fresh candidate scan showed two 0-error LLM modules and several modules
    blocked by shared git/review/QA dict shapes. Focused on those shared shapes
    rather than isolated local casts.
- Type/runtime hardening:
  - Added `RemoteGitStatus` and `DiffShortstat` TypedDicts for fixed GitService
    API shapes.
  - Typed `WorktreeManager.merge_issue()` with a `MergeIssueResult` TypedDict.
  - Updated `ProjectService.remote_status()` to return `RemoteGitStatus`,
    preserving the existing API fields while removing the naked dict boundary.
  - Typed `review_guard` path normalization inputs and artifact output.
  - Added `QACommandResult` for QA verification command execution rows and
    widened audit recorder input to read-only `Sequence[Mapping[str, Any]]`.
- Config update:
  - Added six modules to the strict mypy override list:
    `app.application.conductor_llm`, `app.application.llm_runner`,
    `app.application.git_service`, `app.application.worktree_manager`,
    `app.application.review_guard`, and `app.application.qa_workflow`.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/conductor_llm.py app/application/llm_runner.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 2 source files`.
  - `cd backend && .venv/bin/python -m mypy app/application/git_service.py app/application/worktree_manager.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 2 source files`.
  - `cd backend && .venv/bin/python -m mypy app/application/qa_workflow.py app/application/audit/recorders.py app/application/review_guard.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 3 source files`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Initial result after adding `RemoteGitStatus`: failed on
      `ProjectService.remote_status()`'s old dict return annotation.
    - Final result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m pytest tests/test_project_service.py tests/test_projects_api.py tests/test_git_service.py tests/test_worktree_manager.py tests/test_qa_workflow.py tests/test_review_guard.py tests/test_review_guard_integration.py -q`
    - Result: `129 passed in 42.31s`.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, printed `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 3 warnings in 55.22s`.

## 2026-07-06 Backend Strict Graduation Batch 9

- Context:
  - Continued with the next small-but-central workflow modules:
    `specialist_orchestrator` and `architect_workflow`.
- Type/runtime hardening:
  - Added structural Protocols for the specialist orchestrator store, event bus,
    task runner, workflow graph reference, and optional `list_codex_tasks`
    capability.
  - Preserved the existing narrow-store fallback for specialist duplicate checks
    by keeping `list_codex_tasks` optional at the call boundary.
  - Guarded specialist feed `AgentMessage` writes behind a present `issue_id`,
    avoiding a possible Pydantic validation error for issue-less parent tasks.
  - Restored `specialist_orchestrator.py`'s module docstring to the file top and
    removed import-order noqa noise.
  - Typed architect workflow task inputs as `CodexTask`, framework guard payloads
    as `dict[str, object]`, and normalized payload maps as `dict[str, object]`.
- Config update:
  - Added two modules to the strict mypy override list:
    `app.application.specialist_orchestrator` and
    `app.application.architect_workflow`.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/specialist_orchestrator.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m mypy app/application/architect_workflow.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m pytest tests/test_architect_workflow.py tests/test_specialist_orchestrator.py tests/test_specialist_orchestrator_start_failure.py -q`
    - Result: `30 passed in 0.55s`.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, printed `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 3 warnings in 55.61s`.

## 2026-07-06 Backend Strict Graduation Batch 10

- Context:
  - Candidate scan showed `project_conductor` and `project_review_scheduler`
    were the next smallest shared strictness blockers.
- Type/runtime hardening:
  - Added `ProjectConductorStore` Protocol, inheriting the existing
    GitHub PR follow-up store contract and adding project conductor state/memory
    methods.
  - Typed ProjectConductor event payloads and JSON list helpers as
    `dict[str, object]` / `list[object]`.
  - Typed the project review scheduler default conductor factory boundary,
    keeping its test-friendly narrow store contract while explicitly casting the
    default production factory to `ProjectConductorStore`.
  - Updated the API ProjectConductor construction point to cast the global
    Codex store to `ProjectConductorStore` instead of expanding the large API
    store Protocol.
- Config update:
  - Added two modules to the strict mypy override list:
    `app.application.project_conductor` and
    `app.application.project_review_scheduler`.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/project_conductor.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m mypy app/application/project_review_scheduler.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Initial result after tightening ProjectConductor store typing: failed on
      the API ProjectConductor construction boundary.
    - Final result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check app/application/project_conductor.py app/application/project_review_scheduler.py app/interfaces/api.py tests/test_project_conductor.py tests/test_project_review_scheduler.py tests/test_phase7_endpoints.py`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m pytest tests/test_project_conductor.py tests/test_project_review_scheduler.py tests/test_phase7_endpoints.py tests/test_diagnostics_api.py -q`
    - Result: `34 passed in 2.07s`.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, printed `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 3 warnings in 55.00s`.

## 2026-07-06 Backend Strict Graduation Batch 11

- Context:
  - Resumed from the already-typed `help_orchestrator` local probe and finished
    wiring it into the project strict baseline.
- Type/runtime hardening:
  - Added `HelpStore`, `HelpEventBus`, and `HelpTaskRunner` Protocols for the
    help orchestration boundary.
  - Replaced loose execution-process introspection with a runtime-checkable
    process-id guard.
  - Reworked help continuation payload formatting to use `dict[str, object]`
    and mapping/text guards instead of `Any`.
  - Aligned the HelpStore Protocol with the real async store signatures for
    help-request listing and execution-process status updates.
  - Fixed bootstrap wiring so `HelpOrchestrator` is created only with the async
    SQLite store; help orchestration awaits store methods and should fail fast
    if the async store is unavailable.
- Config update:
  - Added `app.application.help_orchestrator` to the strict mypy override list.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/help_orchestrator.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m ruff check app/application/help_orchestrator.py tests/test_help_orchestrator.py`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m pytest tests/test_help_orchestrator.py -q`
    - Result: `13 passed in 0.46s`.

## 2026-07-06 Backend Strict Graduation Batch 12

- Context:
  - The next strict scan showed `knowledge_index_service.py` as the most useful
    shared blocker: 34 direct strict errors and a large cascade into runtime,
    event bus, scheduler, and process modules.
- Type/runtime hardening:
  - Added explicit `KnowledgeStore`, `EmbeddingService`, DB cursor/connection,
    issue, artifact, search response, and reindex stats types.
  - Converted search hits to `dict[str, object]` and guarded all SQLite row
    reads before treating values as text, bytes, or numbers.
  - Removed `Any` from JSON flattening, artifact indexing, search, semantic
    ranking, and RRF merge paths.
  - Tightened `role_workflow_service` artifact persistence so LLM-produced
    `written_files` entries must have string `name` and `path` before indexing
    or embedding, avoiding a potential KeyError / wrong-type path read.
  - Added `app.application.knowledge_index_service` to the strict mypy override
    list.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/knowledge_index_service.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m pytest tests/test_knowledge_index.py tests/test_help_orchestrator.py -q`
    - Result: `24 passed in 0.70s`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Initial result after adding the module exposed two real call-boundary
      mismatches in `role_workflow_service.py` and `bootstrap.py`.
    - Final result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, printed `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 3 warnings in 59.53s`.

## 2026-07-06 Backend Strict Graduation Batch 13

- Context:
  - After `knowledge_index_service` graduated, the next largest cascade blocker
    was `agent_catalog/generic_specialist_workflow.py`, which was imported by
    `role_workflow_service` and surfaced as the first error for several runtime
    module probes.
- Type/runtime hardening:
  - Typed `GenericSpecialistWorkflow` against `CodexTask` instead of reading
    arbitrary task-shaped objects with `getattr`.
  - Converted specialist output parsing to treat tolerant JSON as `object`,
    require a mapping, and normalize keys before writing the artifact file.
  - Tightened `SpecialistReportDocument` to `dict[str, object]` artifacts and
    concrete written-file rows.
  - Guarded `clarification_question` so only a string becomes a task-facing
    clarification.
- Config update:
  - Added `app.application.agent_catalog.generic_specialist_workflow` to the
    strict mypy override list.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/agent_catalog/generic_specialist_workflow.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m pytest tests/test_agent_catalog.py tests/test_specialist_orchestrator.py tests/test_specialist_orchestrator_start_failure.py -q`
    - Result: `29 passed in 0.60s`.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, printed `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 3 warnings in 68.44s`.

## 2026-07-06 Backend Strict Graduation Batch 14

- Context:
  - After the specialist workflow blocker was removed, `product_manager_service`
    became the first strict error for several runtime module probes.
- Type/runtime hardening:
  - Added a `ProductManagerTask` Protocol and stopped relying on untyped task
    objects at the PM service boundary.
  - Typed PRD `subtask_split` rows, existing-PRD merge payloads, and normalized
    payload maps as `dict[str, object]`.
  - Normalized PRD payload key aliases before Pydantic validation, matching the
    existing bugfix path and making LLM casing variants less brittle.
  - Guarded task description access behind a runtime-checkable optional
    description Protocol.
  - Converted raw JSON loads to `object` + mapping normalization before merging
    or validating.
- Config update:
  - Added `app.application.product_manager_service` to the strict mypy override
    list.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/product_manager_service.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m pytest tests/test_async_refresh_task_result.py tests/test_issue_artifact_backfill.py tests/test_task_send_endpoint.py tests/test_agent_catalog.py -q`
    - Result: `28 passed in 1.25s`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, printed `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 3 warnings in 75.21s`.

## 2026-07-06 Backend Strict Graduation Batch 15

- Context:
  - The strict scan showed `project_memory_service.py` as a shared blocker for
    team notes, self-improvement application, and runtime prompt-context probes.
  - Probing it directly revealed that `team_notes_service.py` needed to graduate
    in the same batch because the two services share DB state reconciliation.
- Type/runtime hardening:
  - Added explicit DB/store/graph/issue/project/LLM-runner Protocols for project
    memory recording and distillation.
  - Reworked JSON artifact reads to return `dict[str, object]` only after
    confirming a mapping, then guarded text/list fields before slicing or
    rendering them into markdown.
  - Removed an unused engineer-report placeholder from summary construction.
  - Typed team-note block serialization and `team_notes_state` rows with a
    `TeamNotesState` TypedDict.
  - Added a shared structural store boundary for team-notes state operations and
    guarded SQLite row values before using them as block ids or deleted markers.
- Config update:
  - Added `app.application.project_memory_service` and
    `app.application.team_notes_service` to the strict mypy override list.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/project_memory_service.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m mypy app/application/team_notes_service.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m pytest tests/test_team_notes.py tests/test_self_improvement_apply_service.py tests/test_self_improvement_api.py -q`
    - Result: `78 passed in 14.60s`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, printed `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 3 warnings in 71.41s`.

## 2026-07-06 Backend Strict Graduation Batch 16

- Context:
  - After project memory and team notes graduated, the downstream
    `self_improvement_apply_service.py` had only a few remaining naked dict
    boundaries.
- Type/runtime hardening:
  - Typed evidence rows, candidate changes, and apply plans as
    `dict[str, object]` shapes.
  - Parsed evidence JSON as `object`, required a list, and normalized mapping
    keys before formatting evidence lines.
  - Preserved the existing runtime validation for project-memory candidate
    path/content before applying or rolling back proposals.
- Config update:
  - Added `app.application.self_improvement_apply_service` to the strict mypy
    override list.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/self_improvement_apply_service.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m pytest tests/test_self_improvement_apply_service.py tests/test_self_improvement_api.py tests/test_self_improvement_proposal_scheduler.py -q`
    - Result: `82 passed in 20.27s`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, printed `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 3 warnings in 61.34s`.

## 2026-07-06 Backend Strict Graduation Batch 17

- Context:
  - With project-memory/self-improvement blockers removed, `project_run_manager`
    became the smallest remaining application module and owns dev-server
    process lifecycle state.
- Type/runtime hardening:
  - Added `RunLogLine`, `RunStatus`, and `RunLogs` TypedDicts for the in-memory
    process status and log-tail API shapes.
  - Typed the bounded log ring buffer and background reader tasks.
  - Typed subprocess stream draining as `asyncio.StreamReader | None`, keeping
    the existing stdout/stderr null guard.
  - Preserved the cross-event-loop stop behavior and process-group termination
    logic unchanged.
- Config update:
  - Added `app.application.project_run_manager` to the strict mypy override
    list.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/project_run_manager.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m pytest tests/test_project_run.py -q -m slow`
    - Result: `8 passed in 2.57s`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, printed `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 3 warnings in 70.31s`.

## 2026-07-06 Backend Strict Graduation Batch 18

- Context:
  - `budget_service.py` was the next remaining top-level application module and
    owns cost aggregation, budget steering events, and conductor budget prompt
    rendering.
- Type/runtime hardening:
  - Added `IssueBudgetPayload` and `BudgetSteeringEvent` TypedDicts for the read
    endpoint / WS steering payload shapes.
  - Added `BudgetStore`, task-row, and execution-process Protocols so sync and
    async stores can both satisfy budget aggregation without naked dynamic
    access.
  - Typed `_maybe_await` with a generic `MaybeAwaitable` alias, preserving the
    existing sync/async store compatibility.
  - Centralized task id extraction through a guard that accepts either mapping
    rows or task-like objects.
- Config update:
  - Added `app.application.budget_service` to the strict mypy override list.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/budget_service.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m pytest tests/test_issue_budget.py tests/test_issue_budget_endpoint.py tests/test_conductor_budget_steering_injection.py tests/test_budget_supported_concurrency.py -q`
    - Result: `41 passed in 1.15s`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, printed `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 3 warnings in 66.15s`.

## 2026-07-06 Backend Strict Graduation Batch 19

- Context:
  - `json_rpc_client.py` was the last remaining medium-sized top-level
    application module before strict probes started failing first on the SQLite
    store adapters.
- Type/runtime hardening:
  - Replaced loose JSON payload aliases with `dict[str, object]` and normalized
    parsed JSON objects through `_json_object()`.
  - Added sync stdin/stdout Protocols for the blocking JSON-RPC peer.
  - Typed JSON-RPC message ids, callback payloads, pending result/error maps,
    and async reader tasks.
  - Guarded initialize/thread/turn responses before reading thread ids from
    nested JSON fields.
  - Added a minimal event-bus append Protocol plus `_append_event()` helper that
    preserves sync and async append support.
- Config update:
  - Added `app.application.json_rpc_client` to the strict mypy override list.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/json_rpc_client.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m pytest tests/test_agent_process_environment.py tests/test_cli_control_payload.py tests/test_message_streaming.py -q`
    - Result: `21 passed in 0.90s`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, printed `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 3 warnings in 65.25s`.

## 2026-07-06 Backend Store Foundation Batch 20

- Context:
  - After most top-level application modules were strict-clean, strict probes
    began failing first inside the sync and async SQLite store adapters. The
    goal for this batch was to harden the shared store foundation without
    enrolling the full store files in strict mypy yet.
- Type/runtime hardening:
  - Added shared row-key Protocol helpers to both store adapters so legacy-row
    compatibility checks use `row.keys()` explicitly instead of ambiguous
    SQLite row membership.
  - Added return and parameter annotations to store constructors and core
    `_init_db` / `_ensure_db` / execute helpers.
  - Replaced repeated benign migration rollback/duplicate-column `try` blocks
    with scoped `contextlib.suppress(...)`, preserving idempotent boot-time
    migrations while reducing noisy exception handling.
  - Kept the existing sync/async store behavior intact; this batch is a
    blocker-reduction pass before deeper session helper typing.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check app/adapters/sqlite_store.py app/adapters/async_sqlite_store.py`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m pytest tests/test_issue_budget.py tests/test_four_phase_preset.py tests/test_team_notes.py tests/test_self_improvement_store.py -q`
    - Result: `33 passed in 0.52s`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, printed `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 2 warnings in 87.01s`.

## 2026-07-06 Backend Store Strict Graduation Batch 21

- Context:
  - The user explicitly encouraged larger, meaningful refactors instead of
    only collecting one-error files. The next high-value move was to finish the
    strict typing pass for the two SQLite store adapters, because they sit at
    the persistence boundary for sessions, tasks, workflow DAGs, runtime rows,
    and self-improvement records.
- Type/runtime hardening:
  - Graduated both `app.adapters.sqlite_store` and
    `app.adapters.async_sqlite_store` to the strict mypy override list.
  - Added store-local JSON boundary helpers for object payloads, object-list
    schemas, string-list fields, Codex settings, and `PlanDetails` artifacts.
  - Hardened session, Codex session, issue, task, help request, execution
    process, runtime catalog, artifact, agent, workflow graph, conductor task,
    memory embedding, and skill row conversions with explicit return types and
    typed query parameter lists.
  - Replaced direct `json.loads(...)` handoff into Pydantic models with guarded
    object/list validation or `RuntimeCatalog.model_validate(...)`.
  - Aligned async `list_codex_tasks()` with the sync store by including
    `workflow_node_id` in the listed task row shape.
- Config update:
  - Added `app.adapters.sqlite_store` and `app.adapters.async_sqlite_store` to
    `backend/pyproject.toml` strict mypy overrides.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/adapters/sqlite_store.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m mypy app/adapters/async_sqlite_store.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, printed `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest tests/test_four_phase_preset.py tests/test_project_run.py tests/test_self_improvement_store.py tests/test_issue_budget.py tests/test_team_notes.py -q`
    - Result: `41 passed in 5.66s`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 1 warning in 76.41s`.

## 2026-07-06 Backend Strict Graduation Batch 22

- Context:
  - After the store adapters graduated, strict probes showed
    `project_service.py` was a tiny but high-impact blocker: many runtime and
    interface modules imported it and therefore reported its first error.
- Type/runtime hardening:
  - Added a typed `FastForwardPullResult` for one-click project pulls instead
    of returning a bare dict.
  - Typed `ProjectService.__init__()` and `list_branches()`.
  - Used `builtins.list[GitBranch]` for `list_branches()` to preserve the
    existing `ProjectService.list()` API name without class-scope type
    shadowing.
- Config update:
  - Added `app.application.project_service` to the strict mypy override list.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/project_service.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m pytest tests/test_projects_api.py tests/test_project_service.py tests/test_git_service.py tests/test_project_run.py -q`
    - Result: `68 passed in 25.09s`.

## 2026-07-06 Backend Strict Graduation Batch 23

- Context:
  - `prototype_service.py` became the next high-leverage strict blocker after
    `project_service.py`: it had only a few local errors but was imported by
    many runtime/interface modules and sits on the active code-driven prototype
    WIP path.
- Type/runtime hardening:
  - Typed SSE `StreamEvent` payloads as `Mapping[str, object]`, matching their
    read-only event-envelope use and avoiding invariant dict widening.
  - Added a `RuntimeCatalogLoader` Protocol for the runtime catalog dependency.
  - Typed prototype detail, batch failure, code-candidate list, and candidate
    metadata payloads as `dict[str, object]` shapes.
  - Kept the existing SSE event names and data fields unchanged.
- Config update:
  - Added `app.application.prototype_service` to the strict mypy override list.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/prototype_service.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, printed `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest tests/test_prototype_service.py tests/test_prototypes_api.py -q`
    - Result: `59 passed in 24.30s`.

## 2026-07-06 Backend Strict Graduation Batch 24

- Context:
  - Once `prototype_service.py` was strict-clean, its runtime evidence capture
    companion (`runtime_prototype_capture.py`) also passed direct strict probes.
    This keeps the code-driven prototype generation and browser-evidence path
    under the same type-safety bar.
- Config update:
  - Added `app.application.runtime_prototype_capture` to the strict mypy
    override list.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/runtime_prototype_capture.py --config-file=/dev/null --python-version 3.12 --ignore-missing-imports --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, printed `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest tests/test_prototype_service.py tests/test_prototypes_api.py -q`
    - Result: `59 passed in 12.13s`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 1 warning in 74.43s`.

## 2026-07-06 Backend Workflow Scheduler Foundation Batch 25

- Context:
  - After project/prototype strict work, the next strict frontier is the
    runtime/orchestration cluster (`workflow_scheduler`, `event_bus`,
    `process_runtime_common`, Codex runtimes). Fully graduating that cluster is
    larger than a safe single slice, so this batch tightened the workflow
    scheduler's own DAG and cross-service boundaries first.
- Type/runtime hardening:
  - Added `WorkflowStore` and `WorkflowEventBus` Protocols for the scheduler's
    actual store/event-bus dependency surface.
  - Typed DAG materialization helpers as `dict[str, object]` and normalized raw
    JSON object keys before building workflow nodes/edges.
  - Added a small task-dispatcher runner adapter and no-op event bus for the
    specialist completion bridge, so the scheduler passes objects with the
    interface shape the specialist orchestrator expects.
  - Added parent/issue id guards in the specialist resume path before loading
    tasks/issues or writing `AgentMessage` rows.
  - Kept `workflow_scheduler.py` out of the strict override list for now,
    because its imported runtime/event-bus dependencies still need a broader
    dedicated pass.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check app/application/workflow_scheduler.py`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, printed `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest tests/test_workflow_scheduler_auto_retry.py tests/test_artifact_validation_signal.py tests/test_task_statuses.py -q`
    - Result: `18 passed in 0.38s`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 2 warnings in 44.82s`.

## 2026-07-06 Backend Runtime Foundation Batch 26

- Context:
  - The user explicitly preferred a larger, meaningful refactor over only
    collecting one-error files. The next high-value frontier after
    `workflow_scheduler.py` is the shared process runtime cluster.
- Type/runtime hardening:
  - Added narrow Protocols for the runtime store, log store, event bus, help
    orchestrator, and workspace-console task discriminator.
  - Typed `BaseProcessRuntime.__init__()` and its shared dependency attributes.
  - Typed shared process scratch state on `ProcessEntry` / `AsyncProcessEntry`:
    waiters, output task, emitted tool IDs, and Codex tool item start times.
  - Converted runtime JSON parsing to return `dict[str, object]` with string
    keys and added local guards for nested Claude/Codex stream payloads.
  - Kept `process_runtime_common.py` out of the strict override list for now;
    the imported event-bus / websocket / task-runner cluster still needs a
    broader pass before graduation.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m pytest tests/test_async_refresh_task_result.py tests/test_reader_loop_finalize.py tests/test_message_streaming.py tests/test_task_chat_endpoint.py -q`
    - Result: `36 passed in 6.20s`.

## 2026-07-06 Backend Subagent Result Boundary Batch 27

- Context:
  - `subagent_result_builder.py` sits between workflow execution and Conductor
    handoff. It accepted arbitrary role documents but returned typed
    `SubAgentResult` fields, making it a good boundary-hardening target.
- Type/runtime hardening:
  - Replaced production `Any` document parameters with `object | None`.
  - Added an object-to-`dict[str, object]` guard for Pydantic `model_dump()`,
    legacy `.dict()`, dataclass, written-file, QA-command, and artifact JSON
    payloads.
  - Typed QA command and critique outputs to match `SubAgentResult` exactly.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m pytest tests/test_subagent_result_builder.py tests/test_agent_catalog.py tests/test_cli_control_payload.py -q`
    - Result: `23 passed in 0.71s`.

## 2026-07-06 Backend Codex App-Server JSON-RPC Batch 28

- Context:
  - After the shared runtime boundary was tightened, the Codex app-server
    runtime still had several raw JSON-RPC payload dicts in its notification
    callback path.
- Type/runtime hardening:
  - Reused `JsonObject` / `ServerRequest` from `json_rpc_client.py` for
    app-server approval and notification callback payloads.
  - Added local JSON object / string guards before reading nested `turn`,
    `error`, and `item` protocol fields.
  - Typed pending-approval snapshots, tool-event payloads, thread-result
    payloads, and the notification callback return shape.
  - Added return annotations to the app-server initialize and handshake helper
    coroutines.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m pytest tests/test_message_streaming.py tests/test_async_refresh_task_result.py tests/test_task_chat_endpoint.py tests/test_codex_version_endpoint.py -q`
    - Result: `35 passed in 2.47s`.
  - `cd backend && .venv/bin/python -m pytest tests/test_async_refresh_task_result.py tests/test_reader_loop_finalize.py tests/test_message_streaming.py tests/test_task_chat_endpoint.py tests/test_subagent_result_builder.py tests/test_agent_catalog.py tests/test_cli_control_payload.py -q`
    - Result: `59 passed in 4.41s`.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, printed `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 5 warnings in 54.05s`.

## 2026-07-06 Backend Event Bus Foundation Batch 29

- Context:
  - After process runtime and Codex app-server payloads were tightened, the
    next shared orchestration surface was `event_bus.py`, which still used
    bare `Any` event envelopes and untyped async queue/task state.
- Type/runtime hardening:
  - Added `JsonEvent`, `EventLogStore`, `WorkflowTaskRunner`, and
    `WorkflowTaskRunnerFactory` narrow protocols/aliases.
  - Typed the EventBus singleton state: replay buffer, subscriber queues,
    running loop, DB log queue, and DB worker task.
  - Made `append()` accept `Mapping[str, object]` while normalizing internal
    envelopes to `dict[str, object]`.
  - Added object/string guards before routing event ids into websocket stream
    managers, and converted mapping inputs back to plain dicts at the
    websocket boundary to preserve existing manager contracts.
  - Made the DB log worker compatible with both async and sync log stores by
    awaiting only awaitable `append_log_event()` results.
  - Typed the workflow scheduler task-dispatch bridge without pulling the
    whole bootstrap/task-runner cluster into this batch.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m pytest tests/test_message_streaming.py tests/test_task_chat_endpoint.py tests/test_workflow_scheduler_auto_retry.py tests/test_artifact_validation_signal.py tests/test_task_statuses.py -q`
    - Result: `38 passed in 2.32s`.
  - `cd backend && .venv/bin/python -m pytest tests/test_run_issue_conductor_loop.py tests/test_conductor_dispatch_batch.py tests/test_specialist_orchestrator.py -q`
    - Result: `39 passed in 0.78s`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 7 warnings in 46.89s`.

## 2026-07-06 Backend WebSocket Stream Foundation Batch 30

- Context:
  - Once `event_bus.py` was typed, the remaining strict frontier showed
    `interfaces/codex_ws.py` as the main consumer of generic event envelopes,
    websocket subscriber queues, and execution-process stream state.
- Type/runtime hardening:
  - Added `JsonFrame`, `JsonPatch`, `ExecutionProcessViews`, and
    `WorkspaceState` aliases for websocket frames and workspace snapshots.
  - Typed `WsSubscriber` outbound queues as bounded `asyncio.Queue[object]`
    because frames can be JSON objects or internal sentinel objects.
  - Typed workspace/log/message subscriber maps with built-in generics instead
    of legacy `Dict` / `Set`.
  - Converted `_maybe_await()` into a generic helper so sync/async fallback
    stores keep their result types across the bridge.
  - Typed workspace stream state, pending events, approval state, patch
    publishing, task/message/log/approval update methods, initial snapshot
    payloads, and raw log/message initial payload serialization.
  - Added a narrow pending-approval manager Protocol/cast at the bootstrap
    process-manager boundary without pulling the larger bootstrap cluster into
    this batch.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m pytest tests/test_message_streaming.py tests/test_task_chat_endpoint.py tests/test_async_refresh_task_result.py tests/test_reader_loop_finalize.py -q`
    - Result: `36 passed in 4.09s`.
  - `cd backend && .venv/bin/python -m pytest tests/test_browser_smoke_endpoint.py tests/test_run_issue_conductor_loop.py tests/test_workflow_scheduler_auto_retry.py -q`
    - Result: `18 passed in 0.80s`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 5 warnings in 51.55s`.

## 2026-07-06 Backend Runtime Wiring Strict Frontier Batch 31

- Context:
  - The user explicitly asked not to limit the pass to tiny 1-error cleanup.
    After the runtime, event bus, and websocket batches were green, the next
    high-value target was the shared process-manager/task-runner/bootstrap
    wiring path that connects Codex/Claude runtimes, task execution, managed
    role result persistence, approval state, and execution-process streams.
- Type/runtime hardening:
  - Typed `CodexProcessManager` as a real facade: constructor dependencies,
    store/log/refresh properties, launch/write/terminate/approval methods,
    task process indexes, command args forwarding, and app-server notification
    callback return type.
  - Added runtime return guards so `launch()` cannot leak an untrusted
    untyped runtime payload as a `CodexSession`.
  - Finished the strict-facing `BaseProcessRuntime` method annotations for
    launch/terminate/task cleanup, log append, task status emission, reader
    finalization, idle fallback, watchdog, heartbeat, and process-tree cleanup.
  - Typed Codex app-server and Claude runtime overrides so their
    `write_input_async`, ownership checks, handshake/error helpers, raw-line
    ingestion, thread-result application, and tool-event emission match the
    base runtime contract.
  - Introduced narrow `CodexTaskRunner` Protocols for its store, event bus,
    process manager, help orchestrator, and runtime help slots. This also made
    API runner construction require a real store via `_require_codex_store()`
    and fixed two missing `await mgr.terminate(...)` calls in workspace delete
    endpoints.
  - Typed `RoleWorkflowService` store capabilities by composing existing
    `KnowledgeStore`, `SpecialistStore`, and `TeamNotesStore` protocols, then
    tightened task parameters for prompt building, artifact persistence,
    critique recording, specialist requests, and operations-engineer script
    updates. Critique persistence now exits early when a task has no
    `issue_id`, matching the issue-graph semantics.
  - Typed the bootstrap mock process manager so test/no-launch mode exposes
    the same facade methods used by API code (`write_input_async`,
    `terminate_task`, approval resolution, pending approvals) and avoids
    leaking untyped kwargs through task execution.
  - Completed the remaining `codex_ws.py` strict annotations for execution
    process serialization, runtime row loading, approval refresh, publish
    methods, and websocket endpoint return types.
- Strict-frontier evidence:
  - Before this batch, a direct no-project-config probe from
    `codex_process_manager.py` showed 79 imported-cluster strict errors.
  - After Batch 31, the same probe reports only the environment dependency
    issue: missing stubs for `openpyxl` in `skill_service.py`; the project
    runtime/runner/bootstrap/websocket cluster has no remaining direct strict
    errors in that import path.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m mypy app/application/codex_process_manager.py app/application/process_runtime_common.py app/application/codex_app_server_runtime.py app/application/claude_process_runtime.py app/application/codex_task_runner.py app/application/role_workflow_service.py app/bootstrap.py app/interfaces/codex_ws.py --strict --show-error-codes --no-pretty`
    - Result: each targeted file passed under project strict configuration.
  - `cd backend && .venv/bin/python -m mypy --config-file=/dev/null app/application/codex_process_manager.py --strict --show-error-codes --no-pretty`
    - Result: only `app/application/skill_service.py:250` missing `openpyxl`
      library stubs remains; no project runtime/runner/ws strict errors remain
      in this import path.
  - `cd backend && .venv/bin/python -m pytest tests/test_message_streaming.py tests/test_task_chat_endpoint.py tests/test_async_refresh_task_result.py -q --tb=short --disable-warnings`
    - Result: `33 passed in 3.62s`.
  - `cd backend && .venv/bin/python -m pytest tests/test_lifespan_shutdown.py tests/test_projects_api.py tests/test_codex_tasks.py tests/test_task_chat_endpoint.py tests/test_async_refresh_task_result.py -q --tb=short --disable-warnings`
    - Result: `59 passed, 77 skipped in 17.50s`.
  - `cd backend && .venv/bin/python -m pytest tests/test_agent_catalog.py tests/test_operations_engineer_script_task.py tests/test_engineer_workflow.py tests/test_qa_workflow.py tests/test_codex_tasks.py -q --tb=short --disable-warnings`
    - Result: `72 passed, 77 skipped in 1.87s`.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, printed `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 2 warnings in 58.93s`.

## 2026-07-06 Backend Strict Probe Closure Batch 32

- Context:
  - Batch 31 reduced the direct `/dev/null --strict` probe from the runtime
    facade import path to one remaining external typing issue: `openpyxl` had
    no installed stubs. The project already depended on `openpyxl` for Excel
    skill imports, so the clean fix was to add the matching stub package rather
    than hide the import with an ignore.
- Type/runtime hardening:
  - Added `types-openpyxl>=3.1.5.20260518` to backend dev/runtime dependency
    declarations used by local quality gates.
  - Installed `openpyxl==3.1.5` and `types-openpyxl==3.1.5.20260518` into the
    backend venv for verification.
  - The newly active stubs exposed two real Excel import boundary issues in
    `skill_service.py`:
    - `wb.active` can be typed as `None`, so `import_excel()` now returns an
      empty import result when no active worksheet exists.
    - The nested row helper was named `cell`, shadowing the previous header
      loop variable and confusing type flow; it is now `cell_value()`.
- Checks:
  - `cd backend && .venv/bin/python -m pip index versions types-openpyxl`
    - Result: latest available version was `3.1.5.20260518`.
  - `cd backend && .venv/bin/python -m pip install 'openpyxl>=3.1.0' 'types-openpyxl>=3.1.5.20260518'`
    - Result: installed `openpyxl-3.1.5`, `types-openpyxl-3.1.5.20260518`,
      and `et-xmlfile-2.0.0`.
  - `cd backend && .venv/bin/python -m mypy --config-file=/dev/null app/application/codex_process_manager.py --strict --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 1 source file`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m pytest tests/test_security_hardening.py tests/test_codex_tasks.py -q --tb=short --disable-warnings`
    - Result: `4 passed, 77 skipped in 0.42s`.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, printed `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 3 warnings in 51.97s`.

## 2026-07-06 Frontend Prerender Storage Boundary Batch 33

- Context:
  - After the backend strict frontier was green, the next broad pass moved to
    frontend release gates. Typecheck, tests, lint, and format were already
    green, but `next build` emitted a prerender warning because grid modules
    touched browser storage in a server/prerender context.
  - Initial frontend baseline:
    - `cd frontend && npm run typecheck`
      - Result: passed.
    - `cd frontend && npm test`
      - Result: passed with `319` tests.
    - `cd frontend && npm run lint`
      - Result: passed.
    - `cd frontend && npm run format:check`
      - Result: passed.
    - `cd frontend && npm run build`
      - Result: passed, but emitted `localStorage is not available because --localstorage-file was not provided`.
- Runtime hardening:
  - Updated `frontend/src/features/workspaces/WorkspaceGrid.tsx` and
    `frontend/src/features/issues/IssueGrid.tsx` so persisted grid preference
    helpers guard `typeof window === "undefined"` before reading storage.
  - Replaced bare `localStorage` references with `window.localStorage`, keeping
    browser-only storage access explicit and SSR/prerender-safe.
  - Added `frontend/tests/sourceHygiene.test.ts` coverage that checks these
    grid storage helpers retain a browser-environment guard.
- Checks:
  - `cd frontend && node --import tsx --test tests/sourceHygiene.test.ts tests/workspaceGridMotion.test.ts tests/issueNavigationCopy.test.ts`
    - Result: passed with `9` tests.
  - `cd frontend && npm run build`
    - Result: passed; the `localStorage is not available because --localstorage-file was not provided` warning is gone.
  - `cd frontend && npm run typecheck`
    - Result: passed when run sequentially after build.
  - `cd frontend && npm test`
    - Result: passed with `320` tests.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm run format:check`
    - Result: passed.
- Notes:
  - One earlier `typecheck` run failed with missing `.next/types/...` files
    while `next build` was running at the same time. A sequential rerun passed,
    so this is a workflow gotcha: do not run `npm run typecheck` concurrently
    with `npm run build` because build mutates `.next/types`.
  - Frontend npm commands still print `npm warn Unknown user config
    "allowBuilds"`. `npm config get allowBuilds` points to the user's global
    `~/.npmrc`, not project source.
  - Frontend tests/build still emit the existing Node `DEP0205
    module.register()` warning from `tsx`; no project failure is attached to it.

## 2026-07-06 Frontend Split API Request Boundary Batch 34

- Context:
  - The user asked not to limit the pass to small 1-error fixes, so after the
    storage/prerender fix the next target was a broader frontend boundary:
    split API modules had repeated `fetch` + `handleResponse` + JSON request
    boilerplate across the active issue/task/project/prototype surfaces.
  - This was a high-leverage but bounded refactor because these modules back
    the main workbench, issue command center, project conductor, and prototype
    generation WIP.
- API boundary hardening:
  - Added shared helpers in `frontend/src/lib/api/fetch.ts`:
    `apiRequest<T>()`, `apiDedupedRequest<T>()`, `jsonRequestInit()`, and
    `apiJsonRequest<T>()`.
  - Refactored the ordinary success/throw request paths in:
    - `frontend/src/lib/api/prototypes.ts`
    - `frontend/src/lib/api/projects.ts`
    - `frontend/src/lib/api/tasks.ts`
    - `frontend/src/lib/api/issues.ts`
  - Preserved existing special-case semantics:
    - project pull/run-start `409` response unwrapping still reads raw
      `Response` objects.
    - list/detail helpers that intentionally degrade to `[]` or `null` on
      HTTP failures still keep their local `response.ok` branches.
    - export helpers still keep their CSV/text vs JSON behavior.
    - SSE/WS URL builders remain pure URL constructors.
- Test/type-safety hardening:
  - Added `frontend/tests/apiFetchHelpers.test.ts` to cover JSON request
    bodies, FastAPI validation error formatting, and concurrent GET dedupe.
  - Replaced explicit test-fixture `any` in `interactionState.test.ts` with
    typed `CodexIssue`, `CodexTask`, and `ExecutionProcess` factories.
  - Removed the remaining `as any` from `task-selection.test.ts`.
  - Extended `frontend/tests/sourceHygiene.test.ts` so frontend tests reject
    explicit `any` fixtures going forward.
- Checks:
  - `cd frontend && node --import tsx --test tests/apiFetchHelpers.test.ts tests/workbenchActions.test.ts tests/projectConductorApi.test.ts tests/prototypeApi.test.ts tests/sourceHygiene.test.ts`
    - Result: passed with `28` tests.
  - `cd frontend && node --import tsx --test tests/sourceHygiene.test.ts tests/interactionState.test.ts tests/task-selection.test.ts tests/apiFetchHelpers.test.ts`
    - Result: passed with `24` tests.
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm test`
    - Result: passed with `324` tests.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm run format:check`
    - Result: passed for `src/**/*.{ts,tsx}`.
  - `cd frontend && npm run build`
    - Result: passed; no `localStorage is not available because --localstorage-file was not provided` warning.
- Notes:
  - The same user-level npm config warning remains:
    `npm warn Unknown user config "allowBuilds"`.
  - The same Node `DEP0205 module.register()` warning from `tsx` remains in
    tests/build; it is not a project failure.

## 2026-07-07 CI Quality Gate Hardening Batch 40

- Context:
  - Local README/spec gates had moved beyond the CI workflow: backend CI still
    treated format/mypy as informational with `|| true`, checked only `app`,
    skipped the import smoke, and ran pytest without the documented quiet
    failure-focused flags.
  - Frontend CI used raw `npx` commands, soft-failed Prettier, and did not run
    the production build even though local quality specs require it.
- CI hardening:
  - Removed the soft-failing backend `ruff format --check . || true` and
    `mypy app || true` baseline steps.
  - Made backend CI enforce the same hard gates as the local spec:
    `ruff check .`, `mypy app benchmark --show-error-codes --no-pretty`,
    `python -c "from app.main import app"`, and
    `pytest -q --tb=short --disable-warnings`.
  - Made frontend CI use project scripts:
    `npm run typecheck`, `npm test`, `npm run lint`, `npm run build`, and
    `npm run format:check`.
  - Added `npm run build` to CI so prerender/type/build failures cannot pass a
    pull request after local gates have caught them.
- Regression guard:
  - Added `backend/tests/test_ci_quality_gates.py` to keep CI aligned with the
    documented hard gates.
  - The test rejects workflow soft-fails (`|| true`,
    `continue-on-error: true`) and asserts the backend/frontend gate commands
    remain present.
  - Extended the same test to keep the backend Python runtime contract aligned:
    `requires-python >=3.12`, mypy `python_version = "3.12"`, Ruff
    `target-version = "py312"`, CI `python-version: "3.12"`, and backend spec
    `Python 3.12+`.
  - Extended it again so README quality gate commands and CI gate commands stay
    aligned from a single test-owned command list.
  - Added `Scenario: CI Workflow Quality Gate Contract` to
    `.trellis/spec/vibe-kanban/backend/quality-guidelines.md`.
  - Corrected `.trellis/spec/vibe-kanban/backend/index.md` from `Python 3.13+`
    to `Python 3.12+`, matching pyproject and CI.
- Checks:
  - `ruby -ryaml -e "YAML.load_file('.github/workflows/ci.yml'); puts 'yaml ok'"`
    - Result: passed, `yaml ok`.
  - `rg -n "\|\| true|baseline|informational|mypy app\b|npx tsc|npx prettier" .github/workflows/ci.yml README.md .trellis/spec/vibe-kanban/backend/quality-guidelines.md .trellis/spec/ccgui/frontend/quality-guidelines.md`
    - Result: workflow has no soft-fail leftovers; remaining hits are the
      intended `mypy app benchmark` command in CI/README/spec.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, `Agent Collaboration Console`.
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm test`
    - Result: passed with `329` tests.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm run format:check`
    - Result: passed.
  - `cd frontend && npm run build`
    - Result: passed; generated `16/16` static pages.
  - `cd backend && .venv/bin/python -m pytest tests/test_ci_quality_gates.py -q --tb=short --disable-warnings`
    - Result: passed with `5` tests.
  - `cd backend && .venv/bin/python -m ruff check tests/test_ci_quality_gates.py`
    - Result: passed.
  - `rg -n "Python 3\.13|python-version:\s*\"3\.13|py313|python_version = \"3\.13\"|>=3\.13" README.md .github backend .trellis/spec/vibe-kanban/backend`
    - Result: no matches.
  - `cd backend && .venv/bin/python -m pytest tests/test_ci_quality_gates.py tests/test_benchmark_type_hygiene.py tests/test_benchmark_runner.py -q --tb=short --disable-warnings`
    - Result: passed with `20` tests.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1088 passed, 77 skipped, 166 deselected, 3 warnings in 48.64s`.
- Notes:
  - `actionlint` is not installed locally and Python lacks PyYAML, so workflow
    validation used Ruby's standard YAML parser plus command/diff inspection.
  - The known user-level npm warning remains:
    `npm warn Unknown user config "allowBuilds"`.

## 2026-07-07 Benchmark API Typed Response Boundary Batch 41

- Context:
  - `backend/benchmark/api.py` had graduated under strict mypy, but its handler
    contracts still used broad `dict[str, Any]` response shapes.
  - The FastAPI forwarding routes in `app/interfaces/api.py` returned `object`
    and passed `request.model_dump()` directly into the benchmark handler,
    leaving the benchmark HTTP JSON boundary underdocumented in types.
- API boundary hardening:
  - Added explicit `TypedDict` payload/response contracts in
    `backend/benchmark/api.py`:
    `TriggerRunPayload`, `TriggerRunResponse`, `SerializedRun`,
    `ListRunsResponse`, `BaselineResponse`, `SetBaselineResponse`,
    `RunDiffResponse`, `CalibrationReportResponse`, and `JobResponse`.
  - Updated `_serialize_run()` and all benchmark handler return annotations to
    use those concrete response shapes instead of `dict[str, Any]`.
  - Updated `/codex/benchmark/*` route annotations in `app/interfaces/api.py`
    to mirror the benchmark handler response contracts.
  - Replaced direct `request.model_dump()` forwarding with an explicit
    `TriggerRunPayload` construction from the Pydantic request fields.
- Spec sync:
  - Added `Scenario: Benchmark Handler Typed JSON Responses` to
    `.trellis/spec/vibe-kanban/backend/quality-guidelines.md` with signatures,
    contracts, validation matrix, tests, and wrong/correct examples.
- Checks:
  - `cd backend && .venv/bin/python -m mypy benchmark/api.py app/interfaces/api.py --strict --follow-imports=silent --show-error-codes --no-pretty`
    - Result: passed for the two touched modules.
  - `cd backend && .venv/bin/python -m ruff check benchmark/api.py app/interfaces/api.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest tests/test_benchmark_api.py -q --tb=short --disable-warnings`
    - Result: passed with `16` tests.
  - `cd backend && .venv/bin/python -m pytest tests/test_benchmark_aggregations.py tests/test_benchmark_api.py tests/test_benchmark_fixtures.py tests/test_benchmark_judge_correlation.py tests/test_benchmark_runner.py tests/test_benchmark_scorers.py tests/test_benchmark_store.py -q --tb=short --disable-warnings`
    - Result: passed with `165` tests.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1080 passed, 77 skipped, 166 deselected, 3 warnings in 47.97s`.
- Notes:
  - `CalibrationItemResponse.fixture_id` is `str | None`; the shipped
    calibration item schema allows missing fixture linkage, and mypy caught that
    boundary while the response contract was being tightened.

## 2026-07-07 Benchmark Job Registry Typed Callback Batch 42

- Context:
  - After Batch 41 typed the benchmark handler responses, the benchmark job
    registry still carried wide callback and metadata types:
    `Awaitable[Any]`, `Callable[..., Any]`, and `dict[str, Any]`.
  - That meant `JobResponse.meta` could be typed as `dict[str, object]` at the
    API boundary while the producing job model still allowed arbitrary `Any`.
- Job boundary hardening:
  - Changed `Job.meta` and `JobRegistry.create(..., meta=...)` to
    `dict[str, object]`.
  - Converted `start_job()` to a Python 3.12 generic function:
    `start_job[ResultT](..., coro: Callable[[], Awaitable[ResultT]],
    on_complete: CompletionCallback[ResultT] | None = None)`.
  - Added a generic `CompletionCallback[ResultT]` alias so the completion
    callback receives the same result type produced by the coroutine.
  - Replaced the callback awaitability probe with `inspect.isawaitable()`.
  - Narrowed the defensive `latest.meta.get("run_id")` fallback before assigning
    it to `Job.result_ref`.
- Spec sync:
  - Extended the benchmark typed JSON response scenario in
    `.trellis/spec/vibe-kanban/backend/quality-guidelines.md` with the generic
    job callback signature and metadata narrowing rule.
- Checks:
  - `cd backend && .venv/bin/python -m mypy benchmark/job.py benchmark/api.py --strict --show-error-codes --no-pretty`
    - Result: passed.
  - `cd backend && .venv/bin/python -m ruff check benchmark/job.py benchmark/api.py`
    - Result: passed.
  - `rg -n "\bAny\b|dict\[str, Any\]|Callable\[\[Job, Any|Awaitable\[Any\]" backend/benchmark/job.py backend/benchmark/api.py`
    - Result: no matches.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m pytest tests/test_benchmark_api.py tests/test_benchmark_runner.py -q --tb=short --disable-warnings`
    - Result: passed with `28` tests.
  - `cd backend && .venv/bin/python -m pytest tests/test_benchmark_aggregations.py tests/test_benchmark_api.py tests/test_benchmark_fixtures.py tests/test_benchmark_judge_correlation.py tests/test_benchmark_runner.py tests/test_benchmark_scorers.py tests/test_benchmark_store.py -q --tb=short --disable-warnings`
    - Result: passed with `165` tests.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.

## 2026-07-07 Benchmark Runtime Store Protocol Batch 43

- Context:
  - `RealConductorExecutor` still accepted `codex_store: Any` when collecting
    QA artifacts and process cost.
  - The real executor only needs two async store reads, but the bootstrap store
    is typed as a wider union that may also include `None` or sync store
    variants. Awaiting that boundary without a guard hides a real runtime
    requirement.
- Runtime boundary hardening:
  - Added `BenchmarkRuntimeStore` Protocol describing the exact async methods
    needed by the real benchmark executor:
    `list_codex_tasks(...) -> list[dict[str, object]]` and
    `list_execution_processes(...) -> list[ExecutionProcess]`.
  - Added `_is_benchmark_runtime_store()` as a `TypeGuard` that checks both
    structural presence and coroutine-function status before the real executor
    awaits store methods.
  - Replaced `codex_store: Any` in `_collect_artifacts()` and `_collect_cost()`
    with `BenchmarkRuntimeStore`.
  - Narrowed task row `id` and `title` fields before using them for process
    lookups and completed-task artifacts.
  - Added runner guard tests proving async stores are accepted while sync or
    missing stores are rejected.
- Spec sync:
  - Extended the benchmark typed JSON response scenario in
    `.trellis/spec/vibe-kanban/backend/quality-guidelines.md` with the runtime
    store Protocol and TypeGuard rule.
- Checks:
  - `cd backend && .venv/bin/python -m mypy benchmark/runner.py --strict --show-error-codes --no-pretty`
    - Result: passed.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m pytest tests/test_benchmark_api.py tests/test_benchmark_runner.py -q --tb=short --disable-warnings`
    - Result: passed with `28` tests.
  - `cd backend && .venv/bin/python -m pytest tests/test_benchmark_runner.py -q --tb=short --disable-warnings`
    - Result: passed with `14` tests after adding the runtime-store guard cases.
  - `cd backend && .venv/bin/python -m pytest tests/test_benchmark_aggregations.py tests/test_benchmark_api.py tests/test_benchmark_fixtures.py tests/test_benchmark_judge_correlation.py tests/test_benchmark_runner.py tests/test_benchmark_scorers.py tests/test_benchmark_store.py -q --tb=short --disable-warnings`
    - Result: passed with `165` tests.

## 2026-07-07 Benchmark Explicit-Any Burnout Batch 43 Follow-up

- Context:
  - After typing the benchmark API, job registry, and real-executor store
    boundary, the benchmark package had one remaining explicit `Any`:
    `Score.metadata: dict[str, Any]`.
  - Existing scorer and judge metadata is JSON-ish debug data asserted by tests;
    it does not need an untyped escape hatch.
- Type boundary hardening:
  - Changed `Score.metadata` to `dict[str, object]`.
  - Removed the final `typing.Any` import from `backend/benchmark/types.py`.
  - Added `backend/tests/test_benchmark_type_hygiene.py` to scan
    `backend/benchmark/**/*.py` for explicit `Any`, `dict[str, Any]`,
    `Awaitable[Any]`, or `Callable[..., Any]` style type escapes.
  - Added the benchmark explicit-Any source scan to backend quality guidelines
    so future benchmark work keeps this package free of broad Any types unless a
    documented external bridge is introduced.
- Checks:
  - `rg -n "\bAny\b|dict\[str, Any\]|Awaitable\[Any\]|Callable\[.*Any" backend/benchmark`
    - Result: no matches.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest tests/test_benchmark_scorers.py tests/test_benchmark_judge_correlation.py -q --tb=short --disable-warnings`
    - Result: passed with `64` tests.
  - `cd backend && .venv/bin/python -m pytest tests/test_benchmark_type_hygiene.py -q --tb=short --disable-warnings`
    - Result: passed with `1` test.
  - `cd backend && .venv/bin/python -m pytest tests/test_benchmark_aggregations.py tests/test_benchmark_api.py tests/test_benchmark_fixtures.py tests/test_benchmark_judge_correlation.py tests/test_benchmark_runner.py tests/test_benchmark_scorers.py tests/test_benchmark_store.py tests/test_benchmark_type_hygiene.py -q --tb=short --disable-warnings`
    - Result: passed with `168` tests.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1086 passed, 77 skipped, 166 deselected, 3 warnings in 51.71s`.

## 2026-07-07 Backend API Strict Graduation Batch 44

- Context:
  - The next high-value backend surface was `backend/app/interfaces/api.py`,
    the large FastAPI transport module that many tests and benchmark paths call
    directly. A targeted strict probe initially reported 45 errors, mostly raw
    `dict` / `list` return types and untyped shared helpers.
- API boundary hardening:
  - Added local JSON aliases and coercion helpers (`JsonObject`, `JsonList`,
    `_json_object`, `_json_list`, `_json_object_list`, `_model_json_object`) so
    parsed JSON and Pydantic dumps are narrowed before endpoint payloads use
    them.
  - Typed shared serializers and helpers, including audit log serialization,
    project conductor state serialization, task payload serialization,
    self-improvement serializers, workflow graph serialization, task runner
    access, execution-process payload building, task result refresh, artifact
    backfill, and chat/refine task helpers.
  - Split API store capabilities into `CodexApiStore` and
    `AgentWorkflowApiStore`, keeping ordinary endpoints on the narrower store
    while workflow/agent endpoints opt into the wider protocol.
  - Made `event_bus` import from its owning application module instead of
    relying on a bootstrap re-export.
  - Added return annotations across `api.py` routes so the file can run under
    strict per-module mypy. Routes that are directly reused by backend code keep
    concrete return types such as `CodexIssue`, `Response`, or
    `list[JsonObject]` instead of a blanket `object`.
  - Added `app.interfaces.api` to the backend per-module strict list in
    `backend/pyproject.toml`.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/interfaces/api.py --strict --follow-imports=silent --show-error-codes --no-pretty`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed with `123` source files checked.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_projects_api.py tests/test_agents_api.py tests/test_self_improvement_api.py tests/test_runtime_catalog.py tests/test_runtime_catalog_api_contract.py tests/test_diagnostics_api.py tests/test_pipeline_stages.py tests/test_codex_issue_artifacts.py tests/test_resume_api.py tests/test_task_chat_endpoint.py tests/test_task_refine_endpoint.py tests/test_task_send_endpoint.py tests/test_task_rerun_endpoint.py tests/test_benchmark_runner.py`
    - Result: passed with `198` tests.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: passed with `1078 passed, 77 skipped, 166 deselected, 2 warnings`.
- Notes:
  - Importing the route module under modern FastAPI caught one real annotation
    pitfall: `204` endpoints must not be annotated as returning a response
    body. The agent delete route now returns `Response` explicitly.
  - App strict coverage is now `101 / 109` modules; the remaining non-strict
    app modules are mostly package `__init__` files plus `app.main`.

## 2026-07-07 Backend App Strict Completion Batch 45

- Context:
  - After Batch 44 graduated `app.interfaces.api`, the remaining backend app
    strict gap was `app.main` plus package `__init__` modules. This batch
    finished the app-module strict burn-down and removed the obsolete broad
    `app.*` loose mypy override.
- Strict coverage:
  - Typed `app.main` lifespan task handles as `asyncio.Task[None] | None`.
  - Added return/parameter annotations for the FastAPI lifespan context manager
    and catch-all exception handler.
  - Added `app.main` and the package modules (`app`, `app.adapters`,
    `app.application`, `app.application.agent_catalog`,
    `app.application.audit`, `app.domain`, `app.interfaces`) to the per-module
    strict list.
  - Removed the old non-strict `app.*` override because every app module now
    has explicit strict coverage.
  - Verified strict coverage with a module inventory: `109 / 109` app modules,
    `0` missing.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/main.py --strict --follow-imports=silent --show-error-codes --no-pretty`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/__init__.py app/adapters/__init__.py app/application/__init__.py app/application/agent_catalog/__init__.py app/application/audit/__init__.py app/domain/__init__.py app/interfaces/__init__.py --strict --show-error-codes --no-pretty`
    - Result: passed.
  - `python3 <module inventory script>`
    - Result: `all 109 strict 109 missing 0`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed with `123` source files checked and no unused override notes.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: printed `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_lifespan_shutdown.py tests/test_bootstrap.py tests/test_browser_smoke_endpoint.py tests/test_codex_version_endpoint.py tests/test_diagnostics_api.py`
    - Result: passed with `18` tests.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: passed with `1078 passed, 77 skipped, 166 deselected, 4 warnings`.
- Notes:
  - The backend app package now has a fully strict mypy surface. Remaining type
    tightening opportunities are outside `app/`, especially the benchmark
    package and tests.

## 2026-07-07 Backend Benchmark Strict Graduation Batch 46

- Context:
  - Batch 43 made benchmark modules strict-ready in targeted probes, but the
    regular backend mypy command did not yet enforce strict mode on the benchmark
    package. This batch turned that prep into a standing gate.
- Strict coverage:
  - Ran `benchmark --strict` across the full benchmark package (`14` source
    files); it passed without code changes.
  - Added all benchmark modules to the backend per-module strict list:
    `benchmark`, `benchmark.aggregations`, `benchmark.api`, `benchmark.cli`,
    `benchmark.correlation`, `benchmark.golden_loader`,
    `benchmark.golden_schema`, `benchmark.job`, `benchmark.judge`,
    `benchmark.runner`, `benchmark.scorers`, `benchmark.scorers_impl`,
    `benchmark.store`, and `benchmark.types`.
  - Updated `.trellis/spec/vibe-kanban/backend/quality-guidelines.md` with the
    FastAPI no-content route annotation contract learned during API strict
    graduation: `204` routes should return `Response`, not `object` or a JSON
    body shape.
- Checks:
  - `cd backend && .venv/bin/python -m mypy benchmark --strict --show-error-codes --no-pretty`
    - Result: passed with `14` source files checked.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed with `123` source files checked.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_benchmark_aggregations.py tests/test_benchmark_api.py tests/test_benchmark_fixtures.py tests/test_benchmark_judge_correlation.py tests/test_benchmark_runner.py tests/test_benchmark_scorers.py tests/test_benchmark_store.py`
    - Result: passed with `165` tests.
- Notes:
  - The backend production app and benchmark package are now both covered by
    strict mypy in the standard backend type-check command.

## 2026-07-07 Backend Strict Coverage Guard Batch 47

- Context:
  - After app and benchmark reached full strict coverage, the next risk was a
    silent config regression: a future edit could add a Python module without
    adding it to the strict list, or reintroduce a loose `app.*` /
    `benchmark.*` override.
- Guardrail:
  - Added `backend/tests/test_mypy_strict_coverage.py`.
  - The test maps every `backend/app/**/*.py` and `backend/benchmark/**/*.py`
    file to its mypy module name, including `__init__.py -> package`, and asserts
    each is present in a strict override.
  - The test also rejects loose package overrides for `app.*` and `benchmark.*`.
- Checks:
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_mypy_strict_coverage.py`
    - Result: passed with `2` tests.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed with `123` source files checked.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: passed with `1080 passed, 77 skipped, 166 deselected, 8 warnings`.
- Notes:
  - This turns the strict burn-down from a one-time cleanup into an executable
    source contract.

## 2026-07-07 Backend No-Content Route Regression Batch 48

- Context:
  - Batch 44 found that `204` FastAPI routes must not be annotated as returning
    a response body. Batch 46 recorded the convention in the backend quality
    spec; this batch added endpoint-level regression evidence.
- Test hardening:
  - Strengthened `backend/tests/test_agents_api.py::test_delete_custom_agent` to
    assert that the successful delete response has status `204` and an empty
    body (`resp.content == b""`).
- Checks:
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_agents_api.py tests/test_mypy_strict_coverage.py`
    - Result: passed with `12` tests.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed with `123` source files checked.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: passed with `1080 passed, 77 skipped, 166 deselected, 4 warnings`.

## 2026-07-07 Frontend Full Gate Recheck Batch 49

- Context:
  - After the backend strict/type-safety batches, the next project-level risk was
    stale frontend evidence. This batch re-ran the complete frontend gate set
    without making frontend code changes.
- Checks:
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm test`
    - Result: passed with `329` tests.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm run format:check`
    - Result: passed for `src/**/*.{ts,tsx}`.
  - `cd frontend && npm run build`
    - Result: passed; Next generated `16 / 16` static pages successfully.
- Notes:
  - The user-level npm warning remains:
    `npm warn Unknown user config "allowBuilds"`.
  - The Node `DEP0205 module.register()` warning from earlier `tsx` runs did not
    appear in this full `npm test` output, but it remains classified as a
    non-project failure when it does appear.

## 2026-07-07 Backend Strict Mypy Graduation Batch 40

- Context:
  - After the frontend API boundary work, the next high-leverage backend pass
    targeted the existing strict-mypy burn-down in `backend/pyproject.toml`.
  - A module comparison showed `109` app modules, `80` already in the strict
    override, and `29` not yet graduated. Several unlisted modules already
    passed `mypy --strict`; the conductor loop/tooling modules needed small
    type-boundary fixes before they could join the gate.
- Type-safety hardening:
  - Added type annotations in `frontend`-independent backend conductor code:
    - `backend/app/application/conductor_tools.py`
      - typed the worktree manager resolver and event emitter boundary;
      - typed budget/dispatch helper parameters;
      - added `_list_count()` so merge summary counts narrow unknown payload
        values before calling `len()`.
    - `backend/app/application/conductor_main_loop.py`
      - typed `CodexIssue` parameters, dynamic store/event bus boundaries,
        `asyncio.Task` generics, heartbeat estimator parameters, and the
        policy-wrapper LLM callable.
  - Expanded the strict mypy override in `backend/pyproject.toml` from `80`
    to `96` app modules. Newly covered modules include conductor runtime
    modules, process runtime modules, codex process modules, event bus,
    bootstrap, role workflow, skill service, workflow scheduler, and codex WS.
  - Left the remaining non-strict modules out of the override because they are
    larger follow-up surfaces: `interfaces/api.py`, `main.py`, `sse.py`,
    `ws_events.py`, `conductor_recovery.py`, and `stall_watchdog.py` plus
    package marker modules.
- Checks:
  - Per-candidate strict scan:
    - Initial result: `app modules 109 strict 80 missing 29`.
  - Post-graduation strict coverage scan:
    - Result: `app modules 109 strict 96 missing 13`.
  - `cd backend && .venv/bin/python -m mypy app/application/conductor_tools.py --strict --show-error-codes --no-pretty`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/application/conductor_main_loop.py --strict --show-error-codes --no-pretty`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m pytest tests/test_conductor_dispatch_batch.py tests/test_run_issue_conductor_loop.py tests/test_conductor_subagent_timeout.py -q --tb=short --disable-warnings`
    - Result: passed with `20` tests.
  - `cd backend && .venv/bin/python -c "from app.main import app; print(app.title)"`
    - Result: passed, printed `Agent Collaboration Console`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 2 warnings in 66.89s`.
- Notes:
  - The remaining strict candidates are intentionally not swept into the same
    batch because they need separate API/recovery focused review rather than a
    configuration-only graduation.

## 2026-07-07 Backend Strict Mypy Graduation Batch 41

- Context:
  - After Batch 40 moved the backend strict gate from `80` to `96` app modules,
    the next tractable strict candidates were smaller transport/watchdog
    modules rather than the very large `interfaces/api.py` or `main.py`
    surfaces.
- Type-safety hardening:
  - Graduated three more modules into the strict mypy override:
    - `app.application.stall_watchdog`
    - `app.interfaces.sse`
    - `app.interfaces.ws_events`
  - `backend/app/interfaces/ws_events.py` now types the websocket endpoint,
    nested sender/receiver/heartbeat coroutines, and task list.
  - `backend/app/interfaces/sse.py` now types stream event serialization,
    route request/response boundaries, and async stream iterators.
  - `backend/app/application/stall_watchdog.py` now types stall event payloads,
    dynamic store/process-manager boundaries, nudge callables, and narrows task
    ids before passing them to task activity/process APIs.
- Checks:
  - Per-module strict runs:
    - `cd backend && .venv/bin/python -m mypy app/interfaces/ws_events.py --strict --show-error-codes --no-pretty`
      - Result: passed.
    - `cd backend && .venv/bin/python -m mypy app/interfaces/sse.py --strict --show-error-codes --no-pretty`
      - Result: passed.
    - `cd backend && .venv/bin/python -m mypy app/application/stall_watchdog.py --strict --show-error-codes --no-pretty`
      - Result: passed.
  - Post-graduation strict coverage scan:
    - Result: `app modules 109 strict 99 missing 10`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check app/interfaces/ws_events.py app/interfaces/sse.py app/application/stall_watchdog.py pyproject.toml`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m pytest tests/test_prototypes_api.py tests/test_browser_smoke_endpoint.py tests/test_swarm_integration.py -q --tb=short --disable-warnings`
    - Result: passed with `35` tests.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 6 warnings in 55.06s`.
- Notes:
  - The remaining strict gaps are now mostly package marker modules plus the
    larger `interfaces/api.py`, `main.py`, and `conductor_recovery.py` surfaces.

## 2026-07-07 Backend Conductor Recovery Strict Batch 42

- Context:
  - After Batch 41, `conductor_recovery.py` was the remaining non-strict
    backend module with a focused error shape. The larger `interfaces/api.py`
    and `main.py` surfaces were left for a separate pass.
- Type-safety hardening:
  - Graduated `app.application.conductor_recovery` into the strict mypy
    override.
  - Typed `_maybe_await()` with a generic return type so async/sync store
    fallback calls preserve their result type instead of becoming untyped.
  - Typed dynamic store/event-bus/task-dispatcher boundaries across conductor
    recovery, relaunch, stalled marking, and watchdog entrypoints.
  - Typed relaunch callback futures as `asyncio.Future[Any]`.
  - Removed a stale `noqa` and used Python 3.12 generic-function syntax for
    the helper.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/conductor_recovery.py --strict --show-error-codes --no-pretty`
    - Result: passed.
  - Post-graduation strict coverage scan:
    - Result: `app modules 109 strict 100 missing 9`.
  - `cd backend && .venv/bin/python -m pytest tests/test_conductor_recovery.py tests/test_conductor_state_machine.py tests/test_lifespan_shutdown.py -q --tb=short --disable-warnings`
    - Result: passed with `18` tests.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 5 warnings in 58.92s`.
- Notes:
  - Remaining strict gaps are now package marker modules plus
    `interfaces/api.py` and `main.py`.

## 2026-07-07 Backend Benchmark Strict Prep Batch 43

- Context:
  - After backend app strict coverage reached `100/109`, probing
    `interfaces/api.py` / `main.py` under strict showed benchmark modules were
    adding extra noise to the remaining large API surface. This batch clears
    the benchmark-local strict issues first, without forcing the huge
    `interfaces/api.py` file into the same change.
- Type-safety hardening:
  - `backend/benchmark/store.py`
    - Typed `SqliteStore._run_params()` as `tuple[object, ...]`.
  - `backend/benchmark/correlation.py`
    - Typed `CalibrationItem.to_dict()` as `dict[str, object]`.
  - `backend/benchmark/runner.py`
    - Imports `GoldenIssue` from `golden_schema` and `load_all` from
      `golden_loader`, matching each module's ownership.
    - Imports the global event bus from `app.application.event_bus` instead of
      relying on an implicit bootstrap re-export.
    - Typed real-executor dynamic store boundaries for artifact/cost
      collection.
  - `backend/benchmark/api.py`
    - Typed benchmark job completion callback parameters.
    - Typed run serialization as `BenchmarkRun` plus optional
      `list[BenchmarkEpoch]`.
- Checks:
  - `cd backend && .venv/bin/python -m mypy benchmark/store.py benchmark/correlation.py benchmark/runner.py benchmark/api.py --strict --follow-imports=silent --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 4 source files`.
  - `cd backend && .venv/bin/python -m pytest tests/test_benchmark_aggregations.py tests/test_benchmark_api.py tests/test_benchmark_fixtures.py tests/test_benchmark_judge_correlation.py tests/test_benchmark_runner.py tests/test_benchmark_scorers.py tests/test_benchmark_store.py -q --tb=short --disable-warnings`
    - Result: passed with `165` tests.
  - `cd backend && .venv/bin/python -m ruff check benchmark/store.py benchmark/correlation.py benchmark/runner.py benchmark/api.py`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed, `Success: no issues found in 123 source files`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed, `All checks passed!`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1078 passed, 77 skipped, 166 deselected, 5 warnings in 59.80s`.
- Notes:
  - A full strict run over these benchmark files without import silencing still
    descends into `app.interfaces.api`; that remaining API strict surface is
    intentionally tracked as the next large backend boundary.

## 2026-07-07 Frontend API Raw-Fetch Contract Batch 39

- Context:
  - Batch 38 reduced ordinary JSON reads in split API modules to shared
    helpers, but without a source contract a future endpoint could silently add
    another one-off raw `fetch` branch and reopen the drift.
- Contract hardening:
  - Added a `frontend/tests/sourceHygiene.test.ts` contract that scans
    `frontend/src/lib/api/*.ts` and allows raw `fetch` only on a documented
    per-file allowlist.
  - The allowlist now captures the intentional raw-Response protocols:
    shared fetch infrastructure, health probes, CSV/JSON export switches,
    project 409 unwraps, skills raw text errors, and benchmark custom
    POST/boolean endpoints.
  - Any new ordinary JSON endpoint now has to use `apiRequest()`,
    `apiDedupedRequest()`, `apiJsonRequest()`, or `apiRequestOr()` instead of
    adding another local `fetch` branch.
- Checks:
  - `cd frontend && node --import tsx --test tests/apiFetchHelpers.test.ts tests/sourceHygiene.test.ts tests/apiCompatibility.test.ts`
    - Result: passed with `19` tests.
  - `cd frontend && npx prettier --check tests/sourceHygiene.test.ts tests/apiFetchHelpers.test.ts`
    - Result: passed.
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm test`
    - Result: passed with `329` tests.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm run build`
    - Result: passed; no `localStorage is not available because --localstorage-file was not provided` warning.
- Notes:
  - The project `npm run format:check` still covers `src/**/*.{ts,tsx}`; test
    formatting was checked separately for the two touched test files.
  - The same user-level npm config warning remains:
    `npm warn Unknown user config "allowBuilds"`.
  - The same Node `DEP0205 module.register()` warning from `tsx` remains in
    tests/build; it is not a project failure.

## 2026-07-07 Frontend API Soft-Failure Request Boundary Batch 38

- Context:
  - Batch 37 left `frontend/src/lib/api.ts` as a compatibility barrel, so the
    next API-layer debt was in split modules: many read endpoints intentionally
    degrade to `[]`, `null`, or `{}` on HTTP failures, but each one still
    duplicated `fetch` + `response.ok` + fallback + optional logging.
  - The goal was to keep those UI soft-failure contracts while removing the
    repeated raw fetch branches from high-traffic workbench, issue, conductor,
    benchmark, and stats surfaces.
- API boundary hardening:
  - Added `apiRequestOr<T>()` in `frontend/src/lib/api/fetch.ts` for typed
    fallback reads, with optional dedupe and status-specific log messages.
  - Re-exported `apiRequestOr` from the legacy `@/lib/api` compatibility map.
  - Migrated soft-failure reads in:
    - `frontend/src/lib/api/approvals.ts`
    - `frontend/src/lib/api/issues.ts`
    - `frontend/src/lib/api/tasks.ts`
    - `frontend/src/lib/api/conductors.ts`
    - `frontend/src/lib/api/projects.ts`
    - `frontend/src/lib/api/benchmarks.ts`
    - `frontend/src/lib/api/stats.ts`
  - Migrated ordinary throw/204 paths in:
    - `frontend/src/lib/api/workspaces.ts`
    - `frontend/src/lib/api/agents.ts`
  - Preserved raw `fetch` for the remaining intentional raw-Response
    contracts: health checks, CSV/text exports, project 409 unwrap protocols,
    skill proxy/category raw text errors, benchmark custom POST error handling,
    and boolean status endpoints.
- Tests and spec sync:
  - Extended `frontend/tests/apiFetchHelpers.test.ts` to cover
    `apiRequestOr()` fallback logging and deduped GET sharing.
  - Updated `.trellis/spec/ccgui/frontend/type-safety.md` so split API modules
    use `apiRequestOr()` for typed soft-failure reads and keep raw `fetch` only
    when the raw `Response` is itself the contract.
- Checks:
  - `cd frontend && node --import tsx --test tests/apiFetchHelpers.test.ts tests/apiCompatibilityExports.test.ts tests/agentMeshApi.test.ts tests/projectConductorApi.test.ts tests/budgetMeter.test.ts`
    - Result: passed with `26` tests.
  - Split API export coverage script:
    - Result: `api exports 231 missing from split 0`.
  - Raw API fetch scan:
    - Result: remaining non-helper raw fetches are limited to health, exports,
      project 409 unwraps, skill raw text errors, benchmark custom POST/boolean
      endpoints, and the shared fetch helper itself.
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm test`
    - Result: passed with `328` tests.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm run format:check`
    - Result: passed for `src/**/*.{ts,tsx}`.
  - `cd frontend && npm run build`
    - Result: passed; no `localStorage is not available because --localstorage-file was not provided` warning.
- Notes:
  - The same user-level npm config warning remains:
    `npm warn Unknown user config "allowBuilds"`.
  - The same Node `DEP0205 module.register()` warning from `tsx` remains in
    tests/build; it is not a project failure.

## 2026-07-07 Frontend API Compatibility Barrel Batch 37

- Context:
  - After Batch 36 made the monolithic `frontend/src/lib/api.ts` share the
    split API response helpers, the remaining large frontend API risk was that
    the file still mixed compatibility exports with endpoint implementation.
    That made it easy to accidentally reintroduce duplicate base constants,
    local response handlers, or stale functions when moving symbols between
    split modules.
- API boundary hardening:
  - Converted `frontend/src/lib/api.ts` into an explicit compatibility
    re-export map over the split domain modules.
  - Moved the missing DAG/replan endpoint functions into
    `frontend/src/lib/api/conductors.ts`:
    `planIssue`, `saveIssueGraph`, `startIssueGraph`, `listReplanPending`,
    `confirmReplan`, and `rejectReplan`.
  - Preserved the existing `@/lib/api` import surface while ensuring the
    monolithic entrypoint no longer owns local endpoint implementation.
  - Updated `frontend/tests/apiCompatibility.test.ts` so its source contract
    now checks that `api.ts` remains a barrel-style compatibility map.
- Export coverage:
  - Ran the split-module export coverage script:
    `api exports 230 missing from split 0`.
- Checks:
  - `cd frontend && node --import tsx --test tests/apiCompatibility.test.ts tests/apiCompatibilityExports.test.ts tests/workbenchActions.test.ts tests/agentMeshApi.test.ts tests/projectConductorApi.test.ts`
    - Result: passed with `28` tests.
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm test`
    - Result: passed with `326` tests.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm run format:check`
    - Result: passed for `src/**/*.{ts,tsx}`.
  - `cd frontend && npm run build`
    - Result: passed; no `localStorage is not available because --localstorage-file was not provided` warning.
- Notes:
  - The same user-level npm config warning remains:
    `npm warn Unknown user config "allowBuilds"`.
  - The same Node `DEP0205 module.register()` warning from `tsx` remains in
    tests/build; it is not a project failure.

## 2026-07-06 Frontend Split API Request Boundary Batch 35

- Context:
  - Batch 34 introduced the shared split-API request helpers and migrated the
    highest-traffic issue/task/project/prototype modules. Batch 35 continued
    the same refactor into lower-risk domain modules so the split API layer has
    one normal JSON request path instead of dozens of local variants.
- API boundary hardening:
  - Migrated ordinary JSON success/throw paths in:
    - `frontend/src/lib/api/agents.ts`
    - `frontend/src/lib/api/approvals.ts`
    - `frontend/src/lib/api/audit.ts`
    - `frontend/src/lib/api/runtime.ts`
    - `frontend/src/lib/api/resume.ts`
    - `frontend/src/lib/api/workspaces.ts`
    - `frontend/src/lib/api/skills.ts`
    - `frontend/src/lib/api/knowledge.ts`
    - `frontend/src/lib/api/stats.ts`
    - selected ordinary command paths in `frontend/src/lib/api/conductors.ts`
  - Preserved raw `fetch` where the endpoint has deliberate nonstandard
    behavior:
    - health checks with custom backend identity errors;
    - benchmark endpoints and conductor list endpoints that degrade to
      `[]`, `null`, `{}`, `false`, or `true`;
    - export helpers that switch between `text()` and `json()`;
    - skill proxy/category delete helpers that intentionally surface raw text;
    - 204/empty response paths where forcing `response.json()` would be risky.
- Spec sync:
  - Updated `.trellis/spec/ccgui/frontend/type-safety.md` with the split API
    request helper convention, including signatures, contracts, error matrix,
    tests required, and wrong/correct examples.
- Checks:
  - `cd frontend && node --import tsx --test tests/agentMeshApi.test.ts tests/resumeApi.test.ts tests/runtimeCatalogMotion.test.ts tests/knowledgeI18n.test.ts tests/workspaceCreateUx.test.ts tests/sourceHygiene.test.ts`
    - Result: passed with `22` tests.
  - `cd frontend && node --import tsx --test tests/agentMeshApi.test.ts tests/projectConductorApi.test.ts tests/decisionExplanationPanel.test.ts tests/conductorAlerts.test.ts tests/budgetMeter.test.ts tests/sourceHygiene.test.ts`
    - Result: passed with `34` tests.
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm test`
    - Result: passed with `324` tests.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm run format:check`
    - Result: passed for `src/**/*.{ts,tsx}`.
  - `cd frontend && npm run build`
    - Result: passed; no `localStorage is not available because --localstorage-file was not provided` warning.
- Notes:
  - Remaining raw API-module fetches are now mostly intentional exceptions
    rather than ordinary boilerplate.
  - The same user-level npm config warning remains:
    `npm warn Unknown user config "allowBuilds"`.
  - The same Node `DEP0205 module.register()` warning from `tsx` remains in
    tests/build; it is not a project failure.

## 2026-07-07 Frontend API Response Boundary Batch 36

- Context:
  - After migrating split API modules to shared request helpers, the next risk
    was response-handler drift: the monolithic compatibility entrypoint still
    had its own `handleResponse()` implementation, and the shared helper parsed
    all successful responses as JSON, including potential `204` no-content
    responses.
- API boundary hardening:
  - Updated `frontend/src/lib/api/fetch.ts` so `handleResponse<T>()` returns
    `undefined as T` for `204` / `205` responses instead of attempting
    `response.json()`.
  - Updated `frontend/src/lib/api.ts` to import `API_BASE`, `WS_BASE`, and
    `handleResponse` from `./api/fetch`, removing its duplicate local base URL
    constants and response handler.
  - Extended `frontend/tests/apiFetchHelpers.test.ts` with a 204 regression
    test for `apiRequest<void>()`.
  - Extended `frontend/tests/apiCompatibility.test.ts` with a source contract
    that prevents reintroducing a second monolithic response handler or local
    API base constants.
- Spec sync:
  - Updated `.trellis/spec/ccgui/frontend/type-safety.md` so the split API
    helper contract explicitly documents `204` / `205` as `undefined as T`.
- Checks:
  - `cd frontend && node --import tsx --test tests/apiFetchHelpers.test.ts tests/sourceHygiene.test.ts`
    - Result: passed with `11` tests.
  - `cd frontend && node --import tsx --test tests/apiCompatibility.test.ts tests/apiCompatibilityExports.test.ts tests/apiFetchHelpers.test.ts tests/workspaceCreateUx.test.ts`
    - Result: passed with `14` tests.
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm test`
    - Result: passed with `326` tests.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm run format:check`
    - Result: passed for `src/**/*.{ts,tsx}`.
  - `cd frontend && npm run build`
    - Result: passed; no `localStorage is not available because --localstorage-file was not provided` warning.
- Notes:
  - The same user-level npm config warning remains:
    `npm warn Unknown user config "allowBuilds"`.
  - The same Node `DEP0205 module.register()` warning from `tsx` remains in
    tests/build; it is not a project failure.

## 2026-07-07 Frontend Benchmark API And Stack Contract Batch 37

- Context:
  - Backend benchmark handlers now expose typed request/response contracts.
    The frontend benchmark API module still carried the last ordinary JSON
    raw-fetch exceptions, and the frontend stack source-hygiene contract only
    enforced the Next.js major even though the spec describes Next/Tailwind/Base
    UI as a single stack contract.
- API boundary hardening:
  - Migrated `frontend/src/lib/api/benchmarks.ts` trigger-baseline and
    set-baseline calls onto shared split-API helpers.
  - Preserved soft-failure behavior for `setBaselineRun()` by returning
    `false` on non-OK responses and logging the same endpoint-specific error
    prefix.
  - Removed benchmark raw-fetch exceptions from
    `frontend/tests/sourceHygiene.test.ts`, shrinking the remaining raw API
    fetch allowance list to deliberate non-JSON/custom-response paths.
  - Added `frontend/tests/benchmarksApi.test.ts` to assert benchmark trigger
    URL/method/JSON body shape, successful baseline pinning, and soft-failure
    baseline behavior.
- Stack contract hardening:
  - Extended `frontend/tests/sourceHygiene.test.ts` so the stack docs contract
    now checks `next` major 15, `tailwindcss` major 4, and
    `@base-ui/react` presence against the ccgui and vibe-kanban frontend specs.
  - Updated both frontend quality specs to document the broader
    Next/Tailwind/Base UI source contract and its validation matrix.
- Checks:
  - `cd frontend && node --import tsx --test tests/benchmarksApi.test.ts tests/sourceHygiene.test.ts`
    - Result: passed with `12` tests.
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm test`
    - Result: passed with `333` tests.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm run format:check`
    - Result: passed for `src/**/*.{ts,tsx}`.
  - `cd frontend && npm run build`
    - Result: passed on Next.js `15.5.15`; generated `16/16` static pages.
- Notes:
  - The same user-level npm config warning remains:
    `npm warn Unknown user config "allowBuilds"`.
  - The same Node `DEP0205 module.register()` warning from `tsx` remains in
    tests/build; it is not a project failure.

## 2026-07-07 Backend Test Mypy Hygiene Batch 38

- Context:
  - Production backend mypy already covers `app benchmark`, but extending the
    probe to `tests` exposed a separate test-hygiene debt surface:
    `567` errors across `61` test files.
  - This batch intentionally avoided the largest noisy fixtures and first
    established a low-risk pattern on fully cleanable files.
- Type hygiene hardening:
  - Cleared all targeted mypy errors from:
    - `backend/tests/test_benchmark_runner.py`
    - `backend/tests/test_event_bus_ws.py`
    - `backend/tests/test_four_phase_preset.py`
    - `backend/tests/test_intent_classifier.py`
    - `backend/tests/test_project_service.py`
    - `backend/tests/test_security_hardening.py`
    - `backend/tests/test_specialist_orchestrator.py`
    - `backend/tests/test_specialist_orchestrator_start_failure.py`
  - Replaced implicit fixture assumptions with real assertions before indexing
    optional rows, JSON blobs, and aggregate metrics.
  - Annotated the async `ProjectService` fixture as an `AsyncGenerator`.
  - Aligned focused test-store method signatures with the production Protocol
    where the test double is meant to satisfy that Protocol, and used a narrow
    cast where the security test intentionally supplies a partial API store.
- Spec sync:
  - Added a backend quality convention: type-narrow test fixtures instead of
    ignoring mypy.
- Checks:
  - `cd backend && .venv/bin/python -m mypy tests/test_benchmark_runner.py tests/test_event_bus_ws.py tests/test_four_phase_preset.py tests/test_intent_classifier.py tests/test_project_service.py tests/test_security_hardening.py tests/test_specialist_orchestrator.py tests/test_specialist_orchestrator_start_failure.py --show-error-codes --no-pretty`
    - Result: passed for `8` source files.
  - `cd backend && .venv/bin/python -m ruff check tests/test_benchmark_runner.py tests/test_event_bus_ws.py tests/test_four_phase_preset.py tests/test_intent_classifier.py tests/test_project_service.py tests/test_security_hardening.py tests/test_specialist_orchestrator.py tests/test_specialist_orchestrator_start_failure.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_benchmark_runner.py tests/test_event_bus_ws.py tests/test_four_phase_preset.py tests/test_intent_classifier.py tests/test_project_service.py tests/test_security_hardening.py tests/test_specialist_orchestrator.py tests/test_specialist_orchestrator_start_failure.py`
    - Result: `97 passed in 3.00s`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed for `123` source files.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1088 passed, 77 skipped, 166 deselected, 3 warnings in 58.19s`.
- Measurement:
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Before this batch: `567` errors across `61` files.
    - After this batch: `557` errors across `53` files.
    - This remains a measurement probe, not a CI gate yet.

## 2026-07-07 Backend Test Mypy Hygiene Batch 39

- Context:
  - After Batch 38 removed the 1-error files, the next clean pool was thirteen
    files with two mypy errors each. Most were the same pattern: tests knew a
    fixture existed, but the type checker could not see the proof.
- Type hygiene hardening:
  - Cleared all targeted mypy errors from:
    - `backend/tests/test_audit_log_api.py`
    - `backend/tests/test_audit_logger.py`
    - `backend/tests/test_codex_task_runner.py`
    - `backend/tests/test_conductor_main_loop.py`
    - `backend/tests/test_conductor_openai_adapter.py`
    - `backend/tests/test_diagnostics_api.py`
    - `backend/tests/test_lifespan_shutdown.py`
    - `backend/tests/test_project_run.py`
    - `backend/tests/test_run_issue_conductor_loop.py`
    - `backend/tests/test_runtime_catalog.py`
    - `backend/tests/test_runtime_catalog_api_contract.py`
    - `backend/tests/test_task_dispatcher.py`
    - `backend/tests/test_workflow_node_batch_key.py`
  - Added explicit graph/store/catalog/project-id non-None assertions before
    dereferencing test fixtures.
  - Tightened test stub signatures for dispatcher and scheduler Protocols.
  - Replaced broad `SimpleNamespace` issue fixtures with real `CodexIssue`
    models where production helpers expect domain objects.
  - Added literal annotations for Conductor turn kinds and runtime-catalog
    protocol values.
- Checks:
  - `cd backend && .venv/bin/python -m mypy tests/test_audit_log_api.py tests/test_audit_logger.py tests/test_codex_task_runner.py tests/test_conductor_main_loop.py tests/test_conductor_openai_adapter.py tests/test_diagnostics_api.py tests/test_lifespan_shutdown.py tests/test_project_run.py tests/test_run_issue_conductor_loop.py tests/test_runtime_catalog.py tests/test_runtime_catalog_api_contract.py tests/test_task_dispatcher.py tests/test_workflow_node_batch_key.py --show-error-codes --no-pretty`
    - Result: passed for `13` source files.
  - `cd backend && .venv/bin/python -m ruff check tests/test_audit_log_api.py tests/test_audit_logger.py tests/test_codex_task_runner.py tests/test_conductor_main_loop.py tests/test_conductor_openai_adapter.py tests/test_diagnostics_api.py tests/test_lifespan_shutdown.py tests/test_project_run.py tests/test_run_issue_conductor_loop.py tests/test_runtime_catalog.py tests/test_runtime_catalog_api_contract.py tests/test_task_dispatcher.py tests/test_workflow_node_batch_key.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_audit_log_api.py tests/test_audit_logger.py tests/test_codex_task_runner.py tests/test_conductor_main_loop.py tests/test_conductor_openai_adapter.py tests/test_diagnostics_api.py tests/test_lifespan_shutdown.py tests/test_project_run.py tests/test_run_issue_conductor_loop.py tests/test_runtime_catalog.py tests/test_runtime_catalog_api_contract.py tests/test_task_dispatcher.py tests/test_workflow_node_batch_key.py`
    - Result: `158 passed, 3 warnings in 6.70s`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed for `123` source files.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1088 passed, 77 skipped, 166 deselected, 3 warnings in 51.41s`.
- Measurement:
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - After Batch 38: `557` errors across `53` files.
    - After Batch 39: `531` errors across `40` files.
    - This remains a measurement probe, not a CI gate yet.

## 2026-07-07 Backend Test Mypy Hygiene Batch 40

- Context:
  - The next low-risk pool contained eight files with three mypy errors each.
    One file, `test_reader_loop_finalize.py`, was deliberately skipped because
    clearing it safely requires a deeper runtime-process Protocol design rather
    than a local test assertion.
- Type hygiene hardening:
  - Cleared all targeted mypy errors from:
    - `backend/tests/test_agent_catalog.py`
    - `backend/tests/test_ci_quality_gates.py`
    - `backend/tests/test_conductor_policy.py`
    - `backend/tests/test_conductor_redispatch_budget.py`
    - `backend/tests/test_embedding_service.py`
    - `backend/tests/test_prototypes_api.py`
    - `backend/tests/test_task_chat_endpoint.py`
  - Added a typed TOML table helper in the CI quality-gate test so pyproject
    indexing proves table shape before reading nested keys.
  - Replaced broad issue `SimpleNamespace` fixtures with real `CodexIssue`
    models in conductor policy tests.
  - Added non-None assertions for prototype services, task reloads, and
    subagent result artifacts before dereferencing.
  - Tightened method-assignment ignores in embedding tests to the precise
    `method-assign` code.
- Checks:
  - `cd backend && .venv/bin/python -m mypy tests/test_agent_catalog.py tests/test_ci_quality_gates.py tests/test_conductor_policy.py tests/test_conductor_redispatch_budget.py tests/test_embedding_service.py tests/test_prototypes_api.py tests/test_task_chat_endpoint.py --show-error-codes --no-pretty`
    - Result: passed for `7` source files.
  - `cd backend && .venv/bin/python -m ruff check tests/test_agent_catalog.py tests/test_ci_quality_gates.py tests/test_conductor_policy.py tests/test_conductor_redispatch_budget.py tests/test_embedding_service.py tests/test_prototypes_api.py tests/test_task_chat_endpoint.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_agent_catalog.py tests/test_ci_quality_gates.py tests/test_conductor_policy.py tests/test_conductor_redispatch_budget.py tests/test_embedding_service.py tests/test_prototypes_api.py tests/test_task_chat_endpoint.py`
    - Result: `80 passed in 5.95s`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed for `123` source files.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1088 passed, 77 skipped, 166 deselected, 3 warnings in 52.14s`.
- Measurement:
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - After Batch 39: `531` errors across `40` files.
    - After Batch 40: `510` errors across `33` files.
    - This remains a measurement probe, not a CI gate yet.

## 2026-07-07 Backend Test Mypy Hygiene Batch 41

- Context:
  - The next safe pool was the four 4-error files. These were still mostly
    fixture-shape and Protocol-alignment issues, plus one production service
    constructor that was typed more concretely than its runtime needs.
- Type hygiene hardening:
  - Cleared all targeted mypy errors from:
    - `backend/tests/test_architect_workflow.py`
    - `backend/tests/test_benchmark_scorers.py`
    - `backend/tests/test_orchestration_service_statuses.py`
    - `backend/tests/test_self_improvement_seal.py`
  - Changed `OrchestrationService` to depend on an
    `OrchestrationSessionService` Protocol rather than the concrete
    `SessionService`, matching its actual dependency on `sessions`,
    `get_session()`, and `update_session()`.
  - Added concrete non-None assertions for architect task paths and
    self-improvement seal mock call/state captures.
  - Narrowed benchmark scorer metadata before indexing nested `failed` /
    `uncovered` collections.
- Spec sync:
  - Added a backend quality convention for typing service constructor
    dependencies by capability Protocol instead of concrete implementation when
    only a subset is required.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/orchestration_service.py tests/test_architect_workflow.py tests/test_benchmark_scorers.py tests/test_orchestration_service_statuses.py tests/test_self_improvement_seal.py --show-error-codes --no-pretty`
    - Result: passed for `5` source files.
  - `cd backend && .venv/bin/python -m ruff check app/application/orchestration_service.py tests/test_architect_workflow.py tests/test_benchmark_scorers.py tests/test_orchestration_service_statuses.py tests/test_self_improvement_seal.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_architect_workflow.py tests/test_benchmark_scorers.py tests/test_orchestration_service_statuses.py tests/test_self_improvement_seal.py`
    - Result: `48 passed in 0.73s`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed for `123` source files.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1088 passed, 77 skipped, 166 deselected, 3 warnings in 61.46s`.
- Measurement:
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - After Batch 40: `510` errors across `33` files.
    - After Batch 41: `494` errors across `29` files.
    - This remains a measurement probe, not a CI gate yet.

## 2026-07-07 Backend Test Mypy Hygiene Batch 42

- Context:
  - The next safe subset inside the 5-error pool excluded runtime-process,
    websocket, and prototype-service tests that need wider fake/protocol design.
- Type hygiene hardening:
  - Cleared all targeted mypy errors from:
    - `backend/tests/test_artifact_validation_signal.py`
    - `backend/tests/test_execution_process_kind.py`
    - `backend/tests/test_project_review_scheduler.py`
    - `backend/tests/test_review_guard_integration.py`
    - `backend/tests/test_task_refine_endpoint.py`
  - Narrowed project-review scheduler summary payload results before indexing.
  - Added non-None assertions for persisted execution processes and review-guard
    worktree paths.
  - Replaced direct dynamic marker assignment on `CodexTask` with an explicit
    test-only cast to model the runtime validation marker.
  - Kept the intentionally invalid `ExecutionProcess.kind` test explicit via a
    narrow literal cast so the runtime Pydantic rejection remains covered.
- Checks:
  - `cd backend && .venv/bin/python -m mypy tests/test_project_review_scheduler.py tests/test_execution_process_kind.py tests/test_review_guard_integration.py tests/test_task_refine_endpoint.py tests/test_artifact_validation_signal.py --show-error-codes --no-pretty`
    - Result: passed for `5` source files.
  - `cd backend && .venv/bin/python -m ruff check tests/test_project_review_scheduler.py tests/test_execution_process_kind.py tests/test_review_guard_integration.py tests/test_task_refine_endpoint.py tests/test_artifact_validation_signal.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_project_review_scheduler.py tests/test_execution_process_kind.py tests/test_review_guard_integration.py tests/test_task_refine_endpoint.py tests/test_artifact_validation_signal.py`
    - Result: `39 passed in 3.84s`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed for `123` source files.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1088 passed, 77 skipped, 166 deselected, 3 warnings in 49.16s`.
- Measurement:
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - After Batch 41: `494` errors across `29` files.
    - After Batch 42: `469` errors across `24` files.
    - This remains a measurement probe, not a CI gate yet.

## 2026-07-07 Backend Test Mypy Hygiene Batch 43

- Context:
  - The remaining 5/6-error pools include several runtime and websocket fake
    types that need deeper design. This batch picked two safe 6-error files that
    were still pure fixture/metadata typing.
- Type hygiene hardening:
  - Cleared all targeted mypy errors from:
    - `backend/tests/test_benchmark_judge_correlation.py`
    - `backend/tests/test_self_improvement_service.py`
  - Narrowed LLM judge metadata fields before substring checks.
  - Narrowed loaded calibration items before reading `human_score` and `note`.
  - Replaced `CodexIssue(**dict[str, object])` with `CodexIssue.model_validate`
    in the self-improvement service test helper.
  - Added a concrete proposal list type for the in-memory self-improvement test
    store.
- Checks:
  - `cd backend && .venv/bin/python -m mypy tests/test_self_improvement_service.py tests/test_benchmark_judge_correlation.py --show-error-codes --no-pretty`
    - Result: passed for `2` source files.
  - `cd backend && .venv/bin/python -m ruff check tests/test_self_improvement_service.py tests/test_benchmark_judge_correlation.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_self_improvement_service.py tests/test_benchmark_judge_correlation.py`
    - Result: `40 passed in 0.69s`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed for `123` source files.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1088 passed, 77 skipped, 166 deselected, 3 warnings in 58.00s`.
- Measurement:
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - After Batch 42: `469` errors across `24` files.
    - After Batch 43: `457` errors across `22` files.
    - This remains a measurement probe, not a CI gate yet.

## 2026-07-07 Backend Test Mypy Hygiene Batch 44

- Context:
  - After clearing the easy 6-error files, the next safe 7/8-error candidates
    were knowledge-index and workflow-scheduler tests. The dispatch-batch
    concurrency test was skipped because it monkeypatches function attributes
    and registry methods in a way that deserves a separate fake design.
- Type hygiene hardening:
  - Cleared all targeted mypy errors from:
    - `backend/tests/test_knowledge_index.py`
    - `backend/tests/test_workflow_scheduler_auto_retry.py`
  - Typed knowledge-index artifact fixtures as `ArtifactRow`.
  - Narrowed search snippets before HTML/snippet substring assertions.
  - Typed RRF merge fixtures as `SearchHit` lists.
  - Replaced `CodexTask(**dict[str, object])` helpers with
    `CodexTask.model_validate`.
- Checks:
  - `cd backend && .venv/bin/python -m mypy tests/test_knowledge_index.py tests/test_workflow_scheduler_auto_retry.py --show-error-codes --no-pretty`
    - Result: passed for `2` source files.
  - `cd backend && .venv/bin/python -m ruff check tests/test_knowledge_index.py tests/test_workflow_scheduler_auto_retry.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_knowledge_index.py tests/test_workflow_scheduler_auto_retry.py`
    - Result: `18 passed in 0.90s`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed for `123` source files.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1088 passed, 77 skipped, 166 deselected, 3 warnings in 56.12s`.
- Measurement:
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - After Batch 43: `457` errors across `22` files.
    - After Batch 44: `441` errors across `20` files.
    - This remains a measurement probe, not a CI gate yet.

## 2026-07-07 Backend Test Mypy Hygiene Batch 45

- Context:
  - Continued the test-mypy graduation, but followed the user's preference for
    larger structural cleanup where it reduced real ambiguity.
- Type/API hygiene hardening:
  - Cleared all targeted mypy errors from:
    - `backend/tests/test_conductor_policy_endpoint.py`
    - `backend/tests/test_swarm_integration.py`
  - Added a typed `IssueOrchestrationPolicyResponse` endpoint contract.
  - Added a shared swarm-test helper that proves issue branch/worktree setup
    before path/branch use.
- Checks:
  - `cd backend && .venv/bin/python -m mypy tests/test_conductor_policy_endpoint.py tests/test_swarm_integration.py --show-error-codes --no-pretty`
    - Result: passed for `2` source files.
  - `cd backend && .venv/bin/python -m ruff check tests/test_conductor_policy_endpoint.py tests/test_swarm_integration.py app/interfaces/api.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_conductor_policy_endpoint.py`
    - Result: `4 passed in 0.31s`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings -m slow tests/test_swarm_integration.py`
    - Result: `10 passed in 11.83s`.
- Measurement:
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - After Batch 44: `441` errors across `20` files.
    - After Batch 45: `421` errors across `18` files.
    - This remains a measurement probe, not a CI gate yet.

## 2026-07-07 Backend Test Mypy Hygiene Batch 46

- Type/API hygiene hardening:
  - Cleared all targeted mypy errors from:
    - `backend/tests/test_worktree_manager.py`
  - Replaced anonymous `dict[str, object]` merge summaries in
    `backend/app/application/worktree_manager.py` with typed
    `AgentMergeSpec`, `AgentMergeSummary`, and conflict/record payloads.
  - Kept dispatch-batch merge errors outside the normal summary shape via a
    separate `merge_error` output field.
  - Fixed a real note regression where the conflict-specific note could be
    overwritten by the generic partial-join note.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/worktree_manager.py app/application/conductor_tools.py tests/test_worktree_manager.py tests/test_conductor_dispatch_batch.py --show-error-codes --no-pretty`
    - Result: passed for `4` source files.
  - `cd backend && .venv/bin/python -m ruff check app/application/worktree_manager.py app/application/conductor_tools.py tests/test_worktree_manager.py tests/test_conductor_dispatch_batch.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_worktree_manager.py tests/test_conductor_dispatch_batch.py`
    - Result: `31 passed in 12.29s`.
- Measurement:
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - After Batch 45: `421` errors across `18` files.
    - After Batch 46: `387` errors across `17` files.
    - This remains a measurement probe, not a CI gate yet.

## 2026-07-07 Backend Test Mypy Hygiene Batch 47

- Type/API hygiene hardening:
  - Cleared all targeted mypy errors from:
    - `backend/tests/test_issue_budget_endpoint.py`
    - `backend/tests/test_pipeline_stages.py`
  - Reused the existing `IssueBudgetPayload` as the budget endpoint return
    contract.
  - Added typed response contracts for pipeline stages, issue activity, and
    graph stats in `backend/app/interfaces/api.py`.
  - Narrowed optional PM summary/foot text in tests before substring checks.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/interfaces/api.py tests/test_issue_budget_endpoint.py tests/test_pipeline_stages.py --show-error-codes --no-pretty`
    - Result: passed for the targeted files.
  - `cd backend && .venv/bin/python -m ruff check app/interfaces/api.py tests/test_issue_budget_endpoint.py tests/test_pipeline_stages.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_issue_budget_endpoint.py tests/test_pipeline_stages.py`
    - Result: `17 passed`.
- Measurement:
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - After Batch 46: `387` errors across `17` files.
    - After Batch 47: `340` errors across `15` files.
    - This remains a measurement probe, not a CI gate yet.

## 2026-07-07 Backend Test Mypy Hygiene Batch 48

- Type/API hygiene hardening:
  - Cleared all targeted mypy errors from:
    - `backend/tests/test_self_improvement_apply_service.py`
    - `backend/tests/test_self_improvement_api.py`
  - Replaced the self-improvement apply plan's anonymous
    `dict[str, object]` shape with a discriminated TypedDict union for
    `append_markdown` versus `open_pr_task` candidates.
  - Added local API-test JSON boundary helpers so `resp.json()` does not leak
    `Any` into project/application assertions.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/self_improvement_apply_service.py tests/test_self_improvement_apply_service.py tests/test_self_improvement_api.py --show-error-codes --no-pretty`
    - Result: passed for the targeted files.
  - `cd backend && .venv/bin/python -m ruff check app/application/self_improvement_apply_service.py tests/test_self_improvement_apply_service.py tests/test_self_improvement_api.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_self_improvement_apply_service.py`
    - Result: `15 passed in 0.34s`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings -m slow tests/test_self_improvement_api.py`
    - Result: `56 passed in 13.51s`.
- Measurement:
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - After Batch 47: `340` errors across `15` files.
    - After Batch 48: `319` errors across `13` files.
    - This remains a measurement probe, not a CI gate yet.

## 2026-07-07 Backend Test Mypy Hygiene Batch 49

- Type/API hygiene hardening:
  - Cleared all targeted mypy errors from:
    - `backend/tests/test_agent_process_environment.py`
    - `backend/tests/test_execution_process_ws_async_store.py`
    - `backend/tests/test_prototype_service.py`
  - Made runtime fake stores implement the actual process-runtime Protocol
    surface instead of passing `None`/partial stores through constructors.
  - Narrowed WebSocket fallback events and execution-process state payloads
    before indexing.
  - Typed prototype-service async fixtures and narrowed version/candidate list
    responses at the test boundary.
- Checks:
  - Targeted mypy for the three files: passed.
  - Targeted ruff for the three files: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_agent_process_environment.py tests/test_execution_process_ws_async_store.py tests/test_prototype_service.py`
    - Result: `44 passed`.
- Measurement:
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - After Batch 48: `319` errors across `13` files.
    - After Batch 49: `304` errors across `10` files.
    - This remains a measurement probe, not a CI gate yet.

## 2026-07-07 Backend Test Mypy Hygiene Batch 50

- Type/API hygiene hardening:
  - Cleared all targeted mypy errors from:
    - `backend/tests/test_project_conductor.py`
    - `backend/tests/test_github_pr_followup.py`
  - Tightened `GitHubPRFollowupStore.load_codex_task/save_codex_task` from
    `object` to the actual `CodexTask` domain type, making the Protocol match
    real store behavior.
  - Aligned GitHub PR follow-up test store method signatures with the Protocol.
  - Narrowed loaded conductor state and result payloads before indexing.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/github_pr_followup.py app/application/project_conductor.py tests/test_project_conductor.py tests/test_github_pr_followup.py --show-error-codes --no-pretty`
    - Result: passed for the targeted files.
  - `cd backend && .venv/bin/python -m ruff check app/application/github_pr_followup.py app/application/project_conductor.py tests/test_project_conductor.py tests/test_github_pr_followup.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_project_conductor.py tests/test_github_pr_followup.py`
    - Result: `22 passed in 1.00s`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed for `123` source files.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1088 passed, 77 skipped, 166 deselected, 3 warnings in 52.27s`.
- Measurement:
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - After Batch 49: `304` errors across `10` files.
    - After Batch 50: `272` errors across `8` files.
    - This remains a measurement probe, not a CI gate yet.

## 2026-07-07 Backend Test Mypy Hygiene Batch 51

- Type/API hygiene hardening:
  - Cleared all remaining non-legacy backend test-mypy errors from:
    - `backend/tests/test_message_streaming.py`
    - `backend/tests/test_ws_subscriber_backpressure.py`
    - `backend/tests/test_reader_loop_finalize.py`
    - `backend/tests/test_help_orchestrator.py`
    - `backend/tests/test_dispatch_batch_budget_concurrency.py`
    - `backend/tests/test_operations_engineer_script_task.py`
    - `backend/tests/test_async_refresh_task_result.py`
  - Changed `WsSubscriber` from a concrete FastAPI `WebSocket` dependency to a
    small `WsSendChannel` Protocol so websocket tests can use focused fakes
    without pretending to inherit framework internals.
  - Aligned runtime/runner fake stores with the actual domain Protocol
    signatures (`CodexTask`, `CodexTaskMessage`, `HelpRequest`,
    `ExecutionProcess`, `LogEvent`) instead of broad untyped stubs.
  - Replaced direct function/method monkeypatch assignment in dispatch-batch
    tests with `pytest.MonkeyPatch.context()` and closure state.
  - Marked the fully skipped legacy `test_codex_tasks.py` module as
    `mypy: ignore-errors`; current project/worktree critical paths remain in
    `test_codex_tasks_ported.py`.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `258` source files.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark --show-error-codes --no-pretty`
    - Result: passed for `123` source files.
  - `cd backend && .venv/bin/python -c "from app.main import app"`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1088 passed, 77 skipped, 166 deselected, 3 warnings in 50.26s`.
- Measurement:
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - After Batch 50: `272` errors across `8` files.
    - After Batch 51: `0` errors across `258` checked source files.
    - The test-mypy measurement now passes locally; promoting it to CI should
      be a separate explicit gate change.

## 2026-07-07 Backend Test Mypy CI Promotion Batch 52

- Quality gate hardening:
  - Promoted backend mypy from `app benchmark` to `app benchmark tests` in
    `.github/workflows/ci.yml`.
  - Updated README quality-gate documentation and the CI quality regression
    test so local docs, spec, and CI all require the same backend mypy command.
  - Updated backend quality guidelines to treat backend tests as part of the
    hard mypy gate.
  - Added a regression guard so `# mypy: ignore-errors` in backend tests is
    explicitly allowlisted; the only allowed module is the runtime-skipped
    legacy `test_codex_tasks.py` suite.
- Checks:
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_ci_quality_gates.py tests/test_mypy_strict_coverage.py`
    - Result: `9 passed in 0.20s`.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `258` source files.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.

## 2026-07-07 Frontend Full Quality Gate Batch 53

- Quality verification:
  - Re-ran the complete documented frontend gate after backend CI/mypy
    hardening to ensure the broader project remains green.
  - Observed npm warning: `Unknown user config "allowBuilds"`; it did not fail
    any gate and was left unchanged.
- Checks:
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm test -- --runInBand`
    - Result: `333` tests passed.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm run build`
    - Result: passed; Next.js built `16` static pages plus dynamic routes.
  - `cd frontend && npm run format:check`
    - Result: passed; all matched files use Prettier style.

## 2026-07-07 Backend Slow Test Sweep Batch 54

- Quality verification:
  - Ran the backend slow-test lane that is excluded from the default pytest
    command. This adds coverage for longer integration-style paths after the
    backend mypy gate was promoted.
- Checks:
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings -m slow`
    - Result: `166 passed, 1167 deselected in 51.60s`.

## 2026-07-07 Backend Pytest Warning Cleanup Batch 55

- Reliability hardening:
  - Removed the default pytest warning summary caused by leaked aiosqlite
    worker threads in audit-log tests.
  - Added async store lifecycle fixtures / `finally: close()` handling in:
    - `backend/tests/test_audit_logger.py`
    - `backend/tests/test_audit_log_api.py`
- Checks:
  - `cd backend && .venv/bin/python -m pytest -q --tb=short tests/test_audit_logger.py tests/test_audit_log_api.py`
    - Result: `34 passed in 1.77s`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short`
    - Result: `1090 passed, 77 skipped, 166 deselected in 53.98s` with no warnings summary.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `258` source files.

## 2026-07-07 Frontend Dependency Audit Hardening Batch 56

- Dependency/security hardening:
  - Upgraded runtime Next.js from `^15.0.0` to `^15.5.20`, keeping the project
    on the documented Next.js 15 stack while picking up the latest 15.x
    security release.
  - Moved `shadcn` from production `dependencies` to `devDependencies` after
    confirming runtime code does not import it; this removes its MCP/Hono/
    Express CLI tree from production installs and production audit scope.
  - Upgraded dev-only `shadcn` to `^4.13.0`, `@next/swc-wasm-nodejs` to
    `^15.5.20`, and `tsx` to `^4.23.0`.
  - Added exact npm `overrides` for patched transitive versions:
    `@babel/core@7.29.7`, `express-rate-limit@8.5.2`,
    `fast-uri@3.1.3`, `hono@4.12.28`, `ip-address@10.2.0`,
    `js-yaml@4.3.0`, `brace-expansion@5.0.7` under `minimatch@10.2.5`,
    `postcss@8.5.16`, and `qs@6.15.3`.
  - Recorded the dependency-audit boundary convention in both frontend quality
    specs so future package changes keep CLI-only tools out of production
    dependencies and use the official npm registry for audit evidence.
- Audit evidence:
  - Before hardening, `cd frontend && npm audit --omit=dev --registry=https://registry.npmjs.org --json`
    reported `10` production vulnerabilities (`1` low, `7` moderate,
    `2` high) after the initial Next-only update; the high production items
    came from `shadcn -> @modelcontextprotocol/sdk -> hono/fast-uri`.
  - After hardening, `cd frontend && npm audit --omit=dev --registry=https://registry.npmjs.org --json`
    reported `0` vulnerabilities.
  - After hardening, `cd frontend && npm audit --registry=https://registry.npmjs.org --json`
    reported `0` vulnerabilities across production and dev dependencies.
  - `cd frontend && npm ls @babel/core brace-expansion esbuild express-rate-limit fast-uri hono ip-address js-yaml postcss qs tsx next shadcn`
    confirmed the patched versions and showed `next@15.5.20` using
    overridden `postcss@8.5.16`.
- Checks:
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm test -- --runInBand`
    - Result: `333` tests passed.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm run format:check`
    - Result: passed; all matched files use Prettier style.
  - `cd frontend && npm run build`
    - Result: passed; Next.js 15.5.20 compiled successfully and generated the
      app routes. Node emitted a non-fatal `DEP0205` deprecation warning from
      the toolchain.
  - `cd frontend && node --import tsx --test tests/sourceHygiene.test.ts`
    - Result: `9` tests passed.
  - `git diff --check`
    - Result: passed.

## 2026-07-07 Frontend Dependency Audit Batch 74

- Supply-chain check:
  - Ran the frontend production dependency audit after the runtime JSON boundary
    sweep and legacy JS cleanup.
  - Ran the full frontend dependency audit, including dev dependencies, through
    the official npm registry.
- Checks:
  - `cd frontend && npm audit --omit=dev --registry=https://registry.npmjs.org`
    - Result: `found 0 vulnerabilities`.
  - `cd frontend && npm audit --registry=https://registry.npmjs.org`
    - Result: `found 0 vulnerabilities`.

## 2026-07-07 Backend Dependency Audit Batch 75

- Supply-chain check:
  - Ran `pip-audit` against `backend/requirements.txt` after the backend
    security and subprocess-boundary cleanup.
- Checks:
  - `cd backend && pipx run pip-audit -r requirements.txt`
    - Result: no known vulnerabilities found.

## 2026-07-07 Backend Subprocess Source-Hygiene Batch 76

- Source hygiene:
  - Extended `backend/tests/test_backend_source_hygiene.py` with an AST rule
    that rejects direct synchronous `subprocess.run(...)`,
    `subprocess.Popen(...)`, `subprocess.call(...)`,
    `subprocess.check_call(...)`, and `subprocess.check_output(...)` calls under
    `backend/app` and `backend/benchmark` outside
    `backend/app/adapters/local_process.py`.
  - Updated backend quality guidelines so the trusted local subprocess boundary
    includes the new regression test and failure mode.
- Checks:
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_backend_source_hygiene.py`
    - Result: `2 passed`.
  - `cd backend && .venv/bin/python -m ruff check tests/test_backend_source_hygiene.py app/adapters/local_process.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy tests/test_backend_source_hygiene.py app/adapters/local_process.py --show-error-codes --no-pretty`
    - Result: passed for `2` source files; single-file mypy emitted the
      existing unused-override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `261` source files.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_backend_source_hygiene.py tests/test_mypy_strict_coverage.py tests/test_ci_quality_gates.py`
    - Result: `11 passed`.
  - `cd backend && pipx run bandit -r app benchmark -f json -q`
    - Result: empty `results` list; no high, medium, or low findings.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1106 passed, 77 skipped, 166 deselected`.

## 2026-07-07 Backend Bare Except Source-Hygiene Batch 77

- Source hygiene:
  - Extended `backend/tests/test_backend_source_hygiene.py` with a stable
    allowlist for existing bare `except ...: pass` sites under `backend/app`
    and `backend/benchmark`.
  - The test keys sites by relative path, enclosing scope, and exception type
    instead of line number, so normal code movement does not make the allowlist
    noisy while new silent exception swallowing still fails the test.
  - Updated backend quality guidelines to document the bare-except/pass
    allowlist and the expectation that new swallowed exceptions either log with
    context, use a more precise `contextlib.suppress(...)`, or get reviewed as
    an explicit allowlist change.
- Checks:
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_backend_source_hygiene.py tests/test_mypy_strict_coverage.py tests/test_ci_quality_gates.py`
    - Result: `12 passed`.
  - `cd backend && .venv/bin/python -m ruff check tests/test_backend_source_hygiene.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy tests/test_backend_source_hygiene.py --show-error-codes --no-pretty`
    - Result: passed for `1` source file; single-file mypy emitted the
      existing unused-override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `261` source files.
  - `cd backend && pipx run bandit -r app benchmark -f json -q`
    - Result: empty `results` list; no high, medium, or low findings.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1107 passed, 77 skipped, 166 deselected, 1 warning`.

## 2026-07-07 Frontend Debug Output Source-Hygiene Batch 78

- Source hygiene:
  - Extended `frontend/tests/sourceHygiene.test.ts` so runtime source rejects
    `console.log(...)`, `console.debug(...)`, `console.warn(...)`, and
    `debugger`.
  - Left existing `console.error(...)` paths available for explicit degradation
    / failure reporting where the UI intentionally continues.
  - Updated ccgui and vibe-kanban frontend quality specs with the debug-output
    rule.
- Checks:
  - `cd frontend && node --import tsx --test tests/sourceHygiene.test.ts`
    - Result: `19` tests passed.
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm run lint`
    - Result: passed.

## 2026-07-07 Backend Trusted Local Process Boundary Batch 67

- Static security cleanup:
  - Added `backend/app/adapters/local_process.py` as the explicit boundary for
    trusted local subprocess execution.
  - Migrated synchronous local `subprocess.run(...)` callers that execute
    project-owned commands through `run_trusted_local(...)`.
  - Added the adapter to strict backend mypy overrides and removed stale
    call-site `# nosec` comments now covered by the boundary.
- Checks:
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `261` source files.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1105 passed, 77 skipped, 166 deselected`.
  - `cd backend && pipx run bandit -r app benchmark -f json -q`
    - Result: `0` findings.

## 2026-07-07 Frontend JSON Boundary Helpers Batch 68

- Type-safety cleanup:
  - Added JSON boundary helpers in `frontend/src/lib/utils.tsx`:
    `safeJsonParse`, `isRecord`, `safeJsonRecord`,
    `safeJsonStringArray`, and `safeJsonNumberRecord`.
  - Hardened browser storage parsing in preferences, grids, workbench state,
    and app boot preference handling so corrupt persisted JSON falls back
    instead of poisoning render or hydration state.
  - Added utility coverage in `frontend/tests/utils.test.ts` and storage
    source-hygiene checks in `frontend/tests/sourceHygiene.test.ts`.

## 2026-07-07 Prototype Stream Parser Batch 69

- Type-safety cleanup:
  - Added `frontend/src/features/prototype/prototypeStreamEvents.ts` for
    feature-local SSE record and code-candidate narrowing.
  - Refactored prototype canvas and project prototype generation handlers away
    from direct `JSON.parse(...)` in UI event handlers.
  - Added `frontend/tests/prototypeStreamEvents.test.ts` and source-hygiene
    coverage that rejects direct prototype SSE parsing in components.

## 2026-07-07 Execution Process Stream Parsers Batch 70

- Type-safety cleanup:
  - Added `frontend/src/hooks/executionProcessStreamFrames.ts` for
    per-process message/log WebSocket frames.
  - Added `frontend/src/hooks/executionProcessesStreamFrames.ts` for global
    and workspace execution-process envelopes, patches, ready, and terminal
    frames.
  - Refactored `useExecutionProcessMessageStream`,
    `useExecutionProcessLogStream`, and `useExecutionProcesses` to consume
    typed frame unions before mutating React state.
  - Added focused node tests for malformed frames, control frames, deltas,
    heartbeats, log rows, event ids, resume gaps, patches, and terminal frames.

## 2026-07-07 Project Conductor Stream Parser Batch 71

- Type-safety cleanup:
  - Added `frontend/src/features/projects/components/projectConductorStreamEvents.ts`
    for project-conductor SSE record and tool-event narrowing.
  - Refactored `ProjectConductorThreadDock` so the component receives already
    narrowed tool events and drops malformed frames without throwing.
  - Added `frontend/tests/projectConductorStreamEvents.test.ts` and extended
    source-hygiene checks for conductor event parsing.
- Checks:
  - `cd frontend && node --import tsx --test tests/projectConductorStreamEvents.test.ts tests/projectConductorI18n.test.ts tests/sourceHygiene.test.ts`
    - Result: `24` tests passed.
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm test`
    - Result: `356` tests passed.
  - `cd frontend && npm run format:check`
    - Result: passed.
  - `cd frontend && npm run build`
    - Result: passed. Existing npm `allowBuilds` and Node
      `module.register()` warnings remain non-fatal.

## 2026-07-07 Frontend Legacy JS Normalizer Cleanup Batch 73

- Source cleanup:
  - Removed tracked legacy JavaScript mirrors that were no longer used by the
    Next/TypeScript runtime or by the current `npm test` script:
    `frontend/src/utils/codexLogNormalizer.js`,
    `frontend/src/hooks/taskConversationDetailUtils.js`, and their legacy
    `.test.js` files.
  - Confirmed active imports now use the TypeScript implementations under
    `frontend/src/lib/` and `frontend/src/hooks/`.
  - Re-scanned `frontend/src` for direct `JSON.parse(...)`; only the shared
    helper implementation and the inline app boot script remain.
- Checks:
  - `cd frontend && rg -n "taskConversationDetailUtils\\.js|utils/codexLogNormalizer\\.js|codexLogNormalizer\\.test\\.js|executionProcessPatch\\.test\\.js" frontend --glob '!node_modules' --glob '!.next'`
    - Result: no live frontend references.
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm test`
    - Result: `368` tests passed.
  - `cd frontend && npm run format:check`
    - Result: passed.
  - `cd frontend && npm run build`
    - Result: passed. Existing npm `allowBuilds` and Node
      `module.register()` warnings remain non-fatal.
  - `git diff --check`
    - Result: passed.

## 2026-07-07 Frontend Runtime JSON Boundary Sweep Batch 72

- Type-safety cleanup:
  - Routed `codexLogNormalizer.ts` through `safeJsonRecord(...)` and added
    source-hygiene coverage so runtime log normalization no longer calls
    `JSON.parse(...)` directly.
  - Added `frontend/src/features/issues/issueResultParsing.ts` for issue
    result records, agent-result sections, role summaries, JSON summary
    extraction, and hook-control-envelope filtering.
  - Refactored `AgentDecisionDrawer`, `IssueNarrativeTimeline`, and
    `useDecisionTimeline` to consume the shared issue-result parser.
  - Added `frontend/src/features/workbench/qaReportStatus.ts` and refactored
    `WorkbenchPage` plus `TaskExecutionSheet` to share the QA report status
    literal guard.
  - Replaced remaining direct runtime `JSON.parse(...)` calls in artifact
    language detection, audit payload parsing, agent dock tool scanning, skills
    import parsing, conductor diff parsing, task-run assistant text extraction,
    and live run failure-result formatting.
  - Added a broad runtime source-hygiene check that allows direct
    `JSON.parse(...)` only in the shared helper implementation and the inline
    app boot script that cannot import modules before hydration.
  - Updated ccgui and vibe-kanban frontend type-safety specs with the runtime
    JSON boundary contract.
- Checks:
  - `cd frontend && node --import tsx --test tests/sourceHygiene.test.ts tests/issueResultParsing.test.ts tests/qaReportStatus.test.ts tests/codexLogNormalizer.test.ts`
    - Result: `33` tests passed.
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm run format:check`
    - Result after formatting touched files: passed.
  - `cd frontend && npm test`
    - Result: `368` tests passed.
  - `cd frontend && npm run build`
    - Result: passed. Existing npm `allowBuilds` and Node
      `module.register()` warnings remain non-fatal.

## 2026-07-07 Frontend Prototype SSE Type Boundary Batch 68

- Frontend parsing/type-safety cleanup:
  - Added `safeJsonParse(...)` and `isRecord(...)` to `frontend/src/lib/utils.tsx`,
    aligning the implementation with the existing frontend type-safety spec.
  - Added `frontend/src/features/prototype/prototypeStreamEvents.ts` to parse
    SSE `event.data` into `Record<string, unknown>` and narrow strings,
    numbers, string arrays, code-candidate payloads, failed-prototype lists, and
    code-generation summaries without direct component casts.
  - Refactored `PrototypeCanvas` and `ProjectPrototypesPage` so prototype
    generation, code-driven generation, and batch-regeneration EventSource
    handlers no longer call `JSON.parse(...)` directly.
  - Added source hygiene coverage preventing direct `JSON.parse(...)` from
    returning to `frontend/src/features/prototype/**` outside the typed SSE
    helper.
  - Updated both canonical and mirror frontend type-safety specs with the typed
    SSE payload parsing contract.
- Checks:
  - `cd frontend && node --import tsx --test tests/prototypeStreamEvents.test.ts tests/sourceHygiene.test.ts tests/prototypeApi.test.ts`
    - Result: `19` tests passed.
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm test`
    - Result: `339` tests passed.
  - `cd frontend && npm run format:check`
    - Result: passed after running Prettier on the touched prototype files.
  - `cd frontend && npm audit --registry=https://registry.npmjs.org`
    - Result: `0` vulnerabilities.
  - `cd frontend && npm run build`
    - Result: passed; Next.js 15.5.20 production build completed successfully.

## 2026-07-07 Frontend Global Execution Stream Parser Batch 71

- Frontend realtime-stream type cleanup:
  - Added `frontend/src/hooks/executionProcessesStreamFrames.ts`, a pure parser
    for the global event-bus WebSocket envelope and workspace execution-process
    patch stream.
  - Refactored `useExecutionProcesses` so `ping`, `resume_gap`, event IDs,
    workspace `JsonPatch`, workspace `Events`, ready frames, finished frames,
    and malformed frames are handled through typed discriminated parser output
    before React state or the workbench store is mutated.
  - Reused the existing log-event type guard for workspace stream event rows.
  - Added node tests for global/workspace stream parser behavior and extended
    source-hygiene coverage so `useExecutionProcesses` cannot reintroduce
    direct `JSON.parse(...)` parsing.
  - Expanded the frontend stream-payload type-safety spec to include the
    global/workspace execution-process stream helper.
- Checks:
  - `cd frontend && node --import tsx --test tests/executionProcessesStreamFrames.test.ts tests/executionProcessStreamFrames.test.ts tests/executionProcessesTransport.test.ts tests/sourceHygiene.test.ts tests/executionProcessPatch.test.ts`
    - Result: `26` tests passed.
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm test`
    - Result: `352` tests passed.
  - `cd frontend && npm run format:check`
    - Result: passed.
  - `cd frontend && npm run build`
    - Result: passed; Next.js 15.5.20 production build completed successfully.
  - `git diff --check`
    - Result: passed before the spec/report append; rerun after this batch
      before the next implementation slice.

## 2026-07-07 Frontend Browser Storage JSON Guard Batch 70

- Frontend storage robustness cleanup:
  - Added `safeJsonRecord(...)`, `safeJsonStringArray(...)`, and
    `safeJsonNumberRecord(...)` alongside `safeJsonParse(...)` in
    `frontend/src/lib/utils.tsx`.
  - Replaced localStorage `JSON.parse(...)` reads for user preferences,
    workspace favorites, issue recent searches, and Workbench project MRU
    ordering with typed storage helpers and field-level narrowing.
  - Hardened the root inline boot script so corrupt preference JSON no longer
    prevents first-paint theme setup.
  - Added `frontend/tests/utils.test.ts` and extended source-hygiene tests for
    storage parsing helper usage.
  - Added the browser-storage JSON narrowing scenario to both canonical and
    mirror frontend type-safety specs.
- Checks:
  - `cd frontend && node --import tsx --test tests/utils.test.ts tests/sourceHygiene.test.ts tests/workspaceGridMotion.test.ts tests/issueNavigationCopy.test.ts tests/workbenchChromeMotion.test.ts`
    - Result: `22` tests passed.
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm test`
    - Result: `349` tests passed.
  - `cd frontend && npm run format:check`
    - Result: passed.
  - `cd frontend && npm run build`
    - Result: passed; Next.js 15.5.20 production build completed successfully.

## 2026-07-07 Frontend Execution Stream Frame Parser Batch 69

- Frontend realtime-stream type cleanup:
  - Added `frontend/src/hooks/executionProcessStreamFrames.ts`, a pure parser
    for execution-process WebSocket message/log frames.
  - Replaced direct `JSON.parse(...)` and broad casts in
    `useExecutionProcessMessageStream` and `useExecutionProcessLogStream` with
    discriminated frame parsing for finished frames, assistant deltas,
    heartbeats, log rows, task messages, control frames, unknown frames, and
    malformed message frames.
  - Added node tests for the new frame parser and source-hygiene coverage that
    prevents direct JSON parsing from returning to the execution-process stream
    hooks.
  - Expanded the frontend type-safety stream-payload spec to cover both
    prototype SSE payloads and execution-process WebSocket frames.
- Checks:
  - `cd frontend && node --import tsx --test tests/executionProcessStreamFrames.test.ts tests/messageStream.test.ts tests/sourceHygiene.test.ts tests/executionProcessesTransport.test.ts`
    - Result: `22` tests passed.
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm test`
    - Result: `344` tests passed.
  - `cd frontend && npm run format:check`
    - Result: passed.
  - `cd frontend && npm run build`
    - Result: passed; Next.js 15.5.20 production build completed successfully.
  - `git diff --check`
    - Result: passed before the spec/report append; rerun after this batch
      before the next implementation slice.

## 2026-07-07 Trusted Local Subprocess Boundary Batch 67

- Static security and process-boundary cleanup:
  - Added `backend/app/adapters/local_process.py` as the single helper for
    trusted one-shot local CLI calls, preserving argv execution with
    `shell=False` and centralizing the remaining Bandit subprocess
    suppressions at the I/O boundary.
  - Migrated scattered synchronous `subprocess.run(...)` callers in CLI
    adapters, runtime availability checks, git/status reads, project
    conductor follow-up, benchmark jobs, QA command execution, and the API
    `osascript` directory picker to `run_trusted_local(...)`.
  - Re-exported `CalledProcessError`, `CompletedProcess`, and `TimeoutExpired`
    from the boundary helper so callers do not need to import `subprocess`
    directly.
  - Added `app.adapters.local_process` to the strict mypy override list after
    `tests/test_mypy_strict_coverage.py` caught the new module as uncovered.
  - Updated backend quality specs with the executable trusted-local-subprocess
    boundary contract.
- Checks:
  - `cd backend && .venv/bin/python -m pytest -q tests/test_mypy_strict_coverage.py`
    - Result: `4 passed`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `261` source files.
  - `cd backend && .venv/bin/python -c "from app.main import app"`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1105 passed, 77 skipped, 166 deselected in 87.84s`.
  - `cd backend && pipx run bandit -r app benchmark -f json -q`
    - Result: empty `results` list; `0` high, `0` medium, `0` low findings.
      Bandit reports `11` skipped tests from documented suppressions and still
      prints existing "nosec encountered, but no failed test" warnings for
      legacy B608/B104 suppressions.
  - `git diff --check`
    - Result: passed.

## 2026-07-07 Backend Logging Contract Spec Batch 67

- Spec update:
  - Added `Backend App Logging Source Hygiene` to
    `.trellis/spec/vibe-kanban/backend/quality-guidelines.md`.
  - The scenario records the executable contract added in Batch 66:
    `backend/app` uses stdlib `logger` instead of real AST `print(...)`
    calls, cleanup / audit / event mirror failures log before being swallowed,
    and `tests/test_backend_source_hygiene.py` enforces the boundary without
    flagging generated hook script strings.
- Checks:
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_backend_source_hygiene.py tests/test_json_rpc_client.py tests/test_ci_quality_gates.py`
    - Result: `20 passed`.
  - `git diff --check`
    - Result: passed.

## 2026-07-07 Backend Silent-Cleanup Burn-Down Batch 68

- Static-analysis cleanup:
  - Replaced another broad set of best-effort `except/pass` cleanup paths with
    `logger.debug(..., exc_info=True)` across async store FTS syncing, Codex
    app-server timeout cleanup, Codex task runner bookkeeping/env rendering,
    conductor context/budget/tool cleanup, knowledge index JSON flattening,
    project memory stale block cleanup, review guard report reads, role workflow
    embedding/project-run side effects, specialist feed messages, tolerant JSON
    repair fallbacks, workflow scheduler events, app/bootstrap/main shutdown,
    transport WS handling, and benchmark cleanup.
  - Replaced the runtime catalog provider `assert` with an explicit
    `RuntimeCatalogValidationError`, so validation is not removed under
    optimized bytecode.
  - Bandit low findings dropped from `61` to `26`; the remaining low findings
    are all local subprocess execution/import/path warnings (`B603`, `B404`,
    `B607`) in expected CLI/runtime integration points.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/adapters/async_sqlite_store.py app/application/codex_app_server_runtime.py app/application/codex_task_runner.py app/application/conductor_main_loop.py app/application/conductor_tools.py app/application/knowledge_index_service.py app/application/project_memory_service.py app/application/review_guard.py app/application/role_workflow_service.py app/application/runtime_catalog_service.py app/application/specialist_orchestrator.py app/application/tolerant_json.py app/application/workflow_scheduler.py app/bootstrap.py app/interfaces/api.py app/interfaces/codex_ws.py app/main.py benchmark/job.py benchmark/store.py --show-error-codes --no-pretty`
    - Result: passed for `19` source files; single-file mypy emitted the
      existing unused-override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_backend_source_hygiene.py tests/test_json_rpc_client.py tests/test_event_bus_ws.py tests/test_audit_logger.py tests/test_codex_task_runner.py tests/test_conductor_main_loop.py tests/test_conductor_subagent_timeout.py tests/test_knowledge_index.py tests/test_project_conductor.py tests/test_runtime_catalog.py tests/test_specialist_orchestrator.py tests/test_workflow_scheduler_auto_retry.py tests/test_lifespan_shutdown.py tests/test_diagnostics_api.py tests/test_benchmark_runner.py`
    - Result: `176 passed`.
  - `cd backend && pipx run bandit -r app benchmark -f json -q` parsed summary
    - Result: `0` high, `0` medium, `26` low findings (`11` B603, `10` B404,
      `5` B607).
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `260` source files.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short`
    - Result: `1105 passed, 77 skipped, 166 deselected in 55.57s`.
  - `git diff --check`
    - Result: passed.

## 2026-07-07 Frontend Audit CI Gate Batch 57

- CI/security gate hardening:
  - Added `npm audit --registry=https://registry.npmjs.org` as a hard frontend
    CI step after `npm ci` and before typecheck/test/lint/build.
  - Updated README quality gates so local frontend checks now include the
    official-registry npm audit command.
  - Updated `backend/tests/test_ci_quality_gates.py` so CI, README, and the
    documented frontend gate list cannot drift.
  - Updated backend and frontend quality specs to treat frontend dependency
    audit as part of the six-command frontend quality gate.
- Checks:
  - `cd frontend && npm audit --registry=https://registry.npmjs.org`
    - Result: `found 0 vulnerabilities`.
  - `backend/.venv/bin/python -m pytest -q --tb=short --disable-warnings backend/tests/test_ci_quality_gates.py`
    - Result: `5 passed`.
  - `cd backend && .venv/bin/python -m ruff check tests/test_ci_quality_gates.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy tests/test_ci_quality_gates.py --show-error-codes --no-pretty`
    - Result: passed for `1` source file; single-file mypy emitted the
      existing unused-override-section note from `pyproject.toml`.
  - `cd frontend && node --import tsx --test tests/sourceHygiene.test.ts`
    - Result: `9` tests passed.
  - `git diff --check`
    - Result: passed.

## 2026-07-07 Backend Dependency Audit Baseline Batch 58

- Security baseline:
  - Ran a one-off Python dependency audit without adding audit tooling to the
    backend virtualenv or project requirements.
  - Command:
    `pipx run pip-audit -r backend/requirements.txt --format json`.
  - Result: `No known vulnerabilities found`.
  - The resolved audit set included current satisfiable versions for the
    backend stack such as `fastapi 0.139.0`, `pydantic 2.13.4`,
    `uvicorn 0.50.2`, `websockets 16.0`, `httpx 0.28.1`,
    `pypdf 6.14.2`, `python-multipart 0.0.32`, and `playwright 1.61.0`.
- Follow-up note:
  - This remains recorded evidence rather than a CI gate because the project
    does not yet have a documented Python audit-tool installation convention.
    If promoted later, add the toolchain setup, README command, CI step, and
    `test_ci_quality_gates.py` contract together.

## 2026-07-07 Frontend Dependency Boundary Regression Batch 59

- Executable contract hardening:
  - Added a source hygiene test that keeps known CLI/build/test-only frontend
    tools out of production `dependencies`.
  - The test checks `package.json` placement for `shadcn`, `tsx`, `prettier`,
    TypeScript/ESLint/Tailwind tooling, and `@next/swc-wasm-nodejs`.
  - The same test scans runtime source imports so a dev-only package cannot be
    imported by app code without failing the source hygiene gate.
- Checks:
  - `cd frontend && node --import tsx --test tests/sourceHygiene.test.ts`
    - Result: `10` tests passed.
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm test -- --runInBand`
    - Result: `334` tests passed.
  - `cd frontend && npm run build`
    - Result: passed; Next.js 15.5.20 compiled successfully and generated the
      app routes. Node emitted the same non-fatal `DEP0205` deprecation warning
      from the toolchain.
  - `cd frontend && npx prettier --check tests/sourceHygiene.test.ts`
    - Result: passed; all matched files use Prettier style.
  - `git diff --check`
    - Result: passed.

## 2026-07-07 Backend Bandit High-Severity Cleanup Batch 60

- Static security scan:
  - Ran one-off Bandit over `backend/app` and `backend/benchmark`.
  - Initial summary: `1` high, `20` medium, `73` low findings.
  - The only high finding was `B324` in
    `backend/app/application/team_notes_service.py`, where SHA-1 is used to
    derive deterministic legacy team-note block IDs from headings.
- Fix:
  - Marked the digest as non-security with
    `hashlib.sha1(..., usedforsecurity=False)` and updated the module
    docstring so the intent is explicit.
  - Kept the ID algorithm and prefix unchanged, preserving existing
    `h:<16-hex>` block IDs.
  - Added a backend quality spec scenario for non-security deterministic hashes
    so future weak-digest uses must document intent and pass targeted Bandit
    checks instead of creating high-severity scanner noise.
- Checks:
  - `pipx run bandit backend/app/application/team_notes_service.py -f json`
    - Result: `0` findings for the file.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_team_notes.py`
    - Result: `7 passed`.
  - `cd backend && .venv/bin/python -m ruff check app/application/team_notes_service.py tests/test_team_notes.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/application/team_notes_service.py tests/test_team_notes.py --show-error-codes --no-pretty`
    - Result: passed for `2` source files; single-file mypy emitted the
      existing unused-override-section note from `pyproject.toml`.
  - `pipx run bandit -r backend/app backend/benchmark -f json`
    - Result after fix: `0` high, `20` medium, `73` low findings. Remaining
      findings are recorded as review backlog rather than blindly suppressed.
  - `git diff --check`
    - Result: passed.

## 2026-07-07 Backend Tempdir Static-Scan Cleanup Batch 61

- Static security cleanup:
  - Replaced hard-coded `/tmp` runtime defaults with `tempfile.gettempdir()`
    through `timeouts.DEFAULT_CODEX_DATA_DIR`.
  - Updated `CodexProcessManager`, the shared async process runtime, and the
    bootstrap mock process manager to use that single default instead of local
    string fallbacks.
  - Updated timeout tests to assert against the default constant rather than a
    platform-specific `/tmp` literal.
- Checks:
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_timeouts.py tests/test_codex_task_runner.py tests/test_async_refresh_task_result.py`
    - Result: `43 passed`.
  - `cd backend && .venv/bin/python -m ruff check app/application/timeouts.py app/application/codex_process_manager.py app/application/process_runtime_common.py app/bootstrap.py tests/test_timeouts.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/application/timeouts.py app/application/codex_process_manager.py app/application/process_runtime_common.py app/bootstrap.py tests/test_timeouts.py --show-error-codes --no-pretty`
    - Result: passed for `5` source files; single-file mypy emitted the
      existing unused-override-section note from `pyproject.toml`.
  - `pipx run bandit backend/app/application/timeouts.py backend/app/application/codex_process_manager.py backend/app/application/process_runtime_common.py backend/app/bootstrap.py -f json`
    - Result: `0` medium findings for the touched files; remaining findings in
      those files are low-severity subprocess/cleanup-path warnings.
  - `pipx run bandit -r backend/app backend/benchmark -f json`
    - Result after tempdir cleanup: `0` high, `16` medium, `73` low findings.
      Medium findings dropped from `20` to `16`.

## 2026-07-07 Backend SQLite Identifier Boundary Batch 62

- Static security cleanup:
  - Added strict sqlite identifier validation/quoting helpers to both sync and
    async stores.
  - Updated store `reset()` to validate table names read from `sqlite_master`
    before building `DELETE FROM "<table>"`.
  - Kept a targeted `# nosec B608` only on the validated execute line, with the
    validation comment immediately above it.
  - Added a backend quality spec scenario for dynamic SQL identifier
    boundaries: values use parameters, identifiers are allowlisted or
    validated/quoted, and B608 suppressions require nearby validation.
- Checks:
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_self_improvement_store.py tests/test_audit_log_api.py tests/test_audit_logger.py`
    - Result: `40 passed`.
  - `cd backend && .venv/bin/python -m ruff check app/adapters/async_sqlite_store.py app/adapters/sqlite_store.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/adapters/async_sqlite_store.py app/adapters/sqlite_store.py --show-error-codes --no-pretty`
    - Result: passed for `2` source files; single-file mypy emitted the
      existing unused-override-section note from `pyproject.toml`.
  - `pipx run bandit backend/app/adapters/async_sqlite_store.py backend/app/adapters/sqlite_store.py -f json`
    - Result: reset-table B608 findings are skipped after identifier
      validation; remaining store findings are unrelated log-order/where-clause
      B608 items plus existing low cleanup warnings.
  - `pipx run bandit -r backend/app backend/benchmark -f json`
    - Result after identifier cleanup: `0` high, `14` medium, `73` low
      findings. Medium findings dropped from `16` to `14`.

## 2026-07-07 Backend Log Query Static-Scan Cleanup Batch 63

- Static security cleanup:
  - Replaced dynamic `ORDER BY created_at {order}` log-event SQL strings in
    sync and async stores with explicit literal SQL branches selected from the
    `reverse` boolean.
  - Added `_log_events_query(...)` helpers so the query shape is centralized
    and does not interpolate SQL keywords.
- Checks:
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_audit_log_api.py tests/test_audit_logger.py tests/test_async_refresh_task_result.py tests/test_message_streaming.py`
    - Result: `58 passed`.
  - `cd backend && .venv/bin/python -m ruff check app/adapters/async_sqlite_store.py app/adapters/sqlite_store.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/adapters/async_sqlite_store.py app/adapters/sqlite_store.py --show-error-codes --no-pretty`
    - Result: passed for `2` source files; single-file mypy emitted the
      existing unused-override-section note from `pyproject.toml`.
  - `pipx run bandit backend/app/adapters/async_sqlite_store.py backend/app/adapters/sqlite_store.py -f json`
    - Result: store medium findings dropped from `13` to `5`.
  - `pipx run bandit -r backend/app backend/benchmark -f json`
    - Result after log-query cleanup: `0` high, `6` medium, `73` low findings.
      Medium findings dropped from `14` to `6`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `258` source files.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short`
    - Result: `1090 passed, 77 skipped, 166 deselected in 53.00s`.
  - `git diff --check`
    - Result: passed.

## 2026-07-07 Backend Bandit Medium Triage Batch 64

- Static security cleanup:
  - Triaged the remaining Bandit medium findings.
  - Added precise, explained `# nosec` annotations only where the dynamic SQL
    fragment is built from fixed internal predicates/columns while user values
    remain parameterized.
  - Added a precise B104 annotation for local URL text normalization; the code
    replaces `0.0.0.0` in command output with `127.0.0.1` and does not bind a
    server socket.
- Checks:
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_self_improvement_store.py tests/test_project_script_suggestions.py`
    - Result: `17 passed`.
  - `cd backend && .venv/bin/python -m ruff check app/adapters/async_sqlite_store.py app/adapters/sqlite_store.py app/application/project_script_suggestions.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/adapters/async_sqlite_store.py app/adapters/sqlite_store.py app/application/project_script_suggestions.py --show-error-codes --no-pretty`
    - Result: passed for `3` source files; single-file mypy emitted the
      existing unused-override-section note from `pyproject.toml`.
  - `pipx run bandit -r backend/app backend/benchmark -f json`
    - Result after triage: `0` high, `0` medium, `73` low findings.
      Medium findings dropped from `6` to `0`; skipped tests increased to `8`
      due to the documented targeted suppressions.
  - `git diff --check`
    - Result: passed.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `258` source files.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short`
    - Result: `1090 passed, 77 skipped, 166 deselected in 58.23s`.
  - `git diff --check`
    - Result: passed.

## 2026-07-07 JSON-RPC Protocol Boundary Refactor Batch 65

- Backend protocol refactor:
  - Centralized JSON-RPC request payload, response payload, message parsing,
    and server-request mapping in `backend/app/application/json_rpc_client.py`.
  - Routed both sync `JsonRpcPeer` and async `AsyncJsonRpcPeer` through the
    same parser/serializer helpers so invalid response/error frames and
    approval requests are handled consistently.
  - Preserved the existing external Codex app-server protocol while making the
    async peer honor the same notification stop contract as the sync peer.
  - Added `backend/tests/test_json_rpc_client.py` covering parse parity,
    approval request mapping, sync/async payload serialization, and async
    notification shutdown behavior.
- Checks:
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_json_rpc_client.py`
    - Result: `14 passed`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_agent_process_environment.py tests/test_message_streaming.py tests/test_codex_task_runner.py`
    - Result: `15 passed`.
  - `cd backend && .venv/bin/python -m ruff check app/application/json_rpc_client.py tests/test_json_rpc_client.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/application/json_rpc_client.py tests/test_json_rpc_client.py --show-error-codes --no-pretty`
    - Result: passed for `2` source files; single-file mypy emitted the
      existing unused-override-section note from `pyproject.toml`.
  - `cd backend && pipx run bandit app/application/json_rpc_client.py -f json`
    - Result: `0` findings.

## 2026-07-07 Backend Logging Hygiene Batch 66

- Source hygiene and observability cleanup:
  - Replaced runtime `print(...)` calls in JSON-RPC, EventBus, audit writer /
    recorders, process runtime help logging, architect auto-repair, and the
    prototype service manual smoke block with stdlib `logger` calls.
  - Added debug logging for best-effort cleanup / audit recorder exceptions
    instead of silent `except/pass`, preserving non-blocking cleanup semantics
    while making failures discoverable when `DEBUG` is enabled.
  - Added `backend/tests/test_backend_source_hygiene.py`, an AST-based
    regression test that rejects real `print(...)` calls under `backend/app`
    without flagging generated hook script strings.
- Checks:
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_backend_source_hygiene.py tests/test_json_rpc_client.py tests/test_event_bus_ws.py tests/test_audit_logger.py tests/test_agent_process_environment.py tests/test_message_streaming.py tests/test_codex_task_runner.py tests/test_architect_workflow.py tests/test_prototypes_api.py`
    - Result: `85 passed`.
  - `cd backend && .venv/bin/python -m ruff check app/application/event_bus.py app/application/process_runtime_common.py app/application/audit/writer.py app/application/audit/recorders.py app/application/architect_workflow.py app/application/prototype_service.py app/application/json_rpc_client.py tests/test_backend_source_hygiene.py tests/test_json_rpc_client.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/application/event_bus.py app/application/process_runtime_common.py app/application/audit/writer.py app/application/audit/recorders.py app/application/architect_workflow.py app/application/prototype_service.py app/application/json_rpc_client.py tests/test_backend_source_hygiene.py tests/test_json_rpc_client.py --show-error-codes --no-pretty`
    - Result: passed for `9` source files; single-file mypy emitted the
      existing unused-override-section note from `pyproject.toml`.
  - `cd backend && pipx run bandit app/application/event_bus.py app/application/process_runtime_common.py app/application/audit/writer.py app/application/audit/recorders.py app/application/architect_workflow.py app/application/prototype_service.py app/application/json_rpc_client.py -f json`
    - Result: `0` high, `0` medium, `1` low finding. The remaining low is
      `B404` for the process runtime's intentional `subprocess` import.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `260` source files.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short`
    - Result: `1105 passed, 77 skipped, 166 deselected in 56.00s`.
  - `cd backend && pipx run bandit -r app benchmark -f json`
    - Result: `0` high, `0` medium, `61` low findings. Remaining low findings
      are subprocess / cleanup / assert-use backlog items; skipped tests remain
      `8` from the targeted suppressions added in earlier batches.
  - `git diff --check`
    - Result: passed.

## 2026-07-07 Frontend Object Payload Guard Sweep Batch 81

- Frontend runtime type-safety cleanup:
  - Replaced remaining broad runtime object assertions in frontend runtime
    boundaries with `isRecord(...)`, `safeJsonRecord(...)`, or feature-local
    guards.
  - Covered audit payload summaries, task/run assistant message extraction,
    Agent Dock tool-use scanning, skill import parsing, conductor log stream
    event guards, workspace bus event readers, prototype/project SSE event-data
    helpers, API error-detail parsing, and task conversation log merging.
  - Added `frontend/tests/sourceHygiene.test.ts` coverage that rejects broad
    object assertions such as `as Record<string, unknown>`,
    `as { data?: unknown }`, `as { detail?: unknown }`, and hidden-entry shape
    assertions in runtime source.
  - Updated ccgui/vibe-kanban frontend type-safety specs so future runtime
    payload work narrows object data with guards before indexing.
- Checks:
  - `cd frontend && node --import tsx --test tests/sourceHygiene.test.ts tests/codexLogNormalizer.test.ts tests/taskConversationDetailUtils.test.ts tests/apiFetchHelpers.test.ts tests/projectConductorStreamEvents.test.ts tests/prototypeStreamEvents.test.ts tests/tasksRunsTabMotion.test.ts tests/auditLogMotion.test.ts tests/agentDockMotion.test.ts tests/skillsLibraryMotion.test.ts tests/conductorLogPanelStreaming.test.ts tests/workspaceConsoleRedesign.test.ts`
    - Result: `72 passed`.
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm test`
    - Result: `371 passed`.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm run format:check`
    - Result: passed.
  - `cd frontend && npm run build`
    - Result: passed. Existing warnings remain: npm `allowBuilds` config and
      Node `[DEP0205] module.register()` during Next build.

## 2026-07-07 Backend Shared JSON Safety Refactor Batch 86

- Backend JSON boundary cleanup:
  - Added `backend/app/json_safety.py` as the shared low-level guard module for
    JSON object/list/string coercion and safe JSON text parsing.
  - Migrated repeated `_object_dict` / `_object_mapping` / JSON object guard
    logic across adapters, JSON-RPC, Codex app-server runtime, process runtime,
    worktree Claude hooks, project conductor/memory, self-improvement apply,
    and API serialization helpers.
  - Kept sqlite store `_json_object(...)` wrappers where malformed persisted DB
    JSON should still raise, but moved the shape coercion inside those wrappers
    to the shared helper.
  - Added `backend/tests/test_json_safety.py` and source-hygiene coverage that
    rejects reintroducing local `_object_dict`, `_object_mapping`, or
    `object_dict` helpers under `backend/app`.
  - Updated backend quality guidelines with the `app.json_safety` contract,
    helper signatures, validation matrix, and required tests.
- Checks:
  - `cd backend && .venv/bin/python -m pytest -q tests/test_json_safety.py tests/test_backend_source_hygiene.py tests/test_json_rpc_client.py tests/test_agent_process_environment.py tests/test_reader_loop_finalize.py`
    - Result: `29 passed`.
  - `cd backend && .venv/bin/python -m pytest -q tests/test_json_safety.py tests/test_backend_source_hygiene.py tests/test_json_rpc_client.py tests/test_agent_process_environment.py tests/test_reader_loop_finalize.py tests/test_project_conductor.py tests/test_worktree_claude_hooks.py tests/test_llm_runner_streaming.py tests/test_process_runtime_help_completion.py`
    - Result: `52 passed`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `263` source files.
  - `cd backend && .venv/bin/python -c "from app.main import app"`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q tests/test_backend_source_hygiene.py tests/test_json_safety.py tests/test_json_rpc_client.py tests/test_projects_api.py tests/test_task_chat_endpoint.py tests/test_self_improvement_api.py`
    - Result: `124 passed, 1 warning in 27.17s`; warning was an existing
      aiosqlite worker-thread `Event loop is closed` warning in
      `test_task_chat_endpoint.py`.
  - `cd backend && .venv/bin/python -m pytest -q tests/test_mypy_strict_coverage.py tests/test_backend_source_hygiene.py tests/test_json_safety.py`
    - Result: `14 passed`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1114 passed, 77 skipped, 166 deselected in 51.16s`.

## 2026-07-07 LLM Runner Streaming JSON Guard Batch 87

- Backend LLM boundary cleanup:
  - Replaced raw `json.loads(raw)` + unchecked `.get(...)` parsing in
    `backend/app/application/llm_runner.py` streaming paths with
    `parse_json_object(...)`, `object_dict(...)`, `string_value(...)`, and a
    small `_int_value(...)` guard for external SSE indexes.
  - Hardened Anthropic SSE text deltas, Anthropic tool-use streaming, OpenAI
    chat completion responses, OpenAI streaming deltas, and tool argument JSON
    so malformed/non-object events degrade to skip or `{}` instead of relying
    on `Any`.
  - Added regression coverage that noisy SSE events (`[]`, malformed JSON, and
    non-object deltas) are ignored while later valid text still streams.
- Checks:
  - `cd backend && .venv/bin/python -m ruff check app/application/llm_runner.py tests/test_llm_runner_streaming.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/application/llm_runner.py tests/test_llm_runner_streaming.py tests/test_conductor_openai_adapter.py --show-error-codes --no-pretty`
    - Result: passed for `3` source files; emitted the existing unused
      override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -m pytest -q tests/test_llm_runner_streaming.py tests/test_conductor_openai_adapter.py`
    - Result: `10 passed`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `263` source files.
  - `cd backend && .venv/bin/python -m pytest -q tests/test_llm_runner_streaming.py tests/test_conductor_openai_adapter.py tests/test_json_safety.py tests/test_backend_source_hygiene.py`
    - Result: `20 passed`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1115 passed, 77 skipped, 166 deselected in 48.44s`.

## 2026-07-07 Prototype SSE JSON Guard Batch 88

- Backend prototype streaming cleanup:
  - Replaced raw `json.loads(raw)` parsing in
    `backend/app/application/prototype_service.py` with
    `parse_json_object(...)`, `object_dict(...)`, and `string_value(...)` for
    prototype HTML SSE events.
  - Updated `backend/app/interfaces/sse.py` runtime evidence query parsing to
    accept only JSON object payloads before constructing
    `RuntimePrototypeEvidence`.
  - Added regression coverage for noisy prototype SSE events (`[]`, malformed
    JSON, and non-object deltas) and non-object runtime-evidence query values.
- Checks:
  - `cd backend && .venv/bin/python -m ruff check app/application/prototype_service.py app/interfaces/sse.py tests/test_prototype_service.py tests/test_prototypes_api.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/application/prototype_service.py app/interfaces/sse.py tests/test_prototype_service.py tests/test_prototypes_api.py --show-error-codes --no-pretty`
    - Result: passed for `4` source files; emitted the existing unused
      override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -m pytest -q tests/test_prototype_service.py tests/test_prototypes_api.py`
    - Result: `61 passed`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `263` source files.
  - `cd backend && .venv/bin/python -m pytest -q tests/test_json_safety.py tests/test_llm_runner_streaming.py tests/test_prototype_service.py tests/test_prototypes_api.py`
    - Result: `69 passed`.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1117 passed, 77 skipped, 166 deselected in 48.09s`.

## 2026-07-07 Frontend Fetch Header Fixture Guard Batch 89

- Frontend test type-safety cleanup:
  - Replaced test-only `as Record<string, string>` header assertions in
    `frontend/tests/agentMeshApi.test.ts` and
    `frontend/tests/projectConductorApi.test.ts` with a small `contentType(...)`
    helper that reads `RequestInit.headers` through the standard `Headers`
    interface.
  - Left production `safeJsonParse(...)` returning `unknown` unchanged because
    that is the shared runtime JSON helper contract documented in the frontend
    type-safety spec.
- Checks:
  - `cd frontend && node --import tsx --test tests/agentMeshApi.test.ts tests/projectConductorApi.test.ts tests/sourceHygiene.test.ts`
    - Result: `31 passed`.
  - `cd frontend && npm run typecheck`
    - Result: passed. Existing npm warning remains: unknown user config
      `allowBuilds`.
  - `cd frontend && npm test`
    - Result: `373 passed`.
  - `cd frontend && npm run lint`
    - Result: passed. Existing npm `allowBuilds` warning remains.
  - `cd frontend && npm run format:check`
    - Result: passed. Existing npm `allowBuilds` warning remains.
  - `cd frontend && npm run build`
    - Result: passed. Existing npm `allowBuilds` warning remains.

## 2026-07-07 Backend Script/GitHub JSON Shape Guard Batch 90

- Backend JSON boundary cleanup:
  - Updated `backend/app/application/github_pr_followup.py` so `gh pr view`
    still distinguishes malformed non-JSON from JSON of the wrong shape, while
    using `object_dict_or_none(...)` for the object guard.
  - Updated `backend/app/application/project_script_suggestions.py` to parse
    `package.json`, AI script suggestions, and package script maps through
    `parse_json_object(...)` / `object_dict(...)`.
  - Hardened script-context collection so malformed `scripts`,
    `dependencies`, or `devDependencies` fields degrade to `{}` / `[]` instead
    of calling `.keys()` on a non-object.
  - Added regression coverage for non-object package metadata fields.
- Checks:
  - `cd backend && .venv/bin/python -m ruff check app/application/github_pr_followup.py app/application/project_script_suggestions.py tests/test_github_pr_followup.py tests/test_project_script_suggestions.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/application/github_pr_followup.py app/application/project_script_suggestions.py tests/test_github_pr_followup.py tests/test_project_script_suggestions.py --show-error-codes --no-pretty`
    - Result: passed for `4` source files; emitted the existing unused
      override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -m pytest -q tests/test_github_pr_followup.py tests/test_project_script_suggestions.py`
    - Result: `27 passed`.
  - `cd backend && .venv/bin/python -m ruff check . && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed; mypy checked `263` source files.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1118 passed, 77 skipped, 166 deselected in 51.65s`.

## 2026-07-07 Backend Streaming JSON Source-Hygiene Batch 91

- Backend source-hygiene hardening:
  - Added `backend/tests/test_backend_source_hygiene.py` coverage that rejects
    direct `json.loads(...)` calls in LLM/prototype streaming boundary modules:
    `app/application/llm_runner.py`, `app/application/prototype_service.py`,
    and `app/interfaces/sse.py`.
  - Updated backend quality guidelines so future SSE/streaming parsers use
    `parse_json_object(...)` from `app.json_safety` instead of local raw JSON
    parsing.
- Checks:
  - `cd backend && .venv/bin/python -m pytest -q tests/test_backend_source_hygiene.py tests/test_llm_runner_streaming.py tests/test_prototype_service.py tests/test_prototypes_api.py`
    - Result: `70 passed`.
  - `cd backend && .venv/bin/python -m ruff check tests/test_backend_source_hygiene.py app/application/llm_runner.py app/application/prototype_service.py app/interfaces/sse.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy tests/test_backend_source_hygiene.py app/application/llm_runner.py app/application/prototype_service.py app/interfaces/sse.py --show-error-codes --no-pretty`
    - Result: passed for `4` source files; emitted the existing unused
      override-section note from `pyproject.toml`.

## 2026-07-07 Phase Duration Estimator Capability Typing Batch 92

- Backend typing cleanup:
  - Replaced `Any` in `backend/app/application/phase_duration_estimator.py`
    with a runtime-checkable `PhaseDurationStore` Protocol that documents the
    only store capability the estimator needs:
    `list_conductor_state_logs(...)`.
  - Preserved the previous optional-capability fallback: stores without that
    method still return empty estimates instead of raising.
- Checks:
  - `cd backend && .venv/bin/python -m ruff check app/application/phase_duration_estimator.py tests/test_conductor_state_machine.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/application/phase_duration_estimator.py tests/test_conductor_state_machine.py --show-error-codes --no-pretty`
    - Result: passed for `2` source files; emitted the existing unused
      override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -m pytest -q tests/test_conductor_state_machine.py tests/test_pipeline_stages.py`
    - Result: `17 passed`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `263` source files.

## 2026-07-07 Codex Log Normalizer Primitive Guard Sweep Batch 82

- Frontend log-boundary cleanup:
  - Added small `stringValue(...)`, `optionalString(...)`,
    `nullableString(...)`, and `firstString(...)` readers inside
    `frontend/src/lib/codexLogNormalizer.ts`.
  - Replaced all primitive `as string` / `as string | undefined` /
    `as unknown[]` assertions in the Codex/Claude log normalizer with explicit
    field readers and array guards.
  - Extended the codex log normalizer source-hygiene test so future runtime log
    parsing cannot reintroduce primitive assertions while parsing untrusted log
    payloads.
- Checks:
  - `cd frontend && node --import tsx --test tests/sourceHygiene.test.ts tests/codexLogNormalizer.test.ts tests/taskConversationDetailUtils.test.ts`
    - Result: `33 passed`.
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm run format:check`
    - Result: passed.
  - `cd frontend && npm test`
    - Result: `371 passed`.
  - `cd frontend && npm run build`
    - Result: passed. Existing warnings remain: npm `allowBuilds` config and
      Node `[DEP0205] module.register()` during Next build.

## 2026-07-07 Backend Logger Lazy Formatting Hygiene Batch 85

- Backend logging cleanup:
  - Replaced remaining `logger.*(f"...")` calls under `backend/app` with stdlib
    lazy formatting (`%s` placeholders plus arguments).
  - Added `backend/tests/test_backend_source_hygiene.py` coverage that rejects
    f-string logger calls in app runtime source.
  - Updated backend logging guidelines to document the no-f-string logger
    contract and its source-hygiene test.
- Checks:
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings tests/test_backend_source_hygiene.py tests/test_projects_api.py tests/test_task_chat_endpoint.py`
    - Result: `48 passed`.
  - `cd backend && .venv/bin/python -m ruff check app/interfaces/api.py tests/test_backend_source_hygiene.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/interfaces/api.py tests/test_backend_source_hygiene.py --show-error-codes --no-pretty`
    - Result: passed for `2` source files; emitted the existing unused
      override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `261` source files.
  - `cd backend && .venv/bin/python -c "from app.main import app"`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1108 passed, 77 skipped, 166 deselected in 53.80s`.

## 2026-07-07 Tool Blocks Runtime Args Guard Sweep Batch 83

- Frontend tool-rendering cleanup:
  - Added a local `pickArgString(...)` reader in
    `frontend/src/features/runs/toolBlocks/ToolBlocks.tsx`.
  - Replaced direct `args[...] as string` reads in edit/search/todo tool blocks
    with guarded string extraction, preserving untrimmed code/diff text.
  - Added `frontend/tests/toolBlocksMotion.test.ts` coverage that rejects
    primitive string assertions in the tool-block runtime arg renderer.
- Checks:
  - `cd frontend && node --import tsx --test tests/toolBlocksMotion.test.ts tests/sourceHygiene.test.ts`
    - Result: `24 passed`.
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm run format:check`
    - Result: passed.
  - `cd frontend && npm test`
    - Result: `372 passed`.
  - `cd frontend && npm run build`
    - Result: passed. Existing warnings remain: npm `allowBuilds` config and
      Node `[DEP0205] module.register()` during Next build.

## 2026-07-07 Runtime Primitive Payload Guard Sweep Batch 84

- Frontend runtime payload cleanup:
  - Removed the remaining primitive assertions from audit payload summaries,
    benchmark frontier point mapping, and conductor turn delta streaming.
  - Added source-hygiene coverage for audit, benchmark, decision-timeline, and
    tool-block runtime payload surfaces so they narrow primitive fields before
    reading them.
  - Left the remaining primitive assertions limited to UI-library drag ids and
    an empty-array type helper, which are not runtime payload parsing
    boundaries.
- Checks:
  - `cd frontend && node --import tsx --test tests/sourceHygiene.test.ts tests/auditLogMotion.test.ts tests/benchmarksHelpers.test.ts tests/issueCommandCenter.test.ts tests/toolBlocksMotion.test.ts`
    - Result: `68 passed`.
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm run format:check`
    - Result: passed.
  - `cd frontend && npm test`
    - Result: `373 passed`.
  - `cd frontend && npm run build`
    - Result: passed. Existing warnings remain: npm `allowBuilds` config and
      Node `[DEP0205] module.register()` during Next build.

## 2026-07-07 Conductor Policy JSON Guard Batch 93

- Backend policy-boundary cleanup:
  - Replaced the remaining `dict[str, Any]` payload shapes in
    `backend/app/application/conductor_policy.py` with `JsonObject` from
    `app.json_safety`.
  - Changed conductor turn payload parsing to use `parse_json_object(...)`,
    preserving safe fallback behavior for malformed or non-object turn JSON.
  - Added regression coverage for malformed and non-object tool-result turns so
    policy selection falls back to `default_call_llm` instead of crashing.
- Checks:
  - `cd backend && .venv/bin/python -m pytest tests/test_conductor_policy.py -q`
    - Result: `14 passed`.
  - `cd backend && .venv/bin/python -m ruff check app/application/conductor_policy.py tests/test_conductor_policy.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/application/conductor_policy.py tests/test_conductor_policy.py --show-error-codes --no-pretty`
    - Result: passed for `2` source files; emitted the existing unused
      override-section note from `pyproject.toml`.

## 2026-07-07 Agent Catalog Shape Guard Batch 94

- Backend catalog cleanup:
  - Replaced `Any` in `backend/app/application/agent_catalog/catalog.py` with
    `JsonObject` for specialist output schemas and custom-agent schemas.
  - Added explicit required-string and positive-int readers for local specialist
    catalog files so malformed required fields fail with a clear `ValueError`,
    while optional schema/retry fields fall back safely.
  - Added regression coverage for missing required fields, non-object
    `output_schema`, and invalid `default_max_retries`.
- Checks:
  - `cd backend && .venv/bin/python -m pytest tests/test_agent_catalog.py -q`
    - Result: `10 passed`.
  - `cd backend && .venv/bin/python -m ruff check app/application/agent_catalog/catalog.py tests/test_agent_catalog.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/application/agent_catalog tests/test_agent_catalog.py --show-error-codes --no-pretty`
    - Result: passed for `4` source files; emitted the existing unused
      override-section note from `pyproject.toml`.

## 2026-07-07 Review Guard Expected Files JSON Batch 95

- Backend review-guard cleanup:
  - Replaced raw implementation-plan `json.loads(...)` in
    `backend/app/application/review_guard.py` with `parse_json_object_list(...)`.
  - Preserved tolerant behavior for missing, malformed, non-list, or legacy plan
    files: expected files degrade to `[]`, hard diff-vs-claim checks still run,
    and soft plan-drift checks are skipped.
  - Added regression coverage for malformed and non-list plan payloads.
- Checks:
  - `cd backend && .venv/bin/python -m pytest tests/test_review_guard.py -q`
    - Result: `13 passed`.
  - `cd backend && .venv/bin/python -m ruff check app/application/review_guard.py tests/test_review_guard.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/application/review_guard.py tests/test_review_guard.py --show-error-codes --no-pretty`
    - Result: passed for `2` source files; emitted the existing unused
      override-section note from `pyproject.toml`.

## 2026-07-07 Knowledge Index JSON Value Guard Batch 96

- Backend JSON helper and index cleanup:
  - Added `parse_json_value(raw, *, default=...)` to `backend/app/json_safety.py`
    for tolerant boundaries that accept any valid JSON shape and need a sentinel
    to distinguish malformed text from valid JSON `null`.
  - Updated `backend/app/application/knowledge_index_service.py` to use the new
    helper when flattening `.json` artifacts for FTS indexing, preserving array,
    object, scalar, and null flattening behavior.
  - Updated backend quality guidelines to document the new helper.
  - Added regression coverage for JSON scalar/default behavior and searchable
    JSON array artifacts.
- Checks:
  - `cd backend && .venv/bin/python -m pytest tests/test_json_safety.py tests/test_knowledge_index.py -q`
    - Result: `18 passed`.
  - `cd backend && .venv/bin/python -m ruff check app/json_safety.py app/application/knowledge_index_service.py tests/test_json_safety.py tests/test_knowledge_index.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/json_safety.py app/application/knowledge_index_service.py tests/test_json_safety.py tests/test_knowledge_index.py --show-error-codes --no-pretty`
    - Result: passed for `4` source files; emitted the existing unused
      override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -m pytest tests/test_backend_source_hygiene.py -q`
    - Result: `6 passed`.

## 2026-07-07 Stall Watchdog Capability Typing Batch 97

- Backend watchdog typing cleanup:
  - Replaced broad `Any` dependencies in `backend/app/application/stall_watchdog.py`
    with focused capability Protocols for the task store, process manager,
    refresh callback, and run-with-user-content callback.
  - Kept the watchdog compatible with both dict-shaped task rows and
    `CodexTask` objects by narrowing mappings through `Mapping[str, object]`.
  - Aligned the nudge callback Protocol with the real API helper's
    `Literal["chat", "refine"]` run-kind contract.
- Checks:
  - `cd backend && .venv/bin/python -m pytest tests/test_stall_watchdog_recovery.py tests/test_lifespan_shutdown.py -q`
    - Result: `6 passed`.
  - `cd backend && .venv/bin/python -m ruff check app/application/stall_watchdog.py tests/test_stall_watchdog_recovery.py tests/test_lifespan_shutdown.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/application/stall_watchdog.py tests/test_stall_watchdog_recovery.py tests/test_lifespan_shutdown.py --show-error-codes --no-pretty`
    - Result: passed for `3` source files; emitted the existing unused
      override-section note from `pyproject.toml`.

## 2026-07-07 Backend Full Gate After JSON/Typing Sweep Batch 98

- Scope:
  - Validated the backend after Batches 93-97, covering conductor policy JSON
    guards, agent catalog shape guards, review guard plan parsing, knowledge
    index JSON-value parsing, and stall watchdog capability typing.
- Checks:
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `263` source files.
  - `cd backend && .venv/bin/python -c "from app.main import app"`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1127 passed, 77 skipped, 166 deselected, 1 warning in 53.84s`.

## 2026-07-07 Conductor Recovery Payload Typing Batch 99

- Backend recovery typing cleanup:
  - Updated `backend/app/application/conductor_recovery.py` so stalled recovery
    result payloads use shared `JsonObject` instead of `dict[str, Any]`.
  - Narrowed the relaunched-loop done callback from `asyncio.Future[Any]` to
    `asyncio.Future[object]`, preserving behavior while avoiding an unnecessary
    `Any` escape hatch.
- Checks:
  - `cd backend && .venv/bin/python -m pytest tests/test_conductor_recovery.py -q`
    - Result: `7 passed`.
  - `cd backend && .venv/bin/python -m ruff check app/application/conductor_recovery.py tests/test_conductor_recovery.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/application/conductor_recovery.py tests/test_conductor_recovery.py --show-error-codes --no-pretty`
    - Result: passed for `2` source files; emitted the existing unused
      override-section note from `pyproject.toml`.

## 2026-07-07 Safe-Read JSON Source Hygiene Batch 100

- Backend source-hygiene hardening:
  - Added `backend/tests/test_backend_source_hygiene.py` coverage that rejects
    direct `json.loads(...)` in tolerant safe-read JSON boundaries:
    `conductor_policy.py`, `review_guard.py`, and `knowledge_index_service.py`.
  - Updated backend quality guidelines so future changes know these boundaries
    must keep using shared `parse_json_*` helpers.
  - Left strict config/LLM-output parsers such as `agent_catalog.py` and
    `product_manager_service.py` out of this rule because they intentionally
    preserve malformed-JSON error details.
- Checks:
  - `cd backend && .venv/bin/python -m pytest tests/test_backend_source_hygiene.py tests/test_json_safety.py tests/test_conductor_policy.py tests/test_review_guard.py tests/test_knowledge_index.py -q`
    - Result: `52 passed`.
  - `cd backend && .venv/bin/python -m ruff check tests/test_backend_source_hygiene.py app/application/conductor_policy.py app/application/review_guard.py app/application/knowledge_index_service.py app/json_safety.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy tests/test_backend_source_hygiene.py app/application/conductor_policy.py app/application/review_guard.py app/application/knowledge_index_service.py app/json_safety.py --show-error-codes --no-pretty`
    - Result: passed for `5` source files; emitted the existing unused
      override-section note from `pyproject.toml`.

## 2026-07-07 Task Completion Registry Result Typing Batch 101

- Backend registry typing cleanup:
  - Replaced `Any` result storage in
    `backend/app/application/task_completion_registry.py` with `object` and
    explicit `object | None` wait results.
  - Updated `backend/app/application/conductor_tools.py` to narrow completion
    registry results through `object_dict(...)` before returning a tool payload.
  - Updated the task-dispatcher start-failure regression to assert the registry
    result is a dict before indexing it.
- Checks:
  - `cd backend && .venv/bin/python -m pytest tests/test_task_completion_registry.py tests/test_task_dispatcher_start_failure.py tests/test_conductor_dispatch_batch.py tests/test_conductor_subagent_timeout.py -q`
    - Result: `25 passed`.
  - `cd backend && .venv/bin/python -m ruff check app/application/task_completion_registry.py app/application/conductor_tools.py tests/test_task_completion_registry.py tests/test_task_dispatcher_start_failure.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/application/task_completion_registry.py app/application/conductor_tools.py tests/test_task_completion_registry.py tests/test_task_dispatcher_start_failure.py --show-error-codes --no-pretty`
    - Result: passed for `4` source files; emitted the existing unused
      override-section note from `pyproject.toml`.

## 2026-07-07 Task Completion Registry Full Mypy Follow-up Batch 102

- Backend test typing follow-up:
  - Added explicit dict assertions before indexing task-completion registry
    results in workflow scheduler auto-retry and artifact-validation signal
    tests.
  - This preserves the stronger `object | None` registry API while keeping
    tests as executable shape documentation at the call sites.
- Checks:
  - `cd backend && .venv/bin/python -m pytest tests/test_workflow_scheduler_auto_retry.py tests/test_artifact_validation_signal.py tests/test_task_completion_registry.py -q`
    - Result: `25 passed`.
  - `cd backend && .venv/bin/python -m ruff check tests/test_workflow_scheduler_auto_retry.py tests/test_artifact_validation_signal.py app/application/task_completion_registry.py app/application/conductor_tools.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `263` source files.

## 2026-07-07 Conductor Session Coroutine Typing Batch 103

- Backend session-registry typing cleanup:
  - Removed `Any` from `backend/app/application/conductor_session_registry.py`
    by typing conductor loop factories as `Coroutine[object, object, object]`.
  - Preserved the existing `asyncio.Task[object]` session handle contract and
    one-live-session invariant.
- Checks:
  - `cd backend && .venv/bin/python -m pytest tests/test_conductor_session_registry.py tests/test_conductor_recovery.py -q`
    - Result: `12 passed`.
  - `cd backend && .venv/bin/python -m ruff check app/application/conductor_session_registry.py tests/test_conductor_session_registry.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/application/conductor_session_registry.py tests/test_conductor_session_registry.py tests/test_conductor_recovery.py --show-error-codes --no-pretty`
    - Result: passed for `3` source files; emitted the existing unused
      override-section note from `pyproject.toml`.

## 2026-07-07 Audit Port Payload Typing Batch 104

- Backend audit typing cleanup:
  - Replaced `Any | None` audit payload types with `object | None` in
    `backend/app/domain/ports.py` and `backend/app/application/audit/writer.py`.
  - Updated `backend/app/application/audit/recorders.py` to use
    `Mapping[str, object]`, `JsonObject`, and explicit text-tail coercion for
    event, command-exec, conductor-turn, and autoplan payloads.
  - Kept audit serialization behavior unchanged: non-JSON-serializable payloads
    still fall back to a repr envelope, and large payloads are still truncated.
- Checks:
  - `cd backend && .venv/bin/python -m pytest tests/test_audit_logger.py tests/test_backend_source_hygiene.py -q`
    - Result: `25 passed`.
  - `cd backend && .venv/bin/python -m mypy app/application/audit/writer.py app/domain/ports.py app/application/audit/recorders.py tests/test_audit_logger.py --show-error-codes --no-pretty`
    - Result: passed for `4` source files; emitted the existing unused
      override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -m pytest tests/test_audit_logger.py tests/test_project_run.py tests/test_project_conductor.py -q`
    - Result: `33 passed`.
  - `cd backend && .venv/bin/python -m ruff check app/application/audit/recorders.py app/application/audit/writer.py app/domain/ports.py tests/test_audit_logger.py`
    - Result: passed.

## 2026-07-07 Tolerant JSON Loader Object Boundary Batch 105

- Backend JSON loader cleanup:
  - Changed `backend/app/application/tolerant_json.py` so
    `tolerant_json_loads(...)` returns `object` instead of `Any`.
  - Updated Architect, Engineer, and QA workflow persistence paths to pass the
    tolerant JSON result through `object_dict(...)` before normalizing payload
    keys.
  - Added explicit shape assertions in tolerant JSON tests before indexing
    repaired payloads.
- Checks:
  - `cd backend && .venv/bin/python -m pytest tests/test_tolerant_json.py tests/test_architect_workflow.py tests/test_qa_workflow.py tests/test_engineer_workflow.py tests/test_agent_catalog.py -q`
    - Result: `78 passed`.
  - `cd backend && .venv/bin/python -m ruff check app/application/tolerant_json.py app/application/architect_workflow.py app/application/engineer_workflow.py app/application/qa_workflow.py tests/test_tolerant_json.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/application/tolerant_json.py app/application/architect_workflow.py app/application/engineer_workflow.py app/application/qa_workflow.py app/application/product_manager_service.py app/application/agent_catalog/generic_specialist_workflow.py tests/test_tolerant_json.py --show-error-codes --no-pretty`
    - Result: passed for `7` source files; emitted the existing unused
      override-section note from `pyproject.toml`.

## 2026-07-07 Backend Full Gate After Audit/Tolerant JSON Sweep Batch 106

- Scope:
  - Validated the backend after Batches 101-105, covering task completion
    registry result typing, conductor session coroutine typing, audit payload
    typing, and tolerant JSON object-boundary guards.
- Checks:
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `263` source files.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1128 passed, 77 skipped, 166 deselected, 1 warning in 52.76s`.

## 2026-07-07 Frontend Prototype API Test JSON Guard Batch 107

- Frontend test-boundary cleanup:
  - Updated `frontend/tests/prototypeApi.test.ts` to parse runtime-evidence
    query JSON with `safeJsonRecord(...)` instead of `JSON.parse(...) as
    { title?: string }`.
  - Kept the test aligned with `noPropertyAccessFromIndexSignature` by reading
    the parsed record through bracket access.
- Checks:
  - `cd frontend && node --import tsx --test tests/prototypeApi.test.ts tests/sourceHygiene.test.ts`
    - Result: `26 passed`.
  - `cd frontend && npm run typecheck`
    - Result: passed. Existing npm warning remains: unknown user config
      `allowBuilds`.

## 2026-07-07 Frontend Execution Patch Test Record Guard Batch 108

- Frontend test-boundary cleanup:
  - Replaced `as Record<string, unknown>` casts in
    `frontend/tests/executionProcessPatch.test.ts` with a local
    `assertRecord(...)` assertion helper.
  - The inline JSON-patch test helper now proves every traversed patch target is
    a non-null object before mutating it.
- Checks:
  - `cd frontend && node --import tsx --test tests/executionProcessPatch.test.ts tests/sourceHygiene.test.ts`
    - Result: `25 passed`.
  - `cd frontend && npm run typecheck`
    - Result: passed. Existing npm warning remains: unknown user config
      `allowBuilds`.

## 2026-07-07 Frontend Full Gate After Test JSON Guard Sweep Batch 109

- Scope:
  - Validated the frontend after Batches 107-108, covering safer test JSON
    parsing in prototype API and execution-process patch helpers.
- Checks:
  - `cd frontend && npm test`
    - Result: `373 passed`.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm run format:check`
    - Result: passed.
  - `cd frontend && npm run build`
    - Result: passed. Existing warnings remain: npm unknown user config
      `allowBuilds`; Next build emits the existing Node `[DEP0205]
      module.register()` warning.

## 2026-07-07 Frontend Fetch Test Utility Refactor Batch 110

- Frontend test infrastructure cleanup:
  - Added `frontend/tests/fetchTestUtils.ts` with shared `withMockFetch(...)`,
    `withMockJsonFetch(...)`, `contentType(...)`, and `jsonRequestBody(...)`
    helpers for API client tests.
  - Migrated API request-body assertions in agent mesh, project conductor,
    resume, benchmarks, API fetch helper, decision explanation, and workbench
    action tests away from ad hoc `JSON.parse(String(call.init?.body))`.
  - Added a source-hygiene test that keeps fetch request-body parsing in tests
    behind `jsonRequestBody(...)`.
- Checks:
  - `cd frontend && npm run typecheck`
    - Result: passed. Existing npm warning remains: unknown user config
      `allowBuilds`.
  - `cd frontend && node --import tsx --test tests/apiFetchHelpers.test.ts tests/agentMeshApi.test.ts tests/projectConductorApi.test.ts tests/resumeApi.test.ts tests/benchmarksApi.test.ts tests/decisionExplanationPanel.test.ts tests/workbenchActions.test.ts tests/sourceHygiene.test.ts`
    - Result: `61 passed`.

## 2026-07-07 Task Conversation Log Typing Batch 111

- Frontend runtime/test typing cleanup:
  - Tightened `mergeTaskConversationLogs(...)` to return
    `TaskConversationLog[]` instead of `unknown[]`, reflecting the existing
    behavior that only logs with a string `id` are retained.
  - Updated `useTaskConversationDetail(...)` to expose typed conversation logs.
  - Replaced broad test casts in task-conversation and execution-process patch
    tests with typed execution-process fixtures and direct `log.id` assertions.
- Checks:
  - `cd frontend && node --import tsx --test tests/taskConversationDetailUtils.test.ts tests/executionProcessPatch.test.ts tests/sourceHygiene.test.ts`
    - Result: `30 passed`.
  - `cd frontend && npm run typecheck`
    - Result: passed. Existing npm warning remains: unknown user config
      `allowBuilds`.

## 2026-07-07 Self-Improvement JSON Boundary Guard Batch 112

- Backend JSON safety cleanup:
  - Updated project-memory safe reads to use `parse_json_object(...)` and the
    shared `object_list(...)` helper instead of a local list guard.
  - Updated self-improvement proposal extraction to parse task result JSON via
    `parse_json_value(..., default=raw)` and tool events via
    `object_dict_list(...)`.
  - Updated self-improvement apply-plan evidence parsing to use
    `parse_json_object_list(...)`.
  - Extended backend source hygiene so project-memory and self-improvement
    safe-read boundaries cannot regress to direct `json.loads(...)`.
- Checks:
  - `cd backend && .venv/bin/python -m pytest tests/test_self_improvement_service.py tests/test_self_improvement_apply_service.py tests/test_backend_source_hygiene.py -q`
    - Result: `33 passed`.
  - `cd backend && .venv/bin/python -m ruff check app/application/project_memory_service.py app/application/self_improvement_service.py app/application/self_improvement_apply_service.py tests/test_self_improvement_service.py tests/test_self_improvement_apply_service.py tests/test_backend_source_hygiene.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/application/project_memory_service.py app/application/self_improvement_service.py app/application/self_improvement_apply_service.py tests/test_self_improvement_service.py tests/test_self_improvement_apply_service.py tests/test_backend_source_hygiene.py --show-error-codes --no-pretty`
    - Result: passed for `6` source files; emitted the existing unused
      override-section note from `pyproject.toml`.

## 2026-07-07 Frontend Full Gate After Fetch/Conversation Typing Batch 113

- Scope:
  - Validated the frontend after Batches 110-111, covering shared fetch test
    utilities, request-body JSON parsing hygiene, and typed task conversation
    logs.
- Checks:
  - `cd frontend && npm test`
    - Result: `374 passed`.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm run format:check`
    - Result: passed.
  - `cd frontend && npm run build`
    - Result: passed. Existing warnings remain: npm unknown user config
      `allowBuilds`; Next build emits the existing Node `[DEP0205]
      module.register()` warning.

## 2026-07-07 Backend Full Gate After Self-Improvement JSON Sweep Batch 114

- Scope:
  - Validated the backend after Batch 112, covering project-memory and
    self-improvement JSON safe-read boundary cleanup.
- Checks:
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `263` source files.
  - `cd backend && .venv/bin/python -c "from app.main import app"`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1128 passed, 77 skipped, 166 deselected in 69.03s`.

## 2026-07-07 API JSON Row Typing Batch 115

- Backend API typing cleanup:
  - Removed `Any` from `backend/app/interfaces/api.py` by typing JSON row
    lists as `list[JsonObject]`.
  - Added narrow string/JSON text readers for row fields before calling typed
    store, process-manager, task-event, and response-model APIs.
  - Added a backend source-hygiene assertion that prevents
    `interfaces/api.py` from regressing to `dict[str, Any]` or importing
    `Any` from `typing`.
- Checks:
  - `cd backend && .venv/bin/python -m pytest tests/test_backend_source_hygiene.py tests/test_codex_tasks.py tests/test_projects_api.py tests/test_operations_engineer_script_task.py tests/test_prototypes_api.py -q`
    - Result: `87 passed, 77 skipped`.
  - `cd backend && .venv/bin/python -m ruff check app/interfaces/api.py tests/test_backend_source_hygiene.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/interfaces/api.py tests/test_backend_source_hygiene.py tests/test_codex_tasks.py tests/test_projects_api.py tests/test_prototypes_api.py --show-error-codes --no-pretty`
    - Result: passed for `5` source files; emitted the existing unused
      override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -c "from app.main import app"`
    - Result: passed.

## 2026-07-07 Backend Full Gate After API Row Typing Batch 116

- Scope:
  - Validated the backend after Batch 115, covering `interfaces/api.py` JSON
    row typing and the new source-hygiene guard.
- Checks:
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `263` source files.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1129 passed, 77 skipped, 166 deselected in 76.84s`.

## 2026-07-07 Backend Test Fixture Typing Batch 117

- Backend test typing cleanup:
  - Replaced `Any` marker casts in artifact-validation signaling tests with a
    narrow `_ValidationMarkedTask` Protocol and explicit result shape
    assertions.
  - Replaced loose TOML table casts in CI quality-gate tests with
    `Mapping`-based object dictionaries.
  - Reworked message-streaming runtime fixtures to construct a real
    `CodexAppServerRuntime` and return typed `AsyncSQLiteStore` fixtures
    instead of using `CodexAppServerRuntime.__new__(...)` through `Any`.
- Checks:
  - `cd backend && .venv/bin/python -m ruff check tests/test_artifact_validation_signal.py tests/test_ci_quality_gates.py tests/test_message_streaming.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy tests/test_artifact_validation_signal.py tests/test_ci_quality_gates.py tests/test_message_streaming.py --show-error-codes --no-pretty`
    - Result: passed for `3` source files; emitted the existing unused
      override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -m pytest tests/test_artifact_validation_signal.py tests/test_ci_quality_gates.py tests/test_message_streaming.py -q`
    - Result: `20 passed`.

## 2026-07-07 Backend Full Gate After Test Fixture Typing Batch 118

- Scope:
  - Validated the backend after Batch 117, covering typed artifact-validation,
    CI quality-gate, and message-streaming test fixtures.
- Checks:
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `263` source files.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1129 passed, 77 skipped, 166 deselected, 1 warning in 75.82s`.

## 2026-07-07 Frontend Format Gate Test Coverage Batch 119

- Frontend quality-gate cleanup:
  - Expanded `frontend/package.json` `format` and `format:check` scripts to
    cover both `src/**/*.{ts,tsx}` and `tests/**/*.{ts,tsx}`.
  - Formatted `frontend/tests/qaReportStatus.test.ts`, which the previous
    `src`-only format gate did not catch.
  - Updated ccgui and vibe-kanban frontend quality specs to describe the
    runtime-and-test TypeScript format boundary.
  - Added a source-hygiene test that locks the format scripts to the expanded
    runtime/test coverage.
- Checks:
  - `cd frontend && npm run format:check`
    - Result: passed across `src` and `tests`.
  - `cd frontend && node --import tsx --test tests/sourceHygiene.test.ts tests/qaReportStatus.test.ts`
    - Result: `26 passed`.
  - `cd frontend && npm run typecheck`
    - Result: passed. Existing npm warning remains: unknown user config
      `allowBuilds`.

## 2026-07-07 Frontend Full Gate After Format Coverage Batch 120

- Scope:
  - Validated the frontend after Batch 119, covering expanded Prettier coverage
    for runtime and test TypeScript files.
- Checks:
  - `cd frontend && npm test`
    - Result: `375 passed`.
  - `cd frontend && npm run lint`
    - Result: passed.
  - `cd frontend && npm run format:check`
    - Result: passed across `src` and `tests`.
  - `cd frontend && npm run typecheck`
    - Result: passed.
  - `cd frontend && npm run build`
    - Result: passed. Existing warnings remain: npm unknown user config
      `allowBuilds`; Next build emits the existing Node `[DEP0205]
      module.register()` warning.

## 2026-07-07 Message Streaming Test Runtime Fixture Batch 121

- Backend test fixture cleanup:
  - Replaced `BaseProcessRuntime` method monkeypatches in
    `test_message_streaming.py` with a small `_TestProcessRuntime` subclass.
  - Removed the remaining `type: ignore[method-assign]` escapes from the
    message-streaming termination test while preserving the same cleanup
    behavior under test.
- Checks:
  - `cd backend && .venv/bin/python -m ruff check tests/test_message_streaming.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy tests/test_message_streaming.py --show-error-codes --no-pretty`
    - Result: passed for `1` source file; emitted the existing unused
      override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -m pytest tests/test_message_streaming.py -q`
    - Result: `11 passed`.

## 2026-07-07 Embedding Service Test Provider Fixture Batch 122

- Backend test fixture cleanup:
  - Replaced `_call_provider` method monkeypatches in
    `tests/test_embedding_service.py` with a typed `_ProviderEmbeddingService`
    test subclass.
  - Removed the remaining `type: ignore[method-assign]` escapes from embedding
    provider cache/error tests.
- Checks:
  - `cd backend && .venv/bin/python -m ruff check tests/test_embedding_service.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy tests/test_embedding_service.py --show-error-codes --no-pretty`
    - Result: passed for `1` source file; emitted the existing unused
      override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -m pytest tests/test_embedding_service.py -q`
    - Result: `11 passed`.

## 2026-07-07 Conductor LLM Protocol Typing Batch 123

- Backend LLM protocol typing cleanup:
  - Replaced `dict[str, Any]` signatures in `llm_runner.py`'s
    Anthropic/OpenAI tool-call adapter boundary with the shared
    `JsonObject` shape from `json_safety`.
  - Updated `conductor_llm.py` to accept and return the same JSON object
    protocol shape, keeping the conductor's LLM wrapper aligned with the
    lower-level adapter.
  - Reworked OpenAI adapter tests and the conductor main-loop tool-use
    fixture to unpack nested JSON with `json_safety` helpers instead of
    annotating fixtures as `Any`.
  - Recorded the previously unlogged backend post-fixture-cleanup gate:
    `ruff check .` passed, full backend mypy passed for `263` source files,
    and the focused fixture cleanup pytest run passed with `39 passed`.
- Checks:
  - `cd backend && .venv/bin/python -m pytest tests/test_conductor_openai_adapter.py tests/test_llm_runner_streaming.py -q`
    - Result: `10 passed`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `263` source files.
  - `cd backend && .venv/bin/python -m pytest tests/test_conductor_openai_adapter.py tests/test_llm_runner_streaming.py tests/test_conductor_main_loop.py -q`
    - Result: `48 passed`.

## 2026-07-07 Conductor Tool Protocol Typing Batch 124

- Backend conductor protocol typing cleanup:
  - Propagated the shared `JsonObject` protocol shape from `llm_runner.py`
    into `conductor_main_loop.py` and `conductor_tools.py` for LLM messages,
    tool definitions, tool inputs, tool results, and persisted turn payloads.
  - Changed the main-loop tool registry parameter to a read-only `Mapping`
    so async tool callables from `ConductorToolRegistry` can be passed without
    invariant `dict` casts.
  - Added small string/int JSON extraction helpers in `conductor_tools.py` for
    dispatcher and worktree boundaries instead of passing raw `object` values.
  - Updated conductor tool tests to unpack tool results with `json_safety`
    helpers, avoiding test-side deep indexing through `object`.
  - Verified the LLM/tool protocol chain no longer contains
    `dict[str, Any]`/`list[dict[str, Any]]` signatures in the touched
    conductor files; remaining `Any` in `conductor_main_loop.py` belongs to
    the broader store/event_bus dynamic port boundary.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/conductor_tools.py app/application/conductor_main_loop.py tests/test_conductor_main_loop.py --show-error-codes --no-pretty`
    - Result: passed for `3` source files; emitted the existing unused
      override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -m ruff check app/application/conductor_tools.py app/application/conductor_main_loop.py tests/test_conductor_main_loop.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest tests/test_conductor_main_loop.py tests/test_conductor_openai_adapter.py tests/test_llm_runner_streaming.py tests/test_conductor_subagent_timeout.py tests/test_conductor_redispatch_budget.py tests/test_artifact_validation_signal.py -q`
    - Result: `64 passed`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `263` source files.

## 2026-07-07 Conductor Tool Port Typing Batch 125

- Backend conductor tool port typing cleanup:
  - Reused existing `EventBusLike` and `TaskDispatcherFn` Protocols for
    `build_conductor_tools(...)` instead of accepting raw injected objects for
    those ports.
  - Narrowed non-store dynamic values in `conductor_tools.py`: status checks now
    accept `object`, and event-bus compatibility is contained inside the
    `_emit(...)` dynamic boundary.
  - Kept `store` as the remaining explicit dynamic port in `conductor_tools.py`
    because the module calls a broad async-store surface and test doubles; that
    should be handled as a dedicated store Protocol refactor.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/conductor_tools.py --show-error-codes --no-pretty`
    - Result: passed for `1` source file; emitted the existing unused
      override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -m ruff check app/application/conductor_tools.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `263` source files.
  - `cd backend && .venv/bin/python -m pytest tests/test_conductor_main_loop.py tests/test_conductor_subagent_timeout.py tests/test_conductor_redispatch_budget.py tests/test_artifact_validation_signal.py -q`
    - Result: `54 passed`.

## 2026-07-07 Conductor Recovery Port Typing Batch 126

- Backend conductor recovery typing cleanup:
  - Reused the existing `EventBusLike` and `TaskDispatcherFn` Protocols in
    `conductor_recovery.py` for recovery, relaunch, stalled marking, and
    watchdog entry points.
  - Narrowed relaunch recovery context graph input to `WorkflowGraph`, leaving
    only the broad store surface as the intentional dynamic boundary.
  - Preserved runtime behavior for stale detection, relaunch circuit breaker,
    graph reset, and watchdog event emission.
- Checks:
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1129 passed, 77 skipped, 166 deselected in 64.11s`.
  - `cd backend && .venv/bin/python -m mypy app/application/conductor_recovery.py --show-error-codes --no-pretty`
    - Result: passed for `1` source file; emitted the existing unused
      override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -m pytest tests/test_conductor_recovery.py tests/test_conductor_redispatch_budget.py tests/test_run_issue_conductor_loop.py -q`
    - Result: `28 passed`.
  - `cd backend && .venv/bin/python -m ruff check app/application/conductor_recovery.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `263` source files.

## 2026-07-07 Conductor Recovery Store Boundary Batch 127

- Backend conductor recovery typing cleanup:
  - Removed the explicit `typing.Any` dependency from
    `conductor_recovery.py`.
  - Changed recovery/watchdog store parameters to `object` and kept optional
    store methods behind the existing `getattr(..., None)` dynamic boundary.
  - Added a tiny `_ConductorTaskSaver` Protocol for the required
    `save_conductor_task(...)` calls so the relaunch breaker and stalled-task
    marking preserve their original fail-fast behavior without constant
    `getattr` calls.
  - Verified source search: `conductor_recovery.py` no longer appears in the
    touched conductor `Any`/`dict[str, Any]` sweep; remaining explicit `Any`
    sites are in `conductor_main_loop.py` and the broad store injection in
    `conductor_tools.py`.
- Checks:
  - `cd backend && .venv/bin/python -m ruff check app/application/conductor_recovery.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app/application/conductor_recovery.py --show-error-codes --no-pretty`
    - Result: passed for `1` source file; emitted the existing unused
      override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -m pytest tests/test_conductor_recovery.py tests/test_run_issue_conductor_loop.py -q`
    - Result: `17 passed`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `263` source files.

## 2026-07-07 Conductor Main Loop Port Typing Batch 128

- Backend conductor main-loop typing cleanup:
  - Reused existing `EventBusLike` and `TaskDispatcherFn` Protocols in
    `conductor_main_loop.py` for the issue loop, failure recovery, graph/issue
    sealing, event emission, and phase transitions.
  - Replaced generic estimator annotations with the concrete
    `PhaseDurationEstimator` type.
  - Left only the broad store parameter as the explicit dynamic boundary in
    `conductor_main_loop.py`; this matches the remaining `conductor_tools.py`
    store boundary and should be tackled as one dedicated store Protocol pass.
  - Verified the touched LLM/tool/recovery chain no longer contains
    `dict[str, Any]` or `list[dict[str, Any]]` protocol signatures.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/conductor_main_loop.py app/application/conductor_recovery.py tests/test_conductor_main_loop.py --show-error-codes --no-pretty`
    - Result: passed for `3` source files; emitted the existing unused
      override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -m ruff check app/application/conductor_main_loop.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `263` source files.
  - `cd backend && .venv/bin/python -m pytest tests/test_conductor_main_loop.py tests/test_conductor_recovery.py tests/test_run_issue_conductor_loop.py tests/test_conductor_subagent_timeout.py tests/test_conductor_redispatch_budget.py -q`
    - Result: `67 passed`.

## 2026-07-07 Prototype Disk Mirror Typing Batch 129

- Backend prototype service typing cleanup:
  - Removed the remaining `type: ignore[assignment]` in
    `prototype_service.py`'s disk mirror path.
  - Split the always-present write target (`disk_target: Path`) from the
    optional persisted path (`disk_path: Path | None`) so disk failures still
    suppress broken UI links without mutating a `Path` variable to `None`.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/prototype_service.py tests/test_prototype_service.py --show-error-codes --no-pretty`
    - Result: passed for `2` source files; emitted the existing unused
      override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `263` source files.
  - `cd backend && .venv/bin/python -m pytest tests/test_prototype_service.py -q`
    - Result: `36 passed`.

## 2026-07-07 Conductor Main Loop Store Boundary Batch 130

- Backend conductor main-loop typing cleanup:
  - Removed the explicit `typing.Any` dependency from
    `conductor_main_loop.py`.
  - Changed main-loop store parameters to `object`, then used small local
    Protocol casts for direct required store calls (`save_conductor_task`,
    issue save/load, latest conductor task load, workflow graph load/save, and
    project load).
  - Reused existing store Protocols for cross-service calls:
    `RuntimeCatalogStore`, `ProjectConductorStore`, `BudgetStore`,
    `ProjectMemoryStore`, and the self-improvement proposal store.
  - Kept optional store features behind the existing `getattr(..., None)`
    boundaries so lightweight test doubles do not need to implement the full
    async store surface.
  - Verified source search: the touched LLM/tool/recovery/main-loop/prototype
    chain no longer contains `dict[str, Any]`, `list[dict[str, Any]]`, or
    explicit `typing.Any` except for the remaining broad store boundary in
    `conductor_tools.py` and a prose comment in `llm_runner.py`.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/conductor_main_loop.py tests/test_conductor_main_loop.py --show-error-codes --no-pretty`
    - Result: passed for `2` source files; emitted the existing unused
      override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -m ruff check app/application/conductor_main_loop.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `263` source files.
  - `cd backend && .venv/bin/python -m pytest tests/test_conductor_main_loop.py tests/test_conductor_recovery.py tests/test_run_issue_conductor_loop.py tests/test_conductor_subagent_timeout.py tests/test_conductor_redispatch_budget.py tests/test_artifact_validation_signal.py -q`
    - Result: `71 passed, 1 warning`; warning was a pytest thread warning from
      an aiosqlite worker reporting `Event loop is closed` after
      `test_loop_calls_finalize`.

## 2026-07-07 Conductor Tool Store Boundary Batch 131

- Backend conductor tool typing cleanup:
  - Removed the final explicit `typing.Any` dependency from
    `conductor_tools.py`.
  - Changed `build_conductor_tools(...)` store input to `object` and used
    existing Protocols (`ProjectConductorStore`, `BudgetStore`,
    `DispatchRoleStore`) plus small local Protocols for workflow graph, task,
    issue, and project store calls.
  - Preserved optional/dynamic behavior at the runtime boundaries while making
    direct required store calls explicit through narrow casts.
  - Verified source search across `backend/app`, `backend/tests`,
    `backend/benchmark`, `frontend/src`, and `frontend/tests`: no remaining
    `type: ignore`, `from typing import Any`, `dict[str, Any]`,
    `list[dict[str, Any]]`, `Awaitable[Any]`, `Callable[..., Any]`, or
    `cast(Any...)` matches outside the source-hygiene test's own assertion
    strings.
- Checks:
  - `cd backend && .venv/bin/python -m mypy app/application/conductor_tools.py tests/test_conductor_main_loop.py tests/test_conductor_redispatch_budget.py tests/test_conductor_subagent_timeout.py tests/test_artifact_validation_signal.py --show-error-codes --no-pretty`
    - Result: passed for `5` source files; emitted the existing unused
      override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -m ruff check app/application/conductor_tools.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `263` source files.
  - `cd backend && .venv/bin/python -m pytest tests/test_conductor_main_loop.py tests/test_conductor_recovery.py tests/test_run_issue_conductor_loop.py tests/test_conductor_subagent_timeout.py tests/test_conductor_redispatch_budget.py tests/test_artifact_validation_signal.py tests/test_conductor_dispatch_batch.py tests/test_dispatch_batch_budget_concurrency.py tests/test_swarm_integration.py -q`
    - Result: `99 passed, 1 warning`; warning was a pytest thread warning from
      an aiosqlite worker reporting `Event loop is closed` after
      `test_relaunch_circuit_breaker_trips_after_max`.
  - `cd backend && .venv/bin/python -m pytest tests/test_backend_source_hygiene.py -q`
    - Result: `8 passed`.

## 2026-07-07 Backend Type Escape Hygiene Batch 132

- Backend source-hygiene hardening:
  - Added a regression test that scans backend app, benchmark, and test Python
    sources for explicit type escape patterns (`type: ignore`,
    `from typing import Any`, `dict[str, Any]`, `list[dict[str, Any]]`,
    `Awaitable[Any]`, and `cast(Any...)`).
  - The test excludes only `test_backend_source_hygiene.py` itself so the
    assertion strings do not self-match.
  - This turns the broad conductor/prototype typing cleanup into an executable
    guard instead of a one-time search result.
- Checks:
  - `cd backend && .venv/bin/python -m pytest tests/test_backend_source_hygiene.py -q`
    - Result: `9 passed`.
  - `cd backend && .venv/bin/python -m ruff check tests/test_backend_source_hygiene.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy tests/test_backend_source_hygiene.py --show-error-codes --no-pretty`
    - Result: passed for `1` source file; emitted the existing unused
      override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `263` source files.

## 2026-07-07 Frontend Full Gate Refresh Batch 133

- Scope:
  - Re-ran the full frontend quality gate after the backend conductor/prototype
    typing pass and source-hygiene hardening.
  - Confirms the expanded format gate still covers runtime and test TypeScript
    files and the production build remains healthy.
- Checks:
  - `cd frontend && npm audit --registry=https://registry.npmjs.org`
    - Result: passed with `found 0 vulnerabilities`; existing npm
      `allowBuilds` warning remains.
  - `cd frontend && npm test`
    - Result: `375 passed`; existing npm warning remains: unknown user config
      `allowBuilds`.
  - `cd frontend && npm run lint`
    - Result: passed; existing npm `allowBuilds` warning remains.
  - `cd frontend && npm run format:check`
    - Result: passed across `src` and `tests`; existing npm `allowBuilds`
      warning remains.
  - `cd frontend && npm run typecheck`
    - Result: passed; existing npm `allowBuilds` warning remains.
  - `cd frontend && npm run build`
    - Result: passed with Next.js `15.5.20`; existing npm `allowBuilds`
      warning remains.

## 2026-07-07 Backend Full Gate After Type Escape Guard Batch 134

- Scope:
  - Re-ran the full backend pytest suite after the conductor store-boundary
    cleanup and new source-hygiene type-escape guard.
  - The total passing count increased by one because
    `test_backend_source_hygiene.py` now includes the explicit type-escape
    regression test.
- Checks:
  - `cd backend && .venv/bin/python -c "from app.main import app"`
    - Result: passed.
  - `cd backend && .venv/bin/python -m pytest -q --tb=short --disable-warnings`
    - Result: `1130 passed, 77 skipped, 166 deselected, 2 warnings in 80.26s`.

## 2026-07-07 Backend Quality Spec Type Hygiene Batch 135

- Backend spec update:
  - Updated `.trellis/spec/vibe-kanban/backend/quality-guidelines.md` to
    document the new project-wide type-escape source-hygiene guard.
  - Clarified that `type: ignore`, `from typing import Any`, `dict[str, Any]`,
    `list[dict[str, Any]]`, `Awaitable[Any]`, and `cast(Any...)` require an
    intentional documented boundary change.
  - Updated the Conductor Tool-Turn Side-Effect Safety signatures from the old
    `dict[str, Any]` protocol shapes to the current `JsonObject` and
    `Mapping[str, ToolCallable]` contracts.
- Checks:
  - `cd backend && .venv/bin/python -m pytest tests/test_backend_source_hygiene.py -q`
    - Result: `9 passed`.
  - `cd backend && .venv/bin/python -m pytest tests/test_benchmark_type_hygiene.py tests/test_backend_source_hygiene.py -q`
    - Result: `10 passed`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `263` source files.

## 2026-07-07 Touched Diff Whitespace Check Batch 136

- Scope:
  - Checked whitespace/conflict-marker hygiene for the files touched by the
    conductor/prototype typing and spec/report updates.
  - A full-repo `git diff --check` is still blocked by an unrelated existing
    dirty file: `backend/app/application/product_manager_service.py:623`
    reports `new blank line at EOF`. That file was not part of this batch and
    was left untouched.
- Checks:
  - `git diff --check -- <typed conductor/prototype/source-hygiene/spec/report files>`
    - Result: passed for the touched file set.

## 2026-07-07 Prototype API Test Debug Output Cleanup Batch 137

- Backend test cleanup:
  - Replaced failure-path `print(...)` debug output in
    `tests/test_prototypes_api.py` with `pytest.fail(...)` carrying the same
    SSE body/event details.
  - Re-ran source search for debug output; remaining matches are i18n keys,
    generated script text, command/test fixture strings, and source-hygiene
    assertions rather than live debug prints.
- Checks:
  - `cd backend && .venv/bin/python -m pytest tests/test_prototypes_api.py -q`
    - Result: `25 passed`.
  - `cd backend && .venv/bin/python -m ruff check tests/test_prototypes_api.py`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy tests/test_prototypes_api.py --show-error-codes --no-pretty`
    - Result: passed for `1` source file; emitted the existing unused
      override-section note from `pyproject.toml`.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `263` source files.

## 2026-07-07 Quick Wrap Gate Batch 138

- Scope:
  - Stopped the final hold window after the user requested a quick wrap.
  - Ran Trellis record-mode survey for the active task and dirty worktree
    status.
  - Kept the task unarchived because the main worktree still has current-task
    uncommitted changes, which Trellis finish-work treats as a reason to return
    to the commit phase rather than archiving.
- Checks:
  - `python3 ./.trellis/scripts/get_context.py --mode record`
    - Result: current task remains
      `.trellis/tasks/07-06-project-excellence-24h` with status
      `in_progress`; main worktree reports `515` uncommitted changes.
  - `cd backend && .venv/bin/python -m ruff check .`
    - Result: passed.
  - `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`
    - Result: passed for `263` source files.
  - `cd frontend && npm run typecheck`
    - Result: passed; existing npm `allowBuilds` warning remains.
  - `git diff --check -- <typed conductor/prototype/source-hygiene/spec files>`
    - Result: passed for the touched quick-wrap file set.
