# Penpot-faithful prototype drag preview

## Goal

Make structured-prototype dragging preserve the visual identity of the object being moved. An
existing canvas node must follow the pointer as a faithful mirror of its current rendered content,
geometry, theme, and scale instead of becoming a generic component-type card.

## What I already know

* The reported failure is visible while dragging an existing `Button` node on the Design canvas.
* `StructuredPrototypeNodeDragOverlay` currently adds a `node.type / node.name` heading, card
  chrome, fixed min/max sizing, padding, ring, and shadow.
* Its nested `OverlayNodeContent` is a simplified re-render. Containers are capped at six children,
  tables at three rows, and leaf styles differ from the business renderer, so exact visual parity is
  impossible by construction.
* `SortableCanvasNode` fades the real source to 20% while `DragOverlay` displays that simplified
  card, producing the large detached panel shown in the screenshot.
* The current hover projection can reparent/reorder nodes during a drag. A stable visual mirror is
  still needed even if the source DOM moves or remounts underneath it.
* Penpot's published `use-dynamic-modifiers` implementation applies transforms directly to the
  rendered shape nodes. For frame reparenting it creates a temporary SVG mirror while hiding the
  original, rather than replacing the shape with a semantic label card.

## Assumptions (temporary)

* "Like Penpot" means preserving the exact rendered object, not copying Penpot's ClojureScript/SVG
  architecture or every transform feature.
* The durable command, hover projection, collision, undo, and recovery contracts must remain
  unchanged; this task changes transient drag presentation only.

## Open Questions

* None.

## Confirmed Scope Decision

* Existing canvas nodes use a faithful mirror of the currently rendered node.
* Palette insertion uses a faithful preview of the materialized node that will be inserted.
* Page-rail sorting remains a compact page preview because it represents navigation ordering, not
  movement of a business node on the canvas.

## Requirements (evolving)

* Existing node drag preview mirrors the exact current DOM subtree before drag styling is applied.
* Palette drag preview renders the exact materialized insertion node with document theme variables
  and target viewport scale instead of a label-only component card.
* The mirror preserves the source node's on-screen width, height, preview scale, prototype theme
  variables, text, table rows, nested children, and current runtime/form values.
* Freeform offsets, percentage sizes, and flex/grid item sizing are removed from the cloned root;
  its captured unscaled border-box dimensions are frozen before it enters the overlay host.
* The mirror contains no component type/name header, generic card chrome, artificial min/max width,
  or independent content reconstruction.
* Drag-only drop targets, selection handles, focusability, IDs, and event behavior must not leak
  into the mirror.
* If the registered source cannot produce a valid mirror, the existing-node gesture is refused
  before an interaction session starts and a visible error is shown; no reconstructed fallback is
  allowed.
* The source location remains legible as a placeholder without competing visually with the mirror.
* Hover projection, nested drop targeting, cancellation, commit, undo, and recovery behavior remain
  deterministic and unchanged.
* Page-rail sorting keeps a compact page title/route preview and is not represented as a canvas
  business object.

## Acceptance Criteria (evolving)

* [x] Dragging a Button shows the same button label, color, size, and surrounding node frame as the
      selected canvas node, with no `BUTTON - name` card.
* [x] Dragging Text, Input, Table, Stack/Grid/Form, and nested containers preserves their full
      visible content instead of a capped approximation.
* [x] Dragging a palette Button, Text, Input, Table, Stack/Grid/Form, or Freeform shows the same
      materialized node that appears after a valid drop, not a type-label card.
* [x] The drag mirror has the same client-pixel bounds at `fit`, `75%`, `100%`, and `200%` zoom.
* [x] Prototype CSS variables and document theme colors remain identical after the mirror leaves the
      scaled preview subtree.
* [x] Reparenting across valid sibling/container targets does not make the mirror jump, resize,
      disappear, or reveal active drop-zone DOM.
* [x] Escape/cancel and successful drop remove the mirror without leaving cloned IDs or focusable
      controls in the document.
* [x] Existing move projection, command, Undo, and recovery tests remain green.
* [x] A browser acceptance test and screenshot verify visual parity against the source node.

## Definition of Done (team quality bar)

* Tests added or updated for snapshot capture, sanitization, scale, lifecycle, and source contracts.
* Focused frontend tests, TypeScript, and ESLint pass.
* Browser QA covers desktop canvas drag at multiple zoom levels and nested reparenting.
* The implementation does not add a second document mutation path.

## Out of Scope (explicit)

* Reimplementing Penpot's SVG renderer or dynamic-modifier architecture.
* Changing persisted prototype schema, backend APIs, runtime semantics, or command journal format.
* Multi-selection drag unless it is already supported by the existing sortable interaction.
* Replacing the compact page-rail ordering preview with a full canvas/page thumbnail.

## Expansion Sweep

* Future evolution: preserve a snapshot abstraction that can later represent multi-selection, but
  do not add multi-selection drag in this task.
* Related scenarios: include palette-to-canvas insertion parity; keep page-rail sorting semantically
  separate.
* Failure and edge cases: include zoom changes, nested reparenting, source remount, invalid drop,
  Escape, pointer cancellation, successful commit, and component unmount cleanup.

## Technical Notes

* Primary files inspected:
  * `frontend/src/features/prototype/structured/StructuredPrototypeStudioPage.tsx`
  * `frontend/src/features/prototype/structured/StructuredPrototypeCanvas.tsx`
  * `frontend/src/features/prototype/structured/structuredPrototypeDrag.ts`
  * `frontend/tests/structuredPrototypeEditorContracts.test.ts`
* Current overlay is rendered from `StructuredPrototypeStudioPage.tsx` through dnd-kit's
  `DragOverlay`; the generic node card lives in `StructuredPrototypeCanvas.tsx`.
* A faithful implementation should capture the source node at drag start, before `isDragging`
  opacity and hover projection alter it, and mount a sanitized inert mirror for the overlay.

## Verification Evidence

* Focused drag/editor/projection suite after root isolation and live-state capture:
  `node --import tsx --test tests/structuredPrototypeDragMirror.test.ts tests/structuredPrototypeEditorContracts.test.ts tests/structuredPrototypePreviewScale.test.ts tests/structuredPrototypeCommands.test.ts tests/structuredPrototypeSelection.test.ts`
  -> `49 passed`.
* Undo/recovery suite:
  `node --import tsx --test tests/structuredPrototypeOperationRecovery.test.ts tests/structuredPrototypeStudioRetry.test.ts`
  -> `28 passed`.
* i18n parity suite: `node --import tsx --test tests/theme-i18n.test.ts` -> `5 passed`.
* `npm run typecheck` -> passed.
* Targeted ESLint for all changed runtime/test files -> passed.
* Targeted Prettier check for all changed runtime/test files -> passed.
* Browser source/mirror bounds:
  * Fit: `545.2657 x 19.0986` source, `545.2656 x 19.0938` mirror (subpixel paint rounding).
  * 75%: `856.5 x 30` source and mirror.
  * 100%: `1142 x 40` captured source and mirror; hover projection narrowed the live source to
    `235 x 40` without resizing the mirror.
  * 200%: `2284 x 80` source and mirror.
* Browser Table drag retained `4 / 4` body rows, full row text, and matching
  `653.7 x 91.8` client bounds while the hover projection moved underneath it.
* Browser palette Button drag rendered the materialized blue primary button at the Fit scale, with
  no type/name card.
* Sanitization observation during drag: zero cloned IDs, zero cloned node IDs, zero drop-intent
  elements, `tabIndex=-1`, inert clone, matching `--prototype-accent: #3157d5`.
* Escape observation: overlay and mirror counts returned to zero and source opacity returned to one.
* Root-isolation browser evidence on the existing Freeform Text at Fit:
  * Before drag: `position:absolute; left:24px; top:24px`, unscaled `27 x 19`, client
    `8.869995 x 6.210327`.
  * During hover reparenting the live source expanded to `78.589172 x 6.210327`, while the clone
    remained `8.869995 x 6.210327` with `position:relative`, zero effective inset,
    `flex:0 0 auto`, `align-self:auto`, and zero cloned IDs/node IDs.
* Live Input browser evidence: after entering `mirror-live-value` in Preview and returning to Edit,
  the source and clone values matched, their client bounds both remained
  `65.103455 x 20.305634`, and the cloned input had `tabIndex=-1` inside an inert clone.
* Percentage-width browser evidence: an Input saved temporarily at `width:50%` measured `571px`
  unscaled and `191.126343px` on screen. Its mounted clone used pixel `width:571px` and matched the
  same client width instead of resolving to 50% of the overlay host. The test command was undone;
  the accepted node returned to `width:auto`.
* Palette Input browser evidence: the overlay contained the real input renderer, was `aria-hidden`
  and inert, and its still-native `tabIndex=0` input remained outside the sequential focus order by
  inheriting the inert ancestor.
* Screenshots:
  `output/playwright/drag-mirror/.playwright-cli/page-2026-07-18T10-11-30-277Z.png`
  (existing Button mirror) and
  `output/playwright/drag-mirror/.playwright-cli/page-2026-07-18T10-30-28-148Z.png`
  (palette Button materialization).

## Research References

* [`research/penpot-drag-visual-parity.md`](research/penpot-drag-visual-parity.md) - Penpot directly
  transforms rendered nodes and uses temporary mirrors only to preserve visual continuity.
