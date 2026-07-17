"use client";

import type { CSSProperties } from "react";

import {
  resolveStructuredPrototypeFreeformGridGeometries,
  type StructuredPrototypeFreeformGridGeometry,
} from "./structuredPrototypeGridGeometry";
import { resolveStructuredPrototypeFreeformGrids } from "./structuredPrototypeFreeformGrids";
import type { StructuredPrototypeFreeformGrid, StructuredPrototypeFreeformNode } from "./types";

const MIN_SQUARE_GRID_SCREEN_SPACING = 4;

interface Props {
  node: StructuredPrototypeFreeformNode;
  width: number;
  height: number;
  previewScale: number;
  colorTokens: Array<{ key: string; value: string }>;
}

function resolveGridColor(
  grid: Readonly<StructuredPrototypeFreeformGrid>,
  colorTokens: ReadonlyMap<string, string>,
): string {
  const color = colorTokens.get(grid.params.colorTokenKey);
  if (color === undefined) {
    throw new Error(`Freeform grid ${grid.id} references a missing color token`);
  }
  return color;
}

function squareGridStyle(
  geometry: Extract<StructuredPrototypeFreeformGridGeometry, { type: "square" }>,
  color: string,
  opacity: number,
  previewScale: number,
): CSSProperties & Record<"--prototype-grid-color", string> {
  const lineThickness = 1 / previewScale;
  const lodStep = Math.max(
    1,
    Math.ceil(MIN_SQUARE_GRID_SCREEN_SPACING / (geometry.size * previewScale)),
  );
  const patternSize = geometry.size * lodStep;
  return {
    "--prototype-grid-color": color,
    left: geometry.clip.x,
    top: geometry.clip.y,
    width: geometry.clip.width,
    height: geometry.clip.height,
    opacity,
    backgroundImage: [
      `linear-gradient(to right, var(--prototype-grid-color) 0, var(--prototype-grid-color) ${lineThickness}px, transparent ${lineThickness}px)`,
      `linear-gradient(to bottom, var(--prototype-grid-color) 0, var(--prototype-grid-color) ${lineThickness}px, transparent ${lineThickness}px)`,
    ].join(","),
    backgroundSize: `${patternSize}px ${patternSize}px`,
  };
}

function TrackGridLayer({
  geometry,
  grid,
  color,
  previewScale,
}: {
  geometry: Extract<StructuredPrototypeFreeformGridGeometry, { type: "columns" | "rows" }>;
  grid: Extract<StructuredPrototypeFreeformGrid, { type: "columns" | "rows" }>;
  color: string;
  previewScale: number;
}) {
  const opacity = Number(grid.params.opacity);
  const gutter = Number(grid.params.gutter);
  const lineThickness = 1 / previewScale;
  if (gutter > 0) {
    return geometry.areas.map((area) => (
      <span
        key={`${grid.id}:${area.index}`}
        className="absolute"
        style={{
          left: area.x,
          top: area.y,
          width: area.width,
          height: area.height,
          backgroundColor: color,
          opacity,
        }}
        data-prototype-layout-grid-track={area.index}
      />
    ));
  }
  return geometry.areas.flatMap((area) => {
    const vertical = geometry.type === "columns";
    const start = vertical ? area.x : area.y;
    const end = start + (vertical ? area.width : area.height);
    return [start, end].map((coordinate, boundaryIndex) => (
      <span
        key={`${grid.id}:${area.index}:${boundaryIndex}`}
        className="absolute"
        style={
          vertical
            ? {
                left: coordinate,
                top: geometry.clip.y,
                width: lineThickness,
                height: geometry.clip.height,
                backgroundColor: color,
                opacity,
              }
            : {
                left: geometry.clip.x,
                top: coordinate,
                width: geometry.clip.width,
                height: lineThickness,
                backgroundColor: color,
                opacity,
              }
        }
        data-prototype-layout-grid-boundary={`${area.index}:${boundaryIndex}`}
      />
    ));
  });
}

export function StructuredPrototypeFreeformGridOverlay({
  node,
  width,
  height,
  previewScale,
  colorTokens,
}: Props) {
  const grids = resolveStructuredPrototypeFreeformGrids(node);
  if (grids.length === 0) return null;
  const geometries = resolveStructuredPrototypeFreeformGridGeometries({
    frame: { width, height },
    grids,
  });
  if (geometries.length === 0) return null;
  const gridsById = new Map(grids.map((grid) => [grid.id, grid]));
  const colorsByKey = new Map(colorTokens.map((token) => [token.key, token.value]));

  return (
    <div
      className="pointer-events-none absolute inset-0 z-0 overflow-hidden"
      aria-hidden
      data-prototype-layout-grid-overlay={node.id}
      data-prototype-layout-grid-count={geometries.length}
    >
      {geometries.map((geometry) => {
        const grid = gridsById.get(geometry.gridId);
        if (grid === undefined) {
          throw new Error(`Freeform grid geometry ${geometry.gridId} has no source grid`);
        }
        const color = resolveGridColor(grid, colorsByKey);
        if (geometry.type === "square" && grid.type === "square") {
          const lodStep = Math.max(
            1,
            Math.ceil(MIN_SQUARE_GRID_SCREEN_SPACING / (geometry.size * previewScale)),
          );
          return (
            <span
              key={grid.id}
              className="absolute"
              style={squareGridStyle(geometry, color, Number(grid.params.opacity), previewScale)}
              data-prototype-layout-grid={grid.id}
              data-prototype-layout-grid-type={grid.type}
              data-prototype-layout-grid-lod-step={lodStep}
            />
          );
        }
        if (geometry.type !== "square" && grid.type !== "square") {
          return (
            <div
              key={grid.id}
              className="absolute inset-0"
              data-prototype-layout-grid={grid.id}
              data-prototype-layout-grid-type={grid.type}
            >
              <TrackGridLayer
                geometry={geometry}
                grid={grid}
                color={color}
                previewScale={previewScale}
              />
            </div>
          );
        }
        throw new Error(`Freeform grid geometry type drifted for ${grid.id}`);
      })}
    </div>
  );
}
