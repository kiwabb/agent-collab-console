import assert from "node:assert/strict";
import test from "node:test";

import {
  resolveStructuredPrototypeFreeformGroupSelection,
  resolveStructuredPrototypeFreeformSelection,
} from "../src/features/prototype/structured/structuredPrototypeGroupSelection";
import type {
  StructuredPrototypeFreeformNode,
  StructuredPrototypeLayoutItem,
  StructuredPrototypeNode,
} from "../src/features/prototype/structured/types";

const AUTO_LAYOUT: StructuredPrototypeLayoutItem = {
  width: { unit: "auto", value: null },
  minWidth: null,
  maxWidth: null,
  height: { unit: "auto", value: null },
  minHeight: null,
  maxHeight: null,
  grow: 0,
  shrink: 1,
  alignSelf: "stretch",
};

function textNode(id: string, x?: number, y?: number): StructuredPrototypeNode {
  return {
    id,
    type: "Text",
    name: id,
    visibility: "visible",
    layoutItem:
      x === undefined || y === undefined
        ? AUTO_LAYOUT
        : { ...AUTO_LAYOUT, position: { x: String(x), y: String(y) } },
    responsive: [],
    content: id,
    semantic: "body",
    tone: "default",
  };
}

function freeform(
  id: string,
  children: StructuredPrototypeNode[],
): StructuredPrototypeFreeformNode {
  return {
    id,
    type: "Freeform",
    name: id,
    visibility: "visible",
    layoutItem: {
      ...AUTO_LAYOUT,
      width: { unit: "px", value: "800" },
      height: { unit: "px", value: "600" },
    },
    responsive: [],
    children,
  };
}

function stack(children: StructuredPrototypeNode[]): StructuredPrototypeNode {
  return {
    id: "root",
    type: "Stack",
    name: "Root",
    visibility: "visible",
    layoutItem: AUTO_LAYOUT,
    responsive: [],
    direction: "column",
    gap: 0,
    align: "stretch",
    justify: "start",
    padding: { top: 0, right: 0, bottom: 0, left: 0 },
    children,
  };
}

test("a freeform group resolves direct siblings in selection order", () => {
  const root = stack([freeform("canvas", [textNode("one", 20, 40), textNode("two", 120, 90)])]);
  const selection = resolveStructuredPrototypeFreeformGroupSelection(root, ["two", "one"]);
  assert.equal(selection?.parent.id, "canvas");
  assert.deepEqual(
    selection?.items.map(({ node, x, y }) => ({ nodeId: node.id, x, y })),
    [
      { nodeId: "two", x: 120, y: 90 },
      { nodeId: "one", x: 20, y: 40 },
    ],
  );
});

test("a freeform positioned selection resolves one direct child for keyboard nudging", () => {
  const root = stack([freeform("canvas", [textNode("one", 20, 40)])]);
  const selection = resolveStructuredPrototypeFreeformSelection(root, ["one"]);
  assert.equal(selection?.parent.id, "canvas");
  assert.deepEqual(
    selection?.items.map(({ node, x, y }) => ({ nodeId: node.id, x, y })),
    [{ nodeId: "one", x: 20, y: 40 }],
  );
});

test("a group rejects single selections, ordinary layout children, and duplicate ids", () => {
  const root = stack([textNode("one"), textNode("two")]);
  assert.equal(resolveStructuredPrototypeFreeformGroupSelection(root, ["one"]), null);
  assert.equal(resolveStructuredPrototypeFreeformGroupSelection(root, ["one", "two"]), null);
  assert.equal(resolveStructuredPrototypeFreeformGroupSelection(root, ["one", "one"]), null);
});

test("a group rejects selected nodes from different Freeform parents", () => {
  const root = stack([
    freeform("left", [textNode("one", 20, 40)]),
    freeform("right", [textNode("two", 120, 90)]),
  ]);
  assert.equal(resolveStructuredPrototypeFreeformGroupSelection(root, ["one", "two"]), null);
});
