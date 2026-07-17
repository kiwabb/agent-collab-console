import type {
  StructuredPrototypeGridColumnOverride,
  StructuredPrototypeLayoutUpdate,
  StructuredPrototypeLength,
  StructuredPrototypeResponsiveOverride,
} from "./types";

export const STRUCTURED_PROTOTYPE_BREAKPOINTS = ["sm", "md", "lg"] as const;
export const STRUCTURED_PROTOTYPE_GRID_OVERRIDE_LIMIT = 3;
export const STRUCTURED_PROTOTYPE_LENGTH_UNITS = ["auto", "px", "percent", "rem"] as const;
const GRID_MIN_WIDTH_OPTIONS = [640, 768, 1024, 1280, 1440, 1920, 2560] as const;

export type StructuredPrototypeBreakpoint = (typeof STRUCTURED_PROTOTYPE_BREAKPOINTS)[number];

const BREAKPOINT_ORDER: Record<StructuredPrototypeBreakpoint, number> = {
  sm: 0,
  md: 1,
  lg: 2,
};

export function structuredPrototypeMaxLengthValue(unit: StructuredPrototypeLength["unit"]): number {
  if (unit === "percent") return 100;
  if (unit === "rem") return 256;
  return 4096;
}

export function defaultStructuredPrototypeLength(
  unit: StructuredPrototypeLength["unit"],
): StructuredPrototypeLength {
  if (unit === "auto") return { unit, value: null };
  if (unit === "percent") return { unit, value: "100" };
  if (unit === "rem") return { unit, value: "20" };
  return { unit, value: "320" };
}

export function canonicalStructuredPrototypeLengthValue(
  unit: StructuredPrototypeLength["unit"],
  rawValue: string | null,
): string | null {
  if (unit === "auto") return null;
  const numeric = Number(rawValue ?? 0);
  if (!Number.isFinite(numeric) || numeric < 0) return "0";
  const bounded = Math.min(numeric, structuredPrototypeMaxLengthValue(unit));
  return Number(bounded.toFixed(4)).toString();
}

export function updateStructuredPrototypeLengthUnit(
  current: StructuredPrototypeLength,
  unit: StructuredPrototypeLength["unit"],
): StructuredPrototypeLength {
  return { unit, value: canonicalStructuredPrototypeLengthValue(unit, current.value) };
}

export function updateStructuredPrototypeLengthValue(
  current: StructuredPrototypeLength,
  value: string,
): StructuredPrototypeLength {
  return {
    unit: current.unit,
    value: canonicalStructuredPrototypeLengthValue(current.unit, value),
  };
}

export function parseStructuredPrototypeLength(
  unit: StructuredPrototypeLength["unit"],
  rawValue: string,
): StructuredPrototypeLength | null {
  if (unit === "auto") return { unit, value: null };
  if (rawValue.trim() === "") return null;
  const numeric = Number(rawValue);
  if (
    !Number.isFinite(numeric) ||
    numeric < 0 ||
    numeric > structuredPrototypeMaxLengthValue(unit)
  ) {
    return null;
  }
  return { unit, value: Number(numeric.toFixed(4)).toString() };
}

export function parseStructuredPrototypeInteger(
  rawValue: string,
  minimum: number,
  maximum: number,
): number | null {
  if (rawValue.trim() === "") return null;
  const numeric = Number(rawValue);
  if (!Number.isSafeInteger(numeric) || numeric < minimum || numeric > maximum) return null;
  return numeric;
}

export function sortStructuredPrototypeResponsiveOverrides(
  overrides: readonly StructuredPrototypeResponsiveOverride[],
): StructuredPrototypeResponsiveOverride[] {
  return [...overrides].sort(
    (left, right) => BREAKPOINT_ORDER[left.breakpoint] - BREAKPOINT_ORDER[right.breakpoint],
  );
}

export function addStructuredPrototypeResponsiveOverride(
  overrides: readonly StructuredPrototypeResponsiveOverride[],
): StructuredPrototypeResponsiveOverride[] | null {
  const used = new Set(overrides.map((override) => override.breakpoint));
  const breakpoint = STRUCTURED_PROTOTYPE_BREAKPOINTS.find((candidate) => !used.has(candidate));
  if (breakpoint === undefined) return null;
  return sortStructuredPrototypeResponsiveOverrides([
    ...overrides,
    {
      breakpoint,
      layoutItem: { width: { unit: "percent", value: "100" } },
    },
  ]);
}

export function setStructuredPrototypeResponsiveBreakpoint(
  overrides: readonly StructuredPrototypeResponsiveOverride[],
  index: number,
  breakpoint: StructuredPrototypeBreakpoint,
): StructuredPrototypeResponsiveOverride[] | null {
  if (
    !Number.isSafeInteger(index) ||
    index < 0 ||
    index >= overrides.length ||
    overrides.some(
      (override, candidateIndex) => candidateIndex !== index && override.breakpoint === breakpoint,
    )
  ) {
    return null;
  }
  return sortStructuredPrototypeResponsiveOverrides(
    overrides.map((override, candidateIndex) =>
      candidateIndex === index ? { ...override, breakpoint } : override,
    ),
  );
}

export function setStructuredPrototypeResponsiveLayoutItem(
  overrides: readonly StructuredPrototypeResponsiveOverride[],
  index: number,
  layoutItem: StructuredPrototypeLayoutUpdate,
): StructuredPrototypeResponsiveOverride[] | null {
  if (
    !Number.isSafeInteger(index) ||
    index < 0 ||
    index >= overrides.length ||
    Object.keys(layoutItem).length === 0
  ) {
    return null;
  }
  return overrides.map((override, candidateIndex) =>
    candidateIndex === index ? { ...override, layoutItem } : override,
  );
}

export function setStructuredPrototypeResponsiveLayoutField<
  Field extends keyof StructuredPrototypeLayoutUpdate,
>(
  overrides: readonly StructuredPrototypeResponsiveOverride[],
  index: number,
  field: Field,
  value: StructuredPrototypeLayoutUpdate[Field] | undefined,
): StructuredPrototypeResponsiveOverride[] | null {
  const override = overrides[index];
  if (override === undefined) return null;
  const layoutItem: StructuredPrototypeLayoutUpdate = { ...override.layoutItem };
  if (value === undefined) {
    delete layoutItem[field];
  } else {
    Object.assign(layoutItem, { [field]: value });
  }
  if (Object.keys(layoutItem).length === 0) {
    return removeStructuredPrototypeResponsiveOverride(overrides, index);
  }
  return setStructuredPrototypeResponsiveLayoutItem(overrides, index, layoutItem);
}

export function removeStructuredPrototypeResponsiveOverride(
  overrides: readonly StructuredPrototypeResponsiveOverride[],
  index: number,
): StructuredPrototypeResponsiveOverride[] {
  return overrides.filter((_, candidateIndex) => candidateIndex !== index);
}

export function addStructuredPrototypeGridColumnOverride(
  overrides: readonly StructuredPrototypeGridColumnOverride[],
  baseColumns: number,
): StructuredPrototypeGridColumnOverride[] | null {
  if (overrides.length >= STRUCTURED_PROTOTYPE_GRID_OVERRIDE_LIMIT) return null;
  const sorted = [...overrides].sort((left, right) => left.minWidth - right.minWidth);
  const used = new Set(sorted.map((override) => override.minWidth));
  const last = sorted.at(-1);
  const minWidth =
    GRID_MIN_WIDTH_OPTIONS.find(
      (candidate) => !used.has(candidate) && (last === undefined || candidate > last.minWidth),
    ) ?? GRID_MIN_WIDTH_OPTIONS.find((candidate) => !used.has(candidate));
  if (minWidth === undefined) return null;
  const successor = sorted.find((override) => override.minWidth > minWidth);
  const columns =
    successor?.columns ?? Math.min(12, Math.max(1, (last?.columns ?? baseColumns) + 1));
  return [...sorted, { minWidth, columns }].sort((left, right) => left.minWidth - right.minWidth);
}

export function setStructuredPrototypeGridColumnOverride(
  overrides: readonly StructuredPrototypeGridColumnOverride[],
  index: number,
  update: StructuredPrototypeGridColumnOverride,
): StructuredPrototypeGridColumnOverride[] | null {
  if (
    !Number.isSafeInteger(index) ||
    index < 0 ||
    index >= overrides.length ||
    !Number.isSafeInteger(update.minWidth) ||
    update.minWidth < 320 ||
    update.minWidth > 2560 ||
    !Number.isSafeInteger(update.columns) ||
    update.columns < 1 ||
    update.columns > 12 ||
    overrides.some(
      (override, candidateIndex) =>
        candidateIndex !== index && override.minWidth === update.minWidth,
    )
  ) {
    return null;
  }
  return overrides
    .map((override, candidateIndex) => (candidateIndex === index ? update : override))
    .sort((left, right) => left.minWidth - right.minWidth);
}

export function removeStructuredPrototypeGridColumnOverride(
  overrides: readonly StructuredPrototypeGridColumnOverride[],
  index: number,
): StructuredPrototypeGridColumnOverride[] {
  return overrides.filter((_, candidateIndex) => candidateIndex !== index);
}
