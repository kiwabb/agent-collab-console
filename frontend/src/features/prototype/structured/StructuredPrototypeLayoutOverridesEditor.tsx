"use client";

import { useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";

import { useI18n } from "@/providers/I18nProvider";

import {
  STRUCTURED_PROTOTYPE_BREAKPOINTS,
  STRUCTURED_PROTOTYPE_GRID_OVERRIDE_LIMIT,
  STRUCTURED_PROTOTYPE_LENGTH_UNITS,
  addStructuredPrototypeGridColumnOverride,
  addStructuredPrototypeResponsiveOverride,
  defaultStructuredPrototypeLength,
  parseStructuredPrototypeInteger,
  parseStructuredPrototypeLength,
  removeStructuredPrototypeGridColumnOverride,
  removeStructuredPrototypeResponsiveOverride,
  setStructuredPrototypeGridColumnOverride,
  setStructuredPrototypeResponsiveBreakpoint,
  setStructuredPrototypeResponsiveLayoutField,
  structuredPrototypeMaxLengthValue,
  updateStructuredPrototypeLengthUnit,
  type StructuredPrototypeBreakpoint,
} from "./structuredPrototypeInspectorLayout";
import type {
  StructuredPrototypeGridColumnOverride,
  StructuredPrototypeLayoutUpdate,
  StructuredPrototypeLength,
  StructuredPrototypeResponsiveOverride,
} from "./types";

interface Props {
  responsive: StructuredPrototypeResponsiveOverride[];
  gridColumns: number | null;
  gridColumnOverrides: StructuredPrototypeGridColumnOverride[] | null;
  disabled: boolean;
  onResponsiveChange: (responsive: StructuredPrototypeResponsiveOverride[]) => void;
  onGridColumnOverridesChange: (columnOverrides: StructuredPrototypeGridColumnOverride[]) => void;
  onValidityChange: (valid: boolean) => void;
}

type ResponsiveLengthField =
  "width" | "minWidth" | "maxWidth" | "height" | "minHeight" | "maxHeight";

const RESPONSIVE_LENGTH_FIELDS: ReadonlyArray<{
  field: ResponsiveLengthField;
  label:
    | "prototype.structured.inspector.width"
    | "prototype.structured.inspector.minWidth"
    | "prototype.structured.inspector.maxWidth"
    | "prototype.structured.inspector.height"
    | "prototype.structured.inspector.minHeight"
    | "prototype.structured.inspector.maxHeight";
  nullable: boolean;
}> = [
  { field: "width", label: "prototype.structured.inspector.width", nullable: false },
  { field: "minWidth", label: "prototype.structured.inspector.minWidth", nullable: true },
  { field: "maxWidth", label: "prototype.structured.inspector.maxWidth", nullable: true },
  { field: "height", label: "prototype.structured.inspector.height", nullable: false },
  { field: "minHeight", label: "prototype.structured.inspector.minHeight", nullable: true },
  { field: "maxHeight", label: "prototype.structured.inspector.maxHeight", nullable: true },
];

const RESPONSIVE_INTEGER_FIELDS = ["grow", "shrink"] as const;

function isStructuredPrototypeLengthUnit(
  value: string,
): value is StructuredPrototypeLength["unit"] {
  return STRUCTURED_PROTOTYPE_LENGTH_UNITS.some((candidate) => candidate === value);
}

function isStructuredPrototypeBreakpoint(value: string): value is StructuredPrototypeBreakpoint {
  return STRUCTURED_PROTOTYPE_BREAKPOINTS.some((candidate) => candidate === value);
}

function isStructuredPrototypeAlignSelf(
  value: string,
): value is NonNullable<StructuredPrototypeLayoutUpdate["alignSelf"]> {
  return (
    value === "auto" ||
    value === "start" ||
    value === "center" ||
    value === "end" ||
    value === "stretch"
  );
}

function responsiveLengthMode(
  layoutItem: StructuredPrototypeLayoutUpdate,
  field: ResponsiveLengthField,
): "inherit" | "clear" | StructuredPrototypeLength["unit"] {
  const value = layoutItem[field];
  if (value === undefined) return "inherit";
  if (value === null) return "clear";
  return value.unit;
}

export function StructuredPrototypeLayoutOverridesEditor({
  responsive,
  gridColumns,
  gridColumnOverrides,
  disabled,
  onResponsiveChange,
  onGridColumnOverridesChange,
  onValidityChange,
}: Props) {
  const { t } = useI18n();
  const [rawInputs, setRawInputs] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    onValidityChange(Object.keys(errors).length === 0);
  }, [errors, onValidityChange]);

  function setFieldError(key: string, message: string | null): void {
    setErrors((current) => {
      const next = { ...current };
      if (message === null) delete next[key];
      else next[key] = message;
      return next;
    });
  }

  function clearFieldState(prefix: string): void {
    setRawInputs((current) =>
      Object.fromEntries(Object.entries(current).filter(([key]) => !key.startsWith(prefix))),
    );
    setErrors((current) =>
      Object.fromEntries(Object.entries(current).filter(([key]) => !key.startsWith(prefix))),
    );
  }

  function updateResponsiveField<Field extends keyof StructuredPrototypeLayoutUpdate>(
    index: number,
    field: Field,
    value: StructuredPrototypeLayoutUpdate[Field] | undefined,
  ): void {
    const next = setStructuredPrototypeResponsiveLayoutField(responsive, index, field, value);
    if (next === null) return;
    if (next.length < responsive.length) {
      const removed = responsive[index];
      if (removed !== undefined) clearFieldState(`responsive:${removed.breakpoint}:`);
    }
    onResponsiveChange(next);
  }

  function commitResponsiveLength(
    index: number,
    field: ResponsiveLengthField,
    length: StructuredPrototypeLength,
    inputKey: string,
  ): void {
    const rawValue = rawInputs[inputKey] ?? length.value ?? "";
    const parsed = parseStructuredPrototypeLength(length.unit, rawValue);
    if (parsed === null) {
      setFieldError(
        inputKey,
        t("prototype.structured.inspector.invalidLength", {
          max: String(structuredPrototypeMaxLengthValue(length.unit)),
        }),
      );
      return;
    }
    setFieldError(inputKey, null);
    setRawInputs((current) => {
      const next = { ...current };
      delete next[inputKey];
      return next;
    });
    updateResponsiveField(index, field, parsed);
  }

  function commitResponsiveInteger(
    index: number,
    field: (typeof RESPONSIVE_INTEGER_FIELDS)[number],
    inputKey: string,
  ): void {
    const rawValue = rawInputs[inputKey] ?? String(responsive[index]?.layoutItem[field] ?? "");
    const parsed = parseStructuredPrototypeInteger(rawValue, 0, 12);
    if (parsed === null) {
      setFieldError(
        inputKey,
        t("prototype.structured.inspector.invalidInteger", { min: "0", max: "12" }),
      );
      return;
    }
    setFieldError(inputKey, null);
    setRawInputs((current) => {
      const next = { ...current };
      delete next[inputKey];
      return next;
    });
    updateResponsiveField(index, field, parsed);
  }

  return (
    <div className="grid gap-4 border-t border-border-subtle pt-3">
      <section className="grid gap-3" data-structured-inspector-responsive-editor>
        <div className="flex items-center justify-between gap-2">
          <div className="text-[11px] font-bold text-text-secondary">
            {t("prototype.structured.inspector.responsiveLayout")}
          </div>
          <button
            type="button"
            className="inline-flex min-h-9 cursor-pointer items-center justify-center gap-1 rounded-md border border-border-muted bg-surface px-2 text-[11px] font-semibold text-foreground hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-45"
            onClick={() => {
              const next = addStructuredPrototypeResponsiveOverride(responsive);
              if (next !== null) onResponsiveChange(next);
            }}
            disabled={disabled || responsive.length >= STRUCTURED_PROTOTYPE_BREAKPOINTS.length}
          >
            <Plus size={13} aria-hidden />
            {t("prototype.structured.inspector.addBreakpoint")}
          </button>
        </div>

        {responsive.length === 0 && (
          <p className="border-l-2 border-border-muted pl-2 text-[11px] leading-4 text-text-muted">
            {t("prototype.structured.inspector.noResponsiveOverrides")}
          </p>
        )}

        {responsive.map((override, index) => {
          const rowPrefix = `responsive:${override.breakpoint}:`;
          return (
            <div
              key={override.breakpoint}
              className="grid gap-3 border-t border-border-subtle pt-3 first:border-t-0 first:pt-0"
              data-structured-responsive-breakpoint={override.breakpoint}
            >
              <div className="flex items-end gap-2">
                <label className="grid min-w-0 flex-1 gap-1 text-[11px] font-semibold text-text-secondary">
                  {t("prototype.structured.inspector.breakpoint")}
                  <select
                    className="min-h-9 cursor-pointer rounded-md border border-border-muted bg-surface-input px-2 text-xs font-normal text-foreground"
                    value={override.breakpoint}
                    onChange={(event) => {
                      const breakpoint = event.target.value;
                      if (!isStructuredPrototypeBreakpoint(breakpoint)) return;
                      const next = setStructuredPrototypeResponsiveBreakpoint(
                        responsive,
                        index,
                        breakpoint,
                      );
                      if (next !== null) {
                        clearFieldState(rowPrefix);
                        onResponsiveChange(next);
                      }
                    }}
                    disabled={disabled}
                  >
                    {STRUCTURED_PROTOTYPE_BREAKPOINTS.map((breakpoint) => (
                      <option
                        key={breakpoint}
                        value={breakpoint}
                        disabled={responsive.some(
                          (candidate) =>
                            candidate.breakpoint === breakpoint &&
                            candidate.breakpoint !== override.breakpoint,
                        )}
                      >
                        {t(`prototype.structured.inspector.breakpoint.${breakpoint}`)}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  className="inline-grid size-9 shrink-0 cursor-pointer place-items-center rounded-md text-error hover:bg-error/10 disabled:cursor-not-allowed disabled:opacity-45"
                  onClick={() => {
                    clearFieldState(rowPrefix);
                    onResponsiveChange(
                      removeStructuredPrototypeResponsiveOverride(responsive, index),
                    );
                  }}
                  disabled={disabled}
                  aria-label={t("prototype.structured.inspector.removeBreakpoint", {
                    breakpoint: override.breakpoint,
                  })}
                  title={t("prototype.structured.inspector.removeBreakpoint", {
                    breakpoint: override.breakpoint,
                  })}
                >
                  <Trash2 size={14} aria-hidden />
                </button>
              </div>

              <div className="grid grid-cols-2 gap-x-2 gap-y-3">
                {RESPONSIVE_LENGTH_FIELDS.map(({ field, label, nullable }) => {
                  const value = override.layoutItem[field];
                  const length = value === null || value === undefined ? null : value;
                  const mode = responsiveLengthMode(override.layoutItem, field);
                  const inputKey = `${rowPrefix}${field}`;
                  const error = errors[inputKey];
                  return (
                    <label
                      key={field}
                      className="grid min-w-0 gap-1 text-[11px] font-semibold text-text-secondary"
                    >
                      {t(label)}
                      <select
                        className="min-h-9 cursor-pointer rounded-md border border-border-muted bg-surface-input px-2 text-xs font-normal text-foreground"
                        value={mode}
                        onChange={(event) => {
                          const nextMode = event.target.value;
                          clearFieldState(inputKey);
                          if (nextMode === "inherit") {
                            updateResponsiveField(index, field, undefined);
                            return;
                          }
                          if (nextMode === "clear" && nullable) {
                            updateResponsiveField(index, field, null);
                            return;
                          }
                          if (!isStructuredPrototypeLengthUnit(nextMode)) return;
                          const nextLength =
                            length === null
                              ? defaultStructuredPrototypeLength(nextMode)
                              : updateStructuredPrototypeLengthUnit(length, nextMode);
                          updateResponsiveField(index, field, nextLength);
                        }}
                        disabled={disabled}
                        aria-label={`${t(label)} ${t("prototype.structured.inspector.unit")}`}
                      >
                        <option value="inherit">
                          {t("prototype.structured.inspector.inherit")}
                        </option>
                        {nullable && (
                          <option value="clear">
                            {t("prototype.structured.inspector.clearConstraint")}
                          </option>
                        )}
                        {STRUCTURED_PROTOTYPE_LENGTH_UNITS.map((unit) => (
                          <option key={unit} value={unit}>
                            {t(`prototype.structured.inspector.unit.${unit}`)}
                          </option>
                        ))}
                      </select>
                      <input
                        className="min-h-9 min-w-0 rounded-md border border-border-muted bg-surface-input px-2 text-xs font-normal text-foreground outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 disabled:opacity-45 aria-invalid:border-error"
                        type="number"
                        min={0}
                        max={length ? structuredPrototypeMaxLengthValue(length.unit) : 0}
                        step={length?.unit === "px" ? 1 : 0.25}
                        value={rawInputs[inputKey] ?? length?.value ?? ""}
                        onChange={(event) => {
                          const rawValue = event.target.value;
                          setRawInputs((current) => ({ ...current, [inputKey]: rawValue }));
                          if (length === null || length.unit === "auto") return;
                          if (parseStructuredPrototypeLength(length.unit, rawValue) === null) {
                            setFieldError(
                              inputKey,
                              t("prototype.structured.inspector.invalidLength", {
                                max: String(structuredPrototypeMaxLengthValue(length.unit)),
                              }),
                            );
                            return;
                          }
                          setFieldError(inputKey, null);
                        }}
                        onBlur={() => {
                          if (length !== null && length.unit !== "auto") {
                            commitResponsiveLength(index, field, length, inputKey);
                          }
                        }}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" && length !== null && length.unit !== "auto") {
                            event.preventDefault();
                            commitResponsiveLength(index, field, length, inputKey);
                          }
                        }}
                        disabled={disabled || length === null || length.unit === "auto"}
                        aria-label={t(label)}
                        aria-invalid={error !== undefined}
                        aria-describedby={error === undefined ? undefined : `${inputKey}-error`}
                      />
                      {error !== undefined && (
                        <span
                          id={`${inputKey}-error`}
                          className="text-[10px] font-medium leading-4 text-error"
                          role="alert"
                        >
                          {error}
                        </span>
                      )}
                    </label>
                  );
                })}
              </div>

              <div className="grid grid-cols-2 gap-2">
                {RESPONSIVE_INTEGER_FIELDS.map((field) => {
                  const value = override.layoutItem[field];
                  const inputKey = `${rowPrefix}${field}`;
                  const error = errors[inputKey];
                  return (
                    <label
                      key={field}
                      className="grid min-w-0 gap-1 text-[11px] font-semibold text-text-secondary"
                    >
                      {t(`prototype.structured.inspector.${field}`)}
                      <select
                        className="min-h-9 cursor-pointer rounded-md border border-border-muted bg-surface-input px-2 text-xs font-normal text-foreground"
                        value={value === undefined ? "inherit" : "value"}
                        onChange={(event) => {
                          clearFieldState(inputKey);
                          updateResponsiveField(
                            index,
                            field,
                            event.target.value === "inherit" ? undefined : (value ?? 0),
                          );
                        }}
                        disabled={disabled}
                        aria-label={`${t(`prototype.structured.inspector.${field}`)} ${t("prototype.structured.inspector.override")}`}
                      >
                        <option value="inherit">
                          {t("prototype.structured.inspector.inherit")}
                        </option>
                        <option value="value">
                          {t("prototype.structured.inspector.override")}
                        </option>
                      </select>
                      <input
                        className="min-h-9 min-w-0 rounded-md border border-border-muted bg-surface-input px-2 text-xs font-normal text-foreground outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 disabled:opacity-45 aria-invalid:border-error"
                        type="number"
                        min={0}
                        max={12}
                        step={1}
                        value={rawInputs[inputKey] ?? value ?? ""}
                        onChange={(event) => {
                          const rawValue = event.target.value;
                          setRawInputs((current) => ({ ...current, [inputKey]: rawValue }));
                          if (parseStructuredPrototypeInteger(rawValue, 0, 12) === null) {
                            setFieldError(
                              inputKey,
                              t("prototype.structured.inspector.invalidInteger", {
                                min: "0",
                                max: "12",
                              }),
                            );
                            return;
                          }
                          setFieldError(inputKey, null);
                        }}
                        onBlur={() => commitResponsiveInteger(index, field, inputKey)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") {
                            event.preventDefault();
                            commitResponsiveInteger(index, field, inputKey);
                          }
                        }}
                        disabled={disabled || value === undefined}
                        aria-label={t(`prototype.structured.inspector.${field}`)}
                        aria-invalid={error !== undefined}
                      />
                      {error !== undefined && (
                        <span className="text-[10px] font-medium leading-4 text-error" role="alert">
                          {error}
                        </span>
                      )}
                    </label>
                  );
                })}

                <label className="col-span-2 grid gap-1 text-[11px] font-semibold text-text-secondary">
                  {t("prototype.structured.inspector.alignSelf")}
                  <select
                    className="min-h-9 cursor-pointer rounded-md border border-border-muted bg-surface-input px-2 text-xs font-normal text-foreground"
                    value={override.layoutItem.alignSelf ?? "inherit"}
                    onChange={(event) => {
                      const value = event.target.value;
                      if (value !== "inherit" && !isStructuredPrototypeAlignSelf(value)) return;
                      updateResponsiveField(
                        index,
                        "alignSelf",
                        value === "inherit" ? undefined : value,
                      );
                    }}
                    disabled={disabled}
                  >
                    <option value="inherit">{t("prototype.structured.inspector.inherit")}</option>
                    {(["auto", "start", "center", "end", "stretch"] as const).map((value) => (
                      <option key={value} value={value}>
                        {t(`prototype.structured.inspector.alignSelf.${value}`)}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </div>
          );
        })}
      </section>

      {gridColumnOverrides !== null && gridColumns !== null && (
        <section
          className="grid gap-3 border-t border-border-subtle pt-3"
          data-structured-inspector-grid-overrides
        >
          <div className="flex items-center justify-between gap-2">
            <div className="text-[11px] font-bold text-text-secondary">
              {t("prototype.structured.inspector.gridOverrides")}
            </div>
            <button
              type="button"
              className="inline-flex min-h-9 cursor-pointer items-center justify-center gap-1 rounded-md border border-border-muted bg-surface px-2 text-[11px] font-semibold text-foreground hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-45"
              onClick={() => {
                const next = addStructuredPrototypeGridColumnOverride(
                  gridColumnOverrides,
                  gridColumns,
                );
                if (next !== null) onGridColumnOverridesChange(next);
              }}
              disabled={
                disabled || gridColumnOverrides.length >= STRUCTURED_PROTOTYPE_GRID_OVERRIDE_LIMIT
              }
            >
              <Plus size={13} aria-hidden />
              {t("prototype.structured.inspector.addGridOverride")}
            </button>
          </div>

          {gridColumnOverrides.map((override, index) => {
            const rowPrefix = `grid:${override.minWidth}:`;
            const widthKey = `${rowPrefix}minWidth`;
            const columnsKey = `${rowPrefix}columns`;
            return (
              <div
                key={`${override.minWidth}-${index}`}
                className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_36px] items-start gap-2"
                data-structured-grid-override={override.minWidth}
              >
                <label className="grid min-w-0 gap-1 text-[11px] font-semibold text-text-secondary">
                  {t("prototype.structured.inspector.minViewportWidth")}
                  <input
                    className="min-h-9 min-w-0 rounded-md border border-border-muted bg-surface-input px-2 text-xs font-normal text-foreground outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 aria-invalid:border-error"
                    type="number"
                    min={320}
                    max={2560}
                    step={1}
                    value={rawInputs[widthKey] ?? override.minWidth}
                    onChange={(event) => {
                      const rawValue = event.target.value;
                      setRawInputs((current) => ({ ...current, [widthKey]: rawValue }));
                      const minWidth = parseStructuredPrototypeInteger(rawValue, 320, 2560);
                      if (minWidth === null) {
                        setFieldError(
                          widthKey,
                          t("prototype.structured.inspector.invalidInteger", {
                            min: "320",
                            max: "2560",
                          }),
                        );
                        return;
                      }
                      if (
                        gridColumnOverrides.some(
                          (candidate, candidateIndex) =>
                            candidateIndex !== index && candidate.minWidth === minWidth,
                        )
                      ) {
                        setFieldError(
                          widthKey,
                          t("prototype.structured.inspector.duplicateGridWidth"),
                        );
                        return;
                      }
                      setFieldError(widthKey, null);
                    }}
                    onBlur={() => {
                      const rawValue = rawInputs[widthKey] ?? String(override.minWidth);
                      const minWidth = parseStructuredPrototypeInteger(rawValue, 320, 2560);
                      if (minWidth === null) return;
                      const next = setStructuredPrototypeGridColumnOverride(
                        gridColumnOverrides,
                        index,
                        { ...override, minWidth },
                      );
                      if (next === null) return;
                      clearFieldState(rowPrefix);
                      onGridColumnOverridesChange(next);
                    }}
                    onKeyDown={(event) => {
                      if (event.key !== "Enter") return;
                      event.preventDefault();
                      const rawValue = rawInputs[widthKey] ?? String(override.minWidth);
                      const minWidth = parseStructuredPrototypeInteger(rawValue, 320, 2560);
                      if (minWidth === null) return;
                      const next = setStructuredPrototypeGridColumnOverride(
                        gridColumnOverrides,
                        index,
                        { ...override, minWidth },
                      );
                      if (next === null) return;
                      clearFieldState(rowPrefix);
                      onGridColumnOverridesChange(next);
                    }}
                    disabled={disabled}
                    aria-invalid={errors[widthKey] !== undefined}
                  />
                  {errors[widthKey] !== undefined && (
                    <span className="text-[10px] font-medium leading-4 text-error" role="alert">
                      {errors[widthKey]}
                    </span>
                  )}
                </label>
                <label className="grid min-w-0 gap-1 text-[11px] font-semibold text-text-secondary">
                  {t("prototype.structured.inspector.columns")}
                  <input
                    className="min-h-9 min-w-0 rounded-md border border-border-muted bg-surface-input px-2 text-xs font-normal text-foreground outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 aria-invalid:border-error"
                    type="number"
                    min={1}
                    max={12}
                    step={1}
                    value={rawInputs[columnsKey] ?? override.columns}
                    onChange={(event) => {
                      const rawValue = event.target.value;
                      setRawInputs((current) => ({ ...current, [columnsKey]: rawValue }));
                      const columns = parseStructuredPrototypeInteger(rawValue, 1, 12);
                      if (columns === null) {
                        setFieldError(
                          columnsKey,
                          t("prototype.structured.inspector.invalidInteger", {
                            min: "1",
                            max: "12",
                          }),
                        );
                        return;
                      }
                      setFieldError(columnsKey, null);
                    }}
                    onBlur={() => {
                      const rawValue = rawInputs[columnsKey] ?? String(override.columns);
                      const columns = parseStructuredPrototypeInteger(rawValue, 1, 12);
                      if (columns === null) return;
                      const next = setStructuredPrototypeGridColumnOverride(
                        gridColumnOverrides,
                        index,
                        { ...override, columns },
                      );
                      if (next === null) return;
                      setRawInputs((current) => {
                        const nextRaw = { ...current };
                        delete nextRaw[columnsKey];
                        return nextRaw;
                      });
                      onGridColumnOverridesChange(next);
                    }}
                    onKeyDown={(event) => {
                      if (event.key !== "Enter") return;
                      event.preventDefault();
                      const rawValue = rawInputs[columnsKey] ?? String(override.columns);
                      const columns = parseStructuredPrototypeInteger(rawValue, 1, 12);
                      if (columns === null) return;
                      const next = setStructuredPrototypeGridColumnOverride(
                        gridColumnOverrides,
                        index,
                        { ...override, columns },
                      );
                      if (next === null) return;
                      setRawInputs((current) => {
                        const nextRaw = { ...current };
                        delete nextRaw[columnsKey];
                        return nextRaw;
                      });
                      onGridColumnOverridesChange(next);
                    }}
                    disabled={disabled}
                    aria-invalid={errors[columnsKey] !== undefined}
                  />
                  {errors[columnsKey] !== undefined && (
                    <span className="text-[10px] font-medium leading-4 text-error" role="alert">
                      {errors[columnsKey]}
                    </span>
                  )}
                </label>
                <button
                  type="button"
                  className="mt-5 inline-grid size-9 cursor-pointer place-items-center rounded-md text-error hover:bg-error/10 disabled:cursor-not-allowed disabled:opacity-45"
                  onClick={() => {
                    clearFieldState(rowPrefix);
                    onGridColumnOverridesChange(
                      removeStructuredPrototypeGridColumnOverride(gridColumnOverrides, index),
                    );
                  }}
                  disabled={disabled}
                  aria-label={t("prototype.structured.inspector.removeGridOverride", {
                    width: String(override.minWidth),
                  })}
                  title={t("prototype.structured.inspector.removeGridOverride", {
                    width: String(override.minWidth),
                  })}
                >
                  <Trash2 size={14} aria-hidden />
                </button>
              </div>
            );
          })}
        </section>
      )}
    </div>
  );
}
