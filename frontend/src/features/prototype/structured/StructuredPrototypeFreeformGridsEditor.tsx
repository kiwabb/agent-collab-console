"use client";

import { ArrowDown, ArrowUp, Eye, EyeOff, Magnet, Plus, Trash2 } from "lucide-react";

import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

import { canonicalStructuredPrototypeFreeformValue } from "./structuredPrototypeFreeformGeometry";
import type { StructuredPrototypeAxisGrid, StructuredPrototypeFreeformGrid } from "./types";

const MAX_FREEFORM_GRIDS = 8;

interface Props {
  grids: StructuredPrototypeFreeformGrid[];
  colorTokens: Array<{ key: string; value: string }>;
  disabled: boolean;
  onChange: (grids: StructuredPrototypeFreeformGrid[]) => void;
}

export function createDefaultStructuredPrototypeFreeformGrid(
  id: string,
  type: StructuredPrototypeFreeformGrid["type"],
  colorTokenKey: string,
): StructuredPrototypeFreeformGrid {
  const common = {
    id,
    version: 1 as const,
    visible: true,
    snapEnabled: true,
    origin: { x: "0", y: "0" },
  };
  if (type === "square") {
    return {
      ...common,
      type,
      params: { size: "16", colorTokenKey, opacity: "0.4" },
    };
  }
  return {
    ...common,
    type,
    params: {
      count: 12,
      itemSize: null,
      gutter: "8",
      margin: "0",
      alignment: "stretch",
      colorTokenKey,
      opacity: "0.1",
    },
  };
}

export function changeStructuredPrototypeFreeformGridType(
  grid: StructuredPrototypeFreeformGrid,
  type: StructuredPrototypeFreeformGrid["type"],
): StructuredPrototypeFreeformGrid {
  if (grid.type === type) return grid;
  const replacement = createDefaultStructuredPrototypeFreeformGrid(
    grid.id,
    type,
    grid.params.colorTokenKey,
  );
  return {
    ...replacement,
    id: grid.id,
    version: grid.version,
    visible: grid.visible,
    snapEnabled: grid.snapEnabled,
    origin: { ...grid.origin },
  };
}

function parseGridType(value: string): StructuredPrototypeFreeformGrid["type"] {
  if (value === "square" || value === "columns" || value === "rows") return value;
  throw new Error(`unsupported Freeform grid type: ${value}`);
}

function parseGridAlignment(value: string): StructuredPrototypeAxisGrid["params"]["alignment"] {
  if (value === "stretch" || value === "start" || value === "center" || value === "end") {
    return value;
  }
  throw new Error(`unsupported Freeform grid alignment: ${value}`);
}

function updateGridPresentation(
  grid: StructuredPrototypeFreeformGrid,
  update: { colorTokenKey?: string; opacity?: string },
): StructuredPrototypeFreeformGrid {
  if (grid.type === "square") {
    return { ...grid, params: { ...grid.params, ...update } };
  }
  return { ...grid, params: { ...grid.params, ...update } };
}

function canonicalDecimalInput(rawValue: string, positive: boolean): string | null {
  const numeric = Number(rawValue);
  if (!Number.isFinite(numeric) || numeric < 0 || (positive && numeric <= 0)) return null;
  try {
    return canonicalStructuredPrototypeFreeformValue(numeric);
  } catch (error) {
    if (error instanceof RangeError) return null;
    throw error;
  }
}

function DecimalField({
  label,
  value,
  positive = false,
  disabled,
  onChange,
}: {
  label: string;
  value: string;
  positive?: boolean;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label className="grid gap-1 text-[11px] font-semibold text-text-secondary">
      {label}
      <input
        className="min-h-9 rounded-md border border-border-muted bg-surface-input px-2 text-sm font-normal text-foreground"
        type="number"
        min={positive ? 0.0001 : 0}
        max={4096}
        step={0.25}
        value={value}
        onChange={(event) => {
          const next = canonicalDecimalInput(event.target.value, positive);
          if (next !== null) onChange(next);
        }}
        disabled={disabled}
      />
    </label>
  );
}

function replaceGrid(
  grids: StructuredPrototypeFreeformGrid[],
  gridId: string,
  replacement: StructuredPrototypeFreeformGrid,
): StructuredPrototypeFreeformGrid[] {
  return grids.map((grid) => (grid.id === gridId ? replacement : grid));
}

function moveGrid(
  grids: StructuredPrototypeFreeformGrid[],
  index: number,
  direction: -1 | 1,
): StructuredPrototypeFreeformGrid[] {
  const targetIndex = index + direction;
  if (targetIndex < 0 || targetIndex >= grids.length) return grids;
  const next = [...grids];
  const current = next[index];
  const target = next[targetIndex];
  if (current === undefined || target === undefined) return grids;
  next[index] = target;
  next[targetIndex] = current;
  return next;
}

export function StructuredPrototypeFreeformGridsEditor({
  grids,
  colorTokens,
  disabled,
  onChange,
}: Props) {
  const { t } = useI18n();
  const defaultColorTokenKey = colorTokens[0]?.key;
  if (defaultColorTokenKey === undefined) {
    throw new Error("Freeform grid editor requires at least one color token");
  }
  const colorValues = new Map(colorTokens.map((token) => [token.key, token.value]));

  return (
    <section className="grid gap-2 border-y border-border-subtle py-3" data-prototype-grid-editor>
      <div className="flex items-center justify-between gap-2">
        <div>
          <div className="text-[11px] font-bold text-text-secondary">
            {t("prototype.structured.inspector.layoutGrids")}
          </div>
          <div className="mt-0.5 text-[10px] text-text-muted">
            {t("prototype.structured.inspector.layoutGridCount", { count: String(grids.length) })}
          </div>
        </div>
        <button
          type="button"
          className="inline-flex min-h-8 cursor-pointer items-center gap-1.5 rounded-md border border-border-muted bg-surface-input px-2 text-[11px] font-semibold text-foreground hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-45"
          onClick={() =>
            onChange([
              ...grids,
              createDefaultStructuredPrototypeFreeformGrid(
                globalThis.crypto.randomUUID(),
                "square",
                defaultColorTokenKey,
              ),
            ])
          }
          disabled={disabled || grids.length >= MAX_FREEFORM_GRIDS}
        >
          <Plus size={13} aria-hidden />
          {t("prototype.structured.inspector.addLayoutGrid")}
        </button>
      </div>

      {grids.length === 0 ? (
        <p className="py-2 text-xs text-text-muted">
          {t("prototype.structured.inspector.noLayoutGrids")}
        </p>
      ) : (
        <div className="divide-y divide-border-subtle border-y border-border-subtle">
          {grids.map((grid, index) => {
            const colorValue = colorValues.get(grid.params.colorTokenKey) ?? "transparent";
            const update = (replacement: StructuredPrototypeFreeformGrid) =>
              onChange(replaceGrid(grids, grid.id, replacement));
            const setDecimal = (field: "x" | "y", value: string): void =>
              update({ ...grid, origin: { ...grid.origin, [field]: value } });
            return (
              <div
                key={grid.id}
                className="grid gap-3 py-3"
                data-prototype-grid-id={grid.id}
                data-prototype-grid-type={grid.type}
              >
                <div className="flex items-center gap-1.5">
                  <select
                    className="min-h-9 min-w-0 flex-1 cursor-pointer rounded-md border border-border-muted bg-surface-input px-2 text-xs font-semibold text-foreground"
                    value={grid.type}
                    onChange={(event) => {
                      const type = parseGridType(event.target.value);
                      update(changeStructuredPrototypeFreeformGridType(grid, type));
                    }}
                    disabled={disabled}
                    aria-label={t("prototype.structured.inspector.layoutGridType")}
                  >
                    {(["square", "columns", "rows"] as const).map((type) => (
                      <option key={type} value={type}>
                        {t(`prototype.structured.inspector.layoutGridType.${type}`)}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className={cn(
                      "grid size-8 cursor-pointer place-items-center rounded-md border border-border-muted bg-surface-input hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-45",
                      grid.visible ? "text-brand" : "text-text-muted",
                    )}
                    onClick={() => update({ ...grid, visible: !grid.visible })}
                    disabled={disabled}
                    aria-pressed={grid.visible}
                    aria-label={t("prototype.structured.inspector.layoutGridVisible")}
                    title={t("prototype.structured.inspector.layoutGridVisible")}
                  >
                    {grid.visible ? (
                      <Eye size={14} aria-hidden />
                    ) : (
                      <EyeOff size={14} aria-hidden />
                    )}
                  </button>
                  <button
                    type="button"
                    className={cn(
                      "grid size-8 cursor-pointer place-items-center rounded-md border border-border-muted bg-surface-input hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-45",
                      grid.snapEnabled ? "text-brand" : "text-text-muted",
                    )}
                    onClick={() => update({ ...grid, snapEnabled: !grid.snapEnabled })}
                    disabled={disabled}
                    aria-pressed={grid.snapEnabled}
                    aria-label={t("prototype.structured.inspector.layoutGridSnap")}
                    title={t("prototype.structured.inspector.layoutGridSnap")}
                  >
                    <Magnet size={14} aria-hidden />
                  </button>
                  <button
                    type="button"
                    className="grid size-8 cursor-pointer place-items-center rounded-md text-text-muted hover:bg-surface-hover hover:text-foreground disabled:cursor-not-allowed disabled:opacity-35"
                    onClick={() => onChange(moveGrid(grids, index, -1))}
                    disabled={disabled || index === 0}
                    aria-label={t("prototype.structured.inspector.moveLayoutGridUp")}
                    title={t("prototype.structured.inspector.moveLayoutGridUp")}
                  >
                    <ArrowUp size={14} aria-hidden />
                  </button>
                  <button
                    type="button"
                    className="grid size-8 cursor-pointer place-items-center rounded-md text-text-muted hover:bg-surface-hover hover:text-foreground disabled:cursor-not-allowed disabled:opacity-35"
                    onClick={() => onChange(moveGrid(grids, index, 1))}
                    disabled={disabled || index === grids.length - 1}
                    aria-label={t("prototype.structured.inspector.moveLayoutGridDown")}
                    title={t("prototype.structured.inspector.moveLayoutGridDown")}
                  >
                    <ArrowDown size={14} aria-hidden />
                  </button>
                  <button
                    type="button"
                    className="grid size-8 cursor-pointer place-items-center rounded-md text-error hover:bg-error/10 disabled:cursor-not-allowed disabled:opacity-45"
                    onClick={() => onChange(grids.filter((candidate) => candidate.id !== grid.id))}
                    disabled={disabled}
                    aria-label={t("prototype.structured.inspector.deleteLayoutGrid")}
                    title={t("prototype.structured.inspector.deleteLayoutGrid")}
                  >
                    <Trash2 size={14} aria-hidden />
                  </button>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <DecimalField
                    label={t("prototype.structured.inspector.layoutGridOriginX")}
                    value={grid.origin.x}
                    disabled={disabled}
                    onChange={(value) => setDecimal("x", value)}
                  />
                  <DecimalField
                    label={t("prototype.structured.inspector.layoutGridOriginY")}
                    value={grid.origin.y}
                    disabled={disabled}
                    onChange={(value) => setDecimal("y", value)}
                  />
                </div>

                {grid.type === "square" ? (
                  <DecimalField
                    label={t("prototype.structured.inspector.layoutGridSize")}
                    value={grid.params.size}
                    positive
                    disabled={disabled}
                    onChange={(size) => update({ ...grid, params: { ...grid.params, size } })}
                  />
                ) : (
                  <AxisGridFields grid={grid} disabled={disabled} onChange={update} />
                )}

                <div className="grid grid-cols-[minmax(0,1fr)_84px] gap-2">
                  <label className="grid gap-1 text-[11px] font-semibold text-text-secondary">
                    {t("prototype.structured.inspector.layoutGridColor")}
                    <span className="flex min-h-9 items-center gap-2 rounded-md border border-border-muted bg-surface-input px-2">
                      <span
                        className="size-3 shrink-0 border border-border-muted"
                        style={{ backgroundColor: colorValue }}
                        aria-hidden
                      />
                      <select
                        className="min-w-0 flex-1 cursor-pointer bg-transparent text-xs font-normal text-foreground outline-none"
                        value={grid.params.colorTokenKey}
                        onChange={(event) =>
                          update(
                            updateGridPresentation(grid, {
                              colorTokenKey: event.target.value,
                            }),
                          )
                        }
                        disabled={disabled}
                      >
                        {colorTokens.map((token) => (
                          <option key={token.key} value={token.key}>
                            {token.key}
                          </option>
                        ))}
                      </select>
                    </span>
                  </label>
                  <label className="grid gap-1 text-[11px] font-semibold text-text-secondary">
                    {t("prototype.structured.inspector.layoutGridOpacity")}
                    <input
                      className="min-h-9 rounded-md border border-border-muted bg-surface-input px-2 text-sm font-normal text-foreground"
                      type="number"
                      min={0}
                      max={1}
                      step={0.05}
                      value={grid.params.opacity}
                      onChange={(event) => {
                        const opacity = canonicalDecimalInput(event.target.value, false);
                        if (opacity !== null && Number(opacity) <= 1) {
                          update(updateGridPresentation(grid, { opacity }));
                        }
                      }}
                      disabled={disabled}
                    />
                  </label>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

function AxisGridFields({
  grid,
  disabled,
  onChange,
}: {
  grid: StructuredPrototypeAxisGrid;
  disabled: boolean;
  onChange: (grid: StructuredPrototypeFreeformGrid) => void;
}) {
  const { t } = useI18n();
  const updateParams = (params: StructuredPrototypeAxisGrid["params"]): void =>
    onChange({ ...grid, params });
  return (
    <div className="grid grid-cols-2 gap-2">
      <label className="grid gap-1 text-[11px] font-semibold text-text-secondary">
        {t("prototype.structured.inspector.layoutGridCountLabel")}
        <input
          className="min-h-9 rounded-md border border-border-muted bg-surface-input px-2 text-sm font-normal text-foreground"
          type="number"
          min={1}
          max={24}
          step={1}
          value={grid.params.count}
          onChange={(event) => {
            const count = Number(event.target.value);
            if (Number.isSafeInteger(count) && count >= 1 && count <= 24) {
              updateParams({ ...grid.params, count });
            }
          }}
          disabled={disabled}
        />
      </label>
      <label className="grid gap-1 text-[11px] font-semibold text-text-secondary">
        {t("prototype.structured.inspector.layoutGridAlignment")}
        <select
          className="min-h-9 cursor-pointer rounded-md border border-border-muted bg-surface-input px-2 text-xs font-normal text-foreground"
          value={grid.params.alignment}
          onChange={(event) => {
            const alignment = parseGridAlignment(event.target.value);
            updateParams({
              ...grid.params,
              alignment,
              itemSize: alignment === "stretch" ? null : (grid.params.itemSize ?? "64"),
            });
          }}
          disabled={disabled}
        >
          {(["stretch", "start", "center", "end"] as const).map((alignment) => (
            <option key={alignment} value={alignment}>
              {t(`prototype.structured.inspector.layoutGridAlignment.${alignment}`)}
            </option>
          ))}
        </select>
      </label>
      {grid.params.itemSize !== null && (
        <DecimalField
          label={t("prototype.structured.inspector.layoutGridItemSize")}
          value={grid.params.itemSize}
          positive
          disabled={disabled}
          onChange={(itemSize) => updateParams({ ...grid.params, itemSize })}
        />
      )}
      <DecimalField
        label={t("prototype.structured.inspector.layoutGridGutter")}
        value={grid.params.gutter}
        disabled={disabled}
        onChange={(gutter) => updateParams({ ...grid.params, gutter })}
      />
      <DecimalField
        label={t("prototype.structured.inspector.layoutGridMargin")}
        value={grid.params.margin}
        disabled={disabled}
        onChange={(margin) => updateParams({ ...grid.params, margin })}
      />
    </div>
  );
}
