# brainstorm: browser investigation and issue fixes

## Goal

Use the local browser experience to inspect Agent Collaboration Console, identify visible or runtime issues, and fix the highest-value problems with evidence from the running app.

## What I already know

* The user asked to start browser-based investigation and repair work.
* The app is a local-first operations console with a Next.js frontend and FastAPI backend.
* Recommended local startup is `./dev-local.sh`.
* Default URLs are frontend `http://localhost:4000` and backend `http://localhost:9000`.
* Browser validation should use the Codex in-app Browser plugin.
* Current branch is `main`, ahead of origin by 5 commits from the earlier coordinator prompt upgrade work.
* Browser opened `http://localhost:4000` successfully and the Inbox rendered.
* The Inbox showed a recent failed issue: `REAL run: three tiny independent modules in parallel`.
* Backend startup recovered issue `c13b189c-4da4-4627-a661-181b01d4443b`, then the conductor failed while calling the LLM.
* The backend traceback ends at `httpx.AsyncClient(timeout=ctx.timeout_s)` with `httpx.InvalidURL: Invalid port: ':1'`.
* Local environment includes `NO_PROXY=127.0.0.1,localhost,::1,127.0.0.0/8,::1/128`.
* A focused reproduction with backend `httpx 0.28.1` shows `httpx.AsyncClient(...)` fails with that `NO_PROXY` value and succeeds with `trust_env=False`.
* Browser retesting the failed issue page exposed a second user-visible problem: `/api/codex/issues/{id}/diff` returned `500 Internal Server Error` when a historical issue still referenced a worktree path that no longer existed on disk.
* After the diff endpoint fix, the same issue detail page loads with `has500: false`, and backend logs show its detail-page API fanout returning `200`.
* A wider browser sweep of core routes found no new 500/error pages, but revealed issue detail deep links such as `?tab=diff`, `?tab=artifacts`, and `?tab=mesh` still selected the default timeline tab.
* After the tab deep-link fix, browser checks show the expected selected tabs: `Diff`, `产物3`, and `协作网4`.
* Browser retesting exposed a backend log-noise issue: navigating away while the workspace execution-process WebSocket was sending its initial snapshot could raise `WebSocketDisconnect` before `_serve_subscriber` owned the connection.
* After the WebSocket initial snapshot fix, the same fast workspace-to-inbox navigation produced normal `connection closed/open` log lines without a new `Exception in ASGI application`.

## Assumptions (temporary)

* The highest-value first repair is the conductor LLM HTTP client boundary, because it turns a recovered conductor into a user-visible failed issue.
* LLM API calls should not crash because local development proxy bypass entries contain IPv6 loopback hosts.
* This task should keep the fix scoped to LLM runner HTTP clients unless further browser retesting reveals a second independent issue.
* Historical failed issue records may retain old conductor error text; repairing the underlying crash should not rewrite that audit history.

## Open Questions

* None currently blocking.

## Requirements (evolving)

* Start the local frontend and backend using the repo's documented workflow.
* Open the app in the in-app Browser and gather DOM, screenshot, console, and network evidence as needed.
* Identify concrete issues before proposing code changes.
* For each selected issue, capture expected behavior, actual behavior, and likely root cause.
* Make narrowly scoped fixes that follow existing repo patterns.
* Verify fixes through automated checks and browser retesting.
* Prevent conductor LLM calls from failing at HTTP client construction when `NO_PROXY` contains bare IPv6 loopback entries.
* Prevent issue detail pages from surfacing a server error when the issue's persisted worktree path is stale.
* Preserve issue detail tab deep links so cross-page navigation can land on Diff, Artifacts, or Mesh directly.
* Treat browser disconnects during workspace execution-process WebSocket initial snapshot sends as benign and return before registering a subscriber.

## Acceptance Criteria (evolving)

* [x] Local app loads at `http://localhost:4000`.
* [x] Browser investigation records at least one concrete finding or confirms the default path is healthy.
* [x] Any implemented fix has a clear before/after verification path.
* [x] Relevant frontend/backend tests or smoke checks pass.
* [x] Browser retest confirms the repaired workflow behaves as expected.

## Definition of Done (team quality bar)

* Tests added/updated where appropriate.
* Lint / typecheck / targeted checks green, or failures documented with cause.
* Browser evidence collected for user-facing behavior.
* Docs/notes updated if behavior or project knowledge changes.
* Rollout/rollback considered if risky.

## Out of Scope (explicit)

* Full accessibility audit across every screen.
* Broad visual redesign unrelated to a concrete defect.
* Production deployment or remote environment validation.
* Changing agent execution semantics unless a browser-observed issue requires it.

## Technical Notes

* `README.md` documents architecture, ports, local startup, and quality gates.
* `dev-local.sh` starts backend and frontend, freeing ports 9000 and 4000 first.
* `frontend/package.json` scripts include `dev`, `build`, `test`, and `lint`.
* Browser plugin setup uses the bundled `browser-client.mjs` script through the Node REPL.
* `backend/app/application/llm_runner.py` creates `httpx.AsyncClient` instances for Anthropic-compatible and OpenAI-compatible LLM calls.
* Existing focused tests live in `backend/tests/test_llm_runner_streaming.py`.
* Backend specs require tests for new backend logic and scope-limited diffs.
* Implemented `_llm_http_client(timeout_s)` with `trust_env=False` and routed LLM HTTP calls through it.
* Added `test_llm_http_client_ignores_invalid_ipv6_no_proxy`.
* Added `test_get_issue_diff_resets_missing_worktree`.
* Updated `IssueDetailPage` to read `useSearchParams()` for `tab`, drive Tabs with `value={activeTab}`, and update the URL via `router.replace(...)` on tab changes.
* Updated `issueCommandCenter.test.ts` to lock the URL-tab contract.
* Added `_send_workspace_initial_snapshot(...)` so the workspace execution-process WebSocket initial snapshot catches `WebSocketDisconnect` before subscriber registration.
* Added `test_workspace_initial_snapshot_disconnect_is_benign`.
* Verification:
  * `backend/.venv/bin/python -m pytest backend/tests/test_llm_runner_streaming.py backend/tests/test_projects_api.py::test_get_issue_diff_resets_missing_worktree backend/tests/test_projects_api.py::test_get_issue_diff_returns_empty_when_no_changes -q` -> `4 passed`.
  * `SQLITE_DB_PATH=/tmp/agent-collab-ws-test-$$.db backend/.venv/bin/python -m pytest backend/tests/test_ws_subscriber_backpressure.py backend/tests/test_execution_process_ws_async_store.py -q` -> `10 passed`.
  * `backend/.venv/bin/python -m pytest backend/tests/test_ws_subscriber_backpressure.py::test_workspace_initial_snapshot_disconnect_is_benign -q` first failed with missing helper, then passed after implementation.
  * `cd frontend && npm run test -- issueCommandCenter.test.ts` -> `151 passed`.
  * `cd backend && .venv/bin/python -c "from app.main import app; print('import ok')"` -> `import ok`.
  * `git diff --check` -> passed.
  * `GET /api/codex/issues/c13b189c-4da4-4627-a661-181b01d4443b/diff?stat_only=true` -> `200 OK`.
  * Browser loaded `/issues/c13b189c-4da4-4627-a661-181b01d4443b` with `has500: false`.
  * Browser loaded `?tab=diff`, `?tab=artifacts`, and `?tab=mesh` with the expected active tab and no 500.
  * Browser loaded `/workspaces/27f61ed5-36a3-4f16-80eb-8de3cb30feed`, quickly navigated back to `/`, and backend logs showed no new ASGI exception after the WebSocket fix.
