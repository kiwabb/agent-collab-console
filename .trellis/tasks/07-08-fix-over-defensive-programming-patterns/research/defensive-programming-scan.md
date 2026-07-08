# Defensive Programming Scan

Date: 2026-07-08

This task was created after a focused scan of backend and frontend source for over-defensive patterns that hide defects, silently degrade behavior, or waste render/runtime work.

## Backend findings

### Critical: governance gates fail open

- `backend/app/application/conductor_tools.py:208-215` — `_check_budget_gate` catches `Exception` and returns `None`, which means dispatch proceeds with no budget block.
- `backend/app/application/conductor_tools.py:173-178` — `_check_role_rework_limit` treats workflow graph load failure as no graph/no limit.
- `backend/app/application/conductor_tools.py:750-761` — `dispatch_batch` budget check catches `Exception` and allows batch fan-out with `batch_budget_status = None`.
- `backend/app/application/specialist_orchestrator.py:146-184` — specialist concurrency/budget checks log debug and skip enforcement on unexpected errors.

Fix direction: fail closed for governance gates. If a gate cannot verify safety, refuse the action with a structured tool result or typed error.

### High: context silently degrades

- `backend/app/application/role_workflow_service.py:114-118` — team memory load failure sets `memory_text = None` with no operator-visible warning.
- `backend/app/application/conductor_main_loop.py:1044-1052` — warm project history assembly failure logs debug and strips recent history from conductor context.
- `backend/app/application/conductor_main_loop.py:1063-1085` — budget context rendering failure logs debug and strips cost guidance.

Fix direction: expected legacy/corrupt optional data may degrade with warning; unexpected service/calculation failures should either propagate to the supervisor boundary or produce explicit failed/unavailable state.

### High/medium: typed model fields accessed defensively

- `backend/app/application/role_workflow_service.py:76` and nearby — `getattr(task, "role", None)` on a declared `CodexTask` field.
- `backend/app/adapters/async_sqlite_store.py:1367-1372` and `sqlite_store.py:1260-1265` — `getattr(issue, "github_pr_url", None)` etc. on declared `CodexIssue` fields inside INSERT.
- `backend/app/application/conductor_main_loop.py:810` — `getattr(issue, "status", None)` on declared `CodexIssue.status`.
- `backend/app/application/budget_service.py:278-286` — repeated `getattr(..., default)` over declared runtime catalog fields.

Fix direction: replace with direct attribute access where the model contract declares the field. Keep guards only at raw DB/JSON/API boundaries.

### Medium: stacked redundant defenses

- `backend/app/application/codex_task_runner.py:437-445` — `is not None` + `getattr` + `callable` + broad `try/except` around a typed store method.
- `backend/app/application/conductor_recovery.py:343-344` and similar — `getattr(graph, "nodes", []) or []` on declared `WorkflowGraph` lists.
- `backend/app/application/conductor_tools.py:617-620` — `getattr(mgr, "terminate_task", None)` for a known manager method.

Fix direction: collapse to the actual invariant. Use one boundary check if the value is genuinely optional; otherwise call directly.

### Lower-risk cleanup

- Duplicate route/service validation and duplicate DB loads in help/prototype/project delete paths.
- Dead try/except around `raw.decode("utf-8", errors="ignore")`.
- Audit recorder helpers wrapping large pure-computation blocks instead of only the sink call.
- `_has_active_specialist_children` returns `True` on any error and can silently block parent resumption.

## Frontend findings

### High: type bypass + fallback compensation

- `frontend/src/features/issues/components/useIssueBudget.ts:99-111` casts an event to `IssueBudgetStatus & { type: string }` and then defaults every field with `??`. This both lies to TypeScript and hides malformed event payloads.

Fix direction: parse event payload with a small guard that returns a normalized partial update; do not cast to full domain type unless all required fields are verified.

### High: redundant `Object.values()` on arrays

- `frontend/src/features/workbench/WorkbenchPage.tsx:333,341,352,360,681,1200,1433` calls `Object.values(executionProcessesAll) as ExecutionProcess[]` although the context returns `ExecutionProcess[]`.

Fix direction: pass `executionProcessesAll` directly. If a call site expects a record, fix the upstream type.

### High: silent error swallowing / destructive recovery

- `frontend/src/features/workbench/WorkbenchPage.tsx:570-572` — cross-tab `getProject(next)` errors are swallowed.
- `frontend/src/features/issues/tabs/DagTab.tsx:97-99,116-118` — graph refresh and polling errors are swallowed.
- `frontend/src/features/workbench/components/CommandPalette.tsx:120-127` — load failure ends loading with no error state.
- `frontend/src/features/issues/IssueDetailPage.tsx:122-129` — six parallel fetches fall back to `null`/`[]`, so backend failure renders an empty page.
- `frontend/src/features/workbench/WorkbenchPage.tsx:504-508` — process log/message load error clears previously loaded data.

Fix direction: preserve stale data, expose a small error state, and avoid empty-screen fallbacks for primary page data.

### Medium/low: redundant nullish guards and dead try/catch

- `frontend/src/lib/taskConversationDetailUtils.ts:111,114,121` — `|| []` on required array parameters.
- `frontend/src/features/workbench/components/AppStatusBar.tsx:50` — `?? []` on typed context array.
- `frontend/src/features/workspaces/NewIssueDialog.tsx:67,70` — `?? []` on required catalog arrays.
- `frontend/src/features/skills/SkillsLibraryPage.tsx:187,917,919` — `?? []` on required `tags` array.
- `frontend/src/features/issues/IssueBoard.tsx:125` — fallback on record keys pre-initialized by `groupIssuesByPhase`.
- `frontend/src/features/workflow/ConductorLogPanel.tsx:1094,1153` — `?? {}` on required `payload` field.
- `frontend/src/features/issues/components/BudgetMeter.tsx:50` — `?? 0.8` on required `soft_warn_ratio`.
- `frontend/src/features/projects/BranchListView.tsx:40-47` — try/catch around `new Date(...).toLocaleString()`, which does not throw for invalid input.
- `frontend/src/lib/taskConversationDetailUtils.ts:29,32-35,74,85` — optional chaining on array/sort elements that are non-null by type.

Fix direction: remove fallbacks where the TypeScript contract guarantees non-null values. If runtime data is truly optional, update the type instead of adding defensive code at call sites.

## Recommended MVP scope

Implement all verified findings above, prioritizing:

1. Fail-closed governance gates.
2. Silent error/degradation paths that hide operator or user-visible failures.
3. Mechanical direct-field / direct-array cleanups with low behavioral risk.
4. Targeted tests for changed gate behavior, frontend error states, and type/source hygiene where appropriate.

Out of scope: repository-wide automated rewrites for every `getattr`/`??` occurrence not included in this verified scan.
