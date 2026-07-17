# Studio Runtime Vertical Slice

Date: 2026-07-13

## Completed

- Added typed frontend contracts and API clients for structured drafts, command batches, runtime sessions, event batches, recovery, and checkpoints.
- Added strict runtime state and view-model JSON parsing before React state mutation.
- Added a production Studio route at `/projects/{project_id}/prototypes/studio` and an entry in the existing prototype workbench menu.
- Added a deterministic three-page procurement seed document with two simulated roles, one mock entity schema, one form, three executable rules, three Flow projections, and all six MVP component types.
- Connected document recovery, runtime recovery, runtime events, optimistic command application, and checkpoint creation to the durable backend APIs.
- Added palette drag/drop and mobile tap insertion through `insertNode`, direct page-root reordering through `moveNode`, and Text/Input/Button property editing through `setNodeProperty`.
- Added Design and Flow modes. Flow reads document rule projections and does not create a second executable edge authority.
- Added desktop three-region layout and mobile Page/Canvas/AI work-area switching without document-level horizontal overflow.
- Added visible draft/runtime sequence, hashes, operation errors, and checkpoint evidence.

## Browser Acceptance Evidence

The local browser executed the backend-backed workflow:

1. Applicant entered `研发笔记本电脑` and amount `12500`.
2. Submit produced runtime sequence 1 and navigated to detail with status `待审批`.
3. Role switch produced runtime sequence 2 and exposed the manager approval action.
4. Approval produced runtime sequence 3; detail and list both displayed `已通过`.
5. Runtime checkpoint advanced to sequence 3.
6. Reload recovered the same role, entity state, state hash, view-model hash, and checkpoint sequence.
7. Dragging a Text component advanced the draft head and created a new pinned runtime session.
8. Editing the inserted Text through the inspector advanced the draft head again.
9. Mobile Page/Canvas/AI switching and tap-to-insert were exercised at a narrow viewport.

## Verification

- Frontend full tests: `476 passed`.
- Frontend strict typecheck: passed.
- Frontend full lint: passed.
- Changed-file Prettier check: passed.
- Structured backend suite: `63 passed`, with the existing Starlette/httpx deprecation warning only.
- Frontend procurement fixture validated directly through backend `NewPrototypeDocumentV1` strict Pydantic validation.
- OpenAPI exposes all four runtime session routes.

## Still Required For Final Goal

- Claude Code UI Engineer initial generation pipeline.
- Claude conversational proposal, preview, Apply, and Reject workflow.
- Deterministic renderer, immutable publish revision, share URL, and runnable published preview.
- Editable Flow rule inspector and persisted Flow node repositioning.
- Nested-container drag targets beyond direct page-root ordering.
- Final automated end-to-end acceptance that starts from Claude generation and ends at published preview.

## Completion Update - 2026-07-14

The generation, AI conversation, publication, share preview, and full runtime
acceptance items above are now complete. Studio bootstrap no longer creates the
procurement fixture when browser storage is empty; it resolves the project-current
draft from the backend and routes document-free projects to requirements
generation. Production runtime actions no longer import fixture UUIDs and instead
derive their identities from the accepted document's semantic runtime contract.

The remaining Flow inspector and nested-container items are post-MVP expansion;
they are not part of the locked vertical-slice acceptance in `final-goal.md`.
