# Detect locally running services from Startup Config

## Goal

Make Startup Config report whether the project's analyzed local access URL is already serving, including services started outside Agent Collaboration Console, so users do not accidentally launch duplicates or mistake an untracked service for an offline project.

## What I already know

* `ProjectRunManager` only knows processes stored in its in-memory `_entries` map.
* A process started from a terminal or IDE, or one surviving outside the current backend lifetime, is not represented by the current `running` field.
* The latest Operations Engineer task result already exposes an optional local `access_url` on Startup Config.
* Startup Config already polls managed run status and retains incremental logs.
* Existing startup-configuration files contain uncommitted work and must be changed incrementally.

## Requirements

* Resolve the latest successful Operations Engineer `access_url` on the backend, not from a browser-supplied URL, so CORS does not determine the result and the status API cannot become an arbitrary local-port scanner.
* Accept only HTTP(S) loopback targets. Normalize wildcard loopback bindings such as `0.0.0.0` to a connectable loopback address and reject remote/private-network targets.
* Treat any received HTTP response as reachable, regardless of status code; connection failures and timeouts mean unreachable.
* Preserve the existing `running` meaning for a process managed by `ProjectRunManager` and add explicit service reachability fields.
* Startup Config must distinguish:
  * managed process running and service reachable;
  * managed process running but service not ready;
  * service reachable but not managed by this console;
  * service unreachable/offline;
  * no usable access URL, where reachability is unknown.
* Never offer Stop for an externally started service because the console does not own its process.
* Recheck reachability on initial load, while the page remains open, after analysis completes, and after start/stop actions.
* Before starting, recheck the resolved target URL and refuse a duplicate launch when an untracked service is already reachable.
* Keep previously rendered project data on transient probe/status errors and expose a clear unknown/error state instead of claiming the project is offline.
* Keep existing project-workspace run controls compatible when no access URL is supplied.

## Acceptance Criteria

* [x] Opening Startup Config for a manually started local service shows that the service is already reachable.
* [x] The external-service state does not show a Stop action owned by the console.
* [x] A managed process whose URL is not reachable is shown as starting/not ready rather than ready.
* [x] A managed and reachable process remains stoppable and keeps its current log behavior.
* [x] Starting from Startup Config while an external service is reachable is refused with visible informational feedback.
* [x] A reachable endpoint returning 4xx or 5xx still counts as a running local service.
* [x] Non-loopback URLs are never requested and produce an unknown/unsupported probe result.
* [x] Missing `access_url` preserves current run behavior and reports reachability as unknown.
* [x] Focused backend probe/API tests and frontend state/component tests pass.
* [x] Existing startup-config tests continue to pass.

## Definition of Done

* Backend probe and API contract are covered by focused tests.
* Frontend types, state derivation, status panel, start flow, and i18n are updated.
* Focused tests and proportionate type checks pass.
* Existing unrelated and user-authored dirty changes remain intact.

## Verification

* Frontend Prettier, focused ESLint, TypeScript typecheck, and 33 focused tests pass.
* Backend focused Ruff and Mypy pass; 115 probe/API/script/lifecycle/source-hygiene tests pass across the focused runs. The combined lane's sole failure is the global strict-coverage check detecting two unrelated modules added concurrently by another active task.
* Browser verification confirms Startup Config and Workspaces show an external local service with Open and without Stop, and service status continues polling every 5 seconds.
* A real proxied `POST /run/start` returns HTTP 409 with `service_already_reachable`, canonical URL, and HTTP 200 evidence.
* Full-repository Mypy is currently blocked only by concurrent uncommitted `project_startup_mcp` / `project_startup_service` work from another active task; the eight files in this task's Mypy lane pass.

## Technical Approach

Add a small application-layer local-service probe with strict URL parsing and a short timeout. Resolve the latest successful project script task on the backend, accept its URL only when its run command still matches the current project configuration, and probe the canonical loopback URL. Extend the run status response with service reachability metadata while keeping `running` as the managed-process flag. Startup Config polls the enriched status, derives a display state, and blocks duplicate starts when the backend reports an externally reachable service.

## Decision (ADR-lite)

**Context:** Process-name and command matching cannot reliably identify framework child processes or ownership, while browser probing is distorted by CORS. The product already has an Operations Engineer access URL.

**Decision:** Use a backend HTTP reachability probe restricted to explicit loopback HTTP(S) URLs. Keep process ownership and endpoint reachability as separate dimensions.

**Consequences:** The UI can accurately say that an address is serving without claiming ownership of the process. A different service occupying the same port is conservatively treated as an occupied/reachable target and duplicate startup is refused. Projects without an analyzed access URL remain detectable only through console-managed process state.

## Expansion and edge cases included

* Preserve an explicit unknown state for unsupported/missing URLs and probe failures that cannot establish offline status.
* Keep the API additive so the workspace page and existing clients continue working.
* Make the probe contract reusable by future health checks without adding process discovery now.

## Out of Scope

* Discovering arbitrary local services when no access URL or port is known.
* Finding or killing external process IDs with `lsof`, `ps`, or platform-specific commands.
* Persisting external process ownership across backend restarts.
* Remote/private-network service monitoring.
* Adding a user-configurable health-check path in this increment.

## Technical Notes

* Primary backend files: `backend/app/application/project_run_manager.py`, a probe helper module, `backend/app/interfaces/api.py`, and `backend/tests/test_project_run.py`.
* Primary frontend files: `frontend/src/lib/types/projects.ts`, `frontend/src/lib/api/projects.ts`, `frontend/src/features/projects/projectStartupConfig.ts`, `useProjectStartupConfig.ts`, `ProjectRunStatusPanel.tsx`, i18n, and focused tests.
* Existing probing code in `backend/app/application/project_script_suggestions.py` is relevant but its launch-verification semantics differ: this task treats every HTTP response as proof of a listener and must enforce loopback validation before any request.
* This task intentionally supersedes the older Startup Config boundary that treated `access_url` only as an expected destination; readiness is now explicit probe evidence rather than an inference from process creation.

## Research References

* [`research/local-service-probe.md`](research/local-service-probe.md) - repository-specific API, security, state, and test findings.
