import {
  createStructuredPrototypeViewportTransform,
  type StructuredPrototypeClientRect,
} from "./structuredPrototypeViewportTransform";

export interface StructuredPrototypeSelectionBounds {
  top: number;
  left: number;
  width: number;
  height: number;
}

export interface StructuredPrototypeSelectionControlsGeometry {
  bounds: StructuredPrototypeSelectionBounds;
  handleScale: number;
}

export function resolveStructuredPrototypeSelectionControlsGeometry(
  canvasRect: StructuredPrototypeClientRect,
  nodeRect: StructuredPrototypeClientRect,
  previewScale: number,
): StructuredPrototypeSelectionControlsGeometry {
  const transform = createStructuredPrototypeViewportTransform({
    viewportOrigin: { x: canvasRect.left, y: canvasRect.top },
    canvasOrigin: { x: 0, y: 0 },
    pan: { x: 0, y: 0 },
    scale: previewScale,
  });
  const topLeft = transform.clientToCanvas({ x: nodeRect.left, y: nodeRect.top });
  const size = transform.clientDeltaToCanvas({ x: nodeRect.width, y: nodeRect.height });
  return {
    bounds: {
      top: topLeft.y,
      left: topLeft.x,
      width: size.x,
      height: size.y,
    },
    handleScale: transform.inverseScale,
  };
}

export function sameStructuredPrototypeSelectionBounds(
  left: StructuredPrototypeSelectionBounds | null,
  right: StructuredPrototypeSelectionBounds,
): boolean {
  return (
    left !== null &&
    left.top === right.top &&
    left.left === right.left &&
    left.width === right.width &&
    left.height === right.height
  );
}
