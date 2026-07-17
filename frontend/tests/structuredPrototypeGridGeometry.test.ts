import assert from "node:assert/strict";
import test from "node:test";

import {
  resolveStructuredPrototypeFreeformGridGeometries,
  resolveStructuredPrototypeFreeformGridGeometry,
  resolveStructuredPrototypeNearestFreeformGridSnapLine,
  type StructuredPrototypeFreeformGridFrame,
} from "../src/features/prototype/structured/structuredPrototypeGridGeometry";
import type {
  StructuredPrototypeAxisGrid,
  StructuredPrototypeFreeformGrid,
  StructuredPrototypeSquareGrid,
} from "../src/features/prototype/structured/types";

const FRAME = { width: 200, height: 120 } as const;

function squareGrid({
  id = "grid-square",
  visible = true,
  snapEnabled = true,
  originX = "0",
  originY = "0",
  size = "16",
}: {
  id?: string;
  visible?: boolean;
  snapEnabled?: boolean;
  originX?: string;
  originY?: string;
  size?: string;
} = {}): StructuredPrototypeSquareGrid {
  return {
    id,
    version: 1,
    type: "square",
    visible,
    snapEnabled,
    origin: { x: originX, y: originY },
    params: { size, colorTokenKey: "grid-color", opacity: "0.4" },
  };
}

function axisGrid({
  id = "grid-axis",
  type = "columns",
  visible = true,
  snapEnabled = true,
  originX = "0",
  originY = "0",
  count = 2,
  itemSize = null,
  gutter = "10",
  margin = "5",
  alignment = "stretch",
}: {
  id?: string;
  type?: "columns" | "rows";
  visible?: boolean;
  snapEnabled?: boolean;
  originX?: string;
  originY?: string;
  count?: number;
  itemSize?: string | null;
  gutter?: string;
  margin?: string;
  alignment?: "stretch" | "start" | "center" | "end";
} = {}): StructuredPrototypeAxisGrid {
  return {
    id,
    version: 1,
    type,
    visible,
    snapEnabled,
    origin: { x: originX, y: originY },
    params: {
      count,
      itemSize,
      gutter,
      margin,
      alignment,
      colorTokenKey: "grid-color",
      opacity: "0.1",
    },
  };
}

function requireSnapLine(
  grids: readonly StructuredPrototypeFreeformGrid[],
  axis: "x" | "y",
  coordinate: number,
  frame: Readonly<StructuredPrototypeFreeformGridFrame> = FRAME,
) {
  const line = resolveStructuredPrototypeNearestFreeformGridSnapLine({
    frame,
    grids,
    axis,
    coordinate,
  });
  if (line === null) throw new Error("expected a nearest grid snap line");
  return line;
}

test("returns a frame-local square pattern without enumerating periodic lines", () => {
  assert.deepEqual(
    resolveStructuredPrototypeFreeformGridGeometry({
      frame: FRAME,
      grid: squareGrid({ originX: "10.5", originY: "4.25", size: "15.5" }),
    }),
    {
      gridId: "grid-square",
      type: "square",
      origin: { x: 10.5, y: 4.25 },
      size: 15.5,
      clip: { x: 10.5, y: 4.25, width: 189.5, height: 115.75 },
    },
  );
});

test("calculates stretched column track areas from origin, margin, and gutter", () => {
  assert.deepEqual(
    resolveStructuredPrototypeFreeformGridGeometry({
      frame: { width: 120, height: 80 },
      grid: axisGrid({
        type: "columns",
        originX: "10",
        originY: "5",
        count: 2,
        gutter: "10",
        margin: "5",
      }),
    }),
    {
      gridId: "grid-axis",
      type: "columns",
      clip: { x: 10, y: 5, width: 110, height: 75 },
      areas: [
        { index: 0, x: 15, y: 5, width: 45, height: 75 },
        { index: 1, x: 70, y: 5, width: 45, height: 75 },
      ],
    },
  );
});

test("places fixed tracks deterministically for start, center, and end alignment", () => {
  const expectedStarts = { start: 20, center: 80, end: 140 } as const;
  for (const alignment of ["start", "center", "end"] as const) {
    const geometry = resolveStructuredPrototypeFreeformGridGeometry({
      frame: FRAME,
      grid: axisGrid({
        alignment,
        itemSize: "20",
        originX: "10",
        margin: "10",
        gutter: "10",
      }),
    });
    if (geometry === null || geometry.type !== "columns") {
      throw new Error(`expected ${alignment} column geometry`);
    }
    assert.deepEqual(
      geometry.areas.map((area) => area.x),
      [expectedStarts[alignment], expectedStarts[alignment] + 30],
    );
    assert.deepEqual(
      geometry.areas.map((area) => area.width),
      [20, 20],
    );
  }
});

test("orients row areas on Y while preserving the cross-axis origin", () => {
  assert.deepEqual(
    resolveStructuredPrototypeFreeformGridGeometry({
      frame: { width: 100, height: 200 },
      grid: axisGrid({
        type: "rows",
        alignment: "start",
        itemSize: "20",
        originX: "3",
        originY: "10",
        margin: "10",
        gutter: "10",
      }),
    }),
    {
      gridId: "grid-axis",
      type: "rows",
      clip: { x: 3, y: 10, width: 97, height: 190 },
      areas: [
        { index: 0, x: 3, y: 20, width: 97, height: 20 },
        { index: 1, x: 3, y: 50, width: 97, height: 20 },
      ],
    },
  );
});

test("visible controls rendering independently of snapEnabled while preserving document order", () => {
  const geometries = resolveStructuredPrototypeFreeformGridGeometries({
    frame: FRAME,
    grids: [
      squareGrid({ id: "grid-z", snapEnabled: false }),
      axisGrid({ id: "grid-hidden", visible: false, snapEnabled: true }),
      squareGrid({ id: "grid-a", snapEnabled: false, size: "20" }),
    ],
  });

  assert.deepEqual(
    geometries.map((geometry) => geometry.gridId),
    ["grid-z", "grid-a"],
  );
  assert.equal(
    resolveStructuredPrototypeFreeformGridGeometry({
      frame: FRAME,
      grid: axisGrid({ visible: false, snapEnabled: true }),
    }),
    null,
  );
});

test("finds periodic square lines in constant work, including very small fractional sizes", () => {
  assert.deepEqual(requireSnapLine([squareGrid()], "x", 47.75), {
    gridId: "grid-square",
    gridType: "square",
    axis: "x",
    coordinate: 48,
    correction: 0.25,
    distance: 0.25,
    lineIndex: 3,
  });
  assert.equal(requireSnapLine([squareGrid()], "y", 31.75).coordinate, 32);

  const tiny = requireSnapLine(
    [squareGrid({ originX: "0.0001", originY: "0.0001", size: "0.0001" })],
    "x",
    2048.00004,
    { width: 4096, height: 4096 },
  );
  assert.ok(tiny.lineIndex > 20_000_000);
  assert.ok(Math.abs(tiny.coordinate - 2048) < 1e-9);
  assert.ok(Math.abs(tiny.distance - 0.00004) < 1e-9);
});

test("uses a non-zero square origin as the lineIndex zero snap line", () => {
  const line = requireSnapLine(
    [squareGrid({ originX: "7.5", originY: "3.25", size: "20" })],
    "x",
    7.6,
  );
  assert.equal(line.gridId, "grid-square");
  assert.equal(line.gridType, "square");
  assert.equal(line.axis, "x");
  assert.equal(line.coordinate, 7.5);
  assert.ok(Math.abs(line.correction + 0.1) < 1e-12);
  assert.ok(Math.abs(line.distance - 0.1) < 1e-12);
  assert.equal(line.lineIndex, 0);
});

test("keeps columns on X and rows on Y", () => {
  const columns = axisGrid({
    id: "columns",
    type: "columns",
    alignment: "start",
    itemSize: "20",
    margin: "10",
  });
  const rows = axisGrid({
    id: "rows",
    type: "rows",
    alignment: "start",
    itemSize: "20",
    margin: "10",
  });

  assert.equal(requireSnapLine([columns], "x", 11).coordinate, 10);
  assert.equal(
    resolveStructuredPrototypeNearestFreeformGridSnapLine({
      frame: FRAME,
      grids: [columns],
      axis: "y",
      coordinate: 11,
    }),
    null,
  );
  assert.equal(requireSnapLine([rows], "y", 11).coordinate, 10);
  assert.equal(
    resolveStructuredPrototypeNearestFreeformGridSnapLine({
      frame: FRAME,
      grids: [rows],
      axis: "x",
      coordinate: 11,
    }),
    null,
  );
});

test("snapEnabled controls lookup independently of visible", () => {
  const hiddenSnapGrid = squareGrid({
    id: "hidden-snap",
    visible: false,
    snapEnabled: true,
    size: "20",
  });
  const visibleDisplayOnlyGrid = squareGrid({
    id: "visible-only",
    visible: true,
    snapEnabled: false,
    size: "25",
  });

  assert.equal(
    requireSnapLine([visibleDisplayOnlyGrid, hiddenSnapGrid], "x", 39).gridId,
    "hidden-snap",
  );
  assert.equal(
    resolveStructuredPrototypeNearestFreeformGridSnapLine({
      frame: FRAME,
      grids: [visibleDisplayOnlyGrid],
      axis: "x",
      coordinate: 39,
    }),
    null,
  );
});

test("resolves equal distances by grid ID then line coordinate regardless of input order", () => {
  const alpha = squareGrid({ id: "grid-a", originX: "4", size: "16" });
  const zeta = squareGrid({ id: "grid-z", size: "16" });
  const forward = requireSnapLine([zeta, alpha], "x", 50);
  const reverse = requireSnapLine([alpha, zeta], "x", 50);

  assert.deepEqual(forward, reverse);
  assert.equal(forward.gridId, "grid-a");
  assert.equal(forward.coordinate, 52);

  const sameGridTie = requireSnapLine([squareGrid({ size: "20" })], "x", 30);
  assert.equal(sameGridTie.coordinate, 20);
});

test("preserves fractional track geometry and nearest boundaries", () => {
  const grid = axisGrid({
    alignment: "center",
    itemSize: "10.25",
    gutter: "2.5",
    margin: "1.25",
    originX: "0.5",
  });
  const geometry = resolveStructuredPrototypeFreeformGridGeometry({ frame: FRAME, grid });
  if (geometry === null || geometry.type !== "columns") {
    throw new Error("expected fractional column geometry");
  }
  assert.equal(geometry.areas[0]?.x, 88.75);
  assert.equal(geometry.areas[1]?.x, 101.5);
  assert.equal(requireSnapLine([grid], "x", 88.7).coordinate, 88.75);
});

test("rejects invalid geometry instead of returning non-finite or zero areas", () => {
  assert.throws(
    () =>
      resolveStructuredPrototypeFreeformGridGeometry({
        frame: { width: Number.POSITIVE_INFINITY, height: 100 },
        grid: squareGrid(),
      }),
    /frame width must be finite/,
  );
  assert.throws(
    () =>
      resolveStructuredPrototypeFreeformGridGeometry({
        frame: FRAME,
        grid: squareGrid({ size: "0" }),
      }),
    /square size must be positive/,
  );
  assert.throws(
    () =>
      resolveStructuredPrototypeFreeformGridGeometry({
        frame: FRAME,
        grid: axisGrid({ alignment: "stretch", itemSize: "20" }),
      }),
    /stretch alignment requires a null item size/,
  );
  assert.throws(
    () =>
      resolveStructuredPrototypeFreeformGridGeometries({
        frame: FRAME,
        grids: [squareGrid({ id: "duplicate" }), axisGrid({ id: "duplicate" })],
      }),
    /id is duplicated/,
  );
});
