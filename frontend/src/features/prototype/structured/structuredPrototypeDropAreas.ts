export interface StructuredPrototypeDropRect {
  top: number;
  right: number;
  bottom: number;
  left: number;
  width: number;
  height: number;
}

export interface StructuredPrototypeMeasuredChild {
  nodeId: string;
  index: number;
  rect: StructuredPrototypeDropRect;
}

export interface StructuredPrototypeMeasuredDropArea {
  key: string;
  targetIndex: number;
  rect: StructuredPrototypeDropRect;
  indicator: {
    direction: "horizontal" | "vertical";
    position: number;
    crossStart: number;
    crossEnd: number;
  };
}

interface StructuredPrototypeDropAreaInput {
  parentRect: StructuredPrototypeDropRect;
  children: readonly StructuredPrototypeMeasuredChild[];
  childCount: number;
  activeIndex: number | null;
  layout: "vertical" | "horizontal" | "grid";
}

interface GridRow {
  children: StructuredPrototypeMeasuredChild[];
  top: number;
  bottom: number;
}

function center(rect: StructuredPrototypeDropRect, axis: "horizontal" | "vertical"): number {
  return axis === "vertical" ? rect.top + rect.height / 2 : rect.left + rect.width / 2;
}

function dropRect(left: number, top: number, right: number, bottom: number) {
  return {
    left,
    top,
    right,
    bottom,
    width: Math.max(0, right - left),
    height: Math.max(0, bottom - top),
  };
}

function emptyDropArea(
  parentRect: StructuredPrototypeDropRect,
  childCount: number,
  activeIndex: number | null,
  direction: "horizontal" | "vertical",
): StructuredPrototypeMeasuredDropArea {
  return {
    key: "empty",
    targetIndex: activeIndex === null ? childCount : activeIndex + 1,
    rect: parentRect,
    indicator:
      direction === "vertical"
        ? {
            direction,
            position: parentRect.top,
            crossStart: parentRect.left,
            crossEnd: parentRect.right,
          }
        : {
            direction,
            position: parentRect.left,
            crossStart: parentRect.top,
            crossEnd: parentRect.bottom,
          },
  };
}

function targetIndexForVisualSlot(
  previous: StructuredPrototypeMeasuredChild | undefined,
  next: StructuredPrototypeMeasuredChild | undefined,
  childCount: number,
  activeIndex: number | null,
): number {
  const activeNodeOwnsSlot =
    activeIndex !== null &&
    (previous === undefined || previous.index < activeIndex) &&
    (next === undefined || activeIndex < next.index);
  return activeNodeOwnsSlot ? activeIndex + 1 : (next?.index ?? childCount);
}

function linearDropAreas(
  parentRect: StructuredPrototypeDropRect,
  children: readonly StructuredPrototypeMeasuredChild[],
  childCount: number,
  activeIndex: number | null,
  direction: "horizontal" | "vertical",
): StructuredPrototypeMeasuredDropArea[] {
  if (children.length === 0) {
    return [emptyDropArea(parentRect, childCount, activeIndex, direction)];
  }
  const areas: StructuredPrototypeMeasuredDropArea[] = [];
  for (let slot = 0; slot <= children.length; slot += 1) {
    const previous = children[slot - 1];
    const next = children[slot];
    const targetIndex = targetIndexForVisualSlot(previous, next, childCount, activeIndex);
    if (direction === "vertical") {
      const top = previous === undefined ? parentRect.top : center(previous.rect, direction);
      const bottom = next === undefined ? parentRect.bottom : center(next.rect, direction);
      areas.push({
        key: `linear-${slot}`,
        targetIndex,
        rect: dropRect(parentRect.left, top, parentRect.right, bottom),
        indicator: {
          direction,
          position: next?.rect.top ?? previous?.rect.bottom ?? parentRect.top,
          crossStart: parentRect.left,
          crossEnd: parentRect.right,
        },
      });
    } else {
      const left = previous === undefined ? parentRect.left : center(previous.rect, direction);
      const right = next === undefined ? parentRect.right : center(next.rect, direction);
      areas.push({
        key: `linear-${slot}`,
        targetIndex,
        rect: dropRect(left, parentRect.top, right, parentRect.bottom),
        indicator: {
          direction,
          position: next?.rect.left ?? previous?.rect.right ?? parentRect.left,
          crossStart: parentRect.top,
          crossEnd: parentRect.bottom,
        },
      });
    }
  }
  return areas;
}

function gridRows(children: readonly StructuredPrototypeMeasuredChild[]): GridRow[] {
  const rows: GridRow[] = [];
  for (const child of children) {
    const current = rows[rows.length - 1];
    if (
      current === undefined ||
      (child.rect.top >= current.bottom - 0.5 && Math.abs(child.rect.top - current.top) > 0.5)
    ) {
      rows.push({ children: [child], top: child.rect.top, bottom: child.rect.bottom });
      continue;
    }
    current.children.push(child);
    current.top = Math.min(current.top, child.rect.top);
    current.bottom = Math.max(current.bottom, child.rect.bottom);
  }
  return rows;
}

function gridDropAreas(
  parentRect: StructuredPrototypeDropRect,
  children: readonly StructuredPrototypeMeasuredChild[],
  childCount: number,
  activeIndex: number | null,
): StructuredPrototypeMeasuredDropArea[] {
  if (children.length === 0) {
    return [emptyDropArea(parentRect, childCount, activeIndex, "horizontal")];
  }
  const rows = gridRows(children);
  return rows.flatMap((row, rowIndex) => {
    const previousRow = rows[rowIndex - 1];
    const nextRow = rows[rowIndex + 1];
    const areaTop = previousRow === undefined ? parentRect.top : (previousRow.bottom + row.top) / 2;
    const areaBottom = nextRow === undefined ? parentRect.bottom : (row.bottom + nextRow.top) / 2;
    return row.children
      .map((child, childIndex) => {
        const previousInRow = row.children[childIndex - 1];
        const previousInSequence =
          previousInRow ?? previousRow?.children[previousRow.children.length - 1];
        return {
          key: `grid-${rowIndex}-${childIndex}`,
          targetIndex: targetIndexForVisualSlot(previousInSequence, child, childCount, activeIndex),
          rect: dropRect(
            previousInRow === undefined
              ? parentRect.left
              : center(previousInRow.rect, "horizontal"),
            areaTop,
            center(child.rect, "horizontal"),
            areaBottom,
          ),
          indicator: {
            direction: "horizontal" as const,
            position: child.rect.left,
            crossStart: row.top,
            crossEnd: row.bottom,
          },
        };
      })
      .concat({
        key: `grid-${rowIndex}-${row.children.length}`,
        targetIndex: targetIndexForVisualSlot(
          row.children[row.children.length - 1],
          nextRow?.children[0],
          childCount,
          activeIndex,
        ),
        rect: dropRect(
          center(row.children[row.children.length - 1]!.rect, "horizontal"),
          areaTop,
          parentRect.right,
          areaBottom,
        ),
        indicator: {
          direction: "horizontal" as const,
          position: row.children[row.children.length - 1]!.rect.right,
          crossStart: row.top,
          crossEnd: row.bottom,
        },
      });
  });
}

export function resolveStructuredPrototypeMeasuredDropAreas({
  parentRect,
  children,
  childCount,
  activeIndex,
  layout,
}: StructuredPrototypeDropAreaInput): StructuredPrototypeMeasuredDropArea[] {
  if (layout === "grid") return gridDropAreas(parentRect, children, childCount, activeIndex);
  return linearDropAreas(parentRect, children, childCount, activeIndex, layout);
}

export function sameStructuredPrototypeDropAreas(
  left: readonly StructuredPrototypeMeasuredDropArea[],
  right: readonly StructuredPrototypeMeasuredDropArea[],
): boolean {
  if (left.length !== right.length) return false;
  return left.every((area, index) => {
    const candidate = right[index];
    return (
      candidate !== undefined &&
      area.key === candidate.key &&
      area.targetIndex === candidate.targetIndex &&
      area.rect.top === candidate.rect.top &&
      area.rect.right === candidate.rect.right &&
      area.rect.bottom === candidate.rect.bottom &&
      area.rect.left === candidate.rect.left &&
      area.indicator.direction === candidate.indicator.direction &&
      area.indicator.position === candidate.indicator.position &&
      area.indicator.crossStart === candidate.indicator.crossStart &&
      area.indicator.crossEnd === candidate.indicator.crossEnd
    );
  });
}
