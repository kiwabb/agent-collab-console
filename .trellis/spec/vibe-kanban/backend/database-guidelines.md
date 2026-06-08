# Database Guidelines

> Database patterns and conventions for this project.

---
## Overview

The persistence layer is **plain `aiosqlite`** with hand-written
SQL in `adapters/async_sqlite_store.py`. There is no ORM, no
migration framework, no schema-diff tool. The store owns the SQL
and the migrations; everything else reaches the database through
the typed methods (`load_codex_issue`, `list_codex_tasks`,
`save_execution_process`, `list_audit_log`, ...). The sync
counterpart in `adapters/sqlite_store.py` is for tests and
one-off scripts.

Migrations are an **idempotent boot-time step**: when the async
store opens a connection it inspects the schema, applies any
missing `ALTER TABLE ... ADD COLUMN` statements, and runs the
required `CREATE TABLE IF NOT EXISTS` blocks. Adding a new
column means: declare it in the domain model, add an idempotent
`ALTER TABLE` to the migration, and update any load method that
returns a row lacking the new column (default it). The
`schema_version` table tracks the current version; bump it
inside the migration block.

Transactions: each store method opens an implicit transaction
via `async with`; the long-running coroutines (conductor loop,
audit sink) do not hold a transaction across an `await` — they
release it before the await and re-acquire on the next call.

---

## Query Patterns

- **One method, one query.** A store method is the unit of
  work — it owns the SQL, the bind parameters, the row → model
  conversion. Callers compose methods; they do not compose SQL.
- **Batch by row, not by statement.** When listing tasks for an
  issue, the store iterates `task_id`s and reuses the existing
  per-task method. The alternative — a single `IN (?, ?, ...)`
  — is left for hot paths only and gets its own dedicated
  method with a focused test.
- **Read-only by default.** A read method never opens a write
  transaction. A write method opens the smallest possible
  transaction: single-row updates do not need `BEGIN`, but
  multi-row updates (`save_workflow_graph` + its `WorkflowNode`
  rows) do.
- **No N+1 in the loop body.** A conductor iteration that reads
  N issues' tasks collects the task ids first, then issues a
  single batched read. The conductor is the only place the
  pressure shows up.
- **No `SELECT *`.** Every query names its columns. Renames
  are safe; the cost is one extra line of SQL per query.

---

## Migrations

- **Migrations are idempotent.** `ALTER TABLE ... ADD COLUMN X`
  is wrapped in a `try/except` for the "duplicate column" case
  so re-opening the same DB does not raise.
- **No down-migrations.** The schema is append-only; rolling
  back a release is a separate problem.
- **Schema changes ship in the same commit as the code that
  reads them.** A new column is meaningless until the load
  method knows what to do with the value.
- **Bump `schema_version`** in the same migration block. The
  `validate()` boot check fails fast if the version is out of
  range.

---

## Naming Conventions

- **Tables**: snake_case, plural (`codex_issues`, `codex_tasks`,
  `execution_processes`, `audit_log`, `conductor_tasks`,
  `workflow_nodes`).
- **Columns**: snake_case, singular. Foreign keys are
  `<other_table_singular>_id` (`session_id`, `issue_id`,
  `task_id`, `project_id`).
- **Indexes**: `idx_<table>_<column>[_<column>...]` for
  single- and multi-column indexes.
- **Booleans**: `is_` / `has_` prefix (`is_pinned`,
  `git_merge_status`, `has_ceiling`).
- **Timestamps**: `*_at` suffix, ISO-8601 strings
  (`created_at`, `updated_at`, `heartbeat_at`,
  `lease_expires_at`).
- **Status enums**: capitalized, present-tense
  (`Completed`, `Failed`, `Running`, `Killed` — the set is
  stable and `budget_service.COMPLETED_PROCESS_STATES` is one
  of the few places that names the set explicitly).
- **JSON blobs**: stored as TEXT, parsed in the load method,
  shaped by a Pydantic model in the application layer.

---

## Common Mistakes

- **Holding a transaction across an `await`.** A long-running
  coroutine that opens a write transaction and then awaits
  another store call holds the SQLite write lock for the
  duration — every other writer queues behind it. The fix is
  to release the transaction before the await, re-acquire on
  the next call.
- **Adding a column without a default in the migration.** The
  first read after a deploy will see `None` for the new column
  on rows written before the migration. The load method must
  default it explicitly, and the test must cover the legacy
  row case.
- **Forgetting to bump `schema_version`**. The boot check will
  silently accept the new schema but the version assertion
  elsewhere will trip on the first new test. Bump it in the
  same migration.
- **Building a "JOIN" via N+1 application code.** If a feature
  needs a list view that joins two tables, the store method
  owns the join — the application layer never iterates rows
  in a loop and re-queries.
- **`is` comparisons on string status values.** A row's
  `status` is a `str`; `row.status is "Completed"` is
  always False. Use `==` and the project's enum-style status
  set, or use a typed `Literal` on the dataclass.
- **Logging a row's content at `INFO` in a recovery path.** A
  recovered conductor row can carry the full task prompt; log
  the row id, not the body. The audit log captures the body
  under the gated prompt-logging flag.
---

## Scenario: Durable Conductor Runner Leases

### 1. Scope / Trigger

- Trigger: changing Conductor orchestration state, `conductor_tasks` schema, startup recovery, or watchdog behavior.
- Conductor loops are in-memory coroutines, but their user-visible task state is durable. Any `running` Conductor row must include enough persisted lease data to distinguish a live runner from a stale database row after backend reload/crash.

### 2. Signatures

- DB table: `conductor_tasks`
- Lease columns:
  - `lease_owner TEXT`
  - `heartbeat_at TEXT`
  - `lease_expires_at TEXT`
- Store APIs:
  - `save_conductor_task(task: ConductorTask) -> None`
  - `load_conductor_task(task_id: str) -> ConductorTask | None`
  - `load_latest_conductor_task_for_issue(issue_id: str) -> ConductorTask | None`
  - `list_conductor_tasks(*, status: str | None = None) -> list[ConductorTask]`
- Recovery API:
  - `recover_orphaned_conductors(store, *, event_bus, current_owner, stale_after_s, recover_foreign_owner=False) -> int`
- Environment keys:
  - `CONDUCTOR_LEASE_TTL_S` default `180`
  - `CONDUCTOR_RECOVERY_INTERVAL_S` default `30`
  - `CONDUCTOR_RECOVERY_ENABLED` default enabled

### 3. Contracts

- A live `run_issue_conductor_loop` must set `lease_owner`, `heartbeat_at`, and `lease_expires_at` on the initial `ConductorTask`.
- A live loop must refresh the lease before persisted turns and phase transitions.
- `lease_owner` format is `pid:<pid>:<uuid>` and is process-local, not per task.
- Recovery scans only `status == "running"` conductor tasks.
- Recovery marks orphaned tasks as `status="stalled"` and `payload.phase="stalled"`, never as `failed`.
- Recovery must preserve `paused`, `done`, `failed`, and already `stalled` tasks.
- Recovery must persist an auditable reason in both `payload` and `result_json`.
- Recovery must emit the existing `conductor_status` event path via `transition_conductor_phase`.

### 4. Validation & Error Matrix

- `lease_expires_at <= now` -> mark `stalled` with reason `orphaned_conductor_runner`.
- No `lease_expires_at`, but `heartbeat_at`/`updated_at`/`created_at` older than `stale_after_s` -> mark `stalled`.
- Startup with `recover_foreign_owner=True` and `lease_owner` pid no longer exists -> mark `stalled` even if the stored expiry is still in the future.
- Startup with foreign owner pid alive and fresh lease -> keep `running`.
- `status` in `paused`, `done`, `failed`, or `stalled` -> do not modify.
- Store without `list_conductor_tasks` -> recovery returns `0` and does not crash startup.

### 5. Good/Base/Bad Cases

- Good: backend reload sees `running / awaiting_llm` with `lease_owner="pid:12345:..."`; pid `12345` no longer exists, so startup marks the row `stalled` and records previous phase/owner.
- Base: a currently running loop heartbeats every persisted turn/phase and remains `running`.
- Bad: a second-round `llm_request` is persisted, the backend reloads, and the row stays forever in `running / awaiting_llm` because there is no durable lease to recover.
- Bad: marking an orphaned Conductor as `failed`, which makes an infrastructure loss look like product/task failure.

### 6. Tests Required

- Regression: expired `running` Conductor becomes `stalled`.
- Regression: fresh `running` Conductor remains `running`.
- Regression: dead foreign owner on startup becomes `stalled`.
- Regression: live foreign owner with fresh lease remains `running`.
- Regression: `paused`, `done`, `failed`, and `stalled` rows are untouched.
- Loop test: `run_issue_conductor_loop` persists lease fields.
- Lifespan test: startup calls recovery and starts the periodic Conductor watchdog.

### 7. Wrong vs Correct

Wrong:

```python
task.status = "running"
await store.save_conductor_task(task)
```

Correct:

```python
now = datetime.now()
task.status = "running"
task.lease_owner = get_conductor_lease_owner()
task.heartbeat_at = now
task.lease_expires_at = now + timedelta(seconds=get_conductor_lease_ttl_s())
await store.save_conductor_task(task)
```

---

## Scenario: Review-Only Self-Improvement Proposal Ledger

### 1. Scope / Trigger

- Trigger: changing issue terminal sealing, self-improvement extraction,
  proposal review APIs, or the `self_improvement_proposals` schema.
- The extraction, review, and apply-plan portions of the first
  self-improvement loop are intentionally review-only: they may create durable
  proposals from issue evidence and preview candidate changes, but they must
  not silently mutate `.trellis/spec/`, prompts, policies, project memory,
  tools, or code.
- A separate reviewed apply endpoint may mutate project memory only when the
  caller presents the hash of the exact dry-run candidate content it reviewed.
  It must not apply higher-risk target kinds directly.
- Proposal extraction runs from the Conductor terminal seal and is best-effort;
  an extraction/store problem must not change a completed issue into a failed
  issue.

### 2. Signatures

- DB table: `self_improvement_proposals`
- Required columns:
  - `id TEXT PRIMARY KEY`
  - `project_id TEXT NOT NULL`
  - `issue_id TEXT NOT NULL`
  - `target_kind TEXT NOT NULL`
  - `title TEXT NOT NULL`
  - `recommendation TEXT NOT NULL`
  - `evidence_json TEXT NOT NULL DEFAULT '[]'`
  - `severity TEXT NOT NULL DEFAULT 'info'`
  - `confidence REAL NOT NULL DEFAULT 0`
  - `status TEXT NOT NULL DEFAULT 'proposed'`
  - `fingerprint TEXT NOT NULL UNIQUE`
  - `created_at TEXT`
  - `updated_at TEXT`
- DB table: `self_improvement_application_events`
- Required columns:
  - `id TEXT PRIMARY KEY`
  - `proposal_id TEXT NOT NULL`
  - `project_id TEXT NOT NULL`
  - `issue_id TEXT NOT NULL`
  - `target_kind TEXT NOT NULL`
  - `action TEXT NOT NULL`
  - `status TEXT NOT NULL`
  - `path TEXT`
  - `content_sha256 TEXT`
  - `result_json TEXT NOT NULL DEFAULT '{}'`
  - `error TEXT`
  - `created_at TEXT`
- Store APIs:
  - `save_self_improvement_proposal(proposal: SelfImprovementProposal) -> None`
  - `list_self_improvement_proposals(project_id: str | None = None, issue_id: str | None = None, status: str | None = None, limit: int | None = None) -> list[SelfImprovementProposal]`
  - `load_self_improvement_proposal(proposal_id: str) -> SelfImprovementProposal | None`
  - `update_self_improvement_proposal_status(proposal_id: str, status: str) -> SelfImprovementProposal | None`
  - `save_self_improvement_application_event(event: SelfImprovementApplicationEvent) -> None`
  - `list_self_improvement_application_events(project_id: str | None = None, proposal_id: str | None = None, limit: int | None = None) -> list[SelfImprovementApplicationEvent]`
- Service APIs:
  - `extract_self_improvement_proposals(issue: CodexIssue, store) -> list[SelfImprovementProposal]`
  - `record_issue_self_improvement(issue: CodexIssue, store) -> list[SelfImprovementProposal]`
  - `rollback_project_memory_proposal(project_repo_path: str | None, proposal: SelfImprovementProposal) -> SelfImprovementRollbackResult`
- Read API:
  - `GET /api/codex/projects/{project_id}/self-improvement-proposals`
  - Optional filters: `issue_id`, `status`, `limit`
  - `GET /api/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/applications`
  - Optional filter: `limit`
- Review API:
  - `PATCH /api/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}`
  - Request body: `{"status": "proposed" | "accepted" | "rejected" | "applied"}`
  - Response body: the same proposal object shape used inside the list endpoint's
    `proposals[]` array.
- Apply-plan API:
  - `POST /api/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/apply-plan`
  - Response body: `{proposal, plan}` where `proposal` is the same proposal
    object shape and `plan` is a dry-run application plan.
- Reviewed project-memory apply API:
  - `POST /api/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/apply`
  - Request body: `{"content_sha256": "<64 lowercase hex sha256>"}`
  - Response body: `{proposal, application}` where `proposal` is the same
    proposal object shape after status update and `application` contains
    `path`, `content_sha256`, `already_present`, and `bytes_written`.
- Reviewed project-memory rollback API:
  - `POST /api/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/rollback`
  - Response body: `{proposal, rollback}` where `proposal` is the same proposal
    object shape after status update and `rollback` contains `path`,
    `content_sha256`, `already_absent`, and `bytes_written`.

### 3. Contracts

- `fingerprint` is the idempotence key. Saving the same fingerprint again must
  update the existing row rather than append an unbounded duplicate.
- Valid `target_kind` values are string-based storage contracts:
  `project_memory`, `code_spec`, `conductor_policy`, `runtime_tooling`,
  `benchmark_eval`.
- Valid `status` values are string-based storage contracts: `proposed`,
  `accepted`, `rejected`, `applied`.
- `evidence_json` stores a JSON list of evidence pointers/snippets. The API
  parses it into `evidence`; malformed or non-list evidence returns `[]` rather
  than failing the endpoint.
- Review status transitions are conservative:
  - `proposed -> accepted`
  - `proposed -> rejected`
  - `accepted -> applied`
  - repeating the current status is idempotent
  - reverting `rejected` or `applied`, and `rejected -> accepted`, are invalid.
- The review API is status-only. It updates only `status` and `updated_at`; it
  must not mutate team notes, `.trellis/spec/`, prompts, policies, tools,
  memory rows, or source code.
- The apply-plan API is also non-mutating. It may translate an accepted proposal
  into candidate change metadata, but it must not write files, update proposal
  status, append team notes, edit specs, change prompts/policies/tools, or
  create source-code patches directly.
- Apply plans are allowed only for `status == "accepted"`. The output is a
  preflight contract for a later reviewed task/PR, not the application itself.
- A `project_memory` apply plan may include an `append_markdown` candidate for
  `.agent-collab/team_notes.md`. Other target kinds must use a reviewed PR/task
  candidate such as `open_pr_task`, not a guessed direct file patch.
- The reviewed apply API is the only self-improvement endpoint in this slice
  allowed to write project memory. It is limited to `status == "accepted"` and
  `target_kind == "project_memory"`.
- The reviewed apply API must rebuild the current dry-run plan, find the single
  `append_markdown` candidate, compute a SHA-256 hash of that exact content,
  and compare it with the request's `content_sha256` before writing.
- Hash mismatch means the caller reviewed stale or different content. Return a
  conflict and do not write `team_notes.md` or mark the proposal applied.
- The reviewed apply API writes only the exact reviewed candidate content into
  `.agent-collab/team_notes.md`, using the candidate's
  `<!-- self-improvement-proposal:{proposal.id} -->` marker as the idempotence
  key. If the marker already exists while the proposal is still accepted, do
  not append a duplicate block; mark the proposal applied and return
  `already_present: true`.
- The reviewed apply API must record one `self_improvement_application_events`
  row after project/proposal resolution:
  - successful apply -> `action="apply"`, `status="succeeded"`, `path` and
    `content_sha256` from the service result, and `result_json` containing the
    application result metadata.
  - service rejection or repository write failure -> `action="apply"`,
    `status="failed"`, safe `error` text, and the reviewed request hash when
    available. Proposal status and file state must remain unchanged on failure.
- The applications list API is project-scoped. It must validate the project and
  proposal first, hide cross-project proposals as not found, then return events
  for that `project_id + proposal_id` in newest-first order.
- Rollback is limited to `status == "applied"` and `target_kind ==
  "project_memory"`.
- Rollback removes the block beginning with
  `<!-- self-improvement-proposal:{proposal.id} -->` from
  `.agent-collab/team_notes.md`, stops before the next self-improvement or issue
  marker, records a rollback event, and marks the proposal back to `accepted`.
- Rollback is idempotent when the marker block is already absent: return
  `already_absent: true`, record a succeeded rollback event, mark the proposal
  `accepted`, and do not fail.
- Failed rollback requests must record a failed rollback event after
  project/proposal resolution and must not change proposal status.
- Direct application of `code_spec`, `conductor_policy`, `runtime_tooling`, or
  `benchmark_eval` proposals is forbidden. These target kinds must remain
  reviewed PR/task flows until they have their own audited execution model.
- The review API is project-scoped. A proposal whose `project_id` differs from
  the path `project_id` is treated as not found rather than exposed.
- A completed capability issue with no task-level benchmark/evaluation evidence
  must create one review-only `benchmark_eval` proposal. The stable rule id is
  `missing_capability_eval_contract`, the severity is at least `medium`, and
  the evidence list includes a `codex_issue` pointer plus the relevant
  `conductor_task` pointers.
- Capability intent may be detected from issue title/description and conductor
  task payload/result text. Benchmark/evaluation evidence is detected only from
  task payload/result text; an issue asking for SWE-bench or evaluation work is
  not itself proof that a benchmark was run.
- Task evidence such as `benchmark_run`, `fixture_id`, `pass_at_1`, `pass@1`,
  calibration output, benchmark artifacts, or `backend/benchmark` references
  suppresses a redundant `benchmark_eval` proposal.
- The terminal seal order for done graphs is:
  1. persist graph status;
  2. call `record_project_memory(graph.id, store)`;
  3. call `record_issue_self_improvement(issue, store)`;
  4. persist terminal issue status.
- Self-improvement extraction is review-only. It writes proposal rows only.

### 4. Validation & Error Matrix

- `codex_store is None` on the read API -> HTTP `503`, detail
  `"SQLite store not available"`.
- Unknown `project_id` on the read API -> HTTP `404`, detail
  `"Project not found"`.
- `codex_store is None` on the review API -> HTTP `503`, detail
  `"SQLite store not available"`.
- Unknown `project_id` on the review API -> HTTP `404`, detail
  `"Project not found"`.
- Unknown or cross-project proposal on the review API -> HTTP `404`, detail
  `"Self-improvement proposal not found"`.
- Invalid review status transition -> HTTP `409`, detail starts with
  `"Invalid self-improvement proposal status transition"`.
- `codex_store is None` on the apply-plan API -> HTTP `503`, detail
  `"SQLite store not available"`.
- Unknown `project_id` on the apply-plan API -> HTTP `404`, detail
  `"Project not found"`.
- Unknown or cross-project proposal on the apply-plan API -> HTTP `404`, detail
  `"Self-improvement proposal not found"`.
- Apply-plan request for `proposed`, `rejected`, or `applied` proposal -> HTTP
  `409`, detail states that the proposal must be accepted.
- `codex_store is None` on the reviewed apply API -> HTTP `503`, detail
  `"SQLite store not available"`.
- Unknown `project_id` on the reviewed apply API -> HTTP `404`, detail
  `"Project not found"`.
- Unknown or cross-project proposal on the reviewed apply API -> HTTP `404`,
  detail `"Self-improvement proposal not found"`.
- Reviewed apply request for `proposed`, `rejected`, or `applied` proposal ->
  HTTP `409`, detail states that the proposal must be accepted.
- Reviewed apply request for non-`project_memory` target kind -> HTTP `409`,
  detail states that only project memory can be applied directly.
- Reviewed apply request with a mismatched `content_sha256` -> HTTP `409`, and
  the endpoint must not write project memory or update proposal status.
- Reviewed apply request whose project repo path is missing or cannot write
  `.agent-collab/team_notes.md` -> HTTP `500`, and the proposal must remain
  accepted.
- `codex_store is None` on the applications list API -> HTTP `503`, detail
  `"SQLite store not available"`.
- Unknown `project_id` on the applications list API -> HTTP `404`, detail
  `"Project not found"`.
- Unknown or cross-project proposal on the applications list API -> HTTP `404`,
  detail `"Self-improvement proposal not found"`.
- `limit < 1` or `limit > 100` on the applications list API -> FastAPI
  validation `422`.
- `codex_store is None` on the rollback API -> HTTP `503`, detail
  `"SQLite store not available"`.
- Unknown `project_id` on the rollback API -> HTTP `404`, detail
  `"Project not found"`.
- Unknown or cross-project proposal on the rollback API -> HTTP `404`, detail
  `"Self-improvement proposal not found"`.
- Rollback request for `proposed`, `accepted`, or `rejected` proposal -> HTTP
  `409`, detail states that the proposal must be applied; proposal status must
  remain unchanged.
- Rollback request for non-`project_memory` target kind -> HTTP `409`, detail
  states that only project memory can be rolled back directly; proposal status
  must remain unchanged.
- Rollback request whose project repo path is missing or cannot write
  `.agent-collab/team_notes.md` -> HTTP `500`, and the proposal status must
  remain applied.
- `limit < 1` or `limit > 100` on the read API -> FastAPI validation `422`.
- Duplicate `fingerprint` on save -> update existing row fields and keep one
  logical proposal.
- Completed capability issue without benchmark/evaluation task evidence -> save
  one `benchmark_eval` proposal with fingerprint
  `project_id|issue_id|benchmark_eval|missing_capability_eval_contract`.
- Capability issue whose task payload/result includes explicit benchmark or
  eval-run evidence -> do not save a redundant `benchmark_eval` proposal.
- Missing conductor/QA artifacts -> produce fewer or zero proposals, not an
  exception.
- Store write failure during terminal seal -> log warning and keep the graph
  and issue terminal status behavior.
- Malformed `evidence_json` during API serialization -> return `evidence: []`.

### 5. Good/Base/Bad Cases

- Good: QA evidence with `bugs_found` creates one `code_spec` proposal with a
  conductor-task evidence pointer and stable fingerprint.
- Good: a runtime traceback or stalled conductor task creates one
  `runtime_tooling` proposal and does not duplicate when extraction runs again.
- Good: a capability issue for SWE-bench/autonomy improvement with no benchmark
  run artifact creates one `benchmark_eval` proposal asking for a reviewed
  fixture/eval before repeating similar work.
- Good: a capability issue whose task result includes `benchmark_run` with a
  `fixture_id` and `pass_at_1` does not create a redundant benchmark-eval
  proposal.
- Good: an operator accepts a proposed `code_spec` lesson with the review API;
  the proposal status becomes `accepted`, and all recommendation/evidence fields
  remain unchanged.
- Good: when a non-memory proposal is applied through a separate reviewed
  change, the review API can record `applied` status only.
- Good: an accepted `project_memory` proposal returns a dry-run
  `.agent-collab/team_notes.md` append candidate, and the file remains unchanged.
- Good: a reviewed apply request for an accepted `project_memory` proposal with
  the candidate content hash appends exactly that markdown to
  `.agent-collab/team_notes.md` and then marks the proposal `applied`.
- Good: a reviewed apply request records a succeeded application event with the
  path, hash, and application result so operators can audit what changed.
- Good: a reviewed apply request that fails hash validation records a failed
  application event and leaves the proposal accepted.
- Good: a reviewed apply request for an accepted `project_memory` proposal whose
  marker is already present marks the proposal `applied` without appending a
  duplicate block.
- Good: an applied `project_memory` proposal rollback removes only the marked
  block, records a succeeded rollback event, and moves the proposal back to
  `accepted`.
- Good: rollback with an already-absent marker records `already_absent: true`
  and still moves the proposal back to `accepted`.
- Good: an accepted `code_spec` proposal returns an `open_pr_task` candidate so a
  later reviewed PR can edit the right spec with tests.
- Base: a clean trivial completed issue creates no proposal and no error.
- Bad: appending a new proposal row on every recovery/seal run for the same
  lesson.
- Bad: treating the phrase "SWE-bench" in the issue title as evidence that an
  evaluation actually ran.
- Bad: auto-editing `.trellis/spec/` or project memory from the extractor in
  the review-only slice.
- Bad: allowing `rejected -> accepted` through the status API without an audit
  model for resurrection.
- Bad: an apply-plan endpoint that writes `team_notes.md` or marks the proposal
  `applied` in the same request.
- Bad: a reviewed apply endpoint that writes project memory without validating
  the reviewed candidate content hash.
- Bad: a reviewed apply endpoint that applies `code_spec`, `conductor_policy`,
  `runtime_tooling`, or `benchmark_eval` by writing files directly.
- Bad: mutating `team_notes.md` or proposal status without an application event
  row; this breaks operational auditability.
- Bad: rollback deleting all of `team_notes.md` or removing adjacent proposal
  blocks instead of only the addressed marker block.
- Bad: rollback failure reverting an `applied` proposal to `accepted`; failures
  must preserve status.
- Bad: returning a direct `patch_file` candidate for `code_spec`,
  `conductor_policy`, `runtime_tooling`, or `benchmark_eval` before a reviewed
  implementation task exists.
- Bad: allowing proposal extraction failure to prevent `issue.status =
  "completed"` after a done graph.

### 6. Tests Required

- Store parity: async and sync stores save/list/filter proposals and dedupe by
  fingerprint.
- Store parity: async and sync stores save/list/filter application events by
  project and proposal, preserve `result_json`/`error`, and return newest-first
  order with `limit`.
- Store parity: async and sync stores load proposals by id and status-update
  rows while preserving all non-status fields and advancing `updated_at`.
- Extraction: QA failure creates a `code_spec` proposal with evidence.
- Extraction: runtime/conductor failure creates a `runtime_tooling` proposal.
- Extraction: completed capability issue without benchmark/evaluation task
  evidence creates one `benchmark_eval` proposal with issue/task evidence.
- Extraction: capability issue with explicit benchmark/evaluation task evidence
  does not create a redundant `benchmark_eval` proposal.
- Extraction: clean issue creates no proposals.
- Extraction: duplicate rule matches save once per issue/rule fingerprint.
- Seal: done graph calls project memory and then self-improvement extraction.
- Seal: self-improvement failure does not block graph/issue terminal status.
- API: project proposals endpoint returns stable JSON, parses `evidence_json`,
  and respects `issue_id`, `status`, and `limit`.
- API: review endpoint covers `proposed -> accepted`, `proposed -> rejected`,
  `accepted -> applied`, idempotent repeats, `409` invalid transitions, `404`
  unknown/cross-project proposals, and `503` store unavailable.
- Apply-plan: service tests cover `project_memory` append candidates and
  non-memory `open_pr_task` candidates.
- Apply-plan: service tests cover `benchmark_eval` returning an `open_pr_task`
  candidate and never a direct `patch_file` candidate.
- API: apply-plan endpoint covers accepted memory/non-memory proposals, `409`
  non-accepted statuses, `404` unknown/cross-project proposals, `503` store
  unavailable, and no proposal status mutation.
- Reviewed apply: service tests cover candidate content hashing, successful
  project-memory append, marker idempotence, hash mismatch, unsupported target
  kind, non-accepted status, and unavailable repo path.
- API: reviewed apply endpoint covers accepted project-memory append and
  `applied` status update, marker idempotence, `409` hash mismatch,
  non-memory target kinds and non-accepted statuses, `404` unknown/cross-project
  proposals, `503` store unavailable, `500` unavailable repo path, and no
  mutation on failed requests.
- API: reviewed apply endpoint records succeeded and failed application events
  after project/proposal resolution.
- API: applications list endpoint covers newest-first event JSON, `result_json`
  parsing, `404` unknown/cross-project proposals, `503` store unavailable, and
  `422` invalid limits.
- Rollback service: tests cover successful marker-block removal, marker-absent
  idempotence, unsupported target kind, non-applied status, and unavailable repo
  path.
- API: rollback endpoint covers successful project-memory removal and accepted
  status update, marker-absent idempotence, `409` non-memory target kinds and
  non-applied statuses, `404` unknown/cross-project proposals, `503` store
  unavailable, `500` unavailable repo path, failed rollback event recording,
  and no status mutation on failed requests.

### 7. Wrong vs Correct

Wrong:

```python
if graph_status == "done":
    await record_issue_self_improvement(issue, store)
issue.status = "completed"
await store.save_codex_issue(issue)
```

Correct:

```python
if graph_status == "done":
    await record_project_memory(graph.id, store)
    try:
        await record_issue_self_improvement(issue, store)
    except Exception as exc:
        logging.getLogger(__name__).warning("self_improvement extraction failed: %s", exc)
issue.status = "completed"
await store.save_codex_issue(issue)
```

Wrong:

```python
proposal.status = request.status
await store.save_self_improvement_proposal(proposal)
await record_project_memory(proposal.issue_id, store)  # review endpoint auto-applies
```

Correct:

```python
if not _is_self_improvement_proposal_status_transition_allowed(proposal.status, request.status):
    raise HTTPException(status_code=409, detail="Invalid self-improvement proposal status transition")
updated = await store.update_self_improvement_proposal_status(proposal.id, request.status)
return _self_improvement_proposal_to_dict(updated)
```

Wrong:

```python
if proposal.status == "accepted":
    Path(repo_path, ".agent-collab/team_notes.md").write_text(proposal.recommendation)
    await store.update_self_improvement_proposal_status(proposal.id, "applied")
```

Correct:

```python
if proposal.status != "accepted":
    raise HTTPException(status_code=409, detail="Self-improvement proposal must be accepted")
return {
    "proposal": _self_improvement_proposal_to_dict(proposal),
    "plan": build_self_improvement_apply_plan(proposal),  # dry-run metadata only
}
```

Wrong:

```python
if proposal.status == "accepted" and proposal.target_kind == "project_memory":
    Path(project.repo_path, ".agent-collab/team_notes.md").write_text(
        proposal.recommendation,
        encoding="utf-8",
    )
    await store.update_self_improvement_proposal_status(proposal.id, "applied")
```

Correct:

```python
result = apply_project_memory_proposal(
    project_repo_path=project.repo_path,
    proposal=proposal,
    reviewed_content_sha256=request.content_sha256,
)
updated = await store.update_self_improvement_proposal_status(proposal.id, "applied")
return {
    "proposal": _self_improvement_proposal_to_dict(updated),
    "application": result.to_dict(),
}
```

Wrong:

```python
result = rollback_project_memory_proposal(project_repo_path=project.repo_path, proposal=proposal)
updated = await store.update_self_improvement_proposal_status(proposal.id, "accepted")
return {"proposal": proposal_to_dict(updated), "rollback": result.to_dict()}
```

Correct:

```python
try:
    result = rollback_project_memory_proposal(project_repo_path=project.repo_path, proposal=proposal)
except SelfImprovementApplyError as exc:
    await record_application_event(proposal, action="rollback", status="failed", error=exc.message)
    raise
updated = await store.update_self_improvement_proposal_status(proposal.id, "accepted")
await record_application_event(
    updated,
    action="rollback",
    status="succeeded",
    path=result.path,
    content_sha256=result.content_sha256,
    result=result.to_dict(),
)
return {"proposal": proposal_to_dict(updated), "rollback": result.to_dict()}
```
