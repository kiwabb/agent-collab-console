"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";

export function SecondaryAccordion({
  icon,
  title,
  summary,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  summary: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section className="overflow-hidden rounded-2xl border border-border-subtle bg-surface/88">
      <button
        type="button"
        onClick={() => setOpen((next) => !next)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <span className="flex min-w-0 items-center gap-3">
          <span className="text-brand">{icon}</span>
          <span>
            <span className="block text-sm font-bold text-foreground">{title}</span>
            <span className="block text-xs text-text-muted">{summary}</span>
          </span>
        </span>
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
      </button>
      <div className={cn("border-t border-border-subtle", !open && "hidden")}>
        {children}
      </div>
    </section>
  );
}
