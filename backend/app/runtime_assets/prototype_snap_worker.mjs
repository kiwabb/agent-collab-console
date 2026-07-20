// src/features/prototype/runtime/canonical.ts
var textEncoder = new TextEncoder();
function compareUnicodeCodePoints(left, right) {
  const leftPoints = Array.from(left);
  const rightPoints = Array.from(right);
  const length = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < length; index += 1) {
    const leftPoint = leftPoints[index]?.codePointAt(0);
    const rightPoint = rightPoints[index]?.codePointAt(0);
    if (leftPoint === void 0 || rightPoint === void 0 || leftPoint === rightPoint) {
      continue;
    }
    return leftPoint < rightPoint ? -1 : 1;
  }
  if (leftPoints.length === rightPoints.length) return 0;
  return leftPoints.length < rightPoints.length ? -1 : 1;
}
function assertWellFormedString(value) {
  if (!value.isWellFormed()) {
    throw new TypeError("Canonical runtime strings must contain valid Unicode");
  }
}
function canonicalize(value) {
  if (value === null) {
    return "null";
  }
  if (typeof value === "string" || typeof value === "boolean") {
    if (typeof value === "string") assertWellFormedString(value);
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value) || Object.is(value, -0)) {
      throw new TypeError("Canonical runtime numbers must be safe integers");
    }
    return String(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalize(item)).join(",")}]`;
  }
  if (typeof value === "object") {
    const entries = Object.entries(value).sort(
      ([left], [right]) => compareUnicodeCodePoints(left, right)
    );
    return `{${entries.map(([key, child]) => {
      assertWellFormedString(key);
      if (child === void 0) {
        throw new TypeError(`Canonical runtime object field ${key} is undefined`);
      }
      return `${JSON.stringify(key)}:${canonicalize(child)}`;
    }).join(",")}}`;
  }
  throw new TypeError(`Unsupported canonical runtime value type: ${typeof value}`);
}
function digestBytesToHex(bytes) {
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
function canonicalRuntimeJson(value) {
  return canonicalize(value);
}
async function hashRuntimeValue(value) {
  const canonical = canonicalRuntimeJson(value);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", textEncoder.encode(canonical));
  return `sha256:${digestBytesToHex(digest)}`;
}

// src/lib/utils.tsx
function safeJsonParse(input) {
  try {
    return JSON.parse(input);
  } catch {
    return null;
  }
}
function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// src/features/prototype/structured/structuredPrototypeFreeformGrids.ts
function cloneStructuredPrototypeFreeformGrids(grids) {
  return grids.map(
    (grid) => grid.type === "square" ? {
      ...grid,
      origin: { ...grid.origin },
      params: { ...grid.params }
    } : {
      ...grid,
      origin: { ...grid.origin },
      params: { ...grid.params }
    }
  );
}

// src/features/prototype/structured/structuredPrototypeGridGeometry.ts
var CANONICAL_DECIMAL_PATTERN = /^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,4})?$/u;
var GRID_VALUE_EPSILON = 1e-9;
var MAX_TRACK_COUNT = 24;
function valueTolerance(...values) {
  return GRID_VALUE_EPSILON * Math.max(1, ...values.map((value) => Math.abs(value)));
}
function compareText(left, right) {
  if (left === right) return 0;
  return left < right ? -1 : 1;
}
function assertFinite(value, label) {
  if (!Number.isFinite(value)) throw new Error(`freeform grid ${label} must be finite`);
}
function assertPositive(value, label) {
  assertFinite(value, label);
  if (value <= 0) throw new Error(`freeform grid ${label} must be positive`);
}
function parseDecimal(value, label, positive = false) {
  if (!CANONICAL_DECIMAL_PATTERN.test(value)) {
    throw new Error(`freeform grid ${label} must be a canonical decimal`);
  }
  const parsed = Number(value);
  assertFinite(parsed, label);
  if (positive && parsed <= 0) throw new Error(`freeform grid ${label} must be positive`);
  return parsed;
}
function assertFrame(frame) {
  assertPositive(frame.width, "frame width");
  assertPositive(frame.height, "frame height");
  return { width: frame.width, height: frame.height };
}
function assertAxis(axis) {
  if (axis !== "x" && axis !== "y") throw new Error("freeform grid snap axis is invalid");
}
function assertPresentation(grid) {
  if (grid.params.colorTokenKey.length === 0) {
    throw new Error("freeform grid color token key must not be empty");
  }
  const opacity = parseDecimal(grid.params.opacity, "opacity");
  if (opacity > 1) {
    throw new Error("freeform grid opacity must be between zero and one");
  }
}
function parseCommon(grid, frame) {
  if (grid.id.length === 0) throw new Error("freeform grid id must not be empty");
  if (grid.version !== 1) throw new Error("freeform grid version is unsupported");
  if (typeof grid.visible !== "boolean" || typeof grid.snapEnabled !== "boolean") {
    throw new Error("freeform grid visibility and snapping flags must be boolean");
  }
  assertPresentation(grid);
  const originX = parseDecimal(grid.origin.x, "origin x");
  const originY = parseDecimal(grid.origin.y, "origin y");
  if (originX >= frame.width || originY >= frame.height) {
    throw new Error("freeform grid origin must be inside its frame");
  }
  return {
    id: grid.id,
    visible: grid.visible,
    snapEnabled: grid.snapEnabled,
    originX,
    originY
  };
}
function clipRect(x, y, width, height, frame, label) {
  assertFinite(x, `${label} x`);
  assertFinite(y, `${label} y`);
  assertPositive(width, `${label} width`);
  assertPositive(height, `${label} height`);
  const left = Math.max(0, x);
  const top = Math.max(0, y);
  const right = Math.min(frame.width, x + width);
  const bottom = Math.min(frame.height, y + height);
  if (![left, top, right, bottom].every(Number.isFinite) || right <= left || bottom <= top) {
    throw new Error(`freeform grid ${label} does not intersect its frame`);
  }
  return { x: left, y: top, width: right - left, height: bottom - top };
}
function alignmentOffset(alignment, freeSpace) {
  if (freeSpace < -valueTolerance(freeSpace, 0)) {
    throw new Error("freeform grid tracks exceed their available frame length");
  }
  const stableFreeSpace = freeSpace < 0 ? 0 : freeSpace;
  switch (alignment) {
    case "stretch":
    case "start":
      return 0;
    case "center":
      return stableFreeSpace / 2;
    case "end":
      return stableFreeSpace;
  }
}
function calculateTrackAreas(grid, common, frame) {
  const { count, itemSize: encodedItemSize, alignment } = grid.params;
  if (!Number.isInteger(count) || count < 1 || count > MAX_TRACK_COUNT) {
    throw new Error(`freeform grid track count must be between 1 and ${MAX_TRACK_COUNT}`);
  }
  const gutter = parseDecimal(grid.params.gutter, "gutter");
  const margin = parseDecimal(grid.params.margin, "margin");
  const axisOrigin = grid.type === "columns" ? common.originX : common.originY;
  const axisLength = (grid.type === "columns" ? frame.width : frame.height) - axisOrigin;
  const availableForItems = axisLength - margin * 2 - gutter * (count - 1);
  if (!Number.isFinite(availableForItems) || availableForItems <= 0) {
    throw new Error("freeform grid tracks have no positive item area");
  }
  let itemSize;
  if (alignment === "stretch") {
    if (encodedItemSize !== null) {
      throw new Error("freeform grid stretch alignment requires a null item size");
    }
    itemSize = availableForItems / count;
  } else {
    if (encodedItemSize === null) {
      throw new Error("freeform grid non-stretch alignment requires an item size");
    }
    itemSize = parseDecimal(encodedItemSize, "item size", true);
  }
  assertPositive(itemSize, "resolved item size");
  const occupied = itemSize * count + gutter * (count - 1);
  const innerLength = axisLength - margin * 2;
  const offset = alignmentOffset(alignment, innerLength - occupied);
  const first = axisOrigin + margin + offset;
  const crossOrigin = grid.type === "columns" ? common.originY : common.originX;
  const crossLength = (grid.type === "columns" ? frame.height : frame.width) - crossOrigin;
  assertPositive(crossLength, "track cross length");
  return Array.from({ length: count }, (_, index) => {
    const axisPosition2 = first + index * (itemSize + gutter);
    const raw = grid.type === "columns" ? { x: axisPosition2, y: crossOrigin, width: itemSize, height: crossLength } : { x: crossOrigin, y: axisPosition2, width: crossLength, height: itemSize };
    const clipped = clipRect(raw.x, raw.y, raw.width, raw.height, frame, `track ${index}`);
    return { index, ...clipped };
  });
}
function calculateGrid(grid, frame) {
  const common = parseCommon(grid, frame);
  if (grid.type === "square") {
    const size = parseDecimal(grid.params.size, "square size", true);
    const remainingWidth = frame.width - common.originX;
    const remainingHeight = frame.height - common.originY;
    if (size - remainingWidth > valueTolerance(size, remainingWidth) || size - remainingHeight > valueTolerance(size, remainingHeight)) {
      throw new Error("freeform square grid does not fit inside its frame");
    }
    return { ...common, type: "square", size };
  }
  if (grid.type === "columns" || grid.type === "rows") {
    return {
      ...common,
      type: grid.type,
      areas: calculateTrackAreas(grid, common, frame)
    };
  }
  throw new Error("freeform grid type is unsupported");
}
function assertUniqueGridIds(grids) {
  const ids = /* @__PURE__ */ new Set();
  for (const grid of grids) {
    if (ids.has(grid.id)) throw new Error(`freeform grid id is duplicated: ${grid.id}`);
    ids.add(grid.id);
  }
}
function calculateGrids(grids, frame) {
  assertUniqueGridIds(grids);
  return grids.map((grid) => calculateGrid(grid, frame));
}
function calculateSortedSnapGrids(grids, frame) {
  return [...calculateGrids(grids, frame)].sort((left, right) => compareText(left.id, right.id));
}
function candidateFromCoordinate({
  calculation,
  axis,
  coordinate,
  requestedCoordinate,
  lineIndex
}) {
  assertFinite(coordinate, "snap line coordinate");
  const correction = coordinate - requestedCoordinate;
  return {
    gridId: calculation.id,
    gridType: calculation.type,
    axis,
    coordinate,
    correction,
    distance: Math.abs(correction),
    lineIndex
  };
}
function compareSnapLines(left, right) {
  const distanceDifference = left.distance - right.distance;
  if (Math.abs(distanceDifference) > valueTolerance(left.distance, right.distance)) {
    return distanceDifference < 0 ? -1 : 1;
  }
  const idOrder = compareText(left.gridId, right.gridId);
  if (idOrder !== 0) return idOrder;
  if (left.coordinate !== right.coordinate) return left.coordinate < right.coordinate ? -1 : 1;
  return left.lineIndex - right.lineIndex;
}
function chooseSnapLine(current, candidate) {
  return current === null || compareSnapLines(candidate, current) < 0 ? candidate : current;
}
function maximumSquareLineIndex(span, size) {
  const tolerance = valueTolerance(span, size);
  return Math.max(0, Math.floor((span - tolerance) / size));
}
function nearestSquareLine(calculation, frame, axis, requestedCoordinate) {
  const origin = axis === "x" ? calculation.originX : calculation.originY;
  const limit = axis === "x" ? frame.width : frame.height;
  const maximumIndex = maximumSquareLineIndex(limit - origin, calculation.size);
  if (maximumIndex < 0) return null;
  const approximateIndex = Math.round((requestedCoordinate - origin) / calculation.size);
  const indices = /* @__PURE__ */ new Set([
    0,
    maximumIndex,
    Math.max(0, Math.min(maximumIndex, approximateIndex - 1)),
    Math.max(0, Math.min(maximumIndex, approximateIndex)),
    Math.max(0, Math.min(maximumIndex, approximateIndex + 1))
  ]);
  let nearest = null;
  for (const lineIndex of indices) {
    const coordinate = origin + lineIndex * calculation.size;
    if (coordinate >= limit - valueTolerance(coordinate, limit)) continue;
    nearest = chooseSnapLine(
      nearest,
      candidateFromCoordinate({
        calculation,
        axis,
        coordinate,
        requestedCoordinate,
        lineIndex
      })
    );
  }
  return nearest;
}
function nearestTrackLine(calculation, axis, requestedCoordinate) {
  if (calculation.type === "columns" && axis !== "x" || calculation.type === "rows" && axis !== "y") {
    return null;
  }
  let nearest = null;
  for (const area of calculation.areas) {
    const start = axis === "x" ? area.x : area.y;
    const end = start + (axis === "x" ? area.width : area.height);
    nearest = chooseSnapLine(
      nearest,
      candidateFromCoordinate({
        calculation,
        axis,
        coordinate: start,
        requestedCoordinate,
        lineIndex: area.index * 2
      })
    );
    nearest = chooseSnapLine(
      nearest,
      candidateFromCoordinate({
        calculation,
        axis,
        coordinate: end,
        requestedCoordinate,
        lineIndex: area.index * 2 + 1
      })
    );
  }
  return nearest;
}
function resolveStructuredPrototypeNearestFreeformGridSnapLine({
  frame: inputFrame,
  grids,
  axis,
  coordinate
}) {
  const frame = assertFrame(inputFrame);
  assertAxis(axis);
  assertFinite(coordinate, "requested snap coordinate");
  let nearest = null;
  for (const calculation of calculateSortedSnapGrids(grids, frame)) {
    if (!calculation.snapEnabled) continue;
    const candidate = calculation.type === "square" ? nearestSquareLine(calculation, frame, axis, coordinate) : nearestTrackLine(calculation, axis, coordinate);
    if (candidate !== null) nearest = chooseSnapLine(nearest, candidate);
  }
  return nearest;
}

// src/features/prototype/structured/structuredPrototypeSpacingSnapping.ts
var SPACING_SNAP_RELATIVE_TOLERANCE = 1e-9;
function structuredPrototypeFreeformSpacingTolerance(...magnitudes) {
  let scale = 1;
  for (const magnitude of magnitudes) {
    const absoluteMagnitude = Math.abs(magnitude);
    if (absoluteMagnitude > scale) scale = absoluteMagnitude;
  }
  return SPACING_SNAP_RELATIVE_TOLERANCE * scale;
}
function structuredPrototypeFreeformSpacingLengthsMatch(segmentLength, gap) {
  if (!Number.isFinite(segmentLength) || !Number.isFinite(gap)) return false;
  return Math.abs(segmentLength - gap) <= structuredPrototypeFreeformSpacingTolerance(segmentLength, gap);
}
function normalizeNear(value, boundary) {
  return Math.abs(value - boundary) <= structuredPrototypeFreeformSpacingTolerance(value, boundary) ? boundary : value;
}
function isMeaningfullyBelow(value, minimum) {
  return minimum - value > structuredPrototypeFreeformSpacingTolerance(value, minimum);
}
function isMeaningfullyAbove(value, maximum) {
  return value - maximum > structuredPrototypeFreeformSpacingTolerance(value, maximum);
}
function assertFinite2(value, label) {
  if (!Number.isFinite(value)) {
    throw new Error(`freeform spacing snap ${label} must be finite`);
  }
}
function assertPositive2(value, label) {
  assertFinite2(value, label);
  if (value <= 0) {
    throw new Error(`freeform spacing snap ${label} must be positive`);
  }
}
function assertBounds(bounds, label) {
  assertFinite2(bounds.x, `${label} x`);
  assertFinite2(bounds.y, `${label} y`);
  assertPositive2(bounds.width, `${label} width`);
  assertPositive2(bounds.height, `${label} height`);
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
function resolveSelectedNodeIds(nodeIds) {
  if (nodeIds.length === 0) {
    throw new Error("freeform spacing snap requires at least one selected node");
  }
  const selected = /* @__PURE__ */ new Set();
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
function assertSiblings(siblings) {
  const nodeIds = /* @__PURE__ */ new Set();
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
function toAxisFrame(axis, sibling) {
  return axis === "x" ? {
    nodeId: sibling.nodeId,
    start: sibling.x,
    end: sibling.x + sibling.width,
    crossStart: sibling.y,
    crossEnd: sibling.y + sibling.height,
    bounds: sibling
  } : {
    nodeId: sibling.nodeId,
    start: sibling.y,
    end: sibling.y + sibling.height,
    crossStart: sibling.x,
    crossEnd: sibling.x + sibling.width,
    bounds: sibling
  };
}
function axisPosition(axis, bounds) {
  return axis === "x" ? bounds.x : bounds.y;
}
function axisSize(axis, bounds) {
  return axis === "x" ? bounds.width : bounds.height;
}
function crossInterval(axis, bounds) {
  return axis === "x" ? [bounds.y, bounds.y + bounds.height] : [bounds.x, bounds.x + bounds.width];
}
function compareText2(left, right) {
  if (left === right) return 0;
  return left < right ? -1 : 1;
}
function compareAxisFrames(left, right) {
  if (left.start !== right.start) return left.start < right.start ? -1 : 1;
  if (left.end !== right.end) return left.end < right.end ? -1 : 1;
  return compareText2(left.nodeId, right.nodeId);
}
function placementRank(placement) {
  switch (placement) {
    case "between":
      return 0;
    case "before":
      return 1;
    case "after":
      return 2;
  }
}
function compareCandidates(left, right) {
  if (left.distance !== right.distance) return left.distance < right.distance ? -1 : 1;
  if (left.outerSpan !== right.outerSpan) return left.outerSpan < right.outerSpan ? -1 : 1;
  const placementComparison = placementRank(left.placement) - placementRank(right.placement);
  if (placementComparison !== 0) return placementComparison;
  if (left.gap !== right.gap) return left.gap < right.gap ? -1 : 1;
  if (left.position !== right.position) return left.position < right.position ? -1 : 1;
  const firstIdComparison = compareText2(left.referenceNodeIds[0], right.referenceNodeIds[0]);
  if (firstIdComparison !== 0) return firstIdComparison;
  return compareText2(left.referenceNodeIds[1], right.referenceNodeIds[1]);
}
function intervalsOverlap(leftStart, leftEnd, rightStart, rightEnd) {
  return leftStart < rightEnd && rightStart < leftEnd;
}
function framesOverlap(left, right) {
  return intervalsOverlap(left.x, left.x + left.width, right.x, right.x + right.width) && intervalsOverlap(left.y, left.y + left.height, right.y, right.y + right.height);
}
function projectMovingBounds(axis, movingBounds, position) {
  return axis === "x" ? { ...movingBounds, x: position } : { ...movingBounds, y: position };
}
function corridorIsOccupied(blocker, start, end, crossStart, crossEnd) {
  return intervalsOverlap(blocker.start, blocker.end, start, end) && intervalsOverlap(blocker.crossStart, blocker.crossEnd, crossStart, crossEnd);
}
function blockerQueryCacheKey(query) {
  const { projectedMovingBounds, fixedCorridor, segmentIntervals } = query;
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
    segmentIntervals[1].end
  ].join("|");
}
function queryHasBlocker(query, siblings) {
  for (const blocker of siblings) {
    if (framesOverlap(query.projectedMovingBounds, blocker.bounds)) return true;
    if (corridorIsOccupied(
      blocker,
      query.fixedCorridor.start,
      query.fixedCorridor.end,
      query.crossStart,
      query.crossEnd
    ) || corridorIsOccupied(
      blocker,
      query.segmentIntervals[0].start,
      query.segmentIntervals[0].end,
      query.crossStart,
      query.crossEnd
    ) || corridorIsOccupied(
      blocker,
      query.segmentIntervals[1].start,
      query.segmentIntervals[1].end,
      query.crossStart,
      query.crossEnd
    )) {
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
  crossCoordinate
}) {
  switch (placement) {
    case "before":
      return [
        {
          start: position + movingSize,
          end: left.start,
          crossCoordinate,
          fromNodeId: null,
          toNodeId: left.nodeId,
          segmentIndex: 0
        },
        {
          start: left.end,
          end: right.start,
          crossCoordinate,
          fromNodeId: left.nodeId,
          toNodeId: right.nodeId,
          segmentIndex: 1
        }
      ];
    case "between":
      return [
        {
          start: left.end,
          end: position,
          crossCoordinate,
          fromNodeId: left.nodeId,
          toNodeId: null,
          segmentIndex: 0
        },
        {
          start: position + movingSize,
          end: right.start,
          crossCoordinate,
          fromNodeId: null,
          toNodeId: right.nodeId,
          segmentIndex: 1
        }
      ];
    case "after":
      return [
        {
          start: left.end,
          end: right.start,
          crossCoordinate,
          fromNodeId: left.nodeId,
          toNodeId: right.nodeId,
          segmentIndex: 0
        },
        {
          start: right.end,
          end: position,
          crossCoordinate,
          fromNodeId: right.nodeId,
          toNodeId: null,
          segmentIndex: 1
        }
      ];
  }
}
function candidatePosition(placement, movingSize, left, right) {
  const fixedGap = right.start - left.end;
  if (fixedGap <= structuredPrototypeFreeformSpacingTolerance(right.start, left.end, fixedGap)) {
    return null;
  }
  switch (placement) {
    case "before":
      return {
        position: left.start - movingSize - fixedGap,
        gap: fixedGap
      };
    case "between": {
      const gap = (fixedGap - movingSize) / 2;
      if (gap <= structuredPrototypeFreeformSpacingTolerance(fixedGap, movingSize, gap)) {
        return null;
      }
      return {
        position: left.end + gap,
        gap
      };
    }
    case "after":
      return {
        position: right.end + fixedGap,
        gap: fixedGap
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
  placement
}) {
  const target = candidatePosition(placement, movingSize, left, right);
  if (target === null || !Number.isFinite(target.position) || !Number.isFinite(target.gap)) {
    return null;
  }
  let position = Object.is(target.position, -0) ? 0 : target.position;
  if (isMeaningfullyBelow(position, input.minimumPosition) || isMeaningfullyAbove(position, input.maximumPosition)) {
    return null;
  }
  position = normalizeNear(position, input.minimumPosition);
  position = normalizeNear(position, input.maximumPosition);
  let correction = position - movingPosition;
  correction = Object.is(correction, -0) ? 0 : correction;
  const distance = Math.abs(correction);
  if (!Number.isFinite(distance) || distance - input.threshold > structuredPrototypeFreeformSpacingTolerance(distance, input.threshold)) {
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
    crossCoordinate
  });
  for (const segment of segments) {
    if (segment.end <= segment.start) return null;
    if (!structuredPrototypeFreeformSpacingLengthsMatch(segment.end - segment.start, target.gap)) {
      return null;
    }
  }
  const referenceNodeIds = [left.nodeId, right.nodeId];
  const guide = {
    axis: input.axis,
    placement,
    gap: target.gap,
    referenceNodeIds,
    segments
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
      outerSpan
    },
    blockerQuery: {
      axis: input.axis,
      projectedMovingBounds: projectMovingBounds(input.axis, input.movingBounds, position),
      crossStart,
      crossEnd,
      fixedCorridor: { start: left.end, end: right.start },
      segmentIntervals: [
        { start: segments[0].start, end: segments[0].end },
        { start: segments[1].start, end: segments[1].end }
      ]
    }
  };
}
function resolveStructuredPrototypeFreeformSpacingSnap(input) {
  if (input.axis !== "x" && input.axis !== "y") {
    throw new Error("freeform spacing snap axis must be x or y");
  }
  assertBounds(input.movingBounds, "moving bounds");
  const selectedNodeIds = resolveSelectedNodeIds(input.selectedNodeIds);
  assertSiblings(input.directSiblings);
  assertFinite2(input.minimumPosition, "minimum position");
  assertFinite2(input.maximumPosition, "maximum position");
  if (input.minimumPosition < 0) {
    throw new Error("freeform spacing snap minimum position must not be negative");
  }
  if (input.maximumPosition < input.minimumPosition) {
    throw new Error("freeform spacing snap maximum position must not be below minimum position");
  }
  assertFinite2(input.threshold, "threshold");
  if (input.threshold < 0) {
    throw new Error("freeform spacing snap threshold must not be negative");
  }
  const movingPosition = axisPosition(input.axis, input.movingBounds);
  if (movingPosition < input.minimumPosition || movingPosition > input.maximumPosition) {
    throw new Error("freeform spacing snap moving position must be inside its envelope");
  }
  const movingSize = axisSize(input.axis, input.movingBounds);
  const [movingCrossStart, movingCrossEnd] = crossInterval(input.axis, input.movingBounds);
  const siblings = input.directSiblings.filter((sibling) => !selectedNodeIds.has(sibling.nodeId)).map((sibling) => toAxisFrame(input.axis, sibling)).sort(compareAxisFrames);
  const blockerCache = /* @__PURE__ */ new Map();
  let best = null;
  for (let leftIndex = 0; leftIndex < siblings.length - 1; leftIndex += 1) {
    const left = siblings[leftIndex];
    if (left === void 0) {
      throw new Error(`freeform spacing snap missing left sibling at index ${leftIndex}`);
    }
    for (let rightIndex = leftIndex + 1; rightIndex < siblings.length; rightIndex += 1) {
      const right = siblings[rightIndex];
      if (right === void 0) {
        throw new Error(`freeform spacing snap missing right sibling at index ${rightIndex}`);
      }
      if (left.end >= right.start) continue;
      for (const placement of ["before", "between", "after"]) {
        const prepared = createPreparedCandidate({
          input,
          movingPosition,
          movingSize,
          movingCrossStart,
          movingCrossEnd,
          left,
          right,
          placement
        });
        if (prepared === null) continue;
        if (best !== null && compareCandidates(prepared.candidate, best) >= 0) continue;
        const cacheKey = blockerQueryCacheKey(prepared.blockerQuery);
        let blocked = blockerCache.get(cacheKey);
        if (blocked === void 0) {
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

// src/features/prototype/structured/structuredPrototypeSnapping.ts
var STRUCTURED_PROTOTYPE_FREEFORM_SNAP_THRESHOLD_CLIENT_PX = 6;
function assertFinite3(value, label) {
  if (!Number.isFinite(value)) throw new Error(`freeform snap ${label} must be finite`);
}
function assertPositive3(value, label) {
  assertFinite3(value, label);
  if (value <= 0) throw new Error(`freeform snap ${label} must be positive`);
}
function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum);
}
function assertBounds2(bounds, label) {
  assertFinite3(bounds.x, `${label} x`);
  assertFinite3(bounds.y, `${label} y`);
  assertPositive3(bounds.width, `${label} width`);
  assertPositive3(bounds.height, `${label} height`);
  if (bounds.x < 0 || bounds.y < 0) {
    throw new Error(`freeform snap ${label} position must not be negative`);
  }
}
function resolveSelectedNodeIds2(nodeIds) {
  if (nodeIds.length === 0) throw new Error("freeform snap requires at least one selected node");
  const selected = /* @__PURE__ */ new Set();
  for (const nodeId of nodeIds) {
    if (nodeId.length === 0) throw new Error("freeform snap selected node id must not be empty");
    if (selected.has(nodeId))
      throw new Error(`freeform snap selected node id is duplicated: ${nodeId}`);
    selected.add(nodeId);
  }
  return selected;
}
function assertSiblings2(siblings) {
  const nodeIds = /* @__PURE__ */ new Set();
  for (const sibling of siblings) {
    if (sibling.nodeId.length === 0) {
      throw new Error("freeform snap sibling node id must not be empty");
    }
    if (nodeIds.has(sibling.nodeId)) {
      throw new Error(`freeform snap sibling node id is duplicated: ${sibling.nodeId}`);
    }
    nodeIds.add(sibling.nodeId);
    assertBounds2(sibling, `sibling ${sibling.nodeId}`);
  }
}
function horizontalAnchors(bounds) {
  return [
    { anchor: "left", coordinate: bounds.x },
    { anchor: "center", coordinate: bounds.x + bounds.width / 2 },
    { anchor: "right", coordinate: bounds.x + bounds.width }
  ];
}
function verticalAnchors(bounds) {
  return [
    { anchor: "top", coordinate: bounds.y },
    { anchor: "middle", coordinate: bounds.y + bounds.height / 2 },
    { anchor: "bottom", coordinate: bounds.y + bounds.height }
  ];
}
function targetKindRank(kind) {
  if (kind === "container") return 0;
  if (kind === "sibling") return 1;
  return 2;
}
function compareNodeIds(left, right) {
  const leftValue = left ?? "";
  const rightValue = right ?? "";
  if (leftValue === rightValue) return 0;
  return leftValue < rightValue ? -1 : 1;
}
function isBetterCandidate(candidate, current) {
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
  threshold
}) {
  const movingBounds = { ...selectionBounds, x: position };
  const movingAnchors = horizontalAnchors(movingBounds);
  const targets = horizontalAnchors({ x: 0, y: 0, width: containerWidth, height: 1 }).map((target) => ({
    ...target,
    kind: "container",
    nodeId: null
  }));
  for (const sibling of directSiblings) {
    if (selectedNodeIds.has(sibling.nodeId)) continue;
    for (const target of horizontalAnchors(sibling)) {
      targets.push({ ...target, kind: "sibling", nodeId: sibling.nodeId });
    }
  }
  const maximumPosition = Math.max(0, containerWidth - selectionBounds.width);
  let best = null;
  for (const movingAnchor of movingAnchors) {
    for (const target of targets) {
      const correction = target.coordinate - movingAnchor.coordinate;
      const distance = Math.abs(correction);
      const snappedPosition = position + correction;
      if (distance > threshold || snappedPosition < 0 || snappedPosition > maximumPosition) {
        continue;
      }
      const candidate = {
        coordinate: target.coordinate,
        correction,
        distance,
        movingAnchor: movingAnchor.anchor,
        targetAnchor: target.anchor,
        targetKind: target.kind,
        targetNodeId: target.nodeId
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
      targetNodeId: best.targetNodeId
    }
  };
}
function resolveVerticalSnap({
  selectionBounds,
  directSiblings,
  selectedNodeIds,
  position,
  containerHeight,
  threshold
}) {
  const movingBounds = { ...selectionBounds, y: position };
  const movingAnchors = verticalAnchors(movingBounds);
  const targets = verticalAnchors({ x: 0, y: 0, width: 1, height: containerHeight }).map((target) => ({
    ...target,
    kind: "container",
    nodeId: null
  }));
  for (const sibling of directSiblings) {
    if (selectedNodeIds.has(sibling.nodeId)) continue;
    for (const target of verticalAnchors(sibling)) {
      targets.push({ ...target, kind: "sibling", nodeId: sibling.nodeId });
    }
  }
  const maximumPosition = Math.max(0, containerHeight - selectionBounds.height);
  let best = null;
  for (const movingAnchor of movingAnchors) {
    for (const target of targets) {
      const correction = target.coordinate - movingAnchor.coordinate;
      const distance = Math.abs(correction);
      const snappedPosition = position + correction;
      if (distance > threshold || snappedPosition < 0 || snappedPosition > maximumPosition) {
        continue;
      }
      const candidate = {
        coordinate: target.coordinate,
        correction,
        distance,
        movingAnchor: movingAnchor.anchor,
        targetAnchor: target.anchor,
        targetKind: target.kind,
        targetNodeId: target.nodeId
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
      targetNodeId: best.targetNodeId
    }
  };
}
function snapAnchorRank(anchor) {
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
function isBetterGridCandidate(candidate, current) {
  if (current === null) return true;
  if (candidate.distance !== current.distance) return candidate.distance < current.distance;
  if (candidate.line.gridId !== current.line.gridId) {
    return candidate.line.gridId < current.line.gridId;
  }
  if (candidate.line.coordinate !== current.line.coordinate) {
    return candidate.line.coordinate < current.line.coordinate;
  }
  const anchorOrder = snapAnchorRank(candidate.guide.movingAnchor) - snapAnchorRank(current.guide.movingAnchor);
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
  grids
}) {
  const movingBounds = {
    ...selectionBounds,
    ...axis === "x" ? { x: position } : { y: position }
  };
  const anchors = axis === "x" ? horizontalAnchors(movingBounds) : verticalAnchors(movingBounds);
  const maximumPosition = Math.max(
    0,
    axis === "x" ? containerWidth - selectionBounds.width : containerHeight - selectionBounds.height
  );
  let best = null;
  for (const anchor of anchors) {
    const line = resolveStructuredPrototypeNearestFreeformGridSnapLine({
      frame: { width: containerWidth, height: containerHeight },
      grids,
      axis,
      coordinate: anchor.coordinate
    });
    if (line === null || line.distance > threshold) continue;
    const snappedPosition = position + line.correction;
    if (snappedPosition < 0 || snappedPosition > maximumPosition) continue;
    const candidate = {
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
        gridLineIndex: line.lineIndex
      }
    };
    if (isBetterGridCandidate(candidate, best)) best = candidate;
  }
  return best;
}
function snapValueTolerance(left, right) {
  return 1e-9 * Math.max(1, Math.abs(left), Math.abs(right));
}
function distanceIsAtMost(left, right) {
  return left - right <= snapValueTolerance(left, right);
}
function distancesAreTied(left, right) {
  return distanceIsAtMost(left, right) && distanceIsAtMost(right, left);
}
function resolveAxisSnap(alignment, spacing, grid) {
  if (alignment.distance !== null && (spacing === null || distanceIsAtMost(alignment.distance, spacing.distance)) && (grid === null || distanceIsAtMost(alignment.distance, grid.distance))) {
    return {
      position: alignment.position,
      guide: alignment.guide,
      spacingGuide: null,
      gridGuide: null
    };
  }
  if (spacing !== null && (grid === null || distanceIsAtMost(spacing.distance, grid.distance))) {
    return {
      position: spacing.position,
      guide: null,
      spacingGuide: spacing.guide,
      gridGuide: null
    };
  }
  if (grid !== null) {
    return {
      position: grid.position,
      guide: null,
      spacingGuide: null,
      gridGuide: grid.guide
    };
  }
  return { position: alignment.position, guide: null, spacingGuide: null, gridGuide: null };
}
function resolveDiagnosticAxisWinner(resolved) {
  if (resolved.guide !== null) return "alignment";
  if (resolved.spacingGuide !== null) return "spacing";
  if (resolved.gridGuide !== null) return "grid";
  return "raw";
}
function diagnosticSortKey(parts) {
  return parts.map((part) => {
    if (part === null) return "null";
    if (typeof part === "number") return `number:${String(part)}`;
    return `string:${part.length}:${part}`;
  }).join("|");
}
function resolveDiagnosticWinnerDistance({
  winner,
  alignment,
  spacing,
  grid
}) {
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
  spacingWasInitiallySelected
}) {
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
  resolved
}) {
  const diagnosticSpacing = spacing === null ? null : {
    ...spacing,
    correction: spacing.position - rawPosition,
    distance: Math.abs(spacing.position - rawPosition)
  };
  const winner = resolveDiagnosticAxisWinner(resolved);
  const winnerDistance = resolveDiagnosticWinnerDistance({
    winner,
    alignment,
    spacing: diagnosticSpacing,
    grid
  });
  const spacingWasInitiallySelected = diagnosticSpacing !== null && resolveAxisSnap(alignment, diagnosticSpacing, grid).spacingGuide !== null;
  const outcome = (source, distance) => resolveDiagnosticCandidateOutcome({
    source,
    distance,
    winner,
    winnerDistance,
    spacingWasInitiallySelected
  });
  const candidates = [];
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
        alignment.position
      ]),
      coordinate: guide.coordinate,
      movingAnchor: guide.movingAnchor,
      targetAnchor: guide.targetAnchor,
      targetKind: guide.targetKind,
      targetNodeId: guide.targetNodeId
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
        diagnosticSpacing.referenceNodeIds[1]
      ]),
      placement: diagnosticSpacing.placement,
      gap: diagnosticSpacing.gap,
      referenceNodeIds: diagnosticSpacing.referenceNodeIds
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
        grid.position
      ]),
      gridId: grid.line.gridId,
      gridType: grid.line.gridType,
      gridLineIndex: grid.line.lineIndex,
      coordinate: grid.line.coordinate,
      movingAnchor: grid.guide.movingAnchor
    });
  }
  return candidates;
}
function selectedSpacingCandidate(alignment, spacing, grid) {
  return resolveAxisSnap(alignment, spacing, grid).spacingGuide === null ? null : spacing;
}
function refreshSpacingCandidate({
  axis,
  candidate,
  finalBounds,
  selectedNodeIds,
  directSiblings,
  maximumPosition
}) {
  const tolerance = snapValueTolerance(
    candidate.position,
    axis === "x" ? finalBounds.x : finalBounds.y
  );
  const refreshed = resolveStructuredPrototypeFreeformSpacingSnap({
    axis,
    movingBounds: finalBounds,
    selectedNodeIds,
    directSiblings,
    minimumPosition: 0,
    maximumPosition,
    threshold: tolerance
  });
  if (refreshed === null || Math.abs(refreshed.position - candidate.position) > snapValueTolerance(refreshed.position, candidate.position)) {
    return null;
  }
  return refreshed;
}
function resolvedSpacingCandidate(resolved, candidate) {
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
  maximumY
}) {
  const horizontal = resolveAxisSnap(horizontalAlignment, horizontalSpacing, horizontalGrid);
  const vertical = resolveAxisSnap(verticalAlignment, verticalSpacing, verticalGrid);
  const finalBounds = {
    ...selectionBounds,
    x: horizontal.position,
    y: vertical.position
  };
  const refreshedHorizontal = horizontalSpacing === null ? null : refreshSpacingCandidate({
    axis: "x",
    candidate: horizontalSpacing,
    finalBounds,
    selectedNodeIds,
    directSiblings,
    maximumPosition: maximumX
  });
  const refreshedVertical = verticalSpacing === null ? null : refreshSpacingCandidate({
    axis: "y",
    candidate: verticalSpacing,
    finalBounds,
    selectedNodeIds,
    directSiblings,
    maximumPosition: maximumY
  });
  const invalidAxes = [];
  if (horizontalSpacing !== null && refreshedHorizontal === null) invalidAxes.push("x");
  if (verticalSpacing !== null && refreshedVertical === null) invalidAxes.push("y");
  const resolvedHorizontal = resolveAxisSnap(
    horizontalAlignment,
    refreshedHorizontal,
    horizontalGrid
  );
  const resolvedVertical = resolveAxisSnap(verticalAlignment, refreshedVertical, verticalGrid);
  return {
    result: {
      horizontal: resolvedHorizontal,
      vertical: resolvedVertical,
      horizontalSpacingCandidate: resolvedSpacingCandidate(resolvedHorizontal, refreshedHorizontal),
      verticalSpacingCandidate: resolvedSpacingCandidate(resolvedVertical, refreshedVertical)
    },
    invalidAxes
  };
}
function planIsValid(plan) {
  return plan.invalidAxes.length === 0;
}
function resolveStructuredPrototypeFreeformCombinedSnaps(input) {
  const selectedHorizontal = selectedSpacingCandidate(
    input.horizontalAlignment,
    input.horizontalSpacing,
    input.horizontalGrid
  );
  const selectedVertical = selectedSpacingCandidate(
    input.verticalAlignment,
    input.verticalSpacing,
    input.verticalGrid
  );
  const initialPlan = evaluateSpacingPlan({
    ...input,
    horizontalSpacing: selectedHorizontal,
    verticalSpacing: selectedVertical
  });
  if (planIsValid(initialPlan)) return initialPlan.result;
  const horizontalInvalid = initialPlan.invalidAxes.includes("x");
  const verticalInvalid = initialPlan.invalidAxes.includes("y");
  const fallbackPlan = () => evaluateSpacingPlan({
    ...input,
    horizontalSpacing: null,
    verticalSpacing: null
  }).result;
  if (horizontalInvalid !== verticalInvalid) {
    const retainedPlan = evaluateSpacingPlan({
      ...input,
      horizontalSpacing: horizontalInvalid ? null : selectedHorizontal,
      verticalSpacing: verticalInvalid ? null : selectedVertical
    });
    return planIsValid(retainedPlan) ? retainedPlan.result : fallbackPlan();
  }
  if (selectedHorizontal === null || selectedVertical === null) {
    throw new Error("invalid dual-axis spacing plan requires both spacing candidates");
  }
  const horizontalFirst = selectedHorizontal.distance <= selectedVertical.distance;
  const preferredPlan = evaluateSpacingPlan({
    ...input,
    horizontalSpacing: horizontalFirst ? selectedHorizontal : null,
    verticalSpacing: horizontalFirst ? null : selectedVertical
  });
  if (planIsValid(preferredPlan)) return preferredPlan.result;
  const alternatePlan = evaluateSpacingPlan({
    ...input,
    horizontalSpacing: horizontalFirst ? null : selectedHorizontal,
    verticalSpacing: horizontalFirst ? selectedVertical : null
  });
  return planIsValid(alternatePlan) ? alternatePlan.result : fallbackPlan();
}
function resolveStructuredPrototypeFreeformMoveSnap({
  selectionBounds,
  selectedNodeIds,
  requestedDelta,
  containerWidth,
  containerHeight,
  previewScale,
  directSiblings,
  grids = [],
  gridSnappingEnabled = true
}) {
  assertPositive3(containerWidth, "container width");
  assertPositive3(containerHeight, "container height");
  assertPositive3(previewScale, "preview scale");
  assertFinite3(requestedDelta.x, "requested delta x");
  assertFinite3(requestedDelta.y, "requested delta y");
  assertBounds2(selectionBounds, "selection bounds");
  const selected = resolveSelectedNodeIds2(selectedNodeIds);
  assertSiblings2(directSiblings);
  const unclampedPosition = {
    x: selectionBounds.x + requestedDelta.x,
    y: selectionBounds.y + requestedDelta.y
  };
  const clampedPosition = {
    x: clamp(unclampedPosition.x, 0, Math.max(0, containerWidth - selectionBounds.width)),
    y: clamp(unclampedPosition.y, 0, Math.max(0, containerHeight - selectionBounds.height))
  };
  const threshold = STRUCTURED_PROTOTYPE_FREEFORM_SNAP_THRESHOLD_CLIENT_PX / previewScale;
  const horizontalAlignment = resolveHorizontalSnap({
    selectionBounds,
    directSiblings,
    selectedNodeIds: selected,
    position: clampedPosition.x,
    containerWidth,
    threshold
  });
  const verticalAlignment = resolveVerticalSnap({
    selectionBounds,
    directSiblings,
    selectedNodeIds: selected,
    position: clampedPosition.y,
    containerHeight,
    threshold
  });
  const movingBounds = {
    ...selectionBounds,
    x: clampedPosition.x,
    y: clampedPosition.y
  };
  const maximumX = Math.max(0, containerWidth - selectionBounds.width);
  const maximumY = Math.max(0, containerHeight - selectionBounds.height);
  const horizontalSpacing = selectionBounds.width > containerWidth ? null : resolveStructuredPrototypeFreeformSpacingSnap({
    axis: "x",
    movingBounds,
    selectedNodeIds,
    directSiblings,
    minimumPosition: 0,
    maximumPosition: maximumX,
    threshold
  });
  const verticalSpacing = selectionBounds.height > containerHeight ? null : resolveStructuredPrototypeFreeformSpacingSnap({
    axis: "y",
    movingBounds,
    selectedNodeIds,
    directSiblings,
    minimumPosition: 0,
    maximumPosition: maximumY,
    threshold
  });
  const horizontalGrid = gridSnappingEnabled && grids.length > 0 ? resolveGridSnap({
    axis: "x",
    selectionBounds,
    position: clampedPosition.x,
    containerWidth,
    containerHeight,
    threshold,
    grids
  }) : null;
  const verticalGrid = gridSnappingEnabled && grids.length > 0 ? resolveGridSnap({
    axis: "y",
    selectionBounds,
    position: clampedPosition.y,
    containerWidth,
    containerHeight,
    threshold,
    grids
  }) : null;
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
    maximumY
  });
  const { horizontal, vertical } = combined;
  const position = { x: horizontal.position, y: vertical.position };
  const guides = [
    horizontal.guide,
    horizontal.gridGuide,
    vertical.guide,
    vertical.gridGuide
  ].filter((guide) => guide !== null);
  const spacingGuides = [horizontal.spacingGuide, vertical.spacingGuide].filter(
    (guide) => guide !== null
  );
  const diagnostics = {
    rawPosition: clampedPosition,
    threshold,
    axisWinners: {
      x: resolveDiagnosticAxisWinner(horizontal),
      y: resolveDiagnosticAxisWinner(vertical)
    },
    candidates: [
      ...resolveAxisDiagnosticCandidates({
        axis: "x",
        rawPosition: clampedPosition.x,
        alignment: horizontalAlignment,
        spacing: combined.horizontalSpacingCandidate ?? horizontalSpacing,
        grid: horizontalGrid,
        resolved: horizontal
      }),
      ...resolveAxisDiagnosticCandidates({
        axis: "y",
        rawPosition: clampedPosition.y,
        alignment: verticalAlignment,
        spacing: combined.verticalSpacingCandidate ?? verticalSpacing,
        grid: verticalGrid,
        resolved: vertical
      })
    ]
  };
  return {
    delta: {
      x: position.x - selectionBounds.x,
      y: position.y - selectionBounds.y
    },
    position,
    guides,
    spacingGuides,
    diagnostics
  };
}

// src/features/prototype/structured/structuredPrototypeSnapBuildIdentity.ts
var STRUCTURED_PROTOTYPE_SNAP_SOLVER_VERSION = "structured-prototype-freeform-snap/v1";
var STRUCTURED_PROTOTYPE_SNAP_SOURCE_HASH = "sha256:62e45d53f507f2b8846ac3000ef5199288f58dfccf11afad218c2aee671dcb37";

// src/features/prototype/structured/structuredPrototypeFreeformMoveReplay.ts
var SHA256_PATTERN = /^sha256:[0-9a-f]{64}$/u;
var UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;
var SIGNED_DECIMAL_PATTERN = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,4})?$/u;
var NON_NEGATIVE_DECIMAL_PATTERN = /^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,4})?$/u;
var TECHNICAL_KEY_PATTERN = /^[a-z][a-z0-9-]{0,63}$/u;
var StructuredPrototypeFreeformMoveReplayError = class extends Error {
  code;
  constructor(code, message) {
    super(message);
    this.name = "StructuredPrototypeFreeformMoveReplayError";
    this.code = code;
  }
};
function replayError(code, message) {
  return new StructuredPrototypeFreeformMoveReplayError(code, message);
}
function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}
function canonicalSignedNumber(value, path) {
  if (!Number.isFinite(value)) {
    throw replayError("invalid_replay_input", `${path} must be finite`);
  }
  const canonical = Number(value.toFixed(4));
  return Object.is(canonical, -0) ? 0 : canonical;
}
function canonicalPoint(point, path) {
  return {
    x: canonicalSignedNumber(point.x, `${path}.x`),
    y: canonicalSignedNumber(point.y, `${path}.y`)
  };
}
function canonicalBounds(bounds, path) {
  return {
    ...canonicalPoint(bounds, path),
    width: canonicalSignedNumber(bounds.width, `${path}.width`),
    height: canonicalSignedNumber(bounds.height, `${path}.height`)
  };
}
function compareCanonicalIds(left, right) {
  if (left === right) return 0;
  return left < right ? -1 : 1;
}
function canonicalizeStructuredPrototypeFreeformMoveReplayInput(input) {
  const selectedNodeIds = [...input.selectedNodeIds].sort(compareCanonicalIds);
  const directSiblings = input.directSiblings.map((sibling) => ({
    nodeId: sibling.nodeId,
    ...canonicalBounds(sibling, `directSiblings.${sibling.nodeId}`)
  })).sort((left, right) => compareCanonicalIds(left.nodeId, right.nodeId));
  return {
    selectionBounds: canonicalBounds(input.selectionBounds, "selectionBounds"),
    selectedNodeIds,
    requestedDelta: canonicalPoint(input.requestedDelta, "requestedDelta"),
    containerWidth: canonicalSignedNumber(input.containerWidth, "containerWidth"),
    containerHeight: canonicalSignedNumber(input.containerHeight, "containerHeight"),
    previewScale: canonicalSignedNumber(input.previewScale, "previewScale"),
    directSiblings,
    grids: cloneStructuredPrototypeFreeformGrids(input.grids),
    gridSnappingEnabled: input.gridSnappingEnabled,
    bypassSnapping: input.bypassSnapping
  };
}
function bypassProjection(canonicalInput, projection) {
  const position = { ...projection.diagnostics.rawPosition };
  const diagnostics = {
    rawPosition: { ...position },
    threshold: projection.diagnostics.threshold,
    axisWinners: { x: "raw", y: "raw" },
    candidates: []
  };
  return {
    position,
    delta: {
      x: position.x - canonicalInput.selectionBounds.x,
      y: position.y - canonicalInput.selectionBounds.y
    },
    guides: [],
    spacingGuides: [],
    diagnostics
  };
}
function replayStructuredPrototypeFreeformMove(input) {
  const canonicalInput = canonicalizeStructuredPrototypeFreeformMoveReplayInput(input);
  let projection;
  try {
    projection = resolveStructuredPrototypeFreeformMoveSnap({
      selectionBounds: canonicalInput.selectionBounds,
      selectedNodeIds: canonicalInput.selectedNodeIds,
      requestedDelta: canonicalInput.requestedDelta,
      containerWidth: canonicalInput.containerWidth,
      containerHeight: canonicalInput.containerHeight,
      previewScale: canonicalInput.previewScale,
      directSiblings: canonicalInput.directSiblings,
      grids: canonicalInput.grids,
      gridSnappingEnabled: canonicalInput.gridSnappingEnabled
    });
  } catch (error) {
    if (error instanceof StructuredPrototypeFreeformMoveReplayError) throw error;
    throw replayError(
      "invalid_replay_input",
      `Freeform move replay failed: ${errorMessage(error)}`
    );
  }
  const resolved = canonicalInput.bypassSnapping ? bypassProjection(canonicalInput, projection) : projection;
  return { ...resolved, canonicalInput };
}
function canonicalSignedDecimal(value) {
  const canonical = canonicalSignedNumber(value, "evidence decimal");
  return String(canonical);
}
function serializePoint(point) {
  return {
    x: canonicalSignedDecimal(point.x),
    y: canonicalSignedDecimal(point.y)
  };
}
function serializeBounds(bounds) {
  return {
    ...serializePoint(bounds),
    width: canonicalSignedDecimal(bounds.width),
    height: canonicalSignedDecimal(bounds.height)
  };
}
function serializeSibling(sibling) {
  return {
    nodeId: sibling.nodeId,
    ...serializeBounds(sibling)
  };
}
function serializeCandidateCommon(candidate) {
  return {
    axis: candidate.axis,
    position: canonicalSignedDecimal(candidate.position),
    correction: canonicalSignedDecimal(candidate.correction),
    distance: canonicalSignedDecimal(candidate.distance),
    sortKey: candidate.sortKey,
    outcome: candidate.outcome
  };
}
function serializeCandidate(candidate) {
  const common = serializeCandidateCommon(candidate);
  switch (candidate.source) {
    case "alignment":
      return {
        source: candidate.source,
        ...common,
        coordinate: canonicalSignedDecimal(candidate.coordinate),
        movingAnchor: candidate.movingAnchor,
        targetAnchor: candidate.targetAnchor,
        targetKind: candidate.targetKind,
        targetNodeId: candidate.targetNodeId
      };
    case "spacing":
      return {
        source: candidate.source,
        ...common,
        placement: candidate.placement,
        gap: canonicalSignedDecimal(candidate.gap),
        referenceNodeIds: [candidate.referenceNodeIds[0], candidate.referenceNodeIds[1]]
      };
    case "grid":
      return {
        source: candidate.source,
        ...common,
        gridId: candidate.gridId,
        gridType: candidate.gridType,
        gridLineIndex: candidate.gridLineIndex,
        coordinate: canonicalSignedDecimal(candidate.coordinate),
        movingAnchor: candidate.movingAnchor
      };
  }
}
async function buildStructuredPrototypeFreeformMoveEvidence(input) {
  const replay = replayStructuredPrototypeFreeformMove(input);
  const canonicalInput = replay.canonicalInput;
  const grids = cloneStructuredPrototypeFreeformGrids(canonicalInput.grids);
  const rawPosition = replay.diagnostics.rawPosition;
  const finalPosition = replay.position;
  return {
    evidenceVersion: 2,
    kind: "freeformMove",
    snapSolverVersion: STRUCTURED_PROTOTYPE_SNAP_SOLVER_VERSION,
    snapSolverSourceHash: STRUCTURED_PROTOTYPE_SNAP_SOURCE_HASH,
    documentId: input.documentId,
    draftId: input.draftId,
    freeformId: input.freeformId,
    baseHeadSequenceNo: input.baseHeadSequenceNo,
    baseDocumentHash: input.baseDocumentHash,
    selectedNodeIds: [...canonicalInput.selectedNodeIds],
    grids,
    gridListHash: await hashRuntimeValue(grids),
    gridSnappingEnabled: canonicalInput.gridSnappingEnabled,
    previewScale: canonicalSignedDecimal(canonicalInput.previewScale),
    clientThreshold: "6",
    selectionBounds: serializeBounds(canonicalInput.selectionBounds),
    directSiblings: canonicalInput.directSiblings.map((sibling) => serializeSibling(sibling)),
    containerSize: {
      width: canonicalSignedDecimal(canonicalInput.containerWidth),
      height: canonicalSignedDecimal(canonicalInput.containerHeight)
    },
    requestedDelta: serializePoint(canonicalInput.requestedDelta),
    rawPosition: serializePoint(rawPosition),
    finalPosition: serializePoint(finalPosition),
    correction: serializePoint({
      x: finalPosition.x - rawPosition.x,
      y: finalPosition.y - rawPosition.y
    }),
    bypassSnapping: canonicalInput.bypassSnapping,
    axisWinners: { ...replay.diagnostics.axisWinners },
    candidates: replay.diagnostics.candidates.map((candidate) => serializeCandidate(candidate)),
    terminalReason: "pointerup"
  };
}
function invalidEvidence(message) {
  throw replayError("invalid_evidence", message);
}
function evidenceRecord(value, path) {
  if (!isRecord(value)) invalidEvidence(`${path} must be an object`);
  return value;
}
function exactKeys(record, keys, path) {
  const expected = new Set(keys);
  for (const key of Object.keys(record)) {
    if (!expected.has(key)) invalidEvidence(`${path} contains unknown field ${key}`);
  }
  for (const key of keys) {
    if (!Object.hasOwn(record, key)) invalidEvidence(`${path} is missing field ${key}`);
  }
}
function evidenceString(value, path) {
  if (typeof value !== "string" || value.length === 0) {
    invalidEvidence(`${path} must be a non-empty string`);
  }
  return value;
}
function evidenceBoundedString(value, maximumLength, path) {
  const parsed = evidenceString(value, path);
  if (Array.from(parsed).length > maximumLength) {
    invalidEvidence(`${path} must contain at most ${maximumLength} characters`);
  }
  return parsed;
}
function evidenceEntityId(value, path) {
  const parsed = evidenceString(value, path);
  if (!UUID_PATTERN.test(parsed)) invalidEvidence(`${path} must be a canonical UUID`);
  return parsed;
}
function evidenceSha256(value, path) {
  const parsed = evidenceString(value, path);
  if (!SHA256_PATTERN.test(parsed)) invalidEvidence(`${path} must be a SHA-256 value`);
  return parsed;
}
function evidenceBoolean(value, path) {
  if (typeof value !== "boolean") invalidEvidence(`${path} must be a boolean`);
  return value;
}
function evidenceInteger(value, minimum, maximum, path) {
  if (!Number.isSafeInteger(value) || typeof value !== "number" || value < minimum || value > maximum) {
    invalidEvidence(`${path} must be an integer from ${minimum} to ${maximum}`);
  }
  return value;
}
function evidenceLiteral(value, values, path) {
  for (const candidate of values) {
    if (value === candidate) return candidate;
  }
  invalidEvidence(`${path} is unsupported`);
}
function evidenceSignedDecimal(value, path) {
  const parsed = evidenceString(value, path);
  if (!SIGNED_DECIMAL_PATTERN.test(parsed) || parsed.startsWith("-") && Number(parsed) === 0) {
    invalidEvidence(`${path} must be a canonical signed decimal`);
  }
  if (!Number.isFinite(Number(parsed))) invalidEvidence(`${path} must be finite`);
  return parsed;
}
function evidenceNonNegativeDecimal(value, path) {
  const parsed = evidenceString(value, path);
  if (!NON_NEGATIVE_DECIMAL_PATTERN.test(parsed) || !Number.isFinite(Number(parsed))) {
    invalidEvidence(`${path} must be a canonical non-negative decimal`);
  }
  return parsed;
}
function evidencePositiveDecimal(value, path) {
  const parsed = evidenceNonNegativeDecimal(value, path);
  if (Number(parsed) <= 0) invalidEvidence(`${path} must be positive`);
  return parsed;
}
function evidenceTechnicalKey(value, path) {
  const parsed = evidenceString(value, path);
  if (!TECHNICAL_KEY_PATTERN.test(parsed)) invalidEvidence(`${path} must be a technical key`);
  return parsed;
}
function evidenceArray(value, maximumLength, path) {
  if (!Array.isArray(value) || value.length > maximumLength) {
    invalidEvidence(`${path} must be an array with at most ${maximumLength} items`);
  }
  return value;
}
function parseEvidencePoint(value, path) {
  const record = evidenceRecord(value, path);
  exactKeys(record, ["x", "y"], path);
  return {
    x: evidenceSignedDecimal(record["x"], `${path}.x`),
    y: evidenceSignedDecimal(record["y"], `${path}.y`)
  };
}
function parseEvidenceBounds(value, path) {
  const record = evidenceRecord(value, path);
  exactKeys(record, ["x", "y", "width", "height"], path);
  return {
    x: evidenceSignedDecimal(record["x"], `${path}.x`),
    y: evidenceSignedDecimal(record["y"], `${path}.y`),
    width: evidencePositiveDecimal(record["width"], `${path}.width`),
    height: evidencePositiveDecimal(record["height"], `${path}.height`)
  };
}
function parseEvidenceSibling(value, path) {
  const record = evidenceRecord(value, path);
  exactKeys(record, ["nodeId", "x", "y", "width", "height"], path);
  return {
    nodeId: evidenceEntityId(record["nodeId"], `${path}.nodeId`),
    x: evidenceSignedDecimal(record["x"], `${path}.x`),
    y: evidenceSignedDecimal(record["y"], `${path}.y`),
    width: evidencePositiveDecimal(record["width"], `${path}.width`),
    height: evidencePositiveDecimal(record["height"], `${path}.height`)
  };
}
function parseEvidenceOrigin(value, path) {
  const record = evidenceRecord(value, path);
  exactKeys(record, ["x", "y"], path);
  const x = evidenceNonNegativeDecimal(record["x"], `${path}.x`);
  const y = evidenceNonNegativeDecimal(record["y"], `${path}.y`);
  if (Number(x) > 4096 || Number(y) > 4096) invalidEvidence(`${path} exceeds 4096`);
  return { x, y };
}
function parseEvidenceGrid(value, path) {
  const record = evidenceRecord(value, path);
  exactKeys(record, ["id", "version", "type", "visible", "snapEnabled", "origin", "params"], path);
  const id = evidenceEntityId(record["id"], `${path}.id`);
  if (record["version"] !== 1) invalidEvidence(`${path}.version is unsupported`);
  const visible = evidenceBoolean(record["visible"], `${path}.visible`);
  const snapEnabled = evidenceBoolean(record["snapEnabled"], `${path}.snapEnabled`);
  const origin = parseEvidenceOrigin(record["origin"], `${path}.origin`);
  const type = evidenceLiteral(
    record["type"],
    ["square", "columns", "rows"],
    `${path}.type`
  );
  const params = evidenceRecord(record["params"], `${path}.params`);
  if (type === "square") {
    exactKeys(params, ["size", "colorTokenKey", "opacity"], `${path}.params`);
    const size = evidencePositiveDecimal(params["size"], `${path}.params.size`);
    const opacity2 = evidenceNonNegativeDecimal(params["opacity"], `${path}.params.opacity`);
    if (Number(size) > 4096 || Number(opacity2) > 1)
      invalidEvidence(`${path}.params is out of range`);
    return {
      id,
      version: 1,
      type,
      visible,
      snapEnabled,
      origin,
      params: {
        size,
        colorTokenKey: evidenceTechnicalKey(
          params["colorTokenKey"],
          `${path}.params.colorTokenKey`
        ),
        opacity: opacity2
      }
    };
  }
  exactKeys(
    params,
    ["count", "itemSize", "gutter", "margin", "alignment", "colorTokenKey", "opacity"],
    `${path}.params`
  );
  const alignment = evidenceLiteral(
    params["alignment"],
    ["stretch", "start", "center", "end"],
    `${path}.params.alignment`
  );
  const itemSize = params["itemSize"] === null ? null : evidencePositiveDecimal(params["itemSize"], `${path}.params.itemSize`);
  if (alignment === "stretch" !== (itemSize === null)) {
    invalidEvidence(`${path}.params.itemSize does not match alignment`);
  }
  const gutter = evidenceNonNegativeDecimal(params["gutter"], `${path}.params.gutter`);
  const margin = evidenceNonNegativeDecimal(params["margin"], `${path}.params.margin`);
  const opacity = evidenceNonNegativeDecimal(params["opacity"], `${path}.params.opacity`);
  if (itemSize !== null && Number(itemSize) > 4096 || Number(gutter) > 4096 || Number(margin) > 4096 || Number(opacity) > 1) {
    invalidEvidence(`${path}.params is out of range`);
  }
  return {
    id,
    version: 1,
    type,
    visible,
    snapEnabled,
    origin,
    params: {
      count: evidenceInteger(params["count"], 1, 24, `${path}.params.count`),
      itemSize,
      gutter,
      margin,
      alignment,
      colorTokenKey: evidenceTechnicalKey(params["colorTokenKey"], `${path}.params.colorTokenKey`),
      opacity
    }
  };
}
function parseCandidateCommon(record, path) {
  return {
    axis: evidenceLiteral(record["axis"], ["x", "y"], `${path}.axis`),
    position: evidenceSignedDecimal(record["position"], `${path}.position`),
    correction: evidenceSignedDecimal(record["correction"], `${path}.correction`),
    distance: evidenceNonNegativeDecimal(record["distance"], `${path}.distance`),
    sortKey: evidenceBoundedString(record["sortKey"], 512, `${path}.sortKey`),
    outcome: evidenceLiteral(
      record["outcome"],
      ["winner", "farther", "tiePriority", "crossAxisInvalid"],
      `${path}.outcome`
    )
  };
}
function parseEvidenceCandidate(value, path) {
  const record = evidenceRecord(value, path);
  const source = evidenceLiteral(
    record["source"],
    ["alignment", "spacing", "grid"],
    `${path}.source`
  );
  const commonKeys = ["source", "axis", "position", "correction", "distance", "sortKey", "outcome"];
  if (source === "alignment") {
    exactKeys(
      record,
      [...commonKeys, "coordinate", "movingAnchor", "targetAnchor", "targetKind", "targetNodeId"],
      path
    );
    const common2 = parseCandidateCommon(record, path);
    const targetKind = evidenceLiteral(
      record["targetKind"],
      ["container", "sibling"],
      `${path}.targetKind`
    );
    const targetNodeId = record["targetNodeId"] === null ? null : evidenceEntityId(record["targetNodeId"], `${path}.targetNodeId`);
    if (targetKind === "container" !== (targetNodeId === null)) {
      invalidEvidence(`${path}.targetNodeId does not match targetKind`);
    }
    return {
      source,
      ...common2,
      coordinate: evidenceSignedDecimal(record["coordinate"], `${path}.coordinate`),
      movingAnchor: evidenceLiteral(
        record["movingAnchor"],
        ["left", "center", "right", "top", "middle", "bottom"],
        `${path}.movingAnchor`
      ),
      targetAnchor: evidenceLiteral(
        record["targetAnchor"],
        ["left", "center", "right", "top", "middle", "bottom"],
        `${path}.targetAnchor`
      ),
      targetKind,
      targetNodeId
    };
  }
  if (source === "spacing") {
    exactKeys(record, [...commonKeys, "placement", "gap", "referenceNodeIds"], path);
    const common2 = parseCandidateCommon(record, path);
    const references = evidenceArray(record["referenceNodeIds"], 2, `${path}.referenceNodeIds`);
    if (references.length !== 2) invalidEvidence(`${path}.referenceNodeIds must contain two IDs`);
    const first = evidenceEntityId(references[0], `${path}.referenceNodeIds[0]`);
    const second = evidenceEntityId(references[1], `${path}.referenceNodeIds[1]`);
    if (first === second) invalidEvidence(`${path}.referenceNodeIds must be unique`);
    return {
      source,
      ...common2,
      placement: evidenceLiteral(
        record["placement"],
        ["before", "between", "after"],
        `${path}.placement`
      ),
      gap: evidencePositiveDecimal(record["gap"], `${path}.gap`),
      referenceNodeIds: [first, second]
    };
  }
  exactKeys(
    record,
    [...commonKeys, "gridId", "gridType", "gridLineIndex", "coordinate", "movingAnchor"],
    path
  );
  const common = parseCandidateCommon(record, path);
  return {
    source,
    ...common,
    gridId: evidenceEntityId(record["gridId"], `${path}.gridId`),
    gridType: evidenceLiteral(
      record["gridType"],
      ["square", "columns", "rows"],
      `${path}.gridType`
    ),
    gridLineIndex: evidenceInteger(
      record["gridLineIndex"],
      0,
      Number.MAX_SAFE_INTEGER,
      `${path}.gridLineIndex`
    ),
    coordinate: evidenceSignedDecimal(record["coordinate"], `${path}.coordinate`),
    movingAnchor: evidenceLiteral(
      record["movingAnchor"],
      ["left", "center", "right", "top", "middle", "bottom"],
      `${path}.movingAnchor`
    )
  };
}
function requireCanonicalSortedUnique(values, path) {
  const unique = new Set(values);
  if (unique.size !== values.length) invalidEvidence(`${path} must contain unique values`);
  for (let index = 1; index < values.length; index += 1) {
    const previous = values[index - 1];
    const current = values[index];
    if (previous === void 0 || current === void 0 || compareCanonicalIds(previous, current) >= 0) {
      invalidEvidence(`${path} must use canonical lexical order`);
    }
  }
}
function parseStructuredPrototypeFreeformMoveEvidence(value) {
  const record = evidenceRecord(value, "evidence");
  exactKeys(
    record,
    [
      "evidenceVersion",
      "kind",
      "snapSolverVersion",
      "snapSolverSourceHash",
      "documentId",
      "draftId",
      "freeformId",
      "baseHeadSequenceNo",
      "baseDocumentHash",
      "selectedNodeIds",
      "grids",
      "gridListHash",
      "gridSnappingEnabled",
      "previewScale",
      "clientThreshold",
      "selectionBounds",
      "directSiblings",
      "containerSize",
      "requestedDelta",
      "rawPosition",
      "finalPosition",
      "correction",
      "bypassSnapping",
      "axisWinners",
      "candidates",
      "terminalReason"
    ],
    "evidence"
  );
  if (record["evidenceVersion"] !== 2 || record["kind"] !== "freeformMove") {
    invalidEvidence("evidence contract is unsupported");
  }
  if (record["snapSolverVersion"] !== STRUCTURED_PROTOTYPE_SNAP_SOLVER_VERSION || record["snapSolverSourceHash"] !== STRUCTURED_PROTOTYPE_SNAP_SOURCE_HASH) {
    throw replayError("solver_identity_mismatch", "Freeform move evidence solver identity differs");
  }
  const selectedNodeIds = evidenceArray(
    record["selectedNodeIds"],
    500,
    "evidence.selectedNodeIds"
  ).map((item, index) => evidenceEntityId(item, `evidence.selectedNodeIds[${index}]`));
  if (selectedNodeIds.length === 0) invalidEvidence("evidence.selectedNodeIds must not be empty");
  requireCanonicalSortedUnique(selectedNodeIds, "evidence.selectedNodeIds");
  const grids = evidenceArray(record["grids"], 8, "evidence.grids").map(
    (grid, index) => parseEvidenceGrid(grid, `evidence.grids[${index}]`)
  );
  const gridIds = grids.map((grid) => grid.id);
  if (new Set(gridIds).size !== gridIds.length)
    invalidEvidence("evidence.grids contains duplicate IDs");
  const directSiblings = evidenceArray(
    record["directSiblings"],
    500,
    "evidence.directSiblings"
  ).map((sibling, index) => parseEvidenceSibling(sibling, `evidence.directSiblings[${index}]`));
  const siblingIds = directSiblings.map((sibling) => sibling.nodeId);
  requireCanonicalSortedUnique(siblingIds, "evidence.directSiblings");
  const selectedSet = new Set(selectedNodeIds);
  if (siblingIds.some((nodeId) => selectedSet.has(nodeId))) {
    invalidEvidence("evidence selected nodes cannot also be direct siblings");
  }
  const freeformId = evidenceEntityId(record["freeformId"], "evidence.freeformId");
  const capturedIds = /* @__PURE__ */ new Set([...selectedNodeIds, ...siblingIds, ...gridIds]);
  if (capturedIds.size !== selectedNodeIds.length + siblingIds.length + gridIds.length) {
    invalidEvidence("evidence node and grid IDs must be distinct");
  }
  if (capturedIds.has(freeformId)) invalidEvidence("evidence.freeformId must be distinct");
  const containerSize = evidenceRecord(record["containerSize"], "evidence.containerSize");
  exactKeys(containerSize, ["width", "height"], "evidence.containerSize");
  const axisWinners = evidenceRecord(record["axisWinners"], "evidence.axisWinners");
  exactKeys(axisWinners, ["x", "y"], "evidence.axisWinners");
  const candidates = evidenceArray(record["candidates"], 6, "evidence.candidates").map(
    (candidate, index) => parseEvidenceCandidate(candidate, `evidence.candidates[${index}]`)
  );
  const sortKeys = candidates.map((candidate) => candidate.sortKey);
  if (new Set(sortKeys).size !== sortKeys.length) {
    invalidEvidence("evidence.candidates contains duplicate sort keys");
  }
  return {
    evidenceVersion: 2,
    kind: "freeformMove",
    snapSolverVersion: STRUCTURED_PROTOTYPE_SNAP_SOLVER_VERSION,
    snapSolverSourceHash: STRUCTURED_PROTOTYPE_SNAP_SOURCE_HASH,
    documentId: evidenceEntityId(record["documentId"], "evidence.documentId"),
    draftId: evidenceEntityId(record["draftId"], "evidence.draftId"),
    freeformId,
    baseHeadSequenceNo: evidenceInteger(
      record["baseHeadSequenceNo"],
      0,
      Number.MAX_SAFE_INTEGER,
      "evidence.baseHeadSequenceNo"
    ),
    baseDocumentHash: evidenceSha256(record["baseDocumentHash"], "evidence.baseDocumentHash"),
    selectedNodeIds,
    grids,
    gridListHash: evidenceSha256(record["gridListHash"], "evidence.gridListHash"),
    gridSnappingEnabled: evidenceBoolean(
      record["gridSnappingEnabled"],
      "evidence.gridSnappingEnabled"
    ),
    previewScale: evidencePositiveDecimal(record["previewScale"], "evidence.previewScale"),
    clientThreshold: evidenceLiteral(
      record["clientThreshold"],
      ["6"],
      "evidence.clientThreshold"
    ),
    selectionBounds: parseEvidenceBounds(record["selectionBounds"], "evidence.selectionBounds"),
    directSiblings,
    containerSize: {
      width: evidencePositiveDecimal(containerSize["width"], "evidence.containerSize.width"),
      height: evidencePositiveDecimal(containerSize["height"], "evidence.containerSize.height")
    },
    requestedDelta: parseEvidencePoint(record["requestedDelta"], "evidence.requestedDelta"),
    rawPosition: parseEvidencePoint(record["rawPosition"], "evidence.rawPosition"),
    finalPosition: parseEvidencePoint(record["finalPosition"], "evidence.finalPosition"),
    correction: parseEvidencePoint(record["correction"], "evidence.correction"),
    bypassSnapping: evidenceBoolean(record["bypassSnapping"], "evidence.bypassSnapping"),
    axisWinners: {
      x: evidenceLiteral(
        axisWinners["x"],
        ["raw", "alignment", "spacing", "grid"],
        "evidence.axisWinners.x"
      ),
      y: evidenceLiteral(
        axisWinners["y"],
        ["raw", "alignment", "spacing", "grid"],
        "evidence.axisWinners.y"
      )
    },
    candidates,
    terminalReason: evidenceLiteral(
      record["terminalReason"],
      ["pointerup"],
      "evidence.terminalReason"
    )
  };
}
function evidenceNumber(value) {
  return Number(value);
}
function evidencePointToSnapPoint(point) {
  return { x: evidenceNumber(point.x), y: evidenceNumber(point.y) };
}
function evidenceBoundsToSnapBounds(bounds) {
  return {
    ...evidencePointToSnapPoint(bounds),
    width: evidenceNumber(bounds.width),
    height: evidenceNumber(bounds.height)
  };
}
function evidenceToBuildInput(evidence) {
  return {
    documentId: evidence.documentId,
    draftId: evidence.draftId,
    baseHeadSequenceNo: evidence.baseHeadSequenceNo,
    baseDocumentHash: evidence.baseDocumentHash,
    freeformId: evidence.freeformId,
    selectedNodeIds: evidence.selectedNodeIds,
    grids: evidence.grids,
    gridSnappingEnabled: evidence.gridSnappingEnabled,
    previewScale: evidenceNumber(evidence.previewScale),
    selectionBounds: evidenceBoundsToSnapBounds(evidence.selectionBounds),
    directSiblings: evidence.directSiblings.map((sibling) => ({
      nodeId: sibling.nodeId,
      ...evidenceBoundsToSnapBounds(sibling)
    })),
    containerWidth: evidenceNumber(evidence.containerSize.width),
    containerHeight: evidenceNumber(evidence.containerSize.height),
    requestedDelta: evidencePointToSnapPoint(evidence.requestedDelta),
    bypassSnapping: evidence.bypassSnapping
  };
}
async function attestStructuredPrototypeFreeformMoveEvidenceJson(evidenceJson) {
  const value = safeJsonParse(evidenceJson);
  if (value === null) {
    throw replayError("invalid_evidence_json", "Freeform move evidence JSON is invalid");
  }
  const evidence = parseStructuredPrototypeFreeformMoveEvidence(value);
  const canonicalEvidenceJson = canonicalRuntimeJson(evidence);
  if (evidenceJson !== canonicalEvidenceJson) {
    throw replayError("evidence_mismatch", "Freeform move evidence JSON is not canonical");
  }
  let rebuilt;
  try {
    rebuilt = await buildStructuredPrototypeFreeformMoveEvidence(evidenceToBuildInput(evidence));
  } catch (error) {
    if (error instanceof StructuredPrototypeFreeformMoveReplayError) {
      throw replayError(
        "invalid_evidence",
        `Freeform move evidence cannot replay: ${error.message}`
      );
    }
    throw replayError(
      "invalid_evidence",
      `Freeform move evidence cannot replay: ${errorMessage(error)}`
    );
  }
  if (canonicalRuntimeJson(rebuilt) !== canonicalEvidenceJson) {
    throw replayError("evidence_mismatch", "Freeform move evidence differs from canonical replay");
  }
  return { evidenceHash: await hashRuntimeValue(evidence) };
}

// src/features/prototype/structured/structuredPrototypeSnapWorkerProtocol.ts
var SNAP_WORKER_PROTOCOL_VERSION = "prototype-snap-worker/v1";
var SNAP_WORKER_ATTEST_MANY_LIMIT = 200;
var SNAP_WORKER_MAX_REQUEST_BYTES = 32 * 1024 * 1024;
var SnapWorkerProtocolError = class extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
    this.name = "SnapWorkerProtocolError";
  }
  code;
};
function identity() {
  return {
    protocolVersion: SNAP_WORKER_PROTOCOL_VERSION,
    snapSolverVersion: STRUCTURED_PROTOTYPE_SNAP_SOLVER_VERSION,
    snapSolverSourceHash: STRUCTURED_PROTOTYPE_SNAP_SOURCE_HASH
  };
}
function requireExactKeys(record, expectedKeys, path) {
  const expected = new Set(expectedKeys);
  for (const key of Object.keys(record)) {
    if (!expected.has(key)) {
      throw new SnapWorkerProtocolError(
        "snap_worker_request_invalid",
        `${path} contains an unknown field`
      );
    }
  }
  for (const key of expectedKeys) {
    if (!Object.hasOwn(record, key)) {
      throw new SnapWorkerProtocolError(
        "snap_worker_request_invalid",
        `${path} is missing field ${key}`
      );
    }
  }
}
function requireNonEmptyString(value, path) {
  if (typeof value !== "string" || value.length === 0 || !value.isWellFormed()) {
    throw new SnapWorkerProtocolError(
      "snap_worker_request_invalid",
      `${path} must be a non-empty well-formed string`
    );
  }
  return value;
}
function requireRequestId(value) {
  const requestId = requireNonEmptyString(value, "request.requestId");
  if (requestId.length > 128) {
    throw new SnapWorkerProtocolError(
      "snap_worker_request_invalid",
      "request.requestId exceeds 128 characters"
    );
  }
  return requestId;
}
function requireAction(value) {
  if (value === "describe" || value === "attest" || value === "attestMany") {
    return value;
  }
  throw new SnapWorkerProtocolError(
    "snap_worker_action_unsupported",
    "snap worker action is unsupported"
  );
}
function isSnapWorkerAction(value) {
  return value === "describe" || value === "attest" || value === "attestMany";
}
function requireRequestRecord(value) {
  if (!isRecord(value)) {
    throw new SnapWorkerProtocolError(
      "snap_worker_request_invalid",
      "snap worker request must be an object"
    );
  }
  return value;
}
function requireEvidenceJson(value, path) {
  return requireNonEmptyString(value, path);
}
function parseSnapWorkerRequest(value) {
  const record = requireRequestRecord(value);
  if (record["protocolVersion"] !== SNAP_WORKER_PROTOCOL_VERSION) {
    throw new SnapWorkerProtocolError(
      "snap_worker_protocol_mismatch",
      `snap worker protocol must equal ${SNAP_WORKER_PROTOCOL_VERSION}`
    );
  }
  const requestId = requireRequestId(record["requestId"]);
  const action = requireAction(record["action"]);
  if (action === "describe") {
    requireExactKeys(record, ["protocolVersion", "requestId", "action"], "request");
    return { protocolVersion: SNAP_WORKER_PROTOCOL_VERSION, requestId, action };
  }
  if (action === "attest") {
    requireExactKeys(record, ["protocolVersion", "requestId", "action", "evidenceJson"], "request");
    return {
      protocolVersion: SNAP_WORKER_PROTOCOL_VERSION,
      requestId,
      action,
      evidenceJson: requireEvidenceJson(record["evidenceJson"], "request.evidenceJson")
    };
  }
  requireExactKeys(record, ["protocolVersion", "requestId", "action", "evidenceJsons"], "request");
  const evidenceJsons = record["evidenceJsons"];
  if (!Array.isArray(evidenceJsons)) {
    throw new SnapWorkerProtocolError(
      "snap_worker_request_invalid",
      "request.evidenceJsons must be an array"
    );
  }
  if (evidenceJsons.length === 0 || evidenceJsons.length > SNAP_WORKER_ATTEST_MANY_LIMIT) {
    throw new SnapWorkerProtocolError(
      "snap_worker_request_invalid",
      `request.evidenceJsons must contain between 1 and ${SNAP_WORKER_ATTEST_MANY_LIMIT} items`
    );
  }
  return {
    protocolVersion: SNAP_WORKER_PROTOCOL_VERSION,
    requestId,
    action,
    evidenceJsons: Array.from(
      evidenceJsons,
      (evidenceJson, index) => requireEvidenceJson(evidenceJson, `request.evidenceJsons[${index}]`)
    )
  };
}
function parseSnapWorkerRequestJson(input) {
  const parsed = safeJsonParse(input);
  if (parsed === null) {
    throw new SnapWorkerProtocolError(
      "snap_worker_request_invalid_json",
      "snap worker request JSON is invalid"
    );
  }
  return parseSnapWorkerRequest(parsed);
}
function readSnapWorkerRequestIdentityJson(input) {
  const parsed = safeJsonParse(input);
  if (!isRecord(parsed)) return { requestId: "unknown", action: "unknown" };
  const rawRequestId = parsed["requestId"];
  const requestId = typeof rawRequestId === "string" && rawRequestId.length > 0 && rawRequestId.length <= 128 && rawRequestId.isWellFormed() ? rawRequestId : "unknown";
  return {
    requestId,
    action: isSnapWorkerAction(parsed["action"]) ? parsed["action"] : "unknown"
  };
}
function replayErrorCode(error) {
  if (error.code === "invalid_replay_input" || error.code === "invalid_evidence_json" || error.code === "invalid_evidence") {
    return "snap_evidence_invalid";
  }
  return "snap_attestation_mismatch";
}
async function attestEvidenceJson(evidenceJson) {
  try {
    return await attestStructuredPrototypeFreeformMoveEvidenceJson(evidenceJson);
  } catch (error) {
    if (error instanceof StructuredPrototypeFreeformMoveReplayError) {
      throw new SnapWorkerProtocolError(replayErrorCode(error), error.message);
    }
    throw error;
  }
}
async function executeSnapWorkerRequest(request) {
  switch (request.action) {
    case "describe":
      return {
        ...identity(),
        requestId: request.requestId,
        action: request.action,
        status: "ok",
        result: identity()
      };
    case "attest":
      return {
        ...identity(),
        requestId: request.requestId,
        action: request.action,
        status: "ok",
        result: await attestEvidenceJson(request.evidenceJson)
      };
    case "attestMany": {
      const evidenceHashes = [];
      for (const evidenceJson of request.evidenceJsons) {
        const attestation = await attestEvidenceJson(evidenceJson);
        evidenceHashes.push(attestation.evidenceHash);
      }
      return {
        ...identity(),
        requestId: request.requestId,
        action: request.action,
        status: "ok",
        result: { evidenceHashes }
      };
    }
  }
}
function snapWorkerResponseJson(response) {
  return canonicalRuntimeJson(response);
}
function snapWorkerErrorResponse(requestId, action, code, message) {
  const boundedMessage = Array.from(message.toWellFormed()).slice(0, 1024).join("");
  return {
    ...identity(),
    requestId,
    action,
    status: "error",
    error: { code, message: boundedMessage }
  };
}

// scripts/prototype-snap-worker.ts
var MAX_RESPONSE_BYTES = 64 * 1024;
function classifyFailure(error) {
  if (error instanceof SnapWorkerProtocolError) {
    return { code: error.code, message: error.message, internal: false };
  }
  return {
    code: "snap_worker_internal_error",
    message: "snap worker failed unexpectedly",
    internal: true
  };
}
function writeBoundedResponse(response) {
  let responseJson = snapWorkerResponseJson(response);
  const withinLimit = Buffer.byteLength(responseJson, "utf8") <= MAX_RESPONSE_BYTES;
  if (!withinLimit) {
    responseJson = snapWorkerResponseJson(
      snapWorkerErrorResponse(
        "unknown",
        "unknown",
        "snap_worker_response_too_large",
        "snap worker response exceeds 64 KiB"
      )
    );
  }
  process.stdout.write(`${responseJson}
`);
  return withinLimit;
}
async function main() {
  let requestId = "unknown";
  let action = "unknown";
  let response;
  let internalDetails = null;
  try {
    process.stdin.setEncoding("utf8");
    let input = "";
    let inputBytes = 0;
    for await (const chunk of process.stdin) {
      if (typeof chunk !== "string") {
        throw new TypeError("snap worker stdin did not decode as UTF-8 text");
      }
      inputBytes += Buffer.byteLength(chunk, "utf8");
      if (inputBytes > SNAP_WORKER_MAX_REQUEST_BYTES) {
        throw new SnapWorkerProtocolError(
          "snap_worker_request_too_large",
          `snap worker request exceeds ${SNAP_WORKER_MAX_REQUEST_BYTES / (1024 * 1024)} MiB`
        );
      }
      input += chunk;
    }
    const requestIdentity = readSnapWorkerRequestIdentityJson(input);
    requestId = requestIdentity.requestId;
    action = requestIdentity.action;
    const request = parseSnapWorkerRequestJson(input);
    response = await executeSnapWorkerRequest(request);
  } catch (error) {
    const failure = classifyFailure(error);
    response = snapWorkerErrorResponse(requestId, action, failure.code, failure.message);
    if (failure.internal) {
      internalDetails = error instanceof Error ? error.stack ?? error.message : String(error);
    }
  }
  if (!writeBoundedResponse(response)) {
    process.exitCode = 1;
  }
  if (internalDetails !== null) {
    process.stderr.write(`${internalDetails}
`);
    process.exitCode = 1;
  }
}
await main();
