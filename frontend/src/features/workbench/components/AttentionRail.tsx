"use client";

import Link from "next/link";
import { AlertTriangle, CheckCircle2, HelpCircle, Radio } from "lucide-react";

import type {
  AttentionItem,
  AttentionKind,
} from "@/features/workbench/interaction/interactionState";
import { cn } from "@/lib/utils";

const ICONS: Record<AttentionKind, typeof CheckCircle2> = {
  approval: CheckCircle2,
  failure: AlertTriangle,
  running: Radio,
  question: HelpCircle,
};

export function AttentionRail({ items }: { items: AttentionItem[] }) {
  if (items.length === 0) return null;

  return (
    <div className="mx-3 mb-3 border-y border-border-subtle bg-surface px-3 py-2">
      <div className="mb-2 flex items-center justify-between text-[10px] font-mono uppercase tracking-[0.18em] text-text-muted">
        <span>attention</span>
        <span>{items.length}</span>
      </div>
      <div className="flex gap-2 overflow-x-auto">
        {items.map((item) => {
          const Icon = ICONS[item.kind];
          return (
            <Link
              key={`${item.kind}:${item.id}`}
              href={item.href}
              className={cn(
                "flex min-w-[210px] items-center gap-2 rounded-xl border border-border-subtle bg-surface-raised/70 px-3 py-2 text-left",
                "hover:border-brand/40 hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/50",
              )}
            >
              <Icon className="size-4 shrink-0 text-brand" />
              <span className="min-w-0">
                <span className="block truncate text-[12px] font-semibold text-foreground">
                  {item.title}
                </span>
                <span className="block truncate text-[10px] text-text-muted">{item.detail}</span>
              </span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
