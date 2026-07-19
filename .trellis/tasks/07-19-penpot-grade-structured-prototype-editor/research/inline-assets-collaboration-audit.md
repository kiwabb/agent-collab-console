# Inline Editing, Assets, and Collaboration Audit

## Direct Editing

Text, Input, Button, and Table already have typed fields and Inspector command paths:

* Node fields: `frontend/src/features/prototype/structured/types.ts:140`.
* `textContent`, `label`, `placeholder`, and `tableData` updates: `types.ts:363`.
* Inspector editing: `StructuredPrototypeInspector.tsx:193` and `:574`.

Canvas content is read-only in Design mode. There is no inline session, double-click/F2 entry, IME
handling, Escape cancel, commit-on-blur, or selection-chrome editing state:
`StructuredPrototypeCanvas.tsx:691`.

Static tables are editable through the Inspector, but the command replaces the complete table.
Before collaboration, introduce field commands such as `setTableCell` and
`setTableColumnLabel` plus row/column insert, remove, and reorder.

## Components and Assets

`componentDefinitions` and `assetRefs` are schema placeholders, not usable systems:

* Definitions exist in `types.ts:245` and backend codec `structured_prototype_contracts.py:644`, but
  there is no ComponentInstance node or definition/instance command family.
* Assets exist in `types.ts:262`, but there is no Image node, upload API, asset browser, or blob
  store. The current JSON object store accepts only `application/json` and the renderer rejects any
  asset with `renderer_assets_unsupported`.

Implement same-document component instances before cross-project libraries. Implement immutable
binary assets in a separate content-addressed blob store rather than embedding them in document JSON.

## Import and Export

Publication already produces deterministic `document.json`, `index.html`, and `runtime.js`, but it
is not an editable interchange flow. A future `.prototype.zip` should contain a hashed manifest,
document JSON, and immutable assets; import must support dry-run validation and explicit new/replace
confirmation.

## Collaboration

Current optimistic seq/hash validation detects concurrent writes and fails with `draft_conflict`,
but there is no prototype WebSocket/SSE stream, author identity, presence, comments, remote command
replay, or local rebase.

Recommended progression:

1. Unified inline-edit session for Text/Input/Button, then Table cells.
2. Fine-grained Table commands.
3. Same-document component definitions/instances and overrides.
4. Image node plus immutable asset pipeline.
5. Portable import/export package.
6. Document-external comments anchored to page/node/flow plus sequence/hash.
7. TTL presence and committed-command broadcast.
8. Server-authoritative remote replay, gesture rebase, and per-user undo. Use field soft locks for
   text first; add text CRDT only for simultaneous editing of the same field.
9. Version-pinned cross-project shared libraries with explicit upgrade and rollback.
