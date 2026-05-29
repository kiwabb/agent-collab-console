# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

<!--
Document your project's quality standards here.

Questions to answer:
- What patterns are forbidden?
- What linting rules do you enforce?
- What are your testing requirements?
- What code review standards apply?
-->

(To be filled by the team)

---

## Forbidden Patterns

<!-- Patterns that should never be used and why -->

(To be filled by the team)

---

## Required Patterns

<!-- Patterns that must always be used -->

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

- Top-level response fields: `service`, `status`, `generated_at`, `database`, `runtime_catalog`, `executors`, `websockets`, `config`, `checks`.
- `status` is `"ok"` only when all checks are ok; use `"degraded"` when any check is degraded or errored but the endpoint can still return a snapshot.
- Runtime catalog entries may expose booleans such as `api_endpoint_configured` and `api_key_configured`.
- Runtime catalog entries must not expose raw secret values, raw API keys, bearer tokens, auth headers, or provider credentials.
- Config fields should expose booleans for whether sensitive paths or env values are configured, not their raw values.

#### 4. Validation & Error Matrix

- `codex_store is None` -> HTTP `503`, detail `"SQLite store not available"`.
- Database query raises -> keep HTTP `200`, set `database.status = "error"`, append a database error check, and set top-level `status = "degraded"`.
- Runtime catalog load raises -> keep HTTP `200`, set `runtime_catalog.status = "error"`, append a runtime catalog error check, and set top-level `status = "degraded"`.
- Runtime catalog has no enabled executor -> keep HTTP `200`, append a degraded runtime catalog check, and set top-level `status = "degraded"`.

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

## Testing Requirements

<!-- What level of testing is expected -->

(To be filled by the team)

---

## Code Review Checklist

<!-- What reviewers should check -->

(To be filled by the team)
