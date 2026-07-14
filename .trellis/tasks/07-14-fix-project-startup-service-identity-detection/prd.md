# Fix project startup service identity detection

## Goal

Prevent a project startup configuration from treating an unrelated HTTP service on the configured port as the expected application being ready. Preserve port-occupation detection, but distinguish it from process liveness and application-specific readiness/identity.

## What I already know

- The user reproduced the problem with `examples/admin-demo`: port 8080 is occupied by another service, yet the console reports the configured service as accessible.
- The current generic probe returns `state="reachable"` for any HTTP response, including 302, 404, and 500.
- `ProjectRunManager.running` only proves the console-managed child process has not exited.
- `admin-demo` exposes `GET /api/dashboard` with a stable, application-specific JSON response and its frontend title is `Northstar 管理后台`.
- Current consumers promote generic reachability into stronger meanings such as startup complete, verified launch, or already-reachable service.

## Current Port-Occupation Behavior

Before this change, if the configured access URL responds:

1. The generic service probe reports `reachable`, regardless of HTTP status or responder identity.
2. If no console-managed process exists, the service may be presented as externally reachable.
3. The startup UI may treat the step as complete and suppress or disable Start.
4. A new start attempt may be rejected with `409 service_already_reachable`.
5. This avoids blindly starting a second listener on the same port, but incorrectly claims that the expected application is available.

If the user bypasses that preflight and runs the command directly, the new process normally exits with its framework's address-in-use error; the console captures the nonzero exit code and stderr logs.

## Assumptions (temporary)

- Generic `reachable` should remain a transport/address-occupation signal rather than silently changing to mean HTTP 2xx.
- Application readiness must be configured generically; platform code must not hard-code `admin-demo` response values.
- An occupied address should block automatic launch by default, but the UI and API should report an occupied/unknown responder rather than successful startup.

## Open Questions

None. Requirements are ready for implementation approval.

## Requirements

- Use a declarative HTTP readiness/identity matcher for the MVP; do not require an active launch token.
- Treat every existing startup service configuration without an identity matcher as invalid and non-runnable; require regeneration rather than preserving unverified reachability behavior.
- Surface the invalid configuration as an explicit actionable state that directs the user to regenerate/re-analyze startup configuration.

- Keep process liveness, address reachability, and expected-application readiness as separate signals.
- Add an application-specific readiness/identity contract to project startup service configuration.
- Do not mark startup complete or launch verified unless the readiness/identity contract passes.
- When the address responds but identity/readiness fails, report an occupied or unknown service state.
- Continue preventing an automatic start from colliding with an occupied configured address.
- Configure `admin-demo` with a probe that distinguishes it from arbitrary services on port 8080.
- Preserve loopback-only and SSRF-resistant probe constraints.
- Keep the current host-process runner for this task; introduce no sandbox or Docker execution mode.
- Support a strict, bounded HTTP matcher with an exact expected status and an identity predicate of either `json_subset` or literal `text_contains`.
- Bound response-body reads and fail closed on malformed, oversized, or mismatched content.
- Add a dedicated `GET /api/health/ready` endpoint to `examples/admin-demo` backend with a stable application identity marker and ready status.
- Configure admin-demo backend readiness against that dedicated endpoint rather than matching `/api/dashboard` business data.
- Configure admin-demo frontend readiness independently using its stable HTML identity marker; frontend readiness remains per-service and must not be inferred solely from backend readiness.

## Decision (ADR-lite)

**Context**: Address reachability alone cannot distinguish the expected application from an unrelated listener, while requiring every project to implement a launch nonce would make adoption invasive.

**Decision**: Implement a generic declarative HTTP readiness/identity matcher. A service configuration defines a separate loopback probe URL, exact expected status, and a bounded `json_subset` or literal `text_contains` identity predicate. Project-specific fingerprints live in configuration, never in platform code. `admin-demo` will add a dedicated `/api/health/ready` backend endpoint instead of coupling readiness to dashboard business data.

**Consequences**: Correct externally started instances can be recognized as ready, but readiness alone does not prove that the console launched or owns the process. A future optional launch token can add ownership proof without replacing the matcher contract. Legacy service configurations without a matcher are intentionally invalidated and must be regenerated; there is no compatibility fallback to generic reachability. Runtime isolation and port namespacing remain unchanged in this task and will be designed separately as an optional Docker/sandbox runner phase.

## Acceptance Criteria (evolving)

- [ ] An unrelated HTTP 200 service on admin-demo's configured port is not reported as admin-demo ready.
- [ ] HTTP 302, 404, and 500 responses remain observable as address reachability but do not establish application readiness.
- [ ] `GET /api/health/ready` in admin-demo returns HTTP 200 with stable service identity and ready status, covered by a Spring test.
- [ ] The generated/persisted admin-demo backend matcher targets `/api/health/ready`; the expected response passes readiness and a foreign HTTP 200 response fails identity.
- [ ] The admin-demo frontend matcher identifies the expected HTML shell independently.
- [ ] If the configured address is occupied by an unknown responder, starting is blocked with an explicit occupied/conflict reason rather than `service_already_reachable` success semantics.
- [ ] A console-managed process that is alive but has not passed readiness is shown as starting or unhealthy, not ready.
- [ ] Backend and frontend tests cover unreachable, occupied/unknown, starting/unhealthy, externally ready, and managed ready states.
- [ ] Existing startup configurations without an identity matcher are reported as invalid, cannot be started, and provide a clear regenerate/re-analyze action.

## Definition of Done

- Tests added/updated at backend unit/API and frontend pure-state/component levels where appropriate.
- Backend pytest is run under an explicit timeout to prevent orphaned test processes.
- Frontend typecheck/tests pass; do not run `npm run build` while the dev server may be active.
- Runtime behavior is exercised end-to-end with admin-demo or an equivalent controlled responder.
- Documentation/spec notes are updated if the startup configuration schema changes.

## Expansion Sweep

### Future evolution

- Support richer readiness predicates without hard-coding individual projects.
- Optionally support a launch-instance token to prove ownership, not only application identity.

### Related scenarios

- Multi-service startup configurations must evaluate readiness per service.
- Externally started instances of the correct application may still be considered ready, but must not be attributed to the current console launch.

### Failure and edge cases

- A foreign service can return the same status code; status-only matching is insufficient.
- Redirects, malformed JSON, timeouts, and an application process that remains alive while unhealthy must remain distinguishable.
- Probe configuration itself may be invalid and must fail closed.

## Technical Approach

1. Extend the strict Operations Engineer startup-service contract, domain model, persistence, and frontend types with a required per-service HTTP readiness probe.
2. Keep generic transport reachability intact for address-occupation evidence; add a separate bounded readiness evaluator for expected status plus identity-body matching.
3. Reuse the evaluator in steady-state status, collision preflight, and launch verification so `reachable`, `ready`, and `verified` cannot diverge semantically.
4. Expand API status payloads and frontend pure-state derivation to represent invalid config, offline, occupied unknown, managed starting/unhealthy, correct external ready, and managed ready.
5. Add admin-demo's dedicated backend readiness endpoint and regenerate/store strict readiness matchers for both backend and frontend services.

## Implementation Plan

- PR1-equivalent: readiness schema/domain/persistence plus strict validation and migration behavior.
- PR2-equivalent: bounded HTTP evaluator, API/preflight/launch-verification integration, and backend tests.
- PR3-equivalent: frontend state/UX updates, admin-demo readiness endpoint/config, end-to-end verification, and spec updates.

## Out of Scope

- Backward-compatible execution of legacy startup configurations without an identity matcher.
- Docker, container, VM, OS sandbox, network namespace, dynamic host-port mapping, and execution-mode selection; these belong to a separate trusted-execution/runtime-isolation phase.

- Killing the process that owns an occupied port.
- Automatically selecting a different port or rewriting project configuration.
- Proving OS-level ownership of externally started services.
- Adding a universal framework-specific health endpoint to every user project.

## Technical Notes

- Generic probe: `backend/app/application/local_service_probe.py`.
- Process liveness: `backend/app/application/project_run_manager.py`.
- Current reachability behavior is test-locked in `backend/tests/test_local_service_probe.py`.
- Admin demo backend fingerprint: `examples/admin-demo/backend/src/main/java/com/example/admindemo/AdminController.java` and its test.
- Admin demo frontend title: `examples/admin-demo/frontend/index.html`.
- Research is persisted under `research/readiness-identity-contract.md`.

## Research References

- [`research/readiness-identity-contract.md`](research/readiness-identity-contract.md) — Recommends a strict per-service HTTP readiness contract with expected status plus bounded `json_subset` / `text_contains`, while preserving transport reachability and process ownership as separate dimensions.
