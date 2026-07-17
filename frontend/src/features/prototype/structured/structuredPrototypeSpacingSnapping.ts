import type {
  StructuredPrototypeFreeformSnapAxis,
  StructuredPrototypeFreeformSnapBounds,
  StructuredPrototypeFreeformSnapSibling,
} from "./structuredPrototypeSnapping";

export type StructuredPrototypeFreeformSpacingPlacement = "before" | "between" | "after";

export interface StructuredPrototypeFreeformSpacingSegment {
  readonly start: number;
  readonly end: number;
  readonly crossCoordinate: number;
  /** `null` identifies the moving single/group selection. */
  readonly fromNodeId: string | null;
  /** `null` identifies the moving single/group selection. */
  readonly toNodeId: string | null;
  readonly segmentIndex: 0 | 1;
}

export interface StructuredPrototypeFreeformSpacingGuide {
  readonly axis: StructuredPrototypeFreeformSnapAxis;
  readonly placement: StructuredPrototypeFreeformSpacingPlacement;
  readonly gap: number;
  readonly referenceNodeIds: readonly [string, string];
  readonly segments: readonly [
    StructuredPrototypeFreeformSpacingSegment,
    StructuredPrototypeFreeformSpacingSegment,
  ];
}

export interface StructuredPrototypeFreeformSpacingSnapCandidate {
  readonly position: number;
  readonly correction: number;
  /** Absolute canvas-space correction used to arbitrate against alignment snapping. */
  readonly distance: number;
  readonly placement: StructuredPrototypeFreeformSpacingPlacement;
  readonly gap: number;
  readonly referenceNodeIds: readonly [string, string];
  readonly guide: StructuredPrototypeFreeformSpacingGuide;
}

export interface StructuredPrototypeFreeformSpacingSnapInput {
  readonly axis: StructuredPrototypeFreeformSnapAxis;
  /** The complete, already-clamped single/group union at the requested move position. */
  readonly movingBounds: Readonly<StructuredPrototypeFreeformSnapBounds>;
  readonly selectedNodeIds: readonly string[];
  readonly directSiblings: readonly Readonly<StructuredPrototypeFreeformSnapSibling>[];
  readonly minimumPosition: number;
  readonly maximumPosition: number;
  readonly threshold: number;
}

interface AxisFrame {
  readonly nodeId: string;
  readonly start: number;
  readonly end: number;
  readonly crossStart: number;
  readonly crossEnd: number;
  readonly bounds: Readonly<StructuredPrototypeFreeformSnapBounds>;
}

interface SpacingCandidate extends StructuredPrototypeFreeformSpacingSnapCandidate {
  readonly outerSpan: number;
}

interface SpacingBlockerInterval {
  readonly start: number;
  readonly end: number;
}

interface SpacingBlockerQuery {
  readonly axis: StructuredPrototypeFreeformSnapAxis;
  readonly projectedMovingBounds: Readonly<StructuredPrototypeFreeformSnapBounds>;
  readonly crossStart: number;
  readonly crossEnd: number;
  readonly fixedCorridor: SpacingBlockerInterval;
  readonly segmentIntervals: readonly [SpacingBlockerInterval, SpacingBlockerInterval];
}

interface PreparedSpacingCandidate {
  readonly candidate: SpacingCandidate;
  readonly blockerQuery: SpacingBlockerQuery;
}

const SPACING_SNAP_RELATIVE_TOLERANCE = 1e-9;

/**
 * Returns the relative tolerance for a local spacing invariant.  Callers pass
 * the values that participate in the same arithmetic operation; raw canvas
 * position is intentionally not used for move-distance decisions.
 */
export function structuredPrototypeFreeformSpacingTolerance(...magnitudes: number[]): number {
  let scale = 1;
  for (const magnitude of magnitudes) {
    const absoluteMagnitude = Math.abs(magnitude);
    if (absoluteMagnitude > scale) scale = absoluteMagnitude;
  }
  return SPACING_SNAP_RELATIVE_TOLERANCE * scale;
}

export function structuredPrototypeFreeformSpacingLengthsMatch(
  segmentLength: number,
  gap: number,
): boolean {
  if (!Number.isFinite(segmentLength) || !Number.isFinite(gap)) return false;
  return (
    Math.abs(segmentLength - gap) <= structuredPrototypeFreeformSpacingTolerance(segmentLength, gap)
  );
}

function normalizeNear(value: number, boundary: number): number {
  return Math.abs(value - boundary) <= structuredPrototypeFreeformSpacingTolerance(value, boundary)
    ? boundary
    : value;
}

function isMeaningfullyBelow(value: number, minimum: number): boolean {
  return minimum - value > structuredPrototypeFreeformSpacingTolerance(value, minimum);
}

function isMeaningfullyAbove(value: number, maximum: number): boolean {
  return value - maximum > structuredPrototypeFreeformSpacingTolerance(value, maximum);
}

function assertFinite(value: number, label: string): void {
  if (!Number.isFinite(value)) {
    throw new Error(`freeform spacing snap ${label} must be finite`);
  }
}

function assertPositive(value: number, label: string): void {
  assertFinite(value, label);
  if (value <= 0) {
    throw new Error(`freeform spacing snap ${label} must be positive`);
  }
}

function assertBounds(
  bounds: Readonly<StructuredPrototypeFreeformSnapBounds>,
  label: string,
): void {
  assertFinite(bounds.x, `${label} x`);
  assertFinite(bounds.y, `${label} y`);
  assertPositive(bounds.width, `${label} width`);
  assertPositive(bounds.height, `${label} height`);
  if (bounds.x < 0 || bounds.y < 0) {
    throw new Error(`freeform spacing snap ${label} position must not be negative`);
  }
  const right = bounds.x + bounds.width;
  const bottom = bounds.y + bounds.height;
  if (!Number.isFinite(right) || right <= bounds.x) {
    throw new Error(`freeform spacing snap ${label} horizontal frame must be finite and positive`);
  }
  if (!Number.isFinite(bottom) || bottom <= bounds.y) {
    throw new Error(`freeform spacing snap ${label} vertical frame must be finite and positive`);
  }
}

function resolveSelectedNodeIds(nodeIds: readonly string[]): ReadonlySet<string> {
  if (nodeIds.length === 0) {
    throw new Error("freeform spacing snap requires at least one selected node");
  }
  const selected = new Set<string>();
  for (const nodeId of nodeIds) {
    if (nodeId.length === 0) {
      throw new Error("freeform spacing snap selected node id must not be empty");
    }
    if (selected.has(nodeId)) {
      throw new Error(`freeform spacing snap selected node id is duplicated: ${nodeId}`);
    }
    selected.add(nodeId);
  }
  return selected;
}

function assertSiblings(
  siblings: readonly Readonly<StructuredPrototypeFreeformSnapSibling>[],
): void {
  const nodeIds = new Set<string>();
  for (const sibling of siblings) {
    if (sibling.nodeId.length === 0) {
      throw new Error("freeform spacing snap sibling node id must not be empty");
    }
    if (nodeIds.has(sibling.nodeId)) {
      throw new Error(`freeform spacing snap sibling node id is duplicated: ${sibling.nodeId}`);
    }
    nodeIds.add(sibling.nodeId);
    assertBounds(sibling, `sibling ${sibling.nodeId}`);
  }
}

function toAxisFrame(
  axis: StructuredPrototypeFreeformSnapAxis,
  sibling: Readonly<StructuredPrototypeFreeformSnapSibling>,
): AxisFrame {
  return axis === "x"
    ? {
        nodeId: sibling.nodeId,
        start: sibling.x,
        end: sibling.x + sibling.width,
        crossStart: sibling.y,
        crossEnd: sibling.y + sibling.height,
        bounds: sibling,
      }
    : {
        nodeId: sibling.nodeId,
        start: sibling.y,
        end: sibling.y + sibling.height,
        crossStart: sibling.x,
        crossEnd: sibling.x + sibling.width,
        bounds: sibling,
      };
}

function axisPosition(
  axis: StructuredPrototypeFreeformSnapAxis,
  bounds: Readonly<StructuredPrototypeFreeformSnapBounds>,
): number {
  return axis === "x" ? bounds.x : bounds.y;
}

function axisSize(
  axis: StructuredPrototypeFreeformSnapAxis,
  bounds: Readonly<StructuredPrototypeFreeformSnapBounds>,
): number {
  return axis === "x" ? bounds.width : bounds.height;
}

function crossInterval(
  axis: StructuredPrototypeFreeformSnapAxis,
  bounds: Readonly<StructuredPrototypeFreeformSnapBounds>,
): readonly [number, number] {
  return axis === "x" ? [bounds.y, bounds.y + bounds.height] : [bounds.x, bounds.x + bounds.width];
}

function compareText(left: string, right: string): number {
  if (left === right) return 0;
  return left < right ? -1 : 1;
}

function compareAxisFrames(left: AxisFrame, right: AxisFrame): number {
  if (left.start !== right.start) return left.start < right.start ? -1 : 1;
  if (left.end !== right.end) return left.end < right.end ? -1 : 1;
  return compareText(left.nodeId, right.nodeId);
}

function placementRank(placement: StructuredPrototypeFreeformSpacingPlacement): number {
  switch (placement) {
    case "between":
      return 0;
    case "before":
      return 1;
    case "after":
      return 2;
  }
}

function compareCandidates(left: SpacingCandidate, right: SpacingCandidate): number {
  if (left.distance !== right.distance) return left.distance < right.distance ? -1 : 1;
  if (left.outerSpan !== right.outerSpan) return left.outerSpan < right.outerSpan ? -1 : 1;
  const placementComparison = placementRank(left.placement) - placementRank(right.placement);
  if (placementComparison !== 0) return placementComparison;
  if (left.gap !== right.gap) return left.gap < right.gap ? -1 : 1;
  if (left.position !== right.position) return left.position < right.position ? -1 : 1;
  const firstIdComparison = compareText(left.referenceNodeIds[0], right.referenceNodeIds[0]);
  if (firstIdComparison !== 0) return firstIdComparison;
  return compareText(left.referenceNodeIds[1], right.referenceNodeIds[1]);
}

function intervalsOverlap(
  leftStart: number,
  leftEnd: number,
  rightStart: number,
  rightEnd: number,
): boolean {
  return leftStart < rightEnd && rightStart < leftEnd;
}

function framesOverlap(
  left: Readonly<StructuredPrototypeFreeformSnapBounds>,
  right: Readonly<StructuredPrototypeFreeformSnapBounds>,
): boolean {
  return (
    intervalsOverlap(left.x, left.x + left.width, right.x, right.x + right.width) &&
    intervalsOverlap(left.y, left.y + left.height, right.y, right.y + right.height)
  );
}

function projectMovingBounds(
  axis: StructuredPrototypeFreeformSnapAxis,
  movingBounds: Readonly<StructuredPrototypeFreeformSnapBounds>,
  position: number,
): StructuredPrototypeFreeformSnapBounds {
  return axis === "x" ? { ...movingBounds, x: position } : { ...movingBounds, y: position };
}

function corridorIsOccupied(
  blocker: AxisFrame,
  start: number,
  end: number,
  crossStart: number,
  crossEnd: number,
): boolean {
  return (
    intervalsOverlap(blocker.start, blocker.end, start, end) &&
    intervalsOverlap(blocker.crossStart, blocker.crossEnd, crossStart, crossEnd)
  );
}

function blockerQueryCacheKey(query: SpacingBlockerQuery): string {
  const { projectedMovingBounds, fixedCorridor, segmentIntervals } = query;
  // Finite Number strings round-trip exactly; -0 and 0 are equivalent for these overlap queries.
  return [
    query.axis,
    projectedMovingBounds.x,
    projectedMovingBounds.y,
    projectedMovingBounds.width,
    projectedMovingBounds.height,
    query.crossStart,
    query.crossEnd,
    fixedCorridor.start,
    fixedCorridor.end,
    segmentIntervals[0].start,
    segmentIntervals[0].end,
    segmentIntervals[1].start,
    segmentIntervals[1].end,
  ].join("|");
}

function queryHasBlocker(query: SpacingBlockerQuery, siblings: readonly AxisFrame[]): boolean {
  for (const blocker of siblings) {
    if (framesOverlap(query.projectedMovingBounds, blocker.bounds)) return true;
    if (
      corridorIsOccupied(
        blocker,
        query.fixedCorridor.start,
        query.fixedCorridor.end,
        query.crossStart,
        query.crossEnd,
      ) ||
      corridorIsOccupied(
        blocker,
        query.segmentIntervals[0].start,
        query.segmentIntervals[0].end,
        query.crossStart,
        query.crossEnd,
      ) ||
      corridorIsOccupied(
        blocker,
        query.segmentIntervals[1].start,
        query.segmentIntervals[1].end,
        query.crossStart,
        query.crossEnd,
      )
    ) {
      return true;
    }
  }
  return false;
}

function buildSegments({
  placement,
  position,
  movingSize,
  left,
  right,
  crossCoordinate,
}: {
  placement: StructuredPrototypeFreeformSpacingPlacement;
  position: number;
  movingSize: number;
  left: AxisFrame;
  right: AxisFrame;
  crossCoordinate: number;
}): readonly [
  StructuredPrototypeFreeformSpacingSegment,
  StructuredPrototypeFreeformSpacingSegment,
] {
  switch (placement) {
    case "before":
      return [
        {
          start: position + movingSize,
          end: left.start,
          crossCoordinate,
          fromNodeId: null,
          toNodeId: left.nodeId,
          segmentIndex: 0,
        },
        {
          start: left.end,
          end: right.start,
          crossCoordinate,
          fromNodeId: left.nodeId,
          toNodeId: right.nodeId,
          segmentIndex: 1,
        },
      ];
    case "between":
      return [
        {
          start: left.end,
          end: position,
          crossCoordinate,
          fromNodeId: left.nodeId,
          toNodeId: null,
          segmentIndex: 0,
        },
        {
          start: position + movingSize,
          end: right.start,
          crossCoordinate,
          fromNodeId: null,
          toNodeId: right.nodeId,
          segmentIndex: 1,
        },
      ];
    case "after":
      return [
        {
          start: left.end,
          end: right.start,
          crossCoordinate,
          fromNodeId: left.nodeId,
          toNodeId: right.nodeId,
          segmentIndex: 0,
        },
        {
          start: right.end,
          end: position,
          crossCoordinate,
          fromNodeId: right.nodeId,
          toNodeId: null,
          segmentIndex: 1,
        },
      ];
  }
}

function candidatePosition(
  placement: StructuredPrototypeFreeformSpacingPlacement,
  movingSize: number,
  left: AxisFrame,
  right: AxisFrame,
): { readonly position: number; readonly gap: number } | null {
  const fixedGap = right.start - left.end;
  if (fixedGap <= structuredPrototypeFreeformSpacingTolerance(right.start, left.end, fixedGap)) {
    return null;
  }
  switch (placement) {
    case "before":
      return {
        position: left.start - movingSize - fixedGap,
        gap: fixedGap,
      };
    case "between": {
      const gap = (fixedGap - movingSize) / 2;
      if (gap <= structuredPrototypeFreeformSpacingTolerance(fixedGap, movingSize, gap)) {
        return null;
      }
      return {
        position: left.end + gap,
        gap,
      };
    }
    case "after":
      return {
        position: right.end + fixedGap,
        gap: fixedGap,
      };
  }
}

function createPreparedCandidate({
  input,
  movingPosition,
  movingSize,
  movingCrossStart,
  movingCrossEnd,
  left,
  right,
  placement,
}: {
  input: StructuredPrototypeFreeformSpacingSnapInput;
  movingPosition: number;
  movingSize: number;
  movingCrossStart: number;
  movingCrossEnd: number;
  left: AxisFrame;
  right: AxisFrame;
  placement: StructuredPrototypeFreeformSpacingPlacement;
}): PreparedSpacingCandidate | null {
  const target = candidatePosition(placement, movingSize, left, right);
  if (target === null || !Number.isFinite(target.position) || !Number.isFinite(target.gap)) {
    return null;
  }
  let position = Object.is(target.position, -0) ? 0 : target.position;
  if (
    isMeaningfullyBelow(position, input.minimumPosition) ||
    isMeaningfullyAbove(position, input.maximumPosition)
  ) {
    return null;
  }
  position = normalizeNear(position, input.minimumPosition);
  position = normalizeNear(position, input.maximumPosition);

  let correction = position - movingPosition;
  correction = Object.is(correction, -0) ? 0 : correction;
  const distance = Math.abs(correction);
  if (
    !Number.isFinite(distance) ||
    distance - input.threshold >
      structuredPrototypeFreeformSpacingTolerance(distance, input.threshold)
  ) {
    return null;
  }

  const crossStart = Math.max(movingCrossStart, left.crossStart, right.crossStart);
  const crossEnd = Math.min(movingCrossEnd, left.crossEnd, right.crossEnd);
  if (!(crossEnd > crossStart)) return null;
  const crossCoordinate = crossStart + (crossEnd - crossStart) / 2;
  const segments = buildSegments({
    placement,
    position,
    movingSize,
    left,
    right,
    crossCoordinate,
  });
  for (const segment of segments) {
    if (segment.end <= segment.start) return null;
    if (!structuredPrototypeFreeformSpacingLengthsMatch(segment.end - segment.start, target.gap)) {
      return null;
    }
  }

  const referenceNodeIds = [left.nodeId, right.nodeId] as const;
  const guide: StructuredPrototypeFreeformSpacingGuide = {
    axis: input.axis,
    placement,
    gap: target.gap,
    referenceNodeIds,
    segments,
  };
  const movingEnd = position + movingSize;
  const outerSpan = Math.max(movingEnd, right.end) - Math.min(position, left.start);
  if (!Number.isFinite(outerSpan) || outerSpan <= 0) return null;
  return {
    candidate: {
      position,
      correction,
      distance,
      placement,
      gap: target.gap,
      referenceNodeIds,
      guide,
      outerSpan,
    },
    blockerQuery: {
      axis: input.axis,
      projectedMovingBounds: projectMovingBounds(input.axis, input.movingBounds, position),
      crossStart,
      crossEnd,
      fixedCorridor: { start: left.end, end: right.start },
      segmentIntervals: [
        { start: segments[0].start, end: segments[0].end },
        { start: segments[1].start, end: segments[1].end },
      ],
    },
  };
}

/**
 * Finds the deterministic equal-spacing target for one move axis. The moving
 * frame is treated as one union and every guide compares exactly two positive
 * gaps between three lane-compatible, non-overlapping frames.
 */
export function resolveStructuredPrototypeFreeformSpacingSnap(
  input: StructuredPrototypeFreeformSpacingSnapInput,
): StructuredPrototypeFreeformSpacingSnapCandidate | null {
  if (input.axis !== "x" && input.axis !== "y") {
    throw new Error("freeform spacing snap axis must be x or y");
  }
  assertBounds(input.movingBounds, "moving bounds");
  const selectedNodeIds = resolveSelectedNodeIds(input.selectedNodeIds);
  assertSiblings(input.directSiblings);
  assertFinite(input.minimumPosition, "minimum position");
  assertFinite(input.maximumPosition, "maximum position");
  if (input.minimumPosition < 0) {
    throw new Error("freeform spacing snap minimum position must not be negative");
  }
  if (input.maximumPosition < input.minimumPosition) {
    throw new Error("freeform spacing snap maximum position must not be below minimum position");
  }
  assertFinite(input.threshold, "threshold");
  if (input.threshold < 0) {
    throw new Error("freeform spacing snap threshold must not be negative");
  }

  const movingPosition = axisPosition(input.axis, input.movingBounds);
  if (movingPosition < input.minimumPosition || movingPosition > input.maximumPosition) {
    throw new Error("freeform spacing snap moving position must be inside its envelope");
  }
  const movingSize = axisSize(input.axis, input.movingBounds);
  const [movingCrossStart, movingCrossEnd] = crossInterval(input.axis, input.movingBounds);
  const siblings = input.directSiblings
    .filter((sibling) => !selectedNodeIds.has(sibling.nodeId))
    .map((sibling) => toAxisFrame(input.axis, sibling))
    .sort(compareAxisFrames);
  const blockerCache = new Map<string, boolean>();
  let best: SpacingCandidate | null = null;
  for (let leftIndex = 0; leftIndex < siblings.length - 1; leftIndex += 1) {
    const left = siblings[leftIndex];
    if (left === undefined) {
      throw new Error(`freeform spacing snap missing left sibling at index ${leftIndex}`);
    }
    for (let rightIndex = leftIndex + 1; rightIndex < siblings.length; rightIndex += 1) {
      const right = siblings[rightIndex];
      if (right === undefined) {
        throw new Error(`freeform spacing snap missing right sibling at index ${rightIndex}`);
      }
      if (left.end >= right.start) continue;
      for (const placement of ["before", "between", "after"] as const) {
        const prepared = createPreparedCandidate({
          input,
          movingPosition,
          movingSize,
          movingCrossStart,
          movingCrossEnd,
          left,
          right,
          placement,
        });
        if (prepared === null) continue;
        if (best !== null && compareCandidates(prepared.candidate, best) >= 0) continue;

        const cacheKey = blockerQueryCacheKey(prepared.blockerQuery);
        let blocked = blockerCache.get(cacheKey);
        if (blocked === undefined) {
          // Positive-gap construction leaves both reference frames touching only query
          // boundaries. Scanning them is therefore safe and makes blocker results depend
          // exclusively on exact query geometry rather than on reference IDs.
          blocked = queryHasBlocker(prepared.blockerQuery, siblings);
          blockerCache.set(cacheKey, blocked);
        }
        if (!blocked) best = prepared.candidate;
      }
    }
  }
  if (best === null) return null;
  const { outerSpan: _outerSpan, ...candidate } = best;
  return candidate;
}
