# Audit Logs Role-Level Call Chains

## Goal

Audit logs should expose the agent role hierarchy for a single turn so users can group calls by agent role and inspect each role's call chain, inputs, outputs, and related details.

## What I Already Know

* Current audit logs do not show role-level call chains clearly enough.
* Users need grouping by intelligent agent role.
* Users need to see the call chain within one round/turn.
* Users need input/output details for calls in that role-level chain.
* Current backend has a unified `audit_log` table and `GET /api/codex/audit-log`.
* Current frontend audit page lists raw audit rows newest-first and expands each row payload.
* Conductor turns already persist `turn_index`, `sub_index`, `kind`, and structured payload under `conductor_turns`.
* `dispatch_subagent` tool payloads carry the target role in `input.role`; tool results can carry spawned `task_id`, `role`, `status`, and summary.
* Sub-agent task audit rows can be associated with a role through `CodexTask.role` by `task_id`.

## Assumptions

* "Role" means the managed or specialist role key (`product_manager`, `architect`, `engineer`, `qa`, `specialist:*`, etc.).
* "One round" means a conductor `turn_index`; calls in the same conductor turn should be visually grouped together.
* Raw audit rows should remain available for debugging and compatibility.
* This MVP should avoid an audit table migration by deriving role and turn metadata at read time.

## Requirements

* Group audit-log entries by agent role.
* Show the role-level call chain for one conductor turn.
* Show detailed input and output information for each call in the chain.
* Preserve the existing raw audit row list and filters.
* Enrich audit log API items with derived role and conductor turn metadata where available.
* Support role grouping for both conductor dispatch calls and sub-agent task audit rows.

## Acceptance Criteria

* [ ] Audit-log UI presents calls grouped by agent role.
* [ ] A user can inspect a single turn's role-level call sequence.
* [ ] A user can inspect input and output details for calls in the chain.
* [ ] Existing audit-log behavior remains available.
* [ ] Backend tests cover derived role metadata for task-linked rows and conductor dispatch rows.
* [ ] Frontend tests or static checks cover the role-chain UI affordance.

## Definition of Done

* Tests added or updated where appropriate.
* Lint and typecheck pass for affected packages.
* Docs or Trellis notes updated if behavior or conventions change.
* Rollout and compatibility risk considered.

## Technical Approach

Add a derived role-chain layer on top of the existing audit read path:

* Backend serializes additional optional fields on audit rows:
  * `role`
  * `role_label`
  * `turn_index`
  * `sub_index`
  * `call_name`
  * `call_input`
  * `call_output`
  * `call_summary`
* For rows with `task_id`, derive role from `codex_tasks.role`.
* For conductor rows, parse `payload_json`:
  * `tool_use` + `dispatch_subagent` -> role from `input.role`, input from `input`.
  * `tool_result` + `dispatch_subagent` -> role from result role or task role, output from `result`.
  * other tool rows -> group under actor/tool when no role is available.
* Frontend adds an additive "Role Call Chain" grouped section before the raw rows:
  * group by role
  * within each role, group by conductor task and turn number where available
  * show category, call name, status, input/output, and raw payload expansion
* Keep all existing category/search/issue/task/time filters.

## Decision (ADR-lite)

**Context**: The existing audit table intentionally stores generic call rows without role-specific columns. Conductor turns already carry turn structure, and task rows already know the role.

**Decision**: Derive role-chain metadata at the API read boundary and render an additive grouped view in the audit page, without changing the audit table schema.

**Consequences**: Existing data remains compatible and old audit rows can still be shown. Some legacy/generic rows may be grouped as `Agent` or `Conductor` when no role can be inferred.

## Out of Scope

* Audit table schema migration for first-class `role` / `turn_index` columns.
* Rewriting the issue-specific conductor log panel.
* Full tracing across arbitrary nested specialist runs beyond known task/conductor relationships.

## Technical Notes

* Task created at `.trellis/tasks/06-27-audit-role-call-chain`.
* Relevant backend files inspected:
  * `backend/app/domain/models.py`
  * `backend/app/application/audit_logger.py`
  * `backend/app/application/conductor_main_loop.py`
  * `backend/app/adapters/audit_log_query.py`
  * `backend/app/adapters/async_sqlite_store.py`
  * `backend/app/interfaces/api.py`
* Relevant frontend files inspected:
  * `frontend/src/features/audit/AuditLogPage.tsx`
  * `frontend/src/features/workflow/ConductorLogPanel.tsx`
  * `frontend/src/lib/api.ts`
  * `frontend/src/lib/i18n.ts`
* Existing tests likely impacted:
  * `backend/tests/test_audit_log_api.py`
  * `backend/tests/test_audit_logger.py`
  * `frontend/tests/auditLogMotion.test.ts`
