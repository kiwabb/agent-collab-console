import { resolveStructuredPrototypeClientDeltaToCanvas } from "./structuredPrototypeViewportTransform";

export const STRUCTURED_PROTOTYPE_MIN_RESIZE_WIDTH = 48;
export const STRUCTURED_PROTOTYPE_MIN_RESIZE_HEIGHT = 36;
export const STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE = 4096;

const STRUCTURED_PROTOTYPE_GEOMETRY_EPSILON = 1e-9;

export type StructuredPrototypeResizeDirection =
  "north" | "northeast" | "east" | "southeast" | "south" | "southwest" | "west" | "northwest";

function structuredPrototypeGeometryTolerance(left: number, right: number): number {
  return STRUCTURED_PROTOTYPE_GEOMETRY_EPSILON * Math.max(1, Math.abs(left), Math.abs(right));
}

export function normalizeStructuredPrototypeFreeformValue(value: number): number {
  if (!Number.isFinite(value)) {
    throw new Error("freeform value must be finite and within the canvas bounds");
  }
  if (value < 0) {
    if (-value <= structuredPrototypeGeometryTolerance(value, 0)) return 0;
    throw new Error("freeform value must be finite and within the canvas bounds");
  }
  if (value > STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE) {
    if (
      value - STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE <=
      structuredPrototypeGeometryTolerance(value, STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE)
    ) {
      return STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE;
    }
    throw new Error("freeform value must be finite and within the canvas bounds");
  }
  return value;
}

export function canonicalStructuredPrototypeFreeformValue(value: number): string {
  return Number(normalizeStructuredPrototypeFreeformValue(value).toFixed(4)).toString();
}

export interface StructuredPrototypeFreeformFrame {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface StructuredPrototypeResizeSize {
  width: number;
  height: number;
}

export type StructuredPrototypeResizeAspectDriver = "auto" | "x" | "y";
export type StructuredPrototypeResizeDimensionPrecision = "continuous" | "integer";
export type StructuredPrototypeResizeHorizontalEdge = "west" | "east";
export type StructuredPrototypeResizeVerticalEdge = "north" | "south";

export interface StructuredPrototypeResizeHandleAxes {
  horizontal: StructuredPrototypeResizeHorizontalEdge | null;
  vertical: StructuredPrototypeResizeVerticalEdge | null;
}

export interface StructuredPrototypeResizeBoundsInput {
  startBounds: StructuredPrototypeFreeformFrame;
  requestedCanvasDelta: { x: number; y: number };
  direction: StructuredPrototypeResizeDirection;
  lockAspectRatio: boolean;
  resizeFromCenter: boolean;
  aspectDriver: StructuredPrototypeResizeAspectDriver;
  minimumSize: StructuredPrototypeResizeSize;
  maximumSize: StructuredPrototypeResizeSize;
  containerWidth: number;
  containerHeight: number;
  dimensionPrecision: StructuredPrototypeResizeDimensionPrecision;
}

interface FreeformMoveInput {
  startX: number;
  startY: number;
  startClientX: number;
  startClientY: number;
  clientX: number;
  clientY: number;
  previewScale: number;
  nodeWidth: number;
  nodeHeight: number;
  containerWidth: number;
  containerHeight: number;
}

interface FreeformResizeInput extends StructuredPrototypeFreeformFrame {
  startClientX: number;
  startClientY: number;
  clientX: number;
  clientY: number;
  previewScale: number;
  direction: StructuredPrototypeResizeDirection;
  lockAspectRatio: boolean;
  resizeFromCenter: boolean;
  containerWidth: number;
  containerHeight: number;
}

function clamp(value: number, minimum: number, maximum: number): number {
  if (!Number.isFinite(value) || !Number.isFinite(minimum) || !Number.isFinite(maximum)) {
    throw new Error("freeform resize clamp values must be finite");
  }
  if (maximum < minimum) throw new Error("freeform resize clamp range is invalid");
  return Math.min(Math.max(minimum, value), maximum);
}

function resizeValueTolerance(left: number, right: number): number {
  return structuredPrototypeGeometryTolerance(left, right);
}

function stabilizeResizeValue(value: number, startValue: number): number {
  return Math.abs(value - startValue) <= resizeValueTolerance(value, startValue)
    ? startValue
    : value;
}

function reconcileResizeMinimum(
  minimum: number,
  maximum: number,
  infeasibleMessage: string,
): number {
  if (maximum >= minimum) return minimum;
  const tolerance = resizeValueTolerance(minimum, maximum);
  if (minimum - maximum > tolerance) throw new Error(infeasibleMessage);
  return maximum;
}

function reconcileResizeMaximum(value: number, maximum: number, label: string): number {
  if (value <= maximum) return value;
  if (value - maximum <= resizeValueTolerance(value, maximum)) return maximum;
  throw new Error(`freeform resize ${label} exceeds its maximum`);
}

function reconcileResizeCoordinateMaximum(value: number, label: string): number {
  if (value >= 0) return value;
  if (-value <= resizeValueTolerance(value, 0)) return 0;
  throw new Error(`freeform resize ${label} has no non-negative range`);
}

function assertFinite(value: number, label: string): void {
  if (!Number.isFinite(value)) throw new Error(`freeform resize ${label} must be finite`);
}

function assertPositive(value: number, label: string): void {
  assertFinite(value, label);
  if (value <= 0) throw new Error(`freeform resize ${label} must be positive`);
}

export function resolveStructuredPrototypeResizeHandleAxes(
  direction: StructuredPrototypeResizeDirection,
): StructuredPrototypeResizeHandleAxes {
  switch (direction) {
    case "north":
      return { horizontal: null, vertical: "north" };
    case "northeast":
      return { horizontal: "east", vertical: "north" };
    case "east":
      return { horizontal: "east", vertical: null };
    case "southeast":
      return { horizontal: "east", vertical: "south" };
    case "south":
      return { horizontal: null, vertical: "south" };
    case "southwest":
      return { horizontal: "west", vertical: "south" };
    case "west":
      return { horizontal: "west", vertical: null };
    case "northwest":
      return { horizontal: "west", vertical: "north" };
    default:
      throw new Error(`freeform resize direction is invalid: ${direction}`);
  }
}

function assertAspectDriver(
  aspectDriver: StructuredPrototypeResizeAspectDriver,
  axes: StructuredPrototypeResizeHandleAxes,
): void {
  if (aspectDriver === "x" && axes.horizontal === null) {
    throw new Error("freeform resize x aspect driver requires a horizontal handle");
  }
  if (aspectDriver === "y" && axes.vertical === null) {
    throw new Error("freeform resize y aspect driver requires a vertical handle");
  }
}

function assertResizeBoundsInput({
  startBounds,
  requestedCanvasDelta,
  aspectDriver,
  minimumSize,
  maximumSize,
  containerWidth,
  containerHeight,
}: StructuredPrototypeResizeBoundsInput): void {
  assertFinite(startBounds.x, "start x");
  assertFinite(startBounds.y, "start y");
  assertPositive(startBounds.width, "start width");
  assertPositive(startBounds.height, "start height");
  if (startBounds.x < 0 || startBounds.y < 0) {
    throw new Error("freeform resize start position must not be negative");
  }
  assertFinite(requestedCanvasDelta.x, "requested delta x");
  assertFinite(requestedCanvasDelta.y, "requested delta y");
  assertPositive(minimumSize.width, "minimum width");
  assertPositive(minimumSize.height, "minimum height");
  assertPositive(maximumSize.width, "maximum width constraint");
  assertPositive(maximumSize.height, "maximum height constraint");
  assertPositive(containerWidth, "container width");
  assertPositive(containerHeight, "container height");
  if (aspectDriver !== "auto" && aspectDriver !== "x" && aspectDriver !== "y") {
    throw new Error("freeform resize aspect driver is invalid");
  }
}

function resolveAspectDriver(
  input: StructuredPrototypeResizeBoundsInput,
  axes: StructuredPrototypeResizeHandleAxes,
  rawWidth: number,
  rawHeight: number,
): "x" | "y" {
  assertAspectDriver(input.aspectDriver, axes);
  if (input.aspectDriver !== "auto") return input.aspectDriver;
  if (axes.horizontal === null) return "y";
  if (axes.vertical === null) return "x";
  const horizontalChange = Math.abs((rawWidth - input.startBounds.width) / input.startBounds.width);
  const verticalChange = Math.abs(
    (rawHeight - input.startBounds.height) / input.startBounds.height,
  );
  return horizontalChange >= verticalChange ? "x" : "y";
}

/**
 * Resolves one resize frame for both single nodes and selection bounds. The
 * overflow envelope includes the current right/bottom edges, so responsive
 * containers can recover existing overflow without making it worse.
 */
export function resolveStructuredPrototypeResizeBounds(
  input: StructuredPrototypeResizeBoundsInput,
): StructuredPrototypeFreeformFrame {
  assertResizeBoundsInput(input);
  const {
    startBounds,
    requestedCanvasDelta,
    lockAspectRatio,
    resizeFromCenter,
    minimumSize,
    maximumSize,
    containerWidth,
    containerHeight,
    dimensionPrecision,
  } = input;
  const axes = resolveStructuredPrototypeResizeHandleAxes(input.direction);
  const west = axes.horizontal === "west";
  const north = axes.vertical === "north";
  const horizontal = axes.horizontal !== null;
  const vertical = axes.vertical !== null;
  const horizontalFactor = resizeFromCenter ? 2 : 1;
  const verticalFactor = resizeFromCenter ? 2 : 1;
  const rawWidth = horizontal
    ? startBounds.width + requestedCanvasDelta.x * (west ? -horizontalFactor : horizontalFactor)
    : startBounds.width;
  const rawHeight = vertical
    ? startBounds.height + requestedCanvasDelta.y * (north ? -verticalFactor : verticalFactor)
    : startBounds.height;
  const centerX = startBounds.x + startBounds.width / 2;
  const centerY = startBounds.y + startBounds.height / 2;
  const startRight = startBounds.x + startBounds.width;
  const startBottom = startBounds.y + startBounds.height;
  const envelopeRight = Math.max(containerWidth, startRight);
  const envelopeBottom = Math.max(containerHeight, startBottom);
  const envelopeMaxWidth =
    resizeFromCenter || !horizontal
      ? 2 * Math.min(centerX, envelopeRight - centerX)
      : west
        ? startRight
        : envelopeRight - startBounds.x;
  const envelopeMaxHeight =
    resizeFromCenter || !vertical
      ? 2 * Math.min(centerY, envelopeBottom - centerY)
      : north
        ? startBottom
        : envelopeBottom - startBounds.y;
  const maxWidth = Math.min(envelopeMaxWidth, maximumSize.width);
  const maxHeight = Math.min(envelopeMaxHeight, maximumSize.height);
  assertPositive(maxWidth, "maximum width");
  assertPositive(maxHeight, "maximum height");

  // A legacy frame smaller than today's minimum remains editable without
  // jumping on the first pointer event.
  const minimumWidthForCanonicalX =
    resizeFromCenter || !horizontal
      ? Math.max(0, 2 * (centerX - STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE))
      : west
        ? Math.max(0, startRight - STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE)
        : 0;
  const minimumHeightForCanonicalY =
    resizeFromCenter || !vertical
      ? Math.max(0, 2 * (centerY - STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE))
      : north
        ? Math.max(0, startBottom - STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE)
        : 0;
  const effectiveMinimumWidth = Math.max(
    Math.min(minimumSize.width, startBounds.width),
    minimumWidthForCanonicalX,
  );
  const effectiveMinimumHeight = Math.max(
    Math.min(minimumSize.height, startBounds.height),
    minimumHeightForCanonicalY,
  );
  const feasibleMinimumWidth = reconcileResizeMinimum(
    effectiveMinimumWidth,
    maxWidth,
    "freeform resize minimum width exceeds its overflow envelope",
  );
  const feasibleMinimumHeight = reconcileResizeMinimum(
    effectiveMinimumHeight,
    maxHeight,
    "freeform resize minimum height exceeds its overflow envelope",
  );
  let width: number;
  let height: number;

  if (lockAspectRatio) {
    const aspectRatio = startBounds.width / startBounds.height;
    assertPositive(aspectRatio, "aspect ratio");
    const minimumWidth = Math.max(feasibleMinimumWidth, feasibleMinimumHeight * aspectRatio);
    const maximumWidth = Math.min(maxWidth, maxHeight * aspectRatio);
    const aspectMinimumWidth = reconcileResizeMinimum(
      minimumWidth,
      maximumWidth,
      "freeform resize cannot preserve aspect ratio in its overflow envelope",
    );
    const driver = resolveAspectDriver(input, axes, rawWidth, rawHeight);
    if (driver === "x") {
      width = clamp(rawWidth, aspectMinimumWidth, maximumWidth);
      height = width / aspectRatio;
    } else {
      const minimumHeight = Math.max(feasibleMinimumHeight, feasibleMinimumWidth / aspectRatio);
      const maximumHeight = Math.min(maxHeight, maxWidth / aspectRatio);
      const aspectMinimumHeight = reconcileResizeMinimum(
        minimumHeight,
        maximumHeight,
        "freeform resize cannot preserve aspect ratio in its overflow envelope",
      );
      height = clamp(rawHeight, aspectMinimumHeight, maximumHeight);
      width = height * aspectRatio;
    }
  } else {
    assertAspectDriver(input.aspectDriver, axes);
    width = horizontal ? clamp(rawWidth, feasibleMinimumWidth, maxWidth) : startBounds.width;
    height = vertical ? clamp(rawHeight, feasibleMinimumHeight, maxHeight) : startBounds.height;
  }

  if (dimensionPrecision !== "continuous" && dimensionPrecision !== "integer") {
    throw new Error("freeform resize dimension precision is invalid");
  }
  if (dimensionPrecision === "integer") {
    width = clamp(Math.round(width), feasibleMinimumWidth, maxWidth);
    height = clamp(Math.round(height), feasibleMinimumHeight, maxHeight);
  }
  width = reconcileResizeMaximum(width, maxWidth, "resolved width");
  height = reconcileResizeMaximum(height, maxHeight, "resolved height");
  assertPositive(width, "resolved width");
  assertPositive(height, "resolved height");

  const changedWidth =
    dimensionPrecision === "integer"
      ? width !== Math.round(startBounds.width)
      : width !== startBounds.width;
  const changedHeight =
    dimensionPrecision === "integer"
      ? height !== Math.round(startBounds.height)
      : height !== startBounds.height;
  const x =
    resizeFromCenter || (!horizontal && changedWidth)
      ? centerX - width / 2
      : west
        ? startRight - width
        : startBounds.x;
  const y =
    resizeFromCenter || (!vertical && changedHeight)
      ? centerY - height / 2
      : north
        ? startBottom - height
        : startBounds.y;
  const maximumX = reconcileResizeCoordinateMaximum(
    Math.min(STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE, envelopeRight - width),
    "x coordinate",
  );
  const maximumY = reconcileResizeCoordinateMaximum(
    Math.min(STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE, envelopeBottom - height),
    "y coordinate",
  );

  return {
    x: normalizeStructuredPrototypeFreeformValue(
      stabilizeResizeValue(clamp(x, 0, maximumX), startBounds.x),
    ),
    y: normalizeStructuredPrototypeFreeformValue(
      stabilizeResizeValue(clamp(y, 0, maximumY), startBounds.y),
    ),
    width: stabilizeResizeValue(width, startBounds.width),
    height: stabilizeResizeValue(height, startBounds.height),
  };
}

export function resolveStructuredPrototypeFreeformMove({
  startX,
  startY,
  startClientX,
  startClientY,
  clientX,
  clientY,
  previewScale,
  nodeWidth,
  nodeHeight,
  containerWidth,
  containerHeight,
}: FreeformMoveInput): { x: number; y: number } {
  const delta = resolveStructuredPrototypeClientDeltaToCanvas(
    { x: clientX - startClientX, y: clientY - startClientY },
    previewScale,
  );
  return {
    x: clamp(startX + delta.x, 0, Math.max(0, containerWidth - nodeWidth)),
    y: clamp(startY + delta.y, 0, Math.max(0, containerHeight - nodeHeight)),
  };
}

export interface StructuredPrototypeFreeformPointerPlacementInput {
  pointerClientX: number;
  pointerClientY: number;
  containerRect: { left: number; top: number };
  containerClientLeft: number;
  containerClientTop: number;
  previewScale: number;
  nodeWidth: number;
  nodeHeight: number;
  containerWidth: number;
  containerHeight: number;
}

/**
 * Resolves a pointer drop as the requested node top-left in the unscaled
 * Freeform canvas, then applies the same boundary semantics as a normal move.
 */
export function resolveStructuredPrototypeFreeformPointerPlacement({
  pointerClientX,
  pointerClientY,
  containerRect,
  containerClientLeft,
  containerClientTop,
  previewScale,
  nodeWidth,
  nodeHeight,
  containerWidth,
  containerHeight,
}: StructuredPrototypeFreeformPointerPlacementInput): { x: number; y: number } {
  const values = [
    pointerClientX,
    pointerClientY,
    containerRect.left,
    containerRect.top,
    containerClientLeft,
    containerClientTop,
    previewScale,
    nodeWidth,
    nodeHeight,
    containerWidth,
    containerHeight,
  ];
  if (values.some((value) => !Number.isFinite(value))) {
    throw new Error("freeform pointer placement geometry must be finite");
  }
  if (previewScale <= 0) throw new Error("freeform pointer placement scale must be positive");
  if (containerClientLeft < 0 || containerClientTop < 0) {
    throw new Error("freeform pointer placement border must be non-negative");
  }
  if (nodeWidth <= 0 || nodeHeight <= 0) {
    throw new Error("freeform pointer placement node size must be positive");
  }
  if (containerWidth <= 0 || containerHeight <= 0) {
    throw new Error("freeform pointer placement container size must be positive");
  }
  const contentOriginClientX = containerRect.left + containerClientLeft * previewScale;
  const contentOriginClientY = containerRect.top + containerClientTop * previewScale;
  return resolveStructuredPrototypeFreeformMove({
    startX: 0,
    startY: 0,
    startClientX: contentOriginClientX,
    startClientY: contentOriginClientY,
    clientX: pointerClientX,
    clientY: pointerClientY,
    previewScale,
    nodeWidth,
    nodeHeight,
    containerWidth,
    containerHeight,
  });
}

export function resolveStructuredPrototypeFreeformResize({
  x: startX,
  y: startY,
  width: startWidth,
  height: startHeight,
  startClientX,
  startClientY,
  clientX,
  clientY,
  previewScale,
  direction,
  lockAspectRatio,
  resizeFromCenter,
  containerWidth,
  containerHeight,
}: FreeformResizeInput): StructuredPrototypeFreeformFrame {
  const delta = resolveStructuredPrototypeClientDeltaToCanvas(
    { x: clientX - startClientX, y: clientY - startClientY },
    previewScale,
  );
  const frame = resolveStructuredPrototypeResizeBounds({
    startBounds: { x: startX, y: startY, width: startWidth, height: startHeight },
    requestedCanvasDelta: delta,
    direction,
    lockAspectRatio,
    resizeFromCenter,
    aspectDriver: "auto",
    minimumSize: {
      width: STRUCTURED_PROTOTYPE_MIN_RESIZE_WIDTH,
      height: STRUCTURED_PROTOTYPE_MIN_RESIZE_HEIGHT,
    },
    maximumSize: {
      width: STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE,
      height: STRUCTURED_PROTOTYPE_MAX_FREEFORM_COORDINATE,
    },
    containerWidth,
    containerHeight,
    dimensionPrecision: "integer",
  });
  return {
    x: Math.round(frame.x),
    y: Math.round(frame.y),
    width: frame.width,
    height: frame.height,
  };
}

export function structuredPrototypeTransformPassedActivationThreshold(
  startClientX: number,
  startClientY: number,
  clientX: number,
  clientY: number,
): boolean {
  return Math.hypot(clientX - startClientX, clientY - startClientY) >= 4;
}

export function structuredPrototypeCanStartTransform(button: number, isPrimary: boolean): boolean {
  return button === 0 && isPrimary;
}
