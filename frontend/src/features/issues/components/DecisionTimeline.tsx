"use client";

import { useState } from "react";
import { History } from "lucide-react";

import type { DecisionTimelineItem } from "../hooks/useDecisionTimeline";
import { TimelineRow } from "./TimelineRow";

interface Props {
  items: DecisionTimelineItem[];
  onOpenItem: (item: DecisionTimelineItem) => void;
}

export function DecisionTimeline({ items, onOpenItem }: Props) {
  const [expanded, setExpanded] = useState(false);
  const collapsedCount = items.length > 20 ? items.length - 10 : 0;
  const visible = collapsedCount > 0 && !expanded ? items.slice(-10) : items;

  return (
    <section className="rounded-[28px] border border-border-subtle bg-surface/88 p-4 shadow-[0_24px_80px_rgba(2,6,23,0.08)]" data-decision-timeline>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-[11px] font-black uppercase tracking-[0.2em] text-text-muted">
            <History size={15} />
            Decision timeline
          </div>
          <p className="mt-1 text-sm text-text-secondary">Every conductor dispatch, question, memory retrieval, and user interruption.</p>
        </div>
        <div className="font-mono text-xs text-text-muted">{items.length} events</div>
      </div>

      {collapsedCount > 0 && !expanded && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="mb-3 w-full rounded-2xl border border-dashed border-border-subtle bg-surface-raised/60 px-4 py-3 text-sm text-text-muted hover:text-foreground"
        >
          ... {collapsedCount} older conductor events hidden. Show all.
        </button>
      )}

      {items.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border-subtle bg-surface-input/40 px-6 py-12 text-center text-sm text-text-muted">
          暂无 Conductor 决策历史
        </div>
      ) : (
        <div className="space-y-3">
          {visible.map((item) => (
            <TimelineRow key={item.id} item={item} onOpen={() => onOpenItem(item)} />
          ))}
        </div>
      )}
    </section>
  );
}
