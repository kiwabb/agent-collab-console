import {
  isStructuredPrototypeContainerNode,
  type StructuredPrototypeContainerNode,
} from "./structuredPrototypeNodes";
import type { StructuredPrototypeFreeformPosition, StructuredPrototypeNode } from "./types";

const LAYER_DRAG_ID_PREFIX = "prototype-layer:drag:";
const LAYER_DROP_ID_PREFIX = "prototype-layer:drop:";

export interface StructuredPrototypeLayerRowModel {
  node: StructuredPrototypeNode;
  parentId: string | null;
  index: number;
  depth: number;
  ancestorNodeIds: readonly string[];
}

export interface StructuredPrototypeLayerTreeState {
  rows: readonly StructuredPrototypeLayerRowModel[];
  effectiveExpandedNodeIds: ReadonlySet<string>;
  visibleRows: readonly StructuredPrototypeLayerRowModel[];
}

export type StructuredPrototypeLayerTreeKeyboardAction =
  | { kind: "focus"; nodeId: string }
  | { kind: "expand"; nodeId: string }
  | { kind: "collapse"; nodeId: string }
  | { kind: "select"; nodeId: string }
  | { kind: "rename"; nodeId: string }
  | { kind: "toggleVisibility"; nodeId: string };

export interface StructuredPrototypeLayerDragData {
  kind: "prototype-layer-drag";
  nodeId: string;
  parentId: string | null;
  index: number;
  depth: number;
  ancestorNodeIds: readonly string[];
}

export type StructuredPrototypeLayerDropIntent = "before" | "inside" | "after";

export interface StructuredPrototypeLayerDropData {
  kind: "prototype-layer-drop";
  nodeId: string;
  intent: StructuredPrototypeLayerDropIntent;
  parentId: string | null;
  index: number;
  depth: number;
  ancestorNodeIds: readonly string[];
}

export type StructuredPrototypeLayerDropRefusalReason =
  | "source-not-found"
  | "target-not-found"
  | "stale-source"
  | "stale-target"
  | "root-not-draggable"
  | "self"
  | "descendant"
  | "inside-non-container"
  | "root-relative"
  | "target-parent-invalid"
  | "cross-parent-freeform"
  | "freeform-position-missing"
  | "unchanged";

export interface StructuredPrototypeLayerDropAccepted {
  accepted: true;
  nodeId: string;
  sourceParentId: string;
  sourceIndex: number;
  targetNodeId: string;
  targetParentId: string;
  targetIndex: number;
  intent: StructuredPrototypeLayerDropIntent;
  targetPosition?: StructuredPrototypeFreeformPosition;
}

export interface StructuredPrototypeLayerDropRefused {
  accepted: false;
  reason: StructuredPrototypeLayerDropRefusalReason;
}

export type StructuredPrototypeLayerDropResolution =
  StructuredPrototypeLayerDropAccepted | StructuredPrototypeLayerDropRefused;

function appendLayerRows(
  rows: StructuredPrototypeLayerRowModel[],
  node: StructuredPrototypeNode,
  parentId: string | null,
  index: number,
  depth: number,
  ancestorNodeIds: readonly string[],
): void {
  rows.push({ node, parentId, index, depth, ancestorNodeIds });
  if (!isStructuredPrototypeContainerNode(node)) return;
  const childAncestorNodeIds = [...ancestorNodeIds, node.id];
  node.children.forEach((child, childIndex) => {
    appendLayerRows(rows, child, node.id, childIndex, depth + 1, childAncestorNodeIds);
  });
}

export function deriveStructuredPrototypeLayerRows(
  root: StructuredPrototypeNode,
): StructuredPrototypeLayerRowModel[] {
  const rows: StructuredPrototypeLayerRowModel[] = [];
  appendLayerRows(rows, root, null, 0, 0, []);
  return rows;
}

export function resolveStructuredPrototypeLayerExpandedNodeIds(
  rows: readonly StructuredPrototypeLayerRowModel[],
  locallyExpandedNodeIds: ReadonlySet<string>,
  selectedNodeId: string | null,
  locallyCollapsedNodeIds: ReadonlySet<string> = new Set(),
): ReadonlySet<string> {
  const containerNodeIds = new Set(
    rows.flatMap((row) => (isStructuredPrototypeContainerNode(row.node) ? [row.node.id] : [])),
  );
  const effective = new Set<string>();
  for (const nodeId of locallyExpandedNodeIds) {
    if (containerNodeIds.has(nodeId)) effective.add(nodeId);
  }
  if (selectedNodeId === null) return effective;
  const selectedRow = rows.find((row) => row.node.id === selectedNodeId);
  if (selectedRow === undefined) return effective;
  for (const ancestorNodeId of selectedRow.ancestorNodeIds) {
    if (containerNodeIds.has(ancestorNodeId) && !locallyCollapsedNodeIds.has(ancestorNodeId)) {
      effective.add(ancestorNodeId);
    }
  }
  return effective;
}

export function resolveStructuredPrototypeVisibleLayerRows(
  rows: readonly StructuredPrototypeLayerRowModel[],
  expandedNodeIds: ReadonlySet<string>,
): StructuredPrototypeLayerRowModel[] {
  return rows.filter((row) =>
    row.ancestorNodeIds.every((ancestorNodeId) => expandedNodeIds.has(ancestorNodeId)),
  );
}

export function deriveStructuredPrototypeLayerTreeState(
  root: StructuredPrototypeNode,
  locallyExpandedNodeIds: ReadonlySet<string>,
  selectedNodeId: string | null,
  locallyCollapsedNodeIds: ReadonlySet<string> = new Set(),
): StructuredPrototypeLayerTreeState {
  const rows = deriveStructuredPrototypeLayerRows(root);
  const effectiveExpandedNodeIds = resolveStructuredPrototypeLayerExpandedNodeIds(
    rows,
    locallyExpandedNodeIds,
    selectedNodeId,
    locallyCollapsedNodeIds,
  );
  return {
    rows,
    effectiveExpandedNodeIds,
    visibleRows: resolveStructuredPrototypeVisibleLayerRows(rows, effectiveExpandedNodeIds),
  };
}

export function resolveStructuredPrototypeLayerTreeKeyboardAction(
  visibleRows: readonly StructuredPrototypeLayerRowModel[],
  expandedNodeIds: ReadonlySet<string>,
  currentNodeId: string,
  key: string,
): StructuredPrototypeLayerTreeKeyboardAction | null {
  const currentIndex = visibleRows.findIndex((row) => row.node.id === currentNodeId);
  if (currentIndex < 0) return null;
  const current = visibleRows[currentIndex];
  if (current === undefined) return null;
  if (key === "ArrowDown") {
    const next = visibleRows[currentIndex + 1];
    return next === undefined ? null : { kind: "focus", nodeId: next.node.id };
  }
  if (key === "ArrowUp") {
    const previous = visibleRows[currentIndex - 1];
    return previous === undefined ? null : { kind: "focus", nodeId: previous.node.id };
  }
  if (key === "Home") {
    const first = visibleRows[0];
    return first === undefined || first.node.id === currentNodeId
      ? null
      : { kind: "focus", nodeId: first.node.id };
  }
  if (key === "End") {
    const last = visibleRows.at(-1);
    return last === undefined || last.node.id === currentNodeId
      ? null
      : { kind: "focus", nodeId: last.node.id };
  }
  const container = isStructuredPrototypeContainerNode(current.node);
  if (key === "ArrowRight" && container) {
    if (!expandedNodeIds.has(currentNodeId)) return { kind: "expand", nodeId: currentNodeId };
    const firstChild = visibleRows[currentIndex + 1];
    return firstChild?.parentId === currentNodeId
      ? { kind: "focus", nodeId: firstChild.node.id }
      : null;
  }
  if (key === "ArrowLeft") {
    if (container && expandedNodeIds.has(currentNodeId)) {
      return { kind: "collapse", nodeId: currentNodeId };
    }
    return current.parentId === null ? null : { kind: "focus", nodeId: current.parentId };
  }
  if (key === "Enter" || key === " ") {
    if (current.parentId !== null) return { kind: "select", nodeId: currentNodeId };
    if (!container) return null;
    return expandedNodeIds.has(currentNodeId)
      ? { kind: "collapse", nodeId: currentNodeId }
      : { kind: "expand", nodeId: currentNodeId };
  }
  if (key === "F2" && current.parentId !== null) {
    return { kind: "rename", nodeId: currentNodeId };
  }
  if (key.toLowerCase() === "v" && current.parentId !== null) {
    return { kind: "toggleVisibility", nodeId: currentNodeId };
  }
  return null;
}

export function structuredPrototypeLayerDraggableId(nodeId: string): string {
  return `${LAYER_DRAG_ID_PREFIX}${nodeId}`;
}

export function structuredPrototypeLayerDroppableId(
  nodeId: string,
  intent: StructuredPrototypeLayerDropIntent,
): string {
  return `${LAYER_DROP_ID_PREFIX}${intent}:${nodeId}`;
}

export function createStructuredPrototypeLayerDragData(
  row: StructuredPrototypeLayerRowModel,
): StructuredPrototypeLayerDragData {
  return {
    kind: "prototype-layer-drag",
    nodeId: row.node.id,
    parentId: row.parentId,
    index: row.index,
    depth: row.depth,
    ancestorNodeIds: row.ancestorNodeIds,
  };
}

export function createStructuredPrototypeLayerDropData(
  row: StructuredPrototypeLayerRowModel,
  intent: StructuredPrototypeLayerDropIntent,
): StructuredPrototypeLayerDropData {
  return {
    kind: "prototype-layer-drop",
    nodeId: row.node.id,
    intent,
    parentId: row.parentId,
    index: row.index,
    depth: row.depth,
    ancestorNodeIds: row.ancestorNodeIds,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isLayerIndex(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isLayerDropIntent(value: unknown): value is StructuredPrototypeLayerDropIntent {
  return value === "before" || value === "inside" || value === "after";
}

export function readStructuredPrototypeLayerDragData(
  value: unknown,
): StructuredPrototypeLayerDragData | null {
  if (
    !isRecord(value) ||
    value["kind"] !== "prototype-layer-drag" ||
    typeof value["nodeId"] !== "string" ||
    !isNullableString(value["parentId"]) ||
    !isLayerIndex(value["index"]) ||
    !isLayerIndex(value["depth"]) ||
    !isStringArray(value["ancestorNodeIds"])
  ) {
    return null;
  }
  return {
    kind: "prototype-layer-drag",
    nodeId: value["nodeId"],
    parentId: value["parentId"],
    index: value["index"],
    depth: value["depth"],
    ancestorNodeIds: value["ancestorNodeIds"],
  };
}

export function readStructuredPrototypeLayerDropData(
  value: unknown,
): StructuredPrototypeLayerDropData | null {
  if (
    !isRecord(value) ||
    value["kind"] !== "prototype-layer-drop" ||
    typeof value["nodeId"] !== "string" ||
    !isLayerDropIntent(value["intent"]) ||
    !isNullableString(value["parentId"]) ||
    !isLayerIndex(value["index"]) ||
    !isLayerIndex(value["depth"]) ||
    !isStringArray(value["ancestorNodeIds"])
  ) {
    return null;
  }
  return {
    kind: "prototype-layer-drop",
    nodeId: value["nodeId"],
    intent: value["intent"],
    parentId: value["parentId"],
    index: value["index"],
    depth: value["depth"],
    ancestorNodeIds: value["ancestorNodeIds"],
  };
}

function sameStringArray(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function dataMatchesRow(
  data: StructuredPrototypeLayerDragData | StructuredPrototypeLayerDropData,
  row: StructuredPrototypeLayerRowModel,
): boolean {
  return (
    data.nodeId === row.node.id &&
    data.parentId === row.parentId &&
    data.index === row.index &&
    data.depth === row.depth &&
    sameStringArray(data.ancestorNodeIds, row.ancestorNodeIds)
  );
}

function refused(
  reason: StructuredPrototypeLayerDropRefusalReason,
): StructuredPrototypeLayerDropRefused {
  return { accepted: false, reason };
}

function targetParentForDrop(
  rowsByNodeId: ReadonlyMap<string, StructuredPrototypeLayerRowModel>,
  targetRow: StructuredPrototypeLayerRowModel,
  intent: StructuredPrototypeLayerDropIntent,
):
  | { parent: StructuredPrototypeContainerNode; targetIndex: number }
  | StructuredPrototypeLayerDropRefused {
  if (intent === "inside") {
    if (!isStructuredPrototypeContainerNode(targetRow.node)) {
      return refused("inside-non-container");
    }
    return { parent: targetRow.node, targetIndex: targetRow.node.children.length };
  }
  if (targetRow.parentId === null) return refused("root-relative");
  const parentRow = rowsByNodeId.get(targetRow.parentId);
  if (parentRow === undefined || !isStructuredPrototypeContainerNode(parentRow.node)) {
    return refused("target-parent-invalid");
  }
  return {
    parent: parentRow.node,
    targetIndex: targetRow.index + (intent === "after" ? 1 : 0),
  };
}

export function resolveStructuredPrototypeLayerDrop(
  root: StructuredPrototypeNode,
  dragged: StructuredPrototypeLayerDragData,
  target: StructuredPrototypeLayerDropData | null,
): StructuredPrototypeLayerDropResolution {
  const rows = deriveStructuredPrototypeLayerRows(root);
  const rowsByNodeId = new Map(rows.map((row) => [row.node.id, row]));
  const sourceRow = rowsByNodeId.get(dragged.nodeId);
  if (sourceRow === undefined) return refused("source-not-found");
  if (!dataMatchesRow(dragged, sourceRow)) return refused("stale-source");
  if (sourceRow.parentId === null) return refused("root-not-draggable");
  if (target === null) return refused("target-not-found");
  const targetRow = rowsByNodeId.get(target.nodeId);
  if (targetRow === undefined) return refused("target-not-found");
  if (!dataMatchesRow(target, targetRow)) return refused("stale-target");
  if (sourceRow.node.id === targetRow.node.id) return refused("self");
  if (targetRow.ancestorNodeIds.includes(sourceRow.node.id)) return refused("descendant");

  const targetParent = targetParentForDrop(rowsByNodeId, targetRow, target.intent);
  if ("accepted" in targetParent) return targetParent;
  if (targetParent.parent.type === "Freeform" && sourceRow.parentId !== targetParent.parent.id) {
    return refused("cross-parent-freeform");
  }

  const targetIndex =
    sourceRow.parentId === targetParent.parent.id && sourceRow.index < targetParent.targetIndex
      ? targetParent.targetIndex - 1
      : targetParent.targetIndex;
  if (sourceRow.parentId === targetParent.parent.id && sourceRow.index === targetIndex) {
    return refused("unchanged");
  }

  if (targetParent.parent.type === "Freeform") {
    const position = sourceRow.node.layoutItem.position;
    if (position === undefined) return refused("freeform-position-missing");
    return {
      accepted: true,
      nodeId: sourceRow.node.id,
      sourceParentId: sourceRow.parentId,
      sourceIndex: sourceRow.index,
      targetNodeId: targetRow.node.id,
      targetParentId: targetParent.parent.id,
      targetIndex,
      intent: target.intent,
      targetPosition: { ...position },
    };
  }

  return {
    accepted: true,
    nodeId: sourceRow.node.id,
    sourceParentId: sourceRow.parentId,
    sourceIndex: sourceRow.index,
    targetNodeId: targetRow.node.id,
    targetParentId: targetParent.parent.id,
    targetIndex,
    intent: target.intent,
  };
}
