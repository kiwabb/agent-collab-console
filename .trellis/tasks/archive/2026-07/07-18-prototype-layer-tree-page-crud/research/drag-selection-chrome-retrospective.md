# Bug Analysis: Drag Mirror Competes With Oversized Selection Chrome

## 1. Root Cause Category

- **Category**: D/E - Test Coverage Gap and Implicit Assumption
- **Specific Cause**: The drag-mirror work treated the cloned business-node DOM as the complete
  dragged presentation. Selection outlines, move activators, and resize handles live in a sibling
  editor-controls layer, so clone sanitization cannot remove or restyle them. Their inverse zoom
  scaling also kept `size-8` white controls at 32 CSS pixels in Fit mode.

## 2. Why Earlier Fixes Failed

1. Replacing the generic DragOverlay card fixed the mirror content but did not inspect the live
   selection-controls layer.
2. Sanitizing cloned node identity and drop targets could not affect sibling editor chrome outside
   the clone boundary.
3. Source tests verified the mirror and source opacity independently, but did not assert the
   simultaneous visual state of mirror, source, and editor controls during an active drag.

## 3. Prevention Mechanisms

| Priority | Mechanism | Specific Action | Status |
| --- | --- | --- | --- |
| P0 | Runtime presentation state | Hide selected-node chrome during canvas-node DnD while keeping the activator DOM mounted | DONE |
| P0 | Visual contract | Remove the visible Grip, use four invisible 10px selection-edge move bands, and render only 8px resize markers | DONE |
| P0 | Regression tests | Test node/selection matching and prove palette, page, and unrelated node drags do not hide chrome | DONE |
| P1 | Browser acceptance | Measure hit-area and marker pixels, inspect active-drag state, cancel, and verify restoration | DONE |
| P1 | Specification | Document business-node mirror and editor-controls layer as separate visual systems | DONE |
| P1 | Gesture priority | Disable selection move and resize while Space owns viewport panning | DONE |

## 4. Systematic Expansion

- **Similar Issues**: Freeform group controls, snap guides, marquee chrome, layer-tree DnD, and page
  sorting all render outside the business-node clone boundary and need independent acceptance.
- **Design Improvement**: Treat drag presentation as three explicit layers: retained live layout,
  captured business mirror, and transient editor/drop chrome.
- **Process Improvement**: Browser acceptance for editor dragging must inspect both idle selection
  and active drag at Fit and numeric zoom, then cancel and verify restoration.

## 5. Knowledge Capture

- [x] Updated the faithful drag-mirror scenario in the frontend state-management spec.
- [x] Added focused unit/source contracts and browser acceptance evidence.
- [x] Corrected the spec ordering so the drag-mirror Wrong/Correct example is contiguous.
- [x] Confirmed this repository has no `src/templates/markdown/spec/` mirror to synchronize.
