import assert from "node:assert/strict";
import test from "node:test";

import { resolveStructuredPrototypeEffectivePreviewScale } from "../src/features/prototype/structured/StructuredPrototypePreview";
import {
  createStructuredPrototypeViewportTransform,
  normalizeStructuredPrototypeWheelDelta,
  resolveStructuredPrototypeFitScale,
  resolveStructuredPrototypeWheelScale,
  resolveStructuredPrototypeZoomAtPoint,
} from "../src/features/prototype/structured/structuredPrototypeViewportTransform";

test("prototype preview freezes Fit scale without overriding numeric zoom", () => {
  assert.equal(
    resolveStructuredPrototypeEffectivePreviewScale({
      zoom: "fit",
      computedFitScale: 0.38,
      frozenFitScale: 0.5,
    }),
    0.5,
  );
  assert.equal(
    resolveStructuredPrototypeEffectivePreviewScale({
      zoom: "fit",
      computedFitScale: 0.38,
      frozenFitScale: null,
    }),
    0.38,
  );
  assert.equal(
    resolveStructuredPrototypeEffectivePreviewScale({
      zoom: 1.25,
      computedFitScale: 0.38,
      frozenFitScale: 0.5,
    }),
    1.25,
  );
});

test("prototype fit scale can shrink below twenty percent for a very tall page", () => {
  const scale = resolveStructuredPrototypeFitScale({
    hostWidth: 1200,
    hostHeight: 800,
    viewportWidth: 1440,
    viewportHeight: 900,
    measuredContentHeight: 5000,
    padding: 32,
  });

  assert.equal(scale, 768 / 5000);
  assert.ok(scale < 0.2);
});

test("prototype fit scale uses the declared viewport height when content is shorter", () => {
  const scale = resolveStructuredPrototypeFitScale({
    hostWidth: 2000,
    hostHeight: 800,
    viewportWidth: 1000,
    viewportHeight: 1600,
    measuredContentHeight: 600,
    padding: 32,
  });

  assert.equal(scale, 768 / 1600);
});

test("prototype fit scale stays positive and never enlarges the frame", () => {
  const roomyScale = resolveStructuredPrototypeFitScale({
    hostWidth: 2000,
    hostHeight: 1400,
    viewportWidth: 1000,
    viewportHeight: 800,
    measuredContentHeight: 700,
    padding: 32,
  });
  const constrainedScale = resolveStructuredPrototypeFitScale({
    hostWidth: 33,
    hostHeight: 33,
    viewportWidth: 1000,
    viewportHeight: 800,
    measuredContentHeight: 700,
    padding: 32,
  });

  assert.equal(roomyScale, 1);
  assert.ok(Number.isFinite(constrainedScale));
  assert.ok(constrainedScale > 0);
});

test("prototype wheel zoom keeps the canvas point under the pointer", () => {
  const pan = { x: 40, y: -20 };
  const pointerFromViewportCenter = { x: 180, y: 90 };
  const currentScale = 0.5;
  const nextScale = 1.25;
  const nextPan = resolveStructuredPrototypeZoomAtPoint({
    pan,
    pointerFromViewportOrigin: pointerFromViewportCenter,
    currentScale,
    nextScale,
  });

  const canvasPointBefore = {
    x: (pointerFromViewportCenter.x - pan.x) / currentScale,
    y: (pointerFromViewportCenter.y - pan.y) / currentScale,
  };
  const canvasPointAfter = {
    x: (pointerFromViewportCenter.x - nextPan.x) / nextScale,
    y: (pointerFromViewportCenter.y - nextPan.y) / nextScale,
  };

  assert.ok(Math.abs(canvasPointAfter.x - canvasPointBefore.x) < 1e-9);
  assert.ok(Math.abs(canvasPointAfter.y - canvasPointBefore.y) < 1e-9);
  assert.deepEqual(
    resolveStructuredPrototypeZoomAtPoint({
      pan,
      pointerFromViewportOrigin: pointerFromViewportCenter,
      currentScale: 0,
      nextScale,
    }),
    pan,
  );
});

test("prototype wheel input normalizes pixel, line, and page delta modes", () => {
  assert.equal(
    normalizeStructuredPrototypeWheelDelta({ deltaY: 12, deltaMode: 0, pageHeight: 800 }),
    12,
  );
  assert.equal(
    normalizeStructuredPrototypeWheelDelta({ deltaY: 2, deltaMode: 1, pageHeight: 800 }),
    32,
  );
  assert.equal(
    normalizeStructuredPrototypeWheelDelta({ deltaY: 0.5, deltaMode: 2, pageHeight: 800 }),
    400,
  );
  assert.equal(
    normalizeStructuredPrototypeWheelDelta({ deltaY: 12, deltaMode: 3, pageHeight: 800 }),
    0,
  );
});

test("prototype wheel zoom resolves an accumulated delta once and clamps scale", () => {
  assert.equal(
    resolveStructuredPrototypeWheelScale({
      currentScale: 0.5,
      normalizedDeltaY: -100,
      minimumScale: 0.01,
      maximumScale: 2,
      intensity: 0.0015,
    }),
    0.581,
  );
  assert.equal(
    resolveStructuredPrototypeWheelScale({
      currentScale: 0.5,
      normalizedDeltaY: 10_000,
      minimumScale: 0.01,
      maximumScale: 2,
      intensity: 0.0015,
    }),
    0.01,
  );
  assert.equal(
    resolveStructuredPrototypeWheelScale({
      currentScale: 0.5,
      normalizedDeltaY: -10_000,
      minimumScale: 0.01,
      maximumScale: 2,
      intensity: 0.0015,
    }),
    2,
  );
});

test("prototype viewport client and canvas coordinates round trip below half a pixel", () => {
  const transform = createStructuredPrototypeViewportTransform({
    viewportOrigin: { x: 90.25, y: 45.75 },
    canvasOrigin: { x: -12.5, y: 8.25 },
    pan: { x: 31.125, y: -17.875 },
    scale: 0.37,
  });
  const clientPoint = { x: 713.4, y: 422.9 };
  const canvasPoint = transform.clientToCanvas(clientPoint);
  const roundTrip = transform.canvasToClient(canvasPoint);

  assert.ok(Math.abs(roundTrip.x - clientPoint.x) < 0.5);
  assert.ok(Math.abs(roundTrip.y - clientPoint.y) < 0.5);
  assert.deepEqual(transform.clientDeltaToCanvas({ x: 37, y: -18.5 }), {
    x: 100,
    y: -50,
  });
});
