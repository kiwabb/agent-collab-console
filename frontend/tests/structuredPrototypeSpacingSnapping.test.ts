import assert from "node:assert/strict";
import test from "node:test";

import {
  resolveStructuredPrototypeFreeformSpacingSnap,
  type StructuredPrototypeFreeformSpacingSnapInput,
} from "../src/features/prototype/structured/structuredPrototypeSpacingSnapping";
import { projectStructuredPrototypeFreeformSpacingGuides } from "../src/features/prototype/structured/structuredPrototypeSnapGuides";

const BASE_INPUT: StructuredPrototypeFreeformSpacingSnapInput = {
  axis: "x",
  movingBounds: { x: 24, y: 10, width: 20, height: 20 },
  selectedNodeIds: ["moving"],
  directSiblings: [
    { nodeId: "left", x: 60, y: 0, width: 20, height: 40 },
    { nodeId: "right", x: 100, y: 5, width: 20, height: 30 },
  ],
  minimumPosition: 0,
  maximumPosition: 500,
  threshold: 6,
};

function snap(overrides: Partial<StructuredPrototypeFreeformSpacingSnapInput> = {}) {
  return resolveStructuredPrototypeFreeformSpacingSnap({ ...BASE_INPUT, ...overrides });
}

function requireCandidate(overrides: Partial<StructuredPrototypeFreeformSpacingSnapInput> = {}) {
  const candidate = snap(overrides);
  if (candidate === null) throw new Error("expected an equal-spacing snap candidate");
  return candidate;
}

function assertCandidateProjects(candidate: NonNullable<ReturnType<typeof snap>>): void {
  assert.equal(
    projectStructuredPrototypeFreeformSpacingGuides({
      freeformOrigin: { x: 0, y: 0 },
      previewScale: 1,
      guides: [candidate.guide],
    }).length,
    2,
  );
}

function denseOverlapSiblings(
  count: number,
  uniqueFullFrames: boolean,
): StructuredPrototypeFreeformSpacingSnapInput["directSiblings"] {
  const leftCount = Math.floor(count / 2);
  const rightCount = count - leftCount;
  const left = Array.from({ length: leftCount }, (_, index) => {
    const y = uniqueFullFrames ? index / (Math.max(1, leftCount) * 10) : 0;
    return {
      nodeId: `left-${String(index).padStart(4, "0")}`,
      x: 100,
      y,
      width: 10,
      height: 40 - y,
    };
  });
  const right = Array.from({ length: rightCount }, (_, index) => {
    const y = uniqueFullFrames ? (index + 0.5) / (Math.max(1, rightCount) * 10) : 0;
    return {
      nodeId: `right-${String(index).padStart(4, "0")}`,
      x: 130,
      y,
      width: 10,
      height: 40 - y,
    };
  });
  return [...right.reverse(), ...left.reverse()];
}

test("resolves before, between, and after equal spacing on both axes", () => {
  const cases: readonly {
    axis: "x" | "y";
    placement: "before" | "between" | "after";
    movingBounds: { x: number; y: number; width: number; height: number };
    directSiblings: readonly {
      nodeId: string;
      x: number;
      y: number;
      width: number;
      height: number;
    }[];
    expectedPosition: number;
    expectedGap: number;
    expectedSegments: readonly (readonly [number, number])[];
  }[] = [
    {
      axis: "x",
      placement: "before",
      movingBounds: { x: 24, y: 10, width: 20, height: 20 },
      directSiblings: [
        { nodeId: "a", x: 60, y: 0, width: 20, height: 40 },
        { nodeId: "b", x: 100, y: 5, width: 20, height: 30 },
      ],
      expectedPosition: 20,
      expectedGap: 20,
      expectedSegments: [
        [40, 60],
        [80, 100],
      ],
    },
    {
      axis: "x",
      placement: "between",
      movingBounds: { x: 64, y: 10, width: 20, height: 20 },
      directSiblings: [
        { nodeId: "a", x: 20, y: 0, width: 20, height: 40 },
        { nodeId: "b", x: 100, y: 5, width: 20, height: 30 },
      ],
      expectedPosition: 60,
      expectedGap: 20,
      expectedSegments: [
        [40, 60],
        [80, 100],
      ],
    },
    {
      axis: "x",
      placement: "after",
      movingBounds: { x: 104, y: 10, width: 20, height: 20 },
      directSiblings: [
        { nodeId: "a", x: 20, y: 0, width: 20, height: 40 },
        { nodeId: "b", x: 60, y: 5, width: 20, height: 30 },
      ],
      expectedPosition: 100,
      expectedGap: 20,
      expectedSegments: [
        [40, 60],
        [80, 100],
      ],
    },
    {
      axis: "y",
      placement: "before",
      movingBounds: { x: 10, y: 24, width: 20, height: 20 },
      directSiblings: [
        { nodeId: "a", x: 0, y: 60, width: 40, height: 20 },
        { nodeId: "b", x: 5, y: 100, width: 30, height: 20 },
      ],
      expectedPosition: 20,
      expectedGap: 20,
      expectedSegments: [
        [40, 60],
        [80, 100],
      ],
    },
    {
      axis: "y",
      placement: "between",
      movingBounds: { x: 10, y: 64, width: 20, height: 20 },
      directSiblings: [
        { nodeId: "a", x: 0, y: 20, width: 40, height: 20 },
        { nodeId: "b", x: 5, y: 100, width: 30, height: 20 },
      ],
      expectedPosition: 60,
      expectedGap: 20,
      expectedSegments: [
        [40, 60],
        [80, 100],
      ],
    },
    {
      axis: "y",
      placement: "after",
      movingBounds: { x: 10, y: 104, width: 20, height: 20 },
      directSiblings: [
        { nodeId: "a", x: 0, y: 20, width: 40, height: 20 },
        { nodeId: "b", x: 5, y: 60, width: 30, height: 20 },
      ],
      expectedPosition: 100,
      expectedGap: 20,
      expectedSegments: [
        [40, 60],
        [80, 100],
      ],
    },
  ];

  for (const entry of cases) {
    const candidate = requireCandidate({
      axis: entry.axis,
      movingBounds: entry.movingBounds,
      directSiblings: entry.directSiblings,
    });
    assert.equal(candidate.placement, entry.placement);
    assert.equal(candidate.position, entry.expectedPosition);
    assert.equal(candidate.gap, entry.expectedGap);
    assert.equal(candidate.guide.axis, entry.axis);
    assert.equal(candidate.guide.placement, entry.placement);
    assert.deepEqual(candidate.referenceNodeIds, ["a", "b"]);
    assert.deepEqual(candidate.guide.referenceNodeIds, ["a", "b"]);
    assert.deepEqual(
      candidate.guide.segments.map((segment) => [segment.start, segment.end]),
      entry.expectedSegments,
    );
    assert.deepEqual(
      candidate.guide.segments.map((segment) => segment.segmentIndex),
      [0, 1],
    );
    assert.equal(candidate.guide.segments[0].crossCoordinate, 20);
    assert.equal(candidate.guide.segments[1].crossCoordinate, 20);
    for (const segment of candidate.guide.segments) {
      const segmentLength = segment.end - segment.start;
      const tolerance = Math.max(1, Math.abs(segmentLength), Math.abs(candidate.gap)) * 1e-9;
      assert.ok(Math.abs(segmentLength - candidate.gap) <= tolerance);
    }
  }
});

test("treats a grouped selection union as the moving frame and exposes stable endpoint metadata", () => {
  const candidate = requireCandidate({
    movingBounds: { x: 58, y: 10, width: 40, height: 20 },
    selectedNodeIds: ["group-a", "group-b"],
    directSiblings: [
      { nodeId: "left", x: 20, y: 0, width: 20, height: 40 },
      { nodeId: "right", x: 120, y: 5, width: 20, height: 30 },
    ],
  });

  assert.equal(candidate.position, 60);
  assert.equal(candidate.gap, 20);
  assert.deepEqual(candidate.guide.segments, [
    {
      start: 40,
      end: 60,
      crossCoordinate: 20,
      fromNodeId: "left",
      toNodeId: null,
      segmentIndex: 0,
    },
    {
      start: 100,
      end: 120,
      crossCoordinate: 20,
      fromNodeId: null,
      toNodeId: "right",
      segmentIndex: 1,
    },
  ]);
});

test("excludes every selected id from references and blocker checks", () => {
  const candidate = requireCandidate({
    movingBounds: { x: 59, y: 10, width: 20, height: 20 },
    selectedNodeIds: ["moving-a", "moving-b"],
    directSiblings: [
      { nodeId: "moving-a", x: 45, y: 10, width: 10, height: 20 },
      { nodeId: "moving-b", x: 85, y: 10, width: 10, height: 20 },
      { nodeId: "left", x: 20, y: 0, width: 20, height: 40 },
      { nodeId: "right", x: 100, y: 5, width: 20, height: 30 },
    ],
  });

  assert.equal(candidate.position, 60);
  assert.deepEqual(candidate.referenceNodeIds, ["left", "right"]);
});

test("requires a strictly positive common cross-axis intersection", () => {
  assert.equal(
    snap({
      movingBounds: { x: 59, y: 20, width: 20, height: 20 },
      directSiblings: [
        { nodeId: "left", x: 20, y: 0, width: 20, height: 20 },
        { nodeId: "right", x: 100, y: 10, width: 20, height: 20 },
      ],
    }),
    null,
  );

  assert.equal(
    snap({
      axis: "y",
      movingBounds: { x: 20, y: 59, width: 20, height: 20 },
      directSiblings: [
        { nodeId: "top", x: 0, y: 20, width: 20, height: 20 },
        { nodeId: "bottom", x: 10, y: 100, width: 20, height: 20 },
      ],
    }),
    null,
  );
});

test("rejects fixed-gap, target-corridor, and projected-frame blockers in the same lane", () => {
  const fixedGapBlocker = snap({
    movingBounds: { x: 19, y: 10, width: 20, height: 20 },
    directSiblings: [
      { nodeId: "left", x: 60, y: 0, width: 20, height: 40 },
      { nodeId: "fixed-gap-blocker", x: 85, y: 15, width: 10, height: 10 },
      { nodeId: "right", x: 100, y: 5, width: 20, height: 30 },
    ],
  });
  assert.equal(fixedGapBlocker, null);

  const targetCorridorBlocker = snap({
    movingBounds: { x: 24, y: 10, width: 20, height: 20 },
    directSiblings: [
      { nodeId: "target-gap-blocker", x: 40, y: 15, width: 20, height: 10 },
      { nodeId: "left", x: 60, y: 0, width: 20, height: 40 },
      { nodeId: "right", x: 100, y: 5, width: 20, height: 30 },
    ],
  });
  assert.equal(targetCorridorBlocker, null);

  const projectedFrameBlocker = snap({
    movingBounds: { x: 24, y: 10, width: 20, height: 20 },
    directSiblings: [
      { nodeId: "projected-frame-blocker", x: 25, y: 15, width: 10, height: 10 },
      { nodeId: "left", x: 60, y: 0, width: 20, height: 40 },
      { nodeId: "right", x: 100, y: 5, width: 20, height: 30 },
    ],
  });
  assert.equal(projectedFrameBlocker, null);

  const offLaneBlocker = requireCandidate({
    movingBounds: { x: 24, y: 10, width: 20, height: 20 },
    directSiblings: [
      { nodeId: "off-lane", x: 40, y: 50, width: 20, height: 10 },
      { nodeId: "left", x: 60, y: 0, width: 20, height: 40 },
      { nodeId: "right", x: 100, y: 5, width: 20, height: 30 },
    ],
  });
  assert.equal(offLaneBlocker.position, 20);
});

test("transposes corridor blocker checks for vertical spacing", () => {
  const verticalBlocker = snap({
    axis: "y",
    movingBounds: { x: 10, y: 24, width: 20, height: 20 },
    directSiblings: [
      { nodeId: "top", x: 0, y: 60, width: 40, height: 20 },
      { nodeId: "corridor-blocker", x: 15, y: 40, width: 10, height: 10 },
      { nodeId: "bottom", x: 5, y: 100, width: 30, height: 20 },
    ],
  });
  assert.equal(verticalBlocker, null);

  const offLane = requireCandidate({
    axis: "y",
    movingBounds: { x: 10, y: 24, width: 20, height: 20 },
    directSiblings: [
      { nodeId: "top", x: 0, y: 60, width: 40, height: 20 },
      { nodeId: "off-lane", x: 50, y: 40, width: 10, height: 10 },
      { nodeId: "bottom", x: 5, y: 100, width: 30, height: 20 },
    ],
  });
  assert.equal(offLane.position, 20);
});

test("rejects zero, negative, and moving-frame-consuming gaps", () => {
  assert.equal(
    snap({
      movingBounds: { x: 40, y: 10, width: 20, height: 20 },
      directSiblings: [
        { nodeId: "left", x: 20, y: 0, width: 20, height: 40 },
        { nodeId: "right", x: 40, y: 5, width: 20, height: 30 },
      ],
    }),
    null,
  );
  assert.equal(
    snap({
      movingBounds: { x: 35, y: 10, width: 20, height: 20 },
      directSiblings: [
        { nodeId: "left", x: 20, y: 0, width: 30, height: 40 },
        { nodeId: "right", x: 40, y: 5, width: 20, height: 30 },
      ],
    }),
    null,
  );
  assert.equal(
    snap({
      movingBounds: { x: 45, y: 10, width: 20, height: 20 },
      directSiblings: [
        { nodeId: "left", x: 20, y: 0, width: 20, height: 40 },
        { nodeId: "right", x: 60, y: 5, width: 20, height: 30 },
      ],
    }),
    null,
  );
});

test("treats fixed and derived arithmetic tails as zero gap", () => {
  assert.equal(
    snap({
      movingBounds: { x: 0.05, y: 0, width: 0.05, height: 20 },
      directSiblings: [
        { nodeId: "left", x: 0.1, y: 0, width: 64.1, height: 20 },
        { nodeId: "right", x: 64.2, y: 0, width: 20, height: 20 },
      ],
    }),
    null,
  );
  assert.equal(
    snap({
      movingBounds: { x: 64.2, y: 0, width: 128.2, height: 20 },
      directSiblings: [
        { nodeId: "left", x: 0.1, y: 0, width: 64.1, height: 20 },
        { nodeId: "right", x: 192.4, y: 0, width: 20, height: 20 },
      ],
    }),
    null,
  );
});

test("uses an inclusive threshold below, at, and above six canvas units", () => {
  assert.ok(
    Math.abs(
      requireCandidate({ movingBounds: { ...BASE_INPUT.movingBounds, x: 25.9 } }).distance - 5.9,
    ) < 1e-9,
  );
  assert.equal(
    requireCandidate({ movingBounds: { ...BASE_INPUT.movingBounds, x: 26 } }).distance,
    6,
  );
  assert.equal(
    snap({ movingBounds: { ...BASE_INPUT.movingBounds, x: 25.9 }, threshold: 5.8 }),
    null,
  );
});

test("accepts a threshold arithmetic tail without changing the equal-spacing target", () => {
  const result = requireCandidate({
    axis: "x",
    movingBounds: { x: 13, y: 0, width: 20.9, height: 20 },
    directSiblings: [
      { nodeId: "left", x: 50, y: 0, width: 20, height: 20 },
      { nodeId: "right", x: 80.1, y: 0, width: 20, height: 20 },
    ],
    threshold: 6,
  });
  const expectedPosition = 50 - 20.9 - (80.1 - (50 + 20));

  assert.equal(result.position, expectedPosition);
  assert.equal(result.correction, expectedPosition - 13);
  assert.equal(result.position, 13 + result.correction);
  assert.equal(result.distance, Math.abs(result.correction));
  assert.ok(result.distance > 6);
  assert.equal(result.placement, "before");
  assertCandidateProjects(result);

  assert.equal(
    snap({
      movingBounds: { ...BASE_INPUT.movingBounds, x: 13.999999 },
      threshold: 6,
    }),
    null,
  );
});

test("preserves a high-coordinate tiny-gap target and projects both segments", () => {
  const movingBounds = { x: 3979.9999, y: 0, width: 100, height: 20 };
  const result = requireCandidate({
    movingBounds,
    directSiblings: [
      { nodeId: "left", x: 3900, y: 0, width: 79.999803, height: 20 },
      { nodeId: "right", x: 4080.000003, y: 0, width: 10, height: 20 },
    ],
    maximumPosition: 5_000,
  });

  assert.equal(result.position, 3979.999903);
  assert.equal(result.position, movingBounds.x + result.correction);
  assert.equal(result.distance, Math.abs(result.correction));
  assert.ok(result.gap > 0.000099 && result.gap < 0.000101);
  assertCandidateProjects(result);

  assert.equal(
    snap({
      movingBounds,
      directSiblings: [
        { nodeId: "left", x: 3900, y: 0, width: 79.999803, height: 20 },
        { nodeId: "right", x: 4080.000003, y: 0, width: 10, height: 20 },
      ],
      maximumPosition: movingBounds.x,
    }),
    null,
  );
});

test("normalizes a true envelope tail while keeping normal-gap guides projectable", () => {
  const result = requireCandidate({
    movingBounds: { x: 13, y: 0, width: 20.9, height: 20 },
    directSiblings: [
      { nodeId: "left", x: 50, y: 0, width: 20, height: 20 },
      { nodeId: "right", x: 80.1, y: 0, width: 20, height: 20 },
    ],
    maximumPosition: 19,
  });

  assert.equal(result.position, 19);
  assert.equal(result.position, 13 + result.correction);
  assert.equal(result.distance, Math.abs(result.correction));
  assertCandidateProjects(result);
});

test("rejects targets outside the inclusive movement envelope", () => {
  assert.equal(snap({ minimumPosition: 21 }), null);
  assert.equal(
    snap({
      movingBounds: { ...BASE_INPUT.movingBounds, x: 96 },
      directSiblings: [
        { nodeId: "left", x: 20, y: 0, width: 20, height: 40 },
        { nodeId: "right", x: 60, y: 5, width: 20, height: 30 },
      ],
      maximumPosition: 99,
    }),
    null,
  );
  assert.equal(
    requireCandidate({
      movingBounds: { ...BASE_INPUT.movingBounds, x: 20 },
      minimumPosition: 20,
      maximumPosition: 20,
    }).position,
    20,
  );
});

test("is independent of sibling and selection input order", () => {
  const directSiblings = [
    { nodeId: "selected", x: 45, y: 10, width: 10, height: 20 },
    { nodeId: "left", x: 60, y: 0, width: 20, height: 40 },
    { nodeId: "right", x: 100, y: 5, width: 20, height: 30 },
  ];
  const forward = requireCandidate({
    selectedNodeIds: ["moving", "selected"],
    directSiblings,
  });
  const reverse = requireCandidate({
    selectedNodeIds: ["selected", "moving"],
    directSiblings: [...directSiblings].reverse(),
  });
  assert.deepEqual(forward, reverse);
});

test("keeps stable reference ids across 400 overlapping sibling frames", () => {
  for (const uniqueFullFrames of [false, true]) {
    const directSiblings = denseOverlapSiblings(400, uniqueFullFrames);
    const forward = requireCandidate({
      movingBounds: { x: 115, y: 10, width: 10, height: 20 },
      directSiblings,
      maximumPosition: 1_000,
      threshold: 0,
    });
    const reverse = requireCandidate({
      movingBounds: { x: 115, y: 10, width: 10, height: 20 },
      directSiblings: [...directSiblings].reverse(),
      maximumPosition: 1_000,
      threshold: 0,
    });

    assert.equal(forward.position, 115);
    assert.equal(forward.gap, 5);
    assert.equal(forward.placement, "between");
    assert.deepEqual(forward.referenceNodeIds, ["left-0000", "right-0000"]);
    assert.deepEqual(reverse, forward);
  }
});

test("rejects 400 overlapping sibling candidates that share one blocker query", () => {
  const result = snap({
    movingBounds: { x: 115, y: 10, width: 10, height: 20 },
    directSiblings: [
      ...denseOverlapSiblings(399, true),
      { nodeId: "shared-blocker", x: 111, y: 10, width: 1, height: 20 },
    ],
    maximumPosition: 1_000,
    threshold: 0,
  });

  assert.equal(result, null);
});

test("does not share blocker results across equal midpoints with different cross intervals", () => {
  const candidate = requireCandidate({
    movingBounds: { x: 115, y: 0, width: 10, height: 20 },
    directSiblings: [
      { nodeId: "a-left", x: 100, y: 0, width: 10, height: 20 },
      { nodeId: "a-right", x: 130, y: 0, width: 10, height: 20 },
      { nodeId: "b-left", x: 100, y: 5, width: 10, height: 10 },
      { nodeId: "b-right", x: 130, y: 5, width: 10, height: 10 },
      { nodeId: "wide-lane-only-blocker", x: 111, y: 1, width: 1, height: 1 },
    ],
    maximumPosition: 1_000,
    threshold: 0,
  });

  assert.equal(candidate.position, 115);
  assert.deepEqual(candidate.referenceNodeIds, ["a-left", "b-right"]);
  assert.equal(candidate.guide.segments[0].crossCoordinate, 10);
  assert.equal(candidate.guide.segments[1].crossCoordinate, 10);
});

test("breaks ties by outer span, placement, gap, position, then reference ids", () => {
  const placementTie = requireCandidate({
    movingBounds: { x: 50, y: 10, width: 10, height: 20 },
    directSiblings: [
      { nodeId: "between-left", x: 30, y: 0, width: 10, height: 40 },
      { nodeId: "before-left", x: 70, y: 0, width: 10, height: 40 },
      { nodeId: "between-right", x: 70, y: 0, width: 10, height: 40 },
      { nodeId: "before-right", x: 90, y: 0, width: 10, height: 40 },
    ],
    threshold: 0,
  });
  assert.equal(placementTie.placement, "between");
  assert.deepEqual(placementTie.referenceNodeIds, ["between-left", "before-left"]);

  const referenceTie = requireCandidate({
    movingBounds: { x: 59, y: 10, width: 20, height: 20 },
    directSiblings: [
      { nodeId: "z-left", x: 20, y: 0, width: 20, height: 40 },
      { nodeId: "z-right", x: 100, y: 0, width: 20, height: 40 },
      { nodeId: "a-left", x: 20, y: 0, width: 20, height: 40 },
      { nodeId: "a-right", x: 100, y: 0, width: 20, height: 40 },
    ],
  });
  assert.deepEqual(referenceTie.referenceNodeIds, ["a-left", "a-right"]);
});

test("fails closed for invalid frames, ids, envelopes, and thresholds", () => {
  const firstSibling = BASE_INPUT.directSiblings[0];
  if (firstSibling === undefined) throw new Error("expected the first base sibling");
  assert.throws(
    () => snap({ movingBounds: { ...BASE_INPUT.movingBounds, x: Number.NaN } }),
    /finite/,
  );
  assert.throws(() => snap({ movingBounds: { ...BASE_INPUT.movingBounds, width: 0 } }), /positive/);
  assert.throws(
    () =>
      snap({
        directSiblings: [
          ...BASE_INPUT.directSiblings,
          { nodeId: "bad", x: 10, y: 10, width: -1, height: 10 },
        ],
      }),
    /positive/,
  );
  assert.throws(() => snap({ selectedNodeIds: [] }), /at least one selected node/);
  assert.throws(() => snap({ selectedNodeIds: ["moving", "moving"] }), /duplicated/);
  assert.throws(() => snap({ directSiblings: [firstSibling, firstSibling] }), /duplicated/);
  assert.throws(() => snap({ minimumPosition: -1 }), /must not be negative/);
  assert.throws(() => snap({ minimumPosition: 30, maximumPosition: 20 }), /below minimum/);
  assert.throws(() => snap({ threshold: Number.POSITIVE_INFINITY }), /finite/);
  assert.throws(() => snap({ threshold: -1 }), /must not be negative/);
  assert.throws(
    () => snap({ movingBounds: { ...BASE_INPUT.movingBounds, x: 501 } }),
    /inside its envelope/,
  );
});
