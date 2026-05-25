"use client";

import { useState } from "react";
import { History, Loader2 } from "lucide-react";

import { useI18n } from "@/providers/I18nProvider";
import type { DecisionTimelineItem } from "../hooks/useDecisionTimeline";
import { TimelineRow } from "./TimelineRow";

interface Props {
  items: DecisionTimelineItem[];
  onOpenItem: (item: DecisionTimelineItem) => void;
  liveThinking?: string;
}

export function DecisionTimeline({ items, onOpenItem, liveThinking }: Props) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const collapsedCount = items.length > 20 ? items.length - 10 : 0;
  const visible = collapsedCount > 0 && !expanded ? items.slice(-10) : items;

  return (
    <section className="rounded-[28px] border border-border-subtle bg-surface/88 p-4 shadow-[0_24px_80px_rgba(2,6,23,0.08)]" data-decision-timeline>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-[11px] font-black uppercase tracking-[0.2em] text-text-muted">
            <History size={15} />
            {t("issue.command.timelineTitle")}
          </div>
          <p className="mt-1 text-sm text-text-secondary">{t("issue.command.timelineDescription")}</p>
        </div>
        <div className="font-mono text-xs text-text-muted">{t("issue.command.eventCount", { count: items.length })}</div>
      </div>

      {collapsedCount > 0 && !expanded && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="mb-3 w-full rounded-2xl border border-dashed border-border-subtle bg-surface-raised/60 px-4 py-3 text-sm text-text-muted hover:text-foreground"
        >
          {t("issue.command.showOlder", { count: collapsedCount })}
        </button>
      )}

      {items.length === 0 && !liveThinking ? (
        <div className="rounded-2xl border border-dashed border-border-subtle bg-surface-input/40 px-6 py-12 text-center text-sm text-text-muted">
          {t("issue.command.emptyTimeline")}
        </div>
      ) : (
        <div className="space-y-3">
          {visible.map((item) => (
            <TimelineRow key={item.id} item={item} onOpen={() => onOpenItem(item)} />
          ))}
          {liveThinking && (
            <div className="rounded-2xl border border-brand/30 bg-brand-muted/10 p-4">
              <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-black uppercase tracking-[0.18em] text-brand">
                <Loader2 size={12} className="animate-spin" />
                {t("issue.command.liveThinking")}
              </div>
              <p className="whitespace-pre-wrap text-xs leading-relaxed text-text-secondary">{liveThinking}</p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
