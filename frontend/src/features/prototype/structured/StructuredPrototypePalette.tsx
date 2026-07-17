"use client";

import { useDraggable } from "@dnd-kit/core";
import {
  Box,
  FormInput,
  Frame,
  GripVertical,
  LayoutGrid,
  MousePointerClick,
  Table2,
  TextCursorInput,
  Type,
} from "lucide-react";

import type { RuntimeFormDefinition } from "../runtime/types";
import {
  STRUCTURED_PROTOTYPE_PALETTE_TYPES,
  type StructuredPrototypePaletteType,
} from "./structuredPrototypePaletteTypes";

export type { StructuredPrototypePaletteType } from "./structuredPrototypePaletteTypes";

const PALETTE_ICONS: Record<StructuredPrototypePaletteType, typeof Box> = {
  Freeform: Frame,
  Stack: Box,
  Grid: LayoutGrid,
  Form: FormInput,
  Text: Type,
  Input: TextCursorInput,
  Button: MousePointerClick,
  Table: Table2,
};

interface PaletteItem {
  type: StructuredPrototypePaletteType;
  label: string;
  icon: typeof Box;
}

interface Props {
  labels: Record<StructuredPrototypePaletteType, string>;
  forms: RuntimeFormDefinition[];
  selectedFormId: string | null;
  formSelectorLabel: string;
  formSelectorPlaceholder: string;
  dragDisabled: boolean;
  controlsDisabled: boolean;
  onFormSelect: (formId: string | null) => void;
  onInsert: (type: StructuredPrototypePaletteType, formId: string | null) => void;
}

function DraggablePaletteItem({
  item,
  disabled,
  formId,
  onInsert,
}: {
  item: PaletteItem;
  disabled: boolean;
  formId: string | null;
  onInsert: (type: StructuredPrototypePaletteType, formId: string | null) => void;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `palette:${item.type}`,
    data: { kind: "palette", nodeType: item.type, formDefinitionId: formId },
    disabled,
  });
  const Icon = item.icon;
  return (
    <button
      ref={setNodeRef}
      type="button"
      className="relative flex min-h-11 w-full cursor-pointer items-center gap-2 border-l-2 border-transparent bg-transparent px-3 py-2 text-left text-foreground transition-colors hover:border-brand hover:bg-brand-bg disabled:cursor-not-allowed disabled:opacity-50"
      style={{ opacity: isDragging ? 0.45 : 1 }}
      disabled={disabled}
      aria-label={item.label}
      onClick={() => onInsert(item.type, formId)}
      {...listeners}
      {...attributes}
    >
      <Icon size={16} className="shrink-0 text-brand" aria-hidden />
      <span className="text-xs font-semibold">{item.label}</span>
      <GripVertical size={13} className="ml-auto shrink-0 text-text-faint" aria-hidden />
    </button>
  );
}

export function StructuredPrototypePalette({
  labels,
  forms,
  selectedFormId,
  formSelectorLabel,
  formSelectorPlaceholder,
  dragDisabled,
  controlsDisabled,
  onFormSelect,
  onInsert,
}: Props) {
  const items: PaletteItem[] = STRUCTURED_PROTOTYPE_PALETTE_TYPES.map((type) => ({
    type,
    label: labels[type],
    icon: PALETTE_ICONS[type],
  }));
  return (
    <div className="grid grid-cols-1 py-1">
      {forms.length > 1 && (
        <div className="border-b border-border-subtle px-3 py-2">
          <select
            className="min-h-9 w-full cursor-pointer rounded-md border border-border-muted bg-surface-input px-2 text-xs text-foreground disabled:cursor-not-allowed disabled:opacity-50"
            aria-label={formSelectorLabel}
            value={selectedFormId ?? ""}
            disabled={controlsDisabled}
            onChange={(event) => onFormSelect(event.target.value || null)}
          >
            <option value="">{formSelectorPlaceholder}</option>
            {forms.map((form) => (
              <option key={form.id} value={form.id}>
                {form.key}
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="grid grid-cols-1 divide-y divide-border-subtle">
        {items.map((item) => {
          const formId = item.type === "Form" ? selectedFormId : null;
          return (
            <DraggablePaletteItem
              key={item.type}
              item={item}
              disabled={dragDisabled || (item.type === "Form" && formId === null)}
              formId={formId}
              onInsert={onInsert}
            />
          );
        })}
      </div>
    </div>
  );
}
