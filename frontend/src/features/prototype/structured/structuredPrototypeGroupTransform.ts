import {
  STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE,
  STRUCTURED_PROTOTYPE_MIN_RESIZE_HEIGHT,
  STRUCTURED_PROTOTYPE_MIN_RESIZE_WIDTH,
  normalizeStructuredPrototypeFreeformValue,
  resolveStructuredPrototypeResizeHandleAxes,
  resolveStructuredPrototypeResizeBounds,
  type StructuredPrototypeResizeDirection,
  type StructuredPrototypeResizeSize,
} from "./structuredPrototypeFreeformGeometry";
import { resolveStructuredPrototypeClientDeltaToCanvas } from "./structuredPrototypeViewportTransform";

export const STRUCTURED_PROTOTYPE_GROUP_TRANSFORM_MIN_ITEMS = 2;
export const STRUCTURED_PROTOTYPE_GROUP_TRANSFORM_MAX_ITEMS = 100;

const MINIMUM_GROUP_DIMENSION = Number.EPSILON;

export interface StructuredPrototypeGroupTransformItem {
  nodeId: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface StructuredPrototypeGroupTransformBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface StructuredPrototypeGroupMoveInput {
  items: readonly StructuredPrototypeGroupTransformItem[];
  startClientX: number;
  startClientY: number;
  clientX: number;
  clientY: number;
  previewScale: number;
  containerWidth: number;
  containerHeight: number;
}

export interface StructuredPrototypeGroupResizeInput extends StructuredPrototypeGroupMoveInput {
  direction: StructuredPrototypeResizeDirection;
  lockAspectRatio: boolean;
  resizeFromCenter: boolean;
}

export interface StructuredPrototypeGroupResizeSizeLimitsInput {
  items: readonly StructuredPrototypeGroupTransformItem[];
  direction: StructuredPrototypeResizeDirection;
  lockAspectRatio: boolean;
  resizeFromCenter: boolean;
}

export interface StructuredPrototypeGroupResizeSizeLimits {
  minimumSize: StructuredPrototypeResizeSize;
  maximumSize: StructuredPrototypeResizeSize;
}

export type StructuredPrototypeGroupAlignment =
  "left" | "center" | "right" | "top" | "middle" | "bottom";

export type StructuredPrototypeGroupDistributionAxis = "horizontal" | "vertical";

function assertFinite(value: number, label: string): void {
  if (!Number.isFinite(value)) throw new Error(`group transform ${label} must be finite`);
}

function assertPositive(value: number, label: string): void {
  assertFinite(value, label);
  if (value <= 0) throw new Error(`group transform ${label} must be positive`);
}

function assertTransformItemCount(
  items: readonly StructuredPrototypeGroupTransformItem[],
  minimumItems: number,
  label: string,
): void {
  if (
    items.length < minimumItems ||
    items.length > STRUCTURED_PROTOTYPE_GROUP_TRANSFORM_MAX_ITEMS
  ) {
    throw new Error(
      `${label} requires ${minimumItems} to ${STRUCTURED_PROTOTYPE_GROUP_TRANSFORM_MAX_ITEMS} items`,
    );
  }
}

function assertTransformItems(
  items: readonly StructuredPrototypeGroupTransformItem[],
  minimumItems: number,
  label: string,
): void {
  assertTransformItemCount(items, minimumItems, label);
  const nodeIds = new Set<string>();
  for (const item of items) {
    if (item.nodeId.length === 0) throw new Error("group transform item nodeId must not be empty");
    if (nodeIds.has(item.nodeId)) {
      throw new Error(`group transform item nodeId is duplicated: ${item.nodeId}`);
    }
    nodeIds.add(item.nodeId);
    assertFinite(item.x, `item ${item.nodeId} x`);
    assertFinite(item.y, `item ${item.nodeId} y`);
    assertPositive(item.width, `item ${item.nodeId} width`);
    assertPositive(item.height, `item ${item.nodeId} height`);
    if (item.x < 0 || item.y < 0) {
      throw new Error(`group transform item ${item.nodeId} is outside its container`);
    }
    assertFinite(item.x + item.width, `item ${item.nodeId} right`);
    assertFinite(item.y + item.height, `item ${item.nodeId} bottom`);
  }
}

function resolveTransformBounds(
  items: readonly StructuredPrototypeGroupTransformItem[],
  minimumItems: number,
  label: string,
): StructuredPrototypeGroupTransformBounds {
  assertTransformItems(items, minimumItems, label);
  const first = items[0];
  if (first === undefined) throw new Error(`${label} has no first item`);
  let minX = first.x;
  let minY = first.y;
  let maxX = first.x + first.width;
  let maxY = first.y + first.height;
  for (const item of items.slice(1)) {
    minX = Math.min(minX, item.x);
    minY = Math.min(minY, item.y);
    maxX = Math.max(maxX, item.x + item.width);
    maxY = Math.max(maxY, item.y + item.height);
  }
  const width = maxX - minX;
  const height = maxY - minY;
  assertPositive(width, `${label} width`);
  assertPositive(height, `${label} height`);
  if (width < MINIMUM_GROUP_DIMENSION || height < MINIMUM_GROUP_DIMENSION) {
    throw new Error(`${label} bounds are degenerate`);
  }
  return { x: minX, y: minY, width, height };
}

function assertContainer(containerWidth: number, containerHeight: number): void {
  assertPositive(containerWidth, "container width");
  assertPositive(containerHeight, "container height");
}

function assertItemsWithinContainer(
  items: readonly StructuredPrototypeGroupTransformItem[],
  containerWidth: number,
  containerHeight: number,
): void {
  for (const item of items) {
    if (item.x + item.width > containerWidth || item.y + item.height > containerHeight) {
      throw new Error(`group transform item ${item.nodeId} is outside its container`);
    }
  }
}

function clamp(value: number, minimum: number, maximum: number): number {
  assertFinite(value, "clamped value");
  assertFinite(minimum, "clamp minimum");
  assertFinite(maximum, "clamp maximum");
  if (maximum < minimum) throw new Error("group transform clamp range is invalid");
  return Math.min(Math.max(value, minimum), maximum);
}

function validateGroupInContainer(
  items: readonly StructuredPrototypeGroupTransformItem[],
  containerWidth: number,
  containerHeight: number,
): StructuredPrototypeGroupTransformBounds {
  const bounds = resolveStructuredPrototypeGroupTransformBounds(items);
  assertContainer(containerWidth, containerHeight);
  assertItemsWithinContainer(items, containerWidth, containerHeight);
  if (bounds.width > containerWidth || bounds.height > containerHeight) {
    throw new Error("group transform bounds are outside their container");
  }
  return bounds;
}

function assertClientInput(
  startClientX: number,
  startClientY: number,
  clientX: number,
  clientY: number,
  previewScale: number,
): void {
  assertFinite(startClientX, "start client x");
  assertFinite(startClientY, "start client y");
  assertFinite(clientX, "client x");
  assertFinite(clientY, "client y");
  assertPositive(previewScale, "preview scale");
}

function resolveClientDelta(
  startClientX: number,
  startClientY: number,
  clientX: number,
  clientY: number,
  previewScale: number,
): { x: number; y: number } {
  assertClientInput(startClientX, startClientY, clientX, clientY, previewScale);
  const delta = resolveStructuredPrototypeClientDeltaToCanvas(
    { x: clientX - startClientX, y: clientY - startClientY },
    previewScale,
  );
  assertFinite(delta.x, "canvas delta x");
  assertFinite(delta.y, "canvas delta y");
  return delta;
}

function projectItemsToBounds(
  items: readonly StructuredPrototypeGroupTransformItem[],
  minimumItems: number,
  label: string,
  nextBounds: StructuredPrototypeGroupTransformBounds,
): StructuredPrototypeGroupTransformItem[] {
  const bounds = resolveTransformBounds(items, minimumItems, label);
  assertFinite(nextBounds.x, "projected bounds x");
  assertFinite(nextBounds.y, "projected bounds y");
  assertPositive(nextBounds.width, "projected bounds width");
  assertPositive(nextBounds.height, "projected bounds height");
  if (nextBounds.x < 0 || nextBounds.y < 0) {
    throw new Error("group transform projected bounds are outside their container");
  }
  const scaleX = nextBounds.width / bounds.width;
  const scaleY = nextBounds.height / bounds.height;
  assertPositive(scaleX, "horizontal scale");
  assertPositive(scaleY, "vertical scale");
  return items.map((item) => ({
    ...item,
    x: nextBounds.x + (item.x - bounds.x) * scaleX,
    y: nextBounds.y + (item.y - bounds.y) * scaleY,
    width: item.width * scaleX,
    height: item.height * scaleY,
  }));
}

export function projectStructuredPrototypeGroupItemsToBounds(
  items: readonly StructuredPrototypeGroupTransformItem[],
  nextBounds: StructuredPrototypeGroupTransformBounds,
): StructuredPrototypeGroupTransformItem[] {
  return projectItemsToBounds(
    items,
    STRUCTURED_PROTOTYPE_GROUP_TRANSFORM_MIN_ITEMS,
    "group transform",
    nextBounds,
  );
}

export function projectStructuredPrototypeGroupResizeItemsToBounds(
  items: readonly StructuredPrototypeGroupTransformItem[],
  nextBounds: StructuredPrototypeGroupTransformBounds,
): StructuredPrototypeGroupTransformItem[] {
  return projectStructuredPrototypeGroupItemsToBounds(items, nextBounds).map((item) => ({
    ...item,
    x: normalizeStructuredPrototypeFreeformValue(item.x),
    y: normalizeStructuredPrototypeFreeformValue(item.y),
    width: normalizeStructuredPrototypeFreeformValue(item.width),
    height: normalizeStructuredPrototypeFreeformValue(item.height),
  }));
}

function resolveMinimumGroupSize(
  input: StructuredPrototypeGroupResizeSizeLimitsInput,
  bounds: StructuredPrototypeGroupTransformBounds,
): { width: number; height: number } {
  const { items } = input;
  const minimumScaleX = Math.max(
    ...items.map((item) => Math.min(1, STRUCTURED_PROTOTYPE_MIN_RESIZE_WIDTH / item.width)),
  );
  const minimumScaleY = Math.max(
    ...items.map((item) => Math.min(1, STRUCTURED_PROTOTYPE_MIN_RESIZE_HEIGHT / item.height)),
  );
  const axes = resolveStructuredPrototypeResizeHandleAxes(input.direction);
  const horizontalMode =
    input.resizeFromCenter || (axes.horizontal === null && input.lockAspectRatio)
      ? "center"
      : axes.horizontal === "west"
        ? "fixed-end"
        : null;
  const verticalMode =
    input.resizeFromCenter || (axes.vertical === null && input.lockAspectRatio)
      ? "center"
      : axes.vertical === "north"
        ? "fixed-end"
        : null;
  const minimumPositionScale = (axis: "x" | "y", mode: "center" | "fixed-end" | null): number => {
    if (mode === null) return 0;
    const start = axis === "x" ? bounds.x : bounds.y;
    const size = axis === "x" ? bounds.width : bounds.height;
    const anchor = mode === "center" ? start + size / 2 : start + size;
    if (anchor <= STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE) return 0;
    return Math.max(
      ...items.map((item) => {
        const position = axis === "x" ? item.x : item.y;
        const distance = anchor - position;
        assertPositive(distance, `${axis} canonical position distance`);
        return Math.min(1, (anchor - STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE) / distance);
      }),
    );
  };
  return {
    width: bounds.width * Math.max(minimumScaleX, minimumPositionScale("x", horizontalMode)),
    height: bounds.height * Math.max(minimumScaleY, minimumPositionScale("y", verticalMode)),
  };
}

function resolveMaximumGroupSize(
  items: readonly StructuredPrototypeGroupTransformItem[],
  bounds: StructuredPrototypeGroupTransformBounds,
): StructuredPrototypeResizeSize {
  const maximumScaleX = Math.min(
    ...items.map((item) => STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE / item.width),
  );
  const maximumScaleY = Math.min(
    ...items.map((item) => STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE / item.height),
  );
  assertPositive(maximumScaleX, "maximum horizontal scale");
  assertPositive(maximumScaleY, "maximum vertical scale");
  return {
    width: bounds.width * maximumScaleX,
    height: bounds.height * maximumScaleY,
  };
}

function resolveGroupResizeSizeLimits(
  input: StructuredPrototypeGroupResizeSizeLimitsInput,
  bounds: StructuredPrototypeGroupTransformBounds,
): StructuredPrototypeGroupResizeSizeLimits {
  return {
    minimumSize: resolveMinimumGroupSize(input, bounds),
    maximumSize: resolveMaximumGroupSize(input.items, bounds),
  };
}

export function resolveStructuredPrototypeGroupResizeSizeLimits(
  input: StructuredPrototypeGroupResizeSizeLimitsInput,
): StructuredPrototypeGroupResizeSizeLimits {
  const bounds = resolveStructuredPrototypeGroupTransformBounds(input.items);
  return resolveGroupResizeSizeLimits(input, bounds);
}

function compareHorizontal(
  left: StructuredPrototypeGroupTransformItem,
  right: StructuredPrototypeGroupTransformItem,
): number {
  if (left.x !== right.x) return left.x < right.x ? -1 : 1;
  if (left.y !== right.y) return left.y < right.y ? -1 : 1;
  if (left.nodeId === right.nodeId) return 0;
  return left.nodeId < right.nodeId ? -1 : 1;
}

function compareVertical(
  left: StructuredPrototypeGroupTransformItem,
  right: StructuredPrototypeGroupTransformItem,
): number {
  if (left.y !== right.y) return left.y < right.y ? -1 : 1;
  if (left.x !== right.x) return left.x < right.x ? -1 : 1;
  if (left.nodeId === right.nodeId) return 0;
  return left.nodeId < right.nodeId ? -1 : 1;
}

export function resolveStructuredPrototypeGroupTransformBounds(
  items: readonly StructuredPrototypeGroupTransformItem[],
): StructuredPrototypeGroupTransformBounds {
  return resolveTransformBounds(
    items,
    STRUCTURED_PROTOTYPE_GROUP_TRANSFORM_MIN_ITEMS,
    "group transform",
  );
}

export function resolveStructuredPrototypeSelectionNudge({
  items,
  deltaX,
  deltaY,
  containerWidth,
  containerHeight,
}: {
  items: readonly StructuredPrototypeGroupTransformItem[];
  deltaX: number;
  deltaY: number;
  containerWidth: number;
  containerHeight: number;
}): StructuredPrototypeGroupTransformItem[] {
  const bounds = resolveTransformBounds(items, 1, "selection nudge");
  assertFinite(deltaX, "nudge delta x");
  assertFinite(deltaY, "nudge delta y");
  assertContainer(containerWidth, containerHeight);
  assertItemsWithinContainer(items, containerWidth, containerHeight);
  const nextBounds = {
    ...bounds,
    x: clamp(bounds.x + deltaX, 0, containerWidth - bounds.width),
    y: clamp(bounds.y + deltaY, 0, containerHeight - bounds.height),
  };
  const transformed = projectItemsToBounds(items, 1, "selection nudge", nextBounds);
  assertItemsWithinContainer(transformed, containerWidth, containerHeight);
  return transformed;
}

export function resolveStructuredPrototypeGroupMove({
  items,
  startClientX,
  startClientY,
  clientX,
  clientY,
  previewScale,
  containerWidth,
  containerHeight,
}: StructuredPrototypeGroupMoveInput): StructuredPrototypeGroupTransformItem[] {
  const bounds = validateGroupInContainer(items, containerWidth, containerHeight);
  const delta = resolveClientDelta(startClientX, startClientY, clientX, clientY, previewScale);
  const nextBounds = {
    ...bounds,
    x: clamp(bounds.x + delta.x, 0, containerWidth - bounds.width),
    y: clamp(bounds.y + delta.y, 0, containerHeight - bounds.height),
  };
  const transformed = projectStructuredPrototypeGroupItemsToBounds(items, nextBounds);
  assertItemsWithinContainer(transformed, containerWidth, containerHeight);
  return transformed;
}

export function resolveStructuredPrototypeGroupResize(
  input: StructuredPrototypeGroupResizeInput,
): StructuredPrototypeGroupTransformItem[] {
  const bounds = resolveStructuredPrototypeGroupTransformBounds(input.items);
  const sizeLimits = resolveGroupResizeSizeLimits(input, bounds);
  assertContainer(input.containerWidth, input.containerHeight);
  const delta = resolveClientDelta(
    input.startClientX,
    input.startClientY,
    input.clientX,
    input.clientY,
    input.previewScale,
  );
  const nextBounds = resolveStructuredPrototypeResizeBounds({
    startBounds: bounds,
    requestedCanvasDelta: delta,
    direction: input.direction,
    lockAspectRatio: input.lockAspectRatio,
    resizeFromCenter: input.resizeFromCenter,
    aspectDriver: "auto",
    minimumSize: sizeLimits.minimumSize,
    maximumSize: sizeLimits.maximumSize,
    containerWidth: input.containerWidth,
    containerHeight: input.containerHeight,
    dimensionPrecision: "continuous",
  });
  return projectStructuredPrototypeGroupResizeItemsToBounds(input.items, nextBounds);
}

export function resolveStructuredPrototypeGroupAlignment(
  items: readonly StructuredPrototypeGroupTransformItem[],
  alignment: StructuredPrototypeGroupAlignment,
): StructuredPrototypeGroupTransformItem[] {
  const bounds = resolveStructuredPrototypeGroupTransformBounds(items);
  switch (alignment) {
    case "left":
      return items.map((item) => ({ ...item, x: bounds.x }));
    case "center":
      return items.map((item) => ({ ...item, x: bounds.x + (bounds.width - item.width) / 2 }));
    case "right":
      return items.map((item) => ({ ...item, x: bounds.x + bounds.width - item.width }));
    case "top":
      return items.map((item) => ({ ...item, y: bounds.y }));
    case "middle":
      return items.map((item) => ({ ...item, y: bounds.y + (bounds.height - item.height) / 2 }));
    case "bottom":
      return items.map((item) => ({ ...item, y: bounds.y + bounds.height - item.height }));
  }
}

export function resolveStructuredPrototypeGroupDistribution(
  items: readonly StructuredPrototypeGroupTransformItem[],
  axis: StructuredPrototypeGroupDistributionAxis,
): StructuredPrototypeGroupTransformItem[] {
  const bounds = resolveStructuredPrototypeGroupTransformBounds(items);
  const sorted = [...items].sort(axis === "horizontal" ? compareHorizontal : compareVertical);
  const totalSize = sorted.reduce(
    (sum, item) => sum + (axis === "horizontal" ? item.width : item.height),
    0,
  );
  assertFinite(totalSize, "distribution total size");
  const availableSize = axis === "horizontal" ? bounds.width : bounds.height;
  const gap = (availableSize - totalSize) / (sorted.length - 1);
  assertFinite(gap, "distribution gap");
  const positions = new Map<string, number>();
  let cursor = axis === "horizontal" ? bounds.x : bounds.y;
  const lastIndex = sorted.length - 1;
  for (const [index, item] of sorted.entries()) {
    const dimension = axis === "horizontal" ? item.width : item.height;
    const position =
      index === lastIndex
        ? axis === "horizontal"
          ? bounds.x + bounds.width - dimension
          : bounds.y + bounds.height - dimension
        : cursor;
    positions.set(item.nodeId, position);
    cursor = position + dimension + gap;
  }
  return items.map((item) => {
    const position = positions.get(item.nodeId);
    if (position === undefined) throw new Error(`group transform distribution lost ${item.nodeId}`);
    return axis === "horizontal" ? { ...item, x: position } : { ...item, y: position };
  });
}
