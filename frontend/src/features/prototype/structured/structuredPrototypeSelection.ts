import { isStructuredPrototypeContainerNode } from "./structuredPrototypeNodes";
import type { StructuredPrototypeNode } from "./types";

export interface StructuredPrototypeSelectionPoint {
  x: number;
  y: number;
}

export interface StructuredPrototypeSelectionRect {
  top: number;
  right: number;
  bottom: number;
  left: number;
  width: number;
  height: number;
}

export interface StructuredPrototypeMarqueeCandidate {
  nodeId: string;
  ancestorNodeIds: readonly string[];
  kind: "container" | "leaf";
  rect: StructuredPrototypeSelectionRect;
}

export interface StructuredPrototypeNodeSelection {
  nodeIds: string[];
  primaryNodeId: string | null;
}

const MARQUEE_ACTIVATION_THRESHOLD = 4;

export function createStructuredPrototypeEmptySelection(): StructuredPrototypeNodeSelection {
  return { nodeIds: [], primaryNodeId: null };
}

export function normalizeStructuredPrototypeSelectionRect(
  start: StructuredPrototypeSelectionPoint,
  end: StructuredPrototypeSelectionPoint,
): StructuredPrototypeSelectionRect {
  const left = Math.min(start.x, end.x);
  const right = Math.max(start.x, end.x);
  const top = Math.min(start.y, end.y);
  const bottom = Math.max(start.y, end.y);
  return { top, right, bottom, left, width: right - left, height: bottom - top };
}

export function structuredPrototypeSelectionRectsIntersect(
  left: StructuredPrototypeSelectionRect,
  right: StructuredPrototypeSelectionRect,
): boolean {
  return !(
    left.right < right.left ||
    left.left > right.right ||
    left.bottom < right.top ||
    left.top > right.bottom
  );
}

export function structuredPrototypeSelectionRectContains(
  container: StructuredPrototypeSelectionRect,
  candidate: StructuredPrototypeSelectionRect,
): boolean {
  return (
    container.left <= candidate.left &&
    container.right >= candidate.right &&
    container.top <= candidate.top &&
    container.bottom >= candidate.bottom
  );
}

export function structuredPrototypeMarqueePassedActivationThreshold(
  startClientX: number,
  startClientY: number,
  clientX: number,
  clientY: number,
): boolean {
  return Math.hypot(clientX - startClientX, clientY - startClientY) >= MARQUEE_ACTIVATION_THRESHOLD;
}

export function resolveStructuredPrototypeOutermostCandidateNodeIds(
  candidates: readonly StructuredPrototypeMarqueeCandidate[],
  nodeIds: readonly string[],
): string[] {
  const requested = new Set(nodeIds);
  return candidates.flatMap((candidate) =>
    requested.has(candidate.nodeId) &&
    !candidate.ancestorNodeIds.some((ancestorNodeId) => requested.has(ancestorNodeId))
      ? [candidate.nodeId]
      : [],
  );
}

export function resolveStructuredPrototypeMarqueeNodeIds(
  candidates: readonly StructuredPrototypeMarqueeCandidate[],
  marquee: StructuredPrototypeSelectionRect,
): string[] {
  const matches = candidates.flatMap((candidate) => {
    const selected =
      candidate.kind === "container"
        ? structuredPrototypeSelectionRectContains(marquee, candidate.rect)
        : structuredPrototypeSelectionRectsIntersect(marquee, candidate.rect);
    return selected ? [candidate.nodeId] : [];
  });
  return resolveStructuredPrototypeOutermostCandidateNodeIds(candidates, matches);
}

export function resolveStructuredPrototypeNodeSelection(
  root: StructuredPrototypeNode,
  nodeIds: readonly string[],
  preferredPrimaryNodeId: string | null,
): StructuredPrototypeNodeSelection {
  const requested = new Set(nodeIds);
  const normalized: string[] = [];

  const visit = (node: StructuredPrototypeNode, selectedAncestor: boolean, isRoot: boolean) => {
    const selected = !isRoot && !selectedAncestor && requested.has(node.id);
    if (selected) normalized.push(node.id);
    if (!isStructuredPrototypeContainerNode(node)) return;
    for (const child of node.children) visit(child, selectedAncestor || selected, false);
  };
  visit(root, false, true);

  const primaryNodeId =
    preferredPrimaryNodeId !== null && normalized.includes(preferredPrimaryNodeId)
      ? preferredPrimaryNodeId
      : (normalized[0] ?? null);
  return { nodeIds: normalized, primaryNodeId };
}

export function toggleStructuredPrototypeNodeSelection(
  root: StructuredPrototypeNode,
  current: StructuredPrototypeNodeSelection,
  nodeId: string,
): StructuredPrototypeNodeSelection {
  if (current.nodeIds.includes(nodeId)) {
    const remaining = current.nodeIds.filter((candidateId) => candidateId !== nodeId);
    return resolveStructuredPrototypeNodeSelection(
      root,
      remaining,
      current.primaryNodeId === nodeId ? (remaining.at(-1) ?? null) : current.primaryNodeId,
    );
  }
  return resolveStructuredPrototypeNodeSelection(root, [...current.nodeIds, nodeId], nodeId);
}

export function promoteStructuredPrototypePrimarySelection(
  root: StructuredPrototypeNode,
  current: StructuredPrototypeNodeSelection,
  nodeId: string,
): StructuredPrototypeNodeSelection {
  return resolveStructuredPrototypeNodeSelection(
    root,
    current.nodeIds.includes(nodeId) ? current.nodeIds : [nodeId],
    nodeId,
  );
}
