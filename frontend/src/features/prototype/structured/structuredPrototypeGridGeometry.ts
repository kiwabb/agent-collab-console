import type { StructuredPrototypeAxisGrid, StructuredPrototypeFreeformGrid } from "./types";

const CANONICAL_DECIMAL_PATTERN = /^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,4})?$/u;
const GRID_VALUE_EPSILON = 1e-9;
const MAX_TRACK_COUNT = 24;

export type StructuredPrototypeFreeformGridAxis = "x" | "y";

export interface StructuredPrototypeFreeformGridFrame {
  readonly width: number;
  readonly height: number;
}

export interface StructuredPrototypeFreeformGridRect {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

export interface StructuredPrototypeFreeformSquareGridGeometry {
  readonly gridId: string;
  readonly type: "square";
  readonly origin: { readonly x: number; readonly y: number };
  readonly size: number;
  readonly clip: StructuredPrototypeFreeformGridRect;
}

export interface StructuredPrototypeFreeformTrackArea extends StructuredPrototypeFreeformGridRect {
  readonly index: number;
}

export interface StructuredPrototypeFreeformTrackGridGeometry {
  readonly gridId: string;
  readonly type: "columns" | "rows";
  readonly clip: StructuredPrototypeFreeformGridRect;
  readonly areas: readonly StructuredPrototypeFreeformTrackArea[];
}

export type StructuredPrototypeFreeformGridGeometry =
  StructuredPrototypeFreeformSquareGridGeometry | StructuredPrototypeFreeformTrackGridGeometry;

export interface StructuredPrototypeFreeformGridSnapLine {
  readonly gridId: string;
  readonly gridType: StructuredPrototypeFreeformGrid["type"];
  readonly axis: StructuredPrototypeFreeformGridAxis;
  readonly coordinate: number;
  readonly correction: number;
  readonly distance: number;
  readonly lineIndex: number;
}

interface GridInput {
  readonly frame: Readonly<StructuredPrototypeFreeformGridFrame>;
  readonly grid: Readonly<StructuredPrototypeFreeformGrid>;
}

interface GridsInput {
  readonly frame: Readonly<StructuredPrototypeFreeformGridFrame>;
  readonly grids: readonly Readonly<StructuredPrototypeFreeformGrid>[];
}

interface NearestGridSnapLineInput extends GridsInput {
  readonly axis: StructuredPrototypeFreeformGridAxis;
  readonly coordinate: number;
}

interface ParsedGridCommon {
  readonly id: string;
  readonly visible: boolean;
  readonly snapEnabled: boolean;
  readonly originX: number;
  readonly originY: number;
}

interface SquareGridCalculation extends ParsedGridCommon {
  readonly type: "square";
  readonly size: number;
}

interface TrackGridCalculation extends ParsedGridCommon {
  readonly type: "columns" | "rows";
  readonly areas: readonly StructuredPrototypeFreeformTrackArea[];
}

type GridCalculation = SquareGridCalculation | TrackGridCalculation;

function valueTolerance(...values: readonly number[]): number {
  return GRID_VALUE_EPSILON * Math.max(1, ...values.map((value) => Math.abs(value)));
}

function compareText(left: string, right: string): number {
  if (left === right) return 0;
  return left < right ? -1 : 1;
}

function assertFinite(value: number, label: string): void {
  if (!Number.isFinite(value)) throw new Error(`freeform grid ${label} must be finite`);
}

function assertPositive(value: number, label: string): void {
  assertFinite(value, label);
  if (value <= 0) throw new Error(`freeform grid ${label} must be positive`);
}

function parseDecimal(value: string, label: string, positive = false): number {
  if (!CANONICAL_DECIMAL_PATTERN.test(value)) {
    throw new Error(`freeform grid ${label} must be a canonical decimal`);
  }
  const parsed = Number(value);
  assertFinite(parsed, label);
  if (positive && parsed <= 0) throw new Error(`freeform grid ${label} must be positive`);
  return parsed;
}

function assertFrame(
  frame: Readonly<StructuredPrototypeFreeformGridFrame>,
): StructuredPrototypeFreeformGridFrame {
  assertPositive(frame.width, "frame width");
  assertPositive(frame.height, "frame height");
  return { width: frame.width, height: frame.height };
}

function assertAxis(axis: StructuredPrototypeFreeformGridAxis): void {
  if (axis !== "x" && axis !== "y") throw new Error("freeform grid snap axis is invalid");
}

function assertPresentation(grid: Readonly<StructuredPrototypeFreeformGrid>): void {
  if (grid.params.colorTokenKey.length === 0) {
    throw new Error("freeform grid color token key must not be empty");
  }
  const opacity = parseDecimal(grid.params.opacity, "opacity");
  if (opacity > 1) {
    throw new Error("freeform grid opacity must be between zero and one");
  }
}

function parseCommon(
  grid: Readonly<StructuredPrototypeFreeformGrid>,
  frame: Readonly<StructuredPrototypeFreeformGridFrame>,
): ParsedGridCommon {
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
    originY,
  };
}

function clipRect(
  x: number,
  y: number,
  width: number,
  height: number,
  frame: Readonly<StructuredPrototypeFreeformGridFrame>,
  label: string,
): StructuredPrototypeFreeformGridRect {
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

function alignmentOffset(
  alignment: StructuredPrototypeAxisGrid["params"]["alignment"],
  freeSpace: number,
): number {
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

function calculateTrackAreas(
  grid: Readonly<StructuredPrototypeAxisGrid>,
  common: Readonly<ParsedGridCommon>,
  frame: Readonly<StructuredPrototypeFreeformGridFrame>,
): readonly StructuredPrototypeFreeformTrackArea[] {
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

  let itemSize: number;
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
    const axisPosition = first + index * (itemSize + gutter);
    const raw =
      grid.type === "columns"
        ? { x: axisPosition, y: crossOrigin, width: itemSize, height: crossLength }
        : { x: crossOrigin, y: axisPosition, width: crossLength, height: itemSize };
    const clipped = clipRect(raw.x, raw.y, raw.width, raw.height, frame, `track ${index}`);
    return { index, ...clipped };
  });
}

function calculateGrid(
  grid: Readonly<StructuredPrototypeFreeformGrid>,
  frame: Readonly<StructuredPrototypeFreeformGridFrame>,
): GridCalculation {
  const common = parseCommon(grid, frame);
  if (grid.type === "square") {
    const size = parseDecimal(grid.params.size, "square size", true);
    const remainingWidth = frame.width - common.originX;
    const remainingHeight = frame.height - common.originY;
    if (
      size - remainingWidth > valueTolerance(size, remainingWidth) ||
      size - remainingHeight > valueTolerance(size, remainingHeight)
    ) {
      throw new Error("freeform square grid does not fit inside its frame");
    }
    return { ...common, type: "square", size };
  }
  if (grid.type === "columns" || grid.type === "rows") {
    return {
      ...common,
      type: grid.type,
      areas: calculateTrackAreas(grid, common, frame),
    };
  }
  throw new Error("freeform grid type is unsupported");
}

function assertUniqueGridIds(grids: readonly Readonly<StructuredPrototypeFreeformGrid>[]): void {
  const ids = new Set<string>();
  for (const grid of grids) {
    if (ids.has(grid.id)) throw new Error(`freeform grid id is duplicated: ${grid.id}`);
    ids.add(grid.id);
  }
}

function calculateGrids(
  grids: readonly Readonly<StructuredPrototypeFreeformGrid>[],
  frame: Readonly<StructuredPrototypeFreeformGridFrame>,
): readonly GridCalculation[] {
  assertUniqueGridIds(grids);
  return grids.map((grid) => calculateGrid(grid, frame));
}

function calculateSortedSnapGrids(
  grids: readonly Readonly<StructuredPrototypeFreeformGrid>[],
  frame: Readonly<StructuredPrototypeFreeformGridFrame>,
): readonly GridCalculation[] {
  return [...calculateGrids(grids, frame)].sort((left, right) => compareText(left.id, right.id));
}

function geometryFromCalculation(
  calculation: Readonly<GridCalculation>,
  frame: Readonly<StructuredPrototypeFreeformGridFrame>,
): StructuredPrototypeFreeformGridGeometry | null {
  if (!calculation.visible) return null;
  if (calculation.type === "square") {
    return {
      gridId: calculation.id,
      type: "square",
      origin: { x: calculation.originX, y: calculation.originY },
      size: calculation.size,
      clip: clipRect(
        calculation.originX,
        calculation.originY,
        frame.width - calculation.originX,
        frame.height - calculation.originY,
        frame,
        "square pattern",
      ),
    };
  }
  return {
    gridId: calculation.id,
    type: calculation.type,
    clip: clipRect(
      calculation.originX,
      calculation.originY,
      frame.width - calculation.originX,
      frame.height - calculation.originY,
      frame,
      `${calculation.type} pattern`,
    ),
    areas: calculation.areas,
  };
}

export function resolveStructuredPrototypeFreeformGridGeometry({
  frame: inputFrame,
  grid,
}: GridInput): StructuredPrototypeFreeformGridGeometry | null {
  const frame = assertFrame(inputFrame);
  return geometryFromCalculation(calculateGrid(grid, frame), frame);
}

export function resolveStructuredPrototypeFreeformGridGeometries({
  frame: inputFrame,
  grids,
}: GridsInput): readonly StructuredPrototypeFreeformGridGeometry[] {
  const frame = assertFrame(inputFrame);
  const geometries: StructuredPrototypeFreeformGridGeometry[] = [];
  for (const calculation of calculateGrids(grids, frame)) {
    const geometry = geometryFromCalculation(calculation, frame);
    if (geometry !== null) geometries.push(geometry);
  }
  return geometries;
}

function candidateFromCoordinate({
  calculation,
  axis,
  coordinate,
  requestedCoordinate,
  lineIndex,
}: {
  readonly calculation: Readonly<GridCalculation>;
  readonly axis: StructuredPrototypeFreeformGridAxis;
  readonly coordinate: number;
  readonly requestedCoordinate: number;
  readonly lineIndex: number;
}): StructuredPrototypeFreeformGridSnapLine {
  assertFinite(coordinate, "snap line coordinate");
  const correction = coordinate - requestedCoordinate;
  return {
    gridId: calculation.id,
    gridType: calculation.type,
    axis,
    coordinate,
    correction,
    distance: Math.abs(correction),
    lineIndex,
  };
}

function compareSnapLines(
  left: Readonly<StructuredPrototypeFreeformGridSnapLine>,
  right: Readonly<StructuredPrototypeFreeformGridSnapLine>,
): number {
  const distanceDifference = left.distance - right.distance;
  if (Math.abs(distanceDifference) > valueTolerance(left.distance, right.distance)) {
    return distanceDifference < 0 ? -1 : 1;
  }
  const idOrder = compareText(left.gridId, right.gridId);
  if (idOrder !== 0) return idOrder;
  if (left.coordinate !== right.coordinate) return left.coordinate < right.coordinate ? -1 : 1;
  return left.lineIndex - right.lineIndex;
}

function chooseSnapLine(
  current: StructuredPrototypeFreeformGridSnapLine | null,
  candidate: StructuredPrototypeFreeformGridSnapLine,
): StructuredPrototypeFreeformGridSnapLine {
  return current === null || compareSnapLines(candidate, current) < 0 ? candidate : current;
}

function maximumSquareLineIndex(span: number, size: number): number {
  const tolerance = valueTolerance(span, size);
  return Math.max(0, Math.floor((span - tolerance) / size));
}

function nearestSquareLine(
  calculation: Readonly<SquareGridCalculation>,
  frame: Readonly<StructuredPrototypeFreeformGridFrame>,
  axis: StructuredPrototypeFreeformGridAxis,
  requestedCoordinate: number,
): StructuredPrototypeFreeformGridSnapLine | null {
  const origin = axis === "x" ? calculation.originX : calculation.originY;
  const limit = axis === "x" ? frame.width : frame.height;
  const maximumIndex = maximumSquareLineIndex(limit - origin, calculation.size);
  if (maximumIndex < 0) return null;

  const approximateIndex = Math.round((requestedCoordinate - origin) / calculation.size);
  const indices = new Set<number>([
    0,
    maximumIndex,
    Math.max(0, Math.min(maximumIndex, approximateIndex - 1)),
    Math.max(0, Math.min(maximumIndex, approximateIndex)),
    Math.max(0, Math.min(maximumIndex, approximateIndex + 1)),
  ]);
  let nearest: StructuredPrototypeFreeformGridSnapLine | null = null;
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
        lineIndex,
      }),
    );
  }
  return nearest;
}

function nearestTrackLine(
  calculation: Readonly<TrackGridCalculation>,
  axis: StructuredPrototypeFreeformGridAxis,
  requestedCoordinate: number,
): StructuredPrototypeFreeformGridSnapLine | null {
  if (
    (calculation.type === "columns" && axis !== "x") ||
    (calculation.type === "rows" && axis !== "y")
  ) {
    return null;
  }
  let nearest: StructuredPrototypeFreeformGridSnapLine | null = null;
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
        lineIndex: area.index * 2,
      }),
    );
    nearest = chooseSnapLine(
      nearest,
      candidateFromCoordinate({
        calculation,
        axis,
        coordinate: end,
        requestedCoordinate,
        lineIndex: area.index * 2 + 1,
      }),
    );
  }
  return nearest;
}

export function resolveStructuredPrototypeNearestFreeformGridSnapLine({
  frame: inputFrame,
  grids,
  axis,
  coordinate,
}: NearestGridSnapLineInput): StructuredPrototypeFreeformGridSnapLine | null {
  const frame = assertFrame(inputFrame);
  assertAxis(axis);
  assertFinite(coordinate, "requested snap coordinate");
  let nearest: StructuredPrototypeFreeformGridSnapLine | null = null;
  for (const calculation of calculateSortedSnapGrids(grids, frame)) {
    if (!calculation.snapEnabled) continue;
    const candidate =
      calculation.type === "square"
        ? nearestSquareLine(calculation, frame, axis, coordinate)
        : nearestTrackLine(calculation, axis, coordinate);
    if (candidate !== null) nearest = chooseSnapLine(nearest, candidate);
  }
  return nearest;
}
