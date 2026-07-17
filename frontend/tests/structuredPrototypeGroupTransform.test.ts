import assert from "node:assert/strict";
import test from "node:test";

import {
  resolveStructuredPrototypeGroupAlignment,
  resolveStructuredPrototypeGroupDistribution,
  resolveStructuredPrototypeGroupMove,
  resolveStructuredPrototypeGroupResize,
  resolveStructuredPrototypeGroupResizeSizeLimits,
  resolveStructuredPrototypeGroupTransformBounds,
  resolveStructuredPrototypeSelectionNudge,
  type StructuredPrototypeGroupTransformItem,
} from "../src/features/prototype/structured/structuredPrototypeGroupTransform";
import {
  canonicalStructuredPrototypeFreeformValue,
  type StructuredPrototypeResizeDirection,
} from "../src/features/prototype/structured/structuredPrototypeFreeformGeometry";

const GROUP_ITEMS: StructuredPrototypeGroupTransformItem[] = [
  { nodeId: "first", x: 100, y: 100, width: 80, height: 40 },
  { nodeId: "second", x: 220, y: 130, width: 80, height: 70 },
];

function boundsOf(items: readonly StructuredPrototypeGroupTransformItem[]) {
  return resolveStructuredPrototypeGroupTransformBounds(items);
}

test("group bounds cover every selected item without changing the input order", () => {
  const items = [
    { nodeId: "later", x: 130, y: 40, width: 25, height: 20 },
    { nodeId: "first", x: 20, y: 80, width: 50, height: 40 },
    { nodeId: "lowest", x: 90, y: 10, width: 20, height: 30 },
  ];

  assert.deepEqual(boundsOf(items), { x: 20, y: 10, width: 135, height: 110 });
  assert.deepEqual(
    items.map((item) => item.nodeId),
    ["later", "first", "lowest"],
  );
});

test("group move converts the client delta once, clamps the union, and preserves offsets", () => {
  const items = [
    { nodeId: "first", x: 10, y: 20, width: 40, height: 20 },
    { nodeId: "second", x: 70, y: 50, width: 30, height: 30 },
  ];
  const moved = resolveStructuredPrototypeGroupMove({
    items,
    startClientX: 0,
    startClientY: 0,
    clientX: 400,
    clientY: -100,
    previewScale: 2,
    containerWidth: 120,
    containerHeight: 100,
  });

  assert.deepEqual(moved, [
    { nodeId: "first", x: 30, y: 0, width: 40, height: 20 },
    { nodeId: "second", x: 90, y: 30, width: 30, height: 30 },
  ]);
  assert.deepEqual(items, [
    { nodeId: "first", x: 10, y: 20, width: 40, height: 20 },
    { nodeId: "second", x: 70, y: 50, width: 30, height: 30 },
  ]);
});

test("keyboard nudge moves single and grouped selections as one clamped frame", () => {
  assert.deepEqual(
    resolveStructuredPrototypeSelectionNudge({
      items: [{ nodeId: "single", x: 2, y: 3, width: 20, height: 10 }],
      deltaX: -10,
      deltaY: 7,
      containerWidth: 100,
      containerHeight: 80,
    }),
    [{ nodeId: "single", x: 0, y: 10, width: 20, height: 10 }],
  );

  const grouped = resolveStructuredPrototypeSelectionNudge({
    items: [
      { nodeId: "first", x: 10, y: 20, width: 30, height: 20 },
      { nodeId: "second", x: 60, y: 40, width: 20, height: 30 },
    ],
    deltaX: 50,
    deltaY: 50,
    containerWidth: 100,
    containerHeight: 90,
  });
  assert.deepEqual(grouped, [
    { nodeId: "first", x: 30, y: 40, width: 30, height: 20 },
    { nodeId: "second", x: 80, y: 60, width: 20, height: 30 },
  ]);
});

test("group resize supports every handle direction and maps each item proportionally", () => {
  const expectedBounds: {
    direction: StructuredPrototypeResizeDirection;
    bounds: { x: number; y: number; width: number; height: number };
  }[] = [
    { direction: "north", bounds: { x: 100, y: 110, width: 200, height: 90 } },
    { direction: "northeast", bounds: { x: 100, y: 110, width: 220, height: 90 } },
    { direction: "east", bounds: { x: 100, y: 100, width: 220, height: 100 } },
    { direction: "southeast", bounds: { x: 100, y: 100, width: 220, height: 110 } },
    { direction: "south", bounds: { x: 100, y: 100, width: 200, height: 110 } },
    { direction: "southwest", bounds: { x: 120, y: 100, width: 180, height: 110 } },
    { direction: "west", bounds: { x: 120, y: 100, width: 180, height: 100 } },
    { direction: "northwest", bounds: { x: 120, y: 110, width: 180, height: 90 } },
  ];

  for (const { direction, bounds } of expectedBounds) {
    const resized = resolveStructuredPrototypeGroupResize({
      items: GROUP_ITEMS,
      startClientX: 0,
      startClientY: 0,
      clientX: 20,
      clientY: 10,
      previewScale: 1,
      direction,
      lockAspectRatio: false,
      resizeFromCenter: false,
      containerWidth: 1_000,
      containerHeight: 1_000,
    });
    assert.deepEqual(boundsOf(resized), bounds);
  }

  const southeast = resolveStructuredPrototypeGroupResize({
    items: GROUP_ITEMS,
    startClientX: 0,
    startClientY: 0,
    clientX: 20,
    clientY: 10,
    previewScale: 1,
    direction: "southeast",
    lockAspectRatio: false,
    resizeFromCenter: false,
    containerWidth: 1_000,
    containerHeight: 1_000,
  });
  assert.deepEqual(southeast[0], {
    nodeId: "first",
    x: 100,
    y: 100,
    width: 88,
    height: 44,
  });
  assert.deepEqual(southeast[1], {
    nodeId: "second",
    x: 232,
    y: 133,
    width: 88,
    height: 77,
  });
});

test("group resize preserves the group aspect ratio with Shift and center with Alt", () => {
  const shifted = resolveStructuredPrototypeGroupResize({
    items: GROUP_ITEMS,
    startClientX: 0,
    startClientY: 0,
    clientX: 80,
    clientY: 5,
    previewScale: 1,
    direction: "southeast",
    lockAspectRatio: true,
    resizeFromCenter: false,
    containerWidth: 1_000,
    containerHeight: 1_000,
  });
  assert.deepEqual(boundsOf(shifted), { x: 100, y: 100, width: 280, height: 140 });

  const centered = resolveStructuredPrototypeGroupResize({
    items: GROUP_ITEMS,
    startClientX: 0,
    startClientY: 0,
    clientX: 50,
    clientY: 30,
    previewScale: 1,
    direction: "southeast",
    lockAspectRatio: false,
    resizeFromCenter: true,
    containerWidth: 1_000,
    containerHeight: 1_000,
  });
  assert.deepEqual(boundsOf(centered), { x: 50, y: 70, width: 300, height: 160 });
});

test("group resize clamps the complete group frame to the container", () => {
  const resized = resolveStructuredPrototypeGroupResize({
    items: [
      { nodeId: "first", x: 80, y: 60, width: 40, height: 20 },
      { nodeId: "second", x: 140, y: 90, width: 40, height: 50 },
    ],
    startClientX: 0,
    startClientY: 0,
    clientX: 100,
    clientY: 100,
    previewScale: 1,
    direction: "southeast",
    lockAspectRatio: false,
    resizeFromCenter: false,
    containerWidth: 200,
    containerHeight: 160,
  });

  assert.deepEqual(boundsOf(resized), { x: 80, y: 60, width: 120, height: 100 });
  for (const item of resized) {
    assert.ok(item.x >= 0 && item.y >= 0);
    assert.ok(item.x + item.width <= 200);
    assert.ok(item.y + item.height <= 160);
  }
});

test("group resize preserves every child's minimum editable dimensions", () => {
  const resized = resolveStructuredPrototypeGroupResize({
    items: GROUP_ITEMS,
    startClientX: 0,
    startClientY: 0,
    clientX: -1_000,
    clientY: -1_000,
    previewScale: 1,
    direction: "southeast",
    lockAspectRatio: false,
    resizeFromCenter: false,
    containerWidth: 1_000,
    containerHeight: 1_000,
  });

  for (const item of resized) {
    assert.ok(item.width >= 48);
    assert.ok(item.height >= 36);
  }
});

test("group resize recovers existing overflow without increasing it", () => {
  const overflowing = [
    { nodeId: "first", x: 60, y: 100, width: 80, height: 40 },
    { nodeId: "second", x: 160, y: 130, width: 80, height: 70 },
  ];
  assert.deepEqual(
    resolveStructuredPrototypeGroupResizeSizeLimits({
      items: overflowing,
      direction: "east",
      lockAspectRatio: false,
      resizeFromCenter: false,
    }),
    {
      minimumSize: { width: 108, height: 90 },
      maximumSize: { width: 9216, height: 5851.428571428572 },
    },
  );

  const recovered = resolveStructuredPrototypeGroupResize({
    items: overflowing,
    startClientX: 0,
    startClientY: 0,
    clientX: -40,
    clientY: 0,
    previewScale: 1,
    direction: "east",
    lockAspectRatio: false,
    resizeFromCenter: false,
    containerWidth: 200,
    containerHeight: 200,
  });
  assert.deepEqual(boundsOf(recovered), { x: 60, y: 100, width: 140, height: 100 });

  const cannotWorsen = resolveStructuredPrototypeGroupResize({
    items: overflowing,
    startClientX: 0,
    startClientY: 0,
    clientX: 40,
    clientY: 0,
    previewScale: 1,
    direction: "east",
    lockAspectRatio: false,
    resizeFromCenter: false,
    containerWidth: 200,
    containerHeight: 200,
  });
  assert.deepEqual(boundsOf(cannotWorsen), { x: 60, y: 100, width: 180, height: 100 });
});

test("group resize keeps every proportional child frame within the Freeform format cap", () => {
  const items = [
    { nodeId: "left", x: 4090, y: 20, width: 100, height: 48 },
    { nodeId: "right", x: 4095, y: 80, width: 80, height: 48 },
  ];
  const resized = resolveStructuredPrototypeGroupResize({
    items,
    startClientX: 0,
    startClientY: 0,
    clientX: 60,
    clientY: 0,
    previewScale: 1,
    direction: "west",
    lockAspectRatio: false,
    resizeFromCenter: false,
    containerWidth: 4096,
    containerHeight: 200,
  });

  assert.equal(resized[0]?.x, 4091.0526315789475);
  assert.equal(resized[1]?.x, 4096);
  for (const item of resized) {
    canonicalStructuredPrototypeFreeformValue(item.x);
    canonicalStructuredPrototypeFreeformValue(item.y);
    canonicalStructuredPrototypeFreeformValue(item.width);
    canonicalStructuredPrototypeFreeformValue(item.height);
  }
});

test("group resize preserves a legal union wider than one canonical child field", () => {
  const items = [
    { nodeId: "left", x: 0, y: 20, width: 4096, height: 48 },
    { nodeId: "right", x: 4096, y: 80, width: 4096, height: 48 },
  ];
  const resized = resolveStructuredPrototypeGroupResize({
    items,
    startClientX: 0,
    startClientY: 0,
    clientX: 200,
    clientY: 0,
    previewScale: 1,
    direction: "west",
    lockAspectRatio: false,
    resizeFromCenter: false,
    containerWidth: 4096,
    containerHeight: 200,
  });

  assert.deepEqual(resized, items);
  assert.deepEqual(boundsOf(resized), { x: 0, y: 20, width: 8192, height: 108 });
});

test("group resize normalizes constrained proportional tails before persistence", () => {
  const resized = resolveStructuredPrototypeGroupResize({
    items: [
      { nodeId: "0", x: 3459.2042, y: 1241.3955, width: 1195.9556, height: 2896.094 },
      { nodeId: "1", x: 2296.9745, y: 2126.6809, width: 3846.5473, height: 1444.4358 },
    ],
    startClientX: 0,
    startClientY: 0,
    clientX: -4227.244,
    clientY: -8538.7503,
    previewScale: 1.8085,
    direction: "southwest",
    lockAspectRatio: true,
    resizeFromCenter: false,
    containerWidth: 2189,
    containerHeight: 1545,
  });

  assert.equal(resized[0]?.x, 4096);
  for (const item of resized) {
    canonicalStructuredPrototypeFreeformValue(item.x);
    canonicalStructuredPrototypeFreeformValue(item.y);
    canonicalStructuredPrototypeFreeformValue(item.width);
    canonicalStructuredPrototypeFreeformValue(item.height);
  }
});

test("group alignment returns deterministic frames for every supported alignment", () => {
  const items = [
    { nodeId: "first", x: 10, y: 20, width: 20, height: 10 },
    { nodeId: "second", x: 50, y: 40, width: 10, height: 20 },
    { nodeId: "third", x: 80, y: 10, width: 15, height: 15 },
  ];

  assert.deepEqual(
    resolveStructuredPrototypeGroupAlignment(items, "left").map((item) => item.x),
    [10, 10, 10],
  );
  assert.deepEqual(
    resolveStructuredPrototypeGroupAlignment(items, "center").map((item) => item.x),
    [42.5, 47.5, 45],
  );
  assert.deepEqual(
    resolveStructuredPrototypeGroupAlignment(items, "right").map((item) => item.x),
    [75, 85, 80],
  );
  assert.deepEqual(
    resolveStructuredPrototypeGroupAlignment(items, "top").map((item) => item.y),
    [10, 10, 10],
  );
  assert.deepEqual(
    resolveStructuredPrototypeGroupAlignment(items, "middle").map((item) => item.y),
    [30, 25, 27.5],
  );
  assert.deepEqual(
    resolveStructuredPrototypeGroupAlignment(items, "bottom").map((item) => item.y),
    [50, 40, 45],
  );
});

test("group distribution orders by axis, breaks ties by nodeId, and keeps caller item order", () => {
  const horizontal = [
    { nodeId: "third", x: 90, y: 20, width: 10, height: 10 },
    { nodeId: "first", x: 10, y: 20, width: 20, height: 10 },
    { nodeId: "second", x: 45, y: 20, width: 15, height: 10 },
  ];
  assert.deepEqual(
    resolveStructuredPrototypeGroupDistribution(horizontal, "horizontal").map((item) => [
      item.nodeId,
      item.x,
    ]),
    [
      ["third", 90],
      ["first", 10],
      ["second", 52.5],
    ],
  );

  const vertical = [
    { nodeId: "second", x: 10, y: 50, width: 10, height: 20 },
    { nodeId: "first", x: 10, y: 10, width: 10, height: 10 },
    { nodeId: "third", x: 10, y: 90, width: 10, height: 10 },
  ];
  assert.deepEqual(
    resolveStructuredPrototypeGroupDistribution(vertical, "vertical").map((item) => [
      item.nodeId,
      item.y,
    ]),
    [
      ["second", 45],
      ["first", 10],
      ["third", 90],
    ],
  );

  const tied = [
    { nodeId: "later", x: 10, y: 0, width: 10, height: 10 },
    { nodeId: "first", x: 10, y: 0, width: 10, height: 10 },
    { nodeId: "last", x: 90, y: 0, width: 10, height: 10 },
  ];
  assert.deepEqual(
    resolveStructuredPrototypeGroupDistribution(tied, "horizontal").map((item) => [
      item.nodeId,
      item.x,
    ]),
    [
      ["later", 50],
      ["first", 10],
      ["last", 90],
    ],
  );
});

test("group transforms reject invalid selection geometry and out-of-bounds frames", () => {
  assert.throws(
    () =>
      resolveStructuredPrototypeGroupTransformBounds([
        { nodeId: "only", x: 0, y: 0, width: 1, height: 1 },
      ]),
    /requires 2 to 100 items/,
  );
  assert.throws(
    () =>
      resolveStructuredPrototypeGroupTransformBounds([
        { nodeId: "same", x: 0, y: 0, width: 10, height: 10 },
        { nodeId: "same", x: 20, y: 0, width: 10, height: 10 },
      ]),
    /duplicated/,
  );
  assert.throws(
    () =>
      resolveStructuredPrototypeGroupTransformBounds([
        { nodeId: "bad-width", x: 0, y: 0, width: 0, height: 10 },
        { nodeId: "valid", x: 20, y: 0, width: 10, height: 10 },
      ]),
    /must be positive/,
  );
  assert.throws(
    () =>
      resolveStructuredPrototypeGroupTransformBounds([
        { nodeId: "bad-number", x: Number.NaN, y: 0, width: 10, height: 10 },
        { nodeId: "valid", x: 20, y: 0, width: 10, height: 10 },
      ]),
    /must be finite/,
  );
  assert.throws(
    () =>
      resolveStructuredPrototypeGroupMove({
        items: [
          { nodeId: "outside", x: 80, y: 0, width: 30, height: 10 },
          { nodeId: "inside", x: 0, y: 20, width: 10, height: 10 },
        ],
        startClientX: 0,
        startClientY: 0,
        clientX: 0,
        clientY: 0,
        previewScale: 1,
        containerWidth: 100,
        containerHeight: 100,
      }),
    /outside its container/,
  );
  assert.throws(
    () =>
      resolveStructuredPrototypeGroupTransformBounds(
        Array.from({ length: 101 }, (_, index) => ({
          nodeId: `node-${index}`,
          x: index * 2,
          y: 0,
          width: 1,
          height: 1,
        })),
      ),
    /requires 2 to 100 items/,
  );
});
