import assert from "node:assert/strict";
import test from "node:test";

import {
  createStructuredPrototypeLayerDragData,
  createStructuredPrototypeLayerDropData,
  deriveStructuredPrototypeLayerRows,
  deriveStructuredPrototypeLayerTreeState,
  readStructuredPrototypeLayerDragData,
  readStructuredPrototypeLayerDropData,
  resolveStructuredPrototypeLayerDrop,
  resolveStructuredPrototypeLayerTreeKeyboardAction,
  structuredPrototypeLayerDraggableId,
  structuredPrototypeLayerDroppableId,
  type StructuredPrototypeLayerDropIntent,
  type StructuredPrototypeLayerRowModel,
} from "../src/features/prototype/structured/structuredPrototypeLayerTreeModel";
import type {
  StructuredPrototypeLayoutItem,
  StructuredPrototypeNode,
} from "../src/features/prototype/structured/types";
import { readCompactSource } from "./sourceTestUtils";

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

function stack(
  id: string,
  children: StructuredPrototypeNode[],
  visibility: "visible" | "hidden" = "visible",
): StructuredPrototypeNode {
  return {
    id,
    type: "Stack",
    name: id,
    visibility,
    layoutItem: AUTO_LAYOUT,
    responsive: [],
    direction: "column",
    gap: 8,
    align: "stretch",
    justify: "start",
    padding: { top: 0, right: 0, bottom: 0, left: 0 },
    children,
  };
}

function text(id: string, position?: { x: string; y: string }): StructuredPrototypeNode {
  return {
    id,
    type: "Text",
    name: id,
    visibility: "visible",
    layoutItem: position === undefined ? AUTO_LAYOUT : { ...AUTO_LAYOUT, position },
    responsive: [],
    content: id,
    semantic: "body",
    tone: "default",
  };
}

function freeform(id: string, children: StructuredPrototypeNode[]): StructuredPrototypeNode {
  return {
    id,
    type: "Freeform",
    name: id,
    visibility: "visible",
    layoutItem: AUTO_LAYOUT,
    responsive: [],
    children,
  };
}

function layerRoot(): StructuredPrototypeNode {
  return stack("root", [
    stack("hidden-stack", [text("nested-text")], "hidden"),
    text("outside-text"),
    freeform("freeform", [
      text("free-a", { x: "10", y: "20" }),
      text("free-b", { x: "30", y: "40" }),
    ]),
  ]);
}

function rowsById(root: StructuredPrototypeNode): Map<string, StructuredPrototypeLayerRowModel> {
  return new Map(deriveStructuredPrototypeLayerRows(root).map((row) => [row.node.id, row]));
}

function requireRow(
  rows: ReadonlyMap<string, StructuredPrototypeLayerRowModel>,
  nodeId: string,
): StructuredPrototypeLayerRowModel {
  const row = rows.get(nodeId);
  if (row === undefined) throw new Error(`missing layer row ${nodeId}`);
  return row;
}

test("layer rows are a complete preorder hierarchy, including hidden nodes", () => {
  const rows = deriveStructuredPrototypeLayerRows(layerRoot());
  assert.deepEqual(
    rows.map((row) => ({
      nodeId: row.node.id,
      parentId: row.parentId,
      index: row.index,
      depth: row.depth,
      ancestorNodeIds: row.ancestorNodeIds,
      visibility: row.node.visibility,
    })),
    [
      {
        nodeId: "root",
        parentId: null,
        index: 0,
        depth: 0,
        ancestorNodeIds: [],
        visibility: "visible",
      },
      {
        nodeId: "hidden-stack",
        parentId: "root",
        index: 0,
        depth: 1,
        ancestorNodeIds: ["root"],
        visibility: "hidden",
      },
      {
        nodeId: "nested-text",
        parentId: "hidden-stack",
        index: 0,
        depth: 2,
        ancestorNodeIds: ["root", "hidden-stack"],
        visibility: "visible",
      },
      {
        nodeId: "outside-text",
        parentId: "root",
        index: 1,
        depth: 1,
        ancestorNodeIds: ["root"],
        visibility: "visible",
      },
      {
        nodeId: "freeform",
        parentId: "root",
        index: 2,
        depth: 1,
        ancestorNodeIds: ["root"],
        visibility: "visible",
      },
      {
        nodeId: "free-a",
        parentId: "freeform",
        index: 0,
        depth: 2,
        ancestorNodeIds: ["root", "freeform"],
        visibility: "visible",
      },
      {
        nodeId: "free-b",
        parentId: "freeform",
        index: 1,
        depth: 2,
        ancestorNodeIds: ["root", "freeform"],
        visibility: "visible",
      },
    ],
  );
});

test("selected ancestors join effective expansion without mutating local expansion", () => {
  const locallyExpanded = new Set(["root"]);
  const nestedState = deriveStructuredPrototypeLayerTreeState(
    layerRoot(),
    locallyExpanded,
    "nested-text",
  );
  assert.deepEqual([...nestedState.effectiveExpandedNodeIds], ["root", "hidden-stack"]);
  assert.deepEqual(
    nestedState.visibleRows.map((row) => row.node.id),
    ["root", "hidden-stack", "nested-text", "outside-text", "freeform"],
  );
  assert.deepEqual([...locallyExpanded], ["root"]);

  const freeformState = deriveStructuredPrototypeLayerTreeState(
    layerRoot(),
    locallyExpanded,
    "free-b",
  );
  assert.deepEqual([...freeformState.effectiveExpandedNodeIds], ["root", "freeform"]);
  assert.deepEqual(
    freeformState.visibleRows.map((row) => row.node.id),
    ["root", "hidden-stack", "outside-text", "freeform", "free-a", "free-b"],
  );

  const collapsed = deriveStructuredPrototypeLayerTreeState(layerRoot(), new Set(), null);
  assert.deepEqual(
    collapsed.visibleRows.map((row) => row.node.id),
    ["root"],
  );
});

test("an explicit collapse overrides auto-expansion until the selected node changes", () => {
  const state = deriveStructuredPrototypeLayerTreeState(
    layerRoot(),
    new Set(["root"]),
    "nested-text",
    new Set(["hidden-stack"]),
  );
  assert.deepEqual([...state.effectiveExpandedNodeIds], ["root"]);
  assert.deepEqual(
    state.visibleRows.map((row) => row.node.id),
    ["root", "hidden-stack", "outside-text", "freeform"],
  );
});

test("tree keyboard actions follow the visible roving-focus hierarchy", () => {
  const root = layerRoot();
  const collapsed = deriveStructuredPrototypeLayerTreeState(root, new Set(["root"]), null);
  assert.deepEqual(
    resolveStructuredPrototypeLayerTreeKeyboardAction(
      collapsed.visibleRows,
      collapsed.effectiveExpandedNodeIds,
      "root",
      "ArrowDown",
    ),
    { kind: "focus", nodeId: "hidden-stack" },
  );
  assert.deepEqual(
    resolveStructuredPrototypeLayerTreeKeyboardAction(
      collapsed.visibleRows,
      collapsed.effectiveExpandedNodeIds,
      "hidden-stack",
      "ArrowRight",
    ),
    { kind: "expand", nodeId: "hidden-stack" },
  );
  assert.deepEqual(
    resolveStructuredPrototypeLayerTreeKeyboardAction(
      collapsed.visibleRows,
      collapsed.effectiveExpandedNodeIds,
      "hidden-stack",
      "F2",
    ),
    { kind: "rename", nodeId: "hidden-stack" },
  );
  assert.deepEqual(
    resolveStructuredPrototypeLayerTreeKeyboardAction(
      collapsed.visibleRows,
      collapsed.effectiveExpandedNodeIds,
      "hidden-stack",
      "v",
    ),
    { kind: "toggleVisibility", nodeId: "hidden-stack" },
  );
  assert.deepEqual(
    resolveStructuredPrototypeLayerTreeKeyboardAction(
      collapsed.visibleRows,
      collapsed.effectiveExpandedNodeIds,
      "root",
      "Enter",
    ),
    { kind: "collapse", nodeId: "root" },
  );

  const expanded = deriveStructuredPrototypeLayerTreeState(
    root,
    new Set(["root", "hidden-stack"]),
    null,
  );
  assert.deepEqual(
    resolveStructuredPrototypeLayerTreeKeyboardAction(
      expanded.visibleRows,
      expanded.effectiveExpandedNodeIds,
      "hidden-stack",
      "ArrowRight",
    ),
    { kind: "focus", nodeId: "nested-text" },
  );
  assert.deepEqual(
    resolveStructuredPrototypeLayerTreeKeyboardAction(
      expanded.visibleRows,
      expanded.effectiveExpandedNodeIds,
      "nested-text",
      "ArrowLeft",
    ),
    { kind: "focus", nodeId: "hidden-stack" },
  );
  assert.deepEqual(
    resolveStructuredPrototypeLayerTreeKeyboardAction(
      expanded.visibleRows,
      expanded.effectiveExpandedNodeIds,
      "hidden-stack",
      "ArrowLeft",
    ),
    { kind: "collapse", nodeId: "hidden-stack" },
  );
  assert.deepEqual(
    resolveStructuredPrototypeLayerTreeKeyboardAction(
      expanded.visibleRows,
      expanded.effectiveExpandedNodeIds,
      "root",
      "End",
    ),
    { kind: "focus", nodeId: "freeform" },
  );
});

test("layer drag and drop identities are namespaced, distinct, and boundary parsed", () => {
  const rows = rowsById(layerRoot());
  const row = requireRow(rows, "free-a");
  const drag = createStructuredPrototypeLayerDragData(row);
  const drop = createStructuredPrototypeLayerDropData(row, "inside");

  assert.equal(structuredPrototypeLayerDraggableId(row.node.id), "prototype-layer:drag:free-a");
  assert.equal(
    structuredPrototypeLayerDroppableId(row.node.id, "after"),
    "prototype-layer:drop:after:free-a",
  );
  assert.equal(drag.kind, "prototype-layer-drag");
  assert.equal(drop.kind, "prototype-layer-drop");
  assert.deepEqual(readStructuredPrototypeLayerDragData(drag), drag);
  assert.deepEqual(readStructuredPrototypeLayerDropData(drop), drop);
  assert.equal(readStructuredPrototypeLayerDragData({ ...drag, ancestorNodeIds: "root" }), null);
  assert.equal(readStructuredPrototypeLayerDropData({ ...drop, intent: "around" }), null);
  assert.equal(readStructuredPrototypeLayerDropData(drag), null);
});

test("same-parent Freeform reorder preserves canonical position and refuses no-op order", () => {
  const root = layerRoot();
  const rows = rowsById(root);
  const freeA = createStructuredPrototypeLayerDragData(requireRow(rows, "free-a"));
  const afterFreeB = createStructuredPrototypeLayerDropData(requireRow(rows, "free-b"), "after");
  assert.deepEqual(resolveStructuredPrototypeLayerDrop(root, freeA, afterFreeB), {
    accepted: true,
    nodeId: "free-a",
    sourceParentId: "freeform",
    sourceIndex: 0,
    targetNodeId: "free-b",
    targetParentId: "freeform",
    targetIndex: 1,
    intent: "after",
    targetPosition: { x: "10", y: "20" },
  });

  const freeB = createStructuredPrototypeLayerDragData(requireRow(rows, "free-b"));
  const afterFreeA = createStructuredPrototypeLayerDropData(requireRow(rows, "free-a"), "after");
  assert.deepEqual(resolveStructuredPrototypeLayerDrop(root, freeB, afterFreeA), {
    accepted: false,
    reason: "unchanged",
  });
});

test("tree drops reject self, descendants, leaf-inside, and cross-parent Freeform targets", () => {
  const root = layerRoot();
  const rows = rowsById(root);
  const drag = (nodeId: string) => createStructuredPrototypeLayerDragData(requireRow(rows, nodeId));
  const drop = (nodeId: string, intent: StructuredPrototypeLayerDropIntent) =>
    createStructuredPrototypeLayerDropData(requireRow(rows, nodeId), intent);

  assert.deepEqual(
    resolveStructuredPrototypeLayerDrop(root, drag("outside-text"), drop("outside-text", "before")),
    {
      accepted: false,
      reason: "self",
    },
  );
  assert.deepEqual(
    resolveStructuredPrototypeLayerDrop(root, drag("hidden-stack"), drop("nested-text", "after")),
    {
      accepted: false,
      reason: "descendant",
    },
  );
  assert.deepEqual(
    resolveStructuredPrototypeLayerDrop(root, drag("outside-text"), drop("nested-text", "inside")),
    {
      accepted: false,
      reason: "inside-non-container",
    },
  );
  assert.deepEqual(
    resolveStructuredPrototypeLayerDrop(root, drag("nested-text"), drop("free-a", "before")),
    {
      accepted: false,
      reason: "cross-parent-freeform",
    },
  );
  assert.deepEqual(
    resolveStructuredPrototypeLayerDrop(root, drag("outside-text"), drop("root", "before")),
    {
      accepted: false,
      reason: "root-relative",
    },
  );
  assert.deepEqual(
    resolveStructuredPrototypeLayerDrop(root, drag("root"), drop("freeform", "inside")),
    {
      accepted: false,
      reason: "root-not-draggable",
    },
  );
});

test("valid cross-container drops resolve post-removal indexes and omit Freeform position", () => {
  const root = layerRoot();
  const rows = rowsById(root);
  const intoStack = resolveStructuredPrototypeLayerDrop(
    root,
    createStructuredPrototypeLayerDragData(requireRow(rows, "free-a")),
    createStructuredPrototypeLayerDropData(requireRow(rows, "hidden-stack"), "inside"),
  );
  assert.deepEqual(intoStack, {
    accepted: true,
    nodeId: "free-a",
    sourceParentId: "freeform",
    sourceIndex: 0,
    targetNodeId: "hidden-stack",
    targetParentId: "hidden-stack",
    targetIndex: 1,
    intent: "inside",
  });
  assert.equal("targetPosition" in intoStack, false);

  const beforeOutside = resolveStructuredPrototypeLayerDrop(
    root,
    createStructuredPrototypeLayerDragData(requireRow(rows, "nested-text")),
    createStructuredPrototypeLayerDropData(requireRow(rows, "outside-text"), "before"),
  );
  assert.deepEqual(beforeOutside, {
    accepted: true,
    nodeId: "nested-text",
    sourceParentId: "hidden-stack",
    sourceIndex: 0,
    targetNodeId: "outside-text",
    targetParentId: "root",
    targetIndex: 1,
    intent: "before",
  });
});

test("resolver fails closed for missing and stale drag metadata", () => {
  const root = layerRoot();
  const rows = rowsById(root);
  const source = createStructuredPrototypeLayerDragData(requireRow(rows, "outside-text"));
  const target = createStructuredPrototypeLayerDropData(requireRow(rows, "hidden-stack"), "inside");

  assert.deepEqual(
    resolveStructuredPrototypeLayerDrop(root, { ...source, nodeId: "missing" }, target),
    {
      accepted: false,
      reason: "source-not-found",
    },
  );
  assert.deepEqual(resolveStructuredPrototypeLayerDrop(root, { ...source, index: 99 }, target), {
    accepted: false,
    reason: "stale-source",
  });
  assert.deepEqual(resolveStructuredPrototypeLayerDrop(root, source, null), {
    accepted: false,
    reason: "target-not-found",
  });
  assert.deepEqual(resolveStructuredPrototypeLayerDrop(root, source, { ...target, depth: 99 }), {
    accepted: false,
    reason: "stale-target",
  });
});

test("layer tree keeps expansion local and exposes keyboard rename plus distinct drop zones", () => {
  const source = readCompactSource(
    "features/prototype/structured/StructuredPrototypeLayerTree.tsx",
  );
  assert.match(source, /ReadonlyMap<string, LocalLayerTreeViewState>/);
  assert.doesNotMatch(source, /useEffect/);
  assert.match(source, /event\.key === "Enter"/);
  assert.match(source, /event\.key === "Escape"/);
  assert.match(source, /const name = renameValue\.trim\(\)/);
  assert.match(source, /onRename: \(nodeId: string, name: string\) => Promise<boolean>/);
  assert.match(source, /const persisted = await onRename\(row\.node\.id, name\)/);
  assert.match(source, /if \(persisted\) cancelRename\(row\.node\.id\)/);
  assert.match(source, /else setRenameError\(labels\.renameFailed\)/);
  assert.match(source, /structured prototype layer rename failed:/);
  assert.match(source, /role="alert"/);
  assert.match(source, /role="tree"/);
  assert.match(source, /intent="before"/);
  assert.match(source, /intent="inside"/);
  assert.match(source, /intent="after"/);
  assert.match(source, /disabled: dragDisabled \|\| root/);
  assert.match(source, /data-prototype-layer-root-actions={root \? "structural" : "editable"}/);
  assert.match(source, /selected={row\.parentId !== null && row\.node\.id === selectedNodeId}/);
});
