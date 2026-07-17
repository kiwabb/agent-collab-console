import assert from "node:assert/strict";
import test from "node:test";

import {
  resolveStructuredPrototypeFreeformCombinedSnaps,
  resolveStructuredPrototypeFreeformMoveSnap,
  type StructuredPrototypeFreeformMoveSnapInput,
  type StructuredPrototypeFreeformSnapDiagnosticCandidate,
  type StructuredPrototypeFreeformSnapAxis,
  type StructuredPrototypeFreeformSnapBounds,
  type StructuredPrototypeFreeformSnapGuide,
  type StructuredPrototypeFreeformSnapSibling,
} from "../src/features/prototype/structured/structuredPrototypeSnapping";
import {
  resolveStructuredPrototypeFreeformSpacingSnap,
  type StructuredPrototypeFreeformSpacingGuide,
  type StructuredPrototypeFreeformSpacingSnapCandidate,
} from "../src/features/prototype/structured/structuredPrototypeSpacingSnapping";
import type {
  StructuredPrototypeAxisGrid,
  StructuredPrototypeSquareGrid,
} from "../src/features/prototype/structured/types";

function columnsGrid({
  id = "grid-columns",
  originX = "0",
  margin = "20",
  visible = true,
  snapEnabled = true,
}: {
  id?: string;
  originX?: string;
  margin?: string;
  visible?: boolean;
  snapEnabled?: boolean;
} = {}): StructuredPrototypeAxisGrid {
  return {
    id,
    version: 1,
    type: "columns",
    visible,
    snapEnabled,
    origin: { x: originX, y: "0" },
    params: {
      count: 1,
      itemSize: "20",
      gutter: "0",
      margin,
      alignment: "start",
      colorTokenKey: "grid-color",
      opacity: "0.1",
    },
  };
}

function squareGrid(size: string): StructuredPrototypeSquareGrid {
  return {
    id: "grid-square",
    version: 1,
    type: "square",
    visible: true,
    snapEnabled: true,
    origin: { x: "0", y: "0" },
    params: {
      size,
      colorTokenKey: "grid-color",
      opacity: "0.4",
    },
  };
}

function snap(input: StructuredPrototypeFreeformMoveSnapInput) {
  return resolveStructuredPrototypeFreeformMoveSnap(input);
}

function guideAt(guides: readonly StructuredPrototypeFreeformSnapGuide[], index: number) {
  const guide = guides[index];
  if (guide === undefined) throw new Error(`expected snap guide at index ${index}`);
  return guide;
}

function spacingGuideAt(guides: readonly StructuredPrototypeFreeformSpacingGuide[], index: number) {
  const guide = guides[index];
  if (guide === undefined) throw new Error(`expected spacing guide at index ${index}`);
  return guide;
}

function diagnosticCandidate(
  candidates: readonly StructuredPrototypeFreeformSnapDiagnosticCandidate[],
  axis: StructuredPrototypeFreeformSnapAxis,
  source: StructuredPrototypeFreeformSnapDiagnosticCandidate["source"],
): StructuredPrototypeFreeformSnapDiagnosticCandidate {
  const candidate = candidates.find((item) => item.axis === axis && item.source === source);
  if (candidate === undefined) throw new Error(`expected ${axis}-axis ${source} diagnostic`);
  return candidate;
}

function spacingCandidateFor(
  axis: StructuredPrototypeFreeformSnapAxis,
  movingBounds: StructuredPrototypeFreeformSnapBounds,
  directSiblings: readonly StructuredPrototypeFreeformSnapSibling[],
): StructuredPrototypeFreeformSpacingSnapCandidate {
  const candidate = resolveStructuredPrototypeFreeformSpacingSnap({
    axis,
    movingBounds,
    selectedNodeIds: ["moving"],
    directSiblings,
    minimumPosition: 0,
    maximumPosition: 280,
    threshold: 6,
  });
  if (candidate === null) throw new Error(`expected ${axis}-axis spacing candidate`);
  return candidate;
}

function resolveMutuallyExclusiveSpacing({
  movingBounds,
  horizontalReferenceY,
  verticalReferenceX,
}: {
  movingBounds: StructuredPrototypeFreeformSnapBounds;
  horizontalReferenceY: number;
  verticalReferenceX: number;
}) {
  const directSiblings: readonly StructuredPrototypeFreeformSnapSibling[] = [
    { nodeId: "x-left", x: 0, y: horizontalReferenceY, width: 20, height: 20 },
    { nodeId: "x-right", x: 80, y: horizontalReferenceY, width: 20, height: 20 },
    { nodeId: "y-top", x: verticalReferenceX, y: 0, width: 20, height: 20 },
    { nodeId: "y-bottom", x: verticalReferenceX, y: 80, width: 20, height: 20 },
  ];
  return resolveStructuredPrototypeFreeformCombinedSnaps({
    selectionBounds: movingBounds,
    selectedNodeIds: ["moving"],
    directSiblings,
    horizontalAlignment: { position: movingBounds.x, distance: null, guide: null },
    verticalAlignment: { position: movingBounds.y, distance: null, guide: null },
    horizontalSpacing: spacingCandidateFor("x", movingBounds, directSiblings),
    verticalSpacing: spacingCandidateFor("y", movingBounds, directSiblings),
    horizontalGrid: null,
    verticalGrid: null,
    maximumX: 280,
    maximumY: 280,
  });
}

test("snaps a single Freeform frame to container edges and returns visible guides", () => {
  const result = snap({
    selectionBounds: { x: 20, y: 15, width: 40, height: 20 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: -16, y: -11 },
    containerWidth: 300,
    containerHeight: 200,
    previewScale: 1,
    directSiblings: [],
  });

  assert.deepEqual(result.position, { x: 0, y: 0 });
  assert.deepEqual(result.delta, { x: -20, y: -15 });
  assert.deepEqual(result.guides, [
    {
      axis: "x",
      coordinate: 0,
      movingAnchor: "left",
      targetAnchor: "left",
      targetKind: "container",
      targetNodeId: null,
    },
    {
      axis: "y",
      coordinate: 0,
      movingAnchor: "top",
      targetAnchor: "top",
      targetKind: "container",
      targetNodeId: null,
    },
  ]);
});

test("converts the six-client-pixel threshold through preview scale", () => {
  const baseInput: Omit<StructuredPrototypeFreeformMoveSnapInput, "previewScale"> = {
    selectionBounds: { x: 20, y: 100, width: 20, height: 20 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: -16, y: 0 },
    containerWidth: 500,
    containerHeight: 500,
    directSiblings: [],
  };

  const zoomedIn = snap({ ...baseInput, previewScale: 2 });
  assert.deepEqual(zoomedIn.position, { x: 4, y: 100 });
  assert.equal(zoomedIn.guides.length, 0);

  const zoomedOut = snap({ ...baseInput, previewScale: 0.5 });
  assert.deepEqual(zoomedOut.position, { x: 0, y: 100 });
  assert.deepEqual(zoomedOut.guides, [
    {
      axis: "x",
      coordinate: 0,
      movingAnchor: "left",
      targetAnchor: "left",
      targetKind: "container",
      targetNodeId: null,
    },
  ]);
});

test("records deterministic alignment diagnostics from the bounded raw frame", () => {
  const input: StructuredPrototypeFreeformMoveSnapInput = {
    selectionBounds: { x: 20, y: 100, width: 20, height: 20 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: -16, y: 0 },
    containerWidth: 500,
    containerHeight: 500,
    previewScale: 1,
    directSiblings: [],
  };
  const result = snap(input);
  const repeated = snap(input);

  assert.deepEqual(result.diagnostics.rawPosition, { x: 4, y: 100 });
  assert.equal(result.diagnostics.threshold, 6);
  assert.deepEqual(result.diagnostics.axisWinners, { x: "alignment", y: "raw" });
  assert.deepEqual(Object.keys(result.diagnostics), [
    "rawPosition",
    "threshold",
    "axisWinners",
    "candidates",
  ]);
  assert.equal(result.diagnostics.candidates.length, 1);

  const candidate = diagnosticCandidate(result.diagnostics.candidates, "x", "alignment");
  if (candidate.source !== "alignment") throw new Error("expected alignment diagnostic");
  assert.deepEqual(
    {
      axis: candidate.axis,
      source: candidate.source,
      position: candidate.position,
      correction: candidate.correction,
      distance: candidate.distance,
      outcome: candidate.outcome,
      coordinate: candidate.coordinate,
      movingAnchor: candidate.movingAnchor,
      targetAnchor: candidate.targetAnchor,
      targetKind: candidate.targetKind,
      targetNodeId: candidate.targetNodeId,
    },
    {
      axis: "x",
      source: "alignment",
      position: 0,
      correction: -4,
      distance: 4,
      outcome: "winner",
      coordinate: 0,
      movingAnchor: "left",
      targetAnchor: "left",
      targetKind: "container",
      targetNodeId: null,
    },
  );
  assert.equal(
    candidate.sortKey,
    "string:1:x|string:9:alignment|number:4|number:0|number:0|null|number:0|number:0|number:0",
  );
  assert.deepEqual(
    repeated.diagnostics.candidates.map((item) => item.sortKey),
    result.diagnostics.candidates.map((item) => item.sortKey),
  );
});

test("records a spacing winner and a farther alignment candidate", () => {
  const result = snap({
    selectionBounds: { x: 50, y: 0, width: 20, height: 20 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: -7, y: 0 },
    containerWidth: 300,
    containerHeight: 200,
    previewScale: 1,
    directSiblings: [
      { nodeId: "left", x: 0, y: 0, width: 20, height: 20 },
      { nodeId: "right", x: 80, y: 0, width: 20, height: 20 },
      { nodeId: "alignment", x: 69, y: 100, width: 20, height: 20 },
    ],
  });

  assert.equal(result.diagnostics.axisWinners.x, "spacing");
  const alignment = diagnosticCandidate(result.diagnostics.candidates, "x", "alignment");
  const spacing = diagnosticCandidate(result.diagnostics.candidates, "x", "spacing");
  assert.equal(alignment.outcome, "farther");
  assert.equal(alignment.distance, 6);
  if (spacing.source !== "spacing") throw new Error("expected spacing diagnostic");
  assert.deepEqual(
    {
      position: spacing.position,
      correction: spacing.correction,
      distance: spacing.distance,
      outcome: spacing.outcome,
      placement: spacing.placement,
      gap: spacing.gap,
      referenceNodeIds: spacing.referenceNodeIds,
    },
    {
      position: 40,
      correction: -3,
      distance: 3,
      outcome: "winner",
      placement: "between",
      gap: 20,
      referenceNodeIds: ["left", "right"],
    },
  );
});

test("records grid wins, farther candidates, and source-priority ties", () => {
  const directSiblings = [
    { nodeId: "left", x: 0, y: 50, width: 10, height: 10 },
    { nodeId: "right", x: 30, y: 50, width: 10, height: 10 },
  ] as const;
  const common = {
    selectionBounds: { x: 0, y: 50, width: 10, height: 10 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: 17, y: 0 },
    containerWidth: 200,
    containerHeight: 120,
    previewScale: 1,
    directSiblings,
    gridSnappingEnabled: true,
  } satisfies Omit<StructuredPrototypeFreeformMoveSnapInput, "grids">;

  const gridWinner = snap({ ...common, grids: [columnsGrid({ originX: "1" })] });
  assert.equal(gridWinner.diagnostics.axisWinners.x, "grid");
  assert.equal(
    diagnosticCandidate(gridWinner.diagnostics.candidates, "x", "alignment").outcome,
    "farther",
  );
  assert.equal(
    diagnosticCandidate(gridWinner.diagnostics.candidates, "x", "spacing").outcome,
    "farther",
  );
  const grid = diagnosticCandidate(gridWinner.diagnostics.candidates, "x", "grid");
  if (grid.source !== "grid") throw new Error("expected grid diagnostic");
  assert.deepEqual(
    {
      position: grid.position,
      correction: grid.correction,
      distance: grid.distance,
      outcome: grid.outcome,
      gridId: grid.gridId,
      gridType: grid.gridType,
      gridLineIndex: grid.gridLineIndex,
      coordinate: grid.coordinate,
      movingAnchor: grid.movingAnchor,
    },
    {
      position: 16,
      correction: -1,
      distance: 1,
      outcome: "winner",
      gridId: "grid-columns",
      gridType: "columns",
      gridLineIndex: 0,
      coordinate: 21,
      movingAnchor: "center",
    },
  );

  const spacingTie = snap({ ...common, grids: [columnsGrid()] });
  assert.equal(spacingTie.diagnostics.axisWinners.x, "spacing");
  assert.equal(
    diagnosticCandidate(spacingTie.diagnostics.candidates, "x", "grid").outcome,
    "tiePriority",
  );
});

test("marks an initially winning spacing candidate as cross-axis invalid", () => {
  const result = snap({
    selectionBounds: { x: 41, y: 9, width: 20, height: 10 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: 0, y: 0 },
    containerWidth: 300,
    containerHeight: 300,
    previewScale: 1,
    directSiblings: [
      { nodeId: "left", x: 0, y: 0, width: 20, height: 10 },
      { nodeId: "right", x: 81, y: 0, width: 20, height: 10 },
    ],
  });

  assert.deepEqual(result.diagnostics.axisWinners, { x: "raw", y: "alignment" });
  const spacing = diagnosticCandidate(result.diagnostics.candidates, "x", "spacing");
  assert.equal(spacing.outcome, "crossAxisInvalid");
  assert.equal(spacing.position, 40.5);
  assert.equal(spacing.distance, 0.5);
});

test("diagnoses the exact spacing candidate refreshed after a cross-axis lane change", () => {
  const input: StructuredPrototypeFreeformMoveSnapInput = {
    selectionBounds: { x: 92, y: 115, width: 29, height: 37 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: -1, y: 5 },
    containerWidth: 300,
    containerHeight: 300,
    previewScale: 1,
    directSiblings: [
      { nodeId: "short-lane-right", x: 129, y: 156, width: 8, height: 39 },
      { nodeId: "tall-lane-right", x: 129, y: 144, width: 34, height: 35 },
      { nodeId: "left", x: 53, y: 112, width: 22, height: 49 },
    ],
  };

  const result = snap(input);
  const repeated = snap(input);
  const initialCandidate = spacingCandidateFor(
    "x",
    {
      ...input.selectionBounds,
      x: result.diagnostics.rawPosition.x,
      y: result.diagnostics.rawPosition.y,
    },
    input.directSiblings,
  );

  assert.deepEqual(result.position, { x: 87.5, y: 119 });
  assert.deepEqual(initialCandidate.referenceNodeIds, ["left", "short-lane-right"]);
  const guide = spacingGuideAt(result.spacingGuides, 0);
  const candidate = diagnosticCandidate(result.diagnostics.candidates, "x", "spacing");
  if (candidate.source !== "spacing") throw new Error("expected spacing diagnostic");
  assert.equal(candidate.outcome, "winner");
  assert.deepEqual(
    {
      referenceNodeIds: candidate.referenceNodeIds,
      gap: candidate.gap,
      placement: candidate.placement,
    },
    {
      referenceNodeIds: guide.referenceNodeIds,
      gap: guide.gap,
      placement: guide.placement,
    },
  );
  assert.deepEqual(guide.referenceNodeIds, ["left", "tall-lane-right"]);
  assert.deepEqual(repeated.diagnostics.candidates, result.diagnostics.candidates);
});

test("keeps modifier bypass outside the solver diagnostic vocabulary", () => {
  const result = snap({
    selectionBounds: { x: 20, y: 100, width: 20, height: 20 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: -16, y: 0 },
    containerWidth: 500,
    containerHeight: 500,
    previewScale: 1,
    directSiblings: [],
  });

  assert.deepEqual(result.diagnostics.axisWinners, { x: "alignment", y: "raw" });
  assert.deepEqual(
    [...new Set(result.diagnostics.candidates.map((candidate) => candidate.source))],
    ["alignment"],
  );
  assert.equal(Object.hasOwn(result.diagnostics, "bypass"), false);
  assert.equal(Object.hasOwn(result.diagnostics, "bypassed"), false);
});

test("snaps selection anchors to frame-local grid lines with stable metadata", () => {
  const result = snap({
    selectionBounds: { x: 0, y: 50, width: 10, height: 10 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: 17, y: 0 },
    containerWidth: 200,
    containerHeight: 120,
    previewScale: 1,
    directSiblings: [],
    grids: [columnsGrid()],
    gridSnappingEnabled: true,
  });

  assert.equal(result.position.x, 15);
  assert.deepEqual(
    result.guides.find((guide) => guide.axis === "x"),
    {
      axis: "x",
      coordinate: 20,
      movingAnchor: "center",
      targetAnchor: "center",
      targetKind: "grid",
      targetNodeId: null,
      gridId: "grid-columns",
      gridType: "columns",
      gridLineIndex: 0,
    },
  );
});

test("arbitrates exact ties as alignment then spacing then grid from one raw frame", () => {
  const alignmentTie = snap({
    selectionBounds: { x: 0, y: 20, width: 10, height: 10 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: 15, y: 0 },
    containerWidth: 40,
    containerHeight: 100,
    previewScale: 1,
    directSiblings: [],
    grids: [columnsGrid({ margin: "0" })],
    gridSnappingEnabled: true,
  });
  assert.equal(alignmentTie.position.x, 15);
  assert.equal(alignmentTie.guides.find((guide) => guide.axis === "x")?.targetKind, "container");

  const directSiblings = [
    { nodeId: "left", x: 0, y: 50, width: 10, height: 10 },
    { nodeId: "right", x: 30, y: 50, width: 10, height: 10 },
  ] as const;
  const spacingTie = snap({
    selectionBounds: { x: 0, y: 50, width: 10, height: 10 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: 17, y: 0 },
    containerWidth: 200,
    containerHeight: 120,
    previewScale: 1,
    directSiblings,
    grids: [columnsGrid()],
    gridSnappingEnabled: true,
  });
  assert.equal(spacingTie.position.x, 15);
  assert.equal(spacingTie.spacingGuides[0]?.axis, "x");
  assert.equal(
    spacingTie.guides.some((guide) => guide.axis === "x" && guide.targetKind === "grid"),
    false,
  );

  const closerGrid = snap({
    selectionBounds: { x: 0, y: 50, width: 10, height: 10 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: 17, y: 0 },
    containerWidth: 200,
    containerHeight: 120,
    previewScale: 1,
    directSiblings,
    grids: [columnsGrid({ originX: "1" })],
    gridSnappingEnabled: true,
  });
  assert.equal(closerGrid.position.x, 16);
  assert.equal(closerGrid.guides.find((guide) => guide.axis === "x")?.targetKind, "grid");
  assert.equal(
    closerGrid.spacingGuides.some((guide) => guide.axis === "x"),
    false,
  );
});

test("treats fractional machine tails as ties without changing the alignment target", () => {
  const result = snap({
    selectionBounds: { x: 0, y: 0, width: 0.17, height: 0.17 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: 0.8, y: 0.8 },
    containerWidth: 1.74,
    containerHeight: 1.74,
    previewScale: 1,
    directSiblings: [],
    grids: [squareGrid("0.3")],
    gridSnappingEnabled: true,
  });

  assert.deepEqual(result.position, { x: 0.785, y: 0.785 });
  assert.deepEqual(
    result.guides.map((guide) => ({ axis: guide.axis, coordinate: guide.coordinate })),
    [
      { axis: "x", coordinate: 0.87 },
      { axis: "y", coordinate: 0.87 },
    ],
  );
  assert.equal(
    result.guides.every((guide) => guide.targetKind === "container"),
    true,
  );
  assert.deepEqual(result.diagnostics.axisWinners, { x: "alignment", y: "alignment" });
  for (const axis of ["x", "y"] as const) {
    assert.equal(
      diagnosticCandidate(result.diagnostics.candidates, axis, "grid").outcome,
      "tiePriority",
    );
  }
});

test("treats fractional machine tails as ties between spacing and grid candidates", () => {
  const result = snap({
    selectionBounds: { x: 0, y: 0.5, width: 0.17, height: 0.17 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: 0.8, y: 0 },
    containerWidth: 2,
    containerHeight: 2,
    previewScale: 1,
    directSiblings: [
      { nodeId: "left", x: 0.515, y: 0.5, width: 0.17, height: 0.17 },
      { nodeId: "right", x: 1.055, y: 0.5, width: 0.17, height: 0.17 },
    ],
    grids: [squareGrid("0.3")],
    gridSnappingEnabled: true,
  });

  assert.equal(result.position.x, 0.785);
  assert.equal(result.spacingGuides[0]?.axis, "x");
  assert.equal(
    result.guides.some((guide) => guide.axis === "x" && guide.targetKind === "grid"),
    false,
  );
});

test("keeps per-grid visibility separate from both snap gates", () => {
  const base = {
    selectionBounds: { x: 0, y: 50, width: 10, height: 10 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: 17, y: 0 },
    containerWidth: 200,
    containerHeight: 120,
    previewScale: 1,
    directSiblings: [],
  } satisfies Omit<StructuredPrototypeFreeformMoveSnapInput, "grids" | "gridSnappingEnabled">;

  const hiddenButEnabled = snap({
    ...base,
    grids: [columnsGrid({ visible: false, snapEnabled: true })],
    gridSnappingEnabled: true,
  });
  assert.equal(hiddenButEnabled.position.x, 15);

  for (const result of [
    snap({
      ...base,
      grids: [columnsGrid({ visible: true, snapEnabled: false })],
      gridSnappingEnabled: true,
    }),
    snap({
      ...base,
      grids: [columnsGrid()],
      gridSnappingEnabled: false,
    }),
  ]) {
    assert.equal(result.position.x, 17);
    assert.equal(
      result.guides.some((guide) => guide.targetKind === "grid"),
      false,
    );
  }
});

test("applies the inclusive six-client-pixel grid threshold at every zoom", () => {
  const gridLineX = 80;
  for (const previewScale of [0.5, 1, 2, 4]) {
    const threshold = 6 / previewScale;
    const width = 1;
    const acceptedX = gridLineX - width - threshold;
    const rejectedX = acceptedX - 1e-6 / previewScale;
    const common = {
      selectionBounds: { x: 0, y: 80, width, height: 1 },
      selectedNodeIds: ["moving"],
      containerWidth: 200,
      containerHeight: 120,
      previewScale,
      directSiblings: [],
      grids: [columnsGrid({ originX: "60" })],
      gridSnappingEnabled: true,
    } as const;
    const accepted = snap({ ...common, requestedDelta: { x: acceptedX, y: 0 } });
    assert.equal(accepted.position.x, gridLineX - width, `accepted at zoom ${previewScale}`);
    assert.deepEqual(
      accepted.guides.find((guide) => guide.axis === "x"),
      {
        axis: "x",
        coordinate: gridLineX,
        movingAnchor: "right",
        targetAnchor: "right",
        targetKind: "grid",
        targetNodeId: null,
        gridId: "grid-columns",
        gridType: "columns",
        gridLineIndex: 0,
      },
      `grid guide at zoom ${previewScale}`,
    );
    const rejected = snap({ ...common, requestedDelta: { x: rejectedX, y: 0 } });
    assert.ok(
      Math.abs(rejected.position.x - rejectedX) < 1e-9,
      `rejected beyond threshold at zoom ${previewScale}`,
    );
  }
});

test("includes container centers and accepts an exact six-pixel snap distance", () => {
  const result = snap({
    selectionBounds: { x: 390, y: 930, width: 200, height: 60 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: 5, y: 4 },
    containerWidth: 1_000,
    containerHeight: 1_000,
    previewScale: 1,
    directSiblings: [],
  });

  assert.deepEqual(result.position, { x: 400, y: 940 });
  assert.deepEqual(result.guides, [
    {
      axis: "x",
      coordinate: 500,
      movingAnchor: "center",
      targetAnchor: "center",
      targetKind: "container",
      targetNodeId: null,
    },
    {
      axis: "y",
      coordinate: 1_000,
      movingAnchor: "bottom",
      targetAnchor: "bottom",
      targetKind: "container",
      targetNodeId: null,
    },
  ]);
});

test("uses unselected direct siblings and aligns the selection's right edge", () => {
  const result = snap({
    selectionBounds: { x: 90, y: 70, width: 50, height: 30 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: 7, y: 3 },
    containerWidth: 400,
    containerHeight: 300,
    previewScale: 1,
    directSiblings: [
      { nodeId: "moving", x: 97, y: 73, width: 50, height: 30 },
      { nodeId: "sibling-b", x: 150, y: 180, width: 60, height: 40 },
    ],
  });

  assert.deepEqual(result.position, { x: 100, y: 73 });
  assert.deepEqual(result.delta, { x: 10, y: 3 });
  assert.deepEqual(result.guides, [
    {
      axis: "x",
      coordinate: 150,
      movingAnchor: "right",
      targetAnchor: "left",
      targetKind: "sibling",
      targetNodeId: "sibling-b",
    },
  ]);
});

test("snaps a grouped selection's horizontal and vertical bounds independently", () => {
  const result = snap({
    selectionBounds: { x: 100, y: 100, width: 200, height: 100 },
    selectedNodeIds: ["first", "second"],
    requestedDelta: { x: 96, y: 45 },
    containerWidth: 1_000,
    containerHeight: 400,
    previewScale: 1,
    directSiblings: [{ nodeId: "target", x: 300, y: 60, width: 80, height: 20 }],
  });

  assert.deepEqual(result.position, { x: 200, y: 150 });
  assert.deepEqual(result.delta, { x: 100, y: 50 });
  assert.deepEqual(guideAt(result.guides, 0), {
    axis: "x",
    coordinate: 300,
    movingAnchor: "center",
    targetAnchor: "left",
    targetKind: "sibling",
    targetNodeId: "target",
  });
  assert.deepEqual(guideAt(result.guides, 1), {
    axis: "y",
    coordinate: 200,
    movingAnchor: "middle",
    targetAnchor: "middle",
    targetKind: "container",
    targetNodeId: null,
  });
});

test("resolves equally close snap targets by kind, coordinate, then node id", () => {
  const byKind = snap({
    selectionBounds: { x: 20, y: 100, width: 20, height: 20 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: -15, y: 0 },
    containerWidth: 1_000,
    containerHeight: 1_000,
    previewScale: 1,
    directSiblings: [{ nodeId: "sibling", x: 10, y: 200, width: 100, height: 20 }],
  });
  assert.equal(guideAt(byKind.guides, 0).targetKind, "container");

  const byCoordinate = snap({
    selectionBounds: { x: 160, y: 100, width: 20, height: 20 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: 0, y: 0 },
    containerWidth: 1_000,
    containerHeight: 1_000,
    previewScale: 1,
    directSiblings: [
      { nodeId: "zeta", x: 155, y: 200, width: 80, height: 20 },
      { nodeId: "alpha", x: 165, y: 240, width: 80, height: 20 },
    ],
  });
  assert.equal(guideAt(byCoordinate.guides, 0).coordinate, 155);
  assert.equal(guideAt(byCoordinate.guides, 0).targetNodeId, "zeta");

  const byNodeId = snap({
    selectionBounds: { x: 160, y: 100, width: 20, height: 20 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: 0, y: 0 },
    containerWidth: 1_000,
    containerHeight: 1_000,
    previewScale: 1,
    directSiblings: [
      { nodeId: "zeta", x: 155, y: 200, width: 80, height: 20 },
      { nodeId: "alpha", x: 155, y: 240, width: 80, height: 20 },
    ],
  });
  assert.equal(guideAt(byNodeId.guides, 0).targetNodeId, "alpha");
});

test("chooses a closer equal-spacing candidate over a farther alignment candidate", () => {
  const result = snap({
    selectionBounds: { x: 50, y: 0, width: 20, height: 20 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: -7, y: 0 },
    containerWidth: 300,
    containerHeight: 200,
    previewScale: 1,
    directSiblings: [
      { nodeId: "left", x: 0, y: 0, width: 20, height: 20 },
      { nodeId: "right", x: 80, y: 0, width: 20, height: 20 },
      { nodeId: "alignment", x: 69, y: 100, width: 20, height: 20 },
    ],
  });

  assert.equal(result.position.x, 40);
  assert.equal(
    result.guides.some((guide) => guide.axis === "x"),
    false,
  );
  assert.equal(result.spacingGuides.length, 1);
  const spacing = spacingGuideAt(result.spacingGuides, 0);
  assert.equal(spacing.axis, "x");
  assert.equal(spacing.placement, "between");
  assert.deepEqual(spacing.referenceNodeIds, ["left", "right"]);
});

test("preserves alignment priority when spacing needs the same correction distance", () => {
  const result = snap({
    selectionBounds: { x: 50, y: 0, width: 20, height: 20 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: -7, y: 0 },
    containerWidth: 300,
    containerHeight: 200,
    previewScale: 1,
    directSiblings: [
      { nodeId: "left", x: 0, y: 0, width: 20, height: 20 },
      { nodeId: "right", x: 80, y: 0, width: 20, height: 20 },
      { nodeId: "alignment", x: 66, y: 100, width: 20, height: 20 },
    ],
  });

  assert.equal(result.position.x, 46);
  assert.equal(result.spacingGuides.length, 0);
  const horizontal = result.guides.find((guide) => guide.axis === "x");
  if (horizontal === undefined) throw new Error("expected horizontal alignment guide");
  assert.equal(horizontal.targetNodeId, "alignment");
  assert.equal(result.diagnostics.axisWinners.x, "alignment");
  assert.equal(
    diagnosticCandidate(result.diagnostics.candidates, "x", "spacing").outcome,
    "tiePriority",
  );
});

test("preserves vertical alignment priority over an equally close spacing candidate", () => {
  const result = snap({
    selectionBounds: { x: 0, y: 50, width: 20, height: 20 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: 0, y: -7 },
    containerWidth: 300,
    containerHeight: 300,
    previewScale: 1,
    directSiblings: [
      { nodeId: "top", x: 0, y: 0, width: 20, height: 20 },
      { nodeId: "bottom", x: 0, y: 80, width: 20, height: 20 },
      { nodeId: "alignment", x: 100, y: 66, width: 20, height: 20 },
    ],
  });

  assert.equal(result.position.y, 46);
  assert.equal(result.spacingGuides.length, 0);
  const vertical = result.guides.find((guide) => guide.axis === "y");
  if (vertical === undefined) throw new Error("expected vertical alignment guide");
  assert.equal(vertical.targetNodeId, "alignment");
});

test("combines horizontal spacing with vertical alignment from one raw frame", () => {
  const result = snap({
    selectionBounds: { x: 50, y: 50, width: 20, height: 20 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: -7, y: -4 },
    containerWidth: 300,
    containerHeight: 200,
    previewScale: 1,
    directSiblings: [
      { nodeId: "left", x: 0, y: 40, width: 20, height: 20 },
      { nodeId: "right", x: 80, y: 40, width: 20, height: 20 },
    ],
  });

  assert.deepEqual(result.position, { x: 40, y: 50 });
  assert.equal(spacingGuideAt(result.spacingGuides, 0).axis, "x");
  const vertical = result.guides.find((guide) => guide.axis === "y");
  if (vertical === undefined) throw new Error("expected vertical alignment guide");
  assert.equal(vertical.coordinate, 50);
});

test("keeps the equal-spacing threshold at exactly six client pixels across zoom", () => {
  const directSiblings = [
    { nodeId: "left", x: 0, y: 0, width: 20, height: 20 },
    { nodeId: "right", x: 200, y: 0, width: 20, height: 20 },
  ] as const;

  for (const previewScale of [0.5, 1, 2, 4]) {
    const thresholdCanvas = 6 / previewScale;
    const atThreshold = snap({
      selectionBounds: { x: 100, y: 0, width: 20, height: 20 },
      selectedNodeIds: ["moving"],
      requestedDelta: { x: thresholdCanvas, y: 0 },
      containerWidth: 500,
      containerHeight: 200,
      previewScale,
      directSiblings,
    });
    assert.equal(atThreshold.position.x, 100);
    assert.equal(spacingGuideAt(atThreshold.spacingGuides, 0).axis, "x");

    const aboveThresholdCanvas = (6 + 1e-6) / previewScale;
    const aboveThreshold = snap({
      selectionBounds: { x: 100, y: 0, width: 20, height: 20 },
      selectedNodeIds: ["moving"],
      requestedDelta: { x: aboveThresholdCanvas, y: 0 },
      containerWidth: 500,
      containerHeight: 200,
      previewScale,
      directSiblings,
    });
    assert.equal(aboveThreshold.position.x, 100 + aboveThresholdCanvas);
    assert.equal(aboveThreshold.spacingGuides.length, 0);
    assert.equal(
      aboveThreshold.guides.some((guide) => guide.axis === "x"),
      false,
    );
  }
});

test("preserves a fractional equal-spacing target through move projection", () => {
  const result = snap({
    selectionBounds: { x: 50, y: 0, width: 20, height: 20 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: -4, y: 0 },
    containerWidth: 300,
    containerHeight: 200,
    previewScale: 1,
    directSiblings: [
      { nodeId: "left", x: 0, y: 0, width: 20, height: 20 },
      { nodeId: "right", x: 81, y: 0, width: 20, height: 20 },
    ],
  });

  assert.equal(result.position.x, 40.5);
  assert.equal(spacingGuideAt(result.spacingGuides, 0).gap, 20.5);
});

test("drops spacing when the other axis snap leaves the shared visual lane", () => {
  const result = snap({
    selectionBounds: { x: 41, y: 9, width: 20, height: 10 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: 0, y: 0 },
    containerWidth: 300,
    containerHeight: 300,
    previewScale: 1,
    directSiblings: [
      { nodeId: "left", x: 0, y: 0, width: 20, height: 10 },
      { nodeId: "right", x: 81, y: 0, width: 20, height: 10 },
    ],
  });

  assert.deepEqual(result.position, { x: 41, y: 10 });
  assert.equal(result.spacingGuides.length, 0);
  const vertical = result.guides.find((guide) => guide.axis === "y");
  if (vertical === undefined) throw new Error("expected the lane-exiting vertical alignment");
  assert.equal(vertical.coordinate, 10);
});

test("keeps compatible horizontal and vertical spacing in stable guide order", () => {
  const result = snap({
    selectionBounds: { x: 41, y: 41, width: 20, height: 20 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: 0, y: 0 },
    containerWidth: 300,
    containerHeight: 300,
    previewScale: 1,
    directSiblings: [
      { nodeId: "x-left", x: 0, y: 0, width: 20, height: 200 },
      { nodeId: "x-right", x: 80, y: 0, width: 20, height: 200 },
      { nodeId: "y-top", x: 0, y: 0, width: 200, height: 20 },
      { nodeId: "y-bottom", x: 0, y: 80, width: 200, height: 20 },
    ],
  });

  assert.deepEqual(result.position, { x: 40, y: 40 });
  assert.deepEqual(
    result.spacingGuides.map((guide) => guide.axis),
    ["x", "y"],
  );
});

test("keeps the smaller horizontal spacing correction when dual-axis lanes conflict", () => {
  const result = resolveMutuallyExclusiveSpacing({
    movingBounds: { x: 42, y: 43, width: 20, height: 20 },
    horizontalReferenceY: 62,
    verticalReferenceX: 61,
  });

  assert.equal(result.horizontal.position, 40);
  assert.equal(result.horizontal.spacingGuide?.axis, "x");
  assert.equal(result.horizontalSpacingCandidate?.guide, result.horizontal.spacingGuide);
  assert.equal(result.vertical.position, 43);
  assert.equal(result.vertical.spacingGuide, null);
  assert.equal(result.verticalSpacingCandidate, null);
});

test("keeps the smaller vertical spacing correction when dual-axis lanes conflict", () => {
  const result = resolveMutuallyExclusiveSpacing({
    movingBounds: { x: 43, y: 42, width: 20, height: 20 },
    horizontalReferenceY: 61,
    verticalReferenceX: 62,
  });

  assert.equal(result.horizontal.position, 43);
  assert.equal(result.horizontal.spacingGuide, null);
  assert.equal(result.horizontalSpacingCandidate, null);
  assert.equal(result.vertical.position, 40);
  assert.equal(result.vertical.spacingGuide?.axis, "y");
  assert.equal(result.verticalSpacingCandidate?.guide, result.vertical.spacingGuide);
});

test("uses horizontal spacing as the fixed tie-break for conflicting equal corrections", () => {
  const result = resolveMutuallyExclusiveSpacing({
    movingBounds: { x: 41, y: 41, width: 20, height: 20 },
    horizontalReferenceY: 60,
    verticalReferenceX: 60,
  });

  assert.equal(result.horizontal.position, 40);
  assert.equal(result.horizontal.spacingGuide?.axis, "x");
  assert.equal(result.vertical.position, 41);
  assert.equal(result.vertical.spacingGuide, null);
});

test("keeps the snapped frame inside the Freeform container", () => {
  const result = snap({
    selectionBounds: { x: 20, y: 20, width: 20, height: 20 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: -1_000, y: 1_000 },
    containerWidth: 100,
    containerHeight: 80,
    previewScale: 1,
    directSiblings: [],
  });

  assert.deepEqual(result.position, { x: 0, y: 60 });
  assert.deepEqual(result.delta, { x: -20, y: 40 });
  assert.equal(result.guides.length, 2);
});

test("falls back to alignment for an arithmetic zero gap and keeps projection safe", async () => {
  const result = snap({
    selectionBounds: { x: 64.2, y: 0, width: 128.2, height: 20 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: 0, y: 0 },
    containerWidth: 400,
    containerHeight: 200,
    previewScale: 1,
    directSiblings: [
      { nodeId: "left", x: 0.1, y: 0, width: 64.1, height: 20 },
      { nodeId: "right", x: 192.4, y: 0, width: 20, height: 20 },
      { nodeId: "alignment", x: 64.20000001, y: 100, width: 20, height: 20 },
    ],
  });

  assert.equal(result.spacingGuides.length, 0);
  const horizontal = result.guides.find((guide) => guide.axis === "x");
  if (horizontal === undefined) throw new Error("expected horizontal alignment guide");
  assert.equal(horizontal.targetNodeId, "left");

  const {
    projectStructuredPrototypeFreeformSnapGuides,
    projectStructuredPrototypeFreeformSpacingGuides,
  } = await import("../src/features/prototype/structured/structuredPrototypeSnapGuides");
  assert.doesNotThrow(() => {
    projectStructuredPrototypeFreeformSnapGuides({
      freeformOrigin: { x: 0, y: 0 },
      containerWidth: 400,
      containerHeight: 200,
      previewScale: 1,
      guides: result.guides,
    });
    projectStructuredPrototypeFreeformSpacingGuides({
      freeformOrigin: { x: 0, y: 0 },
      previewScale: 1,
      guides: result.spacingGuides,
    });
  });
});

test("keeps movement available for rendered frames that overflow their Freeform", () => {
  const partiallyOverflowing = snap({
    selectionBounds: { x: 90, y: 20, width: 20, height: 20 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: 0, y: 0 },
    containerWidth: 100,
    containerHeight: 100,
    previewScale: 1,
    directSiblings: [{ nodeId: "overflowing-sibling", x: 90, y: 50, width: 20, height: 20 }],
  });
  assert.deepEqual(partiallyOverflowing.position, { x: 80, y: 20 });
  assert.equal(guideAt(partiallyOverflowing.guides, 0).targetKind, "container");

  const floatOvershoot = snap({
    selectionBounds: { x: 80, y: 20, width: 20.0000000001, height: 20 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: 0, y: 0 },
    containerWidth: 100,
    containerHeight: 100,
    previewScale: 1,
    directSiblings: [],
  });
  assert.ok(floatOvershoot.position.x >= 0);
  assert.ok(floatOvershoot.position.x <= 100 - 20.0000000001);

  const widerThanContainer = snap({
    selectionBounds: { x: 0, y: 0, width: 120, height: 110 },
    selectedNodeIds: ["moving"],
    requestedDelta: { x: 40, y: 40 },
    containerWidth: 100,
    containerHeight: 100,
    previewScale: 1,
    directSiblings: [],
  });
  assert.deepEqual(widerThanContainer.position, { x: 0, y: 0 });
});
