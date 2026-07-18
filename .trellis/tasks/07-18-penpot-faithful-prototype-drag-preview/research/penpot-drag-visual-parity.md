# Penpot drag visual parity research

## Question

What does Penpot preserve visually during canvas movement, and which part should this structured
prototype editor borrow?

## Sources

* Penpot source, `frontend/src/app/main/ui/workspace/shapes/frame/dynamic_modifiers.cljs`, commit
  `0c84db93508293a71d8ac8f05449886164344bd7`.
* Penpot issue `#3687`, "feature: move the elements faster", including the maintainer explanation
  that movement already uses `fdm/use-dynamic-modifiers` and modifies the DOM directly.
* Penpot issues `#4440` and `#4395` for pointer-down movement and cross-layout/component drag
  failure modes.

## Observed Penpot pattern

1. Movement is applied to the rendered shape DOM/SVG nodes through transformation matrices.
2. `start-transform!` records the existing transform and geometry attributes before preview.
3. `update-transform!` updates the real shape, frame children, mask/filter regions, gradients,
   patterns, and frame title consistently during the gesture.
4. When a shape is temporarily represented inside another frame, Penpot creates an SVG `<use>`
   mirror referencing the original shape and hides the original node. The mirror is still the same
   shape rendering, not a semantic replacement card.
5. `remove-transform!` restores or removes transient transform attributes after the gesture.

## Why the current editor diverges

The current editor's overlay is deliberately a different UI component:

* `StructuredPrototypeNodeDragOverlay` adds editor card chrome and a type/name label.
* `OverlayNodeContent` reconstructs a shortened approximation instead of preserving the rendered
  subtree.
* Containers show at most six children and tables at most three rows.
* Fixed `min-width`, `max-width`, padding, and independent theme context change geometry and color.

This is not a styling mismatch. It is the wrong representation model.

## Mapping to this repository

The editor uses React HTML plus dnd-kit rather than an SVG scene graph, and hover projection can
reparent the source DOM. Directly transforming only the live source is therefore fragile. The
closest equivalent to Penpot's temporary `<use>` mirror is:

1. Capture the actual registered node element synchronously at drag start.
2. Clone the DOM subtree before `isDragging` styles and projection apply.
3. Preserve its client-pixel bounds and copy inherited `--prototype-*` variables required outside
   the preview frame.
4. Remove drag/drop zones, duplicated IDs, focusability, and transient transforms from the clone.
5. Mount the inert clone as the dnd-kit overlay and dispose it on cancel/drop.

This keeps the existing deterministic projection and persistence machinery while making the
transient visual model faithful to the source.

## Alternatives considered

### A. DOM mirror captured at drag start (recommended)

* Exact rendered content and runtime state.
* Stable when hover projection reparents the source.
* Requires explicit sanitization and scale/theme capture.

### B. Move the live sortable node with no overlay

* Closest to Penpot's direct transform.
* Fails when the projected document reparents or remounts the node during drag.

### C. Rebuild an exact React overlay renderer

* Fully declarative.
* Duplicates the recursive business renderer and will drift again as node types evolve.

## Conclusion

Use a sanitized DOM mirror for existing canvas-node dragging. It preserves Penpot's key invariant -
the object seen under the pointer is the object being moved - without replacing the repository's
existing drag projection, collision, command, or recovery contracts.
