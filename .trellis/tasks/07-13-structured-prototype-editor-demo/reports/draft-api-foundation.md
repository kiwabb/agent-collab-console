# Structured Prototype Draft API Foundation

Date: 2026-07-13

## Completed Scope

- Added strict `PrototypeDocumentV1` and `DomainCommandBatchV1` contracts for the MVP `Stack`, `Form`, `Text`, `Input`, `Button`, and `Table` node set.
- Added canonical UUID, route, technical-key, length, responsive, table, runtime-reference and runtime-expression validation before persistence.
- Added deterministic UUIDv5 allocation for batch-local node keys.
- Added pure insert, move, remove, property, layout and page-order execution with server-owned inverse commands and exact inverse hash round trips.
- Added `StructuredPrototypeService` orchestration for durable create, recovery and optimistic command application.
- Create and apply operations persist queued/running evidence before object or journal effects and commit succeeded evidence with the authoritative checkpoint or batch.
- Recovery verifies the checkpoint object, strict document schema, canonical command payload, command-batch hash, inverse payload, every base/result hash and the final draft head.
- Object, schema or replay corruption atomically marks the same draft head `corrupt` with failed operation/step/event evidence.
- Added versioned create/get/apply HTTP endpoints with camel-case-only nested payload validation and a stable error envelope.
- Wired the service through bootstrap, a managed `STRUCTURED_PROTOTYPE_DATA_ROOT`, app OpenAPI and lifespan shutdown.

## HTTP Surface

```text
POST /api/projects/{project_id}/structured-prototype-documents
GET  /api/structured-prototype-drafts/{draft_id}?clientRequestId=...
POST /api/structured-prototype-drafts/{draft_id}/commands
```

Create does not accept a document ID. The service deterministically allocates it from project and client-request identity. Apply requires both expected head sequence and document hash. All successful responses return the authoritative structured document and operation/correlation evidence.

## Verification

```text
Focused object/store/journal/contract/service/API/source tests  PASS, 47/47
Schema-v10 migration tests                                      PASS, 6/6
Strict mypy over 13 structured-prototype modules/tests          PASS
Ruff check and format check                                     PASS
App import, OpenAPI routes and configured service wiring         PASS
```

The repository-wide strict-coverage test still has the same unrelated baseline failure: untracked `app.application.project_startup_mcp` and `app.application.project_startup_service` are absent from the strict override list. All new structured-prototype modules are listed and pass direct strict mypy.

## Not Yet Implemented

- Runtime session/event/checkpoint tables and the Node-worker replay boundary.
- Automatic 30-second/50-batch checkpoints; the 200-batch hard refusal is active.
- Undo/redo target selection and append-only compensation endpoints.
- Reusable-component, navigation, runtime-definition and Flow editing commands beyond the current MVP node/page commands.
- Studio API integration, deterministic renderer, publish/share, GC and Claude generation/conversation workflows.

The next step is runtime-session persistence. It must pin document/scenario/runtime versions, store semantic event batches and state/view-model hashes, and prove browser/Node-worker parity before the Studio uses the API.
