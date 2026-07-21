"use client";

import { useDraggable } from "@dnd-kit/core";
import { GripVertical, Package, Plus, Trash2 } from "lucide-react";

import type { StructuredPrototypeComponentDefinition } from "./types";

interface Props {
  definitions: StructuredPrototypeComponentDefinition[];
  disabled: boolean;
  insertLabel: string;
  deleteLabel: string;
  emptyLabel: string;
  onInsert: (componentId: string) => void;
  onDelete: (componentId: string) => void;
}

function ComponentDefinitionRow({
  definition,
  disabled,
  insertLabel,
  deleteLabel,
  onInsert,
  onDelete,
}: {
  definition: StructuredPrototypeComponentDefinition;
  disabled: boolean;
  insertLabel: string;
  deleteLabel: string;
  onInsert: () => void;
  onDelete: () => void;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `componentDef:${definition.id}`,
    data: { kind: "componentDef", componentId: definition.id },
    disabled,
  });
  return (
    <div
      className="flex items-center gap-1 rounded-lg border border-border-subtle bg-surface-raised px-2 py-1.5"
      style={{ opacity: isDragging ? 0.55 : 1 }}
      data-prototype-component-definition={definition.id}
    >
      <button
        ref={setNodeRef}
        type="button"
        className="flex min-w-0 flex-1 cursor-grab items-center gap-2 text-left disabled:cursor-not-allowed"
        disabled={disabled}
        aria-label={definition.root.name}
        {...listeners}
        {...attributes}
      >
        <GripVertical size={13} className="shrink-0 text-text-faint" aria-hidden />
        <Package size={14} className="shrink-0 text-brand" aria-hidden />
        <span className="min-w-0">
          <span className="block truncate text-xs font-semibold text-foreground">
            {definition.root.name}
          </span>
          <span className="block truncate font-mono text-[10px] text-text-faint">
            {definition.key}
          </span>
        </span>
      </button>
      <button
        type="button"
        className="grid size-7 shrink-0 cursor-pointer place-items-center rounded-md text-text-muted hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-45"
        onClick={onInsert}
        disabled={disabled}
        aria-label={insertLabel}
        title={insertLabel}
      >
        <Plus size={13} aria-hidden />
      </button>
      <button
        type="button"
        className="grid size-7 shrink-0 cursor-pointer place-items-center rounded-md text-text-muted hover:bg-failed-bg hover:text-status-failed disabled:cursor-not-allowed disabled:opacity-45"
        onClick={onDelete}
        disabled={disabled}
        aria-label={deleteLabel}
        title={deleteLabel}
      >
        <Trash2 size={13} aria-hidden />
      </button>
    </div>
  );
}

export function StructuredPrototypeComponentLibrary({
  definitions,
  disabled,
  insertLabel,
  deleteLabel,
  emptyLabel,
  onInsert,
  onDelete,
}: Props) {
  if (definitions.length === 0) {
    return <p className="px-3 py-4 text-xs leading-5 text-text-muted">{emptyLabel}</p>;
  }
  return (
    <div className="grid gap-2 p-3">
      {definitions.map((definition) => (
        <ComponentDefinitionRow
          key={definition.id}
          definition={definition}
          disabled={disabled}
          insertLabel={insertLabel}
          deleteLabel={deleteLabel}
          onInsert={() => onInsert(definition.id)}
          onDelete={() => onDelete(definition.id)}
        />
      ))}
    </div>
  );
}
