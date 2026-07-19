# Fix Prototype Runtime Worker Initialization Timeout

## Goal

Prevent valid structured prototype runtime initialization and replay from failing at a hard-coded five-second worker deadline while preserving fail-closed timeout behavior and operation auditability.

## What I Already Know

- Two independent `create_runtime_session` operations failed with `runtime_worker_timeout`.
- Operation `f2c24ba6-1cc9-5d15-95e8-69e8ad84187a` ran `initialize_runtime_session` for about 5.04 seconds before failing.
- Operation `c57fe71b-22d2-5837-8eef-6e4feba77c1a` reproduced the same failure.
- Operation `7b22f8ad-a75d-5ff7-a542-fd19ed450a14` reproduced the same worker timeout in `replay_runtime_session` / `replay_runtime_event_tail`, proving the deadline affects more than session initialization.
- `PrototypeRuntimeWorker` uses a hard-coded `_DEFAULT_TIMEOUT_S = 5.0`.
- The Node executable and runtime worker bundle are available; a direct `describe` request completes successfully.
- Worker timeout already fails closed: the child process is killed and the operation is persisted as failed.

## Requirements

- Valid structured prototype runtime initialization and replay must have enough time to complete under normal local development workloads.
- The worker deadline must be configurable at the backend composition boundary rather than hidden as an adapter-only magic number.
- Invalid timeout configuration must fail loudly during backend startup.
- A timed-out worker must still be killed and the operation must remain failed with `runtime_worker_timeout`.
- Runtime worker execution must emit enough structured timing context to distinguish an actual slow worker from spawn, protocol, or validation failures.
- Existing operation idempotency and persisted audit records must remain unchanged.

## Acceptance Criteria

- [x] Runtime actions receive a 30-second default deadline instead of the previous five-second deadline.
- [x] A worker exceeding the configured deadline is terminated and reported as `runtime_worker_timeout`.
- [x] The configured deadline is validated as a positive finite duration.
- [x] Logs identify the worker action, configured deadline, elapsed time, and request/operation identifier without logging document payloads.
- [x] Focused backend tests cover configured timeout propagation and timeout failure behavior.
- [x] The reproduced structured prototype runtime session replays successfully after the fix.

## Definition of Done

- Focused tests pass.
- Backend import/startup smoke passes.
- No broad build or frontend checks are required unless frontend code changes.
- Relevant specification knowledge is reviewed and updated only if a reusable convention is discovered.

## Technical Approach

Use a conservative configurable deadline at backend bootstrap, pass it explicitly into `PrototypeRuntimeWorker`, and add bounded observability around `_execute`. Preserve the current process termination and fail-closed service transition.

## Decision (ADR-lite)

**Context**: A fixed five-second deadline repeatedly rejects valid runtime initialization, but removing the deadline would allow a stuck worker to consume resources indefinitely.

**Decision**: Keep a bounded deadline, raise the production default to a value suitable for local structured prototype initialization, make it configurable and validated at startup, and record action-level elapsed timing.

**Consequences**: Slow valid initializations can complete, operators can tune the threshold, and genuine hangs still fail closed. A higher deadline means users wait longer before a true hang is reported.

## Out of Scope

- Rewriting the JavaScript runtime engine.
- Changing operation idempotency or deleting failed audit records.
- Adding automatic retries, which could duplicate expensive deterministic work and obscure the original failure.
- Frontend route or information-architecture cleanup.

## Technical Notes

- `backend/app/adapters/prototype_runtime_worker.py` defines the five-second default and enforces the deadline in `_execute`.
- `backend/app/bootstrap.py` constructs `PrototypeRuntimeWorker()` without an explicit timeout.
- `backend/app/application/structured_prototype_service.py` correctly maps worker errors to failed operations.
- `backend/tests/test_prototype_runtime_worker.py` is the focused adapter test suite.
- `backend/tests/test_structured_prototype_service.py` covers persisted runtime operation failures.
