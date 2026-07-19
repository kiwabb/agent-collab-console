# Transform Model Audit

## Current Architecture

The editor has two valid but separate transform paths:

* Stack/Grid/Form children use dnd-kit ordering and persist parent/index changes.
* Direct Freeform children use absolute coordinates, eight-direction resize, group transforms,
  snapping, and exact pointer-tail commits.

Node type is not the blocker. Every node already shares `layoutItem`; parent-container rules decide
whether `layoutItem.position` is legal.

## Evidence

* Frontend layout model has size plus optional position, but no rotation or placement discriminator:
  `frontend/src/features/prototype/structured/types.ts:55`.
* Existing `moveNode.targetPosition` and `setNodeLayout` commands can already persist position and
  size atomically: `types.ts:408`.
* Frontend command builders currently require position for Freeform and reject it elsewhere:
  `structuredPrototypeCommands.ts:184` and `:214`.
* Backend tree validation requires Freeform children to have position and all other children not to:
  `backend/app/application/structured_prototype_contracts.py:1170`.
* The strict frontend codec enforces the same equality:
  `frontend/src/features/prototype/structured/rendererDocumentCodec.ts:438`.
* Stack/Grid/Form render through flex/grid while Freeform supplies the positioned containing block:
  `StructuredPrototypeCanvas.tsx:905` and `prototypeRendererCore.ts:198`.
* Selection and group geometry are axis-aligned; rotation cannot be added by treating
  `getBoundingClientRect()` as oriented geometry: `structuredPrototypeGroupTransform.ts:18`.
* The interaction state has no rotate kind: `structuredPrototypeInteraction.ts:9`.

## Recommended Model

Persist typed geometry scalars, never CSS transform strings:

```ts
type Placement =
  | { kind: "flow" }
  | { kind: "absolute"; x: CanonicalCoordinate; y: CanonicalCoordinate };

interface TransformFrame {
  placement: Placement;
  width: StructuredPrototypeLength;
  height: StructuredPrototypeLength;
  rotation: CanonicalAngle;
}
```

Keep layout/position on an outer NodeFrame, persistent rotation on an inner NodeVisual, and dnd
preview transforms in the transient interaction layer. Rotation later requires true corner/matrix
geometry and local-coordinate resize rather than AABB math.

## First Vertical Slice

Allow absolute-positioned children in Stack/Grid/Form without adding a new wire field:

1. Root nodes still reject position.
2. Freeform children still require position.
3. Stack/Grid/Form children may be flow (`position` absent) or absolute (`position` present).
4. Those containers become positioned containing blocks; absolute children leave flex/grid flow.
5. Explicit conversion captures x/y plus px width/height in one command batch.
6. Positioned selection/move/resize helpers generalize from Freeform to any same-parent positioned
   selection; Freeform alone adds its layout-grid snapping inputs.
7. Drop-area measurement ignores absolute children while document order remains their stacking
   order.

This preserves every historical V1 command meaning and canonical JSON while unlocking the existing
move/resize machinery for ordinary layout containers.

## Later Rotation Boundary

Rotation should follow version-dispatched frozen parsers/executors rather than mutating V1 replay
semantics. It needs a canonical angle, oriented selection geometry, rotate evidence, snapping, an
inner visual transform, signed renderer support, and worker manifest rebuild.
