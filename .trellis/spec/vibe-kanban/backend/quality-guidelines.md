# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

The bar is **"a senior engineer can read the diff in one pass and
trust it."** A change that touches a service is reviewable in
under 15 minutes; a change that touches the conductor or the
store is reviewable in under 30. The toolchain enforces most of
the mechanical rules (lint, typecheck, tests), so the reviewer's
job is mostly about shape, naming, race conditions, and the
things the tools cannot see.

Every change must pass, locally, in this order:

```bash
cd backend
.venv/bin/python -m pytest -v   # default fast lane; @pytest.mark.slow is skipped
.venv/bin/python -m pytest tests/test_foo.py -v   # pointed test, never skipped
.venv/bin/python -m ruff check .                  # if ruff is wired in
.venv/bin/python -c "from app.main import app"    # import smoke
```

A PR that hasn't run the relevant tests is not ready for
review. A change that touches a public Pydantic model gets a
serializer round-trip test; a change that touches the
conductor gets a state-machine test; a change that touches the
store gets a real-async-store migration test.

---

## Forbidden Patterns

- **`any` in production types.** The `no-any` rule is enforced
  at review time. Use `object` + a type guard, or define a
  narrow union. The exception is bridging a third-party type
  we cannot change — narrow as soon as you cross the bridge.
- **`os.getenv` from feature code.** All env reads go through
  `application/timeouts.py` accessors. The boot-time setup
  in `timeouts.validate()` is the only place that reads
  env vars.
- **Catching `Exception` to "always return a value".** Let
  unexpected exceptions propagate to the loop boundary or the
  transport layer, where they can be logged with a traceback.
  Catch the typed errors the use case actually anticipates.
- **Polling a value the WS already streams.** A background
  task that polls a value the conductor already emits is a
  duplicate of the event stream. The conductor emits at
  semantic boundaries; polling is for silent growth below a
  threshold.
- **Service code that imports from `interfaces/`.** The
  transport layer imports the application layer; never the
  other way. A service that knows the HTTP shape leaks.
- **`raise HTTPException(...)` from a service.** Same leak in
  the other direction. The service raises a typed error; the
  transport maps it to a status.
- **Long-running coroutines that hold a transaction across an
  `await`.** A conductor iteration that opens a write
  transaction and then awaits a dispatch holds the SQLite
  write lock for the duration. Release before the await,
  re-acquire on the next call.
- **Re-using the same conductor issue worktree across parallel
  dispatches.** The `dispatch_batch` path forks an
  isolation worktree per agent (`worktree_manager.prepare_agent_worktree`).
  Running two agents on the same worktree is a race; the
  `in-flow join` cannot merge two agents that wrote to the
  same files at the same time.
- **Untested inline Conductor prompt rewrites.** The issue
  Conductor prompt is behavior, not copy. Keep prompt assembly in
  a pure helper that tests can assert directly, and add an
  integration-style loop test when the prompt depends on project
  memory, budget, language, or user steering context.
- **Calling private or nonexistent memory helpers from the
  Conductor loop.** The issue loop must load project memory
  through `ProjectConductor.get_or_create_state()`. A broad
  background-loop `except Exception` can otherwise hide missing
  method calls and silently remove team notes / warm summaries
  from the model prompt.

---

## Required Patterns

<!-- Patterns that must always be used -->

### Scenario: Unified Audit Log Role-Chain Read Contract

#### 1. Scope / Trigger

- Trigger: changing `GET /api/codex/audit-log`, `audit_log` serialization,
  Conductor turn audit writes, or frontend audit-log role-chain rendering.
- The audit page is a cross-layer observability contract: `audit_log` rows stay
  generic, while API serialization derives role and turn metadata for the UI.

#### 2. Signatures

- Writer helper: `_audit_conductor_turn(..., kind, payload, turn_index=None, sub_index=None)`.
- LLM runner helper: `build_llm_runner(..., audit_actor="auto_plan", audit_role="system_planner")`.
- Store helper: `list_codex_task_roles(task_ids: list[str]) -> dict[str, str]`.
- API: `GET /api/codex/audit-log` returns each item with the original audit row
  fields plus derived optional fields:
  `role`, `role_label`, `turn_index`, `sub_index`, `call_name`,
  `call_input`, `call_output`, `call_summary`.

#### 3. Contracts

- Existing audit fields and filters remain backwards compatible.
- Rows with `task_id` derive `role` from `codex_tasks.role`.
- Conductor `tool_use` rows derive target role from `payload.input.role`.
- Conductor `tool_result` rows derive target role from `payload.result.role` or
  `payload.result.task_id -> codex_tasks.role`.
- Conductor audit payloads must include `turn_index` and `sub_index` when the
  turn recorder knows them.
- Rows without a target role but with `conductor_task_id` group under
  `role="conductor"`.
- Taskless LLM rows must still have an intelligible role. `auto_plan` derives
  `role="system_planner"`, while project script suggestion / operations agent
  calls use `actor="operations_engineer"` and `role="operations"`.
- Successful `llm_return` payloads must include the final assistant text in
  `content` when available; the API exposes that text as `call_output`.
- Taskless `git_command` / `command_exec` rows group under `role="system"`,
  never the generic Agent fallback. If a command row has `task_id`, the task
  role wins.
- Command audit rows split command/cwd into `call_input` and
  `exit_code`/`stdout`/`stderr`/duration/refusal into `call_output`; stdout and
  stderr are outputs, not inputs.

#### 4. Validation & Error Matrix

- Missing or malformed `payload_json` -> derived fields are `null`/fallbacks;
  the row still returns.
- Unknown task id -> no task-derived role; conductor rows fall back to
  `conductor` only when appropriate.
- Unknown role key -> `role_label` is a title-cased fallback, not an error.
- Legacy taskless `auto_plan` row with no payload role -> API derives
  `role="system_planner"`; legacy rows cannot synthesize missing response
  text that was never persisted.
- LLM 200 response with no text content -> record `llm_return` with
  `status="error"` and `error="empty_content"`.
- Taskless command row -> `role="system"` and `role_label="System"` so the UI
  does not present operational git noise as an Agent call chain.
- Store unavailable -> existing audit endpoint `503` behavior remains.

#### 5. Good/Base/Bad Cases

- Good: `dispatch_subagent` tool use/result in turn 3 both render under the
  Architect role with input/output visible.
- Good: clicking project "AI fill commands" records operations LLM rows under
  Operations Engineer, and the LLM response text appears in output details.
- Base: a raw `git_command` audit row with no task still appears in the raw
  list, groups under System, and exposes stdout/stderr in `call_output`.
- Base: legacy `auto_plan` LLM rows without task or role group as System
  Planner rather than Unassigned.
- Bad: auditing only `usage` / `stop_reason` for `llm_return` and dropping the
  assistant text operators need to inspect.
- Bad: putting `stdout`, `stderr`, or `exit_code` inside `call_input`, which
  makes the details drawer look like commands have no output.
- Bad: adding audit table role columns when the value can be derived from task
  and conductor payloads.
- Bad: frontend re-parsing raw `payload_json` to infer role differently from
  the backend.

#### 6. Tests Required

- Backend endpoint test: task-linked row returns `role` / `role_label` and
  input details.
- Backend endpoint test: taskless `git_command` returns `role="system"`,
  command/cwd as `call_input`, and stdout/stderr/exit code as `call_output`.
- Backend endpoint test: task-linked `command_exec` preserves the task role and
  splits input/output fields.
- Backend endpoint test: operations `llm_return` returns
  `role="operations"`, `role_label="Operations Engineer"`, and model text as
  `call_output`.
- LLM runner test: successful Anthropic-compatible response records
  `llm_return.payload.content` after the prefilled `{` normalization.
- Backend endpoint test: conductor dispatch `tool_use` / `tool_result` returns
  role, turn index, input, output, and summary.
- Writer test: `_audit_conductor_turn` preserves `turn_index` and `sub_index`
  in the audit payload.
- Frontend pure helper test: audit records group by role and turn in call
  order, and taskless rows group as System / derived role rather than Agent or
  Unassigned.
- Frontend source or component test: audit page mounts the role-chain view while
  preserving raw rows.

#### 7. Wrong vs Correct

Wrong:

```python
return {"items": [entry.__dict__ for entry in page]}
```

Correct:

```python
payloads = {entry.id: _audit_payload_object(entry.payload_json) for entry in page}
task_roles = await _load_audit_task_roles(page, payloads)
return {"items": [{**serialize_row(entry), **_derive_audit_call_metadata(entry, payloads[entry.id], task_roles)} for entry in page]}
```

### Scenario: Safe Operational Diagnostics API

#### 1. Scope / Trigger

- Trigger: adding or changing machine-readable operational endpoints such as `GET /api/diagnostics`.
- These endpoints are cross-cutting support contracts: they inspect storage, runtime catalog, executors, websockets, and environment flags, so they must be safe to paste into support tickets and CI logs.

#### 2. Signatures

- API: `GET /api/diagnostics`
- Implementation location: `backend/app/interfaces/api.py`
- Success status: `200`
- Store unavailable status: `503` with detail `"SQLite store not available"`

#### 3. Contracts

- Top-level response fields: `service`, `status`, `generated_at`, `database`,
  `runtime_catalog`, `github_pr_followup`, `project_review_scheduler`,
  `executors`, `websockets`, `config`, `checks`.
- `status` is `"ok"` only when all checks are ok; use `"degraded"` when any check is degraded or errored but the endpoint can still return a snapshot.
- Supervisor snapshots such as `github_pr_followup` and
  `project_review_scheduler` produce degraded checks when `last_error` is set
  or when `running` is `true`; running-state details must be short generic
  messages, not project/issue/task content.
- Scheduler-style snapshots with `interval_s` and `last_completed_at` may also
  produce degraded stale checks when the last completion is older than twice the
  configured interval. Missing `last_completed_at` alone is not stale.
- Runtime catalog entries may expose booleans such as `api_endpoint_configured` and `api_key_configured`.
- Runtime catalog entries must not expose raw secret values, raw API keys, bearer tokens, auth headers, or provider credentials.
- Config fields should expose booleans for whether sensitive paths or env values are configured, not their raw values.

#### 4. Validation & Error Matrix

- `codex_store is None` -> HTTP `503`, detail `"SQLite store not available"`.
- Database query raises -> keep HTTP `200`, set `database.status = "error"`, append a database error check, and set top-level `status = "degraded"`.
- Runtime catalog load raises -> keep HTTP `200`, set `runtime_catalog.status = "error"`, append a runtime catalog error check, and set top-level `status = "degraded"`.
- Runtime catalog has no enabled executor -> keep HTTP `200`, append a degraded runtime catalog check, and set top-level `status = "degraded"`.
- Supervisor snapshot has `last_error` -> keep HTTP `200`, append a degraded
  supervisor check using that safe error text, and set top-level `status =
  "degraded"`.
- Supervisor snapshot has `running=true` and no error -> keep HTTP `200`,
  append a degraded supervisor check with a generic running-state detail, and
  set top-level `status = "degraded"`.
- Scheduler snapshot has `last_completed_at` older than `interval_s * 2` and
  no error/running state -> keep HTTP `200`, append a degraded stale check with
  a generic detail, and set top-level `status = "degraded"`.

#### 5. Good/Base/Bad Cases

- Good: report executor availability and `api_key_configured: true` without returning the key.
- Base: return zero counts and empty subscriber counts when no sessions, processes, or websocket subscribers exist.
- Bad: returning `api_key`, `OPENAI_API_KEY`, token strings, workspace root paths, or SQLite paths in the diagnostics payload.

#### 6. Tests Required

- Test that `GET /api/diagnostics` returns all top-level sections.
- Test that a configured runtime API key is represented only by `api_key_configured: true`.
- Test that the raw API key string is absent from the full serialized response body.
- Test the `503` behavior when `codex_store` is unavailable.

#### 7. Wrong vs Correct

Wrong:

```python
{"api_key": executor.api_key, "sqlite_db_path": os.getenv("SQLITE_DB_PATH")}
```

Correct:

```python
{
    "api_key_configured": bool(executor.api_key),
    "sqlite_db_path_configured": bool(os.getenv("SQLITE_DB_PATH")),
}
```

### Scenario: Runtime Catalog Secret Redaction

#### 1. Scope / Trigger

- Trigger: adding or changing runtime catalog APIs, settings UI payloads, executor credentials, or provider secret storage.
- Runtime catalog secrets are needed by backend execution paths, but read responses are consumed by multiple browser surfaces and must be treated as public data.

#### 2. Signatures

- API: `GET /api/runtime-catalog`
- API: `PUT /api/runtime-catalog`
- Storage model: `RuntimeExecutorConfig.api_key`
- Public response field: `api_key_configured: boolean`

#### 3. Contracts

- Stored catalogs may contain `api_key`.
- Browser-facing read/update responses must not include raw `api_key`.
- Browser-facing responses must expose `api_key_configured` so UI can show that a key exists.
- `PUT /api/runtime-catalog` must preserve an existing stored key when the request omits the `api_key` field for an executor.
- `PUT /api/runtime-catalog` may replace/clear a key only when the request explicitly includes `api_key`.

#### 4. Validation & Error Matrix

- `codex_store is None` -> HTTP `503`, detail `"SQLite store not available"`.
- Invalid catalog references -> HTTP `400`, validation detail.
- Request omits `api_key` for an existing executor -> save non-secret changes and preserve existing key.
- Request includes `api_key` -> save the supplied value, but return only `api_key_configured`.

#### 5. Good/Base/Bad Cases

- Good: settings UI changes a model name without deleting the stored key.
- Base: new executor without a key returns `api_key_configured: false`.
- Bad: returning raw API keys from `GET /api/runtime-catalog` or keeping raw keys in frontend app state after save.

#### 6. Tests Required

- Test that `GET /api/runtime-catalog` and `PUT /api/runtime-catalog` responses never contain the raw key string.
- Test that public responses omit `api_key` and include `api_key_configured`.
- Test that an update payload omitting `api_key` preserves the previously stored key.

#### 7. Wrong vs Correct

Wrong:

```python
return await service.load_catalog()
```

Correct:

```python
catalog = await service.load_catalog()
return {
    "executors": [
        {"id": executor.id, "api_key_configured": bool(executor.api_key)}
        for executor in catalog.executors
    ]
}
```

### Scenario: Safe Knowledge Search Snippets

#### 1. Scope / Trigger

- Trigger: adding/changing FTS snippets, knowledge search responses, artifact previews, or frontend `dangerouslySetInnerHTML` rendering.
- FTS snippets include indexed issue/artifact text, which can contain user-authored HTML.

#### 2. Signatures

- Backend helper: `_sanitize_fts_snippet(snippet: str | None) -> str`
- Search response fields: `issues[].snippet`, `artifacts[].snippet`
- Frontend render target: knowledge search result snippets

#### 3. Contracts

- Snippets may preserve backend-generated `<mark>` and `</mark>` tags only.
- All indexed text from issues/artifacts must be HTML-escaped before reaching a browser HTML sink.
- Frontend components must not render raw issue/artifact text through `dangerouslySetInnerHTML` unless the backend contract guarantees sanitization.

#### 4. Validation & Error Matrix

- Empty snippet -> empty string.
- Snippet contains user HTML such as `<img onerror=...>` -> escaped text such as `&lt;img ...&gt;`.
- Snippet contains FTS-generated `<mark>` tags -> preserve those exact tags.
- Snippet contains non-mark tags from indexed content -> escape them.

#### 5. Good/Base/Bad Cases

- Good: `&lt;img src=x onerror=alert(1)&gt; <mark>token</mark>`.
- Base: plain text snippets render unchanged except for escaped HTML characters.
- Bad: `<img src=x onerror=alert(1)> <mark>token</mark>` reaches `dangerouslySetInnerHTML`.

#### 6. Tests Required

- Test that malicious indexed HTML is escaped in artifact snippets.
- Test that `<mark>` highlighting remains available after sanitization.
- Test both issue and artifact snippet paths when modifying shared snippet logic.

#### 7. Wrong vs Correct

Wrong:

```python
{"snippet": row["snippet"]}
```

Correct:

```python
{"snippet": _sanitize_fts_snippet(row["snippet"])}
```

### Scenario: Safe Skill Proxy Fetching

#### 1. Scope / Trigger

- Trigger: adding or changing remote skill preview fetching, URL rewriting, or CORS proxy behavior.
- The proxy runs server-side with local network access, so it must not become a generic URL fetcher.

#### 2. Signatures

- API: `GET /api/skills/proxy?url=<absolute http(s) URL>`
- Helpers: `_rewrite_to_raw(url: str) -> str`, `_validate_skill_proxy_url(url: str) -> str`
- Allowed upstream hosts: `raw.githubusercontent.com`, `gist.githubusercontent.com`

#### 3. Contracts

- Browser-facing callers may pass common GitHub/Gist view URLs; the backend may rewrite them to raw URLs.
- After rewriting, the final target host must be in the allowlist before any network request is made.
- The proxy must not follow redirects, because redirects can leave the allowlisted host after validation.
- The proxy returns markdown text only; HTML content types are rejected.

#### 4. Validation & Error Matrix

- Missing or non-http(s) URL -> HTTP `400`.
- Host outside allowlist, including loopback/private/local hosts -> HTTP `400`, detail contains `"not allowed"`.
- Upstream redirect -> HTTP `400`.
- Upstream HTTP error -> matching upstream status.
- Upstream HTML content type -> HTTP `415`.

#### 5. Good/Base/Bad Cases

- Good: `https://github.com/owner/repo/blob/main/SKILL.md` rewrites to `https://raw.githubusercontent.com/...` and fetches markdown.
- Base: `https://gist.github.com/user/<id>` rewrites to `https://gist.githubusercontent.com/.../raw`.
- Bad: `http://127.0.0.1:8000/secret.md`, cloud metadata IPs, or arbitrary intranet URLs are fetched.

#### 6. Tests Required

- Test that loopback/private URLs are rejected before fetch.
- Test GitHub/Gist view URL rewriting still produces an allowed raw host.
- Test redirects are rejected when proxy behavior changes.

#### 7. Wrong vs Correct

Wrong:

```python
async with httpx.AsyncClient(follow_redirects=True) as client:
    return await client.get(url)
```

Correct:

```python
target = _validate_skill_proxy_url(_rewrite_to_raw(url))
async with httpx.AsyncClient(follow_redirects=False) as client:
    return await client.get(target)
```

### Scenario: Issue Orchestration Policy Contract

#### 1. Scope / Trigger

- Trigger: adding or changing deterministic Conductor scheduling policy, the issue policy endpoint, or frontend policy display surfaces.
- The policy is a cross-layer contract: backend classification steers the Conductor prompt and the browser displays the same policy without reimplementing heuristics.

#### 2. Signatures

- Classifier: `classify_issue_orchestration(title: str | None, description: str | None) -> OrchestrationPolicy`
- Prompt helper: `render_issue_orchestration_policy_block(title: str | None, description: str | None) -> str`
- API: `GET /api/codex/issues/{issue_id}/orchestration-policy`

#### 3. Contracts

- Response fields: `issue_id: string`, `recommendation: string`, `batch_allowed: boolean`, `signals: string[]`, `guidance: string[]`.
- Known recommendation values: `pm_first`, `architect_first`, `batch_allowed`, `single_engineer`.
- Known signal values: `explicit_parallel`, `independent_slices`, `trivial`, `ambiguous_scope`, `risk_or_cross_layer`, `default_serial`.
- The backend classifier is the source of truth. Frontend code may derive display tone/copy from the response, but must not duplicate scheduling heuristics.
- `batch_allowed=true` is only valid when the issue explicitly asks for parallel work and the classifier detects independent slices.

#### 4. Validation & Error Matrix

- `codex_store is None` -> HTTP `503`, detail `"SQLite store not available"`.
- Issue id does not exist -> HTTP `404`, detail contains the issue id.
- Empty or underspecified issue text -> `pm_first`, `batch_allowed=false`, includes `ambiguous_scope`.
- Risky/cross-layer issue text -> `architect_first`, `batch_allowed=false`, includes `risk_or_cross_layer`.
- Explicit parallel independent issue text -> `batch_allowed`, `batch_allowed=true`, includes `explicit_parallel` and `independent_slices`.
- Small/trivial issue text -> `single_engineer`, `batch_allowed=false`, includes `trivial`.

#### 5. Good/Base/Bad Cases

- Good: Conductor prompt and UI panel both reflect the same classifier result for the same issue title/description.
- Base: A normal clear issue returns `single_engineer` and `batch_allowed=false`.
- Bad: frontend infers `batch_allowed=true` from keywords without calling the backend endpoint.

#### 6. Tests Required

- Unit-test classifier branches for trivial, ambiguous, risky/cross-layer, and explicit independent parallel issues.
- Test prompt rendering includes recommendation, batch allowance, signals, and guidance.
- Test the endpoint returns the stable response shape, `404` for missing issues, and `503` when the store is unavailable.
- Frontend tests must assert the typed client URL-encodes issue ids and display derivation consumes the response shape without adding scheduling heuristics.

#### 7. Wrong vs Correct

Wrong:

```typescript
const batchAllowed = issue.description.includes("parallel");
```

Correct:

```typescript
const policy = await getIssueOrchestrationPolicy(issue.id);
const batchAllowed = policy?.batch_allowed ?? false;
```

### Scenario: LLM HTTP Client Environment Isolation

#### 1. Scope / Trigger

- Trigger: creating or changing outbound HTTP clients used for LLM provider calls.
- LLM calls run from the local desktop environment, where `NO_PROXY` / proxy variables may contain OS- or shell-specific values such as bare IPv6 loopback entries.

#### 2. Signatures

- Helper: `_llm_http_client(timeout_s: float) -> httpx.AsyncClient`
- Call sites: Anthropic-compatible and OpenAI-compatible requests in `application/llm_runner.py`.

#### 3. Contracts

- LLM provider clients must pass `trust_env=False`.
- Timeout is still supplied explicitly by the caller.
- This rule applies to LLM provider traffic only; generic API clients keep their own security and redirect rules.

#### 4. Validation & Error Matrix

- `NO_PROXY` contains bare IPv6 entries such as `::1` -> client construction must not raise.
- Provider request times out -> existing timeout handling logs and returns the fallback result.
- Provider returns non-JSON or HTTP error -> existing sanitized error handling applies.

#### 5. Good/Base/Bad Cases

- Good: LLM call succeeds or fails based on provider behavior, not local proxy parsing.
- Base: unset proxy environment behaves the same as before.
- Bad: `httpx.AsyncClient(...)` inherits a local `NO_PROXY` value and crashes before the provider request is sent.

#### 6. Tests Required

- Test that constructing the LLM HTTP client ignores invalid local proxy bypass entries.
- Test streaming/non-streaming call behavior through the shared helper when adding new LLM request paths.

#### 7. Wrong vs Correct

Wrong:

```python
async with httpx.AsyncClient(timeout=timeout_s) as client:
    ...
```

Correct:

```python
async with _llm_http_client(timeout_s) as client:
    ...
```

### Scenario: WebSocket Initial Send Disconnects

#### 1. Scope / Trigger

- Trigger: sending initial WebSocket snapshot/replay frames before the endpoint enters a shared subscriber loop.
- Browser navigation can close the socket immediately after `accept()`, before subscriber cleanup code has been installed.

#### 2. Signatures

- Endpoint shape: `async def <stream>(websocket: WebSocket, ...)`
- Guard helper shape: `_send_*_initial_*(websocket, state) -> bool`

#### 3. Contracts

- Initial snapshot/replay sends must catch `WebSocketDisconnect` and return without registering a subscriber.
- Subscriber loops may still catch `WebSocketDisconnect` at their own boundary.
- A normal browser disconnect must not become an ASGI application exception.

#### 4. Validation & Error Matrix

- Client disconnects during initial snapshot send -> endpoint returns quietly.
- Client remains connected -> endpoint registers subscriber and enters the normal sender/receiver loop.
- Store/resource is missing before accept -> existing close code and reason still apply.

#### 5. Good/Base/Bad Cases

- Good: fast route changes produce normal `connection closed` logs only.
- Base: initial snapshot and `Ready` frame are sent before subscribing.
- Bad: `await websocket.send_json(...)` before the subscriber loop lets `WebSocketDisconnect` escape to uvicorn.

#### 6. Tests Required

- Unit-test the initial-send helper with a fake WebSocket that raises `WebSocketDisconnect`.
- Keep backpressure/subscriber tests covering queue overflow and clean terminal closes.

#### 7. Wrong vs Correct

Wrong:

```python
await websocket.send_json(snapshot)
sub = WsSubscriber(websocket, maxsize=WORKSPACE_QUEUE_MAXSIZE)
```

Correct:

```python
if not await _send_workspace_initial_snapshot(websocket, state):
    return
sub = WsSubscriber(websocket, maxsize=WORKSPACE_QUEUE_MAXSIZE)
```

### Scenario: Artifact File Boundary Safety

#### 1. Scope / Trigger

- Trigger: scanning issue artifact folders, backfilling artifact rows, reading artifact preview content, or building artifact zip downloads.
- Artifact paths can come from disk scans or persisted rows, so every file read/archive path needs a filesystem boundary check.

#### 2. Signatures

- Scanner: `_scan_and_backfill_artifacts(issue_id: str, session_id: str, store) -> list[dict]`
- Roots helper: `_artifact_issue_roots(issue_id: str, session_id: str, store) -> list[Path]`
- Guard helper: `_is_safe_artifact_file(path: Path, roots: list[Path]) -> bool`
- Preview API: `GET /api/codex/issues/{issue_id}/artifacts`
- Download API: `GET /api/codex/issues/{issue_id}/artifacts/download`

#### 3. Contracts

- An artifact file is safe only when it is a regular file, not a symlink, and its resolved path remains under one of the issue artifact roots.
- Directory traversal must not follow symlinked directories.
- Artifact preview must re-check persisted artifact paths before returning a row or reading content.
- Zip download must re-check persisted artifact paths instead of trusting database rows.
- Stores used in tests may omit task-list methods; root discovery must still fall back to the workspace issue root.

#### 4. Validation & Error Matrix

- Symlink file -> skip.
- Symlink directory -> skip.
- Regular file resolving outside issue roots -> skip.
- Missing file or unreadable file -> skip.
- No artifacts after filtering -> return an empty zip when rows existed but no safe files remained.

#### 5. Good/Base/Bad Cases

- Good: `issues/<issue_id>/pm/prd.md` is scanned and zipped.
- Base: stale DB row pointing to a deleted file is ignored.
- Bad: `issues/<issue_id>/pm/leak.md -> /tmp/secret.md` is scanned, indexed, previewed, or zipped.

#### 6. Tests Required

- Test scan skips symlinks that point outside the issue root.
- Test preview skips symlink artifact rows.
- Test zip skips symlink artifact rows.
- Test regular artifacts under the issue root still zip correctly.

#### 7. Wrong vs Correct

Wrong:

```python
if path.exists() and path.is_file():
    zf.write(path, arcname)
```

Correct:

```python
if _is_safe_artifact_file(path, safe_roots):
    zf.write(path, arcname)
```

---

### Scenario: Worktree-Scoped Branch Merge (Swarm-Safe)

#### 1. Scope / Trigger

- Trigger: merging a source branch into a target branch when the target branch is **NOT checked out in the primary repo** but lives in a separate `git worktree` (the parallel-swarm case: agent branches merge back into the issue integration branch, which is checked out in the issue worktree while the primary repo sits on `main`).
- Why code-spec depth: this is a destructive git operation that, done naively, **silently advances the primary repo's checked-out branch (`main`)** onto unreviewed changes — bypassing the human review gate. Discovered empirically during PR3 of `05-29-parallel-swarm-scheduler` (real-git repro: `main` fast-forwarded onto agent changes).

#### 2. Signatures

```python
# git_service.py
async def squash_merge(repo, source_branch, base_branch, message) -> str
#   ^ fast-forwards the PRIMARY repo (assumes base_branch is checked out there).
#     Safe ONLY for the issue→default merge (merge_issue, base=main checked out in primary repo).

async def squash_merge_into_branch(
    repo, source_branch, target_branch, message, target_worktree_path=None
) -> str
#   ^ swarm-safe: squash-merges in a throwaway DETACHED temp worktree,
#     advances ONLY refs/heads/<target_branch> via update-ref,
#     resets the target worktree's index/tree ONLY if it has target_branch checked out.
#     NEVER touches the primary repo's checked-out branch.
```

#### 3. Contracts

- `squash_merge_into_branch` advances exactly one ref: `refs/heads/<target_branch>`. The primary repo's `HEAD`/working tree is invariant.
- Conflict → `reset --hard` in the temp worktree + raise `GitError`; no half-state, no partial ref move.
- `target_worktree_path` index sync happens **iff** that worktree actually has `target_branch` checked out (else a bare `update-ref` leaves the worktree index stale → phantom deletions on next `commit_all`).

#### 4. Validation & Error Matrix

- target branch checked out in primary repo (issue→default) → use `squash_merge` (fast-forward is correct there).
- target branch checked out in a worktree, primary on another branch → use `squash_merge_into_branch` (plain `squash_merge` would pollute the primary branch).
- merge conflict → `GitError` raised; caller collects `conflicted_files` + `worktree_diff` and surfaces for reconcile; already-merged refs are NOT rolled back.

#### 5. Good/Base/Bad Cases

- Good: agent branch → issue branch via `squash_merge_into_branch`; `main` byte-for-byte unchanged, issue branch accumulates, issue worktree clean.
- Base: issue branch → `main` via `squash_merge` (primary repo on `main`).
- Bad: agent branch → issue branch via plain `squash_merge`; `main` silently fast-forwards onto unreviewed agent changes.

#### 6. Tests Required

- Regression: after merging ≥2 agent branches into the issue branch, assert the default branch ref **and tree** are unchanged and contain none of the agent files (`test_merge_agent_worktrees_does_not_pollute_default_branch`).
- Conflict: stop-on-first-conflict, conflicting worktree kept, earlier merges not rolled back, structured `conflicted_files`+diff returned.
- No temp/probe worktree leaks across success/conflict/cleanup paths.

#### 7. Wrong vs Correct

Wrong:

```python
# target (issue branch) lives in a worktree, primary repo is on main:
await git.squash_merge(repo, agent_branch, issue_branch, msg)  # ff's main onto agent work
```

Correct:

```python
await git.squash_merge_into_branch(
    repo, agent_branch, issue_branch, msg,
    target_worktree_path=issue.git_worktree_path,
)
```

#### 8. Terminal-state swarm cleanup (resource hygiene)

- `dispatch_batch` retains per-agent `swarm/<issue.id[:8]>-*` branches + `swarm-<issue.id>-*` worktrees on the conflict / non-merged path (intentional — for reconcile). Their cleanup owner is the conductor terminal seal: `worktree_manager.cleanup_issue_swarm_worktrees(project, issue)`, called best-effort at the end of `_seal_graph_and_issue_status` (`conductor_main_loop.py`).
- Contract: enumerate residuals from **real git state** (`git worktree list` + `git branch --list 'swarm/<prefix>*'`), NOT in-memory lineage (not persisted; gone at terminal time). Discovery prefixes MUST byte-match creation (`_worktree_path` / `_agent_branch_name`): dir uses full `issue.id`, branch uses `issue.id[:8]`.
- HARD: only removes worktrees + force-deletes `swarm/*` refs (`git branch -D`, regex-gated). NEVER merge/checkout/advance `main` or the issue branch. Idempotent + best-effort: missing residuals skip silently; a cleanup failure logs a warning and never blocks the terminal seal.
- Tests: real-git integration asserting residual worktree+branch removed, `git rev-parse main` byte-identical before/after, sibling-issue swarm branches survive (issue-scoped discovery).

---

### Scenario: Isolated Worktree Upstream Visibility

#### 1. Scope / Trigger

- Trigger: forking a per-agent worktree (`prepare_agent_worktree`, base = issue branch) for parallel fan-out where the agent must see upstream artifacts (PM/architect output) produced earlier in the same issue.
- Why: a worktree forked from a branch sees **only what is committed to that branch**. Upstream roles write artifacts into the shared issue worktree but do not auto-commit, so a freshly forked agent worktree would see a stale tree.

#### 2. Signatures

```python
# worktree_manager.py
async def commit_issue_worktree(issue, message=None) -> str | None
#   flush the shared issue worktree's uncommitted changes onto the issue branch.
async def prepare_agent_worktree(project, issue, agent_key) -> (branch, path, base)
```

#### 3. Contracts

- `commit_issue_worktree` MUST run **before** `prepare_agent_worktree` in any fan-out path.
- Idempotent: returns `None` when there is nothing to commit.

#### 4. Validation & Error Matrix

- uncommitted upstream artifacts present → commit them, then fork → agent sees them.
- nothing to commit → `None`, fork proceeds.
- issue has no `git_branch` yet → `prepare_agent_worktree` raises `WorktreeError` (prepare the issue worktree first).

#### 5. Good/Base/Bad Cases

- Good: `dispatch_batch` flushes once, then forks N agent worktrees that all see upstream output.
- Bad: fork first, then agent reads `task.workspace_path` and misses uncommitted upstream artifacts.

#### 6. Tests Required

- Assert a forked agent worktree contains an upstream artifact that was uncommitted in the issue worktree before the batch (flush-then-fork).
- Assert `commit_issue_worktree` is idempotent (`None` on clean tree).

#### 7. Wrong vs Correct

Wrong:

```python
wt = await wm.prepare_agent_worktree(project, issue, key)  # forks stale tree
```

Correct:

```python
await wm.commit_issue_worktree(issue)                      # flush upstream first
wt = await wm.prepare_agent_worktree(project, issue, key)
```

---

### Scenario: Cost / Budget Is Soft, Not a Hard Gate

#### 1. Scope / Trigger

- Trigger: anything touching issue cost aggregation, per-model pricing, or budget-driven Conductor behavior (`budget_service.py`, `usage_utils.price_tokens`, `dispatch_batch` concurrency).
- Why code-spec depth: budget is **advisory** — it steers via prompt + concurrency, it must NEVER hard-kill the loop. A future dev "tightening" this into a hard stop would break the design contract. Also, naive cost aggregation double-counts.

#### 2. Signatures

```python
# usage_utils.py
def price_tokens(input_tokens, output_tokens, cache_read_tokens, pricing=None) -> float
#   pricing: RuntimeModelConfig|dict|None. Per-rate: model price if set, else global env rate.
def price_tokens_for_model(model, ...) -> float

# budget_service.py
def aggregate_issue_spend_usd(store, issue_id) -> float   # COMPLETED runs only
def budget_steering_event(status) -> dict | None          # None when no ceiling / healthy

# timeouts.py
def resolve_issue_budget_usd(issue_budget) -> float       # None -> global default; 0 -> unlimited
def budget_supported_concurrency(remaining, configured_cap, over_budget) -> int
```

#### 3. Contracts

- `price_tokens(pricing=None)` is byte-identical to the legacy global-rate path (backward compat). Per-rate fallback: a model with only `input_usd_per_m` set uses env rates for output/cache.
- Spend aggregation counts only `ExecutionProcess.status in {Completed, Failed, Killed}` — never `Running` (its `total_cost_usd` is not final).
- `budget_usd`: `None` → global default; `0` → unlimited (no warnings, no wind-down, no concurrency squeeze).
- `budget_supported_concurrency` only ever **lowers** the cap: `min(cap, floor(remaining / EST_COST_PER_AGENT_USD))`, clamped ≥ 1; `remaining is None` (unlimited) → cap unchanged; `over_budget` → 1.

#### 4. Validation & Error Matrix

- spend ≥ `BUDGET_SOFT_WARN_RATIO * budget` → `budget_warning` event + WARNING-tone block (no kill).
- spend ≥ budget (over) → `budget_exceeded` event + wind-down steer toward `finalize_task` (no kill).
- aggregation / price collection / concurrency calc raises → best-effort: omit budget block / fall back to configured cap; loop and batch proceed.
- budget = 0 (unlimited) → no events, no squeeze, no false "over".

#### 5. Good/Base/Bad Cases

- Good: over budget → loop keeps running, gets a strong wind-down steer, batch concurrency drops to 1.
- Base: healthy budget → neutral block, configured cap, no events.
- Bad: over budget hard-kills the loop or forces batch concurrency to 0 — violates the soft-semantics contract.

#### 6. Tests Required

- price: per-rate model pricing + env fallback (priced + partial + unpriced regression).
- aggregation: a `Running` process is excluded from the sum.
- soft semantics: over-budget loop still returns `status="done"` (asserted no hard kill).
- concurrency: tight budget downscales effective `dispatch_batch` peak (≥1); unlimited does not.

#### 7. Wrong vs Correct

Wrong:

```python
if status.over_budget:
    raise BudgetExceeded()        # hard-kills the loop — violates the contract
spent = sum(p.total_cost_usd for p in all_processes)   # counts Running → double-count
```

Correct:

```python
if (ev := budget_steering_event(status)):
    emit(ev)                      # soft: event + prompt steer, loop continues
spent = aggregate_issue_spend_usd(store, issue_id)     # completed runs only
```

---

### Scenario: Engineer/QA Real-Codegen Reconciliation (Claim vs Git Ground Truth)

#### 1. Scope / Trigger

- Trigger: changing how the Engineer persists its report (`EngineerWorkflow.persist_result`) or how QA reconciles its verdict (`QAWorkflow.persist_result`) against the real worktree git diff.
- Why code-spec depth: an Engineer (LLM) can declare victory while only writing a markdown report, or misname the files it touched. The framework treats the git diff as ground truth and reconciles deterministically. The hard/soft split must follow the repo philosophy: claim-vs-reality contradiction is a HARD fact; everything else is a SOFT signal that never hard-kills.

#### 2. Signatures

```python
# engineer_workflow.py
def git_changed_files(workspace_path: str | None) -> list[str]   # module-level, single source of truth
class EngineerWorkflow:
    def _apply_diff_cross_check(self, report, actually_changed: list[str]) -> None  # in-place C1 + C2
    @staticmethod
    def _claims_implementation(report) -> bool

# qa_workflow.py
class QAWorkflow:
    @staticmethod
    def _git_cross_check(current_status, workspace_path, issue_id) -> tuple[str, str | None]  # D1
```

#### 3. Contracts

- **C1 (downgrade, HARD):** a report that *claims it landed code* — status ∈ {completed, partial} AND a non-empty `changed_files` (it named files it claims to have modified) — but produces a ZERO real git diff is downgraded to `partial`, `changed_files` cleared, and a `[framework]` qa_note prepended. Covers BOTH `completed` and `partial`.
- **`completed_tasks` is NOT a C1 hard trigger:** the only unambiguous code-landing signal is a non-empty `changed_files`. An honest `changed_files=[]` already-implemented report legitimately lists the task it addressed in `completed_tasks` (the task WAS handled, just without new code), so treating `completed_tasks` as a landing claim would downgrade an honest "already implemented" report (AC4 violation). This is the identical definition of a code-landing claim used by the Architect-Review guard (`review_guard.compute_review_guard` uses `bool(claimed_set)` only) — one consistent notion across the chain.
- **Legal empty diff is NOT a claim:** status=blocked, or `changed_files=[]` (already-implemented / nothing-to-change, with or without `completed_tasks`), is honest and left untouched by C1. The hard trigger is the claim-vs-reality contradiction (named changed files vs zero diff), never "diff is empty". The already-implemented empty-diff case is surfaced only by the SOFT D1 / LLM layers, never by a C1 status downgrade.
- **C2 (reconcile, ground truth):** when real changes DO exist, the report's `changed_files` is overwritten with the actual git-diff set whenever it diverges (after `./`-stripping path normalization), plus a `[framework]` qa_note recording claimed-vs-actual. No divergence → list left verbatim, no note (no noise).
- **D1 (QA soft signal):** layered ON TOP of the command reconcile. If the Engineer report implies implementation (status != blocked, or has completed_tasks) but the worktree shows zero diff, QA bumps to `needs_follow_up` — even when the Engineer recommended no commands. NEVER weakens a `failed` (real non-zero command exit is the stronger fact) and never hard-kills.
- `git_changed_files` is the one base-fallback implementation (origin/main → main → HEAD~1); Engineer cross-check, review guard, and QA D1 all reuse it.

#### 4. Validation & Error Matrix

- claims implementation + zero diff → C1 downgrade to partial + note.
- partial + real (matching) diff → untouched.
- completed/partial + honest `changed_files=[]` + zero diff → NOT flagged by C1 (legal already-implemented / blocked), whether or not `completed_tasks` is listed.
- claimed files ≠ actual files (real changes exist) → C2 rewrite to actual + note; claimed == actual → no note.
- QA: engineer implies impl + zero diff + no commands → `needs_follow_up`. Engineer blocked / real changes → no bump. Command non-zero exit → stays `failed` regardless of D1.

#### 5. Good/Base/Bad Cases

- Good: Engineer claims `[a.py]`, git shows `[b.py]` → report rewritten to `[b.py]` with a reconcile note; review/QA see the truth.
- Base: honest "already implemented, nothing to change" (status=completed, `changed_files=[]`) survives untouched by C1 — even when it lists the addressed task in `completed_tasks`.
- Bad: hard-rejecting / downgrading the legal empty-diff already-implemented case, or letting D1 override a real command failure.

#### 6. Tests Required

- C1: completed+zero-diff downgrade; partial+zero-diff(claiming files) downgrade; legal empty `changed_files` (completed & partial, incl. with completed_tasks) NOT flagged; partial+real-diff untouched.
- C2: claimed≠actual rewrite + note; claimed==actual no note.
- D1: implies-impl + zero diff + no commands → needs_follow_up; real changes → no bump; blocked engineer → no bump; non-zero command exit stays failed (reconcile not regressed).

#### 7. Wrong vs Correct

Wrong:

```python
if report.status == "completed" and not git_changed_files(ws):  # misses partial; ignores claimed files
    report.status = "partial"
```

Correct:

```python
actually_changed = git_changed_files(ws)
self._apply_diff_cross_check(report, actually_changed)  # C1 (completed+partial) + C2 reconcile
```

---

### Scenario: Architect-Review Deterministic Tiered Guard (diff-vs-plan)

> The Architect-Review-side counterpart of *Engineer/QA Real-Codegen Reconciliation* above.
> Same one notion of a code-landing claim (`bool(claimed_changed_files)`), same single
> `git_changed_files` base-fallback. This scenario covers the **review decision**, not the report.

#### 1. Scope / Trigger

- Trigger: an engineer→architect review task (`task_kind="review"`, has `parent_task_id`) is about to be dispatched, OR an architect review prompt is being built. Before this guard the review LLM saw only requirement / system_design / implementation_report markdown — **zero git ground truth** — so "report claims work, code is empty" survived on luck. This guard makes the claim-vs-reality check deterministic and feeds the real diff to the LLM.
- Cross-layer: reads git (worktree), `implementation_plan.json` (architect artifact), the engineer report, and short-circuits an API dispatch path → code-spec depth mandatory.

#### 2. Signatures

```python
# review_guard.py  (pure, synchronous, read-only — safe to call inside sync prompt-build)
def compute_review_guard(workspace_path: str | None, issue_id: str,
                         *, include_diff_summary: bool = True) -> ReviewGuardResult
#   ReviewGuardResult: {verdict: "hard_mismatch"|"plan_drift"|"ok",
#                       claimed_files, actual_files, expected_files,
#                       missing, extra, diff_summary}

# architect_workflow.py
class ReviewReportDocument(BaseModel):
    ...
    framework_guard: dict | None = None   # B5; default None = backward compatible

# api.py
async def submit_codex_task_for_review(task_id): ...   # B2 short-circuit lives here, BEFORE run_codex_task
def _apply_automated_review_to_parent(parent_task, artifact) -> None   # shared by LLM + synthetic-reject paths
```

#### 3. Contracts

- **Ground truth (deterministic):** actual changed files come from the single `git_changed_files` (origin/main → main → HEAD~1 fallback, includes untracked via `git status --porcelain`). `diff_summary` is a truncated real-diff text. `expected_files` is the union of `ImplementationTask.expected_files` from `implementation_plan.json` (tolerant of legacy artifacts → `[]`). All paths normalized repo-relative, leading `./` stripped, before comparison.
- **HARD (`hard_mismatch`) — claim-vs-reality contradiction:** report claims it landed code (non-empty `claimed_changed_files`, same `bool(claimed_set)` definition as Engineer C1 — `completed_tasks` is NOT a signal) but actual git diff is empty. → In `submit_codex_task_for_review`, **before** `run_codex_task`, write a synthetic `ReviewReportDocument(decision="reject", reason="[FRAMEWORK] report-claim mismatch…", framework_guard=…)`, apply it to parent (`status="rework"` + `[FRAMEWORK]` `review_comment`) via `_apply_automated_review_to_parent`, mark the review task done, and `return`. **The LLM is never invoked.**
- **Legal empty diff (AC4):** honest `changed_files=[]` (already-implemented / blocked) with zero diff is NOT `hard_mismatch` — the LLM review IS dispatched (it still sees the empty diff via injected context). The hard trigger is the contradiction, never "diff is empty".
- **SOFT (`plan_drift`):** real changes exist but diverge from `expected_files` (missing and/or extra). → NOT a short-circuit. `{expected, actual, missing, extra}` + `diff_summary` are injected into `_build_review_prompt` as an explicitly-labelled SOFT signal; the LLM weighs it (architect's pre-code file prediction is best-effort, not a contract). Empty `expected_files` → soft layer skipped, only the hard layer applies.
- **Artifact (B5):** the guard verdict/missing/extra is recorded on `ReviewReportDocument.framework_guard` (default `None` keeps old artifacts valid).

#### 4. Validation & Error Matrix

- claimed non-empty + zero diff → `hard_mismatch` → deterministic reject, `run_codex_task` NOT called, parent `rework`.
- honest `changed_files=[]` + zero diff (already-implemented/blocked) → NOT hard; LLM dispatched, parent stays `awaiting_review`.
- real changes + `expected_files` has missing/extra → `plan_drift` → soft inject, no short-circuit.
- real changes == expected (or expected empty) → `ok` → normal LLM review with real diff in context.
- legacy `implementation_plan.json` without `expected_files` → treated as `[]`, soft layer skipped, no error.

#### 5. Good/Base/Bad Cases

- Good: engineer report claims `[api.py]`, worktree diff empty → review auto-rejected with `[FRAMEWORK]` reason, no model tokens spent, engineer goes back to `rework`.
- Base: honest "already implemented" review (claimed `[]`, empty diff) → dispatched to the LLM with the empty diff visible; the model, not the framework, decides.
- Bad: short-circuiting the legal empty-diff case (AC4 regression), or building the review prompt without the real diff so the LLM judges blind again.

#### 6. Tests Required

- `hard_mismatch`: end-to-end `submit_codex_task_for_review` with `run_codex_task` monkeypatched → assert `call_count == 0`, `verdict == "hard_mismatch"`, parent `rework` + `[FRAMEWORK]` comment.
- legal-empty (AC4 lock): honest `changed_files=[]` + completed_tasks + zero diff → assert `run_codex_task` `call_count == 1`, `verdict != "hard_mismatch"`.
- `plan_drift`: real change vs `expected_files` missing → `verdict == "plan_drift"`, prompt context contains the missing entry + real diff, no short-circuit.
- untracked new file counted (no false `hard_mismatch`); path normalization `./a.py == a.py`; swarm per-agent worktree base-fallback computes the real change without touching `main`.

#### 7. Wrong vs Correct

Wrong:

```python
# guard only in prompt text → LLM already invoked; cannot save the tokens, and a blind
# reject depends on the model noticing "changed files: None" in prose.
prompt = _build_review_prompt(task)          # LLM runs regardless
```

Correct:

```python
guard = compute_review_guard(task.workspace_path, issue_id)
if guard.verdict == "hard_mismatch":         # BEFORE run_codex_task
    artifact = ReviewReportDocument(decision="reject", reason="[FRAMEWORK] …", framework_guard=guard.as_dict())
    _apply_automated_review_to_parent(parent_task, artifact)
    return                                   # LLM never invoked (AC3)
await run_codex_task(review_task_id)         # ok / plan_drift → LLM sees real diff via injected context
```

---

### Scenario: Unified Audit Log (single-writer, additive, best-effort)

#### 1. Scope / Trigger
- Trigger: recording any LLM call / agent return / tool call / command execution / git op / CLI spawn / generic event for after-the-fact auditing. New DB table + cross-cutting choke-point instrumentation + read API → code-spec depth mandatory.
- Additive: existing rich records (`conductor_turns`, `log_events`, QA `commands_run`) are NOT removed; `audit_log` is one uniform, queryable view layered on top. It deliberately accepts duplication with those tables (a product decision) in exchange for one place to query.

#### 2. Signatures
```python
# audit_logger.py  (singleton, single write entry-point — NEVER write audit_log directly elsewhere)
audit_logger.record(category, *, actor=None, issue_id=None, task_id=None,
    conductor_task_id=None, execution_process_id=None, correlation_id=None,
    status=None, duration_ms=None, payload=None, error=None) -> None  # fire-and-forget, never raises
# categories: llm_call|llm_return|tool_use|tool_result|command_exec|git_command|cli_spawn|event|agent_finalize

# adapters/audit_log_query.py  (shared by both stores — keeps SQL byte-identical)
build_audit_log_query(*, categories, issue_id, task_id, since, until, q, cursor_*, limit) -> (sql, params)
# api.py
GET /api/codex/audit-log?category=&issue_id=&task_id=&since=&until=&q=&cursor=&limit=  -> {items, next_cursor}
```

#### 3. Contracts
- **Single writer**: every choke point routes through `audit_logger.record`. No scattered `save_audit_log` calls (prevents the double-write drift the unified-table choice risks).
- **Async, non-blocking, best-effort**: `record` is pure enqueue onto a bounded `asyncio.Queue` drained by a background worker (mirrors `EventBus._db_worker`). Enqueue is loop-aware — `call_soon_threadsafe` when called off the worker's loop thread (asyncio.Queue is NOT thread-safe; a plain cross-thread `put_nowait` silently stalls the row). Failures log a warning and are swallowed — NEVER raised into the audited hot path. Shutdown flushes (sentinel) BEFORE the store closes.
- **Bounded + drop**: queue has `maxsize` (drop-newest on saturation) + a `dropped` counter; audit is best-effort, so dropping under load beats OOM. Required because `event_bus.append` is high-frequency.
- **Call-level granularity (NOT line-level)**: one row per call/command/event. Per-line stdout/stderr stays in `log_events`, linked via `execution_process_id`; git/QA stdout/stderr stored only as truncated tail. Large payloads truncated (`{__truncated__, preview, original_length}`).
- **No double-write storm**: `event_bus` instrumentation skips event types already captured richer elsewhere or purely streaming (`conductor_turn`, `conductor_turn_delta`, `log`, `message_delta`, `heartbeat`).
- **Secret hygiene**: `cli_spawn` redacts the trailing prompt arg (`<prompt redacted>`); never log raw prompts/secrets into argv payloads.
- **Read API**: all filters fully parameterized (`?` binds, incl. `q` LIKE term — never string-interpolate); keyset cursor `(created_at, id) < (?, ?)` DESC (offset-drift-immune); `limit` clamped; `limit+1` probe for `next_cursor`; garbage cursor → graceful page-1.

#### 4. Validation & Error Matrix
- store/worker not ready, store raises, non-serializable payload → `record` swallows, no propagation.
- queue full → drop-newest, `dropped++`, no raise.
- off-loop-thread enqueue → routed via `call_soon_threadsafe` (row not lost).
- malformed cursor → `(None, None)` → page 1.
- injection in `q`/filters → bound as values, table intact.

#### 5. Good/Base/Bad Cases
- Good: a git merge, a conductor LLM turn, and a QA command each leave one queryable `audit_log` row, filterable by issue + category, without slowing the operation.
- Base: under an event burst, newest rows drop with a counted warning — the operation never blocks.
- Bad: writing `audit_log` directly from a choke point (drift); awaiting the DB on the hot path; re-copying per-line stdout into `audit_log`; string-interpolating a filter into SQL.

#### 6. Tests Required
- each category lands via its real instrumented function (mutation-verify non-vacuous); best-effort no-raise on store failure; bounded-queue drop counts without raising; cross-thread enqueue drains; event skip-set blocks double-write; cursor paging over tied timestamps has no dupes/gaps; `q` injection (tautology / DROP) returns literal/empty + table intact.

#### 7. Wrong vs Correct
Wrong:
```python
await store.save_audit_log(...)        # direct write at a choke point → drift; await blocks hot path
```
Correct:
```python
audit_logger.record("git_command", issue_id=..., payload={...}, status="ok")  # enqueue, best-effort, non-blocking
```

---

### Scenario: GitHub PR Follow-Up Sweep (review / CI / merge state)

#### 1. Scope / Trigger

- Trigger: changing GitHub PR refresh, project-level PR sweeps, or any
  conductor/scheduled-review path that follows an opened PR through review,
  status checks, and remote merge.
- Why code-spec depth: this is the autonomy bridge after "open PR". If it
  falls back to a manual Refresh PR button, issues stall outside the conductor.
  If one PR refresh failure aborts the sweep, unattended project operation drops
  work.

#### 2. Signatures

```python
# github_pr_followup.py
async def refresh_issue_github_pr(issue_id, *, store, event_bus, run_subprocess) -> GitHubPRFollowupResult
async def sweep_project_github_prs(project_id, *, store, event_bus, run_subprocess, auto_merge=False) -> GitHubPRFollowupSummary
def get_github_pr_followup_status() -> dict[str, object]
def reset_github_pr_followup_status() -> None

# api.py
POST /api/codex/issues/{issue_id}/pr/refresh -> CodexIssue
POST /api/codex/projects/{project_id}/pr/follow-up {"auto_merge": false} -> {
    project_id, counts, results: [{issue_id, status, github_pr_state, message, error}]
}
GET /api/diagnostics -> {"github_pr_followup": {...}, ...}

# project_conductor.py
ProjectConductor.handle_task(ConductorTask(task_kind="scheduled_review")) -> {
    status, answer, task_id, github_pr_followup
}
```

#### 3. Contracts

- The single-issue manual endpoint and project sweep MUST share the same
  application-layer refresh implementation.
- `gh pr view` MUST request
  `state,reviewDecision,reviews,mergeStateStatus,statusCheckRollup` so review,
  CI, and merge state are visible in one call.
- Stable result statuses are:
  - `updated`: PR open, no requested changes or failed completed checks.
  - `changes_requested`: `reviewDecision == "CHANGES_REQUESTED"`; latest
    engineer task is set to `pending` with review feedback.
  - `checks_failed`: at least one completed status check conclusion is not
    success/skipped/neutral; result message names failed checks.
  - `checks_pending`: at least one status check is not completed; auto-merge
    MUST NOT run while this is true.
  - `checks_missing`: auto-merge was requested but GitHub returned no status
    checks; missing checks are not treated as green.
  - `review_required`: auto-merge was requested but the PR is not approved.
  - `merge_blocked`: auto-merge was requested but `mergeStateStatus` is not a
    known mergeable value.
  - `merge_failed`: `gh pr merge` returned non-zero; audit/event recorded and
    the sweep continues.
  - `merged`: `state == "MERGED"`; issue becomes
    `git_merge_status="merged"` and lifecycle `status="completed"`.
  - `failed`: `gh` non-zero, bad JSON, or subprocess exception.
- Auto-merge is opt-in only (`auto_merge=True`). Default project follow-up MUST
  never merge.
- Auto-merge may call
  `gh pr merge <github_pr_url> --merge --delete-branch` only when:
  `state == "OPEN"`, `reviewDecision == "APPROVED"`,
  `mergeStateStatus in {"CLEAN", "HAS_HOOKS", "UNSTABLE"}`, at least one
  status check exists, every status check is completed, and no completed status
  check failed.
- Every result writes `project_audit` event
  `github_pr_followup_<status>` and emits an `issue_pr_followup` event.
- The project sweep skips issues with no `github_pr_url` or already merged
  `git_merge_status`.
- The project sweep MUST maintain an in-memory operational status snapshot with
  only safe fields: `configured`, `running`, `sweep_count`, `last_started_at`,
  `last_completed_at`, `last_error`, `last_summary_counts`, and
  `auto_merge_enabled`.
- `GET /api/diagnostics` MUST expose that snapshot as top-level
  `github_pr_followup`. It must not expose GitHub tokens, project names, repo
  paths, prompts, issue titles/descriptions, or full tracebacks.
- A successful project sweep records completion time, increments
  `sweep_count`, clears `last_error`, and stores summary counts. A sweep-level
  exception records safe error text, increments `sweep_count`, clears
  `running`, and re-raises so callers keep their existing supervisor behavior.
- Manual single-issue PR refresh MUST NOT update the project sweep status
  snapshot.
- A `ProjectConductor` scheduled review MUST run the project sweep with
  `auto_merge=True`, then include the sweep summary under
  `github_pr_followup` in the returned result, persisted task `result_json`,
  and project hot-thread answer event.
- Scheduled-review PR follow-up is best-effort supervisor work. A sweep
  exception is logged and reported as `{"status": "failed", "error": ...}`,
  but the conductor task still completes so the project review loop survives.

#### 4. Validation & Error Matrix

- Missing issue -> service raises `not_found`; manual endpoint maps 404.
- Issue without PR -> service raises `no_pr`; manual endpoint maps 409.
- `gh` unavailable -> endpoint maps 412 before service call.
- `gh pr view` non-zero / bad JSON / subprocess exception -> result
  `failed`, audit/event recorded, sweep continues.
- `auto_merge=False` -> never call `gh pr merge`, even if the PR is approved
  and green.
- `auto_merge=True` + pending checks -> `checks_pending`, no merge.
- `auto_merge=True` + no checks -> `checks_missing`, no merge.
- `auto_merge=True` + not approved -> `review_required`, no merge.
- `auto_merge=True` + unmergeable status -> `merge_blocked`, no merge.
- `auto_merge=True` + merge command non-zero or subprocess exception ->
  `merge_failed`, issue remains open, sweep continues.
- One failed issue in a sweep -> included as `failed`; following issues still
  refresh.
- Sweep-level exception before/after issue iteration -> status snapshot records
  `last_error` and clears `running`; exception propagates to the conductor or
  endpoint boundary.
- Scheduled-review sweep raises unexpectedly -> conductor result includes a
  failed `github_pr_followup` payload and the conductor task status remains
  `done`.

#### 5. Good/Base/Bad Cases

- Good: one project sweep refreshes ten open PRs, requeues one engineer for
  requested changes, auto-merges one approved green PR, marks one remotely
  merged issue completed, records one failed CI status, and reports two `gh`
  failures without aborting the sweep.
- Base: manual refresh of a single issue returns the updated `CodexIssue`, as
  before, but now uses the shared service.
- Bad: duplicating PR parsing in `api.py`; treating a bad JSON response as an
  unhandled exception; only polling review state and ignoring status checks.

#### 6. Tests Required

- Single refresh: remote merged PR updates `git_merge_status`, lifecycle status,
  audit, and event.
- Single refresh: changes requested writes review feedback into latest engineer
  task and emits `task_status`.
- Single refresh: failed completed status check returns `checks_failed` and
  names the failed check.
- Single refresh: bad JSON / non-zero `gh` returns `failed` with audit/event.
- Project sweep: skips no-PR / already-merged issues and isolates failures.
- Project sweep status records success counts, failure error text, running
  transitions, and the `auto_merge_enabled` flag.
- Endpoint: project follow-up returns best-effort summary instead of HTTP
  failing for one broken PR.
- Diagnostics includes top-level `github_pr_followup` and degrades when its
  `last_error` is present or `running` is `true`.
- ProjectConductor scheduled review: calls project sweep with `auto_merge=True`
  and records the summary in return payload, `result_json`, and hot memory.
- ProjectConductor scheduled review: sweep exception is reported without
  raising or failing the conductor task.
- Auto-merge: approved + all-green + mergeable -> calls `gh pr merge`, marks
  merged/completed, records `github_pr_followup_merged`.
- Auto-merge: missing checks / pending checks / review required / merge command
  failure -> no unsafe merge; stable status returned.

#### 7. Wrong vs Correct

Wrong:
```python
# API-only parsing means background/conductor paths cannot reuse the logic.
data = json.loads(await gh_pr_view(...))
issue.github_pr_state = f"{data['state']}:{data['reviewDecision']}"
```

Correct:
```python
summary = await sweep_project_github_prs(
    project_id,
    store=codex_store,
    event_bus=event_bus,
    run_subprocess=_run_subprocess,
)
```

---

### Scenario: Workflow Failed Node Auto Retry

#### 1. Scope / Trigger

- Trigger: changing `WorkflowScheduler.on_task_completed`, workflow node
  terminal status handling, task runner completion events, or automatic recovery
  for DAG-backed tasks.
- Why code-spec depth: this hook is the bridge between executor failures and
  unattended issue progress. A single transient failed task must not strand the
  workflow, but deterministic failures must still surface as failed once the
  node retry budget is exhausted.

#### 2. Signatures

```python
# workflow_scheduler.py
class WorkflowScheduler:
    async def on_task_completed(self, task: CodexTask) -> None
```

Relevant storage calls:

```python
await store.save_codex_task(retry_task)
await store.update_workflow_node(
    node.id,
    status="running",
    task_id=retry_task.id,
    retries=node.retries + 1,
    started_at=retry_task.created_at,
    completed_at=None,
)
```

Relevant events:

```json
{"type": "workflow_node_diff_guard_failed", "task_id": "...", "reason": "..."}
{"type": "workflow_node_retrying", "previous_task_id": "...", "retry_task_id": "..."}
{"type": "workflow_node_retry_failed", "retry_task_id": "...", "status": "failed"}
{"type": "task_status", "task_id": "...", "status": "pending|failed"}
```

#### 3. Contracts

- Auto-retry applies only to tasks with `workflow_node_id` whose terminal task
  status maps to workflow node `failed`.
- Before a workflow-backed Engineer task (`engineer`, `engineer_frontend`, or
  `engineer_backend`) is allowed to mark its node `done`, the scheduler MUST
  honor the Engineer diff cross-check's hard failure note. If the persisted
  Engineer document says the Engineer claimed changed files but git diff
  against the base branch showed no file changes, the scheduler converts the
  completion to `failed`, persists that task status, emits
  `workflow_node_diff_guard_failed`, and then lets the normal auto-retry logic
  handle the failed node. This keeps deterministic "report-only implementation"
  failures self-healing before Architect Review / QA.
- The diff completion guard MUST NOT fire for honest empty-diff Engineer
  reports (`changed_files=[]`, no hard cross-check note), non-Engineer roles,
  or arbitrary prose that happens to mention git diff outside the managed
  Engineer report document.
- A node is eligible only when `node.retries < node.max_retries` and the
  scheduler has both an issue row and a `task_dispatcher`.
- The retry creates a fresh `CodexTask` for the same workflow node:
  `parent_task_id` points to the failed task, `workflow_node_id` is unchanged,
  project/session/issue/role/prompt/executor/provider/model/git fields are
  inherited, and status starts as `pending`.
- The retry task `review_comment` MUST include a short `[AUTO RETRY X/Y]`
  framework note and may include truncated previous result/review context.
- The workflow node MUST be moved back to `running`, `completed_at` cleared to
  `NULL`, `task_id` set to the retry task, and `retries` incremented before the
  retry dispatcher is started.
- While a retry is launched, the Conductor completion registry MUST NOT receive
  the original failed result. It should observe the retry task's eventual
  terminal result instead.
- If retry dispatch itself raises, mark the retry task `failed`, emit
  `workflow_node_retry_failed`, restore normal failed-node handling for the
  original task, and keep the original failed task id on the final node status.
- Once retry budget is exhausted, keep existing failed-node behavior: mark the
  node failed, signal Conductor with the failed result, and do not advance the
  issue phase as if the node succeeded.

#### 4. Validation & Error Matrix

- Task has no `workflow_node_id` -> no scheduler action.
- Task status is non-terminal or maps to no node status -> no scheduler action.
- Failed node with retries remaining and dispatcher available -> create retry
  task, update node to running, emit retry events, start dispatcher, return.
- Done Engineer node with persisted diff-guard failure note and retries
  remaining -> persist the original task as failed, emit
  `workflow_node_diff_guard_failed`, create retry task, update node to running,
  emit retry events, start dispatcher, return.
- Done Engineer node with no diff-guard failure note -> mark node done normally.
- Done non-Engineer node with similar text -> mark node done normally.
- Failed node with retries exhausted -> mark node failed and continue existing
  Conductor signaling.
- Failed node with no issue row or no dispatcher -> mark node failed and
  continue existing Conductor signaling.
- Retry dispatcher raises -> retry task becomes failed, retry-failed event is
  emitted, original node becomes failed, and the exception does not escape the
  scheduler hook.
- Event emission failure -> log/debug and continue; observability must not
  break the recovery path.

#### 5. Good/Base/Bad Cases

- Good: a transient executor startup failure on `engineer` creates
  `task-retry`, moves `engineer` back to running with `retries=1`, and the
  Conductor only sees the retry's eventual result.
- Base: a deterministic QA command failure with `retries == max_retries` marks
  the QA node failed and gives Conductor the failed result.
- Bad: signaling the first failed task to Conductor and also starting a retry,
  leaving two supervisors racing over the same node.

#### 6. Tests Required

- First failed workflow task creates and dispatches a retry task, increments
  node retries, clears node completion time, and emits retry/task events.
- Retry budget exhausted preserves existing failed-node behavior and does not
  create a retry task.
- Retry dispatch failure marks the retry task failed, emits
  `workflow_node_retry_failed`, and falls back to final failed-node handling.
- Diff completion guard converts a `done` Engineer task with the hard
  diff-cross-check note into a failed original task, emits
  `workflow_node_diff_guard_failed`, and then uses the same retry behavior as a
  regular failed node.
- Guard boundaries: a `done` Engineer task without that note marks the node
  done; a `done` non-Engineer task with similar text also marks the node done.
- Existing artifact-validation signaling tests still pass, proving completion
  registry behavior stays compatible.

#### 7. Wrong vs Correct

Wrong:
```python
await store.update_workflow_node(node.id, status="failed")
reg.signal(task.id, {"status": "failed"})
await dispatch_retry_later(task)
```

Correct:
```python
if task.status == "failed" and node.retries < node.max_retries:
    retry_task = build_retry_task(task, node)
    await store.save_codex_task(retry_task)
    await store.update_workflow_node(
        node.id,
        status="running",
        task_id=retry_task.id,
        retries=node.retries + 1,
        completed_at=None,
    )
    await task_dispatcher(retry_task)
    return
```

---

### Scenario: Project Review Scheduler Tick

#### 1. Scope / Trigger

- Trigger: adding or changing backend automation that periodically runs
  project-level reviews across projects.
- The scheduler tick is the bridge between an operator-triggered scheduled
  review endpoint and unattended project operation.

#### 2. Signatures

```python
async def run_project_review_tick(
    store,
    *,
    event_bus=None,
    conductor_factory=_default_conductor_factory,
    limit=None,
) -> ProjectReviewTickSummary
```

#### 3. Contracts

- The scheduler MUST list projects through the typed store API
  (`list_projects`); it does not query SQL directly.
- Each selected project gets a `ConductorTask` with
  `task_kind="scheduled_review"` and the standard scheduled health-review
  question.
- The scheduler MUST call `ProjectConductor.handle_task(...)` instead of
  duplicating GitHub PR follow-up, auto-merge, or memory logic.
- A per-project failure is isolated and returned as a `failed` result with
  safe error text. Later projects in the same tick still run.
- The tick supports a `limit` parameter so future background loops can bound
  work per scan.

#### 4. Tests Required

- Project list with two projects -> two scheduled-review conductor tasks.
- First project raises -> first result `failed`, second project still runs.
- `limit=2` with three projects -> only first two projects are reviewed.

#### 5. Wrong vs Correct

Wrong:
```python
# Re-implements scheduled review internals and silently diverges from
# ProjectConductor / PR follow-up behavior.
await sweep_project_github_prs(project.id, auto_merge=True, ...)
```

Correct:
```python
conductor = ProjectConductor(project_id=project.id, store=store, event_bus=event_bus)
await conductor.handle_task(scheduled_review_task)
```

### Scenario: Project Review Scheduler Background Loop

#### 1. Scope / Trigger

- Trigger: wiring project review scheduling into long-running backend
  process startup, shutdown, or cadence controls.
- The background loop is the unattended supervisor around
  `run_project_review_tick`; it does not change scheduled-review semantics.

#### 2. Signatures

```python
async def run_project_review_scheduler_loop(
    store,
    *,
    event_bus=None,
    interval_s=None,
    limit=None,
    tick_fn=run_project_review_tick,
    sleep_fn=asyncio.sleep,
) -> None

def get_project_review_scheduler_status() -> dict[str, object]
```

#### 3. Contracts

- The loop MUST delegate actual work to `run_project_review_tick(...)`.
- Cadence and default work bounds MUST be read through
  `app.application.timeouts` accessors. Feature code must not call
  `os.getenv` directly.
- A tick-level unexpected exception is a loop-boundary failure: log it with
  `logger.exception(...)`, then continue to the next sleep/cycle.
- `asyncio.CancelledError` MUST propagate so FastAPI lifespan shutdown can
  stop the task promptly.
- Tests SHOULD inject `tick_fn` and `sleep_fn` so loop cadence, exception
  survival, and cancellation are deterministic.
- FastAPI lifespan starts the loop only when `async_store` is available, names
  the task `project-review-scheduler`, and cancels/awaits it during shutdown.
- The loop MUST maintain an in-memory operational status snapshot with only
  safe fields: `configured`, `interval_s`, `limit`, `running`, `tick_count`,
  `last_started_at`, `last_completed_at`, `last_error`, and
  `last_summary_counts`.
- `GET /api/diagnostics` MUST expose that snapshot as top-level
  `project_review_scheduler`. It must not expose project names, repo paths,
  prompts, task payloads, credentials, or full tracebacks.
- A successful tick records completion time, increments `tick_count`, clears
  `last_error`, and stores summary counts. A regular tick exception records
  safe error text, increments `tick_count`, and keeps the loop alive.
- Cancellation sets `running=False` and propagates `asyncio.CancelledError`; it
  must not be counted as a successful completed tick.
- Diagnostics treats a scheduler status as stale when `last_completed_at` is
  present and older than `interval_s * 2`. Error and running states take
  precedence over stale; a scheduler that has never completed a tick is not
  stale from the missing completion timestamp alone.

#### 4. Tests Required

- Loop calls the tick, sleeps the configured interval, and repeats.
- Tick raises a regular exception -> loop logs/survives and runs another tick.
- Tick or sleep raises `CancelledError` -> cancellation propagates.
- Lifespan creates and later cancels the named `project-review-scheduler`
  task.
- Scheduler status records success, failure, and cancellation transitions.
- Diagnostics includes `project_review_scheduler` with configured interval and
  limit, degrades when `last_error` is present, `running` is `true`, or the last
  completion is stale, and does not leak runtime catalog API keys.

#### 5. Wrong vs Correct

Wrong:
```python
while True:
    await run_project_review_tick(store)
    await asyncio.sleep(float(os.getenv("PROJECT_REVIEW_INTERVAL_S", "3600")))
```

Correct:
```python
await run_project_review_scheduler_loop(
    store,
    event_bus=event_bus,
    interval_s=timeouts.project_review_interval_s(),
)
```

Correct:
```python
return {
    "project_review_scheduler": get_project_review_scheduler_status(),
    ...
}
```

---

## Testing Requirements

- **All new code is covered by tests.** Service logic,
  endpoint logic, and pure helper functions all get tests.
  The `pytest` mark `slow` opts into long integration tests;
  the default lane skips them, so a focused run
  (`pytest tests/test_foo.py -v`) is the right shape.
- **Pure functions are unit-tested in isolation.** A function
  in `application/` that takes a `CodexIssue` and returns
  an `IssueBudgetStatus` should be tested with a tiny
  stub store — no need for the real async store in most
  cases.
- **Endpoints are tested with the real async store where
  practical**, and with a focused store stub for the
  endpoint's own logic. The pattern is in
  `test_pipeline_stages.py` and `test_issue_budget_endpoint.py`.
- **Migration tests cover legacy rows.** A new column needs a
  test that exercises a row written before the migration,
  not just a fresh row. See
  `test_issue_budget.py::test_sync_store_migrates_legacy_issue_without_budget_column`
  for the canonical pattern.
- **State-machine tests for the conductor.** The conductor's
  legal/illegal phase transitions are enforced by
  `LEGAL_TRANSITIONS`; a change to the table needs a test
  in `test_conductor_state_machine.py`.
- **Cost / budget behavior is tested with the real
  `timeouts.X()` accessors.** A test that monkey-patches
  `os.getenv` skips the boot-time validation, which is the
  whole point of the accessor pattern.
- **No snapshot tests.** They drift; the per-feature
  derivation tests and the unit tests of the budget
  computation do the work snapshots would.

---

## Code Review Checklist

A reviewer should be able to answer YES to **all** of the
following before approving:

- [ ] The change is **scope-limited**: no incidental refactors,
      no drive-by reformatting, no opportunistic dependency
      bump.
- [ ] Every new service / endpoint is **typed end-to-end**
      (no `any`, no bare `dict` for shape-bearing data).
- [ ] Every new env-driven knob goes through
      `application/timeouts.py`, not a `os.getenv` call from
      feature code.
- [ ] Every new endpoint has a **focused test** (ceiling /
      unlimited / missing branches where applicable).
- [ ] Every new state-derivation rule has a **unit test**
      that covers below / at / above the threshold.
- [ ] Every new long-running coroutine **catches at the
      boundary** and persists a `failed` row with the
      traceback in `result_json` — the loop survives.
- [ ] Every new background poll has an **active-state guard**
      and stops once the issue is done / idle. No polling
      after the user's gone.
- [ ] Every new migration is **idempotent** and bumps
      `schema_version` in the same block.
- [ ] The diff is **readable in one pass** (no nested
      ternaries, no 9-prop god functions, no copy-paste
      boilerplate that should be a helper).
- [ ] `pytest -v` and any pointed test commands are green
      locally, with the actual output attached to the PR
      or task handoff.
- [ ] The change does not introduce a new external dependency
      without a sentence explaining why.
