"use client";

import { useDraggable } from "@dnd-kit/core";
import {
  Box,
  FormInput,
  GripVertical,
  MousePointerClick,
  Table2,
  TextCursorInput,
  Type,
} from "lucide-react";

export type StructuredPrototypePaletteType =
  "Stack" | "Form" | "Text" | "Input" | "Button" | "Table";

interface PaletteItem {
  type: StructuredPrototypePaletteType;
  label: string;
  icon: typeof Box;
}

interface Props {
  labels: Record<StructuredPrototypePaletteType, string>;
  disabled: boolean;
  onInsert: (type: StructuredPrototypePaletteType) => void;
}

function DraggablePaletteItem({
  item,
  disabled,
  onInsert,
}: {
  item: PaletteItem;
  disabled: boolean;
  onInsert: (type: StructuredPrototypePaletteType) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `palette:${item.type}`,
    data: { kind: "palette", nodeType: item.type },
    disabled,
  });
  const Icon = item.icon;
  return (
    <button
      ref={setNodeRef}
      type="button"
      className="relative grid min-h-[72px] cursor-pointer place-items-center gap-1 rounded-lg border border-border-subtle bg-surface-raised px-2 py-3 text-foreground transition-colors hover:border-brand hover:bg-brand-bg disabled:cursor-not-allowed disabled:opacity-50"
      style={{
        transform: transform ? `translate3d(${transform.x}px, ${transform.y}px, 0)` : undefined,
        opacity: isDragging ? 0.55 : 1,
      }}
      disabled={disabled}
      aria-label={item.label}
      onClick={() => onInsert(item.type)}
      {...listeners}
      {...attributes}
    >
      <Icon size={18} className="text-brand" aria-hidden />
      <span className="text-xs font-semibold">{item.label}</span>
      <GripVertical size={13} className="absolute right-1 top-1 text-text-faint" aria-hidden />
    </button>
  );
}

export function StructuredPrototypePalette({ labels, disabled, onInsert }: Props) {
  const items: PaletteItem[] = [
    { type: "Stack", label: labels.Stack, icon: Box },
    { type: "Form", label: labels.Form, icon: FormInput },
    { type: "Text", label: labels.Text, icon: Type },
    { type: "Input", label: labels.Input, icon: TextCursorInput },
    { type: "Button", label: labels.Button, icon: MousePointerClick },
    { type: "Table", label: labels.Table, icon: Table2 },
  ];
  return (
    <div className="grid grid-cols-2 gap-2 p-3">
      {items.map((item) => (
        <DraggablePaletteItem key={item.type} item={item} disabled={disabled} onInsert={onInsert} />
      ))}
    </div>
  );
}
