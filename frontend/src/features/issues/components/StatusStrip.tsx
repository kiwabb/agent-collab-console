"use client";

import { FileText, MoreHorizontal, Pause, Play, RotateCcw, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { StatusBadge, inferStatusKind } from "@/components/ui/status-badge";
import type { CodexIssue, CodexTask } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";
import type { ConductorPhaseView } from "../hooks/useConductorPhase";

interface Props {
  issue: CodexIssue | null;
  phase: ConductorPhaseView;
  activeTask: CodexTask | null;
  onPause: () => void;
  onResume: () => void;
  onSteer: () => void;
  onReset: () => void;
}

const STATUS_LABEL_KEY: Record<string, string> = {
  open: "issue.command.status.queued",
  in_progress: "issue.command.status.running",
  completed: "issue.command.status.done",
  failed: "issue.command.status.failed",
  awaiting_approval: "issue.command.status.paused",
  awaiting_review: "issue.command.status.awaitingReview",
  abandoned: "issue.command.status.abandoned",
};

export function StatusStrip({ issue, phase, activeTask, onPause, onResume, onSteer, onReset }: Props) {
  const { locale, t } = useI18n();
  const status = issue?.status === "open" && (issue.current_phase === "done" || issue.current_phase === "completed")
    ? "completed"
    : issue?.status ?? "open";
  const isPaused = phase.state?.conductor_status === "paused" || status === "awaiting_approval";
  const isDone = status === "completed" || issue?.current_phase === "done";
  const isAbandoned = status === "abandoned" || issue?.git_merge_status === "abandoned";

  return (
    <section
      className={cn(
        "relative overflow-hidden rounded-[28px] border px-5 py-4 shadow-[0_24px_80px_rgba(2,6,23,0.12)]",
        isAbandoned ? "border-border-subtle bg-surface-raised grayscale" : "border-border-subtle bg-surface/90",
      )}
    >
      <div aria-hidden className="agent-mesh-grid pointer-events-none absolute inset-0 opacity-[0.08]" />
      <div className="relative grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)_auto] xl:items-center">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-text-muted">
            <StatusBadge kind={inferStatusKind(status)} label={t(STATUS_LABEL_KEY[status] ?? "issue.command.status.queued")} />
            <span className="font-mono">#{issue?.id.slice(0, 8) ?? t("issue.command.loading")}</span>
            {issue?.created_at && <span>{t("issue.command.created", { time: formatClock(issue.created_at, locale) })}</span>}
            {issue?.updated_at && <span>{t("issue.command.updated", { time: formatClock(issue.updated_at, locale) })}</span>}
          </div>
          <h1 className="truncate text-2xl font-black tracking-[-0.04em] text-foreground">
            {issue?.title ?? t("issue.command.loadingIssue")}
          </h1>
          {isPaused && (
            <div className="mt-2 rounded-xl border border-status-awaiting/30 bg-status-awaiting/10 px-3 py-2 text-xs font-bold uppercase tracking-wider text-status-awaiting">
              {t("issue.command.pausedResumePhase", { phase: phase.phase ?? "unknown" })}
            </div>
          )}
          {isAbandoned && (
            <div className="mt-2 rounded-xl border border-border-subtle bg-surface-input px-3 py-2 text-xs text-text-muted">
              {t("issue.command.abandonedHint")}
            </div>
          )}
        </div>

        <div className={cn(
          "rounded-2xl border px-4 py-3",
          phase.severity === "danger"
            ? "border-status-failed/40 bg-status-failed/10"
            : phase.severity === "warn"
              ? "border-status-awaiting/40 bg-status-awaiting/10"
              : "border-border-subtle bg-surface-raised/70",
        )}>
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-[10px] uppercase tracking-[0.2em] text-text-muted">{t("issue.command.conductorPhase")}</div>
              <div className="mt-1 font-mono text-sm font-bold text-foreground">
                {isDone ? t("issue.command.complete") : phase.phase ?? t("issue.command.idle")}
              </div>
            </div>
            <div className="text-right font-mono text-sm text-text-secondary">
              {isDone ? "✓" : phase.phaseDurationMs != null ? formatDuration(phase.phaseDurationMs) : "—"}
            </div>
          </div>
          <div className="mt-2 text-xs text-text-muted">
            {phase.detail || t("issue.command.noConductorDetail")}
          </div>
          <div className="mt-2 text-xs text-text-secondary">
            {t("issue.command.activeTask")}
            <span className="font-mono text-foreground">
              {activeTask ? `${activeTask.role}#${activeTask.id.slice(0, 6)} ${activeTask.status}` : t("issue.command.none")}
            </span>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-start gap-2 xl:justify-end">
          <Button variant="outline" size="sm" onClick={isPaused ? onResume : onPause} className="gap-2 rounded-xl">
            {isPaused ? <Play size={14} /> : <Pause size={14} />}
            {isPaused ? t("issue.command.resume") : t("issue.command.pause")}
          </Button>
          <Button variant="outline" size="sm" onClick={onSteer} className="gap-2 rounded-xl">
            <RotateCcw size={14} />
            {t("issue.command.restartSteer")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={onReset}
            className="gap-2 rounded-xl border-status-failed/40 text-status-failed hover:bg-status-failed/10 hover:border-status-failed/60"
          >
            <Trash2 size={14} />
            {t("issue.command.reset")}
          </Button>
          <Button variant="outline" size="sm" className="gap-2 rounded-xl">
            <FileText size={14} />
            {t("issue.command.backendLog")}
          </Button>
          <Button variant="ghost" size="sm" className="rounded-xl">
            <MoreHorizontal size={16} />
          </Button>
        </div>
      </div>
    </section>
  );
}

function formatClock(iso: string, locale: string): string {
  return new Date(iso).toLocaleString(locale, { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function formatDuration(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes < 60) return `${minutes}m ${String(rest).padStart(2, "0")}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}
