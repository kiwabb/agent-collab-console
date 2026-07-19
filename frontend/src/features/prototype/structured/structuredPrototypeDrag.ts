import { closestCenter, pointerWithin, type CollisionDetection } from "@dnd-kit/core";

import {
  isStructuredPrototypeContainerNode,
  type StructuredPrototypeContainerNode,
} from "./structuredPrototypeNodes";
import type { StructuredPrototypePaletteType } from "./StructuredPrototypePalette";
import type { StructuredPrototypeDragMirrorCapture } from "./structuredPrototypeDragMirror";
import {
  readStructuredPrototypeLayerDragData,
  readStructuredPrototypeLayerDropData,
} from "./structuredPrototypeLayerTreeModel";
import type {
  NewStructuredPrototypeNode,
  StructuredPrototypeDocument,
  StructuredPrototypeFreeformPosition,
  StructuredPrototypeNode,
} from "./types";

const PALETTE_PREVIEW_NODE_ID_PREFIX = "prototype-palette-preview:";

export function isStructuredPrototypePalettePreviewNodeId(nodeId: string): boolean {
  return nodeId.startsWith(PALETTE_PREVIEW_NODE_ID_PREFIX);
}

export interface StructuredPrototypePaletteDragData {
  kind: "palette";
  nodeType: StructuredPrototypePaletteType;
  formDefinitionId: string | null;
}

export interface StructuredPrototypeNodeDragData {
  kind: "node";
  nodeId: string;
  parentId: string;
  index: number;
}

export interface StructuredPrototypePageDragData {
  kind: "page";
  pageId: string;
  index: number;
}

interface StructuredPrototypeDropTargetMetadata {
  ownerNodeId: string;
  depth: number;
  ancestorNodeIds: readonly string[];
}

export type StructuredPrototypeDropTarget =
  | (StructuredPrototypeDropTargetMetadata & {
      kind: "container";
      intent: "inside";
      parentId: string;
      index: number;
    })
  | (StructuredPrototypeDropTargetMetadata & {
      kind: "slot";
      intent: "before" | "after";
      parentId: string;
      index: number;
    })
  | (StructuredPrototypeDropTargetMetadata & {
      kind: "node";
      intent: "before";
      parentId: string;
      index: number;
    });

interface RemovedStructuredPrototypeNode {
  root: StructuredPrototypeNode;
  node: StructuredPrototypeNode;
}

export interface StructuredPrototypeNodeLocation {
  parentId: string;
  index: number;
  /** Move projections use null to request an explicit return to flow layout. */
  position?: StructuredPrototypeFreeformPosition | null;
}

export interface StructuredPrototypeNodeMoveProjection {
  document: StructuredPrototypeDocument;
  location: StructuredPrototypeNodeLocation;
}

export interface StructuredPrototypePageReorderProjection {
  document: StructuredPrototypeDocument;
  targetIndex: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isIndex(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isPaletteType(value: unknown): value is StructuredPrototypePaletteType {
  return ["Freeform", "Stack", "Grid", "Form", "Text", "Input", "Button", "Table"].includes(
    String(value),
  );
}

function readStructuredPrototypeDropTargetMetadata(
  value: Record<string, unknown>,
): StructuredPrototypeDropTargetMetadata | null {
  if (
    typeof value["ownerNodeId"] !== "string" ||
    !isIndex(value["depth"]) ||
    !isStringArray(value["ancestorNodeIds"])
  ) {
    return null;
  }
  return {
    ownerNodeId: value["ownerNodeId"],
    depth: value["depth"],
    ancestorNodeIds: value["ancestorNodeIds"],
  };
}

export function readStructuredPrototypePaletteDragData(
  value: unknown,
): StructuredPrototypePaletteDragData | null {
  if (!isRecord(value)) return null;
  if (
    value["kind"] !== "palette" ||
    !isPaletteType(value["nodeType"]) ||
    (value["formDefinitionId"] !== null && typeof value["formDefinitionId"] !== "string")
  ) {
    return null;
  }
  return {
    kind: "palette",
    nodeType: value["nodeType"],
    formDefinitionId: value["formDefinitionId"],
  };
}

export function readStructuredPrototypeNodeDragData(
  value: unknown,
): StructuredPrototypeNodeDragData | null {
  if (
    !isRecord(value) ||
    value["kind"] !== "node" ||
    typeof value["nodeId"] !== "string" ||
    typeof value["parentId"] !== "string" ||
    !isIndex(value["index"])
  ) {
    return null;
  }
  return {
    kind: "node",
    nodeId: value["nodeId"],
    parentId: value["parentId"],
    index: value["index"],
  };
}

export function structuredPrototypeNodeDragMatchesSelection(
  dragData: unknown,
  selectedNodeIds: readonly string[],
): boolean {
  const draggedNode = readStructuredPrototypeNodeDragData(dragData);
  return draggedNode !== null && selectedNodeIds.includes(draggedNode.nodeId);
}

export type StructuredPrototypeSelectionChromeState =
  "visible" | "hidden-during-node-drag" | "hidden-during-freeform-move";

export function resolveStructuredPrototypeSelectionChromeState(
  dragData: unknown,
  selectedNodeIds: readonly string[],
  freeformMovePhase: "idle" | "armed" | "preview" | "pending",
): StructuredPrototypeSelectionChromeState {
  if (structuredPrototypeNodeDragMatchesSelection(dragData, selectedNodeIds)) {
    return "hidden-during-node-drag";
  }
  return freeformMovePhase === "preview" || freeformMovePhase === "pending"
    ? "hidden-during-freeform-move"
    : "visible";
}

export function readStructuredPrototypeNodeDragMirrorCapture(
  value: unknown,
): StructuredPrototypeDragMirrorCapture | null {
  if (!isRecord(value) || value["kind"] !== "node") return null;
  const capture = value["captureDragMirror"];
  return typeof capture === "function" ? (capture as StructuredPrototypeDragMirrorCapture) : null;
}

export function readStructuredPrototypePageDragData(
  value: unknown,
): StructuredPrototypePageDragData | null {
  if (
    !isRecord(value) ||
    value["kind"] !== "page" ||
    typeof value["pageId"] !== "string" ||
    !isIndex(value["index"])
  ) {
    return null;
  }
  return {
    kind: "page",
    pageId: value["pageId"],
    index: value["index"],
  };
}

export function resolveStructuredPrototypeActiveLayoutNodeId(
  dragData: unknown,
  ownerNodeId: string,
  directChildren: readonly StructuredPrototypeNode[],
): string | null {
  const draggedNode = readStructuredPrototypeNodeDragData(dragData);
  if (draggedNode !== null) return draggedNode.nodeId;
  if (isStructuredPrototypePalettePreviewNodeId(ownerNodeId)) return null;
  return (
    directChildren.find((child) => isStructuredPrototypePalettePreviewNodeId(child.id))?.id ?? null
  );
}

export function readStructuredPrototypeDropTarget(
  value: unknown,
): StructuredPrototypeDropTarget | null {
  if (!isRecord(value)) return null;
  const metadata = readStructuredPrototypeDropTargetMetadata(value);
  if (metadata === null) return null;
  if (
    value["kind"] === "node" &&
    typeof value["containerId"] === "string" &&
    isIndex(value["containerIndex"])
  ) {
    return {
      ...metadata,
      kind: "container",
      intent: "inside",
      parentId: value["containerId"],
      index: value["containerIndex"],
    };
  }
  if (
    value["kind"] === "slot" &&
    (value["intent"] === "before" || value["intent"] === "after") &&
    typeof value["parentId"] === "string" &&
    isIndex(value["index"])
  ) {
    return {
      ...metadata,
      kind: "slot",
      intent: value["intent"],
      parentId: value["parentId"],
      index: value["index"],
    };
  }
  if (
    (value["kind"] !== "container" && value["kind"] !== "node") ||
    typeof value["parentId"] !== "string" ||
    !isIndex(value["index"])
  ) {
    return null;
  }
  return value["kind"] === "container"
    ? {
        ...metadata,
        kind: "container",
        intent: "inside",
        parentId: value["parentId"],
        index: value["index"],
      }
    : {
        ...metadata,
        kind: "node",
        intent: "before",
        parentId: value["parentId"],
        index: value["index"],
      };
}

export function resolveStructuredPrototypeMoveTargetIndex(
  dragged: StructuredPrototypeNodeDragData,
  target: StructuredPrototypeDropTarget,
): number {
  if (dragged.parentId === target.parentId && dragged.index < target.index) {
    return target.index - 1;
  }
  return target.index;
}

function dropTargetPriority(target: StructuredPrototypeDropTarget): number {
  if (target.kind === "slot") return target.intent === "before" ? 0 : 1;
  if (target.kind === "container") return 2;
  return 3;
}

function targetIsInsideDraggedSubtree(
  dragged: StructuredPrototypeNodeDragData | null,
  target: StructuredPrototypeDropTarget,
): boolean {
  return (
    dragged !== null &&
    (target.ownerNodeId === dragged.nodeId || target.ancestorNodeIds.includes(dragged.nodeId))
  );
}

function targetBelongsToPalettePreview(target: StructuredPrototypeDropTarget): boolean {
  return (
    isStructuredPrototypePalettePreviewNodeId(target.ownerNodeId) ||
    isStructuredPrototypePalettePreviewNodeId(target.parentId) ||
    target.ancestorNodeIds.some(isStructuredPrototypePalettePreviewNodeId)
  );
}

function compareDropTargets(
  left: StructuredPrototypeDropTarget,
  right: StructuredPrototypeDropTarget,
): number {
  const depthDifference = right.depth - left.depth;
  if (depthDifference !== 0) return depthDifference;
  const priorityDifference = dropTargetPriority(left) - dropTargetPriority(right);
  if (priorityDifference !== 0) return priorityDifference;
  const ownerDifference = left.ownerNodeId.localeCompare(right.ownerNodeId);
  if (ownerDifference !== 0) return ownerDifference;
  const parentDifference = left.parentId.localeCompare(right.parentId);
  if (parentDifference !== 0) return parentDifference;
  return left.index - right.index;
}

export const structuredPrototypeCollisionDetection: CollisionDetection = (args) => {
  const layerDrag = readStructuredPrototypeLayerDragData(args.active.data.current);
  if (layerDrag !== null) {
    const droppableContainers = args.droppableContainers.filter(
      (container) => readStructuredPrototypeLayerDropData(container.data.current) !== null,
    );
    const scopedArgs = { ...args, droppableContainers };
    return args.pointerCoordinates === null ? closestCenter(scopedArgs) : pointerWithin(scopedArgs);
  }
  const pageDrag = readStructuredPrototypePageDragData(args.active.data.current);
  const structuredDrag =
    readStructuredPrototypePaletteDragData(args.active.data.current) ??
    readStructuredPrototypeNodeDragData(args.active.data.current);
  if (pageDrag === null && structuredDrag === null) return closestCenter(args);

  const draggedNode = readStructuredPrototypeNodeDragData(args.active.data.current);
  const draggedPalette = readStructuredPrototypePaletteDragData(args.active.data.current);
  const droppableContainers = args.droppableContainers.filter((container) => {
    if (pageDrag !== null) {
      return readStructuredPrototypePageDragData(container.data.current) !== null;
    }
    const target = readStructuredPrototypeDropTarget(container.data.current);
    return (
      target !== null &&
      !targetIsInsideDraggedSubtree(draggedNode, target) &&
      !(draggedPalette !== null && targetBelongsToPalettePreview(target))
    );
  });
  const scopedArgs = { ...args, droppableContainers };

  if (args.pointerCoordinates === null) return closestCenter(scopedArgs);
  const pointerCollisions = pointerWithin(scopedArgs);
  if (pointerCollisions.length === 0) return [];
  if (pageDrag !== null) return pointerCollisions;
  const targetById = new Map(
    droppableContainers.flatMap((container) => {
      const target = readStructuredPrototypeDropTarget(container.data.current);
      return target === null ? [] : [[container.id, target] as const];
    }),
  );
  return [...pointerCollisions].sort((left, right) => {
    const leftTarget = targetById.get(left.id);
    const rightTarget = targetById.get(right.id);
    if (leftTarget === undefined || rightTarget === undefined) return 0;
    return compareDropTargets(leftTarget, rightTarget);
  });
};

function replaceContainerChildren(
  node: StructuredPrototypeContainerNode,
  children: StructuredPrototypeNode[],
): StructuredPrototypeContainerNode {
  if (node.type === "Stack") return { ...node, children };
  if (node.type === "Grid") return { ...node, children };
  if (node.type === "Freeform") return { ...node, children };
  return { ...node, children };
}

function findProjectedContainerNode(
  root: StructuredPrototypeNode,
  nodeId: string,
): StructuredPrototypeContainerNode | null {
  if (!isStructuredPrototypeContainerNode(root)) return null;
  if (root.id === nodeId) return root;
  for (const child of root.children) {
    const found = findProjectedContainerNode(child, nodeId);
    if (found !== null) return found;
  }
  return null;
}

function nodeForTargetContainer(
  node: StructuredPrototypeNode,
  parent: StructuredPrototypeContainerNode,
  targetPosition: StructuredPrototypeFreeformPosition | null | undefined,
): StructuredPrototypeNode | null {
  if (parent.type === "Freeform") {
    if (targetPosition === undefined || targetPosition === null) return null;
    return { ...node, layoutItem: { ...node.layoutItem, position: targetPosition } };
  }
  if (targetPosition === undefined) return node;
  if (targetPosition !== null) {
    return { ...node, layoutItem: { ...node.layoutItem, position: targetPosition } };
  }
  if (node.layoutItem.position === undefined) return node;
  const layoutItem = { ...node.layoutItem };
  delete layoutItem.position;
  return { ...node, layoutItem };
}

function findProjectedNodeLocation(
  root: StructuredPrototypeNode,
  nodeId: string,
): StructuredPrototypeNodeLocation | null {
  if (!isStructuredPrototypeContainerNode(root)) return null;
  for (const [index, child] of root.children.entries()) {
    if (child.id === nodeId) {
      return {
        parentId: root.id,
        index,
        ...(child.layoutItem.position === undefined ? {} : { position: child.layoutItem.position }),
      };
    }
    const nested = findProjectedNodeLocation(child, nodeId);
    if (nested !== null) return nested;
  }
  return null;
}

export function findStructuredPrototypeNodeLocation(
  document: StructuredPrototypeDocument,
  pageId: string,
  nodeId: string,
): StructuredPrototypeNodeLocation | null {
  const page = document.pages.find((candidate) => candidate.id === pageId);
  if (page === undefined || page.root.id === nodeId) return null;
  return findProjectedNodeLocation(page.root, nodeId);
}

function removeProjectedNode(
  root: StructuredPrototypeNode,
  nodeId: string,
): RemovedStructuredPrototypeNode | null {
  if (!isStructuredPrototypeContainerNode(root)) return null;
  for (const [index, child] of root.children.entries()) {
    if (child.id === nodeId) {
      return {
        root: replaceContainerChildren(
          root,
          root.children.filter((_candidate, childIndex) => childIndex !== index),
        ),
        node: child,
      };
    }
    const nested = removeProjectedNode(child, nodeId);
    if (nested !== null) {
      return {
        root: replaceContainerChildren(
          root,
          root.children.map((candidate, childIndex) =>
            childIndex === index ? nested.root : candidate,
          ),
        ),
        node: nested.node,
      };
    }
  }
  return null;
}

function insertProjectedNode(
  root: StructuredPrototypeNode,
  parentId: string,
  index: number,
  node: StructuredPrototypeNode,
): StructuredPrototypeNode | null {
  if (!isStructuredPrototypeContainerNode(root)) return null;
  if (root.id === parentId) {
    if (index > root.children.length) return null;
    const children = root.children.slice();
    children.splice(index, 0, node);
    return replaceContainerChildren(root, children);
  }
  for (const [childIndex, child] of root.children.entries()) {
    const updatedChild = insertProjectedNode(child, parentId, index, node);
    if (updatedChild !== null) {
      return replaceContainerChildren(
        root,
        root.children.map((candidate, indexInParent) =>
          indexInParent === childIndex ? updatedChild : candidate,
        ),
      );
    }
  }
  return null;
}

export function projectStructuredPrototypeNodeInsert(
  document: StructuredPrototypeDocument,
  pageId: string,
  parentId: string,
  index: number,
  node: StructuredPrototypeNode,
  targetPosition?: StructuredPrototypeFreeformPosition | null,
): StructuredPrototypeDocument | null {
  const page = document.pages.find((candidate) => candidate.id === pageId);
  if (
    page === undefined ||
    page.root.id === node.id ||
    findProjectedNodeLocation(page.root, node.id) !== null
  ) {
    return null;
  }
  const parent = findProjectedContainerNode(page.root, parentId);
  if (parent === null) return null;
  const positionedNode = nodeForTargetContainer(node, parent, targetPosition);
  if (positionedNode === null) return null;
  const root = insertProjectedNode(page.root, parentId, index, positionedNode);
  if (root === null) return null;
  return {
    ...document,
    pages: document.pages.map((candidate) =>
      candidate.id === pageId ? { ...candidate, root } : candidate,
    ),
  };
}

export function materializeStructuredPrototypePalettePreviewNode(
  node: NewStructuredPrototypeNode,
  ownerSessionId: number,
): StructuredPrototypeNode {
  const common = {
    id: `${PALETTE_PREVIEW_NODE_ID_PREFIX}${ownerSessionId}:${node.newNodeKey}`,
    name: node.name,
    visibility: node.visibility,
    layoutItem: node.layoutItem,
    responsive: node.responsive,
  };
  if (node.type === "Stack") {
    return {
      ...common,
      type: node.type,
      direction: node.direction,
      gap: node.gap,
      align: node.align,
      justify: node.justify,
      padding: node.padding,
      children: node.children.map((child) =>
        materializeStructuredPrototypePalettePreviewNode(child, ownerSessionId),
      ),
    };
  }
  if (node.type === "Grid") {
    return {
      ...common,
      type: node.type,
      columns: node.columns,
      gap: node.gap,
      padding: node.padding,
      columnOverrides: node.columnOverrides,
      children: node.children.map((child) =>
        materializeStructuredPrototypePalettePreviewNode(child, ownerSessionId),
      ),
    };
  }
  if (node.type === "Form") {
    return {
      ...common,
      type: node.type,
      formDefinitionId: node.formDefinitionId,
      gap: node.gap,
      padding: node.padding,
      children: node.children.map((child) =>
        materializeStructuredPrototypePalettePreviewNode(child, ownerSessionId),
      ),
    };
  }
  if (node.type === "Freeform") {
    return {
      ...common,
      type: node.type,
      children: node.children.map((child) =>
        materializeStructuredPrototypePalettePreviewNode(child, ownerSessionId),
      ),
    };
  }
  if (node.type === "Text") {
    return {
      ...common,
      type: node.type,
      content: node.content,
      semantic: node.semantic,
      tone: node.tone,
    };
  }
  if (node.type === "Input") {
    return {
      ...common,
      type: node.type,
      label: node.label,
      placeholder: node.placeholder,
      value: node.value,
      inputType: node.inputType,
      required: node.required,
      disabled: node.disabled,
      formDefinitionId: node.formDefinitionId,
      formFieldId: node.formFieldId,
    };
  }
  if (node.type === "Button") {
    return {
      ...common,
      type: node.type,
      label: node.label,
      variant: node.variant,
      size: node.size,
      disabled: node.disabled,
      iconName: node.iconName,
    };
  }
  return {
    ...common,
    type: node.type,
    columns: node.columns,
    rows: node.rows,
    density: node.density,
  };
}

export function projectStructuredPrototypeNodeMove(
  document: StructuredPrototypeDocument,
  pageId: string,
  nodeId: string,
  targetParentId: string,
  targetIndex: number,
  targetPosition?: StructuredPrototypeFreeformPosition | null,
): StructuredPrototypeDocument | null {
  const page = document.pages.find((candidate) => candidate.id === pageId);
  if (page === undefined || page.root.id === nodeId) return null;
  const targetParent = findProjectedContainerNode(page.root, targetParentId);
  if (targetParent === null) return null;
  const removed = removeProjectedNode(page.root, nodeId);
  if (removed === null) return null;
  const positionedNode = nodeForTargetContainer(removed.node, targetParent, targetPosition);
  if (positionedNode === null) return null;
  const root = insertProjectedNode(removed.root, targetParentId, targetIndex, positionedNode);
  if (root === null) return null;
  return {
    ...document,
    pages: document.pages.map((candidate) =>
      candidate.id === pageId ? { ...candidate, root } : candidate,
    ),
  };
}

export function projectStructuredPrototypeNodeMoveToDropTarget(
  document: StructuredPrototypeDocument,
  pageId: string,
  nodeId: string,
  target: StructuredPrototypeDropTarget,
  targetPosition?: StructuredPrototypeFreeformPosition | null,
): StructuredPrototypeNodeMoveProjection | null {
  const location = findStructuredPrototypeNodeLocation(document, pageId, nodeId);
  if (location === null) return null;
  const targetIndex = resolveStructuredPrototypeMoveTargetIndex(
    { kind: "node", nodeId, parentId: location.parentId, index: location.index },
    target,
  );
  if (nodeId === target.parentId) return null;
  const positionUnchanged =
    targetPosition === undefined ||
    (targetPosition === null
      ? location.position === undefined
      : location.position?.x === targetPosition.x && location.position.y === targetPosition.y);
  const projected = projectStructuredPrototypeNodeMove(
    document,
    pageId,
    nodeId,
    target.parentId,
    targetIndex,
    targetPosition,
  );
  if (projected === null) return null;
  if (
    location.parentId === target.parentId &&
    location.index === targetIndex &&
    positionUnchanged
  ) {
    return { document, location };
  }
  const projectedPosition = targetPosition === undefined ? location.position : targetPosition;
  return {
    document: projected,
    location: {
      parentId: target.parentId,
      index: targetIndex,
      ...(projectedPosition === undefined ? {} : { position: projectedPosition }),
    },
  };
}

export function projectStructuredPrototypePageReorder(
  document: StructuredPrototypeDocument,
  pageId: string,
  targetIndex: number,
): StructuredPrototypeDocument | null {
  const sourceIndex = document.pages.findIndex((page) => page.id === pageId);
  if (sourceIndex < 0 || targetIndex >= document.pages.length) return null;
  if (sourceIndex === targetIndex) return document;
  const page = document.pages[sourceIndex];
  if (page === undefined) return null;
  const pages = document.pages.filter((candidate) => candidate.id !== pageId);
  pages.splice(targetIndex, 0, page);
  const pageOrder = new Map(pages.map((candidate, index) => [candidate.id, index]));
  const navigationItems = document.navigation.items
    .map((item, index) => ({ item, index }))
    .sort((left, right) => {
      const pageDifference =
        (pageOrder.get(left.item.targetPageId) ?? pages.length) -
        (pageOrder.get(right.item.targetPageId) ?? pages.length);
      return pageDifference === 0 ? left.index - right.index : pageDifference;
    })
    .map(({ item }) => item);
  return { ...document, pages, navigation: { ...document.navigation, items: navigationItems } };
}

export function projectStructuredPrototypePageReorderByTargetPageId(
  document: StructuredPrototypeDocument,
  pageId: string,
  targetPageId: string,
): StructuredPrototypePageReorderProjection | null {
  const targetIndex = document.pages.findIndex((page) => page.id === targetPageId);
  if (targetIndex < 0) return null;
  const projected = projectStructuredPrototypePageReorder(document, pageId, targetIndex);
  return projected === null ? null : { document: projected, targetIndex };
}
