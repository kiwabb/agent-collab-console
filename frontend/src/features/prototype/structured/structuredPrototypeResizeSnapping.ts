import {
  resolveStructuredPrototypeResizeBounds,
  resolveStructuredPrototypeResizeHandleAxes,
  type StructuredPrototypeResizeAspectDriver,
  type StructuredPrototypeResizeDirection,
  type StructuredPrototypeResizeSize,
} from "./structuredPrototypeFreeformGeometry";
import {
  STRUCTURED_PROTOTYPE_FREEFORM_SNAP_THRESHOLD_CLIENT_PX,
  type StructuredPrototypeFreeformSnapAnchor,
  type StructuredPrototypeFreeformSnapAxis,
  type StructuredPrototypeFreeformSnapBounds,
  type StructuredPrototypeFreeformSnapGuide,
  type StructuredPrototypeFreeformSnapPoint,
  type StructuredPrototypeFreeformSnapSibling,
  type StructuredPrototypeFreeformSnapTargetKind,
} from "./structuredPrototypeSnapping";

export interface StructuredPrototypeFreeformResizeSnapInput {
  readonly startBounds: Readonly<StructuredPrototypeFreeformSnapBounds>;
  readonly requestedCanvasDelta: Readonly<StructuredPrototypeFreeformSnapPoint>;
  readonly direction: StructuredPrototypeResizeDirection;
  readonly lockAspectRatio: boolean;
  readonly resizeFromCenter: boolean;
  readonly bypassSnapping: boolean;
  readonly minimumSize: Readonly<StructuredPrototypeResizeSize>;
  readonly maximumSize: Readonly<StructuredPrototypeResizeSize>;
  readonly selectedNodeIds: readonly string[];
  readonly directSiblings: readonly Readonly<StructuredPrototypeFreeformSnapSibling>[];
  readonly containerWidth: number;
  readonly containerHeight: number;
  readonly previewScale: number;
}

export interface StructuredPrototypeFreeformResizeSnapResult {
  readonly bounds: StructuredPrototypeFreeformSnapBounds;
  readonly guides: readonly StructuredPrototypeFreeformSnapGuide[];
}

type HorizontalTargetAnchor = "left" | "center" | "right";
type VerticalTargetAnchor = "top" | "middle" | "bottom";

interface ResizeSnapTarget {
  readonly axis: StructuredPrototypeFreeformSnapAxis;
  readonly coordinate: number;
  readonly anchor: StructuredPrototypeFreeformSnapAnchor;
  readonly kind: StructuredPrototypeFreeformSnapTargetKind;
  readonly nodeId: string | null;
}

interface ResizeSnapCandidate {
  readonly axis: StructuredPrototypeFreeformSnapAxis;
  readonly target: ResizeSnapTarget;
  readonly bounds: StructuredPrototypeFreeformSnapBounds;
  readonly distanceClient: number;
}

const SNAP_COORDINATE_EPSILON = 1e-7;

function assertFinite(value: number, label: string): void {
  if (!Number.isFinite(value)) throw new Error(`freeform resize snap ${label} must be finite`);
}

function assertPositive(value: number, label: string): void {
  assertFinite(value, label);
  if (value <= 0) throw new Error(`freeform resize snap ${label} must be positive`);
}

function assertBounds(bounds: StructuredPrototypeFreeformSnapBounds, label: string): void {
  assertFinite(bounds.x, `${label} x`);
  assertFinite(bounds.y, `${label} y`);
  assertPositive(bounds.width, `${label} width`);
  assertPositive(bounds.height, `${label} height`);
  if (bounds.x < 0 || bounds.y < 0) {
    throw new Error(`freeform resize snap ${label} position must not be negative`);
  }
}

function resolveSelectedNodeIds(nodeIds: readonly string[]): ReadonlySet<string> {
  if (nodeIds.length === 0) {
    throw new Error("freeform resize snap requires at least one selected node");
  }
  const selected = new Set<string>();
  for (const nodeId of nodeIds) {
    if (nodeId.length === 0) {
      throw new Error("freeform resize snap selected node id must not be empty");
    }
    if (selected.has(nodeId)) {
      throw new Error(`freeform resize snap selected node id is duplicated: ${nodeId}`);
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
      throw new Error("freeform resize snap sibling node id must not be empty");
    }
    if (nodeIds.has(sibling.nodeId)) {
      throw new Error(`freeform resize snap sibling node id is duplicated: ${sibling.nodeId}`);
    }
    nodeIds.add(sibling.nodeId);
    assertBounds(sibling, `sibling ${sibling.nodeId}`);
  }
}

function horizontalAnchors(
  bounds: StructuredPrototypeFreeformSnapBounds,
): readonly { anchor: HorizontalTargetAnchor; coordinate: number }[] {
  return [
    { anchor: "left", coordinate: bounds.x },
    { anchor: "center", coordinate: bounds.x + bounds.width / 2 },
    { anchor: "right", coordinate: bounds.x + bounds.width },
  ];
}

function verticalAnchors(
  bounds: StructuredPrototypeFreeformSnapBounds,
): readonly { anchor: VerticalTargetAnchor; coordinate: number }[] {
  return [
    { anchor: "top", coordinate: bounds.y },
    { anchor: "middle", coordinate: bounds.y + bounds.height / 2 },
    { anchor: "bottom", coordinate: bounds.y + bounds.height },
  ];
}

function buildTargets(
  input: StructuredPrototypeFreeformResizeSnapInput,
  selectedNodeIds: ReadonlySet<string>,
): readonly ResizeSnapTarget[] {
  const targets: ResizeSnapTarget[] = [];
  for (const target of horizontalAnchors({
    x: 0,
    y: 0,
    width: input.containerWidth,
    height: 1,
  })) {
    targets.push({
      axis: "x",
      coordinate: target.coordinate,
      anchor: target.anchor,
      kind: "container",
      nodeId: null,
    });
  }
  for (const target of verticalAnchors({
    x: 0,
    y: 0,
    width: 1,
    height: input.containerHeight,
  })) {
    targets.push({
      axis: "y",
      coordinate: target.coordinate,
      anchor: target.anchor,
      kind: "container",
      nodeId: null,
    });
  }
  for (const sibling of input.directSiblings) {
    if (selectedNodeIds.has(sibling.nodeId)) continue;
    for (const target of horizontalAnchors(sibling)) {
      targets.push({
        axis: "x",
        coordinate: target.coordinate,
        anchor: target.anchor,
        kind: "sibling",
        nodeId: sibling.nodeId,
      });
    }
    for (const target of verticalAnchors(sibling)) {
      targets.push({
        axis: "y",
        coordinate: target.coordinate,
        anchor: target.anchor,
        kind: "sibling",
        nodeId: sibling.nodeId,
      });
    }
  }
  return targets;
}

function targetKindRank(kind: StructuredPrototypeFreeformSnapTargetKind): number {
  if (kind === "container") return 0;
  if (kind === "sibling") return 1;
  return 2;
}

function targetAnchorRank(anchor: StructuredPrototypeFreeformSnapAnchor): number {
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

function compareNodeIds(left: string | null, right: string | null): number {
  const leftValue = left ?? "";
  const rightValue = right ?? "";
  if (leftValue === rightValue) return 0;
  return leftValue < rightValue ? -1 : 1;
}

function compareCandidates(
  left: ResizeSnapCandidate,
  right: ResizeSnapCandidate,
  preferredAspectDriver: StructuredPrototypeFreeformSnapAxis | null,
): number {
  if (left.distanceClient !== right.distanceClient) {
    return left.distanceClient < right.distanceClient ? -1 : 1;
  }
  if (preferredAspectDriver !== null) {
    const leftDriverRank = left.axis === preferredAspectDriver ? 0 : 1;
    const rightDriverRank = right.axis === preferredAspectDriver ? 0 : 1;
    if (leftDriverRank !== rightDriverRank) return leftDriverRank - rightDriverRank;
  }
  const leftKindRank = targetKindRank(left.target.kind);
  const rightKindRank = targetKindRank(right.target.kind);
  if (leftKindRank !== rightKindRank) return leftKindRank - rightKindRank;
  if (left.target.coordinate !== right.target.coordinate) {
    return left.target.coordinate < right.target.coordinate ? -1 : 1;
  }
  const nodeComparison = compareNodeIds(left.target.nodeId, right.target.nodeId);
  if (nodeComparison !== 0) return nodeComparison;
  const anchorComparison =
    targetAnchorRank(left.target.anchor) - targetAnchorRank(right.target.anchor);
  if (anchorComparison !== 0) return anchorComparison;
  if (left.axis === right.axis) return 0;
  return left.axis === "x" ? -1 : 1;
}

function sameCoordinate(left: number, right: number): boolean {
  const magnitude = Math.max(1, Math.abs(left), Math.abs(right));
  return Math.abs(left - right) <= SNAP_COORDINATE_EPSILON * magnitude;
}

function activeCoordinate(
  bounds: StructuredPrototypeFreeformSnapBounds,
  axis: StructuredPrototypeFreeformSnapAxis,
  input: StructuredPrototypeFreeformResizeSnapInput,
): number {
  const axes = resolveStructuredPrototypeResizeHandleAxes(input.direction);
  if (axis === "x") {
    if (axes.horizontal === null) {
      throw new Error("freeform resize snap x coordinate requires a horizontal handle");
    }
    return axes.horizontal === "west" ? bounds.x : bounds.x + bounds.width;
  }
  if (axes.vertical === null) {
    throw new Error("freeform resize snap y coordinate requires a vertical handle");
  }
  return axes.vertical === "north" ? bounds.y : bounds.y + bounds.height;
}

function movingAnchor(
  axis: StructuredPrototypeFreeformSnapAxis,
  input: StructuredPrototypeFreeformResizeSnapInput,
): StructuredPrototypeFreeformSnapAnchor {
  const axes = resolveStructuredPrototypeResizeHandleAxes(input.direction);
  if (axis === "x") {
    if (axes.horizontal === null) {
      throw new Error("freeform resize snap x guide requires a horizontal handle");
    }
    return axes.horizontal === "west" ? "left" : "right";
  }
  if (axes.vertical === null) {
    throw new Error("freeform resize snap y guide requires a vertical handle");
  }
  return axes.vertical === "north" ? "top" : "bottom";
}

function resolveBounds(
  input: StructuredPrototypeFreeformResizeSnapInput,
  requestedCanvasDelta: StructuredPrototypeFreeformSnapPoint,
  aspectDriver: StructuredPrototypeResizeAspectDriver,
): StructuredPrototypeFreeformSnapBounds {
  return resolveStructuredPrototypeResizeBounds({
    startBounds: { ...input.startBounds },
    requestedCanvasDelta,
    direction: input.direction,
    lockAspectRatio: input.lockAspectRatio,
    resizeFromCenter: input.resizeFromCenter,
    aspectDriver,
    minimumSize: { ...input.minimumSize },
    maximumSize: { ...input.maximumSize },
    containerWidth: input.containerWidth,
    containerHeight: input.containerHeight,
    dimensionPrecision: "continuous",
  });
}

function resolveRawAspectDriver(
  input: StructuredPrototypeFreeformResizeSnapInput,
): StructuredPrototypeFreeformSnapAxis {
  const axes = resolveStructuredPrototypeResizeHandleAxes(input.direction);
  if (axes.horizontal === null) return "y";
  if (axes.vertical === null) return "x";
  const horizontalChange = Math.abs(input.requestedCanvasDelta.x / input.startBounds.width);
  const verticalChange = Math.abs(input.requestedCanvasDelta.y / input.startBounds.height);
  return horizontalChange >= verticalChange ? "x" : "y";
}

function resolveCandidate(
  input: StructuredPrototypeFreeformResizeSnapInput,
  rawBounds: StructuredPrototypeFreeformSnapBounds,
  target: ResizeSnapTarget,
): ResizeSnapCandidate | null {
  const rawCoordinate = activeCoordinate(rawBounds, target.axis, input);
  const distanceClient = Math.abs(target.coordinate - rawCoordinate) * input.previewScale;
  if (distanceClient > STRUCTURED_PROTOTYPE_FREEFORM_SNAP_THRESHOLD_CLIENT_PX) return null;
  const startCoordinate = activeCoordinate(input.startBounds, target.axis, input);
  const requestedCanvasDelta = { ...input.requestedCanvasDelta };
  if (target.axis === "x") {
    requestedCanvasDelta.x = target.coordinate - startCoordinate;
  } else {
    requestedCanvasDelta.y = target.coordinate - startCoordinate;
  }
  const bounds = resolveBounds(
    input,
    requestedCanvasDelta,
    input.lockAspectRatio ? target.axis : "auto",
  );
  if (!sameCoordinate(activeCoordinate(bounds, target.axis, input), target.coordinate)) return null;
  return { axis: target.axis, target, bounds, distanceClient };
}

function toGuide(
  input: StructuredPrototypeFreeformResizeSnapInput,
  candidate: ResizeSnapCandidate,
): StructuredPrototypeFreeformSnapGuide {
  return {
    axis: candidate.axis,
    coordinate: candidate.target.coordinate,
    movingAnchor: movingAnchor(candidate.axis, input),
    targetAnchor: candidate.target.anchor,
    targetKind: candidate.target.kind,
    targetNodeId: candidate.target.nodeId,
  };
}

function sortGuides(
  guides: readonly StructuredPrototypeFreeformSnapGuide[],
): readonly StructuredPrototypeFreeformSnapGuide[] {
  return [...guides].sort((left, right) => {
    if (left.axis === right.axis) return 0;
    return left.axis === "x" ? -1 : 1;
  });
}

/**
 * Snaps only the pointer-side edges represented by the active resize handle.
 * The caller freezes sibling geometry at pointerdown and uses this function for
 * both RAF previews and the exact pointerup event.
 */
export function resolveStructuredPrototypeFreeformResizeSnap(
  input: StructuredPrototypeFreeformResizeSnapInput,
): StructuredPrototypeFreeformResizeSnapResult {
  assertBounds(input.startBounds, "start bounds");
  assertFinite(input.requestedCanvasDelta.x, "requested delta x");
  assertFinite(input.requestedCanvasDelta.y, "requested delta y");
  assertPositive(input.minimumSize.width, "minimum width");
  assertPositive(input.minimumSize.height, "minimum height");
  assertPositive(input.maximumSize.width, "maximum width constraint");
  assertPositive(input.maximumSize.height, "maximum height constraint");
  assertPositive(input.containerWidth, "container width");
  assertPositive(input.containerHeight, "container height");
  assertPositive(input.previewScale, "preview scale");
  const selectedNodeIds = resolveSelectedNodeIds(input.selectedNodeIds);
  assertSiblings(input.directSiblings);
  const axes = resolveStructuredPrototypeResizeHandleAxes(input.direction);
  const rawBounds = resolveBounds(input, { ...input.requestedCanvasDelta }, "auto");
  if (input.bypassSnapping) return { bounds: rawBounds, guides: [] };

  const targets = buildTargets(input, selectedNodeIds).filter(
    (target) =>
      (target.axis === "x" && axes.horizontal !== null) ||
      (target.axis === "y" && axes.vertical !== null),
  );
  const candidates = targets.flatMap((target) => {
    const candidate = resolveCandidate(input, rawBounds, target);
    return candidate === null ? [] : [candidate];
  });

  if (input.lockAspectRatio) {
    if (candidates.length === 0) return { bounds: rawBounds, guides: [] };
    const preferredAspectDriver = resolveRawAspectDriver(input);
    const best = [...candidates].sort((left, right) =>
      compareCandidates(left, right, preferredAspectDriver),
    )[0];
    if (best === undefined) throw new Error("freeform resize snap lost its best candidate");
    const guides: StructuredPrototypeFreeformSnapGuide[] = [toGuide(input, best)];
    const otherAxis: StructuredPrototypeFreeformSnapAxis = best.axis === "x" ? "y" : "x";
    const otherAxisActive = otherAxis === "x" ? axes.horizontal !== null : axes.vertical !== null;
    if (otherAxisActive) {
      const derivedCoordinate = activeCoordinate(best.bounds, otherAxis, input);
      const exactTargets = targets
        .filter(
          (target) =>
            target.axis === otherAxis && sameCoordinate(target.coordinate, derivedCoordinate),
        )
        .map<ResizeSnapCandidate>((target) => ({
          axis: otherAxis,
          target,
          bounds: best.bounds,
          distanceClient: 0,
        }))
        .sort((left, right) => compareCandidates(left, right, null));
      const exactTarget = exactTargets[0];
      if (exactTarget !== undefined) guides.push(toGuide(input, exactTarget));
    }
    return { bounds: best.bounds, guides: sortGuides(guides) };
  }

  const horizontal = candidates
    .filter((candidate) => candidate.axis === "x")
    .sort((left, right) => compareCandidates(left, right, null))[0];
  const vertical = candidates
    .filter((candidate) => candidate.axis === "y")
    .sort((left, right) => compareCandidates(left, right, null))[0];
  if (horizontal === undefined && vertical === undefined) {
    return { bounds: rawBounds, guides: [] };
  }
  const requestedCanvasDelta = { ...input.requestedCanvasDelta };
  if (horizontal !== undefined) {
    requestedCanvasDelta.x =
      horizontal.target.coordinate - activeCoordinate(input.startBounds, "x", input);
  }
  if (vertical !== undefined) {
    requestedCanvasDelta.y =
      vertical.target.coordinate - activeCoordinate(input.startBounds, "y", input);
  }
  const bounds = resolveBounds(input, requestedCanvasDelta, "auto");
  const guides = [horizontal, vertical]
    .filter((candidate): candidate is ResizeSnapCandidate => candidate !== undefined)
    .filter((candidate) =>
      sameCoordinate(activeCoordinate(bounds, candidate.axis, input), candidate.target.coordinate),
    )
    .map((candidate) => toGuide(input, candidate));
  return { bounds, guides: sortGuides(guides) };
}
