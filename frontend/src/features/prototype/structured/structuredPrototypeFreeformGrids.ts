import type { StructuredPrototypeFreeformGrid, StructuredPrototypeFreeformNode } from "./types";

const EMPTY_STRUCTURED_PROTOTYPE_FREEFORM_GRIDS: readonly StructuredPrototypeFreeformGrid[] = [];

/**
 * Missing and empty grids have identical editor semantics. The missing form must
 * remain absent from canonical JSON so historical document hashes still replay.
 */
export function resolveStructuredPrototypeFreeformGrids(
  node: StructuredPrototypeFreeformNode,
): readonly StructuredPrototypeFreeformGrid[] {
  return node.grids ?? EMPTY_STRUCTURED_PROTOTYPE_FREEFORM_GRIDS;
}

export function cloneStructuredPrototypeFreeformGrids(
  grids: readonly StructuredPrototypeFreeformGrid[],
): StructuredPrototypeFreeformGrid[] {
  return grids.map((grid) =>
    grid.type === "square"
      ? {
          ...grid,
          origin: { ...grid.origin },
          params: { ...grid.params },
        }
      : {
          ...grid,
          origin: { ...grid.origin },
          params: { ...grid.params },
        },
  );
}
