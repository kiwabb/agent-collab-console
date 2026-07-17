import assert from "node:assert/strict";
import test from "node:test";

import {
  projectStructuredPrototypeFreeformSpacingGuides,
  projectStructuredPrototypeFreeformSnapGuides,
  type StructuredPrototypeFreeformSpacingGuideProjectionInput,
  type StructuredPrototypeFreeformSnapGuideProjectionInput,
} from "../src/features/prototype/structured/structuredPrototypeSnapGuides";
import type { StructuredPrototypeFreeformSpacingGuide } from "../src/features/prototype/structured/structuredPrototypeSpacingSnapping";
import type { StructuredPrototypeFreeformSnapGuide } from "../src/features/prototype/structured/structuredPrototypeSnapping";

const HORIZONTAL_GUIDE: StructuredPrototypeFreeformSnapGuide = {
  axis: "y",
  coordinate: 80,
  movingAnchor: "middle",
  targetAnchor: "bottom",
  targetKind: "sibling",
  targetNodeId: "summary-card",
};

const VERTICAL_GUIDE: StructuredPrototypeFreeformSnapGuide = {
  axis: "x",
  coordinate: 120,
  movingAnchor: "right",
  targetAnchor: "center",
  targetKind: "container",
  targetNodeId: null,
};

const GUIDES: readonly StructuredPrototypeFreeformSnapGuide[] = [HORIZONTAL_GUIDE, VERTICAL_GUIDE];

const BASE_INPUT: StructuredPrototypeFreeformSnapGuideProjectionInput = {
  freeformOrigin: { x: 45, y: 30 },
  containerWidth: 640,
  containerHeight: 360,
  previewScale: 2,
  guides: GUIDES,
};

const HORIZONTAL_SPACING_GUIDE: StructuredPrototypeFreeformSpacingGuide = {
  axis: "x",
  placement: "between",
  gap: 40,
  referenceNodeIds: ["left-card", "right-card"],
  segments: [
    {
      start: 20,
      end: 60,
      crossCoordinate: 48,
      fromNodeId: "left-card",
      toNodeId: null,
      segmentIndex: 0,
    },
    {
      start: 160,
      end: 200,
      crossCoordinate: 48,
      fromNodeId: null,
      toNodeId: "right-card",
      segmentIndex: 1,
    },
  ],
};

const VERTICAL_SPACING_GUIDE: StructuredPrototypeFreeformSpacingGuide = {
  axis: "y",
  placement: "after",
  gap: 30,
  referenceNodeIds: ["top-card", "middle-card"],
  segments: [
    {
      start: 10,
      end: 40,
      crossCoordinate: 90,
      fromNodeId: "top-card",
      toNodeId: "middle-card",
      segmentIndex: 0,
    },
    {
      start: 80,
      end: 110,
      crossCoordinate: 90,
      fromNodeId: "middle-card",
      toNodeId: null,
      segmentIndex: 1,
    },
  ],
};

const SPACING_BASE_INPUT: StructuredPrototypeFreeformSpacingGuideProjectionInput = {
  freeformOrigin: { x: 45, y: 30 },
  previewScale: 2,
  guides: [HORIZONTAL_SPACING_GUIDE, VERTICAL_SPACING_GUIDE],
};

function guideAt(
  guides: ReturnType<typeof projectStructuredPrototypeFreeformSnapGuides>,
  index: number,
) {
  const guide = guides[index];
  if (guide === undefined) throw new Error(`expected projected guide at index ${index}`);
  return guide;
}

test("projects nested Freeform guides into Canvas-local full-span geometry", () => {
  assert.deepEqual(projectStructuredPrototypeFreeformSnapGuides(BASE_INPUT), [
    {
      axis: "y",
      left: 45,
      top: 110,
      width: 640,
      height: 0.5,
      movingAnchor: "middle",
      targetAnchor: "bottom",
      targetKind: "sibling",
      targetNodeId: "summary-card",
    },
    {
      axis: "x",
      left: 165,
      top: 30,
      width: 0.5,
      height: 360,
      movingAnchor: "right",
      targetAnchor: "center",
      targetKind: "container",
      targetNodeId: null,
    },
  ]);
});

test("keeps guide thickness at one physical pixel across preview zoom levels", () => {
  for (const previewScale of [0.5, 1, 2, 4]) {
    const projected = projectStructuredPrototypeFreeformSnapGuides({
      ...BASE_INPUT,
      previewScale,
    });
    const horizontal = guideAt(projected, 0);
    const vertical = guideAt(projected, 1);

    assert.equal(horizontal.height * previewScale, 1);
    assert.equal(horizontal.width, BASE_INPUT.containerWidth);
    assert.equal(vertical.width * previewScale, 1);
    assert.equal(vertical.height, BASE_INPUT.containerHeight);
  }
});

test("preserves deterministic guide input order and metadata", () => {
  const projected = projectStructuredPrototypeFreeformSnapGuides({
    ...BASE_INPUT,
    guides: [VERTICAL_GUIDE, HORIZONTAL_GUIDE],
  });

  assert.deepEqual(
    projected.map((guide) => [
      guide.axis,
      guide.movingAnchor,
      guide.targetAnchor,
      guide.targetKind,
      guide.targetNodeId,
    ]),
    [
      ["x", "right", "center", "container", null],
      ["y", "middle", "bottom", "sibling", "summary-card"],
    ],
  );
});

test("rejects invalid origins, dimensions, scale, guide coordinates, and axes", () => {
  assert.throws(
    () =>
      projectStructuredPrototypeFreeformSnapGuides({
        ...BASE_INPUT,
        freeformOrigin: { x: Number.NaN, y: 0 },
      }),
    /freeform origin x must be finite/,
  );
  assert.throws(
    () => projectStructuredPrototypeFreeformSnapGuides({ ...BASE_INPUT, containerWidth: 0 }),
    /container width must be positive/,
  );
  assert.throws(
    () => projectStructuredPrototypeFreeformSnapGuides({ ...BASE_INPUT, containerHeight: -1 }),
    /container height must be positive/,
  );
  assert.throws(
    () => projectStructuredPrototypeFreeformSnapGuides({ ...BASE_INPUT, previewScale: Infinity }),
    /preview scale must be finite/,
  );
  assert.throws(
    () =>
      projectStructuredPrototypeFreeformSnapGuides({
        ...BASE_INPUT,
        previewScale: Number.MIN_VALUE,
      }),
    /inverse preview scale must be finite/,
  );
  assert.throws(
    () =>
      projectStructuredPrototypeFreeformSnapGuides({
        ...BASE_INPUT,
        guides: [{ ...HORIZONTAL_GUIDE, coordinate: Number.NEGATIVE_INFINITY }],
      }),
    /coordinate must be finite/,
  );
  assert.throws(
    () =>
      projectStructuredPrototypeFreeformSnapGuides({
        ...BASE_INPUT,
        freeformOrigin: { x: Number.MAX_VALUE, y: 0 },
        guides: [{ ...VERTICAL_GUIDE, coordinate: Number.MAX_VALUE }],
      }),
    /projected left must be finite/,
  );

  const invalidAxisGuide = structuredClone(HORIZONTAL_GUIDE);
  Reflect.set(invalidAxisGuide, "axis", "z");
  assert.throws(
    () =>
      projectStructuredPrototypeFreeformSnapGuides({ ...BASE_INPUT, guides: [invalidAxisGuide] }),
    /axis must be x or y/,
  );
});

test("projects nested Freeform spacing segments on both axes", () => {
  assert.deepEqual(projectStructuredPrototypeFreeformSpacingGuides(SPACING_BASE_INPUT), [
    {
      axis: "x",
      left: 65,
      top: 78,
      width: 40,
      height: 0.5,
      capThickness: 0.5,
      capLength: 3,
      gap: 40,
      placement: "between",
      referenceNodeIds: ["left-card", "right-card"],
      fromNodeId: "left-card",
      toNodeId: null,
      segmentIndex: 0,
    },
    {
      axis: "x",
      left: 205,
      top: 78,
      width: 40,
      height: 0.5,
      capThickness: 0.5,
      capLength: 3,
      gap: 40,
      placement: "between",
      referenceNodeIds: ["left-card", "right-card"],
      fromNodeId: null,
      toNodeId: "right-card",
      segmentIndex: 1,
    },
    {
      axis: "y",
      left: 135,
      top: 40,
      width: 0.5,
      height: 30,
      capThickness: 0.5,
      capLength: 3,
      gap: 30,
      placement: "after",
      referenceNodeIds: ["top-card", "middle-card"],
      fromNodeId: "top-card",
      toNodeId: "middle-card",
      segmentIndex: 0,
    },
    {
      axis: "y",
      left: 135,
      top: 110,
      width: 0.5,
      height: 30,
      capThickness: 0.5,
      capLength: 3,
      gap: 30,
      placement: "after",
      referenceNodeIds: ["top-card", "middle-card"],
      fromNodeId: "middle-card",
      toNodeId: null,
      segmentIndex: 1,
    },
  ]);
});

test("flattens multiple same-axis spacing guides in deterministic segment order", () => {
  const secondHorizontal: StructuredPrototypeFreeformSpacingGuide = {
    ...HORIZONTAL_SPACING_GUIDE,
    placement: "before",
    gap: 12,
    referenceNodeIds: ["first", "second"],
    segments: [
      {
        start: 1,
        end: 13,
        crossCoordinate: 5,
        fromNodeId: null,
        toNodeId: "first",
        segmentIndex: 0,
      },
      {
        start: 20,
        end: 32,
        crossCoordinate: 5,
        fromNodeId: "first",
        toNodeId: "second",
        segmentIndex: 1,
      },
    ],
  };

  const projected = projectStructuredPrototypeFreeformSpacingGuides({
    ...SPACING_BASE_INPUT,
    guides: [secondHorizontal, HORIZONTAL_SPACING_GUIDE],
  });

  assert.deepEqual(
    projected.map((guide) => [
      guide.placement,
      guide.referenceNodeIds,
      guide.fromNodeId,
      guide.toNodeId,
      guide.segmentIndex,
      guide.left,
    ]),
    [
      ["before", ["first", "second"], null, "first", 0, 46],
      ["before", ["first", "second"], "first", "second", 1, 65],
      ["between", ["left-card", "right-card"], "left-card", null, 0, 65],
      ["between", ["left-card", "right-card"], null, "right-card", 1, 205],
    ],
  );
});

test("keeps spacing lines and caps at fixed client-pixel sizes across preview zoom", () => {
  for (const previewScale of [0.5, 1, 2, 4]) {
    const projected = projectStructuredPrototypeFreeformSpacingGuides({
      ...SPACING_BASE_INPUT,
      previewScale,
    });
    const horizontal = projected[0];
    const vertical = projected[2];
    if (horizontal === undefined || vertical === undefined) {
      throw new Error("expected horizontal and vertical spacing projections");
    }

    assert.equal(horizontal.height * previewScale, 1);
    assert.equal(vertical.width * previewScale, 1);
    assert.equal(horizontal.capThickness * previewScale, 1);
    assert.equal(vertical.capThickness * previewScale, 1);
    assert.equal(horizontal.capLength * previewScale, 6);
    assert.equal(vertical.capLength * previewScale, 6);
    assert.equal(horizontal.width, HORIZONTAL_SPACING_GUIDE.gap);
    assert.equal(vertical.height, VERTICAL_SPACING_GUIDE.gap);
  }
});

test("accepts relative 1e-9 spacing tails and rejects invalid spacing geometry", () => {
  const withinTolerance: StructuredPrototypeFreeformSpacingGuide = {
    ...HORIZONTAL_SPACING_GUIDE,
    segments: [
      {
        ...HORIZONTAL_SPACING_GUIDE.segments[0],
        end: 60 + 40 * 5e-10,
      },
      HORIZONTAL_SPACING_GUIDE.segments[1],
    ],
  };
  assert.doesNotThrow(() =>
    projectStructuredPrototypeFreeformSpacingGuides({
      ...SPACING_BASE_INPUT,
      guides: [withinTolerance],
    }),
  );

  assert.throws(
    () =>
      projectStructuredPrototypeFreeformSpacingGuides({
        ...SPACING_BASE_INPUT,
        freeformOrigin: { x: Number.NaN, y: 0 },
      }),
    /spacing freeform origin x must be finite/,
  );
  assert.throws(
    () =>
      projectStructuredPrototypeFreeformSpacingGuides({
        ...SPACING_BASE_INPUT,
        previewScale: 0,
      }),
    /spacing preview scale must be positive/,
  );
  assert.throws(
    () =>
      projectStructuredPrototypeFreeformSpacingGuides({
        ...SPACING_BASE_INPUT,
        previewScale: Number.MIN_VALUE,
      }),
    /spacing inverse preview scale must be finite/,
  );
  assert.throws(
    () =>
      projectStructuredPrototypeFreeformSpacingGuides({
        ...SPACING_BASE_INPUT,
        guides: [{ ...HORIZONTAL_SPACING_GUIDE, gap: 0 }],
      }),
    /spacing gap must be positive/,
  );
  assert.throws(
    () =>
      projectStructuredPrototypeFreeformSpacingGuides({
        ...SPACING_BASE_INPUT,
        guides: [
          {
            ...HORIZONTAL_SPACING_GUIDE,
            segments: [
              { ...HORIZONTAL_SPACING_GUIDE.segments[0], crossCoordinate: Infinity },
              HORIZONTAL_SPACING_GUIDE.segments[1],
            ],
          },
        ],
      }),
    /spacing segment cross coordinate must be finite/,
  );
  assert.throws(
    () =>
      projectStructuredPrototypeFreeformSpacingGuides({
        ...SPACING_BASE_INPUT,
        guides: [
          {
            ...HORIZONTAL_SPACING_GUIDE,
            segments: [
              { ...HORIZONTAL_SPACING_GUIDE.segments[0], end: 20 },
              HORIZONTAL_SPACING_GUIDE.segments[1],
            ],
          },
        ],
      }),
    /spacing segment end must be greater than start/,
  );
  assert.throws(
    () =>
      projectStructuredPrototypeFreeformSpacingGuides({
        ...SPACING_BASE_INPUT,
        guides: [
          {
            ...HORIZONTAL_SPACING_GUIDE,
            segments: [
              { ...HORIZONTAL_SPACING_GUIDE.segments[0], end: 61 },
              HORIZONTAL_SPACING_GUIDE.segments[1],
            ],
          },
        ],
      }),
    /spacing segment length must match gap/,
  );
  assert.throws(
    () =>
      projectStructuredPrototypeFreeformSpacingGuides({
        ...SPACING_BASE_INPUT,
        freeformOrigin: { x: 0, y: Number.MAX_VALUE },
        guides: [
          {
            ...HORIZONTAL_SPACING_GUIDE,
            segments: [
              {
                ...HORIZONTAL_SPACING_GUIDE.segments[0],
                crossCoordinate: Number.MAX_VALUE,
              },
              HORIZONTAL_SPACING_GUIDE.segments[1],
            ],
          },
        ],
      }),
    /spacing projected top must be finite/,
  );

  const invalidAxisGuide = structuredClone(HORIZONTAL_SPACING_GUIDE);
  Reflect.set(invalidAxisGuide, "axis", "z");
  assert.throws(
    () =>
      projectStructuredPrototypeFreeformSpacingGuides({
        ...SPACING_BASE_INPUT,
        guides: [invalidAxisGuide],
      }),
    /axis must be x or y/,
  );
});

test("projects high-coordinate tiny gaps and rejects a mismatch beyond the local invariant", () => {
  const tinyGapGuide: StructuredPrototypeFreeformSpacingGuide = {
    axis: "x",
    placement: "between",
    gap: 0.00009999999997489795,
    referenceNodeIds: ["left", "right"],
    segments: [
      {
        start: 3979.999803,
        end: 3979.999903,
        crossCoordinate: 10,
        fromNodeId: "left",
        toNodeId: null,
        segmentIndex: 0,
      },
      {
        start: 3979.999903 + 100,
        end: 4080.000003,
        crossCoordinate: 10,
        fromNodeId: null,
        toNodeId: "right",
        segmentIndex: 1,
      },
    ],
  };

  assert.doesNotThrow(() =>
    projectStructuredPrototypeFreeformSpacingGuides({
      freeformOrigin: { x: 0, y: 0 },
      previewScale: 1,
      guides: [tinyGapGuide],
    }),
  );

  const overToleranceGuide: StructuredPrototypeFreeformSpacingGuide = {
    ...tinyGapGuide,
    segments: [
      {
        ...tinyGapGuide.segments[0],
        end: tinyGapGuide.segments[0].start + tinyGapGuide.gap + 2e-9,
      },
      tinyGapGuide.segments[1],
    ],
  };
  assert.throws(
    () =>
      projectStructuredPrototypeFreeformSpacingGuides({
        freeformOrigin: { x: 0, y: 0 },
        previewScale: 1,
        guides: [overToleranceGuide],
      }),
    /spacing segment length must match gap/,
  );
});
