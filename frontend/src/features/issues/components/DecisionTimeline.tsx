"use client";

import { useState } from "react";
import { CheckCircle2, History } from "lucide-react";

import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { useI18n } from "@/providers/I18nProvider";
import type { DecisionTimelineItem } from "../hooks/useDecisionTimeline";
import { TimelineRow } from "./TimelineRow";
import { deriveTimelineExecutionSummary } from "./deriveTimelineExecutionSummary";

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
  const executionSummary = deriveTimelineExecutionSummary(items);

  return (
    <section className="rounded-lg border border-border-subtle bg-surface/90 p-3" data-decision-timeline>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[11px] font-black uppercase tracking-[0.2em] text-text-muted">
            <History size={15} />
            {t("issue.command.timelineTitle")}
          </div>
          <p className="mt-1 text-sm leading-relaxed text-text-secondary">{t("issue.command.timelineDescription")}</p>
        </div>
        <div className="shrink-0 rounded-md border border-border-subtle bg-surface-input px-2 py-1 font-mono text-xs text-text-muted">
          {t("issue.command.eventCount", { count: items.length })}
        </div>
      </div>

      {(executionSummary.developmentDispatched > 0 || executionSummary.qaDone > 0 || executionSummary.finalized) && (
        <div className="mb-3 flex flex-wrap gap-2" data-timeline-execution-summary>
          {executionSummary.developmentDispatched > 0 && (
            <span className="inline-flex items-center gap-1.5 rounded-md border border-status-done/25 bg-status-done/10 px-2.5 py-1 text-xs font-semibold text-status-done">
              <CheckCircle2 size={13} />
              {t("issue.command.executionSummary.devDispatchCount", { count: executionSummary.developmentDispatched })}
            </span>
          )}
          {executionSummary.qaDone > 0 && (
            <span className="inline-flex items-center gap-1.5 rounded-md border border-status-done/25 bg-status-done/10 px-2.5 py-1 text-xs font-semibold text-status-done">
              <CheckCircle2 size={13} />
              {t("issue.command.executionSummary.qaCount", { count: executionSummary.qaDone })}
            </span>
          )}
          {executionSummary.finalized && (
            <span className="inline-flex items-center gap-1.5 rounded-md border border-brand/25 bg-brand-muted/10 px-2.5 py-1 text-xs font-semibold text-brand">
              <CheckCircle2 size={13} />
              {t("issue.command.executionSummary.finalized")}
            </span>
          )}
        </div>
      )}

      {collapsedCount > 0 && !expanded && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="mb-3 w-full rounded-lg border border-dashed border-border-subtle bg-surface-raised/60 px-4 py-3 text-sm text-text-muted hover:text-foreground"
        >
          {t("issue.command.showOlder", { count: collapsedCount })}
        </button>
      )}

      {items.length === 0 && !liveThinking ? (
        <div className="rounded-lg border border-dashed border-border-subtle bg-surface-input/40 px-6 py-12 text-center text-sm text-text-muted">
          {t("issue.command.emptyTimeline")}
        </div>
      ) : (
        <div className="space-y-2.5">
          {visible.map((item) => (
            <TimelineRow key={item.id} item={item} onOpen={() => onOpenItem(item)} />
          ))}
          {liveThinking && (
            <div className="motion-essential relative overflow-hidden rounded-lg border border-brand/30 bg-brand-muted/10 p-4">
              <span
                aria-hidden
                className="pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-brand/70 to-transparent"
              />
              <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-black uppercase tracking-[0.18em] text-brand">
                <AgentThinkingIndicator phase="thinking" size={12} />
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
