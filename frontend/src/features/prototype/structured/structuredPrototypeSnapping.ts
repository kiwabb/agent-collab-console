import {
  resolveStructuredPrototypeNearestFreeformGridSnapLine,
  type StructuredPrototypeFreeformGridSnapLine,
} from "./structuredPrototypeGridGeometry";
import {
  resolveStructuredPrototypeFreeformSpacingSnap,
  type StructuredPrototypeFreeformSpacingGuide,
  type StructuredPrototypeFreeformSpacingSnapCandidate,
} from "./structuredPrototypeSpacingSnapping";
import type { StructuredPrototypeFreeformGrid } from "./types";

export const STRUCTURED_PROTOTYPE_FREEFORM_SNAP_THRESHOLD_CLIENT_PX = 6;

export interface StructuredPrototypeFreeformSnapPoint {
  x: number;
  y: number;
}

/**
 * A single Freeform node frame or the union frame for a multi-node selection.
 */
export interface StructuredPrototypeFreeformSnapBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface StructuredPrototypeFreeformSnapSibling extends StructuredPrototypeFreeformSnapBounds {
  nodeId: string;
}

export type StructuredPrototypeFreeformSnapAxis = "x" | "y";

export type StructuredPrototypeFreeformSnapTargetKind = "container" | "sibling" | "grid";

export type StructuredPrototypeFreeformSnapAnchor =
  "left" | "center" | "right" | "top" | "middle" | "bottom";

export interface StructuredPrototypeFreeformSnapGuide {
  axis: StructuredPrototypeFreeformSnapAxis;
  coordinate: number;
  movingAnchor: StructuredPrototypeFreeformSnapAnchor;
  targetAnchor: StructuredPrototypeFreeformSnapAnchor;
  targetKind: StructuredPrototypeFreeformSnapTargetKind;
  targetNodeId: string | null;
  gridId?: string;
  gridType?: StructuredPrototypeFreeformGrid["type"];
  gridLineIndex?: number;
}

export interface StructuredPrototypeFreeformMoveSnapInput {
  selectionBounds: StructuredPrototypeFreeformSnapBounds;
  selectedNodeIds: readonly string[];
  requestedDelta: StructuredPrototypeFreeformSnapPoint;
  containerWidth: number;
  containerHeight: number;
  previewScale: number;
  /** Direct children of the selection's Freeform container. Selected IDs are ignored. */
  directSiblings: readonly StructuredPrototypeFreeformSnapSibling[];
  grids?: readonly Readonly<StructuredPrototypeFreeformGrid>[];
  gridSnappingEnabled?: boolean;
}

export interface StructuredPrototypeFreeformMoveSnapResult {
  delta: StructuredPrototypeFreeformSnapPoint;
  position: StructuredPrototypeFreeformSnapPoint;
  guides: readonly StructuredPrototypeFreeformSnapGuide[];
  spacingGuides: readonly StructuredPrototypeFreeformSpacingGuide[];
  diagnostics: StructuredPrototypeFreeformMoveSnapDiagnostics;
}

export type StructuredPrototypeFreeformSnapDiagnosticAxisWinner =
  "raw" | "alignment" | "spacing" | "grid";

export type StructuredPrototypeFreeformSnapDiagnosticCandidateOutcome =
  "winner" | "farther" | "tiePriority" | "crossAxisInvalid";

interface StructuredPrototypeFreeformSnapDiagnosticCandidateBase {
  readonly axis: StructuredPrototypeFreeformSnapAxis;
  readonly source: "alignment" | "spacing" | "grid";
  readonly position: number;
  readonly correction: number;
  readonly distance: number;
  readonly outcome: StructuredPrototypeFreeformSnapDiagnosticCandidateOutcome;
  /** Stable identity for the source's already-ranked best candidate. */
  readonly sortKey: string;
}

export interface StructuredPrototypeFreeformAlignmentSnapDiagnosticCandidate extends StructuredPrototypeFreeformSnapDiagnosticCandidateBase {
  readonly source: "alignment";
  readonly coordinate: number;
  readonly movingAnchor: StructuredPrototypeFreeformSnapAnchor;
  readonly targetAnchor: StructuredPrototypeFreeformSnapAnchor;
  readonly targetKind: Exclude<StructuredPrototypeFreeformSnapTargetKind, "grid">;
  readonly targetNodeId: string | null;
}

export interface StructuredPrototypeFreeformSpacingSnapDiagnosticCandidate extends StructuredPrototypeFreeformSnapDiagnosticCandidateBase {
  readonly source: "spacing";
  readonly placement: StructuredPrototypeFreeformSpacingSnapCandidate["placement"];
  readonly gap: number;
  readonly referenceNodeIds: readonly [string, string];
}

export interface StructuredPrototypeFreeformGridSnapDiagnosticCandidate extends StructuredPrototypeFreeformSnapDiagnosticCandidateBase {
  readonly source: "grid";
  readonly gridId: string;
  readonly gridType: StructuredPrototypeFreeformGrid["type"];
  readonly gridLineIndex: number;
  readonly coordinate: number;
  readonly movingAnchor: StructuredPrototypeFreeformSnapAnchor;
}

export type StructuredPrototypeFreeformSnapDiagnosticCandidate =
  | StructuredPrototypeFreeformAlignmentSnapDiagnosticCandidate
  | StructuredPrototypeFreeformSpacingSnapDiagnosticCandidate
  | StructuredPrototypeFreeformGridSnapDiagnosticCandidate;

export interface StructuredPrototypeFreeformMoveSnapDiagnostics {
  readonly rawPosition: StructuredPrototypeFreeformSnapPoint;
  readonly threshold: number;
  readonly axisWinners: Readonly<{
    x: StructuredPrototypeFreeformSnapDiagnosticAxisWinner;
    y: StructuredPrototypeFreeformSnapDiagnosticAxisWinner;
  }>;
  readonly candidates: readonly StructuredPrototypeFreeformSnapDiagnosticCandidate[];
}

type StructuredPrototypeFreeformHorizontalSnapAnchor = "left" | "center" | "right";
type StructuredPrototypeFreeformVerticalSnapAnchor = "top" | "middle" | "bottom";

interface StructuredPrototypeFreeformSnapCandidate {
  coordinate: number;
  correction: number;
  distance: number;
  movingAnchor: StructuredPrototypeFreeformSnapAnchor;
  targetAnchor: StructuredPrototypeFreeformSnapAnchor;
  targetKind: StructuredPrototypeFreeformSnapTargetKind;
  targetNodeId: string | null;
}

export interface StructuredPrototypeFreeformAxisSnapResult {
  readonly position: number;
  readonly distance: number | null;
  readonly guide: StructuredPrototypeFreeformSnapGuide | null;
}

export interface StructuredPrototypeFreeformResolvedAxisSnap {
  readonly position: number;
  readonly guide: StructuredPrototypeFreeformSnapGuide | null;
  readonly spacingGuide: StructuredPrototypeFreeformSpacingGuide | null;
  readonly gridGuide: StructuredPrototypeFreeformSnapGuide | null;
}

interface StructuredPrototypeFreeformGridSnapCandidate {
  readonly position: number;
  readonly distance: number;
  readonly line: StructuredPrototypeFreeformGridSnapLine;
  readonly guide: StructuredPrototypeFreeformSnapGuide;
}

function assertFinite(value: number, label: string): void {
  if (!Number.isFinite(value)) throw new Error(`freeform snap ${label} must be finite`);
}

function assertPositive(value: number, label: string): void {
  assertFinite(value, label);
  if (value <= 0) throw new Error(`freeform snap ${label} must be positive`);
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum);
}

function assertBounds(bounds: StructuredPrototypeFreeformSnapBounds, label: string): void {
  assertFinite(bounds.x, `${label} x`);
  assertFinite(bounds.y, `${label} y`);
  assertPositive(bounds.width, `${label} width`);
  assertPositive(bounds.height, `${label} height`);
  if (bounds.x < 0 || bounds.y < 0) {
    throw new Error(`freeform snap ${label} position must not be negative`);
  }
}

function resolveSelectedNodeIds(nodeIds: readonly string[]): ReadonlySet<string> {
  if (nodeIds.length === 0) throw new Error("freeform snap requires at least one selected node");
  const selected = new Set<string>();
  for (const nodeId of nodeIds) {
    if (nodeId.length === 0) throw new Error("freeform snap selected node id must not be empty");
    if (selected.has(nodeId))
      throw new Error(`freeform snap selected node id is duplicated: ${nodeId}`);
    selected.add(nodeId);
  }
  return selected;
}

function assertSiblings(siblings: readonly StructuredPrototypeFreeformSnapSibling[]): void {
  const nodeIds = new Set<string>();
  for (const sibling of siblings) {
    if (sibling.nodeId.length === 0) {
      throw new Error("freeform snap sibling node id must not be empty");
    }
    if (nodeIds.has(sibling.nodeId)) {
      throw new Error(`freeform snap sibling node id is duplicated: ${sibling.nodeId}`);
    }
    nodeIds.add(sibling.nodeId);
    assertBounds(sibling, `sibling ${sibling.nodeId}`);
  }
}

function horizontalAnchors(
  bounds: StructuredPrototypeFreeformSnapBounds,
): readonly { anchor: StructuredPrototypeFreeformHorizontalSnapAnchor; coordinate: number }[] {
  return [
    { anchor: "left", coordinate: bounds.x },
    { anchor: "center", coordinate: bounds.x + bounds.width / 2 },
    { anchor: "right", coordinate: bounds.x + bounds.width },
  ];
}

function verticalAnchors(
  bounds: StructuredPrototypeFreeformSnapBounds,
): readonly { anchor: StructuredPrototypeFreeformVerticalSnapAnchor; coordinate: number }[] {
  return [
    { anchor: "top", coordinate: bounds.y },
    { anchor: "middle", coordinate: bounds.y + bounds.height / 2 },
    { anchor: "bottom", coordinate: bounds.y + bounds.height },
  ];
}

function targetKindRank(kind: StructuredPrototypeFreeformSnapTargetKind): number {
  if (kind === "container") return 0;
  if (kind === "sibling") return 1;
  return 2;
}

function compareNodeIds(left: string | null, right: string | null): number {
  const leftValue = left ?? "";
  const rightValue = right ?? "";
  if (leftValue === rightValue) return 0;
  return leftValue < rightValue ? -1 : 1;
}

function isBetterCandidate(
  candidate: StructuredPrototypeFreeformSnapCandidate,
  current: StructuredPrototypeFreeformSnapCandidate | null,
): boolean {
  if (current === null) return true;
  if (candidate.distance !== current.distance) return candidate.distance < current.distance;
  const candidateKindRank = targetKindRank(candidate.targetKind);
  const currentKindRank = targetKindRank(current.targetKind);
  if (candidateKindRank !== currentKindRank) return candidateKindRank < currentKindRank;
  if (candidate.coordinate !== current.coordinate) return candidate.coordinate < current.coordinate;
  return compareNodeIds(candidate.targetNodeId, current.targetNodeId) < 0;
}

function resolveHorizontalSnap({
  selectionBounds,
  directSiblings,
  selectedNodeIds,
  position,
  containerWidth,
  threshold,
}: {
  selectionBounds: StructuredPrototypeFreeformSnapBounds;
  directSiblings: readonly StructuredPrototypeFreeformSnapSibling[];
  selectedNodeIds: ReadonlySet<string>;
  position: number;
  containerWidth: number;
  threshold: number;
}): StructuredPrototypeFreeformAxisSnapResult {
  const movingBounds = { ...selectionBounds, x: position };
  const movingAnchors = horizontalAnchors(movingBounds);
  const targets: Array<{
    anchor: StructuredPrototypeFreeformHorizontalSnapAnchor;
    coordinate: number;
    kind: StructuredPrototypeFreeformSnapTargetKind;
    nodeId: string | null;
  }> = horizontalAnchors({ x: 0, y: 0, width: containerWidth, height: 1 }).map((target) => ({
    ...target,
    kind: "container",
    nodeId: null,
  }));
  for (const sibling of directSiblings) {
    if (selectedNodeIds.has(sibling.nodeId)) continue;
    for (const target of horizontalAnchors(sibling)) {
      targets.push({ ...target, kind: "sibling", nodeId: sibling.nodeId });
    }
  }

  const maximumPosition = Math.max(0, containerWidth - selectionBounds.width);
  let best: StructuredPrototypeFreeformSnapCandidate | null = null;
  for (const movingAnchor of movingAnchors) {
    for (const target of targets) {
      const correction = target.coordinate - movingAnchor.coordinate;
      const distance = Math.abs(correction);
      const snappedPosition = position + correction;
      if (distance > threshold || snappedPosition < 0 || snappedPosition > maximumPosition) {
        continue;
      }
      const candidate: StructuredPrototypeFreeformSnapCandidate = {
        coordinate: target.coordinate,
        correction,
        distance,
        movingAnchor: movingAnchor.anchor,
        targetAnchor: target.anchor,
        targetKind: target.kind,
        targetNodeId: target.nodeId,
      };
      if (isBetterCandidate(candidate, best)) best = candidate;
    }
  }
  if (best === null) return { position, distance: null, guide: null };
  return {
    position: position + best.correction,
    distance: best.distance,
    guide: {
      axis: "x",
      coordinate: best.coordinate,
      movingAnchor: best.movingAnchor,
      targetAnchor: best.targetAnchor,
      targetKind: best.targetKind,
      targetNodeId: best.targetNodeId,
    },
  };
}

function resolveVerticalSnap({
  selectionBounds,
  directSiblings,
  selectedNodeIds,
  position,
  containerHeight,
  threshold,
}: {
  selectionBounds: StructuredPrototypeFreeformSnapBounds;
  directSiblings: readonly StructuredPrototypeFreeformSnapSibling[];
  selectedNodeIds: ReadonlySet<string>;
  position: number;
  containerHeight: number;
  threshold: number;
}): StructuredPrototypeFreeformAxisSnapResult {
  const movingBounds = { ...selectionBounds, y: position };
  const movingAnchors = verticalAnchors(movingBounds);
  const targets: Array<{
    anchor: StructuredPrototypeFreeformVerticalSnapAnchor;
    coordinate: number;
    kind: StructuredPrototypeFreeformSnapTargetKind;
    nodeId: string | null;
  }> = verticalAnchors({ x: 0, y: 0, width: 1, height: containerHeight }).map((target) => ({
    ...target,
    kind: "container",
    nodeId: null,
  }));
  for (const sibling of directSiblings) {
    if (selectedNodeIds.has(sibling.nodeId)) continue;
    for (const target of verticalAnchors(sibling)) {
      targets.push({ ...target, kind: "sibling", nodeId: sibling.nodeId });
    }
  }

  const maximumPosition = Math.max(0, containerHeight - selectionBounds.height);
  let best: StructuredPrototypeFreeformSnapCandidate | null = null;
  for (const movingAnchor of movingAnchors) {
    for (const target of targets) {
      const correction = target.coordinate - movingAnchor.coordinate;
      const distance = Math.abs(correction);
      const snappedPosition = position + correction;
      if (distance > threshold || snappedPosition < 0 || snappedPosition > maximumPosition) {
        continue;
      }
      const candidate: StructuredPrototypeFreeformSnapCandidate = {
        coordinate: target.coordinate,
        correction,
        distance,
        movingAnchor: movingAnchor.anchor,
        targetAnchor: target.anchor,
        targetKind: target.kind,
        targetNodeId: target.nodeId,
      };
      if (isBetterCandidate(candidate, best)) best = candidate;
    }
  }
  if (best === null) return { position, distance: null, guide: null };
  return {
    position: position + best.correction,
    distance: best.distance,
    guide: {
      axis: "y",
      coordinate: best.coordinate,
      movingAnchor: best.movingAnchor,
      targetAnchor: best.targetAnchor,
      targetKind: best.targetKind,
      targetNodeId: best.targetNodeId,
    },
  };
}

function snapAnchorRank(anchor: StructuredPrototypeFreeformSnapAnchor): number {
  switch (anchor) {
    case "left":
    case "top":
      return 0;
    case "center":
    case "middle":
      return 1;
    case "right":
    case "bottom":
      return 2;
  }
}

function isBetterGridCandidate(
  candidate: StructuredPrototypeFreeformGridSnapCandidate,
  current: StructuredPrototypeFreeformGridSnapCandidate | null,
): boolean {
  if (current === null) return true;
  if (candidate.distance !== current.distance) return candidate.distance < current.distance;
  if (candidate.line.gridId !== current.line.gridId) {
    return candidate.line.gridId < current.line.gridId;
  }
  if (candidate.line.coordinate !== current.line.coordinate) {
    return candidate.line.coordinate < current.line.coordinate;
  }
  const anchorOrder =
    snapAnchorRank(candidate.guide.movingAnchor) - snapAnchorRank(current.guide.movingAnchor);
  if (anchorOrder !== 0) return anchorOrder < 0;
  return candidate.line.lineIndex < current.line.lineIndex;
}

function resolveGridSnap({
  axis,
  selectionBounds,
  position,
  containerWidth,
  containerHeight,
  threshold,
  grids,
}: {
  axis: StructuredPrototypeFreeformSnapAxis;
  selectionBounds: StructuredPrototypeFreeformSnapBounds;
  position: number;
  containerWidth: number;
  containerHeight: number;
  threshold: number;
  grids: readonly Readonly<StructuredPrototypeFreeformGrid>[];
}): StructuredPrototypeFreeformGridSnapCandidate | null {
  const movingBounds = {
    ...selectionBounds,
    ...(axis === "x" ? { x: position } : { y: position }),
  };
  const anchors = axis === "x" ? horizontalAnchors(movingBounds) : verticalAnchors(movingBounds);
  const maximumPosition = Math.max(
    0,
    axis === "x"
      ? containerWidth - selectionBounds.width
      : containerHeight - selectionBounds.height,
  );
  let best: StructuredPrototypeFreeformGridSnapCandidate | null = null;
  for (const anchor of anchors) {
    const line = resolveStructuredPrototypeNearestFreeformGridSnapLine({
      frame: { width: containerWidth, height: containerHeight },
      grids,
      axis,
      coordinate: anchor.coordinate,
    });
    if (line === null || line.distance > threshold) continue;
    const snappedPosition = position + line.correction;
    if (snappedPosition < 0 || snappedPosition > maximumPosition) continue;
    const candidate: StructuredPrototypeFreeformGridSnapCandidate = {
      position: snappedPosition,
      distance: line.distance,
      line,
      guide: {
        axis,
        coordinate: line.coordinate,
        movingAnchor: anchor.anchor,
        targetAnchor: anchor.anchor,
        targetKind: "grid",
        targetNodeId: null,
        gridId: line.gridId,
        gridType: line.gridType,
        gridLineIndex: line.lineIndex,
      },
    };
    if (isBetterGridCandidate(candidate, best)) best = candidate;
  }
  return best;
}

function snapValueTolerance(left: number, right: number): number {
  return 1e-9 * Math.max(1, Math.abs(left), Math.abs(right));
}

function distanceIsAtMost(left: number, right: number): boolean {
  // Decimal grid arithmetic can leave machine-precision tails. Apply tolerance
  // only while ranking candidates; the winning candidate keeps its exact target.
  return left - right <= snapValueTolerance(left, right);
}

function distancesAreTied(left: number, right: number): boolean {
  return distanceIsAtMost(left, right) && distanceIsAtMost(right, left);
}

function resolveAxisSnap(
  alignment: StructuredPrototypeFreeformAxisSnapResult,
  spacing: StructuredPrototypeFreeformSpacingSnapCandidate | null,
  grid: StructuredPrototypeFreeformGridSnapCandidate | null,
): StructuredPrototypeFreeformResolvedAxisSnap {
  if (
    alignment.distance !== null &&
    (spacing === null || distanceIsAtMost(alignment.distance, spacing.distance)) &&
    (grid === null || distanceIsAtMost(alignment.distance, grid.distance))
  ) {
    return {
      position: alignment.position,
      guide: alignment.guide,
      spacingGuide: null,
      gridGuide: null,
    };
  }
  if (spacing !== null && (grid === null || distanceIsAtMost(spacing.distance, grid.distance))) {
    return {
      position: spacing.position,
      guide: null,
      spacingGuide: spacing.guide,
      gridGuide: null,
    };
  }
  if (grid !== null) {
    return {
      position: grid.position,
      guide: null,
      spacingGuide: null,
      gridGuide: grid.guide,
    };
  }
  return { position: alignment.position, guide: null, spacingGuide: null, gridGuide: null };
}

function resolveDiagnosticAxisWinner(
  resolved: StructuredPrototypeFreeformResolvedAxisSnap,
): StructuredPrototypeFreeformSnapDiagnosticAxisWinner {
  if (resolved.guide !== null) return "alignment";
  if (resolved.spacingGuide !== null) return "spacing";
  if (resolved.gridGuide !== null) return "grid";
  return "raw";
}

function diagnosticSortKey(parts: readonly (string | number | null)[]): string {
  return parts
    .map((part) => {
      if (part === null) return "null";
      if (typeof part === "number") return `number:${String(part)}`;
      return `string:${part.length}:${part}`;
    })
    .join("|");
}

function resolveDiagnosticWinnerDistance({
  winner,
  alignment,
  spacing,
  grid,
}: {
  winner: StructuredPrototypeFreeformSnapDiagnosticAxisWinner;
  alignment: StructuredPrototypeFreeformAxisSnapResult;
  spacing: StructuredPrototypeFreeformSpacingSnapCandidate | null;
  grid: StructuredPrototypeFreeformGridSnapCandidate | null;
}): number | null {
  switch (winner) {
    case "raw":
      return null;
    case "alignment":
      if (alignment.distance === null) {
        throw new Error("alignment snap diagnostic winner requires a candidate");
      }
      return alignment.distance;
    case "spacing":
      if (spacing === null) throw new Error("spacing snap diagnostic winner requires a candidate");
      return spacing.distance;
    case "grid":
      if (grid === null) throw new Error("grid snap diagnostic winner requires a candidate");
      return grid.distance;
  }
}

function resolveDiagnosticCandidateOutcome({
  source,
  distance,
  winner,
  winnerDistance,
  spacingWasInitiallySelected,
}: {
  source: StructuredPrototypeFreeformSnapDiagnosticCandidate["source"];
  distance: number;
  winner: StructuredPrototypeFreeformSnapDiagnosticAxisWinner;
  winnerDistance: number | null;
  spacingWasInitiallySelected: boolean;
}): StructuredPrototypeFreeformSnapDiagnosticCandidateOutcome {
  if (source === winner) return "winner";
  if (source === "spacing" && spacingWasInitiallySelected) return "crossAxisInvalid";
  if (winnerDistance === null) {
    throw new Error("raw snap diagnostic winner cannot have an eligible candidate");
  }
  return distancesAreTied(distance, winnerDistance) ? "tiePriority" : "farther";
}

function resolveAxisDiagnosticCandidates({
  axis,
  rawPosition,
  alignment,
  spacing,
  grid,
  resolved,
}: {
  axis: StructuredPrototypeFreeformSnapAxis;
  rawPosition: number;
  alignment: StructuredPrototypeFreeformAxisSnapResult;
  spacing: StructuredPrototypeFreeformSpacingSnapCandidate | null;
  grid: StructuredPrototypeFreeformGridSnapCandidate | null;
  resolved: StructuredPrototypeFreeformResolvedAxisSnap;
}): readonly StructuredPrototypeFreeformSnapDiagnosticCandidate[] {
  const diagnosticSpacing =
    spacing === null
      ? null
      : {
          ...spacing,
          correction: spacing.position - rawPosition,
          distance: Math.abs(spacing.position - rawPosition),
        };
  const winner = resolveDiagnosticAxisWinner(resolved);
  const winnerDistance = resolveDiagnosticWinnerDistance({
    winner,
    alignment,
    spacing: diagnosticSpacing,
    grid,
  });
  const spacingWasInitiallySelected =
    diagnosticSpacing !== null &&
    resolveAxisSnap(alignment, diagnosticSpacing, grid).spacingGuide !== null;
  const outcome = (
    source: StructuredPrototypeFreeformSnapDiagnosticCandidate["source"],
    distance: number,
  ) =>
    resolveDiagnosticCandidateOutcome({
      source,
      distance,
      winner,
      winnerDistance,
      spacingWasInitiallySelected,
    });
  const candidates: StructuredPrototypeFreeformSnapDiagnosticCandidate[] = [];

  if (alignment.distance !== null) {
    const guide = alignment.guide;
    if (guide === null) throw new Error("alignment snap diagnostic candidate requires a guide");
    if (guide.targetKind === "grid") {
      throw new Error("alignment snap diagnostic candidate cannot target a grid");
    }
    const correction = alignment.position - rawPosition;
    candidates.push({
      axis,
      source: "alignment",
      position: alignment.position,
      correction,
      distance: alignment.distance,
      outcome: outcome("alignment", alignment.distance),
      sortKey: diagnosticSortKey([
        axis,
        "alignment",
        alignment.distance,
        targetKindRank(guide.targetKind),
        guide.coordinate,
        guide.targetNodeId,
        snapAnchorRank(guide.movingAnchor),
        snapAnchorRank(guide.targetAnchor),
        alignment.position,
      ]),
      coordinate: guide.coordinate,
      movingAnchor: guide.movingAnchor,
      targetAnchor: guide.targetAnchor,
      targetKind: guide.targetKind,
      targetNodeId: guide.targetNodeId,
    });
  }

  if (diagnosticSpacing !== null) {
    candidates.push({
      axis,
      source: "spacing",
      position: diagnosticSpacing.position,
      correction: diagnosticSpacing.correction,
      distance: diagnosticSpacing.distance,
      outcome: outcome("spacing", diagnosticSpacing.distance),
      sortKey: diagnosticSortKey([
        axis,
        "spacing",
        diagnosticSpacing.distance,
        diagnosticSpacing.placement,
        diagnosticSpacing.gap,
        diagnosticSpacing.position,
        diagnosticSpacing.referenceNodeIds[0],
        diagnosticSpacing.referenceNodeIds[1],
      ]),
      placement: diagnosticSpacing.placement,
      gap: diagnosticSpacing.gap,
      referenceNodeIds: diagnosticSpacing.referenceNodeIds,
    });
  }

  if (grid !== null) {
    candidates.push({
      axis,
      source: "grid",
      position: grid.position,
      correction: grid.line.correction,
      distance: grid.distance,
      outcome: outcome("grid", grid.distance),
      sortKey: diagnosticSortKey([
        axis,
        "grid",
        grid.distance,
        grid.line.gridId,
        grid.line.coordinate,
        snapAnchorRank(grid.guide.movingAnchor),
        grid.line.lineIndex,
        grid.position,
      ]),
      gridId: grid.line.gridId,
      gridType: grid.line.gridType,
      gridLineIndex: grid.line.lineIndex,
      coordinate: grid.line.coordinate,
      movingAnchor: grid.guide.movingAnchor,
    });
  }

  return candidates;
}

export interface StructuredPrototypeFreeformCombinedSnapResult {
  readonly horizontal: StructuredPrototypeFreeformResolvedAxisSnap;
  readonly vertical: StructuredPrototypeFreeformResolvedAxisSnap;
  /** Final lane-refreshed candidates actually used by the resolved axes. */
  readonly horizontalSpacingCandidate: StructuredPrototypeFreeformSpacingSnapCandidate | null;
  readonly verticalSpacingCandidate: StructuredPrototypeFreeformSpacingSnapCandidate | null;
}

export interface StructuredPrototypeFreeformCombinedSnapInput {
  readonly selectionBounds: StructuredPrototypeFreeformSnapBounds;
  readonly selectedNodeIds: readonly string[];
  readonly directSiblings: readonly StructuredPrototypeFreeformSnapSibling[];
  readonly horizontalAlignment: StructuredPrototypeFreeformAxisSnapResult;
  readonly verticalAlignment: StructuredPrototypeFreeformAxisSnapResult;
  readonly horizontalSpacing: StructuredPrototypeFreeformSpacingSnapCandidate | null;
  readonly verticalSpacing: StructuredPrototypeFreeformSpacingSnapCandidate | null;
  readonly horizontalGrid: StructuredPrototypeFreeformGridSnapCandidate | null;
  readonly verticalGrid: StructuredPrototypeFreeformGridSnapCandidate | null;
  readonly maximumX: number;
  readonly maximumY: number;
}

function selectedSpacingCandidate(
  alignment: StructuredPrototypeFreeformAxisSnapResult,
  spacing: StructuredPrototypeFreeformSpacingSnapCandidate | null,
  grid: StructuredPrototypeFreeformGridSnapCandidate | null,
): StructuredPrototypeFreeformSpacingSnapCandidate | null {
  return resolveAxisSnap(alignment, spacing, grid).spacingGuide === null ? null : spacing;
}

function refreshSpacingCandidate({
  axis,
  candidate,
  finalBounds,
  selectedNodeIds,
  directSiblings,
  maximumPosition,
}: {
  axis: StructuredPrototypeFreeformSnapAxis;
  candidate: StructuredPrototypeFreeformSpacingSnapCandidate;
  finalBounds: StructuredPrototypeFreeformSnapBounds;
  selectedNodeIds: readonly string[];
  directSiblings: readonly StructuredPrototypeFreeformSnapSibling[];
  maximumPosition: number;
}): StructuredPrototypeFreeformSpacingSnapCandidate | null {
  const tolerance = snapValueTolerance(
    candidate.position,
    axis === "x" ? finalBounds.x : finalBounds.y,
  );
  const refreshed = resolveStructuredPrototypeFreeformSpacingSnap({
    axis,
    movingBounds: finalBounds,
    selectedNodeIds,
    directSiblings,
    minimumPosition: 0,
    maximumPosition,
    threshold: tolerance,
  });
  if (
    refreshed === null ||
    Math.abs(refreshed.position - candidate.position) >
      snapValueTolerance(refreshed.position, candidate.position)
  ) {
    return null;
  }
  return refreshed;
}

interface StructuredPrototypeFreeformEvaluatedSnapPlan {
  readonly result: StructuredPrototypeFreeformCombinedSnapResult;
  readonly invalidAxes: readonly StructuredPrototypeFreeformSnapAxis[];
}

function resolvedSpacingCandidate(
  resolved: StructuredPrototypeFreeformResolvedAxisSnap,
  candidate: StructuredPrototypeFreeformSpacingSnapCandidate | null,
): StructuredPrototypeFreeformSpacingSnapCandidate | null {
  if (resolved.spacingGuide === null) return null;
  if (candidate === null || resolved.spacingGuide !== candidate.guide) {
    throw new Error("resolved spacing guide requires its exact refreshed candidate");
  }
  return candidate;
}

function evaluateSpacingPlan({
  selectionBounds,
  selectedNodeIds,
  directSiblings,
  horizontalAlignment,
  verticalAlignment,
  horizontalSpacing,
  verticalSpacing,
  horizontalGrid,
  verticalGrid,
  maximumX,
  maximumY,
}: StructuredPrototypeFreeformCombinedSnapInput): StructuredPrototypeFreeformEvaluatedSnapPlan {
  const horizontal = resolveAxisSnap(horizontalAlignment, horizontalSpacing, horizontalGrid);
  const vertical = resolveAxisSnap(verticalAlignment, verticalSpacing, verticalGrid);
  const finalBounds = {
    ...selectionBounds,
    x: horizontal.position,
    y: vertical.position,
  };
  const refreshedHorizontal =
    horizontalSpacing === null
      ? null
      : refreshSpacingCandidate({
          axis: "x",
          candidate: horizontalSpacing,
          finalBounds,
          selectedNodeIds,
          directSiblings,
          maximumPosition: maximumX,
        });
  const refreshedVertical =
    verticalSpacing === null
      ? null
      : refreshSpacingCandidate({
          axis: "y",
          candidate: verticalSpacing,
          finalBounds,
          selectedNodeIds,
          directSiblings,
          maximumPosition: maximumY,
        });
  const invalidAxes: StructuredPrototypeFreeformSnapAxis[] = [];
  if (horizontalSpacing !== null && refreshedHorizontal === null) invalidAxes.push("x");
  if (verticalSpacing !== null && refreshedVertical === null) invalidAxes.push("y");
  const resolvedHorizontal = resolveAxisSnap(
    horizontalAlignment,
    refreshedHorizontal,
    horizontalGrid,
  );
  const resolvedVertical = resolveAxisSnap(verticalAlignment, refreshedVertical, verticalGrid);
  return {
    result: {
      horizontal: resolvedHorizontal,
      vertical: resolvedVertical,
      horizontalSpacingCandidate: resolvedSpacingCandidate(resolvedHorizontal, refreshedHorizontal),
      verticalSpacingCandidate: resolvedSpacingCandidate(resolvedVertical, refreshedVertical),
    },
    invalidAxes,
  };
}

function planIsValid(plan: StructuredPrototypeFreeformEvaluatedSnapPlan): boolean {
  return plan.invalidAxes.length === 0;
}

/**
 * Combines independently resolved alignment and equal-spacing candidates. Each
 * attempted spacing plan is refreshed against its own final two-axis frame.
 */
export function resolveStructuredPrototypeFreeformCombinedSnaps(
  input: StructuredPrototypeFreeformCombinedSnapInput,
): StructuredPrototypeFreeformCombinedSnapResult {
  const selectedHorizontal = selectedSpacingCandidate(
    input.horizontalAlignment,
    input.horizontalSpacing,
    input.horizontalGrid,
  );
  const selectedVertical = selectedSpacingCandidate(
    input.verticalAlignment,
    input.verticalSpacing,
    input.verticalGrid,
  );
  const initialPlan = evaluateSpacingPlan({
    ...input,
    horizontalSpacing: selectedHorizontal,
    verticalSpacing: selectedVertical,
  });
  if (planIsValid(initialPlan)) return initialPlan.result;

  const horizontalInvalid = initialPlan.invalidAxes.includes("x");
  const verticalInvalid = initialPlan.invalidAxes.includes("y");
  const fallbackPlan = () =>
    evaluateSpacingPlan({
      ...input,
      horizontalSpacing: null,
      verticalSpacing: null,
    }).result;

  if (horizontalInvalid !== verticalInvalid) {
    const retainedPlan = evaluateSpacingPlan({
      ...input,
      horizontalSpacing: horizontalInvalid ? null : selectedHorizontal,
      verticalSpacing: verticalInvalid ? null : selectedVertical,
    });
    return planIsValid(retainedPlan) ? retainedPlan.result : fallbackPlan();
  }

  if (selectedHorizontal === null || selectedVertical === null) {
    // evaluateSpacingPlan reports an invalid axis only when that axis had a candidate.
    throw new Error("invalid dual-axis spacing plan requires both spacing candidates");
  }
  const horizontalFirst = selectedHorizontal.distance <= selectedVertical.distance;
  const preferredPlan = evaluateSpacingPlan({
    ...input,
    horizontalSpacing: horizontalFirst ? selectedHorizontal : null,
    verticalSpacing: horizontalFirst ? null : selectedVertical,
  });
  if (planIsValid(preferredPlan)) return preferredPlan.result;

  const alternatePlan = evaluateSpacingPlan({
    ...input,
    horizontalSpacing: horizontalFirst ? null : selectedHorizontal,
    verticalSpacing: horizontalFirst ? selectedVertical : null,
  });
  return planIsValid(alternatePlan) ? alternatePlan.result : fallbackPlan();
}

/**
 * Resolves a clamped move and any visible Freeform alignment guides. The caller
 * is responsible for deciding whether modifier keys disable this solver.
 */
export function resolveStructuredPrototypeFreeformMoveSnap({
  selectionBounds,
  selectedNodeIds,
  requestedDelta,
  containerWidth,
  containerHeight,
  previewScale,
  directSiblings,
  grids = [],
  gridSnappingEnabled = true,
}: StructuredPrototypeFreeformMoveSnapInput): StructuredPrototypeFreeformMoveSnapResult {
  assertPositive(containerWidth, "container width");
  assertPositive(containerHeight, "container height");
  assertPositive(previewScale, "preview scale");
  assertFinite(requestedDelta.x, "requested delta x");
  assertFinite(requestedDelta.y, "requested delta y");
  assertBounds(selectionBounds, "selection bounds");
  const selected = resolveSelectedNodeIds(selectedNodeIds);
  assertSiblings(directSiblings);

  const unclampedPosition = {
    x: selectionBounds.x + requestedDelta.x,
    y: selectionBounds.y + requestedDelta.y,
  };
  const clampedPosition = {
    x: clamp(unclampedPosition.x, 0, Math.max(0, containerWidth - selectionBounds.width)),
    y: clamp(unclampedPosition.y, 0, Math.max(0, containerHeight - selectionBounds.height)),
  };
  const threshold = STRUCTURED_PROTOTYPE_FREEFORM_SNAP_THRESHOLD_CLIENT_PX / previewScale;
  const horizontalAlignment = resolveHorizontalSnap({
    selectionBounds,
    directSiblings,
    selectedNodeIds: selected,
    position: clampedPosition.x,
    containerWidth,
    threshold,
  });
  const verticalAlignment = resolveVerticalSnap({
    selectionBounds,
    directSiblings,
    selectedNodeIds: selected,
    position: clampedPosition.y,
    containerHeight,
    threshold,
  });
  const movingBounds = {
    ...selectionBounds,
    x: clampedPosition.x,
    y: clampedPosition.y,
  };
  const maximumX = Math.max(0, containerWidth - selectionBounds.width);
  const maximumY = Math.max(0, containerHeight - selectionBounds.height);
  const horizontalSpacing =
    selectionBounds.width > containerWidth
      ? null
      : resolveStructuredPrototypeFreeformSpacingSnap({
          axis: "x",
          movingBounds,
          selectedNodeIds,
          directSiblings,
          minimumPosition: 0,
          maximumPosition: maximumX,
          threshold,
        });
  const verticalSpacing =
    selectionBounds.height > containerHeight
      ? null
      : resolveStructuredPrototypeFreeformSpacingSnap({
          axis: "y",
          movingBounds,
          selectedNodeIds,
          directSiblings,
          minimumPosition: 0,
          maximumPosition: maximumY,
          threshold,
        });
  const horizontalGrid =
    gridSnappingEnabled && grids.length > 0
      ? resolveGridSnap({
          axis: "x",
          selectionBounds,
          position: clampedPosition.x,
          containerWidth,
          containerHeight,
          threshold,
          grids,
        })
      : null;
  const verticalGrid =
    gridSnappingEnabled && grids.length > 0
      ? resolveGridSnap({
          axis: "y",
          selectionBounds,
          position: clampedPosition.y,
          containerWidth,
          containerHeight,
          threshold,
          grids,
        })
      : null;
  const combined = resolveStructuredPrototypeFreeformCombinedSnaps({
    selectionBounds,
    selectedNodeIds,
    directSiblings,
    horizontalAlignment,
    verticalAlignment,
    horizontalSpacing,
    verticalSpacing,
    horizontalGrid,
    verticalGrid,
    maximumX,
    maximumY,
  });
  const { horizontal, vertical } = combined;
  const position = { x: horizontal.position, y: vertical.position };
  const guides = [
    horizontal.guide,
    horizontal.gridGuide,
    vertical.guide,
    vertical.gridGuide,
  ].filter((guide): guide is StructuredPrototypeFreeformSnapGuide => guide !== null);
  const spacingGuides = [horizontal.spacingGuide, vertical.spacingGuide].filter(
    (guide): guide is StructuredPrototypeFreeformSpacingGuide => guide !== null,
  );
  const diagnostics: StructuredPrototypeFreeformMoveSnapDiagnostics = {
    rawPosition: clampedPosition,
    threshold,
    axisWinners: {
      x: resolveDiagnosticAxisWinner(horizontal),
      y: resolveDiagnosticAxisWinner(vertical),
    },
    candidates: [
      ...resolveAxisDiagnosticCandidates({
        axis: "x",
        rawPosition: clampedPosition.x,
        alignment: horizontalAlignment,
        spacing: combined.horizontalSpacingCandidate ?? horizontalSpacing,
        grid: horizontalGrid,
        resolved: horizontal,
      }),
      ...resolveAxisDiagnosticCandidates({
        axis: "y",
        rawPosition: clampedPosition.y,
        alignment: verticalAlignment,
        spacing: combined.verticalSpacingCandidate ?? verticalSpacing,
        grid: verticalGrid,
        resolved: vertical,
      }),
    ],
  };
  return {
    delta: {
      x: position.x - selectionBounds.x,
      y: position.y - selectionBounds.y,
    },
    position,
    guides,
    spacingGuides,
    diagnostics,
  };
}
