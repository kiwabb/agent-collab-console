import type {
  StructuredPrototypeFreeformSnapAnchor,
  StructuredPrototypeFreeformSnapAxis,
  StructuredPrototypeFreeformSnapGuide,
  StructuredPrototypeFreeformSnapPoint,
  StructuredPrototypeFreeformSnapTargetKind,
} from "./structuredPrototypeSnapping";
import type { StructuredPrototypeFreeformGrid } from "./types";
import {
  structuredPrototypeFreeformSpacingLengthsMatch,
  type StructuredPrototypeFreeformSpacingGuide,
} from "./structuredPrototypeSpacingSnapping";

export interface StructuredPrototypeFreeformSnapGuideProjectionInput {
  readonly freeformOrigin: Readonly<StructuredPrototypeFreeformSnapPoint>;
  readonly containerWidth: number;
  readonly containerHeight: number;
  readonly previewScale: number;
  readonly guides: readonly StructuredPrototypeFreeformSnapGuide[];
}

export interface StructuredPrototypeFreeformSnapGuideOverlayFrame {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

export interface StructuredPrototypeFreeformSnapGuideOverlay {
  readonly frame: StructuredPrototypeFreeformSnapGuideOverlayFrame;
  readonly guides: readonly StructuredPrototypeFreeformSnapGuide[];
  readonly spacingGuides: readonly StructuredPrototypeFreeformSpacingGuide[];
  readonly previewScale: number;
}

export interface StructuredPrototypeFreeformSnapGuideProjection {
  readonly axis: StructuredPrototypeFreeformSnapAxis;
  readonly left: number;
  readonly top: number;
  readonly width: number;
  readonly height: number;
  readonly movingAnchor: StructuredPrototypeFreeformSnapAnchor;
  readonly targetAnchor: StructuredPrototypeFreeformSnapAnchor;
  readonly targetKind: StructuredPrototypeFreeformSnapTargetKind;
  readonly targetNodeId: string | null;
  readonly gridId?: string;
  readonly gridType?: StructuredPrototypeFreeformGrid["type"];
  readonly gridLineIndex?: number;
}

export interface StructuredPrototypeFreeformSpacingGuideProjectionInput {
  readonly freeformOrigin: Readonly<StructuredPrototypeFreeformSnapPoint>;
  readonly previewScale: number;
  readonly guides: readonly StructuredPrototypeFreeformSpacingGuide[];
}

type StructuredPrototypeFreeformSpacingGuideSegment =
  StructuredPrototypeFreeformSpacingGuide["segments"][number];

export interface StructuredPrototypeFreeformSpacingGuideProjection {
  readonly axis: StructuredPrototypeFreeformSnapAxis;
  readonly left: number;
  readonly top: number;
  readonly width: number;
  readonly height: number;
  readonly capThickness: number;
  readonly capLength: number;
  readonly gap: number;
  readonly placement: StructuredPrototypeFreeformSpacingGuide["placement"];
  readonly referenceNodeIds: StructuredPrototypeFreeformSpacingGuide["referenceNodeIds"];
  readonly fromNodeId: StructuredPrototypeFreeformSpacingGuideSegment["fromNodeId"];
  readonly toNodeId: StructuredPrototypeFreeformSpacingGuideSegment["toNodeId"];
  readonly segmentIndex: StructuredPrototypeFreeformSpacingGuideSegment["segmentIndex"];
}

function assertFinite(value: number, label: string): void {
  if (!Number.isFinite(value)) throw new Error(`snap guide ${label} must be finite`);
}

function assertPositive(value: number, label: string): void {
  assertFinite(value, label);
  if (value <= 0) throw new Error(`snap guide ${label} must be positive`);
}

function assertGuideAxis(axis: StructuredPrototypeFreeformSnapAxis): void {
  if (axis !== "x" && axis !== "y") {
    throw new Error("snap guide axis must be x or y");
  }
}

function assertSpacingSegmentLength(segmentLength: number, gap: number): void {
  assertFinite(segmentLength, "spacing segment length");
  if (!structuredPrototypeFreeformSpacingLengthsMatch(segmentLength, gap)) {
    throw new Error("snap guide spacing segment length must match gap");
  }
}

export function projectStructuredPrototypeFreeformSnapGuides({
  freeformOrigin,
  containerWidth,
  containerHeight,
  previewScale,
  guides,
}: StructuredPrototypeFreeformSnapGuideProjectionInput): readonly StructuredPrototypeFreeformSnapGuideProjection[] {
  assertFinite(freeformOrigin.x, "freeform origin x");
  assertFinite(freeformOrigin.y, "freeform origin y");
  assertPositive(containerWidth, "container width");
  assertPositive(containerHeight, "container height");
  assertPositive(previewScale, "preview scale");
  const thickness = 1 / previewScale;
  assertPositive(thickness, "inverse preview scale");

  return guides.map((guide) => {
    assertGuideAxis(guide.axis);
    assertFinite(guide.coordinate, "coordinate");
    const vertical = guide.axis === "x";
    const left = freeformOrigin.x + (vertical ? guide.coordinate : 0);
    const top = freeformOrigin.y + (vertical ? 0 : guide.coordinate);
    assertFinite(left, "projected left");
    assertFinite(top, "projected top");
    return {
      axis: guide.axis,
      left,
      top,
      width: vertical ? thickness : containerWidth,
      height: vertical ? containerHeight : thickness,
      movingAnchor: guide.movingAnchor,
      targetAnchor: guide.targetAnchor,
      targetKind: guide.targetKind,
      targetNodeId: guide.targetNodeId,
      ...(guide.gridId === undefined ? {} : { gridId: guide.gridId }),
      ...(guide.gridType === undefined ? {} : { gridType: guide.gridType }),
      ...(guide.gridLineIndex === undefined ? {} : { gridLineIndex: guide.gridLineIndex }),
    };
  });
}

export function projectStructuredPrototypeFreeformSpacingGuides({
  freeformOrigin,
  previewScale,
  guides,
}: StructuredPrototypeFreeformSpacingGuideProjectionInput): readonly StructuredPrototypeFreeformSpacingGuideProjection[] {
  assertFinite(freeformOrigin.x, "spacing freeform origin x");
  assertFinite(freeformOrigin.y, "spacing freeform origin y");
  assertPositive(previewScale, "spacing preview scale");
  const thickness = 1 / previewScale;
  const capLength = 6 / previewScale;
  assertPositive(thickness, "spacing inverse preview scale");
  assertPositive(capLength, "spacing cap length");

  const projections: StructuredPrototypeFreeformSpacingGuideProjection[] = [];
  for (const guide of guides) {
    assertGuideAxis(guide.axis);
    assertPositive(guide.gap, "spacing gap");
    const horizontal = guide.axis === "x";

    for (const segment of guide.segments) {
      assertFinite(segment.start, "spacing segment start");
      assertFinite(segment.end, "spacing segment end");
      assertFinite(segment.crossCoordinate, "spacing segment cross coordinate");
      assertFinite(segment.segmentIndex, "spacing segment index");
      if (segment.end <= segment.start) {
        throw new Error("snap guide spacing segment end must be greater than start");
      }

      const segmentLength = segment.end - segment.start;
      assertSpacingSegmentLength(segmentLength, guide.gap);
      const left = freeformOrigin.x + (horizontal ? segment.start : segment.crossCoordinate);
      const top = freeformOrigin.y + (horizontal ? segment.crossCoordinate : segment.start);
      const width = horizontal ? segmentLength : thickness;
      const height = horizontal ? thickness : segmentLength;
      assertFinite(left, "spacing projected left");
      assertFinite(top, "spacing projected top");
      assertPositive(width, "spacing projected width");
      assertPositive(height, "spacing projected height");

      projections.push({
        axis: guide.axis,
        left,
        top,
        width,
        height,
        capThickness: thickness,
        capLength,
        gap: guide.gap,
        placement: guide.placement,
        referenceNodeIds: guide.referenceNodeIds,
        fromNodeId: segment.fromNodeId,
        toNodeId: segment.toNodeId,
        segmentIndex: segment.segmentIndex,
      });
    }
  }

  return projections;
}
