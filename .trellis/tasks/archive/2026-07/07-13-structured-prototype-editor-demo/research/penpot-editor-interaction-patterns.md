# Penpot Editor Interaction Patterns

## Reference

- Repository: `https://github.com/penpot/penpot`
- Branch: `develop`
- Commit: `167aa7410f95bce91b9a80059624a3e3d9307f1e`
- Checkout: `/tmp/penpot-reference`
- License: MPL-2.0. This task reuses architecture and interaction ideas, not Penpot source code.

All Penpot paths and line numbers below refer to the pinned checkout and commit above.

## What Penpot Actually Does

Penpot does not make arbitrary application DOM draggable. It separates the rendered
content from a top-level interaction layer, then treats each pointer gesture as a
transaction with transient modifiers and one final persistent commit.

### Viewport and coordinates

- `frontend/src/app/main/data/workspace/zoom.cljs:25` keeps `zoom`,
  `zoom-inverse`, and the view box synchronized. Zoom is performed around an explicit
  canvas point, normally the pointer.
- `frontend/src/app/main/data/workspace/zoom.cljs:113` computes fit from the union of
  visible shape bounds plus fixed padding.
- `common/src/app/common/geom/align.cljc:125` owns the pure fit geometry.
- `frontend/src/app/main/ui/workspace/viewport/viewport_ref.cljs:23` observes viewport
  bounds; `viewport_ref.cljs:55` centralizes client-to-canvas conversion: subtract the
  viewport origin, divide by zoom, then add the view-box origin.
- `frontend/src/app/main/data/workspace/viewport.cljs:206` divides pan deltas by zoom,
  so panning speed is stable in canvas coordinates.
- `frontend/src/app/main/ui/workspace/viewport/actions.cljs:359` converts pointer events
  once and publishes canvas coordinates plus client-space movement in one event.
- `frontend/src/app/main/ui/workspace/viewport/actions.cljs:383` and
  `actions.cljs:403` accumulate wheel zoom and scroll respectively, then flush each
  accumulator once through `requestAnimationFrame`; `app/util/dom/normalize_wheel.js:128`
  normalizes browser delta modes.

The DOM editor should expose one `ViewportTransform` contract with `clientToCanvas`,
`canvasToClient`, `zoomAtPoint`, and `fitRect`. Use floating-point `DOMMatrix` inversion;
do not scatter `/ previewScale` calculations across node components.

### Content and interaction layers

- `frontend/src/app/main/ui/workspace/viewport.scss:9` stacks render, control, and HTML
  overlay layers over the same viewport.
- `frontend/src/app/main/ui/workspace/viewport.cljs:372` prevents the classic SVG
  render layer from owning pointer interaction.
- `frontend/src/app/main/ui/workspace/viewport.cljs:419` mounts a separate controls
  layer for selection and transforms with the same view box as the render layer.
- `frontend/src/app/main/ui/workspace/viewport.cljs:491` renders the selection area;
  `viewport.cljs:698` renders handlers later in the controls tree so they stay on top.
- `frontend/src/app/main/ui/workspace/viewport_wasm.cljs:672` is the event-free Canvas
  renderer and `viewport_wasm.cljs:694` is its separate SVG controls layer.
- `frontend/src/app/main/ui/workspace/viewport/selection.cljs:44` inflates tiny selection
  hit regions to `10 / zoom`; `selection.cljs:78` calculates four side and four corner
  resize handles, while `selection.cljs:214` separates visible points from larger hit
  targets.

This is the key answer to the current "components block dragging" problem: prototype
buttons, inputs, and tables must not compete with editor gestures while Design mode is
active. Runtime interaction belongs to an explicit Preview mode.

### Layer-tree drop intent

- `frontend/src/app/main/ui/hooks.cljs:90` implements nested sortable cleanup at the
  leaf target and broadcasts drag-end cleanup to every entered node.
- `frontend/src/app/util/dom/dnd.cljs:131` classifies a container target into `top`,
  `center`, or `bot`. Container edges are the outer 20%; the middle 60% means "inside".
  Non-container targets split at 50% into before/after.
- `frontend/src/app/main/ui/workspace/sidebar/layer_item.cljs:374` maps those explicit
  intents to parent and index. It validates the target parent before relocating.
- `frontend/src/app/main/ui/workspace/sidebar/layer_item.cljs:555` renders separate
  visual states for center, top, and bottom.
- `frontend/src/app/main/data/workspace/shapes.cljs:524` removes nested selected loops
  and refuses to relocate a parent into its own descendant.
- `common/src/app/common/geom/shapes/flex_layout/drop_area.cljc:21` builds continuous
  child drop areas from direction, gaps, reverse order, and child midpoints;
  `drop_area.cljc:141` handles wrapped lines and `drop_area.cljc:211` resolves the area
  containing the pointer to an insertion index.
- `frontend/src/app/main/ui/workspace/sidebar/sitemap.cljs:142` uses the same top/bottom
  contract for page ordering.

The transferable pattern is an explicit `before | inside | after` drop plan. A single
`closestCenter` result is not enough for a nested business-page tree. For DOM layouts,
measure parent and child rectangles, group wrapped Grid children into visual rows, and
split the main axis at adjacent child midpoints. Resolve the deepest valid area and keep
the dragged subtree out of the candidate set.

### Move and resize transactions

- `frontend/src/app/main/data/workspace/transforms.cljs:151` implements eight resize
  directions, fixed opposite origins, Shift aspect locking, Alt center resize, rotation
  compensation, and scale-aware geometry.
- `frontend/src/app/main/ui/workspace/viewport/selection.cljs:78` calculates four
  corners, four sides, and rotation hit regions. Handle dimensions are divided by zoom,
  so their screen hit area stays usable at every scale.
- `frontend/src/app/main/data/workspace/transforms.cljs:593` waits for a movement
  threshold before starting a move.
- `frontend/src/app/main/data/workspace/transforms.cljs:668` continuously derives a
  valid parent, flex insertion index, grid cell, snapping, and axis constraints.
- `frontend/src/app/main/streams.cljs:25` owns separate temporary modifier and selection
  rectangle subjects so live preview can bypass unrelated global-store subscriptions.
- `frontend/src/app/main/constants.cljs:337` sets transform preview sampling to 16ms.
  Resize calls `rx/sample` at `transforms.cljs:312` and `transforms.cljs:340`; move does
  so at `transforms.cljs:806` and `transforms.cljs:846`. This is a frame-rate cadence,
  not a universal RAF pipeline.
- `frontend/src/app/main/data/workspace/modifiers.cljs:626` publishes temporary selection
  geometry, `modifiers.cljs:633` publishes temporary modifiers, and
  `modifiers.cljs:665` applies live WASM modifiers.
- `frontend/src/app/main/data/workspace/transforms.cljs:326` takes the exact last resize
  event before commit. Move does the same at `transforms.cljs:827` and
  `transforms.cljs:867`, then wraps geometry, reparenting, and undo in one transaction.
- `frontend/src/app/main/data/workspace/modifiers.cljs:742` commits WASM geometry;
  `modifiers.cljs:932` and `modifiers.cljs:975` are the non-WASM commit path.
- `frontend/src/app/util/mouse.cljs:79` stops a gesture on pointer-up, blur, or explicit
  interrupt; the transform streams, not the stopper itself, preserve the exact tail.

The transferable transaction is:

```text
pointer down
  -> capture start geometry and document head
  -> show transient local projection
  -> coalesce preview at frame-rate cadence (Penpot: rx/sample 16ms; this product: RAF)
  -> pointer up/cancel
  -> calculate the exact final frame from the latest pointer event
  -> submit one typed command batch
  -> keep projection until server confirmation
  -> accept authoritative result or roll back with visible error
```

For this product, keep a single top-level
`idle | pan | marquee | move | resize` gesture state. Pointer movement updates only a
mutable latest-draft ref; one RAF projects that draft. Pointer-up computes the final
draft synchronously and submits exactly one command. Pointer-cancel or Escape discards
the draft and submits nothing.

## Decisions for This Product

### Implement now

1. Separate Design gestures from Preview runtime interaction.
2. Use explicit before/inside/after targets with visible insertion feedback.
3. Prefer the deepest valid nested target and refuse moves into the dragged subtree.
4. Keep a local projected document after drop/resize until the command is confirmed.
5. Remove editor-only padding/background from semantic nodes; selection chrome must not
   alter the prototype layout.
6. Keep `dnd-kit` for Stack/Grid/Form ordering and page sorting.
7. Preserve the command journal as the only persistent mutation authority.

### Implementation sequence

1. Completed: centralize client/canvas coordinates, deltas, Fit scale, and pointer-anchored
   zoom in one viewport transform module. Wheel input now normalizes pixel, line, and page
   delta modes, accumulates into one RAF, and anchors at the latest pointer. A generic
   DOMMatrix-backed `fitRect` remains unnecessary until the editor supports more than the
   current axis-aligned DOM canvas.
2. Completed: use a top-level, session-qualified
   `idle | pan | marquee | move | resize | mutation` interaction state. Marquee now performs
   thresholded overlap/containment selection, Shift toggling, nested-selection reduction, RAF
   projection, and explicit cancel/blur/Escape cleanup.
3. Completed: the node DOM-ref registry and canvas-level controls layer serve selection,
   Marquee, sortable hierarchy movement, Freeform movement, and Resize without putting editor
   chrome back inside semantic prototype nodes.
4. Completed: east, south, southeast, west, and north Resize projections are RAF-batched and
   retain the exact final-frame commit. Shift preserves aspect ratio. Positioned Freeform
   children also support Alt center resizing because origin and dimensions are committed in one
   atomic `setNodeLayout` command.
5. Completed: nested Stack/Grid/Form moves, Palette insertion, and page reorder all project
   live during `onDragOver`. PageRail stays authoritative while preview navigation projects;
   Palette ghosts are excluded from their host's measured layout and observer inputs.
6. Completed: Stack/Grid/Form direction, gap, padding, alignment, base columns, responsive
   layout overrides, and Grid column overrides are editable through typed atomic Inspector
   commands.

### Do not fake

- Free positioning remains legal only for direct children of an explicit `Freeform` container.
  Page roots and ordinary Stack/Grid/Form containers must not acquire cosmetic `x`/`y` state.
- Do not replace runnable business DOM with SVG/Canvas. Inputs, tables, forms, and the
  deterministic runtime remain DOM-based.
- Do not copy Penpot's Potok/Rx/WASM engine. DOM node refs and bounded React state are
  sufficient for the current prototype sizes.
- Do not copy Penpot's native HTML5 drag implementation. `frontend/src/app/main/ui/hooks.cljs:115`
  uses an invisible drag image and `frontend/src/app/util/dom/dnd.cljs:131` depends on
  `offsetY`; keep `dnd-kit`, pointer sensors, and the real-content drag overlay.
- Do not copy MPL-2.0 source. Reimplement the observed interaction contracts and pure
  algorithms independently, and retain this pinned-reference record as provenance.

## First Implementation Slice Acceptance

- A node can be dropped before, inside, or after a nested container without the parent
  or child stealing the target.
- The active target displays an insertion line or inside outline.
- The moved layout does not snap back while the server command is pending.
- Failed commands restore the authoritative document and preserve a visible error.
- Design mode does not activate prototype buttons, rows, or form controls.
- Editor selection chrome does not add padding, card backgrounds, or structural borders
  to the prototype content.
- Coordinate round trips stay within 0.5px and pointer-anchored zoom drifts by at most
  1px across the supported zoom range.
- Node Move and Resize pointer movement perform no backend mutation and cause at most one
  preview update per RAF. Pointer-up synchronously computes the exact tail, submits one typed
  command and one undo item; cancel submits none and cancels any pending frame.
- Wrapped Grid and Stack siblings have continuous measured insertion areas, and the
  projected layout updates during `onDragOver` without entering the dragged subtree.
- A referenced node deletion returns a typed non-retryable domain error rather than 500,
  and the selection is retained when deletion fails.

## Implementation Status (2026-07-16)

The nested-layout and interaction-transaction slices are now implemented in the production
Studio:

- Stack, Form, horizontal Stack, and wrapped Grid containers measure their rendered DOM
  children and expose continuous insertion areas derived from child midpoints and gaps.
- `onDragOver` recomputes the node location from the current projected document, coalesces
  updates through one animation frame, and performs no backend mutation.
- `dragEnd` preserves the final projection while one typed `moveNode` command is pending;
  cancel and failed commands restore the authoritative document.
- The earlier nested-drop browser acceptance moved `用户总数` into `进行中订单`: the local
  hierarchy changed while the draft stayed at `doc 63`, drop committed exactly `doc 64`,
  and Undo produced `doc 65` with the original hierarchy restored.
- `setNodeLayout` now preserves validated `LengthV1` objects, explicitly completes the
  recursive Pydantic node serializers, and survives persistence, restart recovery, Undo,
  and Redo without the former `MockValSer` HTTP 500.
- Selection outlines, the dnd-kit activator, the southeast Resize handle, and the live
  size label now render in a canvas-level sibling controls layer. Semantic node wrappers
  still own layout, focus, sortable transforms, and drop zones, but no longer render the
  selection chrome themselves.
- Node and activator registrations carry an instance token, so cleanup from a projected
  old parent cannot remove the replacement registration after cross-container movement.
- Resize keeps the exact pointer-up frame, requires four client pixels before activation,
  owns and releases the real handle's pointer capture, and treats pointer cancel, lost
  capture, blur, Escape, and unmount as explicit non-committing termination paths. Pointer
  moves only replace the latest client coordinates and schedule at most one RAF; pointer-up
  cancels that frame and computes the final size synchronously.
- Fit scale and the centered frame height are frozen for the complete Drag or Resize
  gesture. The final DOM is remeasured before the transform is released, preventing the
  canvas from shrinking or recentering under the pointer.
- `structuredPrototypeViewportTransform.ts` now owns client/canvas conversion, client
  delta conversion, Fit scale, and pointer-anchored zoom. Coordinate round trips and zoom
  anchoring have pure contract tests.
- Wheel zoom normalizes browser pixel, line, and page delta modes before accumulating the
  frame's input. One RAF applies the exponential scale and pointer-anchored pan together;
  page/viewport reset, Fit selection, blocked interaction, and unmount cancel pending input.
  Live browser evidence zoomed at an off-center pointer from `0.535417` to `0.622` with one
  transform, adjusted pan to `(-24.2066, -12.888)`, and measured only `0.00013px` anchor
  drift while document sequence stayed at `doc 97`.
- Studio now owns a monotonic session-token interaction state for Pan, Move, Resize, and
  document/runtime Mutation. Stale end events cannot clear a newer owner, and Move/Resize
  keep `committing` until their server result settles.
- Pan uses real pointer capture and terminates on pointer-up, pointer-cancel, lost capture,
  Escape, blur, page/viewport reset, and unmount without submitting a document command.
- Node move and page reorder retain their pending document projection during commit.
  Resize retains its projected size and now ends the matching session even when its
  callback rejects, while surfacing a visible failure.
- Page hover projection now derives from stable page identities without mutating PageRail.
  Live browser evidence moved `仪表盘` after `订单管理`: PageRail DOM stayed in the
  authoritative order while preview navigation projected the target order at `doc 85`, drop
  committed exactly `doc 86`, and Undo restored both views at `doc 87`.
- Palette hover now renders one deterministic real-content transient subtree and treats it as
  the active layout item even across a transient dnd-kit active-data gap. Its host exposes the
  active layout node, measured child count, and drop-area count as DOM observability evidence.
  Live browser evidence held one pointer over the populated `进行中订单` Stack for 11 sampled
  frames: sequence stayed at `doc 93`, the ghost bounds were identical, and the host remained
  at three measured children and four drop areas. Drop committed exactly `doc 94`; Undo restored
  `doc 95`; a separate Escape cancellation stayed at `doc 95` with no ghost or mutation.
- RAF Resize browser evidence sent 97 pointer path points to `进行中订单` and rendered 22
  non-empty draft sizes before the exact `376 x 310` tail. Sequence stayed at `doc 95` until
  pointer-up committed exactly `doc 96`; Inspector persisted width `376px` and height `310px`.
  Undo produced `doc 97` and restored the original `147.344 x 133.995` client bounds exactly.
  A separate Escape during a live preview stayed at `doc 97`, restored the same bounds, and
  recorded `resizeLastEnd=escape` without submitting a command.
- The selection controls layer now exposes separate east-width, south-height, and southeast
  size handles. East browser evidence persisted `350 x 250` at `doc 98`, proving height stayed
  fixed, then Undo restored the original bounds at `doc 99`. A Shift-modified south resize
  persisted `349 x 318` at `doc 102`; its aspect-ratio drift from the measured source was
  `0.0021`, within integer-pixel rounding. Undo restored the original bounds at `doc 103`.
- History, Inspector, Palette insertion, runtime events, checkpoint, publish, delete, and
  AI Apply use the same document mutation lock. PageRail and Palette keep active droppable
  targets available while ordinary controls remain locked.
- AI Apply now rejects a stale session/base hash instead of adopting fail-open. A confirmed
  backend draft is staged before runtime rebuild; runtime failure preserves that
  authoritative draft with the prior runtime and a visible error. AI thread refresh runs
  after the document lock is released.
- Base Stack, Grid, and Form layout properties are editable through typed Inspector
  commands, and responsive layout plus Grid column overrides are rendered from the
  document contract.
- Marquee selection now shares the interaction session owner, measures registered semantic
  nodes in canvas coordinates, selects leaf overlaps and fully contained containers, removes
  nested selection loops, and restores the initial selection on cancel.
- Responsive layout and Grid column override authoring are implemented in the Inspector with
  canonical ordering, duplicate/bounds refusal, and atomic command batches.
- An explicit `Freeform` container now owns bounded direct-child positions. Palette/drop moves
  assign deterministic coordinates, positioned children expose separate free-move and hierarchy
  drag handles, controls remeasure before paint, and Canvas/renderer clipping semantics match.
  Browser evidence created Freeform at `doc 108`, inserted a real Text node at `doc 109`, moved
  it from `(24,24)` to `(211,197)` at `doc 112`, atomically changed west origin/width at
  `doc 113`, restored both through Undo at `doc 114`, then removed all test nodes by `doc 117`.
- Same-Freeform multi-selection now has a shared bounds outline, group move, eight-direction Resize,
  six alignment actions, and horizontal/vertical distribution. Every operation persists one atomic
  position/frame batch and one Undo unit; desktop and mobile browser checks kept the toolbar inside
  the viewport.
- Freeform single and grouped selections support bounded keyboard nudging: Arrow moves one canvas
  pixel and Shift+Arrow moves ten. Browser evidence changed `(24,24)` to `(25,24)` and then
  `(25,34)` at `doc 147` and `doc 148`; four Undo operations restored both positions and removed
  the temporary Text and Freeform nodes by `doc 152`.
- Freeform single and grouped movement now snaps independently on both axes to container and
  unselected direct-sibling edges/centers with a stable six-client-pixel threshold. Pointerdown
  freezes sibling geometry and Canvas-local guide origin; RAF and pointerup share one solver,
  Ctrl/Meta bypasses snapping, and guides stay in the selection-controls layer. Browser evidence
  held `doc 156` through preview while two full-span guides measured about one physical pixel,
  committed exactly `doc 157`, restored through Undo at `doc 158`, committed an unsnapped Meta
  move at `doc 159`, restored at `doc 160`, and proved Escape cleared guides without changing
  `doc 160`. All temporary nodes were removed by `doc 162`; desktop/mobile reloads had no new
  console warnings or errors.
- Freeform single and grouped Resize now snaps the active edges of all eight handles to container
  and visible direct-sibling edges/centers with the same six-client-pixel threshold. Shift, Alt,
  Shift+Alt, and event-local Ctrl/Meta bypass share one RAF/pointerup projection; grouped children
  are proportionally reprojected only after shared bounds snap. Existing right/bottom overflow can
  recover but cannot worsen. West, north, and centered shrink constraints also keep every single or
  proportionally projected group field within the document's canonical `0..4096` range. Focused
  geometry normalizes only relative-`1e-9` arithmetic tails, preserves legal group union bounds
  wider than one persisted field, and keeps Move/Nudge measured geometry unchanged. Focused
  geometry and editor/UI contract suites plus deterministic single/group boundary sweeps cover the
  interaction; browser evidence remains separate from this automated completion record.
  Cleanup then removed only QA nodes `641c3ce3-5ee9-5338-9f82-65a0fe14fc0a` and
  `ccf93782-443c-58d9-8859-c9221a581546` in one atomic batch (`doc 164 -> 165`); a fresh current-
  draft recovery reported `85` entity IDs and neither QA ID, while preserving one-step Undo.
- All structured-prototype requests now have a total deadline. A strict, project-scoped operation
  outcome endpoint and schema-validated pending descriptor recover Studio, AI, and generation
  mutations. Unknown or non-terminal outcomes retain the descriptor and editor lock; terminal
  outcomes clear it only after the corresponding draft/runtime/publication/thread/job is read.
- Latest browser evidence is reversible and observable: Undo/Redo changed
  `doc 79 -> 80 -> 81` and restored identical canvas text; Resize changed
  `doc 81 -> 82`, and Undo produced `doc 83` with the selected bounds restored from
  `99.397 x 9.940` to exactly the same dimensions. Both traces returned to
  `idle`. After the later page, Palette, wheel, and directional Resize checks, a clean `doc 103`
  reload retained the original layout, no transient projection, and emitted no new browser
  error or warning.

The remaining Penpot gaps are deliberately separate product slices rather than hidden defects in
the completed interaction contract:

1. Move and Resize smart guides plus sibling/container edge/center snapping are complete. Freeform
   Move distance/equal-spacing snapping is also implemented for `before | between | after` on both
   axes. A single selection or same-parent group union remains one rigid frame; candidates use only
   frozen, visible, unselected direct siblings with two positive gaps, a common visual lane, no
   occupied corridor, and a legal Freeform envelope. Alignment and spacing compete from the same
   continuous raw frame by correction distance, with alignment winning an exact tie; the combined
   X/Y result revalidates the final lane. Mutually invalid X/Y spacing retries the smaller
   correction alone, fixes X as the exact-tie winner, then tries the alternate and alignment/raw.
   The inclusive threshold remains six client pixels at the pointerdown zoom; local `1e-9`
   arithmetic tails may admit a comparison but never rewrite the authoritative target, arithmetic
   zero gaps remain edge alignment, and fractional targets are preserved. Winning previews render two metadata-stable
   distance segments with six-client-pixel end caps, labels, and one-physical-pixel strokes.
   Ctrl/Meta bypass, RAF preview, exact pointer-up projection, one atomic move batch, and one-step
   Undo reuse the existing Move transaction. Exact blocker-query geometry is cached per projection,
   reducing the measured 400-sibling overlap cases from `81.6-157.6ms` to `8.6-17.3ms` without
   replacing stable reference IDs. Configurable grid snapping, grid preferences, and
   simultaneous grid/alignment/equal-spacing arbitration remain the next independent slice.
2. The page rail is not a full Penpot layer tree: visibility/lock/rename, explicit z-order actions,
   component detachment, and reusable component authoring remain future work.
3. Multiplayer presence, comments, vector/path tools, boolean geometry, and Penpot file-format
   compatibility remain outside this product's structured web-prototype scope.
