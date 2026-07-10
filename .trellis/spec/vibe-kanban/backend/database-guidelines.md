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

## Scenario: Prototype Code-Scan Removal With Legacy Provenance

### 1. Scope / Trigger

- Trigger: changing prototype creation, prototype list/get/iteration/regeneration,
  the prototype SQLite schema, or the frontend `Prototype` contract.
- Code-scan generation is removed, but prototypes created by that retired flow
  remain normal user data and must stay usable without a migration.

### 2. Signatures

- Retained model fields: `source_kind: Literal["manual", "code"]`,
  `source_ref`, `source_hash`, and `source_meta_json`.
- Retained store APIs: `save_prototype`, `load_prototype`, and
  `list_prototypes`.
- Retained SQLite columns: `prototypes.source_kind`, `source_ref`,
  `source_hash`, and `source_meta_json`.
- Retained index: `idx_prototypes_project_source`.
- Removed HTTP paths:
  `GET /api/projects/{project_id}/prototypes/code-candidates` and
  `GET /api/projects/{project_id}/prototypes/generate-from-code/stream`.
- Removed dedicated store APIs: `load_prototype_by_source`,
  `list_code_prototypes`, and `update_prototype_source_metadata`.

### 3. Contracts

- Manual creation writes `source_kind="manual"` and does not invoke source
  discovery or browser capture.
- A persisted `source_kind="code"` row remains visible through the normal list
  and get APIs and supports iteration and regenerate-all.
- The backend and frontend `Prototype` shapes retain all four provenance
  fields, even though the frontend no longer renders a source badge/reference.
- Removing code-scan does not drop columns, drop the provenance index, rewrite
  historical rows, or add a schema migration.
- The two removed routes are absent from OpenAPI and requests return `404`.

### 4. Validation & Error Matrix

- Legacy code prototype list/get -> return the row with provenance unchanged.
- Legacy code prototype iteration/regenerate-all -> create the next normal
  version and preserve prototype provenance.
- Manual prototype creation -> persist `source_kind="manual"`.
- Request to either retired route -> `404`; no compatibility shim.
- Missing legacy provenance values -> preserve existing nullable-field behavior;
  do not synthesize scanner metadata.

### 5. Good/Base/Bad Cases

- Good: a historical code prototype is listed, iterated, and regenerated while
  `source_hash` and `source_meta_json` round-trip unchanged.
- Base: a new manual prototype uses the ordinary create/stream flow.
- Bad: filtering `list_prototypes` to manual rows, which hides user data.
- Bad: dropping `source_*` fields or SQLite columns as part of removing the
  scanner, which turns a feature removal into an API/data migration.

### 6. Tests Required

- Service regression: persist a legacy code prototype, then assert list, get,
  iterate, regenerate-all, and provenance round-trip behavior.
- API regression: assert both retired paths are absent from OpenAPI and return
  `404`.
- Frontend regression: manual creation and regenerate-all readers remain, while
  code-scan API/types/UI identifiers have no active-source matches.
- Run the prototype service/API tests without a `slow` marker on the legacy
  compatibility test so the default pytest gate collects it.

### 7. Wrong vs Correct

Wrong:

```python
# Removing a feature must not silently delete its historical data contract.
await conn.execute("ALTER TABLE prototypes DROP COLUMN source_kind")
```

Correct:

```python
# Remove scanner-only queries; normal CRUD still loads legacy provenance.
async def list_prototypes(self, project_id: str) -> list[Prototype]:
    ...
```

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
