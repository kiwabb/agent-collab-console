"use client";

import { AlertCircle, CheckCircle2, HelpCircle, Lightbulb, Loader2, MessageCircle, Square } from "lucide-react";

import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";
import type { DecisionTimelineItem } from "../hooks/useDecisionTimeline";
import { TimelineThinkingTurns } from "./TimelineThinkingTurns";
import { formatDuration } from "./StatusStrip";

interface Props {
  item: DecisionTimelineItem;
  onOpen: () => void;
}

const STATUS_ICON = {
  running: Loader2,
  done: CheckCircle2,
  failed: AlertCircle,
  waiting: HelpCircle,
  info: Square,
};

export function TimelineRow({ item, onOpen }: Props) {
  const { locale, t } = useI18n();
  const Icon = item.kind === "user" ? MessageCircle : STATUS_ICON[item.status];
  const failed = item.status === "failed";
  const waiting = item.kind === "clarification";
  const title = item.titleKey ? t(item.titleKey, item.titleParams) : item.title;

  return (
    <article
      id={`timeline-${item.id}`}
      className={cn(
        "rounded-2xl border bg-surface-raised/70 p-4 transition-colors hover:border-brand/50",
        failed && "border-status-failed/35 bg-status-failed/5",
        waiting && "border-status-awaiting/35 bg-status-awaiting/5",
        !failed && !waiting && "border-border-subtle",
      )}
    >
      <button type="button" onClick={onOpen} className="grid w-full grid-cols-[84px_1fr_auto] gap-3 text-left">
        <div className="font-mono text-xs text-text-muted">
          {item.createdAt ? new Date(item.createdAt).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" }) : "—"}
        </div>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn(
              "inline-flex size-7 items-center justify-center rounded-xl border",
              item.status === "failed" && "border-status-failed/30 bg-status-failed/10 text-status-failed",
              item.status === "done" && "border-status-done/30 bg-status-done/10 text-status-done",
              item.status === "running" && "border-status-running/30 bg-status-running/10 text-status-running",
              item.status === "waiting" && "border-status-awaiting/30 bg-status-awaiting/10 text-status-awaiting",
              item.status === "info" && "border-border-subtle bg-surface text-text-muted",
            )}>
              <Icon size={15} className={item.status === "running" ? "animate-spin" : undefined} />
            </span>
            <span className="font-mono text-xs font-bold uppercase text-brand">{item.role}</span>
            <span className="rounded-full border border-border-subtle px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-text-muted">
              {item.status}
            </span>
            {item.durationMs != null && (
              <span className="font-mono text-xs text-text-muted">{formatDuration(item.durationMs)}</span>
            )}
          </div>
          <h3 className="mt-2 truncate text-sm font-bold text-foreground">{title}</h3>
          {item.summary && <p className="mt-1 line-clamp-2 text-xs text-text-secondary">{item.summary}</p>}
        </div>
        <div className="text-xs font-semibold text-text-muted">{t("issue.command.details")}</div>
      </button>

      {failed && item.why && (
        <div className="mt-3 rounded-xl border border-status-failed/25 bg-background/70 p-3">
          <div className="mb-1 text-[11px] font-black uppercase tracking-[0.18em] text-status-failed">{t("issue.command.why")}</div>
          <pre className="max-h-36 overflow-auto whitespace-pre-wrap text-xs leading-relaxed text-text-secondary">{item.why}</pre>
        </div>
      )}

      {waiting && (
        <div className="mt-3 rounded-xl border border-status-awaiting/25 bg-status-awaiting/10 p-3 text-xs text-status-awaiting">
          {t("issue.command.waitingAnswerHint")}
        </div>
      )}

      {item.rationale && (
        <div className="mt-3 rounded-xl border border-brand/25 bg-brand-muted/10 p-3">
          <div className="mb-1 flex items-center gap-1.5 text-[11px] font-black uppercase tracking-[0.18em] text-brand">
            <Lightbulb size={12} />
            {t("issue.command.rationale")}
          </div>
          <p className="whitespace-pre-wrap text-xs leading-relaxed text-text-secondary">{item.rationale}</p>
        </div>
      )}

      <TimelineThinkingTurns turns={item.thinkingTurns} />
    </article>
  );
}
