# Existing Prototype Backend Contracts

## Scope

This note records the repository patterns that the structured prototype backend design should preserve. It is local code research, not an implementation plan.

## Existing Aggregate

- `backend/app/domain/models.py` defines `Prototype` and `PrototypeVersion` as the current HTML-oriented aggregate.
- `PrototypeVersion` stores a complete HTML document and an optional immutable disk path.
- `backend/app/application/prototype_service.py` streams a full HTML document from the model and only appends a version after the provider emits the required terminal event and the HTML is complete.
- The current aggregate represents an individual generated page. It does not own a shared page tree, navigation model, component graph, or business flow.

## Existing SQLite Patterns

- All SQL lives in `backend/app/adapters/async_sqlite_store.py`.
- Multi-row publication uses a dedicated store method with `BEGIN IMMEDIATE`, state preconditions, and one commit.
- `append_prototype_version` allocates the next positive version inside the write transaction.
- `complete_prototype_generation_item` atomically inserts the immutable version, advances the prototype pointer, updates the run item, and refreshes run counters.
- Cross-process idempotency is enforced in SQLite. Service-local locks are only an optimization.
- Boot recovery converts active generation work into explicit interrupted terminal states instead of pretending it completed or automatically issuing duplicate model calls.

## Existing Durable Work Pattern

- `PrototypeGenerationRun` and `PrototypeGenerationRunItem` persist status, phase, counters, attempts, timestamps, errors, and runtime identifiers.
- SSE emits validated complete snapshots plus heartbeats. The transport validates resource identity before sending a snapshot.
- A reconnecting client can load the same snapshot through HTTP and continue observing through SSE.
- Retry creates a new run for failed/interrupted work instead of mutating terminal history.

## Existing Artifact Pattern

- `backend/app/application/prototype_version_artifacts.py` writes project-local immutable artifacts before the database commit.
- Paths are containment-checked, symlinks are refused, UTF-8 is enforced, and files use exclusive creation.
- If database completion is ambiguous after the file write, the service reconciles against durable database state and does not delete the file immediately.
- Reads verify that the file path matches the record identity and that disk content matches the database record.

## Consequences for the New Design

1. The structured subsystem should be a new aggregate rather than adding JSON fields to `prototype_versions`.
2. The authoritative payload should be an immutable validated document snapshot; HTML remains a derived artifact.
3. Active editing needs a materialized in-memory state for fast loading, immutable managed checkpoints, and an append-only SQLite command history for recovery, undo, audit, and AI attribution. A full draft JSON column is not required.
4. User mutations, AI proposal application, and publication need database-enforced optimistic concurrency and idempotency.
5. Model calls and rendering must happen outside SQLite transactions.
6. Publication must advance the public pointer only in the same transaction that records a verified render artifact.
7. Active work must become explicitly interrupted on restart; the last published revision remains available.
8. Object/checkpoint bytes must be written, fsynced, read back, and validated before SQLite registers a reference; ambiguous DB completion is reconciled and unreferenced objects are collected later.

## Files Inspected

- `backend/app/domain/models.py`
- `backend/app/domain/prototype_generation.py`
- `backend/app/application/prototype_service.py`
- `backend/app/application/prototype_generation_service.py`
- `backend/app/application/prototype_version_artifacts.py`
- `backend/app/adapters/async_sqlite_store.py`
- `backend/app/interfaces/sse.py`
- `backend/tests/test_prototype_generation_service.py`
