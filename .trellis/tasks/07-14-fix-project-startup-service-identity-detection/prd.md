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

- How expressive should the first declarative response matcher be: exact scalar/path assertions only, or a broader JSON matcher language?

## Requirements (evolving)

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

## Decision (ADR-lite)

**Context**: Address reachability alone cannot distinguish the expected application from an unrelated listener, while requiring every project to implement a launch nonce would make adoption invasive.

**Decision**: Implement a generic declarative HTTP readiness/identity matcher. A service configuration can define the probe target and expected response properties; project-specific fingerprints live in configuration, never in platform code.

**Consequences**: Correct externally started instances can be recognized as ready, but readiness alone does not prove that the console launched or owns the process. A future optional launch token can add ownership proof without replacing the matcher contract. Legacy service configurations without a matcher are intentionally invalidated and must be regenerated; there is no compatibility fallback to generic reachability.

## Acceptance Criteria (evolving)

- [ ] An unrelated HTTP 200 service on admin-demo's configured port is not reported as admin-demo ready.
- [ ] HTTP 302, 404, and 500 responses remain observable as address reachability but do not establish application readiness.
- [ ] The correct admin-demo endpoint and expected response pass readiness.
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

## Out of Scope (tentative)

- Backward-compatible execution of legacy startup configurations without an identity matcher.

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
- Research will be persisted under `research/readiness-identity-contract.md`.
