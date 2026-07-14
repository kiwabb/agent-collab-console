"use client";

import { FileText, GripVertical } from "lucide-react";

import { cn } from "@/lib/utils";

import type { StructuredPrototypePage } from "./types";

interface Props {
  pages: StructuredPrototypePage[];
  activePageId: string;
  onSelect: (pageId: string) => void;
}

export function StructuredPrototypePageRail({ pages, activePageId, onSelect }: Props) {
  return (
    <div className="min-h-0 overflow-auto p-2">
      {pages.map((page) => (
        <button
          key={page.id}
          type="button"
          className={cn(
            "mb-1 grid min-h-13 w-full cursor-pointer grid-cols-[22px_minmax(0,1fr)] items-center gap-2 rounded-md border px-2 py-2 text-left transition-colors",
            page.id === activePageId
              ? "border-brand-ring bg-brand-bg"
              : "border-transparent bg-transparent hover:bg-surface-hover",
          )}
          onClick={() => onSelect(page.id)}
          aria-current={page.id === activePageId ? "page" : undefined}
        >
          <span className="grid size-6 place-items-center text-text-faint">
            {page.id === activePageId ? (
              <FileText size={15} aria-hidden />
            ) : (
              <GripVertical size={15} aria-hidden />
            )}
          </span>
          <span className="min-w-0">
            <strong className="block truncate text-xs font-semibold text-foreground">
              {page.title}
            </strong>
            <span className="mt-1 block truncate text-[10px] text-text-muted">{page.route}</span>
          </span>
        </button>
      ))}
    </div>
  );
}
