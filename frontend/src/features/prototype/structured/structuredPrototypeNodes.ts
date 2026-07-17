import type {
  StructuredPrototypeFreeformNode,
  StructuredPrototypeFormNode,
  StructuredPrototypeGridNode,
  StructuredPrototypeLayoutItem,
  StructuredPrototypeNode,
  StructuredPrototypeStackNode,
} from "./types";

export type StructuredPrototypeContainerNode =
  | StructuredPrototypeStackNode
  | StructuredPrototypeGridNode
  | StructuredPrototypeFormNode
  | StructuredPrototypeFreeformNode;

export function isStructuredPrototypeContainerNode(
  node: StructuredPrototypeNode,
): node is StructuredPrototypeContainerNode {
  return (
    node.type === "Stack" ||
    node.type === "Grid" ||
    node.type === "Form" ||
    node.type === "Freeform"
  );
}

export function resolveStructuredPrototypeGridColumns(
  node: StructuredPrototypeGridNode,
  viewportWidth: number,
): number {
  let columns = node.columns;
  for (const override of node.columnOverrides) {
    if (override.minWidth > viewportWidth) break;
    columns = override.columns;
  }
  return columns;
}

const RESPONSIVE_BREAKPOINT_WIDTHS = { sm: 640, md: 768, lg: 1024 } as const;

export function resolveStructuredPrototypeLayoutItem(
  node: StructuredPrototypeNode,
  viewportWidth: number,
): StructuredPrototypeLayoutItem {
  let layoutItem = node.layoutItem;
  for (const override of node.responsive) {
    if (RESPONSIVE_BREAKPOINT_WIDTHS[override.breakpoint] > viewportWidth) continue;
    layoutItem = { ...layoutItem, ...override.layoutItem };
  }
  return layoutItem;
}
