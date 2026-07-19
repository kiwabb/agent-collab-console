import assert from "node:assert/strict";
import test from "node:test";

import { readCompactSource } from "./sourceTestUtils";

test("Freeform positioned nodes expose independent move and hierarchy drag paths", () => {
  const canvas = readCompactSource("features/prototype/structured/StructuredPrototypeCanvas.tsx");
  const sortableNodeStart = canvas.indexOf("function SortableCanvasNode");
  const controlsLayerStart = canvas.indexOf("function StructuredPrototypeSelectionControlsLayer");
  const canvasRootStart = canvas.indexOf("export function StructuredPrototypeCanvas");
  assert.ok(sortableNodeStart >= 0 && controlsLayerStart > sortableNodeStart);
  assert.ok(canvasRootStart > controlsLayerStart);
  const sortableNode = canvas.slice(sortableNodeStart, controlsLayerStart);
  const controlsLayer = canvas.slice(controlsLayerStart, canvasRootStart);

  assert.match(sortableNode, /disabled: props\.dragDisabled \|\| !props\.editing/);
  assert.doesNotMatch(sortableNode, /disabled:.*layoutItem\.position/);
  assert.match(controlsLayer, /data-prototype-selection-move-surface="freeform"/);
  assert.match(controlsLayer, /data-prototype-freeform-layer-handle="true"/);
  assert.match(controlsLayer, /prototype\.structured\.canvas\.reparent/);
  assert.match(controlsLayer, /ref=\{sortableControls\.setActivatorNodeRef\}/);
  assert.doesNotMatch(canvas, /GripVertical/);
});

test("Freeform selection controls skip hidden draft measurement and remeasure on restore", () => {
  const canvas = readCompactSource("features/prototype/structured/StructuredPrototypeCanvas.tsx");
  const controlsLayerStart = canvas.indexOf("function StructuredPrototypeSelectionControlsLayer");
  const canvasRootStart = canvas.indexOf("export function StructuredPrototypeCanvas");
  assert.ok(controlsLayerStart >= 0 && canvasRootStart > controlsLayerStart);
  const controlsLayer = canvas.slice(controlsLayerStart, canvasRootStart);

  assert.match(
    controlsLayer,
    /useLayoutEffect\(\(\) => \{if \(!selectionChromeHidden\) measure\(\);\}, \[freeformMoveDraft, measure, resizeDraft, selectionChromeHidden\]\)/,
  );
  assert.match(controlsLayer, /const selectionChromeHidden = selectionChromeState !== "visible"/);
});

test("Freeform controls move from the group selection edges and expose all resize directions", () => {
  const canvas = readCompactSource("features/prototype/structured/StructuredPrototypeCanvas.tsx");
  assert.match(canvas, /data-prototype-selection-move-surface="group-freeform"/);
  assert.match(canvas, /SELECTION_MOVE_EDGE_HIT_SIZE = 10/);
  assert.match(canvas, /GROUP_RESIZE_HANDLES/);
  assert.match(canvas, /data-prototype-resize-direction=\{handle\.direction\}/);
  for (const direction of [
    "north",
    "northeast",
    "east",
    "southeast",
    "south",
    "southwest",
    "west",
    "northwest",
  ]) {
    assert.match(canvas, new RegExp(`direction: "${direction}"`));
  }
});

test("positioned selection controls expose bounded arrow-key nudging", () => {
  const canvas = readCompactSource("features/prototype/structured/StructuredPrototypeCanvas.tsx");
  const studio = readCompactSource(
    "features/prototype/structured/StructuredPrototypeStudioPage.tsx",
  );

  assert.match(canvas, /data-prototype-keyboard-nudge="arrow-shift-10"/);
  assert.match(canvas, /event\.shiftKey \? 10 : 1/);
  for (const key of ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"]) {
    assert.match(canvas, new RegExp(`case "${key}"`));
  }
  assert.match(canvas, /resolveStructuredPrototypeSelectionNudge/);
  assert.match(studio, /summary: `Nudge \$\{items\.length\} positioned component/);
  assert.match(
    studio,
    /setPositionedGroupLayoutBatch\(changedItems, "position", options\.summary\)/,
  );
});

test("Freeform transform lifecycle clears stale errors and preserves failed commits", () => {
  const studio = readCompactSource(
    "features/prototype/structured/StructuredPrototypeStudioPage.tsx",
  );
  const moveHook = readCompactSource(
    "features/prototype/structured/useStructuredPrototypeFreeformMove.ts",
  );
  const canvas = readCompactSource("features/prototype/structured/StructuredPrototypeCanvas.tsx");

  assert.equal(
    [...studio.matchAll(/if \(sessionId !== null\) setInteractionError\(null\)/g)].length,
    2,
  );
  assert.match(
    studio,
    /applied \? null : t\("prototype\.structured\.canvas\.freeformMoveFailed"\)/,
  );
  assert.match(studio, /applied \? null : t\("prototype\.structured\.canvas\.resizeFailed"\)/);
  assert.match(moveHook, /structuredPrototypeCanStartTransform\(event\.button, event\.isPrimary\)/);
  assert.match(canvas, /structuredPrototypeCanStartTransform\(event\.button, event\.isPrimary\)/);
});

test("Freeform move snapping freezes one gesture frame and projects preview and commit identically", () => {
  const moveHook = readCompactSource(
    "features/prototype/structured/useStructuredPrototypeFreeformMove.ts",
  );
  const canvas = readCompactSource("features/prototype/structured/StructuredPrototypeCanvas.tsx");
  const pointerDownStart = moveHook.indexOf("const onPointerDown");
  const cancelOldGesture = moveHook.indexOf('endGesture("pointercancel")', pointerDownStart);
  const resolveStartFrame = moveHook.indexOf("resolveStartFrame(nodeId)", pointerDownStart);
  assert.ok(pointerDownStart >= 0);
  assert.ok(cancelOldGesture > pointerDownStart && cancelOldGesture < resolveStartFrame);

  assert.match(moveHook, /selectedNodeIds: \[\.\.\.canonicalStartInput\.selectedNodeIds\]/);
  assert.match(moveHook, /directSiblings: canonicalStartInput\.directSiblings\.map/);
  assert.match(
    moveHook,
    /grids: cloneStructuredPrototypeFreeformGrids\(canonicalStartInput\.grids\)/,
  );
  assert.match(moveHook, /gridSnappingEnabled: canonicalStartInput\.gridSnappingEnabled/);
  assert.match(moveHook, /gridIds: canonicalStartInput\.grids\.map\(\(grid\) => grid\.id\)/);
  assert.match(moveHook, /guideOverlayFrame:\s*\{\s*\.\.\.startFrame\.guideOverlayFrame\s*\}/);
  assert.match(moveHook, /previewScale: canonicalStartInput\.previewScale/);

  const projectionStart = moveHook.indexOf("function resolveProjection");
  const scheduleStart = moveHook.indexOf("function schedule", projectionStart);
  const cleanupStart = moveHook.indexOf("function cleanup", scheduleStart);
  const pointerUpStart = moveHook.indexOf("function handlePointerUp", cleanupStart);
  const pointerCancelStart = moveHook.indexOf("function handlePointerCancel", pointerUpStart);
  assert.ok(
    projectionStart >= 0 &&
      scheduleStart > projectionStart &&
      cleanupStart > scheduleStart &&
      pointerUpStart > cleanupStart &&
      pointerCancelStart > pointerUpStart,
  );
  assert.match(
    moveHook.slice(scheduleStart, cleanupStart),
    /resolveProjection\(\s*current,\s*current\.latestClientX,\s*current\.latestClientY,\s*current\.latestBypassSnapping,?\s*\)/,
  );
  assert.match(
    moveHook.slice(pointerUpStart, pointerCancelStart),
    /resolveProjection\(\s*active,\s*pointerEvent\.clientX,\s*pointerEvent\.clientY,\s*bypassSnapping,?\s*\)/,
  );
  assert.match(moveHook, /pointerEvent\.ctrlKey \|\| pointerEvent\.metaKey/);
  assert.match(moveHook, /canonicalizeStructuredPrototypeFreeformMoveReplayInput\(/);
  assert.match(moveHook, /return replayStructuredPrototypeFreeformMove\(/);
  assert.doesNotMatch(moveHook, /resolveStructuredPrototypeFreeformMoveSnap\(/);
  assert.match(moveHook, /grids: gesture\.grids/);
  assert.match(moveHook, /gridSnappingEnabled: gesture\.gridSnappingEnabled/);
  assert.match(moveHook, /spacingGuides: projection\.spacingGuides/);
  assert.equal([...moveHook.matchAll(/moveNodeRef\.current\(/g)].length, 1);
  assert.match(moveHook, /freeformId: gesture\.freeformId/);
  assert.match(moveHook, /\.\.\.finalProjection\.canonicalInput/);
  assert.match(
    moveHook,
    /selectedNodeIds: \[\.\.\.finalProjection\.canonicalInput\.selectedNodeIds\]/,
  );
  assert.doesNotMatch(moveHook, /diagnostics: finalProjection|finalPosition: finalProjection/);
  assert.match(moveHook, /bypassSnapping,/);
  assert.match(
    moveHook,
    /return \{draft, guideOverlay, phase, lastEnd, onPointerDown, acknowledge\}/,
  );
  assert.match(canvas, /const deltaX = rawFreeformMoveDraft\.x - groupX/);
  assert.match(canvas, /const deltaY = rawFreeformMoveDraft\.y - groupY/);
  assert.match(
    canvas,
    /groupItems: positionedGroupSelection\.items\.map\(\(item\) => \(\{nodeId: item\.node\.id, x: item\.x \+ deltaX, y: item\.y \+ deltaY,?\}\)\)/,
  );
});

test("Freeform move guides exist only for active previews and clear on every terminal path", () => {
  const moveHook = readCompactSource(
    "features/prototype/structured/useStructuredPrototypeFreeformMove.ts",
  );
  assert.match(
    moveHook,
    /projection\.guides\.length === 0 && projection\.spacingGuides\.length === 0 \? null/,
  );
  assert.match(moveHook, /spacingGuides: projection\.spacingGuides/);
  assert.match(moveHook, /const clearGuideOverlay = useCallback/);
  assert.match(moveHook, /clearGuideOverlay\(\);\s*return gesture/);
  assert.match(
    moveHook,
    /const acknowledge = useCallback\(\(\): void => \{setDraft\(null\);\s*clearGuideOverlay\(\)/,
  );
  assert.match(
    moveHook,
    /const gesture = detachPointer\(\);\s*if \(gesture === null\) return;\s*clearGuideOverlay\(\)/,
  );
  assert.match(moveHook, /endGesture\("unmount"\);\s*endCommit\("unmount"\)/);
});

test("positioned move snapping freezes direct siblings and limits layout grids to Freeform", () => {
  const canvas = readCompactSource("features/prototype/structured/StructuredPrototypeCanvas.tsx");
  const controlsLayerStart = canvas.indexOf("function StructuredPrototypeSelectionControlsLayer");
  const canvasRootStart = canvas.indexOf("export function StructuredPrototypeCanvas");
  assert.ok(controlsLayerStart >= 0 && canvasRootStart > controlsLayerStart);
  const controlsLayer = canvas.slice(controlsLayerStart, canvasRootStart);
  const canvasRoot = canvas.slice(canvasRootStart);

  assert.match(canvasRoot, /const resolvePositionedSnapContext = useCallback/);
  assert.match(canvasRoot, /const directSiblings = parent\.children\.flatMap/);
  assert.match(canvasRoot, /selectedNodeIdSet\.has\(child\.id\)/);
  assert.match(canvasRoot, /child\.visibility === "hidden"/);
  assert.match(canvasRoot, /!runtimeNodeVisible\(props\.viewModel, child\.id\)/);
  assert.match(canvasRoot, /!registration\.element\.isConnected/);
  assert.match(canvasRoot, /registration\.element\.parentElement !== container/);
  assert.match(
    canvasRoot,
    /registration\.ancestorNodeIds\[registration\.ancestorNodeIds\.length - 1\] !== parent\.id/,
  );
  assert.match(
    canvasRoot,
    /resolveStructuredPrototypePositionedSelection\(page\.root, \[nodeId\]\)/,
  );
  assert.match(
    canvasRoot,
    /grids: parent\.type === "Freeform" \? resolveStructuredPrototypeFreeformGrids\(parent\) : \[\]/,
  );
  assert.match(
    canvasRoot,
    /gridSnappingEnabled: parent\.type === "Freeform" && props\.gridSnappingEnabled/,
  );
  assert.match(canvasRoot, /guideOverlayFrame: \{/);

  assert.match(controlsLayer, /projectStructuredPrototypeFreeformSnapGuides/);
  assert.match(controlsLayer, /projectStructuredPrototypeFreeformSpacingGuides/);
  assert.match(controlsLayer, /freeformMovePhase === "preview"/);
  assert.match(controlsLayer, /data-prototype-snap-guide="true"/);
  assert.match(controlsLayer, /data-prototype-spacing-guide="true"/);
  assert.match(controlsLayer, /data-prototype-snap-guide-kind="spacing"/);
  assert.match(controlsLayer, /data-prototype-spacing-axis=\{guide\.axis\}/);
  assert.match(controlsLayer, /data-prototype-spacing-placement=\{guide\.placement\}/);
  assert.match(controlsLayer, /data-prototype-spacing-gap=\{guide\.gap\}/);
  assert.match(controlsLayer, /data-prototype-spacing-segment-index=\{guide\.segmentIndex\}/);
  assert.match(
    controlsLayer,
    /guide\.axis.*guide\.placement.*guide\.referenceNodeIds\.join.*guide\.segmentIndex/,
  );
  assert.match(controlsLayer, /data-prototype-spacing-line="true"/);
  assert.match(controlsLayer, /data-prototype-spacing-label="true"/);
  assert.match(controlsLayer, /canonicalStructuredPrototypeFreeformValue\(guide\.gap\)\} px/);
  assert.match(
    controlsLayer,
    /canonicalStructuredPrototypeFreeformValue\(freeformMoveDraft\.x\).*canonicalStructuredPrototypeFreeformValue\(freeformMoveDraft\.y\)/,
  );
  assert.match(
    controlsLayer,
    /canonicalStructuredPrototypeFreeformValue\(selectedMoveDraft\.x\).*canonicalStructuredPrototypeFreeformValue\(selectedMoveDraft\.y\)/,
  );
  assert.doesNotMatch(controlsLayer, /guide\.gap\.toFixed|selectedMoveDraft\.[xy]\}/);
  assert.match(controlsLayer, /guide\.referenceNodeIds\.join/);
  assert.match(controlsLayer, /data-prototype-snap-axis=\{guide\.axis\}/);
  assert.match(controlsLayer, /data-prototype-snap-target-node-id=/);
  assert.match(controlsLayer, /data-prototype-snap-grid-id=\{guide\.gridId\}/);
  assert.match(controlsLayer, /data-prototype-snap-grid-type=\{guide\.gridType\}/);
  assert.match(controlsLayer, /data-prototype-snap-grid-line-index=\{guide\.gridLineIndex\}/);
  assert.match(controlsLayer, /pointer-events-none absolute inset-0 z-40/);
});

test("Freeform grid overlay is editing-only, pointer-transparent, and fed by the Studio gate", () => {
  const overlay = readCompactSource(
    "features/prototype/structured/StructuredPrototypeFreeformGridOverlay.tsx",
  );
  const canvas = readCompactSource("features/prototype/structured/StructuredPrototypeCanvas.tsx");
  const preview = readCompactSource("features/prototype/structured/StructuredPrototypePreview.tsx");
  const studio = readCompactSource(
    "features/prototype/structured/StructuredPrototypeStudioPage.tsx",
  );

  assert.match(
    canvas,
    /node\.type === "Freeform" && props\.editing && dropGeometry\.parentRect !== null/,
  );
  assert.match(canvas, /<StructuredPrototypeFreeformGridOverlay/);
  assert.match(overlay, /pointer-events-none absolute inset-0 z-0 overflow-hidden/);
  assert.match(overlay, /data-prototype-layout-grid-overlay=\{node\.id\}/);
  assert.match(overlay, /resolveStructuredPrototypeFreeformGridGeometries/);

  assert.match(studio, /const \[gridSnappingEnabled, setGridSnappingEnabled\] = useState\(true\)/);
  assert.match(studio, /setGridSnappingEnabled\(\(current\) => !current\)/);
  assert.match(studio, /data-prototype-grid-snapping-enabled=\{gridSnappingEnabled\}/);
  assert.match(
    studio,
    /<StructuredPrototypePreview[^>]*gridSnappingEnabled=\{gridSnappingEnabled\}/,
  );
  assert.match(
    preview,
    /<StructuredPrototypeCanvas[^>]*gridSnappingEnabled=\{gridSnappingEnabled\}/,
  );
});

test("Freeform resize snapping freezes one start frame and shares exact event-local projection", () => {
  const canvas = readCompactSource("features/prototype/structured/StructuredPrototypeCanvas.tsx");
  const canvasRootStart = canvas.indexOf("export function StructuredPrototypeCanvas");
  const resizeStart = canvas.indexOf("const handleResizePointerDown", canvasRootStart);
  const activateStart = canvas.indexOf("function activateResize", resizeStart);
  const projectionStart = canvas.indexOf("function resolveResizeProjection", activateStart);
  const scheduleStart = canvas.indexOf("function scheduleResize", projectionStart);
  const cleanupStart = canvas.indexOf("function cleanup", scheduleStart);
  const pointerMoveStart = canvas.indexOf("function handlePointerMove", cleanupStart);
  const pointerUpStart = canvas.indexOf("function handlePointerUp", pointerMoveStart);
  const pointerCancelStart = canvas.indexOf("function handlePointerCancel", pointerUpStart);
  assert.ok(
    canvasRootStart >= 0 &&
      resizeStart > canvasRootStart &&
      activateStart > resizeStart &&
      projectionStart > activateStart &&
      scheduleStart > projectionStart &&
      cleanupStart > scheduleStart &&
      pointerMoveStart > cleanupStart &&
      pointerUpStart > pointerMoveStart &&
      pointerCancelStart > pointerUpStart,
  );

  const pointerDown = canvas.slice(resizeStart, activateStart);
  const activation = canvas.slice(activateStart, projectionStart);
  const projector = canvas.slice(projectionStart, scheduleStart);
  const scheduledProjection = canvas.slice(scheduleStart, cleanupStart);
  const pointerMove = canvas.slice(pointerMoveStart, pointerUpStart);
  const pointerUp = canvas.slice(pointerUpStart, pointerCancelStart);
  const contextIndex = pointerDown.indexOf(
    "resolvePositionedSnapContext(snapParent, snapSelectedNodeIds, snapContainer)",
  );
  const sessionIndex = pointerDown.indexOf("const sessionId = resizeGestureChangeRef.current");
  const selectIndex = pointerDown.indexOf('onSelect(nodeId, "primary")');
  assert.ok(contextIndex >= 0 && contextIndex < sessionIndex && sessionIndex < selectIndex);
  assert.match(pointerDown, /setResizePhase\("armed"\)/);
  assert.match(pointerDown, /selectedNodeIds: \[\.\.\.snapContext\.selectedNodeIds\]/);
  assert.match(pointerDown, /directSiblings: snapContext\.directSiblings\.map/);
  assert.match(pointerDown, /guideOverlayFrame: \{\.\.\.snapContext\.guideOverlayFrame\}/);
  assert.match(pointerDown, /previewScale: snapContext\.previewScale/);
  assert.match(activation, /gesture\.activated = true; setResizePhase\("preview"\)/);

  assert.match(
    scheduledProjection,
    /resolveResizeProjection\(\s*current,\s*current\.latestClientX,\s*current\.latestClientY,\s*current\.latestLockAspectRatio,\s*current\.latestResizeFromCenter,\s*current\.latestBypassSnapping,?\s*\)/,
  );
  assert.match(
    pointerMove,
    /scheduleResize\(\s*pointerEvent\.clientX,\s*pointerEvent\.clientY,\s*pointerEvent\.shiftKey,\s*pointerEvent\.altKey,\s*pointerEvent\.ctrlKey \|\| pointerEvent\.metaKey,?\s*\)/,
  );
  assert.match(
    pointerUp,
    /resolveResizeProjection\(\s*activeGesture,\s*pointerEvent\.clientX,\s*pointerEvent\.clientY,\s*pointerEvent\.shiftKey,\s*pointerEvent\.altKey,\s*pointerEvent\.ctrlKey \|\| pointerEvent\.metaKey,?\s*\)/,
  );
  assert.doesNotMatch(
    `${projector} ${scheduledProjection}`,
    /getBoundingClientRect|nodeElementRegistrationsRef|\.parentElement|\.clientWidth|\.clientHeight/,
  );
});

test("Freeform resize snapping reprojects groups and exposes guides only during preview", () => {
  const canvas = readCompactSource("features/prototype/structured/StructuredPrototypeCanvas.tsx");
  const controlsLayerStart = canvas.indexOf("function StructuredPrototypeSelectionControlsLayer");
  const canvasRootStart = canvas.indexOf("export function StructuredPrototypeCanvas");
  const resizeStart = canvas.indexOf("const handleResizePointerDown", canvasRootStart);
  const projectionStart = canvas.indexOf("function resolveResizeProjection", resizeStart);
  const scheduleStart = canvas.indexOf("function scheduleResize", projectionStart);
  const cleanupStart = canvas.indexOf("function cleanup", scheduleStart);
  assert.ok(
    controlsLayerStart >= 0 &&
      canvasRootStart > controlsLayerStart &&
      resizeStart > canvasRootStart &&
      projectionStart > resizeStart &&
      scheduleStart > projectionStart &&
      cleanupStart > scheduleStart,
  );
  const controlsLayer = canvas.slice(controlsLayerStart, canvasRootStart);
  const projector = canvas.slice(projectionStart, scheduleStart);
  const scheduledProjection = canvas.slice(scheduleStart, cleanupStart);

  assert.match(
    projector,
    /resolveStructuredPrototypeGroupResizeSizeLimits\(\{\s*items: gesture\.groupItems,\s*direction: gesture\.direction,\s*lockAspectRatio,\s*resizeFromCenter,?\s*\}\)/,
  );
  assert.match(
    projector,
    /projectStructuredPrototypeGroupResizeItemsToBounds\(\s*gesture\.groupItems,\s*projection\.bounds,?\s*\)/,
  );
  assert.match(projector, /groupItems === undefined \? \{} : \{groupItems\}/);
  assert.match(
    controlsLayer,
    /resizePhase === "preview" \? resizeGuideOverlay : freeformMovePhase === "preview"/,
  );
  assert.match(controlsLayer, /resizeGuideOverlay === null \? "none" : "resize"/);
  assert.match(controlsLayer, /data-prototype-snap-guide-source=\{snapGuideSource\}/);
  assert.match(controlsLayer, /data-prototype-snap-source=\{snapGuideSource\}/);
  assert.match(scheduledProjection, /spacingGuides: \[\]/);
  assert.doesNotMatch(
    `${projector} ${scheduledProjection}`,
    /resolveStructuredPrototypeFreeformSpacingSnap|projection\.spacingGuides/,
  );
  assert.doesNotMatch(controlsLayer, /resizePhase === "pending".*resizeGuideOverlay/);
});

test("Freeform resize guides clear on pointerup, cancellation, acknowledgement, failure, and unmount", () => {
  const canvas = readCompactSource("features/prototype/structured/StructuredPrototypeCanvas.tsx");
  const canvasRootStart = canvas.indexOf("export function StructuredPrototypeCanvas");
  const endGestureStart = canvas.indexOf("const endResizeGesture", canvasRootStart);
  const endCommitStart = canvas.indexOf("const endResizeCommit", endGestureStart);
  const resizeStart = canvas.indexOf("const handleResizePointerDown", endCommitStart);
  const cancelStart = canvas.indexOf("function cancelResize", resizeStart);
  const pointerUpStart = canvas.indexOf("function handlePointerUp", cancelStart);
  const pointerCancelStart = canvas.indexOf("function handlePointerCancel", pointerUpStart);
  const unmountStart = canvas.indexOf("mountedRef.current = true", pointerCancelStart);
  const acknowledgeStart = canvas.indexOf(
    'if (resizePhase !== "pending" || resizeDraft === null) return',
    unmountStart,
  );
  assert.ok(
    canvasRootStart >= 0 &&
      endGestureStart > canvasRootStart &&
      endCommitStart > endGestureStart &&
      resizeStart > endCommitStart &&
      cancelStart > resizeStart &&
      pointerUpStart > cancelStart &&
      pointerCancelStart > pointerUpStart &&
      unmountStart > pointerCancelStart &&
      acknowledgeStart > unmountStart,
  );

  const endGesture = canvas.slice(endGestureStart, endCommitStart);
  const endCommit = canvas.slice(endCommitStart, resizeStart);
  const cancel = canvas.slice(cancelStart, pointerUpStart);
  const pointerUp = canvas.slice(pointerUpStart, pointerCancelStart);
  const unmount = canvas.slice(unmountStart, acknowledgeStart);
  const acknowledge = canvas.slice(
    acknowledgeStart,
    canvas.indexOf("const root = page.root", acknowledgeStart),
  );
  assert.match(endGesture, /clearResizeGuideOverlay\(\)/);
  assert.match(endCommit, /clearResizeGuideOverlay\(\)/);
  assert.match(cancel, /endResizeGesture\(reason\)/);
  assert.match(pointerUp, /const gesture = detachResizePointer\(\);.*clearResizeGuideOverlay\(\)/);
  assert.ok(
    pointerUp.indexOf("clearResizeGuideOverlay()") < pointerUp.indexOf('setResizePhase("pending")'),
  );
  assert.match(pointerUp, /if \(!applied && mountedRef\.current\).*endResizeCommit\("pointerup"\)/);
  assert.match(unmount, /endResizeGesture\("unmount"\); endResizeCommit\("unmount"\)/);
  assert.match(
    acknowledge,
    /if \(applied\) \{setResizeDraft\(null\); clearResizeGuideOverlay\(\); setResizePhase\("idle"\)/,
  );
});

test("editable prototype zoom does not interpolate geometry under pointer gestures", () => {
  const preview = readCompactSource("features/prototype/structured/StructuredPrototypePreview.tsx");
  assert.match(
    preview,
    /editing \? "transition-none" : "transition-\[transform,width\] motion-reduce:transition-none"/,
  );
  assert.match(preview, /dragDisabled=\{dragDisabled \|\| spacePressed\}/);
  assert.match(preview, /resizeDisabled=\{resizeDisabled \|\| spacePressed\}/);
  assert.match(preview, /marqueeDisabled=\{interactionBlocked \|\| spacePressed\}/);
  assert.match(
    preview,
    /const shouldPan = event\.button === 1 \|\| spacePressed \|\| \(event\.button === 0 && startedOnPreviewBackdrop\)/,
  );
});

test("mobile Studio keeps the canvas mounted and drives each side region through one Sheet", () => {
  const studio = readCompactSource(
    "features/prototype/structured/StructuredPrototypeStudioPage.tsx",
  );
  const responsiveRegion = readCompactSource(
    "features/prototype/structured/StructuredPrototypeResponsiveSideRegion.tsx",
  );
  const sheet = readCompactSource("components/ui/sheet.tsx");

  assert.match(studio, /const \[mobileDrawer, setMobileDrawer\] = useState<MobileDrawer>\(null\)/);
  assert.doesNotMatch(studio, /mobilePanel|mobileDrawer === "canvas"/);
  const canvasMarker = 'data-prototype-canvas-region="persistent"';
  const canvasMarkerStart = studio.lastIndexOf(canvasMarker);
  const canvasRegionStart = studio.lastIndexOf("<section", canvasMarkerStart);
  const canvasRegionEnd = studio.indexOf("</section>", canvasMarkerStart);
  assert.ok(
    canvasMarkerStart >= 0 && canvasRegionStart >= 0 && canvasRegionEnd > canvasMarkerStart,
  );
  assert.doesNotMatch(studio.slice(canvasRegionStart, canvasRegionEnd), /mobileDrawer/);
  assert.equal([...studio.matchAll(/<StructuredPrototypeResponsiveSideRegion/g)].length, 2);
  assert.match(responsiveRegion, /if \(desktop\) \{return \(\s*<aside/);
  assert.match(
    responsiveRegion,
    /<Sheet open=\{open\} onOpenChange=\{onOpenChange\} modal="trap-focus">/,
  );
  assert.match(responsiveRegion, /\{open && \(\s*<SheetContent/);
  assert.match(responsiveRegion, /data-prototype-side-region-mode="drawer"/);
  assert.match(responsiveRegion, /<SheetClose/);
  assert.match(sheet, /overlayClassName\?: SheetPrimitive\.Backdrop\.Props\["className"\]/);
  assert.match(sheet, /<SheetOverlay className=\{overlayClassName\}\s*\/>/);
  assert.match(
    responsiveRegion,
    /overlayClassName="bg-black\/45 supports-backdrop-filter:backdrop-blur-sm"/,
  );

  assert.match(studio, /action: "pages", drawer: "left" as const/);
  assert.match(studio, /action: "canvas", drawer: null/);
  assert.match(studio, /action: "inspector", drawer: "right" as const/);
  assert.match(studio, /setMobileDrawer\(item\.drawer\)/);
  assert.match(
    studio,
    /onSelectNode=.*setInspectorTab\("properties"\); setMobileDrawer\("right"\)/,
  );
});
