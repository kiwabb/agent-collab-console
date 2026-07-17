# Structured Prototype Object Store Foundation

Date: 2026-07-13

## Completed Scope

- Added a managed, project-scoped content-addressed object store in `backend/app/adapters/prototype_object_store.py`.
- Added immutable object descriptor and owner-reference domain records in `backend/app/domain/structured_prototype.py`.
- Added an isolated async SQLite descriptor/reference store in `backend/app/adapters/structured_prototype_store.py`.
- Added the shared schema to both production SQLite stores and advanced the main schema version to 10.
- Added durable operation, step and event evidence plus document, draft, checkpoint and append-only command-batch records.
- Added atomic initial-document/checkpoint creation, optimistic command append, checkpoint registration and consistent recovery-bundle reads.
- Pinned `zstandard==0.25.0` and a fixed codec profile: level 10, checksum and content size enabled, dictionary ID disabled, single-threaded deterministic compression.
- Canonical object identity is computed from uncompressed UTF-8 bytes; storage identity is computed separately from compressed bytes.
- Local layout is `<data_root>/projects/{project_id}/prototype-store/objects/<prefix>/<hash>.json.zst`; no canonical object is written into the Git project directory.
- Object installation uses a same-filesystem temporary file, file fsync, non-overwriting hard-link installation, directory fsync and full read-back/decompression/hash verification.
- Existing objects are never overwritten. A mismatched or corrupt object at the expected content path fails closed.
- SQLite stores descriptors and typed owner references only. It has no document/payload JSON column.
- Descriptor registration is transactional, idempotent and rejects conflicting descriptors without inserting the new reference.

## Cross-Language Canonical Fixture

Python and TypeScript both produce the following canonical bytes for the fixture containing ASCII, private-use and non-BMP keys:

```json
{"a":[true,null,"中文"],"z":2,"":"private","😀":"emoji"}
```

Pinned content hash:

```text
sha256:13b8db984e15a32f530afbda948a2f354b9fb276e6e73c16c45e0427a26cbfd5
```

## Verification

```text
Backend focused object/store/journal tests PASS, 33/33
Existing schema-v10 migration tests        PASS, 6/6
Journal suite alone                        PASS, 9/9
Ruff check                              PASS
Ruff format --check                     PASS after formatting
Strict mypy for 5 touched modules/tests  PASS
uv lock --check                          PASS
uv pip check                             PASS
Frontend runtime/core tests              PASS, 12/12
Frontend strict TypeScript               PASS
```

The repository-wide strict coverage test still reports two unrelated pre-existing untracked modules, `app.application.project_startup_mcp` and `app.application.project_startup_service`, missing from the strict override list. The new structured-prototype modules are present in that list and pass direct strict mypy.

## Not Yet Implemented

- No bootstrap wiring or API route uses these stores.
- No application service validates a full `PrototypeDocumentV1`, executes typed commands, or rebuilds active state from the recovery bundle.
- Recovery does not yet read and validate object bytes, replay command bodies, or durably mark a failed draft `corrupt`.
- No GC process consumes object references.
- No frontend runtime is connected to the structured draft API.

The next implementation step is the strict document/command executor and draft application service. It must create durable operation evidence before writing an object, verify every replay hash, and fail closed on recovery corruption before any API or Studio integration is enabled.
