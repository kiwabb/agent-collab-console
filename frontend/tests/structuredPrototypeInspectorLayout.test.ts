import assert from "node:assert/strict";
import test from "node:test";

import {
  addStructuredPrototypeGridColumnOverride,
  addStructuredPrototypeResponsiveOverride,
  defaultStructuredPrototypeLength,
  parseStructuredPrototypeInteger,
  parseStructuredPrototypeLength,
  setStructuredPrototypeGridColumnOverride,
  setStructuredPrototypeResponsiveBreakpoint,
  setStructuredPrototypeResponsiveLayoutField,
  setStructuredPrototypeResponsiveLayoutItem,
} from "../src/features/prototype/structured/structuredPrototypeInspectorLayout";
import type { StructuredPrototypeResponsiveOverride } from "../src/features/prototype/structured/types";

test("structured length inputs preserve canonical units and reject invalid raw values", () => {
  assert.deepEqual(defaultStructuredPrototypeLength("auto"), { unit: "auto", value: null });
  assert.deepEqual(defaultStructuredPrototypeLength("percent"), {
    unit: "percent",
    value: "100",
  });
  assert.deepEqual(parseStructuredPrototypeLength("px", "12.34567"), {
    unit: "px",
    value: "12.3457",
  });
  assert.equal(parseStructuredPrototypeLength("px", ""), null);
  assert.equal(parseStructuredPrototypeLength("px", "-1"), null);
  assert.equal(parseStructuredPrototypeLength("percent", "100.01"), null);
  assert.equal(parseStructuredPrototypeInteger("3.5", 1, 12), null);
  assert.equal(parseStructuredPrototypeInteger("12", 1, 12), 12);
});

test("responsive overrides add in canonical order and reject duplicates or bad indexes", () => {
  const initial: StructuredPrototypeResponsiveOverride[] = [
    { breakpoint: "lg", layoutItem: { width: { unit: "px", value: "960" } } },
  ];
  const withSmall = addStructuredPrototypeResponsiveOverride(initial);
  assert.deepEqual(
    withSmall?.map((override) => override.breakpoint),
    ["sm", "lg"],
  );
  assert.ok(withSmall);
  const complete = addStructuredPrototypeResponsiveOverride(withSmall);
  assert.deepEqual(
    complete?.map((override) => override.breakpoint),
    ["sm", "md", "lg"],
  );
  assert.ok(complete);
  assert.equal(addStructuredPrototypeResponsiveOverride(complete), null);
  assert.equal(setStructuredPrototypeResponsiveBreakpoint(complete, 0, "md"), null);
  assert.equal(setStructuredPrototypeResponsiveBreakpoint(complete, -1, "sm"), null);
  assert.equal(setStructuredPrototypeResponsiveBreakpoint(complete, 0.5, "sm"), null);
  assert.equal(setStructuredPrototypeResponsiveLayoutItem(complete, 99, { grow: 1 }), null);
  assert.equal(setStructuredPrototypeResponsiveLayoutItem(complete, 0, {}), null);
});

test("responsive layout fields distinguish inherit, clear, and value states", () => {
  const initial: StructuredPrototypeResponsiveOverride[] = [
    { breakpoint: "sm", layoutItem: { width: { unit: "percent", value: "100" } } },
  ];
  const withClearedConstraint = setStructuredPrototypeResponsiveLayoutField(
    initial,
    0,
    "minWidth",
    null,
  );
  assert.deepEqual(withClearedConstraint, [
    {
      breakpoint: "sm",
      layoutItem: {
        width: { unit: "percent", value: "100" },
        minWidth: null,
      },
    },
  ]);
  assert.ok(withClearedConstraint);
  const inheritedWidth = setStructuredPrototypeResponsiveLayoutField(
    withClearedConstraint,
    0,
    "width",
    undefined,
  );
  assert.deepEqual(inheritedWidth, [{ breakpoint: "sm", layoutItem: { minWidth: null } }]);
  assert.ok(inheritedWidth);
  assert.deepEqual(
    setStructuredPrototypeResponsiveLayoutField(inheritedWidth, 0, "minWidth", undefined),
    [],
  );
});

test("Grid override insertion remains monotonic when the last breakpoint is 2560", () => {
  assert.deepEqual(addStructuredPrototypeGridColumnOverride([], 2), [
    { minWidth: 640, columns: 3 },
  ]);
  assert.deepEqual(addStructuredPrototypeGridColumnOverride([{ minWidth: 2560, columns: 3 }], 2), [
    { minWidth: 640, columns: 3 },
    { minWidth: 2560, columns: 3 },
  ]);
});

test("Grid override setters enforce index, uniqueness, bounds, and the three-row limit", () => {
  const overrides = [
    { minWidth: 640, columns: 2 },
    { minWidth: 1024, columns: 4 },
  ];
  assert.equal(
    setStructuredPrototypeGridColumnOverride(overrides, -1, {
      minWidth: 768,
      columns: 3,
    }),
    null,
  );
  assert.equal(
    setStructuredPrototypeGridColumnOverride(overrides, 0.5, {
      minWidth: 768,
      columns: 3,
    }),
    null,
  );
  assert.equal(
    setStructuredPrototypeGridColumnOverride(overrides, 0, {
      minWidth: 1024,
      columns: 3,
    }),
    null,
  );
  assert.equal(
    setStructuredPrototypeGridColumnOverride(overrides, 0, {
      minWidth: 319,
      columns: 3,
    }),
    null,
  );
  assert.equal(
    setStructuredPrototypeGridColumnOverride(overrides, 0, {
      minWidth: 768,
      columns: 13,
    }),
    null,
  );
  assert.deepEqual(
    setStructuredPrototypeGridColumnOverride(overrides, 0, {
      minWidth: 1280,
      columns: 6,
    }),
    [
      { minWidth: 1024, columns: 4 },
      { minWidth: 1280, columns: 6 },
    ],
  );
  assert.equal(
    addStructuredPrototypeGridColumnOverride(
      [
        { minWidth: 640, columns: 2 },
        { minWidth: 768, columns: 3 },
        { minWidth: 1024, columns: 4 },
      ],
      1,
    ),
    null,
  );
});
