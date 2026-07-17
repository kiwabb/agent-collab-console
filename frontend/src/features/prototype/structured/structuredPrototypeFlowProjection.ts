import type { Edge, Node, XYPosition } from "reactflow";

import { RUNTIME_FLOW_COORDINATE_LIMIT } from "../runtime/types";
import { findStructuredPrototypeNode } from "./structuredPrototypeDerived";
import type { StructuredPrototypePendingRuleConnection } from "./structuredPrototypeRuleDraft";
import type { StructuredPrototypeDocument } from "./types";

export const STRUCTURED_PROTOTYPE_FLOW_COORDINATE_LIMIT = RUNTIME_FLOW_COORDINATE_LIMIT;
export const STRUCTURED_PROTOTYPE_FLOW_GRID_COLUMNS = 3;
export const STRUCTURED_PROTOTYPE_FLOW_GRID_ORIGIN = { x: 72, y: 72 } as const;
export const STRUCTURED_PROTOTYPE_FLOW_GRID_STEP = { x: 320, y: 200 } as const;

export interface StructuredPrototypeFlowNodeData {
  pageId: string;
  title: string;
  route: string;
  incomingCount: number;
  outgoingCount: number;
}

export interface StructuredPrototypeFlowEdgeData {
  ruleId: string;
  flowKey: string;
}

export interface StructuredPrototypeFlowProjection {
  nodes: Array<Node<StructuredPrototypeFlowNodeData>>;
  edges: Array<Edge<StructuredPrototypeFlowEdgeData>>;
}

export interface StructuredPrototypeFlowPosition {
  x: number;
  y: number;
}

export function resolveStructuredPrototypePendingFlowConnection(connection: {
  source: string | null;
  target: string | null;
}): StructuredPrototypePendingRuleConnection | null {
  if (connection.source === null || connection.target === null) return null;
  return {
    kind: "pendingConnection",
    sourcePageId: connection.source,
    targetPageId: connection.target,
  };
}

function clampFlowCoordinate(value: number): number {
  return Math.min(
    STRUCTURED_PROTOTYPE_FLOW_COORDINATE_LIMIT,
    Math.max(-STRUCTURED_PROTOTYPE_FLOW_COORDINATE_LIMIT, value),
  );
}

export function normalizeStructuredPrototypeFlowPosition(
  position: StructuredPrototypeFlowPosition,
): StructuredPrototypeFlowPosition {
  if (!Number.isFinite(position.x) || !Number.isFinite(position.y)) {
    throw new Error("structured prototype flow coordinates must be finite numbers");
  }
  return {
    x: clampFlowCoordinate(Math.round(position.x)),
    y: clampFlowCoordinate(Math.round(position.y)),
  };
}

export function resolveStructuredPrototypeDefaultFlowPosition(
  pageIndex: number,
): StructuredPrototypeFlowPosition {
  if (!Number.isSafeInteger(pageIndex) || pageIndex < 0) {
    throw new Error("structured prototype flow page index must be a non-negative integer");
  }
  return {
    x:
      STRUCTURED_PROTOTYPE_FLOW_GRID_ORIGIN.x +
      (pageIndex % STRUCTURED_PROTOTYPE_FLOW_GRID_COLUMNS) * STRUCTURED_PROTOTYPE_FLOW_GRID_STEP.x,
    y:
      STRUCTURED_PROTOTYPE_FLOW_GRID_ORIGIN.y +
      Math.floor(pageIndex / STRUCTURED_PROTOTYPE_FLOW_GRID_COLUMNS) *
        STRUCTURED_PROTOTYPE_FLOW_GRID_STEP.y,
  };
}

export function findStructuredPrototypeFlowSourcePageId(
  document: StructuredPrototypeDocument,
  fromNodeId: string,
): string | null {
  for (const page of document.pages) {
    if (findStructuredPrototypeNode(page.root, fromNodeId) !== null) return page.id;
  }
  return null;
}

function authoritativeFlowPositions(
  document: StructuredPrototypeDocument,
): ReadonlyMap<string, StructuredPrototypeFlowPosition> {
  const positions = new Map<string, StructuredPrototypeFlowPosition>();
  for (const position of document.runtime.flowLayout?.nodes ?? []) {
    if (positions.has(position.nodeId)) {
      throw new Error(`structured prototype flow layout duplicates node ${position.nodeId}`);
    }
    positions.set(position.nodeId, normalizeStructuredPrototypeFlowPosition(position));
  }
  return positions;
}

export function projectStructuredPrototypeFlow(
  document: StructuredPrototypeDocument,
): StructuredPrototypeFlowProjection {
  const pagesById = new Map(document.pages.map((page) => [page.id, page]));
  const edges: Array<Edge<StructuredPrototypeFlowEdgeData>> = document.flows.map((flow) => {
    const source = findStructuredPrototypeFlowSourcePageId(document, flow.fromNodeId);
    if (source === null) {
      throw new Error(`structured prototype flow ${flow.id} references an unknown source node`);
    }
    if (flow.toPageId === null) {
      throw new Error(`structured prototype flow ${flow.id} has no navigate target page`);
    }
    const target = flow.toPageId;
    if (!pagesById.has(target)) {
      throw new Error(`structured prototype flow ${flow.id} references an unknown target page`);
    }
    return {
      id: flow.id,
      source,
      target,
      type: "smoothstep",
      animated: false,
      focusable: true,
      data: { ruleId: flow.ruleId, flowKey: flow.key },
    };
  });
  const incomingCounts = new Map<string, number>();
  const outgoingCounts = new Map<string, number>();
  for (const edge of edges) {
    outgoingCounts.set(edge.source, (outgoingCounts.get(edge.source) ?? 0) + 1);
    incomingCounts.set(edge.target, (incomingCounts.get(edge.target) ?? 0) + 1);
  }
  const savedPositions = authoritativeFlowPositions(document);
  const nodes = document.pages.map<Node<StructuredPrototypeFlowNodeData>>((page, index) => ({
    id: page.id,
    type: "prototypePage",
    position: savedPositions.get(page.id) ?? resolveStructuredPrototypeDefaultFlowPosition(index),
    data: {
      pageId: page.id,
      title: page.title,
      route: page.route,
      incomingCount: incomingCounts.get(page.id) ?? 0,
      outgoingCount: outgoingCounts.get(page.id) ?? 0,
    },
    ariaLabel: `${page.title} ${page.route}`,
  }));
  return { nodes, edges };
}

export function normalizeStructuredPrototypeFlowNodePosition(
  position: XYPosition,
): StructuredPrototypeFlowPosition {
  return normalizeStructuredPrototypeFlowPosition(position);
}
