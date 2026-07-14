# Observability Guidelines

> Contracts for backend observability surfaces: raw audit evidence, semantic
> Agent Timeline operations, and lightweight trace/span identity.

---

## Scenario: Audit Log vs Agent Timeline Trace Contract

### 1. Scope / Trigger

- Trigger: changing audit event recorders, `audit_log` payload shape,
  `log_events` trace fields, trace detail APIs, or the Agent Timeline API.
- The product has two separate observability layers:
  - **Audit Log** is the raw evidence layer. It may store noisy events such as
    `task_status` and raw payload previews.
- **Agent Timeline** is the user-facing semantic projection. Its top-level
  items represent one agent execution; semantic audit rows such as `cli_spawn`
  and `project_script_updated` are entries/steps inside that execution.
- Runtime task executions use `execution_process_id` as the natural trace
  boundary. Do not infer one execution from `task_id` alone because follow-up
  runs can reuse the same task.

### 2. Signatures

- Raw evidence API:
  - `GET /api/codex/audit-log`
  - `GET /api/codex/audit-log/chains` legacy grouping, compatibility only.
- Semantic timeline API:
  - `GET /api/codex/agent-timeline`
- Trace detail APIs:
  - `GET /api/codex/audit-log/{audit_id}/trace`
  - `GET /api/codex/traces/{trace_id}`
- Trace identity fields:
  - `trace_id`
  - `span_id`
  - `parent_span_id`
  - `execution_process_id`
  - `correlation_id`
- Important event types:
  - `task_status`
  - `project_script_updated`
  - `cli_spawn`
  - `prototype_artifact_validation`

### 3. Contracts

- New runtime executions must set `trace_id = execution_process_id` for the
  active `CodexTask`.
- `span_id` identifies the emitting unit, usually the task id for task runtime
  events.
- `parent_span_id` preserves upstream lineage when available.
- `correlation_id` should default to `trace_id` or `execution_process_id` when
  no explicit correlation id is supplied.
- `task_status` is audit evidence and span/task state. It must not be a default
  Agent Timeline node.
- Agent Timeline step rows should be semantic operations such as:
  - `cli_spawn`
  - `project_script_updated`
  - command/tool/git/finalize operations when they represent agent work.
- Agent Timeline top-level items should aggregate semantic rows by
  `execution_process_id` or `trace_id`. When legacy rows lack execution
  identity, a task-scoped fallback may merge them into the single known
  execution for that task; do not merge across multiple known executions.
- `project_script_updated` audit rows must carry structured fields, not only a
  string preview:
  - `project_id`
  - `task_id`
  - `role`
  - `task_kind`
  - `execution_process_id`
  - `trace_id`
  - `span_id`
  - `parent_span_id`
  - `setup_script`
  - `run_command`
- Agent Timeline operation responses should expose:
  - `timeline_kind`
  - `event_type`
  - `title`
  - `summary`
  - `result`
  - `status`
  - `status_source`
  - `execution_process_id`
  - `trace_id`
  - `span_id`
  - `parent_span_id`
  - `entries`
- `status_source` is diagnostic metadata:
  - `audit_row` means the status came from the semantic node row.
  - `task_status` means the status was merged from a `task_status` event.
- Timeline status merging must respect execution boundaries. If a node has an
  `execution_process_id` or `trace_id`, do not apply a status from the same
  `task_id` unless the status event matches that execution/trace. Task-level
  fallback is allowed only when the node itself lacks an execution boundary.
- Trace detail for semantic audit rows should prefer row-specific details over
  whole-task runtime logs. For example:
  - `cli_spawn` trace detail returns argv/cwd/executor/model/pid details plus
    reconstructed task messages and runtime log events for the CLI process.
  - `project_script_updated` trace detail returns setup/run command results.
  - Whole-task runtime logs are a fallback when the row has no better semantic
    detail and no provider trace row exists.
- Prototype generation follows the raw runtime evidence policy. Persist the
  complete stdout/stream-json frames, thinking, tool inputs and outputs,
  commands, assistant messages, final result/HTML, runtime traces, status
  events, and audit payloads. This trajectory is durable Agent-system data for
  debugging, review, and continuation.
- Runtime trace `request_json` and `response_json` retain the complete payload;
  bounded preview columns are UI summaries only and never replace the source
  trace.
- Runtime evidence is observability only. Generation must never reconstruct
  HTML from logs, constrain or whitelist the agent's tool sequence, or use
  tool history as artifact-success evidence. Success comes only from the
  staged HTML, strict manifest, source integrity, and durable completion.
- `prototype_artifact_validation` records only task/process identity, the exact
  staging path, validated checksum and byte size, `passed|failed`, and a stable
  safe error code. It never serializes manifest text, exception text, or HTML.
- Schema version 8 does not rewrite runtime history. Databases already opened
  by the retired destructive v8 migration have irreversibly lost those old
  payloads; future migrations and writes preserve complete content.

### 4. Validation & Error Matrix

- Store unavailable -> `503`, detail `SQLite store not available`.
- Unknown trace id with no trace rows -> `available=false`,
  `reason=trace_not_recorded`.
- Audit row without trace detail and without runtime fallback ->
  `available=false`, `reason=trace_not_recorded`.
- Legacy audit rows with only `payload_preview` -> parse best-effort and return
  semantic timeline data when safe; never fail the endpoint because preview
  parsing fails.
- Status event for same `task_id` but different/missing execution boundary ->
  do not override an execution-scoped timeline node.
- Runtime task identity unavailable while persisting a frame -> retain the raw
  frame with the available correlation fields; do not silently discard Agent
  trajectory data.
- Prototype model response is not a strict compact `prototype-artifact/v1`
  manifest -> retain the raw result for observability, while final artifact
  validation fails through the normal generator boundary.

### 5. Good/Base/Bad Cases

- Good: an Operations Engineer execution produces one top-level timeline item
  with `cli_spawn` and `project_script_updated` entries; `task_status=done`
  updates the item status but does not appear as its own node.
- Good: `project_script_updated` opens a trace detail showing
  `setup_script`/`run_command`, not an unrelated full runtime transcript.
- Good: `cli_spawn` opens a trace detail showing the Claude Code runtime
  process from persisted task messages and `log_events`.
- Base: an old audit row only has `payload_preview`; the timeline still shows a
  useful summary if the preview can be parsed.
- Bad: rendering `cli_spawn` and `project_script_updated` from the same
  execution as separate top-level Agent Timeline cards.
- Bad: grouping every `task_status` event as a visible Agent Timeline node.
- Bad: using only `task_id` to merge status across multiple follow-up runs.
- Bad: storing the business result only inside `payload_preview`, forcing the
  frontend to regex a Python dict string.

### 6. Tests Required

- Recorder test: `record_event(project_script_updated)` writes structured
  `role`, `task_kind`, trace/span fields, `setup_script`, and `run_command`.
- API test: `/api/codex/agent-timeline` excludes `task_status` as a node while
  using it to set operation status.
- API test: timeline operations include `timeline_kind`, `event_type`,
  `result`, `status_source`, and trace/span fields.
- API test: a task-level status event without an execution boundary does not
  override an execution-scoped timeline node.
- Trace test: `GET /audit-log/{id}/trace` for `project_script_updated` returns
  row-specific setup/run command response data.
- Trace test: `GET /audit-log/{id}/trace` for `cli_spawn` includes persisted
  task messages and `log_events` so the UI can show the Claude Code process.
- Store parity test: sync and async log-event stores preserve
  `parent_span_id`.
- Runtime evidence test: HTML and command sentinels in stdout, thinking,
  Write/Edit/Bash, tool result, message delta, task result, agent trace, status,
  and audit payload are persisted for `prototype_generation`.
- Migration test: all schema v7 runtime-history rows remain byte-for-byte
  unchanged at v8, and reopening v8 is idempotent.
- Artifact audit test: success and every post-task failure stage emit exactly
  one metadata-only `prototype_artifact_validation` event.
- Frontend typecheck: timeline API types stay aligned with the response shape.

### 7. Wrong vs Correct

#### Wrong

```python
await event_bus.append({
    "type": "task_status",
    "task_id": task.id,
    "status": "done",
})
```

This emits too little identity for standalone pages, audit evidence, and
timeline status merging.

#### Correct

```python
await event_bus.append(
    build_task_status_event(
        task,
        "done",
        execution_process_id=task.last_execution_process_id,
    )
)
```

For prototype generation runtime evidence, this complete trace is correct:

```python
response_payload = {
    "result": task.result,
    "logs": [{"content": event.content} for event in logs],
}
```

The following metadata-only replacement is wrong because it destroys the
Agent trajectory:

```python
response_payload = {
    "status": task.status,
    "execution_process_id": task.last_execution_process_id,
    "result_is_manifest": validated_manifest is not None,
    "manifest": validated_manifest_metadata,
    "log_count": len(logs),
    "log_content_chars": sum(len(event.content) for event in logs),
}
```

#### Wrong

```python
return {"items": audit_rows}
```

Using raw audit rows directly as the Agent Timeline makes noisy state events
look like agent work.

#### Correct

```python
return {
    "items": [
        {
            "timeline_kind": "project_script_updated",
            "status": "done",
            "status_source": "task_status",
            "result": {
                "setup_script": project.setup_script,
                "run_command": project.run_command,
            },
            "entries": [project_script_updated_audit_row],
        }
    ]
}
```

## Scenario: Plan-Scoped Prototype Discovery MCP

### 1. Scope / Trigger

- Trigger: a Claude Code prototype-planning run needs to read project code and
  persist page discoveries before its final response.

### 2. Signatures

- Endpoint: `POST /api/internal/prototype-planning-mcp`.
- Tools: `list_discovered_pages`, `register_prototype_page`, and
  `finalize_prototype_inventory`.
- Item fields: `discovery_origin` (`static|claude`) and `review_status`
  (`provisional|confirmed|needs_confirmation`).
- Source line boundary: `source_line_count(source) -> int` is shared by static
  evidence discovery and dynamic MCP evidence validation.

### 3. Contracts

- The spawned Claude process receives an ephemeral MCP config with a random
  `X-Prototype-Planning-Token`; it is revoked when that planning run exits.
- The endpoint first enforces loopback host restrictions, then validates that
  token. It never accepts the MCP token for other API routes.
- `list_discovered_pages` returns paths, routes, confidence, diagnostics and
  evidence IDs, never source excerpts. Each successful registration is an
  upsert, so the persisted plan snapshot is the live progress source.
- Evidence `start_line` and `end_line` refer only to addressable lines in the
  source file. A trailing newline terminates the last line; it does not create
  an additional empty line.

### 4. Validation & Error Matrix

- Missing, expired, or wrong MCP token -> `401`; non-loopback host -> `403`.
- Invalid source path, evidence line, locale, or evidence ID -> tool error and
  no partial item persistence.
- `end_line` greater than `source_line_count(source)` -> tool error, including
  when the only apparent extra line comes from `source.count("\n") + 1` on a
  file ending in a newline.
- Finalization before route-list lookup -> tool error. Missing static routes ->
  tool error containing the missing candidate IDs; the plan remains analyzing.

### 5. Good/Base/Bad Cases

- Good: Claude reads a route, registers it, and the review UI shows a locked
  provisional row before the next route is processed.
- Base: a source-backed page not found by the static scanner is stored as
  `claude` / `needs_confirmation` and is not selected for generation.
- Good: a one-line file containing `"component\n"` produces `end_line=1`.
- Bad: forwarding the console control token to Claude, or bypassing all local
  authentication for the MCP endpoint.
- Bad: calculating line bounds with `source.count("\n") + 1`, which reports a
  non-existent second line for `"component\n"`.

### 6. Tests Required

- MCP tests cover compact route output, registration, finalization, token
  revocation, a valid non-static source-backed page, and rejection of an
  `end_line` one past the real final line.
- Planning tests assert incremental upserts preserve prior rows and do not let
  non-static discoveries increase the static-route progress denominator.
- Evidence scanner tests assert a trailing-newline source ends at its real
  final line.
- Frontend type and stream-parser tests include both new item fields.

### 7. Wrong vs Correct

#### Wrong

```python
if request.url.path.startswith("/api/internal/"):
    return await call_next(request)
```

#### Correct

```python
failure = authorize_loopback_request(request)
if failure is None and prototype_planning_mcp_service.has_session_token(token):
    return await call_next(request)
```

For source bounds, the wrong calculation is:

```python
line_count = source.count("\n") + 1
```

The correct shared calculation is:

```python
line_count = source_line_count(source)
```
