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

## Scenario: Project-Evidence Prototype Plans and Generation Runs

### 1. Scope / Trigger

- Trigger: changing project evidence discovery, prototype planning/generation
  APIs, plan/run SQLite tables, or source-backed prototype versioning.
- This is the supported replacement for the retired direct code-scan routes:
  analysis first persists an editable plan; generation consumes a frozen plan.

### 2. Signatures

- Analysis: `POST /api/projects/{project_id}/prototype-plans` with an optional
  JSON body; an empty body is valid.
- Planning runtime: `PROTOTYPE_PLANNING_TIMEOUT_S` defaults to `120` seconds and
  is independent from `WORKFLOW_ORCHESTRATOR_TIMEOUT`.
- Recovery: `GET /api/projects/{project_id}/prototype-plans/latest` and
  `GET /api/prototype-plans/{plan_id}/generation-runs/latest`.
- Generation: `POST /api/prototype-plans/{plan_id}/generate` and retry through
  the generation-run retry endpoint.
- Store ownership: plan/run creation, run-item completion, prototype-version
  persistence, and source-hash advancement remain typed store operations.
- Freeze operation:
  `freeze_prototype_generation_run(..., seed_briefs, reuse_terminal_run)` owns
  idempotence across service instances and SQLite connections.
- Artifact protocol: Claude Code writes
  `.agent-collab/prototype-staging/<run-item-id>/index.html` and returns a
  `prototype-artifact/v1` manifest, not HTML in assistant text.
- Agent-facing prompt:
  `_build_prompt(*, title, target_routes, output_locale, artifact_path)` accepts
  only page identity and the artifact protocol. `PrototypeArtifactRequest`
  keeps `candidate_id`, `source_hash`, and `source_paths` as server-only
  worktree/fingerprint guards.
- Durable version file:
  `<project>/prototypes/<prototype-id>/<version-id>/index.html`. The version ID
  is allocated before the SQLite version number and is safe for concurrent
  writers; `disk_path` is committed with the version row.
- UI analysis protocol:
  `PrototypePlanningUIEngineer.plan(project, plan_id, prompt, source_paths)`
  runs the built-in `prototype_ui_engineer` through the Claude executor in an
  isolated read-only prototype worktree and returns strict plan JSON.
- Legacy contract: schema version 7 reconstructs
  `prototype_plan_items.evidence_ids_json` and
  `prototype_generation_run_items.seed_brief` from durable legacy data.
- Runtime-history contract: schema version 8 preserves complete
  `prototype_generation` task results, messages, runtime logs, agent-call
  traces, and audit rows byte-for-byte. Historical payloads destroyed by the
  retired v8 scrub cannot be reconstructed.

### 3. Contracts

- Evidence IDs are stable, bounded, persisted in plan items, and validated
  against the scanned manifest before a planner response is accepted.
- Deterministic route/package/evidence discovery remains backend-owned. When a
  UI engineer is configured, project context, titles, summaries, restore
  briefs, and representative state selection are UI-engineer responsibilities;
  the direct HTTP planner is not called.
- Planner `states` are stable lowercase technical identifiers such as
  `default`, `loading`, `empty`, `error`, and `success`. Route-derived state
  identifiers may additionally use digits, colon, slash, dot, underscore, and
  hyphen (for example `collections-:id`). They are not user-visible prose and
  are excluded from `output_locale` validation.
- The planning UI engineer uses the same Runtime Catalog Claude/MiniMax
  resolution and built-in `prototype_ui_engineer` role as artifact generation.
  It receives the exact manifest source paths, may inspect the isolated source,
  must not edit it, and must not generate HTML during planning.
- A plan records the source fingerprint used for analysis. If a post-planner
  rescan differs, the plan is persisted as `stale`, never as ready.
- Generation gives Claude an isolated full-project worktree and requires it to
  locate router entries, imports, components, layouts, navigation, styles,
  tokens, and assets itself. The generation prompt must not contain scanned
  source paths, candidate/hash values, evidence, project context, restore seed,
  or routes belonging only to other plan items.
- Project-driven generation always requires the Claude artifact generator.
  Missing CLI/runtime/configuration fails before `freeze_prototype_generation_run`;
  it never falls back to direct HTTP because that model request cannot read the
  repository. Manual prototype streaming remains a separate service path.
- Concurrent generation requests for one plan resolve to one persisted run.
- Prototype version creation and run-item `done` are one transaction. The
  prototype `source_hash` advances only after that transaction succeeds.
- A generation item succeeds only after a validated artifact manifest, durable
  project-file write, and store-owned completion transaction. Restart recovery
  converts in-flight items to interrupted and recalculates persisted counters.
- MiniMax-M3 planning requests omit Anthropic assistant prefill because its
  compatibility endpoint can return HTTP 200 with `content=null`; an empty
  successful response is retried once with the alternate message shape.
- Repository-scale planning calls contain at most six candidates per LLM
  response. Batch outputs are merged in memory and persisted only after the
  combined output covers every candidate exactly once.
- Each batch uses strict JSON parsing first. At the external model boundary
  only, known MiniMax JSON drift may pass through `tolerant_json_loads`; the
  repaired object must still pass `_PlannerOutput`, candidate, and evidence-ID
  validation before it is accepted.
- Tolerant repair runs only after the raw planner response is proven to be one
  complete top-level JSON object. Truncated, fenced, prefixed, suffixed, or
  concatenated objects are not repair candidates.
- An ordinary generate request reuses only an active latest run. After the
  latest run is terminal, a new user request creates a new run from the plan's
  current selection. If two service instances began the same request before
  either froze a run, the second freeze still reuses the first winner even when
  that fast run became terminal during preparation.
- Restore seeds are materialized before dispatch and persisted on both the
  version-zero seed and run item. They remain audit/version instructions and
  are never forwarded to the generation agent; Claude derives the page from
  the repository and target routes. A later plan edit cannot rewrite the
  persisted instruction used by completion or retry.
- Claude chooses how to create and inspect the staged file. The backend never
  parses, constrains, or replays its Write/Edit/Bash sequence and never derives
  HTML from audit logs. The final manifest is at most 2,048 UTF-8 bytes and its
  exact path, byte size, checksum, UTF-8, HTML structure, URL policy, symlinks,
  and source-tree diff are checked before version persistence. The default
  resource allowlist is limited to Tailwind CDN plus Google Fonts
  (`fonts.googleapis.com` and `fonts.gstatic.com`); inert URLs in copy and form
  values are not resources.
- Complete Claude runtime evidence, including commands, tool inputs/outputs,
  thinking, assistant text, HTML, result, trace, status, and audit payloads, is
  persisted for Agent debugging, review, and continuation. These records are
  never artifact inputs and never prove generation success.
- Prototype artifact audit data contains task/process identity, artifact path,
  checksum, byte size, validation outcome, and safe errors. It does not store,
  reconstruct, or generate the staged HTML.
- A successful artifact is written with exclusive create and `fsync` before
  SQLite completion. Preview and iteration read `disk_path` first. Only legacy
  rows with `disk_path IS NULL` may use the database HTML copy; a missing,
  escaped, symlinked, invalid UTF-8, or DB-mismatched file fails loudly.
- SQL defaults are not migration semantics. Version 7 backfills evidence IDs
  from validated evidence records and seed briefs from version-zero seeds; an
  unreconstructable retryable row aborts startup instead of loading an empty
  contract value.

### 4. Validation & Error Matrix

- Unknown evidence ID -> reject planner output and mark analysis failed.
- Repository fingerprint changes during analysis -> persist `stale`.
- Feature, budget, cost, candidate-count, or concurrency gate unavailable or
  denied -> reject analysis/generation fail-closed.
- Claude artifact generator absent or unavailable -> reject before freezing a
  run or prototype; do not call manual/direct HTTP generation.
- Repeated/concurrent request while a run is active -> return the active run.
- Generate after a terminal run -> create a new run from the current selection.
- Project-file write or version transaction failure -> item `failed`; do not
  create a positive version or advance source hash.
- Planner request exceeds `PROTOTYPE_PLANNING_TIMEOUT_S` -> analysis failed with
  the saved draft retained and an explicit retry/reanalysis action.
- Any batch is truncated, unrecoverable, or fails schema/evidence validation ->
  the whole plan is `analysis_failed`; do not persist earlier batch items.
- Manifest over 2 KiB, path mismatch/traversal/symlink, invalid UTF-8/HTML/URL,
  byte-size or checksum mismatch, or source edit -> fail the item atomically.
  A valid final artifact is accepted regardless of which Claude tools created
  it or how many mutations were used.
- Planner response with a missing closer, open string, markdown fence, prose
  prefix, or multiple objects -> `analysis_failed`; tolerant repair is not run.
- UI engineer unavailable, failed, returned no result, or edited project source
  during planning -> `analysis_failed` with an explicit UI-engineer error; do
  not fall through silently to the direct HTTP planner.
- Localized or whitespace-bearing planner state (`默认`, `Loading state`) ->
  schema rejection with the failing nested field path; use a stable technical
  identifier. Valid `default` and `collections-:id` states on a zh-CN plan do
  not trigger locale rejection.
- Version 6 legacy create/update/unchanged item with no recoverable evidence,
  or retryable run item with no version-zero seed -> migration fails loudly.

### 5. Good/Base/Bad Cases

- Good: a 19-item plan is reviewed, selected items generate once, and refresh
  restores titles, counters, errors, versions, and retry state.
- Base: an empty analysis body creates a restore plan and reuses the latest
  saved project instruction.
- Good: two service instances freeze the same ordinary request; the first run
  completes before the second `BEGIN IMMEDIATE`, and both callers still receive
  the same terminal run id.
- Good: after that terminal run, a later user request with a different reviewed
  selection receives a new run id containing only the newly selected items.
- Good: a failed legacy run is migrated, retried, and uses the exact frozen seed
  that produced its original version-zero row.
- Good: a zh-CN plan returns Chinese context/brief copy plus
  `states=["default", "empty"]`; locale validation accepts the state IDs and
  validates only human-authored copy.
- Good: production planning creates a `prototype_planning` Claude task with
  role `prototype_ui_engineer` and never calls the configured direct HTTP
  runner.
- Good: generation sends only the current item's title/routes and artifact
  protocol; Claude searches the worktree and restores the page from real router
  and component imports.
- Good: a successful version exists under `<project>/prototypes/...` before its
  row is marked complete, and preview verifies the disk file against the DB
  integrity copy.
- Bad: create a run in one transaction and source prototypes in another,
  allowing duplicate POSTs to create orphan rows.
- Bad: update `source_hash` before version persistence succeeds.
- Bad: serialize the evidence manifest, source paths, project context, frozen
  seed, or all plan routes into the Claude generation prompt.
- Bad: select a direct HTTP backend for project-driven generation; it cannot
  inspect the repository and therefore cannot satisfy the restore contract.
- Bad: treating balanced-looking HTML at socket EOF as provider completion.
- Bad: accepting a JSON repair that invents missing closing structure after a
  token-limit truncation.

### 6. Tests Required

- Evidence tests cover router aliases, dynamic-path diagnostics, deduplication,
  content-derived page/style fingerprints, stable IDs, and prompt bounds.
- Planning tests cover empty bodies, instruction reuse, invalid evidence IDs,
  reanalysis, startup recovery, post-LLM stale detection, candidate batching,
  real MiniMax asymmetric-quote repair followed by strict validation, and
  rejection of incomplete/non-single JSON envelopes before repair.
- UI-engineer planning tests assert executor/role/task kind, isolated worktree,
  source-path forwarding, read-only enforcement, direct-runner precedence, and
  zh-CN acceptance of stable state identifiers.
- Generation tests synchronize two POSTs and assert one run, atomic version/item
  completion, Claude-only fail-closed gates, interrupted counter
  recovery, failed/interrupted-only retry, terminal-before-second-freeze reuse,
  exact wire-prompt context non-injection, tool-sequence-independent final
  artifact acceptance, and every manifest/filesystem validation branch.
- Version-artifact tests assert the version-ID path, exclusive/concurrent writes,
  symlink/escape rejection, disk-first reads, legacy DB-only fallback, missing
  file failure, UTF-8 handling, and disk/DB mismatch detection.
- Migration tests start from version 6 rows and assert deterministic evidence-ID
  and seed backfills plus fail-closed behavior when either cannot be recovered.
- API/frontend tests assert typed snapshots round-trip without reconstructing
  lifecycle state in React.

### 7. Wrong vs Correct

Wrong:

```python
prototype.source_hash = item.source_hash
await store.save_prototype(prototype)
await store.mark_run_item_done(item.id)
```

Correct:

```python
await store.complete_prototype_generation_item(
    run_item=item,
    prototype=prototype,
    version=version,
)
```

Wrong:

```python
# A SQL default makes the column non-null but does not restore its meaning.
seed_brief = row["seed_brief"] or rebuild_seed_from_current_plan(plan)
```

Correct:

```python
# Migration reconstructs the frozen value from the durable version-zero seed.
# If a retryable row has no such seed, startup fails for explicit repair.
seed_brief = row["seed_brief"]
```

Wrong:

```python
for state in item.states:
    require_zh_cn_copy(state)  # Rejects the contract value "default".
```

Correct:

```python
validate_lowercase_technical_identifiers(item.states)
validate_locale(item.title, item.summary, item.brief)
```

Wrong:

```python
prompt = build_prompt(
    source_paths=item.source_paths,
    project_context=plan.project_context,
    seed=item.seed_brief,
    project_routes=all_plan_routes,
)
```

Correct:

```python
# The guard data remains on the server; Claude discovers implementation detail.
prompt = build_prompt(
    title=item.title,
    target_routes=tuple(item.route_patterns),
    output_locale=plan.output_locale,
    artifact_path=staging_path,
)
```

Wrong:

```python
# Tool logs describe one implementation strategy; they are not the artifact.
logs = await store.load_log_events(task.id)
html = replay_successful_write_and_edit_calls(logs)
validate_artifact_bash_commands(logs)
```

Correct:

```python
# Claude owns the tool sequence. The backend validates only the final boundary.
artifact = validate_prototype_artifact(
    worktree_path=worktree_path,
    expected_artifact_path=staging_path,
    manifest_text=task.result,
    max_bytes=max_artifact_bytes,
)
await assert_source_tree_unchanged(worktree_path)
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
