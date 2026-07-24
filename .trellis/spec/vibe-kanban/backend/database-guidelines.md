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
- **Assuming a fallback store method is always async.** Most
  production paths use `AsyncSQLiteStore`, but legacy/session
  services can be wired with the sync `SQLiteStore` in tests or
  fallback boot paths. A service that intentionally accepts both
  must route store method results through a small `_maybe_await`
  helper instead of blindly writing `await store.save_foo(...)`.
  Services that only support async stores should type that
  dependency narrowly and fail at wiring time.
- **`is` comparisons on string status values.** A row's
  `status` is a `str`; `row.status is "Completed"` is
  always False. Use `==` and the project's enum-style status
  set, or use a typed `Literal` on the dataclass.
- **Changing SQLite row column checks to `key in row`.**
  `sqlite3.Row` and `aiosqlite.Row` membership does not mean
  "column name exists" in the same way a dict does. Legacy-row
  compatibility code that needs to ask whether a selected column
  exists must use the store-local `_row_has_key(row, "column")`
  helper, which intentionally checks `row.keys()` in one
  documented place.

  Wrong:

  ```python
  # This can check row values rather than column names.
  if "workflow_node_id" in row:
      value = row["workflow_node_id"]
  ```

  Correct:

  ```python
  if _row_has_key(row, "workflow_node_id"):
      value = row["workflow_node_id"]
  ```

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
- The first self-improvement loop is intentionally review-only: it may create
  durable proposals from issue evidence, but it must not silently mutate
  `.trellis/spec/`, prompts, policies, project memory, tools, or code.
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
- Store APIs:
  - `save_self_improvement_proposal(proposal: SelfImprovementProposal) -> None`
  - `list_self_improvement_proposals(project_id: str | None = None, issue_id: str | None = None, status: str | None = None, limit: int | None = None) -> list[SelfImprovementProposal]`
- Service APIs:
  - `extract_self_improvement_proposals(issue: CodexIssue, store) -> list[SelfImprovementProposal]`
  - `record_issue_self_improvement(issue: CodexIssue, store) -> list[SelfImprovementProposal]`
- Read API:
  - `GET /api/codex/projects/{project_id}/self-improvement-proposals`
  - Optional filters: `issue_id`, `status`, `limit`

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
- `limit < 1` or `limit > 100` on the read API -> FastAPI validation `422`.
- Duplicate `fingerprint` on save -> update existing row fields and keep one
  logical proposal.
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
- Base: a clean trivial completed issue creates no proposal and no error.
- Bad: appending a new proposal row on every recovery/seal run for the same
  lesson.
- Bad: auto-editing `.trellis/spec/` or project memory from the extractor in
  the review-only slice.
- Bad: allowing proposal extraction failure to prevent `issue.status =
  "completed"` after a done graph.

### 6. Tests Required

- Store parity: async and sync stores save/list/filter proposals and dedupe by
  fingerprint.
- Extraction: QA failure creates a `code_spec` proposal with evidence.
- Extraction: runtime/conductor failure creates a `runtime_tooling` proposal.
- Extraction: clean issue creates no proposals.
- Extraction: duplicate rule matches save once per issue/rule fingerprint.
- Seal: done graph calls project memory and then self-improvement extraction.
- Seal: self-improvement failure does not block graph/issue terminal status.
- API: project proposals endpoint returns stable JSON, parses `evidence_json`,
  and respects `issue_id`, `status`, and `limit`.

### 7. Wrong vs Correct

Wrong:

```python
if graph_status == "done":
    await record_issue_self_improvement(issue, store)
issue.status = "completed"
await store.save_codex_issue(issue)
```

---

## Scenario: Project-Current Structured Prototype Recovery

### 1. Scope / Trigger

- Trigger: changing structured-prototype Studio bootstrap, project document
  selection, requirements generation recovery, candidate acceptance, or the
  frontend's generation-to-Studio transition.
- The server owns current document/job identity. Browser storage is never the
  authority for which draft or generation job belongs to a project.

### 2. Signatures

- Current draft:
  `GET /api/projects/{project_id}/structured-prototype-documents/current?clientRequestId={uuid}`
  -> `StructuredPrototypeDraftResponseV1 | null`.
- Current generation:
  `GET /api/projects/{project_id}/prototype-document-generation-jobs/current`
  -> `GenerationJobResponseV1 | null`.
- Store reads:
  `load_current_project_document(project_id)` and
  `load_latest_project_generation_job(project_id)`.
- Candidate acceptance remains:
  `POST /api/prototype-document-generation-jobs/{job_id}/accept`.

### 3. Contracts

- Current document selection joins the document's referenced active draft and
  orders by draft update time, document creation time, then SQLite row identity.
  It never trusts a browser-supplied draft ID.
- A current corrupt draft remains an error. The read must not skip it and fall
  back to an older healthy document, because that would hide corruption.
- Current generation returns the latest durable job, including failed or
  accepted jobs, so refresh can reconstruct the exact review/recovery state.
- Empty project state returns JSON `null`; the frontend then offers requirements
  generation. It does not create a seed document behind the user's back.
- Candidate acceptance atomically creates the project document, active draft,
  checkpoint, object references, and terminal evidence before Studio recovery.
- Current draft recovery runs the normal checkpoint plus command-tail replay and
  returns a fresh recovery operation/correlation identity.

### 4. Validation & Error Matrix

- Invalid `clientRequestId` -> `422 client_request_id_invalid`; no recovery
  operation is created.
- No project document/job -> `200 null`.
- Referenced active draft missing -> fail with `active_draft_missing`; do not
  create a replacement draft.
- Corrupt checkpoint, missing sequence, or hash mismatch -> normal fail-closed
  recovery error; do not select an older document.
- Candidate/job hashes change before acceptance -> `409`; no document rows are
  partially inserted.

### 5. Good/Base/Bad Cases

- Good: a fresh browser opens Studio and recovers the accepted draft using only
  `project_id` plus a new request UUID.
- Base: a project without a structured document or generation job receives two
  `null` reads and sees the requirements form.
- Good: refresh during planning or page generation reloads the latest job and
  its persisted item/task/process evidence.
- Bad: read `localStorage["draft-id"]` and treat it as project ownership.
- Bad: call a fixture document factory when current-draft recovery returns
  `null`.

### 6. Tests Required

- Store/service/API: empty project returns `null`; a created or accepted
  document returns its active draft through deterministic replay.
- API: current generation returns the same job ID and full blueprint/progress
  snapshot as the direct job endpoint.
- Conflict/corruption: no fallback document or partial accept is created.
- Frontend API: project IDs are URL-encoded and current draft recovery carries
  `clientRequestId`.
- Browser: direct Studio navigation restores an accepted project without manual
  local-storage seeding; a document-free project renders the requirements form.

### 7. Wrong vs Correct

Wrong:

```typescript
const draftId = localStorage.getItem(`project:${projectId}:draft`);
const draft = draftId ? await getDraft(draftId) : createFixtureDocument();
```

Correct:

```typescript
const draft = await getCurrentStructuredPrototypeDraft(projectId, crypto.randomUUID());
if (!draft) return showRequirementsGeneration();
return recoverStudioRuntime(draft);
```

---

## Scenario: Durable Structured Prototype Operation Outcome Lookup

### 1. Scope / Trigger

- Trigger: changing structured-prototype mutation idempotency, operation
  persistence, request timeout recovery, or the operation-outcome API.
- A lost HTTP response is ambiguous. The durable operation row is the only
  authority for whether that exact mutation is unknown, active, or terminal.

### 2. Signatures

- HTTP:
  `GET /api/projects/{project_id}/structured-prototype-operations/outcome?operationKind={kind}&clientRequestId={uuid}`
  -> `StructuredPrototypeOperationOutcomeResponseV1`.
- Service:
  `get_operation_outcome(project_id, operation_kind, client_request_id) -> PrototypeOperation`.
- Store:
  `load_operation_by_request(project_id, operation_kind, client_request_id) -> PrototypeOperation | None`.
- Lookup identity is the full `(project_id, operation_kind, client_request_id)`
  tuple; no request creates a new operation row.

### 3. Contracts

- Return the persisted operation whether its status is `queued`, `running`,
  `succeeded`, `failed`, `interrupted`, or `cancelled`; do not collapse active
  states into unknown.
- `terminal` is derived only from
  `succeeded | failed | interrupted | cancelled`. It is false for `queued` and
  `running`.
- The response exposes operation/resource identity, correlation and parent IDs,
  attempt, phase, request/config/result/failure evidence hashes, error code, and
  lifecycle timestamps from the same durable row.
- The lookup is read-only and idempotent. It does not advance phase, rewrite
  evidence, create recovery operations, or substitute another operation with a
  similar resource ID.
- Project, operation kind, and request identity are all required so one project
  or mutation kind cannot observe another operation accidentally.
- Operation lifecycle writers remain responsible for atomic status/evidence
  transitions. The outcome endpoint reports those facts without repairing
  incomplete rows.

### 4. Validation & Error Matrix

- Invalid `clientRequestId` -> `422 client_request_id_invalid`; no lookup
  fallback and no operation creation.
- Unsupported `operationKind` -> request validation error.
- Exact tuple not found -> `404 operation_outcome_unknown`, retryable, with no
  fabricated pending or terminal outcome.
- Exact tuple found in `queued` or `running` -> `200`, `terminal=false`.
- Exact tuple found in a terminal status -> `200`, `terminal=true`, preserving
  its success or failure evidence.
- Persisted row violates domain lifecycle invariants -> fail closed through the
  normal typed boundary; do not synthesize missing hashes or timestamps.

### 5. Good/Base/Bad Cases

- Good: a timed-out command request first reads `running`, later reads
  `succeeded`, and both responses carry the same operation and correlation IDs.
- Base: a request identity that has not reached persistence returns retryable
  `operation_outcome_unknown`.
- Good: a failed operation returns its failure evidence hash and error code so
  the frontend can surface an observable terminal failure.
- Bad: query only by `client_request_id` and return an operation from another
  project or kind.
- Bad: create a synthetic failed operation when the lookup misses.
- Bad: return `404` for a known running operation because it has no result
  manifest yet.

### 6. Tests Required

- Store/service: queued, running, succeeded, and failed rows round-trip by the
  exact composite request identity.
- Service: invalid UUID is rejected before the store read; unknown identity
  raises `operation_outcome_unknown`.
- API: active and terminal responses preserve every identity, evidence, attempt,
  phase, and lifecycle field with the correct `terminal` value.
- API isolation: the same request UUID under another project or operation kind
  remains unknown.
- Frontend integration: unknown and non-terminal outcomes retain the pending
  operation; terminal outcome still requires authoritative resource recovery.

### 7. Wrong vs Correct

Wrong:

```python
operation = await store.load_operation_by_client_request_id(client_request_id)
if operation is None or operation.result_manifest_hash is None:
    raise StructuredPrototypeServiceError("operation_outcome_unknown", "unknown")
```

Correct:

```python
operation = await store.load_operation_by_request(
    project_id,
    operation_kind,
    client_request_id,
)
if operation is None:
    raise StructuredPrototypeServiceError(
        "operation_outcome_unknown",
        "structured prototype operation outcome is not recorded",
    )
return operation
```

---

## Scenario: Structured Prototype Restart Operation Reconciliation

### 1. Scope / Trigger

- Trigger: changing structured-prototype operation lifecycle persistence,
  backend startup order, or a workflow-specific restart recovery path.
- A backend process loss must not leave an ordinary `queued` or `running`
  operation permanently holding the project-wide `prototype_busy` gate.

### 2. Signatures

- Store:
  `recover_interrupted_non_generation_operations(recovered_at: datetime) -> int`.
- Service:
  `recover_interrupted_non_generation_operations() -> int`.
- Recovered operation terminal contract:
  `status="interrupted"`, `phase="service_restart_recovery"`, and
  `error_code="service_restart"`.
- Startup order:
  publication recovery -> AI run recovery -> generation job recovery -> pending
  project deletion recovery -> ordinary operation reconciliation.

### 3. Contracts

- One SQLite `BEGIN IMMEDIATE` transaction reconciles all ordinary active
  operations and verifies that none remain before commit.
- Generic reconciliation excludes the complete recursive operation tree rooted
  at a top-level `generation_job` resource because the generation recovery
  service owns that lifecycle. An active `generation_job` or `generation_item`
  outside that tree is corrupt ownership, not another exclusion.
- A queued operation receives an auditable `running` transition before its
  `interrupted` transition. Reuse a valid active running step; otherwise create
  the recovery step with a deterministic UUIDv5 identity.
- The terminal operation, step, and `operation_interrupted` event share the
  failure evidence hash and `service_restart` error code. Existing operation,
  correlation, request, attempt, and manifest identities remain unchanged.
- Recovery validates canonical UUIDs, lifecycle timestamps, active-step
  cardinality, terminal evidence absence, and a gap-free event sequence.
  Cancellation, commit failure, or invalid durable state rolls back the entire
  reconciliation and aborts startup.
- Queuing the SQLite commit is the transaction point of no return. Cancellation,
  including repeated cancellation, must remain shielded until the commit worker
  reports its real result. A successful commit is never followed by rollback;
  a reported commit failure is rolled back before the error escapes.
- Workflow-specific recovery runs first so it can persist its richer domain
  outcome. Generic recovery only closes operations those owners did not consume.
- Generic recovery excludes active `delete_project_prototype` operations because
  deletion recovery owns their resumable filesystem/database saga. The final
  verification query must apply the same exclusion as the selection query.
- If the structured-prototype store and ordinary service are available but the
  generation recovery service is not, startup fails with
  `generation_recovery_unavailable` before the generic pass. It must not serve
  requests while a generation tree could remain active and excluded.

### 4. Validation & Error Matrix

- Ordinary `queued` operation -> `queued -> running -> interrupted` with a
  `service_restart_recovery` step.
- Ordinary `running` operation with one valid running step -> reuse that step
  and append `operation_interrupted`.
- Top-level generation root and every recursive child -> generic recovery leaves
  it unchanged for the generation owner.
- Active `generation_job`/`generation_item` outside the owned recursive tree ->
  `operation_recovery_corrupt`; roll back and abort startup.
- Non-canonical operation/step UUID, terminal evidence on an active row,
  impossible timestamp, multiple active steps, missing queued event, or event
  number gap ->
  `operation_recovery_corrupt`; roll back and abort startup.
- Any ordinary active operation remains after the scan ->
  `operation_recovery_incomplete`; roll back and abort startup.
- Store recovery error -> preserve the typed error code through the service and
  abort backend startup; never log-and-continue past a broken concurrency gate.
- Generation recovery service unavailable while structured persistence is
  active -> `generation_recovery_unavailable`; abort startup before generic
  reconciliation.
- Cancellation before commit is queued -> roll back and propagate cancellation.
- Cancellation while commit is pending -> wait through repeated cancellation;
  commit success persists the reconciliation without rollback, while commit
  failure rolls back and propagates the database error.

### 5. Good/Base/Bad Cases

- Good: a process dies during `apply_command_batch`; the next startup records
  `service_restart`, deletion no longer sees `prototype_busy`, and a fresh
  delete request succeeds.
- Base: no ordinary active operation exists; recovery returns `0` without
  writing rows.
- Good: a generation root with nested `create_document` work is handled by the
  generation recovery service before the generic pass.
- Bad: age-filter active rows and leave a recent orphan blocking the project.
- Bad: catch reconciliation failure and start serving requests with an unknown
  operation ledger.
- Bad: exclude only the generation root while interrupting its recursive child.
- Bad: exclude an orphan generation-kind row by label even though no generation
  root owns it.

### 6. Tests Required

- Store/service regression: a running ordinary operation blocks deletion,
  startup reconciliation interrupts it with complete observability, and a new
  deletion succeeds.
- Queued regression: event states are exactly
  `queued`, `running`, `interrupted`; a second recovery is idempotent.
- Ownership regression: generation root, child, and grandchild remain active for
  the generation owner.
- Corruption regression: a generation-kind row outside the tree, invalid active
  lifecycle evidence, or a gapped event history rolls back all transitions and
  raises the typed recovery error.
- Transaction regression: cancellation during a transition, repeated
  cancellation while commit is pending, and commit failure leave the documented
  durable state with no open transaction; a later recovery starts normally.
- Lifespan regression: workflow-specific recovery precedes generic operation
  reconciliation, including deletion before the generic pass; unavailable
  generation recovery and a typed recovery failure both abort startup.

### 7. Wrong vs Correct

Wrong:

```sql
UPDATE prototype_operations
SET status = 'interrupted'
WHERE status IN ('queued', 'running')
  AND operation_kind != 'generation_job';
```

Correct:

```sql
WITH RECURSIVE generation_tree(id) AS (
  SELECT id FROM prototype_operations
  WHERE operation_kind = 'generation_job'
    AND resource_kind = 'generation_job'
    AND parent_operation_id IS NULL
  UNION
  SELECT child.id
  FROM prototype_operations AS child
  JOIN generation_tree AS parent ON child.parent_operation_id = parent.id
)
SELECT operation.id
FROM prototype_operations AS operation
WHERE operation.status IN ('queued', 'running')
  AND NOT EXISTS (
    SELECT 1 FROM generation_tree WHERE generation_tree.id = operation.id
  );
```

The selected set is then validated before mutation: a generation-kind row in
this set has no valid owner and raises `operation_recovery_corrupt`.

---

## Scenario: Recoverable Physical Project Structured Prototype Deletion

### 1. Scope / Trigger

- Trigger: changing project-level structured prototype deletion, generation job
  lifecycle states, managed object/render storage, generation snapshot refs,
  operation recovery, or the Studio/generation delete controls.
- SQLite and the filesystem cannot share one transaction. The durable deletion
  operation therefore owns a resumable saga and must not report success until
  database rows and physical prototype content are both gone.

### 2. Signatures

- HTTP:
  `DELETE /api/projects/{project_id}/structured-prototype-documents?clientRequestId={uuid}`
  -> `{ contractVersion: 1, operationId, correlationId, deleted: true }`.
- Service:
  `delete_project_prototype(project_id, client_request_id) -> DeleteStructuredPrototypeResult`.
- Startup service:
  `recover_pending_project_prototype_deletions() -> int`.
- Store prepare:
  `prepare_project_prototype_deletion(project_id, deletion_operation_id) -> PrototypeProjectDeletionCounts`.
- Managed storage:
  `purge_project_store(project_id, deletion_operation_id) -> None`.
- Generation resource cleaner:
  `purge_generation_resources(project_id) -> None`.
- Store finalize:
  `finalize_project_prototype_deletion(project_id, deletion_operation_id, completed_operation, completion_step, completion_event, replay_descriptor, replay_reference) -> None`.
- Evidence kind: `project_prototype_deleted`; operation kind:
  `delete_project_prototype`.

### 3. Contracts

- The prepare `BEGIN IMMEDIATE` transaction removes the project's documents,
  drafts, checkpoints, command batches, revisions, publications/render rows,
  runtime sessions/events/checkpoints, AI threads/messages/edit runs, generation
  jobs/runs/items, every object reference, and every prior operation. It retains
  only the current running deletion operation/step/events and the project's
  object descriptors.
- A queued/running deletion operation is the project tombstone. Store-level
  operation creation rejects every other prototype mutation with
  `prototype_busy`, including requests from another backend process. A
  service-local lock only serializes duplicate in-process delete calls.
- Physical cleanup validates the managed root/project tree without following
  symlinks, atomically renames `prototype-store` to the deterministic
  `prototype-store-deleting-{operation_id}` tombstone, and removes its complete
  `objects`, `renders`, and `tmp` contents. Missing active/tombstone directories
  are successful idempotent retries; unsafe paths fail closed.
- Generation snapshot cleanup first observes the repo's
  `refs/agent-collab/prototype-generation/{job_id}` refs, then loads the global
  durable owner set, and CAS-deletes only observed unowned refs. A ref created
  after the first read cannot be swept, and an active job in any project remains
  protected.
- After physical cleanup, the service writes a new replay manifest for the
  current deletion. The finalize `BEGIN IMMEDIATE` transaction verifies that
  prepare is complete, deletes every old project object descriptor, registers
  only that replay object/reference, and transitions the deletion to
  `succeeded`.
- Final durable state contains one current deletion replay object and its
  operation evidence, but no historical prototype object, render bundle,
  object descriptor/reference, job, document, runtime, AI, publication, or old
  operation evidence.
- Reusing a successful `clientRequestId` returns the original result. Reusing a
  queued/running deletion request resumes prepare -> physical cleanup -> replay
  -> finalize rather than returning `operation_in_progress`.
- Cancellation must wait for an already-started physical cleanup thread to
  finish before releasing the caller. Cancellation or any post-prepare failure
  leaves the operation running so the same request or startup recovery can
  safely retry.
- Both prepare and finalize shield SQLite commit/rollback to a known outcome.
  A successful worker commit is never rolled back after caller cancellation.
- Startup owns active deletion recovery after generation recovery and before
  generic reconciliation. Generic recovery excludes deletion operations in both
  its scan and final remaining-count verification.
- A root `generation_job` operation may remain `running` while its durable job
  waits for the user. Only `awaiting_confirmation` and `ready` are quiescent and
  exempt from the busy gate. Planning, generating, assembling, validating, and
  preview rendering remain active and block deletion. A generation operation
  without a matching durable job is not quiescent and also blocks deletion.
- The frontend retains one delete request identity while the transport outcome
  is unknown, the operation is non-terminal, or successful resource recovery
  cannot yet be verified. It clears the pending operation and request identity
  after an authoritative terminal failure, and clears them after a successful
  deletion is verified. The last loaded prototype remains visible on any error.

### 4. Validation & Error Matrix

- Invalid `clientRequestId` -> `422 client_request_id_invalid`; no operation.
- Another queued/running non-quiescent project operation -> `409 prototype_busy`,
  retryable; no prototype row or object reference is removed.
- Unmatched queued/running `generation_job` or `generation_item` operation ->
  `409 prototype_busy`; SQL `NULL` from the left join must not exempt it.
- Deletion operation identity/evidence mismatch ->
  `prototype_delete_identity_mismatch`; refuse the transaction.
- SQLite failure before prepare commits -> `prototype_delete_failed`; roll back
  every mutation and persist terminal failed deletion evidence.
- Managed path/symlink error, object purge failure, Git ref list/CAS failure,
  replay write/read-back failure, or finalize failure after prepare ->
  `503 prototype_cleanup_pending`, retryable. Keep the deletion running and do
  not manufacture terminal failure evidence.
- Cancellation before prepare commits -> roll back and leave the deletion
  running; cancellation after cleanup starts -> wait for cleanup, then leave the
  deletion running.
- Running deletion with anything other than its one canonical running step ->
  `operation_observability_corrupt`; fail closed instead of guessing recovery.
- Same successful `clientRequestId` -> `200` with the original operation and
  correlation IDs.
- Authoritative `failed`, `interrupted`, or `cancelled` outcome -> clear the
  browser's pending delete/request identity before surfacing the error; the next
  user click creates a new UUID.
- Unknown outcome, active outcome, request deadline, or failed resource read ->
  retain the pending delete/request identity for reconciliation.

### 5. Good/Base/Bad Cases

- Good: a published draft with runtime, AI, render, and object history leaves
  only the current deletion replay file/descriptor/reference.
- Good: the process dies after prepare; startup resumes physical cleanup and
  finalize with the original operation/request identity.
- Good: a snapshot ref changes between observation and CAS deletion; cleanup
  remains pending and the newer ref is preserved.
- Base: deleting a project with no prototype and no managed directory succeeds
  as an observable no-op with one deletion replay receipt.
- Bad: treating every running generation root as active, which makes the visible
  delete control fail while the job is waiting for user confirmation.
- Bad: mark the operation succeeded after deleting only SQLite references while
  historical object and render files remain on disk.
- Bad: mark a post-prepare cleanup failure terminal; a new request could bypass
  the tombstone and race regeneration against unfinished deletion.
- Bad: recursively delete a path before rejecting symlinks or proving it remains
  under the managed root.
- Bad: clearing frontend state before the server confirms success.
- Bad: retaining a request identity after a known `prototype_busy` terminal
  failure, which makes every later click replay the same failed operation.

### 6. Tests Required

- API: deletion removes editable, published, and runtime reads; retry with the
  same request ID returns the identical response and terminal event sequence;
  `prototype_cleanup_pending` maps to retryable `503`.
- Store/service: an unrelated active operation returns retryable
  `prototype_busy` and leaves the document readable.
- Object store: project purge removes object, render, and tmp files, preserves
  another project, finishes an interrupted deterministic tombstone, is
  idempotent when absent, and refuses nested symlinks without touching targets.
- Saga: injected physical cleanup failure leaves one running delete tombstone,
  blocks new mutations, survives generic recovery, and completes through the
  deletion recovery owner using the same operation ID.
- Final state: exactly one object descriptor/reference/file remains for the
  current deletion replay; a later new delete removes the prior receipt and
  replaces it with its own.
- Git cleanup: refs are observed before owners, owned refs remain, unowned refs
  use expected-object CAS, and a changed ref yields cleanup pending.
- Generation regression: both `awaiting_confirmation` and `ready` jobs delete
  successfully and their root operations disappear with the job.
- Generation regression: unmatched active generation-job/item operations remain
  busy and cannot pass through the quiescent-job exemption.
- Frontend: project IDs are encoded, the request uses `DELETE`, both entry points
  reuse the identity while the outcome is ambiguous, clear it after a known
  terminal failure, and clear project state only after verified success.
- Lifespan: publication -> AI -> generation -> deletion -> generic recovery;
  typed deletion-recovery corruption aborts startup.

### 7. Wrong vs Correct

Wrong:

```python
await store.delete_project_prototype_rows(project_id)
completed = succeed_operation(operation)
await store.record_operation_transition(completed)
schedule_best_effort_object_gc(project_id)
```

Correct:

```python
await store.prepare_project_prototype_deletion(project_id, operation.id)
await purge_project_store_to_completion(project_id, operation.id)
await purge_unowned_generation_snapshot_refs(project_id)
replay = await write_current_deletion_replay(operation)
await store.finalize_project_prototype_deletion(
    project_id,
    operation.id,
    completed_operation=succeed_operation(operation, replay.content_hash),
    replay_descriptor=replay.descriptor,
    replay_reference=replay.reference,
)
```

The operation stays `running` between prepare and finalize. Only finalize may
make `deleted: true` durable and observable.

---

## Scenario: Structured Prototype Is the Only Editable Prototype System

### 1. Scope / Trigger

- Trigger: changing prototype persistence, project prototype routing, Claude UI
  Engineer execution, renderer output, or removing/adding a prototype API.
- The structured document, command journal, checkpoint, and object references are
  the only editable prototype state. Stored HTML prototypes are retired.

### 2. Signatures

- Project entry: `/projects/{projectId}/prototypes` redirects to
  `/projects/{projectId}/prototypes/studio`.
- Editable APIs use `/api/structured-prototype-*` and
  `/api/prototype-document-generation-jobs/*`; published previews use the
  structured publication APIs.
- Claude execution:
  `PrototypeUiEngineerRunner.execute_scoped_task(...) -> PrototypeUiEngineerScopedTaskResult`.
- Schema v12 drops, in dependency order:
  `prototype_generation_run_items`, `prototype_generation_runs`,
  `prototype_plan_items`, `prototype_plans`, `prototype_versions`, and
  `prototypes`.

### 3. Contracts

- Do not define legacy `Prototype`, `PrototypeVersion`, plan, evidence, or HTML
  generation domain models, services, routes, frontend types, or environment
  knobs.
- HTML is a deterministic publication/render output. It may exist under the
  structured render-artifact store, but it is never read back as editable state.
- The MCP catalog contains `project-startup`, `structured-prototype-ai`, and
  `structured-prototype-generation`; there is no `prototype-planning` server.
- The UI Engineer runner owns Claude availability checks, isolated worktree
  creation, task/process correlation, activity callbacks, source-integrity
  checks, and cleanup. It does not know an HTML manifest or staging path.
- Missing Claude runtime/catalog/CLI capability refuses the task. Source edits
  outside the runner baseline refuse the result after the process is cleaned up.

### 4. Validation & Error Matrix

- Existing database at schema <= 11 -> drop all six legacy tables at the
  version-12 migration; later additive migrations may advance the global schema
  version further. Do not migrate old HTML rows into structured documents.
- New database -> never create a legacy prototype table.
- Request to a retired prototype plan/version/stream endpoint -> route absent
  (`404`); do not add a compatibility handler.
- Claude runtime disabled, executor misconfigured, CLI unavailable, missing task
  result, or process mismatch -> `PrototypeUiEngineerRunnerError`; structured
  generation/edit service maps it to its typed failure contract.
- Claude modifies project source -> reject the result and clean the worktree.
- Published HTML missing or corrupt -> structured publication/render failure;
  never fall back to legacy HTML state.

### 5. Good/Base/Bad Cases

- Good: Studio applies domain commands, checkpoints the structured document,
  publishes a revision, and Renderer regenerates HTML from that revision.
- Base: a project with no document opens Studio requirements generation.
- Good: an old schema-11 database starts once, deletes legacy tables, and keeps
  unrelated project/session data.
- Bad: reintroduce `GET /api/prototypes/{id}` to read an HTML column.
- Bad: let Claude write `.agent-collab/prototype-staging/index.html` and treat it
  as successful prototype state.

### 6. Tests Required

- `test_legacy_prototype_schema_removal.py`: schema-11 rows/tables are removed,
  schema becomes 12, and a fresh database never creates those tables.
- `test_prototype_ui_engineer_runner.py`: launch-disabled and CLI-unavailable
  paths fail closed; task/process identity, MCP args, source rejection, and
  cleanup are asserted.
- MCP catalog tests assert exactly the three supported framework-owned servers.
- Structured AI/generation runtime tests use the runner Protocol and assert typed
  MCP submission identity.
- Frontend typecheck and node tests assert the Studio APIs remain available after
  legacy routes/types/components are removed.

### 7. Wrong vs Correct

Wrong:

```python
html = await store.load_prototype_version(prototype_id, version_no)
return {"html": html}
```

Correct:

```python
draft = await structured_store.load_active_draft(document_id)
publication = await structured_service.publish_draft(draft.id, expected_head_hash)
return publication
```

---

## Scenario: Repository-Autonomous Multi-Service Startup Configuration

### 1. Scope / Trigger

- Trigger: changing Operations Engineer startup analysis, project startup MCP,
  startup-service persistence, service process lifecycle APIs, or the Startup
  Config frontend contract.
- Repository-capable Claude owns evidence discovery. The backend owns identity,
  validation, persistence, command safety, and process lifecycle.

### 2. Signatures

- Analysis task: `POST /api/projects/{project_id}/script-task`; executor is
  Claude and task kind is `project_script_suggestion`.
- MCP: `POST /api/internal/project-startup-mcp` with a task/project-scoped
  `X-Project-Startup-Token`; required tool is `save_startup_config`.
- Read: `GET /api/projects/{project_id}/startup-config`.
- Per-service process APIs:
  `/projects/{project_id}/services/{service_id}/run/{start|stop|status|logs}`.
- Batch process APIs: `/projects/{project_id}/run/{start-all|stop-all}`.
- Tables: `project_startup_configs` and `project_startup_services`; service
  identity is the composite `(project_id, service_id)`.

### 3. Contracts

- Every newly saved startup service includes a required `readiness_probe` with
  `kind="http"`, a loopback-only URL, exact expected status, and one strict
  identity predicate: bounded `json_subset` or literal `text_contains`.
- Persist `readiness_probe` as JSON per service. Migrated legacy rows use
  `NULL`; loading them is allowed only so the API/UI can report
  `startup_config_invalid` and direct the user to re-analyze. They are not
  runnable.
- Address reachability, application readiness, and console-owned process
  liveness remain separate status dimensions. Any HTTP response proves address
  occupation; only a matcher pass at the expected status proves ready.
- Readiness responses are bounded to 64 KiB, redirects and environment proxies
  stay disabled, malformed/oversized/mismatched bodies fail closed, and all
  targets pass the existing loopback URL canonicalizer.
- An occupied address blocks automatic start with
  `service_address_occupied`, never with copy that claims the expected service
  is already running.
- Claude receives the repository root and output/safety contract, then uses its
  own Glob/Grep/Read tools. Do not serialize a fixed evidence-file whitelist or
  source excerpts into the prompt.
- `save_startup_config.services[]` contains `service_id`, `name`,
  `working_directory`, `setup_command`, `run_command`, `access_url`,
  `depends_on`, and `evidence[]` objects with separate `path` and `detail`.
- Commands are relative to `working_directory`; they do not repeat `cd`, shell
  operators, or grouping.
- The MCP save is authoritative. Claude final text is diagnostic only; a task
  without a successful MCP finalize fails.
- Store replacement of config metadata and all service rows is one transaction.
- Environment variables preserve existing user rows. Agent-supplied secret
  values are discarded rather than stored in plaintext.
- Start-all follows dependency order; stop-all follows reverse order. Process
  state and logs are keyed by `(project_id, service_id)`.
- Legacy `Project.setup_script` / `run_command` stay readable through the old
  panel when no startup-service rows exist; do not synthesize an unpersisted
  `legacy` service.

### 4. Validation & Error Matrix

- Missing/invalid MCP token -> `401`; no persistence.
- MCP unavailable -> analysis task creation returns `503` and fails closed.
- Missing MCP finalize -> Operations Engineer task becomes failed.
- Duplicate service ID, missing dependency, or dependency cycle -> MCP tool
  error; previous valid configuration remains unchanged.
- Working directory outside/missing from project -> MCP tool error.
- Evidence path outside/missing from project -> MCP tool error.
- Unsafe setup/run command -> MCP tool error with command-safety reason.
- External reachable service during start/start-all -> `409
  service_already_reachable`; start-all preflights every service before spawning.
- One service read/poll failure -> preserve other services' state and logs and
  expose the error in that service panel.

### 5. Good/Base/Bad Cases

- Good: Claude reads `backend/pom.xml` and `frontend/vite.config.ts`, saves
  backend plus frontend, and declares `frontend.depends_on=["backend"]`.
- Base: a single-service repository saves one service through the same MCP
  contract.
- Good: a legacy single-command project has no service rows and remains usable
  through the compatibility panel.
- Bad: adding another filename to `_CONTEXT_FILES` instead of letting Claude
  follow the repository dependency graph.
- Bad: parsing Claude's final JSON and overwriting a configuration already
  finalized through MCP.
- Bad: concatenating multiple long-running commands into one shell string.

### 6. Tests Required

- MCP unit: valid two-service payload persists both services and dependency.
- MCP negative: bad token, missing evidence, and dependency cycle do not replace
  prior configuration.
- Store integration: services, dependency JSON, evidence JSON, notes, and task
  identity round-trip through a migrated SQLite database.
- Role workflow: missing finalize fails; finalized result becomes task result
  with MCP authority recorded.
- Run manager: two services under one project run independently; stopping one
  leaves the other running and its logs intact.
- API: start-all dependency order, reverse stop order, environment refusal, and
  external reachable preflight.
- Frontend: typed startup-config/service APIs, all locale keys, independent
  service errors, and legacy panel fallback.
- Browser: a real `admin-demo` analysis displays backend and frontend service
  cards with evidence and dependency.

### 7. Wrong vs Correct

Wrong:

```python
repo_context = collect_project_script_context(project.repo_path)
raw = await llm(build_prompt(repo_context))
project.run_command = json.loads(raw)["run_command"]
```

Correct:

```python
session = startup_mcp.open_session(project=project, task_id=task.id)
await runner.start_task_run(
    task,
    command_args_override=["--mcp-config", session.claude_config(endpoint), "--strict-mcp-config"],
)
# Completion succeeds only after save_startup_config validates and commits.
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

---

## Scenario: Structured Prototype Navigator Command and Inverse Boundaries

### 1. Scope / Trigger

- Trigger: changing structured-prototype page CRUD, node rename, command-size
  validation, generated inverse commands, Undo/Redo, or journal replay.
- A small user request can legitimately produce a large inverse snapshot. The
  request boundary and the server-owned recovery payload are different trust
  boundaries and must not share one byte limit.

### 2. Signatures

- Execution:
  `execute_command_batch(document, batch, draft_id, client_request_id) -> CommandExecutionResultV1`.
- Forward limit: `PROTOTYPE_FORWARD_COMMAND_BATCH_MAX_BYTES = 256 * 1024`.
- Page commands: `addPage`, `duplicatePage`, `renamePage`, and `deletePage`.
- User rename: `updateNodeName { nodeId, name: CommandNodeName }`.
- Generated inverse rename:
  `restoreNodeName { nodeId, name: string[1..80] }`.
- Journal payloads remain
  `(commands_json, inverse_commands_json, operation_kind, target_batch_id)`.

### 3. Contracts

- Apply the 256 KiB limit only to the canonical serialized
  `DomainCommandBatchV1` submitted as a forward operation. Enforce it during
  execution, forward journal append, and forward replay validation.
- Never apply the forward-request limit to server-generated
  `InverseCommandBatchV1`, or to the inverse payload stored as the commands of
  an Undo/Redo entry. A page deletion may need to snapshot the complete page,
  nodes, rows, rules, navigation, and bindings.
- Every inverse command must reconstruct the exact accepted preimage, not only
  values that a new user command is allowed to create.
- `updateNodeName` requires a non-whitespace name. `restoreNodeName` accepts the
  complete persisted schema range, including a historical whitespace-only
  value, so repairing that value remains reversible.
- Generated page and node IDs stay deterministic under retry and replay, and
  `runtime.pageIds` stays exactly aligned with ordered `pages[].id` after every
  page command and inverse.

### 4. Validation & Error Matrix

- Canonical user forward batch exceeds 256 KiB ->
  `command_batch_too_large`; no document or journal mutation.
- Stored forward entry exceeds 256 KiB -> fail closed as corrupt history.
- Canonical generated inverse exceeds 256 KiB -> accept and persist; size alone
  is not corruption.
- `updateNodeName` is empty or whitespace-only -> contract rejection.
- `restoreNodeName` contains a historical whitespace-only schema value ->
  accept for exact Undo/Redo.
- Inverse payload is non-canonical, structurally invalid, or references a
  missing target -> typed inverse/replay corruption error.

### 5. Good/Base/Bad Cases

- Good: deleting a large page stores a large `restorePageProjection` inverse,
  then Undo restores the byte-equivalent page graph.
- Good: renaming a legacy blank-looking node creates `restoreNodeName` and Undo
  restores the original persisted value exactly.
- Base: a small rename has small forward and inverse payloads.
- Bad: reject page deletion because its generated inverse is larger than the
  incoming request.
- Bad: reuse `CommandNodeName` for `restoreNodeName`, making a valid repair
  impossible to undo.

### 6. Tests Required

- Contract: forward batches immediately below/above 256 KiB accept/refuse at
  the user boundary.
- Contract/store/service: a small delete with an inverse larger than 256 KiB
  appends, replays, Undoes, and Redoes without weakening canonical validation.
- Contract: `updateNodeName` rejects whitespace while `restoreNodeName` accepts
  every value allowed by the persisted node schema.
- Page CRUD: deterministic ID remapping, reference cleanup/refusal,
  `runtime.pageIds`, command hash, replay, Undo, and Redo remain aligned.

### 7. Wrong vs Correct

Wrong:

```python
for payload in (commands_json, inverse_commands_json):
    if len(payload.encode("utf-8")) > MAX_BYTES:
        raise CommandBatchTooLarge()
```

Correct:

```python
if operation_kind == "forward" and len(commands_json.encode("utf-8")) > MAX_BYTES:
    raise CommandBatchTooLarge()
parse_inverse_command_batch_json(inverse_commands_json)  # canonical and typed, not request-sized
```

## Scenario: Bounded Project Conductor State and Durable Review Claims

### 1. Scope / Trigger

- Trigger: changing Project Conductor state, scheduled reviews, conductor task
  persistence, memory compaction/retrieval, or the Project Conductor HTTP API.
- This contract exists because a reload-triggered scheduler and a scheduled
  answer that re-ingested rendered warm/cold context created thousands of
  duplicate tasks and recursively growing JSON.

### 2. Signatures

- Store:
  - `create_conductor_task_if_absent(task: ConductorTask) -> bool`.
  - `load_latest_completed_project_review_at(project_id: str) -> datetime | None`.
  - `list_conductor_tasks(*, status: str | None = None, issue_id: str | None = None) -> list[ConductorTask]`.
  - `save_project_conductor_state(state: ProjectConductorState) -> bool` uses
    `state.revision` as an optimistic compare-and-swap token.
- Scheduler:
  `run_project_review_tick(store, *, limit=None, due_after=None, review_slot=None) -> ProjectReviewTickSummary`.
- API:
  - `GET /api/codex/projects/{project_id}/conductor/state`.
  - `POST /api/codex/projects/{project_id}/conductor/ask`.
  - `POST /api/codex/projects/{project_id}/conductor/schedule-review`.
  - `POST /api/codex/projects/{project_id}/conductor/start-loop`.
- State responses expose bounded `hot_thread`, `warm_summaries`, and
  `cold_memories` plus total/truncated metadata for bounded tiers.

### 3. Contracts

- The background scheduler derives one deterministic task ID per
  `(project_id, interval slot)` and claims it with `INSERT OR IGNORE`. A second
  process or reload in the same slot returns `skipped_claimed`.
- When a completed scheduled review is newer than `due_after`, the project
  returns `skipped_recent`; backend reload alone never makes a review due.
- A scheduled review may run the typed GitHub PR sweep, but it MUST NOT call
  `answer_question()` or render pinned/warm/cold memory into its answer. It
  persists one bounded delta containing only review outcome and compact PR
  counts/status.
- User questions remain the only path that renders retrieved context for an
  answer. Persisted hot/warm entries strip known legacy rendered-memory
  sections before reuse.
- Input, answer, event, summary, hot-count, warm-count, retrieval-count, and
  state-tail limits are hard application constants. The state endpoint returns
  at most 20 hot items, 8 warm items, and 20 cold items.
- Count or token overflow compacts the oldest required prefix into the next
  memory tier before retaining the bounded tail. Applying `items[-limit:]`
  before compaction is forbidden because it silently discards history and can
  make the token thresholds unreachable.
- Persisted `hot_thread_json` and `warm_summaries_json` are strict JSON arrays.
  Invalid JSON or a non-array raises `ProjectConductorStateError`; it must not
  silently become an empty state that later overwrites durable data.
- Every state update loads a revision, applies its delta, and saves only while
  that revision is current. A conflict reloads and reapplies the events and
  task-count increment; bounded exhaustion fails loudly. Long external work,
  including a PR sweep, must finish before loading the state to mutate.
- Schema migrations that repair recursive memory validate affected JSON before
  mutation, remove only scaffolds linked to a confirmed recursive review's
  project/task/source identity, preserve retained scalar JSON values exactly,
  recompute token counters, record an audit event, and are idempotent on a
  second open. Text matching alone must never delete another project's memory.
- Issue self-improvement reads conductor tasks with an `issue_id` store filter;
  it must not load the project-wide task ledger and filter in Python.

### 4. Validation & Error Matrix

- Same project and review slot already claimed -> `skipped_claimed`; no second
  task or memory event.
- Latest completed review is within the interval -> `skipped_recent`; no claim.
- Scheduled PR sweep fails -> bounded `github_pr_followup.status="failed"`;
  the supervisor task still reaches `done` and the next interval remains live.
- Corrupt state JSON -> typed `ProjectConductorStateError`; no repair overwrite.
- Question/prompt above 4,000 characters or blank after trimming -> HTTP 422.
- Legacy repair encounters unparseable target JSON -> migration rolls back and
  startup fails closed.
- State compare-and-swap conflict -> reload and reapply the delta; retry-budget
  exhaustion raises `ProjectConductorStateConflictError` without overwriting a
  newer row.

### 5. Good/Base/Bad Cases

- Good: two scheduler instances scan the same project in the same interval;
  exactly one durable task executes and one bounded hot event is written.
- Good: a manual event lands while a scheduled review is running; both events
  and the exact task count survive after the review finishes.
- Base: an operator explicitly requests a manual review and receives the
  compact result immediately.
- Good: a state with hundreds of historical rows returns recent tails and
  truncation metadata without serializing the entire ledger.
- Bad: run one review immediately on every process start.
- Bad: construct a scheduled answer from `Pinned`, `Warm summaries`, and
  `Relevant cold memory`, then compact that rendered answer back into memory.
- Bad: catch JSON decoding and return `[]` at a persistence boundary.
- Bad: `INSERT OR REPLACE` an old whole-state snapshot after a long await.

### 6. Tests Required

- Scheduler: recent completion skips; two calls with one interval slot produce
  one claim; per-project failures remain isolated.
- Conductor: scheduled review never calls/duplicates question-answer context;
  repeated reviews keep hot/result payloads bounded.
- Compaction: the 49th hot event becomes a warm summary while 48 recent events
  remain; the 25th warm summary moves the oldest summary to cold memory.
- API: exact endpoint paths, project ID encoding, input validation, task ID
  correlation, state-tail totals/truncation, and cold-memory serialization.
- Migration: a real memory row survives; only known recursive scaffolds are
  removed; a clean project quoting legacy text and a retained integer above
  int64 survive exactly; token counts are recomputed; corrupt JSON rolls back;
  second open produces no further mutation.
- Concurrency: force two writers to load the same revision and prove both
  deltas survive via compare-and-swap retry.
- Query scope: self-improvement requests only the matching issue's tasks.

### 7. Wrong vs Correct

Wrong:

```python
for project in await store.list_projects():
    await conductor.handle_task(new_random_scheduled_review(project))
```

Correct:

```python
task = scheduled_review_for_interval(project.id, review_slot)
if latest_completed_at is not None and latest_completed_at >= due_after:
    return "skipped_recent"
if not await store.create_conductor_task_if_absent(task):
    return "skipped_claimed"
await conductor.handle_task(task)
```
