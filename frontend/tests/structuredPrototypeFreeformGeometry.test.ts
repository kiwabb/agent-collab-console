import assert from "node:assert/strict";
import test from "node:test";

import {
  STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE,
  canonicalStructuredPrototypeFreeformValue,
  normalizeStructuredPrototypeFreeformValue,
  resolveStructuredPrototypeFreeformMove,
  resolveStructuredPrototypeFreeformPointerPlacement,
  resolveStructuredPrototypeFreeformResize,
  resolveStructuredPrototypeResizeBounds,
  structuredPrototypeCanStartTransform,
  structuredPrototypeTransformPassedActivationThreshold,
} from "../src/features/prototype/structured/structuredPrototypeFreeformGeometry";

test("Freeform values use canonical four-decimal strings", () => {
  assert.equal(canonicalStructuredPrototypeFreeformValue(12.345678), "12.3457");
  assert.equal(canonicalStructuredPrototypeFreeformValue(100 + 1 / 3), "100.3333");
  assert.equal(canonicalStructuredPrototypeFreeformValue(0.0001), "0.0001");
  assert.equal(canonicalStructuredPrototypeFreeformValue(0), "0");
  assert.throws(() => canonicalStructuredPrototypeFreeformValue(-1), /within the canvas bounds/);
  assert.equal(normalizeStructuredPrototypeFreeformValue(-1e-12), 0);
  assert.equal(
    normalizeStructuredPrototypeFreeformValue(STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE + 1e-12),
    STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE,
  );
});

test("Freeform move converts client deltas once and clamps the complete node to its canvas", () => {
  assert.deepEqual(
    resolveStructuredPrototypeFreeformMove({
      startX: 100,
      startY: 80,
      startClientX: 10,
      startClientY: 20,
      clientX: 210,
      clientY: 120,
      previewScale: 2,
      nodeWidth: 120,
      nodeHeight: 80,
      containerWidth: 300,
      containerHeight: 200,
    }),
    { x: 180, y: 120 },
  );
});

test("Freeform move preserves continuous canvas coordinates before canonical persistence", () => {
  assert.deepEqual(
    resolveStructuredPrototypeFreeformMove({
      startX: 100.25,
      startY: 80.75,
      startClientX: 10,
      startClientY: 20,
      clientX: 11,
      clientY: 19,
      previewScale: 2,
      nodeWidth: 120,
      nodeHeight: 80,
      containerWidth: 300,
      containerHeight: 200,
    }),
    { x: 100.75, y: 80.25 },
  );
});

test("Freeform pointer placement converts the scaled, bordered canvas origin once", () => {
  assert.deepEqual(
    resolveStructuredPrototypeFreeformPointerPlacement({
      pointerClientX: 204,
      pointerClientY: 153,
      containerRect: { left: 100, top: 50 },
      containerClientLeft: 2,
      containerClientTop: 3,
      previewScale: 2,
      nodeWidth: 80,
      nodeHeight: 40,
      containerWidth: 300,
      containerHeight: 200,
    }),
    { x: 50, y: 48.5 },
  );
});

test("Freeform pointer placement clamps the requested top-left to keep the node in bounds", () => {
  assert.deepEqual(
    resolveStructuredPrototypeFreeformPointerPlacement({
      pointerClientX: 1000,
      pointerClientY: -100,
      containerRect: { left: 100, top: 100 },
      containerClientLeft: 0,
      containerClientTop: 0,
      previewScale: 1,
      nodeWidth: 80,
      nodeHeight: 40,
      containerWidth: 300,
      containerHeight: 200,
    }),
    { x: 220, y: 0 },
  );
});

test("Freeform pointer placement uses each nested container's own client origin", () => {
  const pointer = { pointerClientX: 360, pointerClientY: 260 };
  assert.deepEqual(
    resolveStructuredPrototypeFreeformPointerPlacement({
      ...pointer,
      containerRect: { left: 40, top: 20 },
      containerClientLeft: 0,
      containerClientTop: 0,
      previewScale: 0.5,
      nodeWidth: 80,
      nodeHeight: 40,
      containerWidth: 1000,
      containerHeight: 800,
    }),
    { x: 640, y: 480 },
  );
  assert.deepEqual(
    resolveStructuredPrototypeFreeformPointerPlacement({
      ...pointer,
      containerRect: { left: 260, top: 160 },
      containerClientLeft: 2,
      containerClientTop: 2,
      previewScale: 0.5,
      nodeWidth: 80,
      nodeHeight: 40,
      containerWidth: 400,
      containerHeight: 300,
    }),
    { x: 198, y: 198 },
  );
});

test("Freeform pointer placement rejects unavailable geometry", () => {
  assert.throws(
    () =>
      resolveStructuredPrototypeFreeformPointerPlacement({
        pointerClientX: 0,
        pointerClientY: 0,
        containerRect: { left: 0, top: 0 },
        containerClientLeft: 0,
        containerClientTop: 0,
        previewScale: 0,
        nodeWidth: 80,
        nodeHeight: 40,
        containerWidth: 300,
        containerHeight: 200,
      }),
    /scale must be positive/,
  );
});

test("west and north resize keep the opposite edge fixed", () => {
  assert.deepEqual(
    resolveStructuredPrototypeFreeformResize({
      x: 100,
      y: 80,
      width: 200,
      height: 120,
      startClientX: 0,
      startClientY: 0,
      clientX: 40,
      clientY: 20,
      previewScale: 1,
      direction: "northwest",
      lockAspectRatio: false,
      resizeFromCenter: false,
      containerWidth: 800,
      containerHeight: 600,
    }),
    { x: 140, y: 100, width: 160, height: 100 },
  );
});

test("Alt resize keeps the center fixed", () => {
  assert.deepEqual(
    resolveStructuredPrototypeFreeformResize({
      x: 100,
      y: 80,
      width: 200,
      height: 120,
      startClientX: 0,
      startClientY: 0,
      clientX: 50,
      clientY: 30,
      previewScale: 1,
      direction: "southeast",
      lockAspectRatio: false,
      resizeFromCenter: true,
      containerWidth: 800,
      containerHeight: 600,
    }),
    { x: 50, y: 50, width: 300, height: 180 },
  );
});

test("Shift resize preserves the source aspect ratio", () => {
  const frame = resolveStructuredPrototypeFreeformResize({
    x: 100,
    y: 80,
    width: 200,
    height: 100,
    startClientX: 0,
    startClientY: 0,
    clientX: 80,
    clientY: 5,
    previewScale: 1,
    direction: "southeast",
    lockAspectRatio: true,
    resizeFromCenter: false,
    containerWidth: 800,
    containerHeight: 600,
  });
  assert.deepEqual(frame, { x: 100, y: 80, width: 280, height: 140 });
});

test("shared resize bounds preserve but never worsen existing overflow", () => {
  const base = {
    startBounds: { x: 50, y: 40, width: 80, height: 80 },
    direction: "southeast" as const,
    lockAspectRatio: false,
    resizeFromCenter: false,
    aspectDriver: "auto" as const,
    minimumSize: { width: 48, height: 36 },
    maximumSize: {
      width: STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE,
      height: STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE,
    },
    containerWidth: 100,
    containerHeight: 100,
    dimensionPrecision: "continuous" as const,
  };
  assert.deepEqual(
    resolveStructuredPrototypeResizeBounds({
      ...base,
      requestedCanvasDelta: { x: 0, y: 0 },
    }),
    base.startBounds,
  );
  assert.deepEqual(
    resolveStructuredPrototypeResizeBounds({
      ...base,
      requestedCanvasDelta: { x: 20, y: 20 },
    }),
    base.startBounds,
  );
  assert.deepEqual(
    resolveStructuredPrototypeResizeBounds({
      ...base,
      requestedCanvasDelta: { x: -30, y: -20 },
    }),
    { x: 50, y: 40, width: 50, height: 60 },
  );
});

test("shared resize bounds keep every persisted field within the Freeform format cap", () => {
  const base = {
    lockAspectRatio: false,
    resizeFromCenter: false,
    aspectDriver: "auto" as const,
    minimumSize: { width: 48, height: 36 },
    maximumSize: {
      width: STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE,
      height: STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE,
    },
    containerWidth: STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE,
    containerHeight: STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE,
    dimensionPrecision: "continuous" as const,
  };
  assert.deepEqual(
    resolveStructuredPrototypeResizeBounds({
      ...base,
      startBounds: { x: 4090, y: 10, width: 100, height: 50 },
      requestedCanvasDelta: { x: 60, y: 0 },
      direction: "west",
    }),
    { x: 4096, y: 10, width: 94, height: 50 },
  );
  assert.deepEqual(
    resolveStructuredPrototypeResizeBounds({
      ...base,
      startBounds: { x: 10, y: 4090, width: 50, height: 100 },
      requestedCanvasDelta: { x: 0, y: 60 },
      direction: "north",
    }),
    { x: 10, y: 4096, width: 50, height: 94 },
  );
  assert.deepEqual(
    resolveStructuredPrototypeResizeBounds({
      ...base,
      startBounds: { x: 100, y: 10, width: 4096, height: 50 },
      requestedCanvasDelta: { x: -100, y: 0 },
      direction: "west",
    }),
    { x: 100, y: 10, width: 4096, height: 50 },
  );
  assert.deepEqual(
    resolveStructuredPrototypeResizeBounds({
      ...base,
      startBounds: { x: 4090, y: 10, width: 100, height: 50 },
      requestedCanvasDelta: { x: -40, y: 0 },
      direction: "east",
      resizeFromCenter: true,
    }),
    { x: 4096, y: 10, width: 88, height: 50 },
  );
});

test("shared resize bounds do not enlarge a legacy frame below today's minimum", () => {
  assert.deepEqual(
    resolveStructuredPrototypeResizeBounds({
      startBounds: { x: 20, y: 20, width: 30, height: 20 },
      requestedCanvasDelta: { x: 0, y: 0 },
      direction: "southeast",
      lockAspectRatio: false,
      resizeFromCenter: false,
      aspectDriver: "auto",
      minimumSize: { width: 48, height: 36 },
      maximumSize: {
        width: STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE,
        height: STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE,
      },
      containerWidth: 100,
      containerHeight: 100,
      dimensionPrecision: "continuous",
    }),
    { x: 20, y: 20, width: 30, height: 20 },
  );
});

test("aspect resize reconciles floating-point envelope equality for legacy frames", () => {
  const startBounds = { x: 100, y: 0.1, width: 1, height: 64 };
  assert.deepEqual(
    resolveStructuredPrototypeResizeBounds({
      startBounds,
      requestedCanvasDelta: { x: 0, y: 0 },
      direction: "southwest",
      lockAspectRatio: true,
      resizeFromCenter: false,
      aspectDriver: "auto",
      minimumSize: { width: 48, height: 36 },
      maximumSize: {
        width: STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE,
        height: STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE,
      },
      containerWidth: 10,
      containerHeight: 10,
      dimensionPrecision: "continuous",
    }),
    startBounds,
  );
});

test("constrained Shift resize removes derived maximum epsilon before positioning", () => {
  const result = resolveStructuredPrototypeResizeBounds({
    startBounds: { x: 1631.4923, y: 472.6689, width: 2249.3507, height: 74.8019 },
    requestedCanvasDelta: { x: -9250.6264, y: 5725.8994 },
    direction: "southwest",
    lockAspectRatio: true,
    resizeFromCenter: false,
    aspectDriver: "auto",
    minimumSize: { width: 48, height: 36 },
    maximumSize: {
      width: STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE,
      height: STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE,
    },
    containerWidth: 3623,
    containerHeight: 2876,
    dimensionPrecision: "continuous",
  });

  for (const value of [result.x, result.y, result.width, result.height]) {
    canonicalStructuredPrototypeFreeformValue(value);
  }
  assert.ok(result.x >= 0);
  assert.ok(result.y >= 0);
});

test("transform gestures activate at four client pixels", () => {
  assert.equal(structuredPrototypeTransformPassedActivationThreshold(0, 0, 3, 0), false);
  assert.equal(structuredPrototypeTransformPassedActivationThreshold(0, 0, 4, 0), true);
});

test("transform gestures start only from the primary pointer's left button", () => {
  assert.equal(structuredPrototypeCanStartTransform(0, true), true);
  assert.equal(structuredPrototypeCanStartTransform(1, true), false);
  assert.equal(structuredPrototypeCanStartTransform(2, true), false);
  assert.equal(structuredPrototypeCanStartTransform(0, false), false);
});
