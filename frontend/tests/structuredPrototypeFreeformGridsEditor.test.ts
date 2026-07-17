import assert from "node:assert/strict";
import test from "node:test";

import { changeStructuredPrototypeFreeformGridType } from "../src/features/prototype/structured/StructuredPrototypeFreeformGridsEditor";
import type { StructuredPrototypeSquareGrid } from "../src/features/prototype/structured/types";

test("changing a grid type preserves its envelope and resets its kind-specific params", () => {
  const grid: StructuredPrototypeSquareGrid = {
    id: "00000000-0000-4000-8000-000000000031",
    version: 1,
    type: "square",
    visible: false,
    snapEnabled: false,
    origin: { x: "12.5", y: "8.75" },
    params: {
      size: "0.3",
      colorTokenKey: "grid-accent",
      opacity: "0.65",
    },
  };

  const changed = changeStructuredPrototypeFreeformGridType(grid, "rows");

  assert.deepEqual(changed, {
    id: grid.id,
    version: grid.version,
    type: "rows",
    visible: grid.visible,
    snapEnabled: grid.snapEnabled,
    origin: grid.origin,
    params: {
      count: 12,
      itemSize: null,
      gutter: "8",
      margin: "0",
      alignment: "stretch",
      colorTokenKey: "grid-accent",
      opacity: "0.1",
    },
  });
  assert.notEqual(changed.origin, grid.origin);
});
