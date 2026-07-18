import assert from "node:assert/strict";
import test from "node:test";

import {
  resolveStructuredPrototypeDragMirrorGeometry,
  resolveStructuredPrototypeDragMirrorRootStyle,
} from "../src/features/prototype/structured/structuredPrototypeDragMirror";

for (const scale of [0.5, 0.75, 1, 2]) {
  test(`prototype drag mirror preserves client bounds at ${scale * 100}% scale`, () => {
    const geometry = resolveStructuredPrototypeDragMirrorGeometry({
      clientWidth: 320 * scale,
      clientHeight: 180 * scale,
      contentWidth: 320,
      contentHeight: 180,
    });

    assert.deepEqual(geometry, {
      clientWidth: 320 * scale,
      clientHeight: 180 * scale,
      contentWidth: 320,
      contentHeight: 180,
      scaleX: scale,
      scaleY: scale,
    });
  });
}

test("prototype drag mirror rejects invalid dimensions", () => {
  const invalidValues = [0, -1, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, Number.NaN];
  const dimensions = ["clientWidth", "clientHeight", "contentWidth", "contentHeight"] as const;

  for (const dimension of dimensions) {
    for (const invalidValue of invalidValues) {
      assert.equal(
        resolveStructuredPrototypeDragMirrorGeometry({
          clientWidth: dimension === "clientWidth" ? invalidValue : 320,
          clientHeight: dimension === "clientHeight" ? invalidValue : 180,
          contentWidth: dimension === "contentWidth" ? invalidValue : 320,
          contentHeight: dimension === "contentHeight" ? invalidValue : 180,
        }),
        null,
        `${dimension} must reject ${String(invalidValue)}`,
      );
    }
  }
});

test("prototype drag mirror root is isolated from Freeform and parent sizing layout", () => {
  assert.deepEqual(resolveStructuredPrototypeDragMirrorRootStyle(320, 180), {
    position: "relative",
    inset: "auto",
    top: "auto",
    right: "auto",
    bottom: "auto",
    left: "auto",
    width: "320px",
    height: "180px",
    minWidth: "0px",
    minHeight: "0px",
    maxWidth: "none",
    maxHeight: "none",
    margin: "0px",
    boxSizing: "border-box",
    flex: "0 0 auto",
    alignSelf: "auto",
    justifySelf: "auto",
    gridArea: "auto",
    order: "0",
    transform: "none",
    translate: "none",
    rotate: "none",
    scale: "none",
    transition: "none",
  });
});

test("prototype drag mirror root rejects invalid frozen content bounds", () => {
  assert.equal(resolveStructuredPrototypeDragMirrorRootStyle(0, 180), null);
  assert.equal(resolveStructuredPrototypeDragMirrorRootStyle(320, Number.NaN), null);
});
