import { STRUCTURED_PROTOTYPE_GROUP_TRANSFORM_MAX_ITEMS } from "./structuredPrototypeGroupTransform";
import {
  isStructuredPrototypeContainerNode,
  type StructuredPrototypeContainerNode,
} from "./structuredPrototypeNodes";
import type { StructuredPrototypeFreeformNode, StructuredPrototypeNode } from "./types";

export interface StructuredPrototypePositionedSelectionItem {
  node: StructuredPrototypeNode;
  x: number;
  y: number;
}

export interface StructuredPrototypePositionedSelection {
  parent: StructuredPrototypeContainerNode;
  items: StructuredPrototypePositionedSelectionItem[];
}

export type StructuredPrototypeFreeformGroupSelectionItem =
  StructuredPrototypePositionedSelectionItem;

export interface StructuredPrototypeFreeformGroupSelection {
  parent: StructuredPrototypeFreeformNode;
  items: StructuredPrototypeFreeformGroupSelectionItem[];
}

export function resolveStructuredPrototypePositionedSelection(
  root: StructuredPrototypeNode,
  nodeIds: readonly string[],
): StructuredPrototypePositionedSelection | null {
  if (nodeIds.length < 1 || nodeIds.length > STRUCTURED_PROTOTYPE_GROUP_TRANSFORM_MAX_ITEMS) {
    return null;
  }
  const requestedNodeIds = new Set(nodeIds);
  if (requestedNodeIds.size !== nodeIds.length) return null;

  let parent: StructuredPrototypeContainerNode | null = null;
  let invalid = false;
  const itemsByNodeId = new Map<string, StructuredPrototypePositionedSelectionItem>();

  const visit = (node: StructuredPrototypeNode): void => {
    if (!isStructuredPrototypeContainerNode(node)) return;
    for (const child of node.children) {
      if (requestedNodeIds.has(child.id)) {
        const position = child.layoutItem.position;
        if (position === undefined) {
          invalid = true;
        } else if (parent !== null && parent.id !== node.id) {
          invalid = true;
        } else {
          parent = node;
          itemsByNodeId.set(child.id, {
            node: child,
            x: Number(position.x),
            y: Number(position.y),
          });
        }
      }
      visit(child);
    }
  };

  visit(root);
  if (invalid || parent === null || itemsByNodeId.size !== requestedNodeIds.size) return null;
  return {
    parent,
    items: nodeIds.map((nodeId) => {
      const item = itemsByNodeId.get(nodeId);
      if (item === undefined) {
        throw new Error(`selected node ${nodeId} was not resolved`);
      }
      return item;
    }),
  };
}

export function resolveStructuredPrototypePositionedGroupSelection(
  root: StructuredPrototypeNode,
  nodeIds: readonly string[],
): StructuredPrototypePositionedSelection | null {
  if (nodeIds.length < 2) return null;
  return resolveStructuredPrototypePositionedSelection(root, nodeIds);
}

export function resolveStructuredPrototypeFreeformSelection(
  root: StructuredPrototypeNode,
  nodeIds: readonly string[],
): StructuredPrototypeFreeformGroupSelection | null {
  const selection = resolveStructuredPrototypePositionedSelection(root, nodeIds);
  if (selection === null || selection.parent.type !== "Freeform") return null;
  return { parent: selection.parent, items: selection.items };
}

export function resolveStructuredPrototypeFreeformGroupSelection(
  root: StructuredPrototypeNode,
  nodeIds: readonly string[],
): StructuredPrototypeFreeformGroupSelection | null {
  if (nodeIds.length < 2) return null;
  return resolveStructuredPrototypeFreeformSelection(root, nodeIds);
}
