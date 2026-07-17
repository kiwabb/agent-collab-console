export interface StructuredPrototypePoint {
  x: number;
  y: number;
}

export interface StructuredPrototypeClientRect {
  top: number;
  right: number;
  bottom: number;
  left: number;
  width: number;
  height: number;
}

interface StructuredPrototypeViewportTransformInput {
  viewportOrigin: StructuredPrototypePoint;
  canvasOrigin: StructuredPrototypePoint;
  pan: StructuredPrototypePoint;
  scale: number;
}

export interface StructuredPrototypeViewportTransform {
  scale: number;
  inverseScale: number;
  clientToCanvas: (point: StructuredPrototypePoint) => StructuredPrototypePoint;
  canvasToClient: (point: StructuredPrototypePoint) => StructuredPrototypePoint;
  clientDeltaToCanvas: (delta: StructuredPrototypePoint) => StructuredPrototypePoint;
}

export function resolveStructuredPrototypeInverseScale(scale: number): number {
  return 1 / scale;
}

export function resolveStructuredPrototypeClientDeltaToCanvas(
  delta: StructuredPrototypePoint,
  scale: number,
): StructuredPrototypePoint {
  const inverseScale = resolveStructuredPrototypeInverseScale(scale);
  return { x: delta.x * inverseScale, y: delta.y * inverseScale };
}

export function createStructuredPrototypeViewportTransform({
  viewportOrigin,
  canvasOrigin,
  pan,
  scale,
}: StructuredPrototypeViewportTransformInput): StructuredPrototypeViewportTransform {
  const inverseScale = resolveStructuredPrototypeInverseScale(scale);
  return {
    scale,
    inverseScale,
    clientToCanvas: (point) => ({
      x: canvasOrigin.x + (point.x - viewportOrigin.x - pan.x) * inverseScale,
      y: canvasOrigin.y + (point.y - viewportOrigin.y - pan.y) * inverseScale,
    }),
    canvasToClient: (point) => ({
      x: viewportOrigin.x + pan.x + (point.x - canvasOrigin.x) * scale,
      y: viewportOrigin.y + pan.y + (point.y - canvasOrigin.y) * scale,
    }),
    clientDeltaToCanvas: (delta) => resolveStructuredPrototypeClientDeltaToCanvas(delta, scale),
  };
}

interface StructuredPrototypeFitScaleInput {
  hostWidth: number;
  hostHeight: number;
  viewportWidth: number;
  viewportHeight: number;
  measuredContentHeight: number;
  padding: number;
}

export function resolveStructuredPrototypeFitScale({
  hostWidth,
  hostHeight,
  viewportWidth,
  viewportHeight,
  measuredContentHeight,
  padding,
}: StructuredPrototypeFitScaleInput): number {
  const availableWidth = hostWidth - padding;
  const availableHeight = hostHeight - padding;
  const frameHeight = Math.max(viewportHeight, measuredContentHeight);
  if (
    !Number.isFinite(availableWidth) ||
    !Number.isFinite(availableHeight) ||
    !Number.isFinite(viewportWidth) ||
    !Number.isFinite(frameHeight) ||
    availableWidth <= 0 ||
    availableHeight <= 0 ||
    viewportWidth <= 0 ||
    frameHeight <= 0
  ) {
    return 1;
  }
  const scale = Math.min(availableWidth / viewportWidth, availableHeight / frameHeight);
  return Number.isFinite(scale) && scale > 0 ? Math.min(1, scale) : 1;
}

interface StructuredPrototypeZoomAtPointInput {
  pan: StructuredPrototypePoint;
  pointerFromViewportOrigin: StructuredPrototypePoint;
  currentScale: number;
  nextScale: number;
}

const ORIGIN: StructuredPrototypePoint = { x: 0, y: 0 };

export function resolveStructuredPrototypeZoomAtPoint({
  pan,
  pointerFromViewportOrigin,
  currentScale,
  nextScale,
}: StructuredPrototypeZoomAtPointInput): StructuredPrototypePoint {
  if (
    !Number.isFinite(currentScale) ||
    !Number.isFinite(nextScale) ||
    currentScale <= 0 ||
    nextScale <= 0
  ) {
    return pan;
  }
  const currentTransform = createStructuredPrototypeViewportTransform({
    viewportOrigin: ORIGIN,
    canvasOrigin: ORIGIN,
    pan,
    scale: currentScale,
  });
  const canvasPoint = currentTransform.clientToCanvas(pointerFromViewportOrigin);
  return {
    x: pointerFromViewportOrigin.x - canvasPoint.x * nextScale,
    y: pointerFromViewportOrigin.y - canvasPoint.y * nextScale,
  };
}

interface StructuredPrototypeWheelDeltaInput {
  deltaY: number;
  deltaMode: number;
  pageHeight: number;
  lineHeight?: number;
}

export function normalizeStructuredPrototypeWheelDelta({
  deltaY,
  deltaMode,
  pageHeight,
  lineHeight = 16,
}: StructuredPrototypeWheelDeltaInput): number {
  if (
    !Number.isFinite(deltaY) ||
    !Number.isFinite(pageHeight) ||
    !Number.isFinite(lineHeight) ||
    pageHeight <= 0 ||
    lineHeight <= 0
  ) {
    return 0;
  }
  if (deltaMode === 0) return deltaY;
  if (deltaMode === 1) return deltaY * lineHeight;
  if (deltaMode === 2) return deltaY * pageHeight;
  return 0;
}

interface StructuredPrototypeWheelScaleInput {
  currentScale: number;
  normalizedDeltaY: number;
  minimumScale: number;
  maximumScale: number;
  intensity: number;
}

export function resolveStructuredPrototypeWheelScale({
  currentScale,
  normalizedDeltaY,
  minimumScale,
  maximumScale,
  intensity,
}: StructuredPrototypeWheelScaleInput): number {
  if (
    !Number.isFinite(currentScale) ||
    !Number.isFinite(normalizedDeltaY) ||
    !Number.isFinite(minimumScale) ||
    !Number.isFinite(maximumScale) ||
    !Number.isFinite(intensity) ||
    currentScale <= 0 ||
    minimumScale <= 0 ||
    maximumScale < minimumScale ||
    intensity <= 0
  ) {
    return currentScale;
  }
  const nextScale = currentScale * Math.exp(-normalizedDeltaY * intensity);
  return Number(Math.min(maximumScale, Math.max(minimumScale, nextScale)).toFixed(3));
}
