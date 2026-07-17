"use client";

import { useEffect, useMemo, useState } from "react";
import { Plus, Save, Trash2 } from "lucide-react";

import { useI18n } from "@/providers/I18nProvider";

import type { RuntimeEntity, RuntimeEntityFieldDefinition, RuntimeValue } from "../runtime/types";
import { StructuredPrototypeLayoutOverridesEditor } from "./StructuredPrototypeLayoutOverridesEditor";
import { StructuredPrototypeFreeformGridsEditor } from "./StructuredPrototypeFreeformGridsEditor";
import {
  cloneStructuredPrototypeFreeformGrids,
  resolveStructuredPrototypeFreeformGrids,
} from "./structuredPrototypeFreeformGrids";
import {
  STRUCTURED_PROTOTYPE_LENGTH_UNITS,
  defaultStructuredPrototypeLength,
  structuredPrototypeMaxLengthValue,
  updateStructuredPrototypeLengthUnit,
  updateStructuredPrototypeLengthValue,
} from "./structuredPrototypeInspectorLayout";
import type {
  StructuredPrototypeCommandBatch,
  StructuredPrototypeLength,
  StructuredPrototypeLayoutItem,
  StructuredPrototypeLayoutUpdate,
  StructuredPrototypeNode,
  StructuredPrototypeNodePropertyUpdate,
  StructuredPrototypePadding,
  StructuredPrototypeResponsiveOverride,
  StructuredPrototypeGridColumnOverride,
  StructuredPrototypeFreeformGrid,
  StructuredPrototypeTableColumn,
  StructuredPrototypeTableRow,
} from "./types";

export interface StructuredPrototypeInspectorRuntimeTable {
  scenarioId: string;
  schemaId: string;
  fields: RuntimeEntityFieldDefinition[];
  rows: RuntimeEntity[];
}

interface Props {
  node: StructuredPrototypeNode | null;
  colorTokens: Array<{ key: string; value: string }>;
  selectedCount: number;
  disabled: boolean;
  canDelete: boolean;
  isRuntimeBoundTable: boolean;
  runtimeTable: StructuredPrototypeInspectorRuntimeTable | null;
  onApply: (batch: StructuredPrototypeCommandBatch) => Promise<boolean>;
  onDelete: () => void;
}

export interface StructuredPrototypeInspectorDraft {
  content: string;
  buttonVariant: "primary" | "secondary" | "danger" | "ghost";
  visibility: "visible" | "hidden";
  width: StructuredPrototypeLength;
  minWidth: StructuredPrototypeLength | null;
  maxWidth: StructuredPrototypeLength | null;
  height: StructuredPrototypeLength;
  minHeight: StructuredPrototypeLength | null;
  maxHeight: StructuredPrototypeLength | null;
  grow: number;
  shrink: number;
  alignSelf: StructuredPrototypeLayoutItem["alignSelf"];
  containerLayout: StructuredPrototypeInspectorContainerLayout;
  freeformGrids: StructuredPrototypeFreeformGrid[];
  responsive: StructuredPrototypeResponsiveOverride[];
  tableColumns: StructuredPrototypeTableColumn[];
  tableRows: StructuredPrototypeTableRow[];
}

export type StructuredPrototypeInspectorContainerLayout =
  | {
      kind: "stack";
      direction: "row" | "column";
      gap: number;
      align: "start" | "center" | "end" | "stretch";
      justify: "start" | "center" | "end" | "between";
      padding: StructuredPrototypePadding;
    }
  | {
      kind: "grid";
      columns: number;
      gap: number;
      padding: StructuredPrototypePadding;
      columnOverrides: StructuredPrototypeGridColumnOverride[];
    }
  | {
      kind: "form";
      gap: number;
      padding: StructuredPrototypePadding;
    }
  | null;

function cloneTableColumns(
  columns: StructuredPrototypeTableColumn[],
): StructuredPrototypeTableColumn[] {
  return columns.map((column) => ({ ...column }));
}

function cloneTableRows(rows: StructuredPrototypeTableRow[]): StructuredPrototypeTableRow[] {
  return rows.map((row) => ({
    ...row,
    cells: row.cells.map((cell) => ({ ...cell })),
  }));
}

function cloneResponsiveOverrides(
  responsive: StructuredPrototypeResponsiveOverride[],
): StructuredPrototypeResponsiveOverride[] {
  return responsive.map((override) => ({
    ...override,
    layoutItem: { ...override.layoutItem },
  }));
}

function containerLayoutForNode(
  node: StructuredPrototypeNode,
): StructuredPrototypeInspectorContainerLayout {
  if (node.type === "Stack") {
    return {
      kind: "stack",
      direction: node.direction,
      gap: node.gap,
      align: node.align,
      justify: node.justify,
      padding: { ...node.padding },
    };
  }
  if (node.type === "Grid") {
    return {
      kind: "grid",
      columns: node.columns,
      gap: node.gap,
      padding: { ...node.padding },
      columnOverrides: node.columnOverrides.map((override) => ({ ...override })),
    };
  }
  if (node.type === "Form") {
    return {
      kind: "form",
      gap: node.gap,
      padding: { ...node.padding },
    };
  }
  return null;
}

export function createStructuredPrototypeTableRow(
  columns: StructuredPrototypeTableColumn[],
): StructuredPrototypeTableRow {
  return {
    id: crypto.randomUUID(),
    cells: columns.map((column) => ({ columnKey: column.key, value: "" })),
  };
}

function cloneRuntimeRows(rows: RuntimeEntity[]): RuntimeEntity[] {
  return rows.map((row) => ({
    ...row,
    fields: row.fields.map((field) => ({ ...field, value: { ...field.value } })),
  }));
}

function sameLength(left: StructuredPrototypeLength, right: StructuredPrototypeLength): boolean {
  return left.unit === right.unit && left.value === right.value;
}

function sameTableData(
  leftColumns: StructuredPrototypeTableColumn[],
  leftRows: StructuredPrototypeTableRow[],
  rightColumns: StructuredPrototypeTableColumn[],
  rightRows: StructuredPrototypeTableRow[],
): boolean {
  return (
    JSON.stringify({ columns: leftColumns, rows: leftRows }) ===
    JSON.stringify({ columns: rightColumns, rows: rightRows })
  );
}

function sameStructuredValue(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function sameRuntimeValue(left: RuntimeValue, right: RuntimeValue): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function editableValue(node: StructuredPrototypeNode): string | null {
  if (node.type === "Text") return node.content;
  if (node.type === "Input") return node.label;
  if (node.type === "Button") return node.label;
  return null;
}

function propertyUpdate(
  node: StructuredPrototypeNode,
  value: string,
): StructuredPrototypeNodePropertyUpdate | null {
  if (node.type === "Text") return { kind: "textContent", content: value };
  if (node.type === "Input" || node.type === "Button") return { kind: "label", label: value };
  return null;
}

function runtimeFieldValueLabel(value: RuntimeValue): string {
  if (value.type === "null") return "";
  if (value.type === "boolean") return value.value ? "true" : "false";
  if (value.type === "integer") return String(value.value);
  if (value.type === "entityRef") return value.entityId;
  return value.value;
}

function runtimeFieldValueFromInput(
  field: RuntimeEntityFieldDefinition,
  rawValue: string,
): RuntimeValue | null {
  if (rawValue === "" && field.nullable) return { type: "null" };
  if (field.valueType === "string") return { type: "string", value: rawValue };
  if (field.valueType === "enum") return { type: "enum", value: rawValue };
  if (field.valueType === "boolean") return { type: "boolean", value: rawValue === "true" };
  if (field.valueType === "integer") {
    const value = Number(rawValue);
    return Number.isSafeInteger(value) ? { type: "integer", value } : null;
  }
  return null;
}

function runtimeFieldEditable(field: RuntimeEntityFieldDefinition): boolean {
  return (
    field.valueType === "string" ||
    field.valueType === "enum" ||
    field.valueType === "boolean" ||
    field.valueType === "integer"
  );
}

export function buildStructuredPrototypeRuntimeTableCommands(
  runtimeTable: StructuredPrototypeInspectorRuntimeTable,
  draftRows: RuntimeEntity[],
): StructuredPrototypeCommandBatch["commands"] {
  const originalRowsById = new Map(runtimeTable.rows.map((row) => [row.id, row]));
  const commands: StructuredPrototypeCommandBatch["commands"] = [];
  for (const draftRow of draftRows) {
    const originalRow = originalRowsById.get(draftRow.id);
    if (originalRow === undefined) continue;
    for (const draftField of draftRow.fields) {
      const originalField = originalRow.fields.find(
        (candidate) => candidate.fieldId === draftField.fieldId,
      );
      if (originalField === undefined) continue;
      if (sameRuntimeValue(draftField.value, originalField.value)) continue;
      commands.push({
        kind: "setRuntimeEntityField",
        scenarioId: runtimeTable.scenarioId,
        schemaId: runtimeTable.schemaId,
        entityId: draftRow.id,
        fieldId: draftField.fieldId,
        value: draftField.value,
      });
    }
  }
  return commands;
}

export function buildStructuredPrototypeInspectorBatch(
  node: StructuredPrototypeNode,
  draft: StructuredPrototypeInspectorDraft,
): StructuredPrototypeCommandBatch | null {
  const commands: StructuredPrototypeCommandBatch["commands"] = [];
  const initialContent = editableValue(node);
  const update = propertyUpdate(node, draft.content);
  if (update && draft.content !== initialContent) {
    commands.push({
      kind: "setNodeProperty",
      node: { kind: "existing", nodeId: node.id },
      update,
    });
  }
  if (node.type === "Button" && draft.buttonVariant !== node.variant) {
    commands.push({
      kind: "setNodeProperty",
      node: { kind: "existing", nodeId: node.id },
      update: { kind: "buttonVariant", variant: draft.buttonVariant },
    });
  }
  if (draft.visibility !== node.visibility) {
    commands.push({
      kind: "setNodeProperty",
      node: { kind: "existing", nodeId: node.id },
      update: { kind: "visibility", visibility: draft.visibility },
    });
  }
  const layoutUpdate: StructuredPrototypeLayoutUpdate = {};
  if (!sameLength(draft.width, node.layoutItem.width)) layoutUpdate.width = draft.width;
  if (!sameStructuredValue(draft.minWidth, node.layoutItem.minWidth)) {
    layoutUpdate.minWidth = draft.minWidth;
  }
  if (!sameStructuredValue(draft.maxWidth, node.layoutItem.maxWidth)) {
    layoutUpdate.maxWidth = draft.maxWidth;
  }
  if (!sameLength(draft.height, node.layoutItem.height)) layoutUpdate.height = draft.height;
  if (!sameStructuredValue(draft.minHeight, node.layoutItem.minHeight)) {
    layoutUpdate.minHeight = draft.minHeight;
  }
  if (!sameStructuredValue(draft.maxHeight, node.layoutItem.maxHeight)) {
    layoutUpdate.maxHeight = draft.maxHeight;
  }
  if (draft.grow !== node.layoutItem.grow) layoutUpdate.grow = draft.grow;
  if (draft.shrink !== node.layoutItem.shrink) layoutUpdate.shrink = draft.shrink;
  if (draft.alignSelf !== node.layoutItem.alignSelf) layoutUpdate.alignSelf = draft.alignSelf;
  if (Object.keys(layoutUpdate).length > 0) {
    commands.push({
      kind: "setNodeLayout",
      node: { kind: "existing", nodeId: node.id },
      update: layoutUpdate,
    });
  }
  const initialContainerLayout = containerLayoutForNode(node);
  if (!sameStructuredValue(draft.containerLayout, initialContainerLayout)) {
    const layout = draft.containerLayout;
    if (node.type === "Stack" && layout?.kind === "stack") {
      commands.push({
        kind: "setNodeProperty",
        node: { kind: "existing", nodeId: node.id },
        update: {
          kind: "stackLayout",
          direction: layout.direction,
          gap: layout.gap,
          align: layout.align,
          justify: layout.justify,
          padding: layout.padding,
        },
      });
    } else if (node.type === "Grid" && layout?.kind === "grid") {
      commands.push({
        kind: "setNodeProperty",
        node: { kind: "existing", nodeId: node.id },
        update: {
          kind: "gridLayout",
          columns: layout.columns,
          gap: layout.gap,
          padding: layout.padding,
          columnOverrides: layout.columnOverrides,
        },
      });
    } else if (node.type === "Form" && layout?.kind === "form") {
      commands.push({
        kind: "setNodeProperty",
        node: { kind: "existing", nodeId: node.id },
        update: { kind: "formLayout", gap: layout.gap, padding: layout.padding },
      });
    } else {
      throw new Error(`container layout draft does not match ${node.type}`);
    }
  }
  if (
    node.type === "Freeform" &&
    !sameStructuredValue(draft.freeformGrids, resolveStructuredPrototypeFreeformGrids(node))
  ) {
    commands.push({
      kind: "setNodeProperty",
      node: { kind: "existing", nodeId: node.id },
      update: { kind: "freeformGrids", grids: draft.freeformGrids },
    });
  }
  if (!sameStructuredValue(draft.responsive, node.responsive)) {
    commands.push({
      kind: "setNodeProperty",
      node: { kind: "existing", nodeId: node.id },
      update: { kind: "responsiveLayout", responsive: draft.responsive },
    });
  }
  if (
    node.type === "Table" &&
    !sameTableData(draft.tableColumns, draft.tableRows, node.columns, node.rows)
  ) {
    commands.push({
      kind: "setNodeProperty",
      node: { kind: "existing", nodeId: node.id },
      update: {
        kind: "tableData",
        columns: draft.tableColumns,
        rows: draft.tableRows,
      },
    });
  }
  if (commands.length === 0) return null;
  return {
    commandContractVersion: 1,
    summary: `Edit ${node.type} properties`,
    commands,
  };
}

function EditableInspector({
  node,
  colorTokens,
  selectedCount,
  disabled,
  canDelete,
  isRuntimeBoundTable,
  runtimeTable,
  onApply,
  onDelete,
}: Props & { node: StructuredPrototypeNode }) {
  const { t } = useI18n();
  const initialValue = editableValue(node);
  const [value, setValue] = useState(initialValue ?? "");
  const [variant, setVariant] = useState(node.type === "Button" ? node.variant : "primary");
  const [visibility, setVisibility] = useState(node.visibility);
  const [width, setWidth] = useState(node.layoutItem.width);
  const [minWidth, setMinWidth] = useState(node.layoutItem.minWidth);
  const [maxWidth, setMaxWidth] = useState(node.layoutItem.maxWidth);
  const [height, setHeight] = useState(node.layoutItem.height);
  const [minHeight, setMinHeight] = useState(node.layoutItem.minHeight);
  const [maxHeight, setMaxHeight] = useState(node.layoutItem.maxHeight);
  const [grow, setGrow] = useState(node.layoutItem.grow);
  const [shrink, setShrink] = useState(node.layoutItem.shrink);
  const [alignSelf, setAlignSelf] = useState(node.layoutItem.alignSelf);
  const [containerLayout, setContainerLayout] = useState(() => containerLayoutForNode(node));
  const [freeformGrids, setFreeformGrids] = useState(() =>
    node.type === "Freeform"
      ? cloneStructuredPrototypeFreeformGrids(resolveStructuredPrototypeFreeformGrids(node))
      : [],
  );
  const [responsive, setResponsive] = useState(() => cloneResponsiveOverrides(node.responsive));
  const [layoutOverridesValid, setLayoutOverridesValid] = useState(true);
  const [tableColumns, setTableColumns] = useState(() =>
    node.type === "Table" ? cloneTableColumns(node.columns) : [],
  );
  const [tableRows, setTableRows] = useState(() =>
    node.type === "Table" ? cloneTableRows(node.rows) : [],
  );
  const [runtimeRows, setRuntimeRows] = useState(() =>
    runtimeTable ? cloneRuntimeRows(runtimeTable.rows) : [],
  );
  const runtimeRowsKey = useMemo(
    () => JSON.stringify(runtimeTable?.rows ?? []),
    [runtimeTable?.rows],
  );
  useEffect(() => {
    setRuntimeRows(runtimeTable ? cloneRuntimeRows(runtimeTable.rows) : []);
  }, [runtimeRowsKey, runtimeTable]);
  const runtimeFieldsById = useMemo(
    () => new Map((runtimeTable?.fields ?? []).map((field) => [field.id, field])),
    [runtimeTable],
  );
  const updateRuntimeCell = (entityId: string, fieldId: string, value: RuntimeValue) => {
    setRuntimeRows((current) =>
      current.map((row) => {
        if (row.id !== entityId) return row;
        return {
          ...row,
          fields: row.fields.map((field) =>
            field.fieldId === fieldId ? { ...field, value } : field,
          ),
        };
      }),
    );
  };
  const updateContainerPadding = (
    side: keyof StructuredPrototypePadding,
    rawValue: string,
  ): void => {
    const next = Number(rawValue);
    if (!Number.isSafeInteger(next) || next < 0 || next > 256) return;
    setContainerLayout((current) =>
      current === null ? null : { ...current, padding: { ...current.padding, [side]: next } },
    );
  };
  const sizeFields: Array<{
    label: string;
    value: StructuredPrototypeLength | null;
    nullable: boolean;
    onChange: (value: StructuredPrototypeLength | null) => void;
  }> = [
    {
      label: t("prototype.structured.inspector.width"),
      value: width,
      nullable: false,
      onChange: (next) => {
        if (next !== null) setWidth(next);
      },
    },
    {
      label: t("prototype.structured.inspector.minWidth"),
      value: minWidth,
      nullable: true,
      onChange: setMinWidth,
    },
    {
      label: t("prototype.structured.inspector.maxWidth"),
      value: maxWidth,
      nullable: true,
      onChange: setMaxWidth,
    },
    {
      label: t("prototype.structured.inspector.height"),
      value: height,
      nullable: false,
      onChange: (next) => {
        if (next !== null) setHeight(next);
      },
    },
    {
      label: t("prototype.structured.inspector.minHeight"),
      value: minHeight,
      nullable: true,
      onChange: setMinHeight,
    },
    {
      label: t("prototype.structured.inspector.maxHeight"),
      value: maxHeight,
      nullable: true,
      onChange: setMaxHeight,
    },
  ];

  const save = async () => {
    if (!layoutOverridesValid) return;
    const propertyBatch = buildStructuredPrototypeInspectorBatch(node, {
      content: value,
      buttonVariant: variant,
      visibility,
      width,
      minWidth,
      maxWidth,
      height,
      minHeight,
      maxHeight,
      grow,
      shrink,
      alignSelf,
      containerLayout,
      freeformGrids,
      responsive,
      tableColumns,
      tableRows,
    });
    const runtimeCommands =
      node.type === "Table" && runtimeTable
        ? buildStructuredPrototypeRuntimeTableCommands(runtimeTable, runtimeRows)
        : [];
    const commands = [...(propertyBatch?.commands ?? []), ...runtimeCommands];
    if (commands.length === 0) return;
    await onApply({
      commandContractVersion: 1,
      summary: `Edit ${node.type} properties`,
      commands,
    });
  };

  return (
    <div className="grid gap-5 p-4">
      <div>
        <div className="text-xs font-bold uppercase text-text-muted">{node.type}</div>
        <div className="mt-1 truncate text-sm font-semibold text-foreground">{node.name}</div>
        <div className="mt-1 truncate font-mono text-[10px] text-text-faint">{node.id}</div>
      </div>
      {selectedCount > 1 && (
        <div
          className="border-l-2 border-brand bg-brand/8 px-3 py-2 text-xs font-semibold text-text-secondary"
          role="status"
        >
          {t("prototype.structured.inspector.selectionCount", {
            count: String(selectedCount),
          })}
        </div>
      )}
      {initialValue !== null && (
        <label className="grid gap-2 text-xs font-semibold text-text-secondary">
          {t("prototype.structured.inspector.content")}
          <textarea
            className="min-h-28 resize-y rounded-lg border border-border-muted bg-surface-input p-3 text-sm font-normal text-foreground outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            disabled={disabled}
          />
        </label>
      )}
      {node.type === "Button" && (
        <label className="grid gap-2 text-xs font-semibold text-text-secondary">
          {t("prototype.structured.inspector.variant")}
          <select
            className="min-h-10 cursor-pointer rounded-md border border-border-muted bg-surface-input px-3 text-sm font-normal text-foreground"
            value={variant}
            onChange={(event) =>
              setVariant(event.target.value as "primary" | "secondary" | "danger" | "ghost")
            }
            disabled={disabled}
          >
            <option value="primary">Primary</option>
            <option value="secondary">Secondary</option>
            <option value="danger">Danger</option>
            <option value="ghost">Ghost</option>
          </select>
        </label>
      )}
      <label className="grid gap-2 text-xs font-semibold text-text-secondary">
        {t("prototype.structured.inspector.visibility")}
        <select
          className="min-h-10 cursor-pointer rounded-md border border-border-muted bg-surface-input px-3 text-sm font-normal text-foreground"
          value={visibility}
          onChange={(event) => setVisibility(event.target.value as "visible" | "hidden")}
          disabled={disabled}
        >
          <option value="visible">{t("prototype.structured.inspector.visible")}</option>
          <option value="hidden">{t("prototype.structured.inspector.hidden")}</option>
        </select>
      </label>
      {node.type === "Table" && (
        <div className="grid gap-3 rounded-lg border border-border-subtle bg-surface-raised p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="text-xs font-bold text-foreground">
              {t("prototype.structured.inspector.tableData")}
            </div>
            <div className="flex shrink-0 gap-2">
              <button
                type="button"
                className="inline-flex min-h-9 cursor-pointer items-center justify-center gap-1 rounded-md border border-border-muted bg-surface px-2 text-[11px] font-semibold text-foreground hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-45"
                onClick={() => {
                  const key = `column-${crypto.randomUUID().slice(0, 8)}`;
                  setTableColumns((current) => [
                    ...current,
                    { key, label: t("prototype.structured.inspector.newColumn"), fieldId: null },
                  ]);
                  setTableRows((current) =>
                    current.map((row) => ({
                      ...row,
                      cells: [...row.cells, { columnKey: key, value: "" }],
                    })),
                  );
                }}
                disabled={disabled || isRuntimeBoundTable}
              >
                <Plus size={13} aria-hidden />
                {t("prototype.structured.inspector.addColumn")}
              </button>
              <button
                type="button"
                className="inline-flex min-h-9 cursor-pointer items-center justify-center gap-1 rounded-md border border-border-muted bg-surface px-2 text-[11px] font-semibold text-foreground hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-45"
                onClick={() => {
                  setTableRows((current) => [
                    ...current,
                    createStructuredPrototypeTableRow(tableColumns),
                  ]);
                }}
                disabled={disabled || isRuntimeBoundTable}
              >
                <Plus size={13} aria-hidden />
                {t("prototype.structured.inspector.addRow")}
              </button>
            </div>
          </div>
          {isRuntimeBoundTable && (
            <p className="rounded-md border border-border-subtle bg-surface px-3 py-2 text-xs leading-5 text-text-muted">
              {t("prototype.structured.inspector.runtimeTableNote")}
            </p>
          )}
          <div className="overflow-auto">
            <table className="w-full min-w-[420px] border-collapse text-left text-xs">
              <thead>
                <tr>
                  {tableColumns.map((column) => (
                    <th
                      key={column.key}
                      className="border border-border-subtle bg-surface-input p-1 align-top"
                    >
                      <label className="grid gap-1 font-semibold text-text-secondary">
                        {t("prototype.structured.inspector.column")}
                        <input
                          className="min-h-8 rounded-md border border-border-muted bg-surface px-2 text-xs font-normal text-foreground outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
                          value={column.label}
                          onChange={(event) => {
                            const label = event.target.value;
                            setTableColumns((current) =>
                              current.map((candidate) =>
                                candidate.key === column.key ? { ...candidate, label } : candidate,
                              ),
                            );
                          }}
                          disabled={disabled}
                        />
                      </label>
                      <button
                        type="button"
                        className="mt-1 inline-flex min-h-8 cursor-pointer items-center justify-center gap-1 rounded-md px-2 text-[11px] font-semibold text-error hover:bg-error/10 disabled:cursor-not-allowed disabled:opacity-45"
                        onClick={() => {
                          setTableColumns((current) =>
                            current.filter((candidate) => candidate.key !== column.key),
                          );
                          setTableRows((current) =>
                            current.map((row) => ({
                              ...row,
                              cells: row.cells.filter((cell) => cell.columnKey !== column.key),
                            })),
                          );
                        }}
                        disabled={disabled || tableColumns.length <= 1}
                        aria-label={t("prototype.structured.inspector.deleteColumn", {
                          label: column.label,
                        })}
                      >
                        <Trash2 size={12} aria-hidden />
                        {t("prototype.structured.inspector.deleteColumnShort")}
                      </button>
                    </th>
                  ))}
                  <th className="w-16 border border-border-subtle bg-surface-input p-1 text-center text-text-muted">
                    {t("prototype.structured.inspector.rowActions")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {runtimeTable
                  ? runtimeRows.map((row, rowIndex) => (
                      <tr key={row.id}>
                        {tableColumns.map((column) => {
                          const fieldId = column.fieldId;
                          const field = fieldId ? runtimeFieldsById.get(fieldId) : undefined;
                          const runtimeValue = fieldId
                            ? row.fields.find((candidate) => candidate.fieldId === fieldId)
                            : undefined;
                          const editable = field !== undefined && runtimeFieldEditable(field);
                          const value =
                            runtimeValue === undefined
                              ? ""
                              : runtimeFieldValueLabel(runtimeValue.value);
                          return (
                            <td key={column.key} className="border border-border-subtle p-1">
                              {field?.valueType === "boolean" ? (
                                <select
                                  className="min-h-8 w-full cursor-pointer rounded-md border border-border-muted bg-surface-input px-2 text-xs text-foreground outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 disabled:cursor-not-allowed disabled:opacity-45"
                                  value={value === "true" ? "true" : "false"}
                                  onChange={(event) => {
                                    if (!fieldId || field === undefined) return;
                                    const nextValue = runtimeFieldValueFromInput(
                                      field,
                                      event.target.value,
                                    );
                                    if (nextValue) updateRuntimeCell(row.id, fieldId, nextValue);
                                  }}
                                  disabled={disabled || !editable || fieldId === null}
                                  aria-label={t("prototype.structured.inspector.cell", {
                                    row: String(rowIndex + 1),
                                    column: column.label,
                                  })}
                                >
                                  <option value="true">true</option>
                                  <option value="false">false</option>
                                </select>
                              ) : (
                                <input
                                  className="min-h-8 w-full rounded-md border border-border-muted bg-surface-input px-2 text-xs text-foreground outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 disabled:cursor-not-allowed disabled:opacity-45"
                                  type={field?.valueType === "integer" ? "number" : "text"}
                                  value={value}
                                  onChange={(event) => {
                                    if (!fieldId || field === undefined) return;
                                    const nextValue = runtimeFieldValueFromInput(
                                      field,
                                      event.target.value,
                                    );
                                    if (nextValue) updateRuntimeCell(row.id, fieldId, nextValue);
                                  }}
                                  disabled={disabled || !editable || fieldId === null}
                                  aria-label={t("prototype.structured.inspector.cell", {
                                    row: String(rowIndex + 1),
                                    column: column.label,
                                  })}
                                />
                              )}
                            </td>
                          );
                        })}
                        <td className="border border-border-subtle p-1 text-center">
                          <button
                            type="button"
                            className="inline-grid size-8 cursor-pointer place-items-center rounded-md text-error hover:bg-error/10 disabled:cursor-not-allowed disabled:opacity-45"
                            disabled
                            aria-label={t("prototype.structured.inspector.deleteRow", {
                              row: String(rowIndex + 1),
                            })}
                          >
                            <Trash2 size={13} aria-hidden />
                          </button>
                        </td>
                      </tr>
                    ))
                  : tableRows.map((row, rowIndex) => (
                      <tr key={row.id}>
                        {tableColumns.map((column) => {
                          const cellValue =
                            row.cells.find((cell) => cell.columnKey === column.key)?.value ?? "";
                          return (
                            <td key={column.key} className="border border-border-subtle p-1">
                              <input
                                className="min-h-8 w-full rounded-md border border-border-muted bg-surface-input px-2 text-xs text-foreground outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
                                value={cellValue}
                                onChange={(event) => {
                                  const nextValue = event.target.value;
                                  setTableRows((current) =>
                                    current.map((candidate) => {
                                      if (candidate.id !== row.id) return candidate;
                                      const cells = tableColumns.map((candidateColumn) => {
                                        if (candidateColumn.key === column.key) {
                                          return {
                                            columnKey: candidateColumn.key,
                                            value: nextValue,
                                          };
                                        }
                                        return (
                                          candidate.cells.find(
                                            (cell) => cell.columnKey === candidateColumn.key,
                                          ) ?? { columnKey: candidateColumn.key, value: "" }
                                        );
                                      });
                                      return { ...candidate, cells };
                                    }),
                                  );
                                }}
                                disabled={disabled}
                                aria-label={t("prototype.structured.inspector.cell", {
                                  row: String(rowIndex + 1),
                                  column: column.label,
                                })}
                              />
                            </td>
                          );
                        })}
                        <td className="border border-border-subtle p-1 text-center">
                          <button
                            type="button"
                            className="inline-grid size-8 cursor-pointer place-items-center rounded-md text-error hover:bg-error/10 disabled:cursor-not-allowed disabled:opacity-45"
                            onClick={() =>
                              setTableRows((current) =>
                                current.filter((candidate) => candidate.id !== row.id),
                              )
                            }
                            disabled={disabled}
                            aria-label={t("prototype.structured.inspector.deleteRow", {
                              row: String(rowIndex + 1),
                            })}
                          >
                            <Trash2 size={13} aria-hidden />
                          </button>
                        </td>
                      </tr>
                    ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <div className="grid gap-3 rounded-lg border border-border-subtle bg-surface-raised p-3">
        <div className="text-xs font-bold text-foreground">
          {t("prototype.structured.inspector.layout")}
        </div>
        {containerLayout !== null && (
          <div className="grid gap-3 border-b border-border-subtle pb-3">
            <div className="text-[11px] font-bold text-text-secondary">
              {t("prototype.structured.inspector.containerLayout")}
            </div>
            {containerLayout.kind === "stack" && (
              <div className="grid grid-cols-2 gap-2">
                <label className="grid gap-1 text-xs font-semibold text-text-secondary">
                  {t("prototype.structured.inspector.direction")}
                  <select
                    className="min-h-10 cursor-pointer rounded-md border border-border-muted bg-surface-input px-2 text-sm font-normal text-foreground"
                    value={containerLayout.direction}
                    onChange={(event) => {
                      const direction = event.target.value as "row" | "column";
                      setContainerLayout((current) =>
                        current?.kind === "stack" ? { ...current, direction } : current,
                      );
                    }}
                    disabled={disabled}
                  >
                    <option value="row">{t("prototype.structured.inspector.direction.row")}</option>
                    <option value="column">
                      {t("prototype.structured.inspector.direction.column")}
                    </option>
                  </select>
                </label>
                <label className="grid gap-1 text-xs font-semibold text-text-secondary">
                  {t("prototype.structured.inspector.align")}
                  <select
                    className="min-h-10 cursor-pointer rounded-md border border-border-muted bg-surface-input px-2 text-sm font-normal text-foreground"
                    value={containerLayout.align}
                    onChange={(event) => {
                      const align = event.target.value as typeof containerLayout.align;
                      setContainerLayout((current) =>
                        current?.kind === "stack" ? { ...current, align } : current,
                      );
                    }}
                    disabled={disabled}
                  >
                    {(["start", "center", "end", "stretch"] as const).map((value) => (
                      <option key={value} value={value}>
                        {t(`prototype.structured.inspector.alignSelf.${value}`)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="col-span-2 grid gap-1 text-xs font-semibold text-text-secondary">
                  {t("prototype.structured.inspector.justify")}
                  <select
                    className="min-h-10 cursor-pointer rounded-md border border-border-muted bg-surface-input px-2 text-sm font-normal text-foreground"
                    value={containerLayout.justify}
                    onChange={(event) => {
                      const justify = event.target.value as typeof containerLayout.justify;
                      setContainerLayout((current) =>
                        current?.kind === "stack" ? { ...current, justify } : current,
                      );
                    }}
                    disabled={disabled}
                  >
                    {(["start", "center", "end", "between"] as const).map((value) => (
                      <option key={value} value={value}>
                        {value === "between"
                          ? t("prototype.structured.inspector.justify.between")
                          : t(`prototype.structured.inspector.alignSelf.${value}`)}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            )}
            {containerLayout.kind === "grid" && (
              <label className="grid gap-1 text-xs font-semibold text-text-secondary">
                {t("prototype.structured.inspector.columns")}
                <input
                  className="min-h-10 rounded-md border border-border-muted bg-surface-input px-3 text-sm font-normal text-foreground"
                  type="number"
                  min={1}
                  max={12}
                  step={1}
                  value={containerLayout.columns}
                  onChange={(event) => {
                    const columns = Number(event.target.value);
                    if (!Number.isSafeInteger(columns) || columns < 1 || columns > 12) return;
                    setContainerLayout((current) =>
                      current?.kind === "grid" ? { ...current, columns } : current,
                    );
                  }}
                  disabled={disabled}
                />
              </label>
            )}
            <label className="grid gap-1 text-xs font-semibold text-text-secondary">
              {t("prototype.structured.inspector.gap")}
              <input
                className="min-h-10 rounded-md border border-border-muted bg-surface-input px-3 text-sm font-normal text-foreground"
                type="number"
                min={0}
                max={128}
                step={1}
                value={containerLayout.gap}
                onChange={(event) => {
                  const gap = Number(event.target.value);
                  if (!Number.isSafeInteger(gap) || gap < 0 || gap > 128) return;
                  setContainerLayout((current) => (current === null ? null : { ...current, gap }));
                }}
                disabled={disabled}
              />
            </label>
            <fieldset className="grid grid-cols-2 gap-2">
              <legend className="col-span-2 mb-1 text-xs font-semibold text-text-secondary">
                {t("prototype.structured.inspector.padding")}
              </legend>
              {(["top", "right", "bottom", "left"] as const).map((side) => (
                <label
                  key={side}
                  className="grid gap-1 text-[11px] font-semibold text-text-secondary"
                >
                  {t(`prototype.structured.inspector.padding.${side}`)}
                  <input
                    className="min-h-9 rounded-md border border-border-muted bg-surface-input px-2 text-sm font-normal text-foreground"
                    type="number"
                    min={0}
                    max={256}
                    step={1}
                    value={containerLayout.padding[side]}
                    onChange={(event) => updateContainerPadding(side, event.target.value)}
                    disabled={disabled}
                  />
                </label>
              ))}
            </fieldset>
          </div>
        )}
        {node.type === "Freeform" && (
          <StructuredPrototypeFreeformGridsEditor
            grids={freeformGrids}
            colorTokens={colorTokens}
            disabled={disabled}
            onChange={setFreeformGrids}
          />
        )}
        {sizeFields.map((item) => (
          <div key={item.label} className="grid grid-cols-[minmax(0,1fr)_92px] gap-2">
            <label className="grid gap-1 text-xs font-semibold text-text-secondary">
              {item.label}
              <input
                className="min-h-10 rounded-md border border-border-muted bg-surface-input px-3 text-sm font-normal text-foreground disabled:opacity-55"
                type="number"
                min={0}
                max={item.value === null ? 0 : structuredPrototypeMaxLengthValue(item.value.unit)}
                step={item.value?.unit === "px" ? 1 : 0.25}
                value={item.value?.value ?? ""}
                onChange={(event) => {
                  if (item.value === null) return;
                  item.onChange(
                    updateStructuredPrototypeLengthValue(item.value, event.target.value),
                  );
                }}
                disabled={disabled || item.value === null || item.value.unit === "auto"}
                aria-label={item.label}
              />
            </label>
            <label className="grid gap-1 text-xs font-semibold text-text-secondary">
              {t("prototype.structured.inspector.unit")}
              <select
                className="min-h-10 cursor-pointer rounded-md border border-border-muted bg-surface-input px-2 text-sm font-normal text-foreground"
                value={item.value?.unit ?? "none"}
                onChange={(event) => {
                  if (event.target.value === "none" && item.nullable) {
                    item.onChange(null);
                    return;
                  }
                  const unit = event.target.value as StructuredPrototypeLength["unit"];
                  item.onChange(
                    item.value === null
                      ? defaultStructuredPrototypeLength(unit)
                      : updateStructuredPrototypeLengthUnit(item.value, unit),
                  );
                }}
                disabled={disabled}
              >
                {item.nullable && (
                  <option value="none">{t("prototype.structured.inspector.noConstraint")}</option>
                )}
                {STRUCTURED_PROTOTYPE_LENGTH_UNITS.map((unit) => (
                  <option key={unit} value={unit}>
                    {t(`prototype.structured.inspector.unit.${unit}`)}
                  </option>
                ))}
              </select>
            </label>
          </div>
        ))}
        <StructuredPrototypeLayoutOverridesEditor
          responsive={responsive}
          gridColumns={containerLayout?.kind === "grid" ? containerLayout.columns : null}
          gridColumnOverrides={
            containerLayout?.kind === "grid" ? containerLayout.columnOverrides : null
          }
          disabled={disabled}
          onResponsiveChange={setResponsive}
          onGridColumnOverridesChange={(columnOverrides) =>
            setContainerLayout((current) =>
              current?.kind === "grid" ? { ...current, columnOverrides } : current,
            )
          }
          onValidityChange={setLayoutOverridesValid}
        />
      </div>
      <label className="grid gap-2 text-xs font-semibold text-text-secondary">
        {t("prototype.structured.inspector.grow")}
        <input
          className="min-h-10 rounded-md border border-border-muted bg-surface-input px-3 text-sm font-normal text-foreground"
          type="number"
          min={0}
          max={12}
          step={1}
          value={grow}
          onChange={(event) => {
            const next = Number(event.target.value);
            if (Number.isSafeInteger(next) && next >= 0 && next <= 12) setGrow(next);
          }}
          disabled={disabled}
        />
      </label>
      <label className="grid gap-2 text-xs font-semibold text-text-secondary">
        {t("prototype.structured.inspector.alignSelf")}
        <select
          className="min-h-10 cursor-pointer rounded-md border border-border-muted bg-surface-input px-3 text-sm font-normal text-foreground"
          value={alignSelf}
          onChange={(event) =>
            setAlignSelf(event.target.value as StructuredPrototypeLayoutItem["alignSelf"])
          }
          disabled={disabled}
        >
          {(["auto", "start", "center", "end", "stretch"] as const).map((value) => (
            <option key={value} value={value}>
              {t(`prototype.structured.inspector.alignSelf.${value}`)}
            </option>
          ))}
        </select>
      </label>
      <label className="grid gap-2 text-xs font-semibold text-text-secondary">
        {t("prototype.structured.inspector.shrink")}
        <input
          className="min-h-10 rounded-md border border-border-muted bg-surface-input px-3 text-sm font-normal text-foreground"
          type="number"
          min={0}
          max={12}
          step={1}
          value={shrink}
          onChange={(event) => {
            const next = Number(event.target.value);
            if (Number.isSafeInteger(next) && next >= 0 && next <= 12) setShrink(next);
          }}
          disabled={disabled}
        />
      </label>
      {!layoutOverridesValid && (
        <p className="border-l-2 border-error pl-3 text-xs leading-5 text-error" role="alert">
          {t("prototype.structured.inspector.invalidOverrides")}
        </p>
      )}
      <button
        type="button"
        className="inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-lg bg-brand px-4 text-sm font-semibold text-black hover:bg-brand-strong disabled:cursor-not-allowed disabled:opacity-45"
        onClick={() => void save()}
        disabled={disabled || !layoutOverridesValid}
      >
        <Save size={15} aria-hidden />
        {t("prototype.structured.inspector.save")}
      </button>
      <button
        type="button"
        className="inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-lg border border-error/35 bg-surface-raised px-4 text-sm font-semibold text-error hover:bg-error/10 disabled:cursor-not-allowed disabled:opacity-45"
        onClick={onDelete}
        disabled={disabled || !canDelete}
      >
        <Trash2 size={15} aria-hidden />
        {selectedCount > 1
          ? t("prototype.structured.inspector.deleteSelection", {
              count: String(selectedCount),
            })
          : t("prototype.structured.inspector.delete")}
      </button>
    </div>
  );
}

export function StructuredPrototypeInspector(props: Props) {
  const { t } = useI18n();
  if (!props.node) {
    return (
      <div className="grid min-h-56 place-items-center p-6 text-center text-sm text-text-muted">
        {t("prototype.structured.inspector.empty")}
      </div>
    );
  }
  return <EditableInspector key={props.node.id} {...props} node={props.node} />;
}
