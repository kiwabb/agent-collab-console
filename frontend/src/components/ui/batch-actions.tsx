"use client";

import { useState, useCallback } from "react";
import { CheckSquare, Square, Trash2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

export interface SelectableItem {
  id: string;
  [key: string]: unknown;
}

interface UseBatchSelectionOptions<T extends SelectableItem> {
  items: T[];
  onDelete?: (ids: string[]) => Promise<void> | void;
  onDeleteLabel?: string;
}

export function useBatchSelection<T extends SelectableItem>({
  items,
  onDelete,
  onDeleteLabel = "Delete",
}: UseBatchSelectionOptions<T>) {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [isDeleting, setIsDeleting] = useState(false);

  const toggleSelection = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const toggleAll = useCallback(() => {
    if (selectedIds.size === items.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(items.map((item) => item.id)));
    }
  }, [items, selectedIds.size]);

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  const isSelected = useCallback(
    (id: string) => selectedIds.has(id),
    [selectedIds]
  );

  const handleBatchDelete = useCallback(async () => {
    if (!onDelete || selectedIds.size === 0) return;
    setIsDeleting(true);
    try {
      await onDelete(Array.from(selectedIds));
      setSelectedIds(new Set());
    } finally {
      setIsDeleting(false);
    }
  }, [onDelete, selectedIds]);

  return {
    selectedIds,
    selectedCount: selectedIds.size,
    isAllSelected: selectedIds.size === items.length && items.length > 0,
    isSomeSelected: selectedIds.size > 0 && selectedIds.size < items.length,
    isDeleting,
    toggleSelection,
    toggleAll,
    clearSelection,
    isSelected,
    handleBatchDelete,
  };
}

interface BatchActionsBarProps {
  selectedCount: number;
  totalCount: number;
  onClear: () => void;
  onDelete: () => void;
  onSelectAll: () => void;
  isDeleting?: boolean;
  deleteLabel?: string;
  className?: string;
}

export function BatchActionsBar({
  selectedCount,
  totalCount,
  onClear,
  onDelete,
  onSelectAll,
  isDeleting = false,
  deleteLabel = "Delete",
  className,
}: BatchActionsBarProps) {
  if (selectedCount === 0) return null;

  return (
    <div
      className={cn(
        "flex items-center gap-3 px-4 py-2.5 bg-brand/10 border border-brand/20 rounded-xl animate-in slide-in-from-top-2 duration-200",
        className
      )}
    >
      <span className="text-xs font-bold text-brand">
        {selectedCount} selected
      </span>
      <div className="h-4 w-px bg-border-subtle" />
      <button
        type="button"
        onClick={onSelectAll}
        className="text-xs text-text-muted hover:text-foreground transition-colors"
      >
        {selectedCount === totalCount ? "Deselect all" : "Select all"}
      </button>
      <div className="flex-1" />
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={onClear}
        className="text-text-muted hover:text-foreground h-7 px-2"
      >
        <X size={14} />
      </Button>
      <Button
        type="button"
        variant="destructive"
        size="sm"
        onClick={onDelete}
        disabled={isDeleting}
        className="h-7"
      >
        <Trash2 size={14} className="mr-1" />
        {isDeleting ? "Deleting..." : deleteLabel}
      </Button>
    </div>
  );
}

interface SelectableProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  indeterminate?: boolean;
  className?: string;
}

export function Selectable({ checked, onChange, indeterminate = false, className }: SelectableProps) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={indeterminate ? "mixed" : checked}
      onClick={(e) => {
        e.stopPropagation();
        onChange(!checked);
      }}
      className={cn(
        "flex-shrink-0 transition-all active:scale-90",
        checked || indeterminate ? "text-brand" : "text-text-muted hover:text-foreground",
        className
      )}
    >
      {checked ? (
        <CheckSquare size={16} />
      ) : indeterminate ? (
        <div className="relative">
          <Square size={16} />
          <div className="absolute inset-1.5 bg-brand rounded-sm" />
        </div>
      ) : (
        <Square size={16} />
      )}
    </button>
  );
}
