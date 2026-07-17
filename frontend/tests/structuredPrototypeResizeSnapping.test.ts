import assert from "node:assert/strict";
import test from "node:test";

import {
  projectStructuredPrototypeGroupResizeItemsToBounds,
  resolveStructuredPrototypeGroupResizeSizeLimits,
  resolveStructuredPrototypeGroupTransformBounds,
  type StructuredPrototypeGroupTransformItem,
} from "../src/features/prototype/structured/structuredPrototypeGroupTransform";
import type { StructuredPrototypeResizeDirection } from "../src/features/prototype/structured/structuredPrototypeFreeformGeometry";
import {
  resolveStructuredPrototypeFreeformResizeSnap,
  type StructuredPrototypeFreeformResizeSnapInput,
} from "../src/features/prototype/structured/structuredPrototypeResizeSnapping";
import type { StructuredPrototypeFreeformSnapGuide } from "../src/features/prototype/structured/structuredPrototypeSnapping";

const BASE_INPUT: StructuredPrototypeFreeformResizeSnapInput = {
  startBounds: { x: 100, y: 100, width: 100, height: 80 },
  requestedCanvasDelta: { x: 0, y: 0 },
  direction: "east",
  lockAspectRatio: false,
  resizeFromCenter: false,
  bypassSnapping: false,
  minimumSize: { width: 48, height: 36 },
  maximumSize: { width: 4096, height: 4096 },
  selectedNodeIds: ["moving"],
  directSiblings: [],
  containerWidth: 500,
  containerHeight: 500,
  previewScale: 1,
};

function snap(overrides: Partial<StructuredPrototypeFreeformResizeSnapInput> = {}) {
  return resolveStructuredPrototypeFreeformResizeSnap({ ...BASE_INPUT, ...overrides });
}

function guideAt(guides: readonly StructuredPrototypeFreeformSnapGuide[], index: number) {
  const guide = guides[index];
  if (guide === undefined) throw new Error(`expected resize snap guide at index ${index}`);
  return guide;
}

function assertApproximately(actual: number, expected: number): void {
  assert.ok(Math.abs(actual - expected) < 1e-9, `expected ${actual} to equal ${expected}`);
}

test("snaps only the active edges for all eight resize handles", () => {
  const sibling = { nodeId: "target", x: 55, y: 65, width: 190, height: 150 };
  const cases: readonly {
    direction: StructuredPrototypeResizeDirection;
    delta: { x: number; y: number };
    bounds: { x: number; y: number; width: number; height: number };
    axes: readonly ("x" | "y")[];
  }[] = [
    {
      direction: "north",
      delta: { x: 0, y: -31 },
      bounds: { x: 100, y: 65, width: 100, height: 115 },
      axes: ["y"],
    },
    {
      direction: "northeast",
      delta: { x: 41, y: -31 },
      bounds: { x: 100, y: 65, width: 145, height: 115 },
      axes: ["x", "y"],
    },
    {
      direction: "east",
      delta: { x: 41, y: 0 },
      bounds: { x: 100, y: 100, width: 145, height: 80 },
      axes: ["x"],
    },
    {
      direction: "southeast",
      delta: { x: 41, y: 31 },
      bounds: { x: 100, y: 100, width: 145, height: 115 },
      axes: ["x", "y"],
    },
    {
      direction: "south",
      delta: { x: 0, y: 31 },
      bounds: { x: 100, y: 100, width: 100, height: 115 },
      axes: ["y"],
    },
    {
      direction: "southwest",
      delta: { x: -41, y: 31 },
      bounds: { x: 55, y: 100, width: 145, height: 115 },
      axes: ["x", "y"],
    },
    {
      direction: "west",
      delta: { x: -41, y: 0 },
      bounds: { x: 55, y: 100, width: 145, height: 80 },
      axes: ["x"],
    },
    {
      direction: "northwest",
      delta: { x: -41, y: -31 },
      bounds: { x: 55, y: 65, width: 145, height: 115 },
      axes: ["x", "y"],
    },
  ];

  for (const entry of cases) {
    const result = snap({
      direction: entry.direction,
      requestedCanvasDelta: entry.delta,
      directSiblings: [sibling],
    });
    assert.deepEqual(result.bounds, entry.bounds, entry.direction);
    assert.deepEqual(
      result.guides.map((guide) => guide.axis),
      entry.axes,
      entry.direction,
    );
  }
});

test("uses container and sibling edge or center targets with complete guide metadata", () => {
  const containerCenter = snap({ requestedCanvasDelta: { x: 46, y: 0 } });
  assert.deepEqual(containerCenter.bounds, { x: 100, y: 100, width: 150, height: 80 });
  assert.deepEqual(containerCenter.guides, [
    {
      axis: "x",
      coordinate: 250,
      movingAnchor: "right",
      targetAnchor: "center",
      targetKind: "container",
      targetNodeId: null,
    },
  ]);

  const siblingCenter = snap({
    requestedCanvasDelta: { x: 86, y: 0 },
    directSiblings: [{ nodeId: "summary", x: 250, y: 300, width: 80, height: 40 }],
  });
  assert.deepEqual(siblingCenter.bounds, { x: 100, y: 100, width: 190, height: 80 });
  assert.deepEqual(siblingCenter.guides, [
    {
      axis: "x",
      coordinate: 290,
      movingAnchor: "right",
      targetAnchor: "center",
      targetKind: "sibling",
      targetNodeId: "summary",
    },
  ]);
});

test("keeps the six-client-pixel threshold stable across zoom and accepts equality", () => {
  const target = { nodeId: "target", x: 208, y: 300, width: 100, height: 40 };
  const common = {
    requestedCanvasDelta: { x: 4, y: 0 },
    directSiblings: [target],
  };

  const zoomedIn = snap({ ...common, previewScale: 2 });
  assert.deepEqual(zoomedIn.bounds, { x: 100, y: 100, width: 104, height: 80 });
  assert.equal(zoomedIn.guides.length, 0);

  const exactThreshold = snap({ ...common, previewScale: 1.5 });
  assert.deepEqual(exactThreshold.bounds, { x: 100, y: 100, width: 108, height: 80 });
  assert.equal(guideAt(exactThreshold.guides, 0).targetNodeId, "target");

  const zoomedOut = snap({ ...common, previewScale: 0.5 });
  assert.deepEqual(zoomedOut.bounds, { x: 100, y: 100, width: 108, height: 80 });
});

test("Ctrl or Meta bypass returns constrained geometry without guides", () => {
  const result = snap({
    requestedCanvasDelta: { x: 4, y: 0 },
    bypassSnapping: true,
    directSiblings: [{ nodeId: "target", x: 208, y: 300, width: 100, height: 40 }],
  });
  assert.deepEqual(result.bounds, { x: 100, y: 100, width: 104, height: 80 });
  assert.deepEqual(result.guides, []);
});

test("Shift preserves aspect ratio and never snaps a side handle's derived axis", () => {
  const result = snap({
    startBounds: { x: 100, y: 100, width: 100, height: 50 },
    requestedCanvasDelta: { x: 46, y: 0 },
    direction: "east",
    lockAspectRatio: true,
    directSiblings: [{ nodeId: "vertical-target", x: 400, y: 62.5, width: 40, height: 100 }],
  });

  assert.deepEqual(result.bounds, { x: 100, y: 87.5, width: 150, height: 75 });
  assert.equal(result.bounds.width / result.bounds.height, 2);
  assert.deepEqual(
    result.guides.map((guide) => guide.axis),
    ["x"],
  );
});

test("Shift corner snapping chooses the closest scale driver and exposes only exact derived guides", () => {
  const closestVertical = snap({
    startBounds: { x: 100, y: 100, width: 100, height: 50 },
    requestedCanvasDelta: { x: 46, y: 21 },
    direction: "southeast",
    lockAspectRatio: true,
    directSiblings: [{ nodeId: "vertical-target", x: 400, y: 175, width: 40, height: 40 }],
  });
  assert.deepEqual(closestVertical.bounds, { x: 100, y: 100, width: 150, height: 75 });
  assert.deepEqual(
    closestVertical.guides.map((guide) => [guide.axis, guide.coordinate]),
    [
      ["x", 250],
      ["y", 175],
    ],
  );

  const equalDistancePrefersRawHorizontalDriver = snap({
    startBounds: { x: 100, y: 100, width: 100, height: 50 },
    requestedCanvasDelta: { x: 46, y: 21 },
    direction: "southeast",
    lockAspectRatio: true,
    directSiblings: [{ nodeId: "incompatible-y", x: 400, y: 167, width: 40, height: 40 }],
  });
  assert.deepEqual(equalDistancePrefersRawHorizontalDriver.bounds, {
    x: 100,
    y: 100,
    width: 150,
    height: 75,
  });
  assert.deepEqual(
    equalDistancePrefersRawHorizontalDriver.guides.map((guide) => guide.axis),
    ["x"],
  );
});

test("Alt keeps the center fixed, including combined Shift and Alt", () => {
  const centered = snap({
    requestedCanvasDelta: { x: 46, y: 0 },
    resizeFromCenter: true,
  });
  assert.deepEqual(centered.bounds, { x: 50, y: 100, width: 200, height: 80 });
  assert.equal(guideAt(centered.guides, 0).coordinate, 250);

  const centeredAspect = snap({
    startBounds: { x: 100, y: 100, width: 100, height: 50 },
    requestedCanvasDelta: { x: 46, y: 21 },
    direction: "southeast",
    lockAspectRatio: true,
    resizeFromCenter: true,
  });
  assert.deepEqual(centeredAspect.bounds, { x: 50, y: 75, width: 200, height: 100 });
  assert.deepEqual(
    centeredAspect.guides.map((guide) => guide.axis),
    ["x"],
  );
});

test("snaps grouped bounds before proportionally projecting children in caller order", () => {
  const items: readonly StructuredPrototypeGroupTransformItem[] = [
    { nodeId: "first", x: 100, y: 100, width: 80, height: 40 },
    { nodeId: "second", x: 220, y: 130, width: 80, height: 70 },
  ];
  const bounds = resolveStructuredPrototypeGroupTransformBounds(items);
  const sizeLimits = resolveStructuredPrototypeGroupResizeSizeLimits({
    items,
    direction: "east",
    lockAspectRatio: false,
    resizeFromCenter: false,
  });
  const result = snap({
    startBounds: bounds,
    selectedNodeIds: items.map((item) => item.nodeId),
    requestedCanvasDelta: { x: 46, y: 0 },
    minimumSize: sizeLimits.minimumSize,
    maximumSize: sizeLimits.maximumSize,
    directSiblings: [{ nodeId: "target", x: 350, y: 300, width: 80, height: 40 }],
  });
  assert.deepEqual(result.bounds, { x: 100, y: 100, width: 250, height: 100 });
  assert.deepEqual(projectStructuredPrototypeGroupResizeItemsToBounds(items, result.bounds), [
    { nodeId: "first", x: 100, y: 100, width: 100, height: 40 },
    { nodeId: "second", x: 250, y: 130, width: 100, height: 70 },
  ]);
});

test("does not jump or worsen a pre-existing overflow frame and can snap it back inside", () => {
  const overflowInput = {
    startBounds: { x: 90, y: 80, width: 30, height: 30 },
    direction: "southeast" as const,
    minimumSize: { width: 5, height: 5 },
    containerWidth: 100,
    containerHeight: 100,
  };
  const unchanged = snap({ ...overflowInput, requestedCanvasDelta: { x: 0, y: 0 } });
  assert.deepEqual(unchanged.bounds, overflowInput.startBounds);

  const recovered = snap({ ...overflowInput, requestedCanvasDelta: { x: -16, y: -6 } });
  assert.deepEqual(recovered.bounds, { x: 90, y: 80, width: 10, height: 20 });
  assert.deepEqual(
    recovered.guides.map((guide) => [guide.axis, guide.coordinate]),
    [
      ["x", 100],
      ["y", 100],
    ],
  );

  const cannotWorsen = snap({
    ...overflowInput,
    requestedCanvasDelta: { x: 4, y: 0 },
    directSiblings: [{ nodeId: "farther", x: 124, y: 10, width: 20, height: 20 }],
  });
  assert.deepEqual(cannotWorsen.bounds, overflowInput.startBounds);
  assert.equal(cannotWorsen.guides.length, 0);
});

test("rejects snap targets that violate minimum dimensions", () => {
  const result = snap({
    requestedCanvasDelta: { x: -51, y: 0 },
    directSiblings: [{ nodeId: "too-small", x: 145, y: 300, width: 100, height: 20 }],
  });
  assert.deepEqual(result.bounds, { x: 100, y: 100, width: 49, height: 80 });
  assert.equal(result.guides.length, 0);
});

test("tie breaking is independent of sibling input order", () => {
  const siblings = [
    { nodeId: "zeta", x: 155, y: 250, width: 80, height: 20 },
    { nodeId: "alpha", x: 165, y: 280, width: 80, height: 20 },
  ];
  const forward = snap({
    startBounds: { x: 100, y: 100, width: 60, height: 80 },
    directSiblings: siblings,
  });
  const reverse = snap({
    startBounds: { x: 100, y: 100, width: 60, height: 80 },
    directSiblings: [...siblings].reverse(),
  });
  assert.deepEqual(forward, reverse);
  assert.equal(guideAt(forward.guides, 0).coordinate, 155);

  const sameCoordinate = snap({
    startBounds: { x: 100, y: 100, width: 60, height: 80 },
    directSiblings: [
      { nodeId: "zeta", x: 155, y: 250, width: 80, height: 20 },
      { nodeId: "alpha", x: 155, y: 280, width: 80, height: 20 },
    ],
  });
  assert.equal(guideAt(sameCoordinate.guides, 0).targetNodeId, "alpha");
});

test("ignores selected siblings and fails fast for malformed frozen inputs", () => {
  const ignored = snap({
    requestedCanvasDelta: { x: 4, y: 0 },
    directSiblings: [{ nodeId: "moving", x: 208, y: 300, width: 100, height: 40 }],
  });
  assert.equal(ignored.guides.length, 0);

  assert.throws(() => snap({ selectedNodeIds: [] }), /at least one selected node/);
  assert.throws(
    () => snap({ selectedNodeIds: ["moving", "moving"] }),
    /selected node id is duplicated/,
  );
  assert.throws(
    () =>
      snap({
        directSiblings: [
          { nodeId: "same", x: 0, y: 0, width: 10, height: 10 },
          { nodeId: "same", x: 20, y: 0, width: 10, height: 10 },
        ],
      }),
    /sibling node id is duplicated/,
  );
  assert.throws(() => snap({ previewScale: Number.NaN }), /preview scale must be finite/);
  assert.throws(
    () => snap({ startBounds: { x: -1, y: 0, width: 10, height: 10 } }),
    /position must not be negative/,
  );
});

test("continuous snap coordinates retain exact fractional targets", () => {
  const result = snap({
    requestedCanvasDelta: { x: 117, y: 0 },
    directSiblings: [{ nodeId: "fractional", x: 321.25, y: 300, width: 20, height: 20 }],
  });
  assertApproximately(result.bounds.x + result.bounds.width, 321.25);
  assertApproximately(guideAt(result.guides, 0).coordinate, 321.25);
});
