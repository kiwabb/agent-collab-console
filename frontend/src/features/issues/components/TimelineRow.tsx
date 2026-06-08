"use client";

import { AlertCircle, CheckCircle2, HelpCircle, Lightbulb, Loader2, MessageCircle, Square } from "lucide-react";

import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";
import { formatTok, formatCost } from "@/lib/format";
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

const STATUS_LABEL_KEY: Record<DecisionTimelineItem["status"], string> = {
  running: "issue.command.timelineStatus.running",
  done: "issue.command.timelineStatus.done",
  failed: "issue.command.timelineStatus.failed",
  waiting: "issue.command.timelineStatus.waiting",
  info: "issue.command.timelineStatus.info",
};

export function TimelineRow({ item, onOpen }: Props) {
  const { locale, t } = useI18n();
  const Icon = item.kind === "user" ? MessageCircle : STATUS_ICON[item.status];
  const failed = item.status === "failed";
  const waiting = item.kind === "clarification";
  const title = item.titleKey ? t(item.titleKey, item.titleParams) : item.title;
  const roleLabel = item.role === "conductor"
    ? t("issue.command.actor.conductor")
    : item.role === "user"
      ? t("issue.command.actor.user")
      : item.role;
  const rationaleTitle = item.kind === "dispatch"
    ? t("issue.command.rationalePlan")
    : t("issue.command.rationale");
  const rationale = item.rationale ? formatRationale(item.rationale, t) : null;
  const summary = item.summaryKey ? t(item.summaryKey, item.summaryParams) : item.summary;

  return (
    <article
      id={`timeline-${item.id}`}
      className={cn(
        "rounded-lg border bg-surface-raised/70 p-3 transition-colors hover:border-brand/50 sm:p-4",
        failed && "border-status-failed/35 bg-status-failed/5",
        waiting && "border-status-awaiting/35 bg-status-awaiting/5",
        !failed && !waiting && "border-border-subtle",
      )}
    >
      <button type="button" onClick={onOpen} className="grid w-full grid-cols-[64px_minmax(0,1fr)] gap-3 text-left lg:grid-cols-[84px_minmax(0,1fr)_auto]">
        <div className="font-mono text-xs text-text-muted">
          {item.createdAt ? new Date(item.createdAt).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" }) : "—"}
        </div>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn(
              "inline-flex size-7 items-center justify-center rounded-md border",
              item.status === "failed" && "border-status-failed/30 bg-status-failed/10 text-status-failed",
              item.status === "done" && "border-status-done/30 bg-status-done/10 text-status-done",
              item.status === "running" && "border-status-running/30 bg-status-running/10 text-status-running",
              item.status === "waiting" && "border-status-awaiting/30 bg-status-awaiting/10 text-status-awaiting",
              item.status === "info" && "border-border-subtle bg-surface text-text-muted",
            )}>
              <Icon size={15} className={item.status === "running" ? "animate-spin" : undefined} />
            </span>
            <span className="font-mono text-xs font-bold uppercase text-brand">{roleLabel}</span>
            <span className="rounded-full border border-border-subtle px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-text-muted">
              {t(STATUS_LABEL_KEY[item.status])}
            </span>
            {item.durationMs != null && (
              <span className="font-mono text-xs text-text-muted">{formatDuration(item.durationMs)}</span>
            )}
          </div>
          <h3 className="mt-2 break-words text-sm font-bold text-foreground">{title}</h3>
          {summary && <p className="mt-1 whitespace-pre-wrap break-words text-xs leading-relaxed text-text-secondary">{summary}</p>}
        </div>
        <div className="col-span-2 flex flex-wrap items-center justify-between gap-2 border-t border-border-subtle/50 pt-2 lg:col-span-1 lg:flex-col lg:items-end lg:justify-start lg:border-t-0 lg:pt-0">
          {/* Cost/tokens badge for completed tasks */}
          {(() => {
            const lastRun = item.task?.last_run;
            if (!lastRun) return null;

            const cost = lastRun.total_cost_usd;
            const inputTokens = lastRun.input_tokens;
            const outputTokens = lastRun.output_tokens;

            if (cost == null && inputTokens == null && outputTokens == null) return null;

            const parts: string[] = [];
            if (cost != null) parts.push(formatCost(cost));
            if (inputTokens != null || outputTokens != null) {
              const inp = inputTokens ?? 0;
              const out = outputTokens ?? 0;
              parts.push(`${formatTok(inp + out)} tok`);
            }

            return (
              <span className="font-mono text-[10px] text-text-faint">
                {parts.join(" · ")}
              </span>
            );
          })()}
          <div className="text-xs font-semibold text-text-muted">{t("issue.command.details")}</div>
        </div>
      </button>

      {failed && item.why && (
        <div className="mt-3 rounded-lg border border-status-failed/25 bg-background/70 p-3">
          <div className="mb-1 text-[11px] font-black uppercase tracking-[0.18em] text-status-failed">{t("issue.command.why")}</div>
          <pre className="whitespace-pre-wrap break-words text-xs leading-relaxed text-text-secondary">{item.why}</pre>
        </div>
      )}

      {waiting && (
        <div className="mt-3 rounded-lg border border-status-awaiting/25 bg-status-awaiting/10 p-3 text-xs text-status-awaiting">
          {t("issue.command.waitingAnswerHint")}
        </div>
      )}

      {rationale && (
        <div className="mt-3 rounded-lg border border-brand/25 bg-brand-muted/10 p-3">
          <div className="mb-1 flex items-center gap-1.5 text-[11px] font-black uppercase tracking-[0.18em] text-brand">
            <Lightbulb size={12} />
            {rationaleTitle}
          </div>
          <p className="whitespace-pre-wrap text-xs leading-relaxed text-text-secondary">{rationale}</p>
        </div>
      )}

      <TimelineThinkingTurns turns={item.thinkingTurns} />
    </article>
  );
}

function formatRationale(value: string, t: (key: string) => string): string {
  return value
    .replaceAll("**Analysis:**", t("issue.command.rationaleAnalysis"))
    .replaceAll("**Plan:**", t("issue.command.rationaleSteps"))
    .replaceAll("`dispatch_batch`", "dispatch_batch");
}
