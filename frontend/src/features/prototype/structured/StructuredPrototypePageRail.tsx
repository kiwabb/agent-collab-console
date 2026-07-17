"use client";

import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { FileText, GripVertical } from "lucide-react";

import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

import { readStructuredPrototypePageDragData } from "./structuredPrototypeDrag";
import type { StructuredPrototypePage } from "./types";

interface Props {
  pages: StructuredPrototypePage[];
  activePageId: string;
  dragDisabled: boolean;
  selectionDisabled: boolean;
  onSelect: (pageId: string) => void;
}

export type StructuredPrototypePageDropIndicator = "top" | "bottom";

export function resolveStructuredPrototypePageDropIndicator(
  activeIndex: number | null,
  targetIndex: number,
): StructuredPrototypePageDropIndicator | null {
  if (activeIndex === null || activeIndex === targetIndex) return null;
  return activeIndex < targetIndex ? "bottom" : "top";
}

function SortablePageRailItem({
  page,
  index,
  activePageId,
  dragDisabled,
  selectionDisabled,
  onSelect,
}: {
  page: StructuredPrototypePage;
  index: number;
  activePageId: string;
  dragDisabled: boolean;
  selectionDisabled: boolean;
  onSelect: (pageId: string) => void;
}) {
  const { t } = useI18n();
  const {
    active,
    attributes,
    listeners,
    setActivatorNodeRef,
    setNodeRef,
    transform,
    transition,
    isDragging,
    isOver,
  } = useSortable({
    id: `page:${page.id}`,
    data: { kind: "page", pageId: page.id, index },
    disabled: dragDisabled,
  });
  const activePage = readStructuredPrototypePageDragData(active?.data.current);
  const dropIndicator = isOver
    ? resolveStructuredPrototypePageDropIndicator(activePage?.index ?? null, index)
    : null;
  return (
    <div
      ref={setNodeRef}
      className={cn(
        "relative grid min-h-13 w-full grid-cols-[minmax(0,1fr)_32px] border-l-2 transition-colors motion-reduce:transition-none",
        page.id === activePageId
          ? "border-brand bg-brand-bg"
          : "border-transparent bg-transparent hover:bg-surface-hover",
        isDragging && "opacity-35",
      )}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
      }}
      data-prototype-page-drop-indicator={dropIndicator ?? "none"}
    >
      {dropIndicator !== null && (
        <span
          className={cn(
            "pointer-events-none absolute inset-x-0 z-20 h-0.5 bg-brand",
            dropIndicator === "top" ? "top-0" : "bottom-0",
          )}
          data-prototype-page-drop-indicator-line={dropIndicator}
          aria-hidden
        />
      )}
      <button
        type="button"
        className="grid min-h-13 min-w-0 cursor-pointer grid-cols-[22px_minmax(0,1fr)] items-center gap-2 px-2 py-2 text-left disabled:cursor-not-allowed disabled:opacity-50"
        onClick={() => onSelect(page.id)}
        disabled={selectionDisabled}
        aria-current={page.id === activePageId ? "page" : undefined}
      >
        <span className="grid size-6 place-items-center text-text-faint">
          <FileText size={15} aria-hidden />
        </span>
        <span className="min-w-0">
          <strong className="block truncate text-xs font-semibold text-foreground">
            {page.title}
          </strong>
          <span className="mt-1 block truncate text-[10px] text-text-muted">{page.route}</span>
        </span>
      </button>
      <button
        ref={setActivatorNodeRef}
        type="button"
        className="grid min-h-13 cursor-grab place-items-center text-text-faint hover:bg-surface-hover hover:text-foreground active:cursor-grabbing disabled:cursor-not-allowed disabled:opacity-50"
        disabled={dragDisabled}
        {...attributes}
        {...listeners}
        aria-label={t("prototype.structured.canvas.drag", { name: page.title })}
      >
        <GripVertical size={15} aria-hidden />
      </button>
    </div>
  );
}

export function StructuredPrototypePageRail({
  pages,
  activePageId,
  dragDisabled,
  selectionDisabled,
  onSelect,
}: Props) {
  return (
    <div className="min-h-0 overflow-auto p-2">
      <SortableContext
        items={pages.map((page) => `page:${page.id}`)}
        strategy={verticalListSortingStrategy}
      >
        {pages.map((page, index) => (
          <SortablePageRailItem
            key={page.id}
            page={page}
            index={index}
            activePageId={activePageId}
            dragDisabled={dragDisabled}
            selectionDisabled={selectionDisabled}
            onSelect={onSelect}
          />
        ))}
      </SortableContext>
    </div>
  );
}
