# Selection and Layer Stack Audit

## Existing Strengths

* Formal selection contains ordered `nodeIds` plus `primaryNodeId`:
  `frontend/src/features/prototype/structured/structuredPrototypeSelection.ts:25`.
* Shift click, Marquee overlap/containment, root exclusion, and nested-loop reduction exist:
  `StructuredPrototypeCanvas.tsx:686`, `:2595`, and `structuredPrototypeSelection.ts:80`.
* Same-parent direct Freeform children support grouped move, eight-direction resize, align,
  distribute, and arrow nudge: `structuredPrototypeGroupSelection.ts:16`.
* Alignment, equal-spacing, layout-grid, container and sibling snapping already share bounded pure
  solvers: `structuredPrototypeSnapping.ts:12` and `structuredPrototypeResizeSnapping.ts:19`.
* Layers support rename, visibility, ARIA tree navigation, and before/inside/after movement:
  `StructuredPrototypeLayerTree.tsx:170` and `structuredPrototypeLayerTreeModel.ts:165`.

## Missing Contracts

* LayerTree receives one `selectedNodeId`, so tree multi-selection, range selection, and batch drag
  do not exist: `StructuredPrototypeLayerTree.tsx:57`.
* Canvas nodes stop click propagation and immediately select the top hit. There is no
  `elementsFromPoint` hit stack or overlap cycle: `StructuredPrototypeCanvas.tsx:686` and `:1411`.
* Group is transient Freeform multi-selection, not a persistent node type; there are no Group or
  Ungroup commands: `types.ts:191`.
* Nodes have visibility but no persisted locked state: `types.ts:93` and
  `backend/app/application/structured_prototype_contracts.py:378`.
* Freeform child array order implies stacking, and layer drag can reorder it, but no forward/back/
  front/back commands or multi-selection stable reorder exist.
* Rotation, rulers, persistent manual guides, layer search, and corresponding shortcuts are absent.
* Shortcut matching does not centrally distinguish unspecified modifier keys, so new modified
  shortcuts need a stricter contract first: `frontend/src/hooks/useKeyboardShortcuts.ts:19`.

## Recommended Order

1. Centralized hit stack and overlap cycling.
2. Full selection model in LayerTree with range/toggle semantics.
3. Persisted lock plus hit-test, Marquee, transform, delete, layer-drag, and AI mutation gates.
4. Stable Freeform multi-selection forward/back/front/back operations.
5. Explicit modifier-key matching and keyboard entry points.
6. Persistent Group/Ungroup with world-coordinate preservation.
7. Affine rotation and oriented selection bounds.
8. Rulers and persistent guides.

This order establishes which nodes are targetable and operable before adding rotation matrices.
