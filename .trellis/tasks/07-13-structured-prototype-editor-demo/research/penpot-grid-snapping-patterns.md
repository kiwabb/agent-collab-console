# Penpot Grid Snapping Patterns

## Scope and provenance

This note records the grid model and snapping behavior observed in a pinned Penpot
checkout. It is an interaction and data-contract study for the structured prototype
editor; it is not a request to copy Penpot implementation code.

- Repository: `https://github.com/penpot/penpot`
- Pinned commit: `167aa7410f95bce91b9a80059624a3e3d9307f1e`
- Local checkout: `/tmp/penpot-reference`
- License boundary: the inspected files carry the Mozilla Public License 2.0
  header. This project reimplements the observed contracts and algorithms and does
  not copy Penpot source code, Potok/Rx plumbing, or CSS/SVG implementation.
- Inspection date: 2026-07-17

The conclusions below are based on source inspection at that commit. No Penpot build
or runtime benchmark was used as evidence for this note. Paths and line numbers refer
to the pinned checkout.

## Verified Penpot contracts

### 1. Grid ownership and persisted shape

Penpot attaches grids to an individual frame, not to a transient project-wide canvas
mode. The frame stores a `grids` sequence. The page also has `default-grids`, which is
used as a template when a new frame grid is added; changing a frame grid and changing
the page default are separate operations.

Evidence:

- `common/src/app/common/types/grid.cljc:35-61` defines a discriminated `grid`
  schema with `:type`, `:display`, and `:params`, plus a separate
  `schema:default-grids` map for page defaults.
- `frontend/src/app/main/data/workspace/grid.cljs:23-36` creates a new square grid
  from the page's square default and appends it to the selected frame's `:grids`.
- `frontend/src/app/main/data/workspace/grid.cljs:39-51` removes or updates one
  frame grid by index.
- `frontend/src/app/main/data/workspace/grid.cljs:53-62` persists a changed default
  through a page change event rather than changing every existing frame.

The supported grid kinds are:

| Penpot kind | Parameters | Axis used for snap candidates |
| --- | --- | --- |
| `square` | `size`, `color` | X and Y |
| `column` | `type`, `size`, `margin`, `item-length`, `gutter`, `color` | X |
| `row` | the same layout parameters | Y |

The schema is in `common/src/app/common/types/grid.cljc:16-55`. Layout parameter
`type` is one of `stretch`, `left`, `center`, or `right`; for rows the UI labels the
last two directions as top and bottom. Parameters are permissive enough to represent
an automatic count or automatic item length (`nil` values).

The pinned defaults are explicit:

- square size `16`, info color, opacity `0.4`;
- column and row size `12`, `stretch`, automatic item length, gutter `8`, margin `0`,
  layout color, opacity `0.1`.

These defaults are defined at `common/src/app/common/types/grid.cljc:63-80`.

### 2. Geometry and grid-line generation

`common/src/app/common/geom/grid.cljc` is the pure geometry contract.

#### Square grids

`grid-snap-points` uses the frame's own `x`, `y`, `width`, and `height` and emits
internal lines at `size, 2*size, ...` up to but excluding the outer boundary
(`geom/grid.cljc:111-124`). X queries receive points on the top and bottom edges of
each vertical grid line; Y queries receive points on the left and right edges of each
horizontal line. A non-positive size produces no points.

`grid-areas` uses integer quotient/remainder arithmetic for rendering square cells
(`geom/grid.cljc:64-74`). The visible pattern is therefore a frame-local repeating
pattern, not an infinite page grid.

#### Column and row grids

`calculate-generic-grid` derives a count when `size` is absent, computes item length
when `item-length` is absent, and applies the requested left/center/right offset
(`geom/grid.cljc:27-52`). `stretch` recomputes the gutter to fill the available frame
length while clamping it to a non-negative number (`geom/grid.cljc:44-47`).

`grid-areas` returns a deterministic sequence of cell rectangles for all three grid
kinds (`geom/grid.cljc:90-102`). `grid-snap-points` uses the corners of those areas,
but only their X coordinates for a column grid and only their Y coordinates for a row
grid (`geom/grid.cljc:126-134`). Thus a column grid does not unexpectedly create Y
snap lines, and a row grid does not create X snap lines.

The frame's own outer edges are not special grid lines in the square implementation.
They remain available through ordinary shape/frame alignment candidates.

### 3. Visibility, snapping, and workspace flags

Penpot has two different scopes of state:

1. `grid.display` is stored on the frame grid and controls whether that individual
   grid is rendered.
2. Workspace layout flags control whether guide/layout candidates are considered at
   all. The valid flags include `:display-guides`, `:snap-guides`, and
   `:dynamic-alignment` (`frontend/src/app/main/data/workspace/layout.cljs:17-36`).

The default workspace layout contains all three (`layout.cljs:58-70`). The local-storage
mapping at `layout.cljs:141-168` persists only a different subset such as rulers and
palette visibility; `display-guides`, `snap-guides`, and `dynamic-alignment` are not in
that mapping. They are workspace state rather than frame-grid document fields.

The important Penpot coupling is in `common/src/app/common/geom/grid.cljc:111-115`:
`grid-snap-points` returns no points when `:display` is false. The main snap filter also
rejects every `:layout` candidate unless both `:display-guides` and `:snap-guides`
are enabled (`frontend/src/app/main/snap.cljs:29-58`). Therefore, in the inspected
version, hiding a grid also disables its snap points; there is no observed per-grid
`snapEnabled` field.

This coupling is a Penpot fact, not a requirement for this product. The product
recommendation below deliberately separates visibility from snapping so an author can
hide visual clutter while preserving a documented alignment aid.

### 4. Rendering behavior

The frame grid overlay is a separate controls/display layer:

- `viewport/frame_grid.cljs:21-47` renders a square pattern in frame coordinates,
  with one-physical-pixel strokes (`1 / zoom`).
- `viewport/frame_grid.cljs:49-114` renders column/row cells as translucent fills
  when there is a gutter, or as boundary lines when there is no gutter.
- `viewport/frame_grid.cljs:116-160` clips the overlay to the frame and visible
  parents, omits grids while the frame or an ancestor is transforming, and renders
  only `(:grids frame)` entries passing `:display`.
- `viewport/frame_grid.cljs:167-185` puts the whole overlay under
  `pointer-events: none`, filters rotated frames, and limits display to the current
  focus when a focus set exists.

This is the transferable interaction boundary: grid chrome must never become the DOM
target that steals a move/resize gesture, and transient transform state must not cause
the grid to jump or be committed as document content.

### 5. Snap index and candidate metadata

Penpot builds a range-tree index rather than scanning every shape on each pointer
move. The worker includes `:grids` in the frame snapshot attributes
(`frontend/src/app/worker/snap.cljs:22`).

For each eligible frame, `get-grids-snap-points` converts grid points into indexed
records with `:type :layout`, the frame ID, the grid kind, and the point
(`worker/snap.cljs:58-71`). Frame and shape points are inserted into per-frame X and Y
range trees (`worker/snap.cljs:73-102`), and updates remove the old frame data before
adding the new data (`worker/snap.cljs:181-191`, `228-263`). Hidden frames, hidden
parents, and layout descendants fail the frame-index eligibility gate. A blocked frame
suppresses its ordinary frame snap points, while rotated frames explicitly suppress grid
snap points (`worker/snap.cljs:58-61`, `78-102`).

Queries are range queries over the active page/frame/axis, with global guides merged
into the result (`worker/snap.cljs:268-279`). The indexed metadata retains the source
kind (`:layout` versus `:shape`), which is necessary for filtering and debugging.

A moving selection contributes its bounding-rectangle corners and center. Indexed
shapes contribute their geometry points and center, while frames additionally have
midpoints on each edge (`common/src/app/common/geom/snap.cljc:16-48`). The moving
selection therefore competes with grid coordinates using multiple anchors rather than
snapping only its top-left corner.

### 6. Thresholds and arbitration observed in Penpot

Penpot defines `snap-accuracy` as 10 client pixels and converts it to canvas units by
dividing by zoom (`frontend/src/app/main/snap.cljs:25-27`, `96-101`). Its dynamic
equal-distance alignment uses a separate 20-client-pixel threshold
(`main/snap.cljs:145-147`). Candidate queries are made around every moving anchor and
the nearest value on each axis is selected (`main/snap.cljs:109-125`).

`closest-snap-move` merges ordinary grid/shape point snapping with dynamic alignment
(`main/snap.cljs:271-288`). The observed `combine-snaps-points` operation keeps the
largest absolute X and Y correction from the merged results (`main/snap.cljs:259-269`);
it is not an explicit semantic priority such as "alignment beats grid." This is an
important distinction: the product should define its own deterministic precedence
instead of assuming that Penpot's merge function is a universal policy.

### 7. Grid editing UI and defaults

The frame-grid inspector exposes add, remove, visibility, type, and parameter edits.
Changing type replaces parameters with that type's defaults
(`ui/workspace/sidebar/options/menus/frame_grid.cljs:36-81`). Square size is edited
directly; column/row count can be automatic, and item length, gutter, margin, color,
and orientation are editable (`frame_grid.cljs:83-145`, `147-297`). Existing grids
can be reset to the page default or saved as the new page default.

The inspector is frame-scoped and keyed by frame ID plus grid index
(`frame_grid.cljs:299-350`). This supports the model that grid configuration is part
of the editable frame/document, while workspace visibility and snapping modes are
separate editor controls.

## Transferable algorithm contract

The following behavior is worth carrying over independently of Penpot's code:

1. **Frame-local ownership.** Resolve the grid configuration from the selected
   Freeform container. Do not use a hidden global grid that changes the meaning of an
   existing document.
2. **One raw frame.** Build all alignment, equal-spacing, and grid candidates from the
   same continuous, clamped pointer projection. Do not snap to alignment and then feed
   that result into a second grid solver.
3. **Anchor-based candidates.** For a single selection or rigid group union, use the
   left/center/right X anchors and top/center/bottom Y anchors. A grid line competes
   with the matching axis anchor and yields a correction plus stable source metadata.
4. **Axis-specific kinds.** Square produces both axes; columns produce X candidates;
   rows produce Y candidates. This follows Penpot's geometry and prevents a column
   layout from creating surprising vertical snaps.
5. **Zoom-stable tolerance.** Keep the product's existing six-client-pixel threshold,
   represented in canvas units as `6 / frozenPreviewScale`. Keep continuous values
   until the canonical command boundary.
6. **Deterministic arbitration.** Choose the smallest absolute correction. On an exact
   tie, use the explicit product order `alignment > equal-spacing > grid`; then sort by
   grid ID, axis, anchor, line coordinate, and candidate index. Never depend on DOM or
   array arrival order.
7. **Final-frame validation.** Combine X and Y winners, revalidate the complete moving
   frame against Freeform bounds and any existing spacing/lane constraints, and fall
   back to the next deterministic candidate if the other axis invalidates a winner.
8. **Transient controls only.** Draw grid overlays and snap guides in a sibling controls
   layer with pointer events disabled. Design mode owns gestures; Preview mode owns
   buttons, inputs, tables, and runtime navigation.
9. **One transaction.** Pointer movement updates a local projection only. Pointer-up
   recomputes the exact final projection and submits the existing atomic move command;
   Escape, pointer cancel, blur, and lost capture submit nothing.

## Recommendation for this project

This section is deliberately separate from the Penpot observations. It is the proposed
contract for the structured prototype editor, not a statement about Penpot behavior.

### A. Document model

Add a versioned `grids` collection to every `Freeform` node. The collection is empty
when no grid is configured. A discriminated `FreeformGridV1` should contain:

```json
{
  "id": "stable-grid-uuid",
  "version": 1,
  "type": "square",
  "visible": true,
  "snapEnabled": true,
  "origin": {"x": "0", "y": "0"},
  "params": {
    "size": "16",
    "colorTokenKey": "color-accent",
    "opacity": "0.4"
  }
}
```

The `columns` and `rows` variants should use the same envelope and replace `size`
with explicit layout parameters:

```json
{
  "id": "stable-grid-uuid",
  "version": 1,
  "type": "columns",
  "visible": true,
  "snapEnabled": true,
  "origin": {"x": "0", "y": "0"},
  "params": {
    "count": 12,
    "itemSize": null,
    "gutter": "8",
    "margin": "0",
    "alignment": "stretch",
    "colorTokenKey": "color-muted",
    "opacity": "0.1"
  }
}
```

Recommended invariants:

- `id` is a stable UUID and grid order is canonical list order; all candidate and
  command records include the grid ID.
- `origin` is Freeform-local and canonical. Version 1 defaults to the top-left
  origin (`0,0`); changing the origin semantics requires a new grid version rather
  than silently changing old documents.
- Decimal geometry uses the existing canonical decimal-string boundary and the same
  bounded envelope as Freeform layout. Runtime calculations may use floating point,
  but preview and command encoding normalize only machine-precision tails.
- `count`, `itemSize`, `gutter`, and `margin` have explicit bounded ranges. `null`
  means automatic calculation, not zero. `alignment` is limited to
  `stretch | start | center | end`.
- Color is a token reference plus bounded canonical decimal-string opacity, not a
  JSON float or arbitrary style dictionary. The object-store canonical JSON contract
  rejects floats, so values such as forty percent serialize as `"0.4"`.
- Grids are direct properties of a `Freeform` node, whether that node is a page root or
  nested. They never live on the page envelope or on Stack, Grid, or Form nodes.
  Freeform children remain the only nodes eligible for free positioning.

The current frontend codec uses exact per-node key sets
(`frontend/src/features/prototype/structured/rendererDocumentCodec.ts:324-385`) and
the backend uses strict Pydantic models with `extra="forbid"`
(`backend/app/application/structured_prototype_contracts.py:45-53`). Therefore the
implementation must update the TypeScript codec, frontend types, backend strict models,
new-node models, serializers, and fixtures together.

### B. Compatibility and defaults

Do not make `grids` required at the raw wire boundary before old drafts are readable.
Use one explicit compatibility rule:

1. A missing `Freeform.grids` is accepted by the document decoder as the canonical
   empty-grid representation. A single typed read helper exposes it to editor logic as
   `[]` without adding an enumerable property to the decoded document.
2. Empty grids remain omitted from canonical JSON. Only a non-empty validated list of
   `FreeformGridV1` objects is serialized. This preserves historical document,
   checkpoint, journal, and renderer hashes; deleting the last grid restores the exact
   pre-grid canonical payload.
3. Unknown grid versions or unknown fields fail closed with a typed codec/contract
   error. They must not be silently dropped.
4. The migration is a read-boundary normalization, not a bulk historical rewrite.
   Add a document schema version only when the existing versioning contract requires
   it, and test both old and new canonical hashes.

This preserves current `admin-demo` drafts while keeping the future format exact and
replayable.

### C. Visibility versus snapping

Keep three effective switches:

| Scope | Field | Meaning |
| --- | --- | --- |
| Document/grid | `visible` | This grid may render in Design mode. |
| Document/grid | `snapEnabled` | This grid may contribute snap candidates. |
| Editor session | `gridSnappingEnabled` | Global gate for all grid candidates. |

The effective rules are:

```text
renderGrid = designMode && session.displayGuides && grid.visible
useGridCandidates = designMode && session.gridSnappingEnabled && grid.snapEnabled
```

The per-grid fields belong to the document and are changed through an undoable grid
configuration command. The session gate is editor state, but every gesture evidence
record and replay manifest must capture its value. This gives the product the useful
behavior Penpot does not expose in the inspected version: a grid can be hidden while
remaining an intentional snap aid.

Grid settings never affect Preview/runtime interactions. Runtime controls must not be
blocked by the visual overlay or by design-mode candidate logic.

### D. Commands and persistence

Use the existing atomic `setNodeProperty` command with a discriminated
`freeformGrids` update for add, update, remove, and reorder operations. It must include:

- expected draft head sequence and contract version;
- the Freeform node ID;
- the complete after grid list; the existing inverse-command machinery captures the
  complete before list losslessly;
- normalized grid configuration hash;
- inverse data for Undo/Redo.

Moving a node uses the existing Move command. Grid snapping changes only the transient
projection until pointer-up; it must not append a command per pointer move. A failed
grid edit or move preserves the last accepted document and reports a typed error.

The browser and backend replay continue to share the pinned TypeScript runtime core;
Python validates and stores the document but does not implement a second grid solver.

### E. Candidate arbitration and guides

For each RAF projection:

1. Freeze the eligible Freeform grids and visible direct siblings at pointer-down.
2. Compute the clamped raw selection union from the latest pointer coordinates.
3. Generate alignment, equal-spacing, and grid candidates from that same raw frame.
4. Reject candidates outside the six-client-pixel threshold, Freeform bounds, or the
   current group constraints.
5. Pick the smallest correction per axis. Exact correction ties use
   `alignment > equal-spacing > grid`, followed by stable IDs and coordinates.
6. Combine axes, revalidate the complete frame, and retry the next deterministic
   candidate if a cross-axis rule is violated.
7. Render the chosen guide and grid overlay from the same projected frame that will be
   committed on pointer-up.

Grid guide metadata should include `gridId`, grid type, axis, anchor, source line,
raw coordinate, correction, threshold, and the effective switch values. This prevents
the current failure mode where a dragged element is represented only by its component
type and the user cannot tell what it snapped to.

### F. Observability and reproducibility

Every grid configuration mutation and every committed snap move should be explainable
without reading browser DOM state. Capture:

- document ID, draft head sequence, document object hash, and command contract version;
- Freeform ID and selected node IDs in canonical order;
- grid list hash and each effective `visible`, `snapEnabled`, and session gate value;
- frozen preview scale, client threshold, raw frame, final frame, and correction;
- candidate source IDs/kinds, deterministic sort key, winner, and rejection reason for
  any candidate that was close enough to compete;
- modifier state (`Ctrl`/`Meta` bypass), gesture phase, and cancellation reason;
- resulting command batch hash, new sequence, and Undo/Redo linkage.

Preview frames may retain only a bounded diagnostic ring, but pointer-up and failed
operations must retain a durable terminal record. A replay should be able to recompute
the same winner and final frame from the frozen document, grid settings, geometry,
pointer trace, and pinned runtime version. A hash mismatch fails closed and keeps the
last accepted document.

### G. Focused test matrix

#### Contract and compatibility

- Decode a legacy Freeform with no `grids` and assert canonical `[]`.
- Reject unknown grid type, version, field, token, non-canonical decimal, negative
  value, zero square size, invalid count, invalid opacity, and duplicate grid ID.
- Round-trip TypeScript codec, backend strict model, canonical JSON, object hash, and
  restart recovery for empty and non-empty lists.
- Validate that Stack/Grid/Form children and responsive overrides cannot carry grid
  fields or Freeform positions.

#### Geometry and rendering

- Golden vectors for square, columns, and rows with explicit and automatic parameters.
- Origin, margin, gutter, centered/right-aligned, fractional item length, and frame
  boundary cases.
- `visible=false` produces no overlay; `snapEnabled=false` produces no candidate; the
  global gate disables all grid candidates without changing the document.
- Hidden Freeforms, transforming frames, clipping, pointer-events, and
  one-physical-pixel strokes across supported zoom values. Rotation remains absent
  from the version-1 product contract rather than being approximated.

#### Move and arbitration

- Single and rigid grouped selections using all three anchors on each axis.
- Alignment, equal-spacing, and grid candidates from one raw frame; exact ties choose
  alignment, then spacing, then grid.
- Stable result when sibling/grid array order is permuted; stable result when two grids
  share a line; deterministic fallback after cross-axis invalidation.
- Six-client-pixel inclusive boundary and `+1e-6` rejection at zoom 0.5, 1, 2, and 4.
- Ctrl/Meta bypass, Escape, pointer-cancel, blur, lost capture, pending command,
  stale head, failed command, one-batch commit, and one-step Undo.

#### Performance and evidence

- Range-index or equivalent candidate lookup with adversarial 100/200/400-node scenes.
- Exact semantic cache keys include axis, grid ID, line coordinate, moving frame, and
  effective flags; no hidden full-scan path in RAF work.
- Browser acceptance at desktop and mobile widths verifies no console error, no DOM
  interaction theft, no preview sequence mutation, and exact pointer-up persistence.

## Implementation sequence

1. Land `FreeformGridV1` types and a single non-mutating empty-grid read helper in the
   frontend plus an omitted-empty default in backend contracts; add round-trip, hash,
   and strictness fixtures.
2. Add the atomic `freeformGrids` command, inverse payload, optimistic head check,
   persistence, Undo, and Redo.
3. Add default values, Inspector controls, stable grid IDs, and frame-local grid
   rendering in a pointer-events-disabled controls layer.
4. Add the pure square/columns/rows geometry module and golden tests.
5. Integrate grid candidates into the existing Freeform move solver using one raw-frame
   arbitration path and the explicit precedence above.
6. Add durable candidate/gesture evidence and replay assertions.
7. Complete the in-app browser acceptance before marking the grid slice complete.

## Non-goals and open boundaries

- Do not copy Penpot's MPL source, range-tree implementation, Potok streams, or WASM
  renderer. Reuse the contracts and write a small TypeScript implementation consistent
  with this product's existing RAF and command journal.
- Do not make page-wide arbitrary positioning legal. Grids apply only to direct
  children of an explicit Freeform container.
- Do not add rotation-aware grid snapping in this slice. Penpot omits rotated frame
  grids from its snap index; matching that restriction keeps the first contract clear.
- Do not infer a per-grid `snapEnabled` field from Penpot; it is a deliberate product
  extension and must be tested and documented as such.
- Whether future documents should expose page-level grid presets remains open. A preset
  may be added later, but it must copy validated params into a Freeform and never become
  a hidden runtime dependency.
