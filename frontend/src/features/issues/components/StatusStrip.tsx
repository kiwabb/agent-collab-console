"use client";

import { Clock3, FileText, MoreHorizontal, Pause, Play, RotateCcw, Trash2, GitBranch, Terminal } from "lucide-react";

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
      data-density="command-header"
      className={cn(
        "relative overflow-hidden rounded-lg border p-3 transition-colors",
        isAbandoned 
          ? "border-border-subtle bg-slate-950/20 grayscale" 
          : "enterprise-panel border-border-subtle/60 bg-surface/90",
      )}
    >
      <div className="relative z-10 flex flex-col gap-3">
        <div className="grid gap-3 2xl:grid-cols-[minmax(0,1fr)_auto] 2xl:items-start">
          <div className="min-w-0 flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2 text-xs text-text-secondary/80">
              <StatusBadge kind={inferStatusKind(status)} label={t(STATUS_LABEL_KEY[status] ?? "issue.command.status.queued")} />
              <span className="font-mono bg-surface-input px-2 py-0.5 rounded-md text-text-muted text-[11px] border border-border-subtle/50">
                #{issue?.id.slice(0, 8) ?? t("issue.command.loading")}
              </span>
              {issue?.created_at && (
                <span className="hidden items-center gap-1 sm:inline-flex">
                  <span className="w-1.5 h-1.5 rounded-full bg-text-faint" />
                  {t("issue.command.created", { time: formatClock(issue.created_at, locale) })}
                </span>
              )}
              {issue?.updated_at && (
                <span className="hidden items-center gap-1 md:inline-flex">
                  <span className="w-1.5 h-1.5 rounded-full bg-text-faint" />
                  {t("issue.command.updated", { time: formatClock(issue.updated_at, locale) })}
                </span>
              )}
            </div>
            
            <h1
              className="line-clamp-1 break-words text-lg md:text-xl font-black leading-tight text-foreground 2xl:line-clamp-2"
              title={issue?.title ?? undefined}
            >
              {issue?.title ?? t("issue.command.loadingIssue")}
            </h1>

            <div className="flex flex-wrap items-center gap-2 text-xs text-text-muted">
              {issue?.git_branch && (
                <div className="flex min-w-0 items-center gap-1.5 font-mono font-bold text-brand bg-brand-muted/10 border border-brand/25 px-2 py-0.5 rounded-md">
                  <GitBranch size={12} className="shrink-0 text-brand" />
                  <span className="truncate">{issue.git_branch}</span>
                  {issue.git_merge_status && (
                    <span className="text-[10px] uppercase font-black bg-brand-muted/20 text-brand px-1.5 py-0.2 rounded-sm border border-brand/20">
                      {issue.git_merge_status}
                    </span>
                  )}
                </div>
              )}
              {isPaused && (
                <span className="rounded-md border border-status-awaiting/30 bg-status-awaiting/10 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider text-status-awaiting">
                  {t("issue.command.pausedResumePhase", { phase: phase.phase ?? "unknown" })}
                </span>
              )}
              {isAbandoned && (
                <span className="rounded-md border border-border-subtle bg-surface-input px-2 py-0.5 text-[11px] text-text-muted">
                  {t("issue.command.abandonedHint")}
                </span>
              )}
            </div>
          </div>

          <div data-density="command-actions" className="grid grid-cols-4 gap-1.5 2xl:flex 2xl:flex-wrap 2xl:items-center 2xl:justify-end">
            <Button 
              variant="outline" 
              size="sm" 
              onClick={isPaused ? onResume : onPause} 
              className={cn(
                "min-w-0 gap-1.5 rounded-md border-border-subtle shadow-none cursor-pointer h-8 px-2 transition-colors font-bold text-[11px]",
                isPaused 
                  ? "bg-brand text-background hover:bg-brand-strong" 
                  : "bg-surface-raised hover:bg-surface-hover text-text-primary"
              )}
            >
              {isPaused ? <Play size={13} fill="currentColor" /> : <Pause size={13} fill="currentColor" />}
              <span className="truncate">{isPaused ? t("issue.command.resume") : t("issue.command.pause")}</span>
            </Button>
            
            <Button 
              variant="outline" 
              size="sm" 
              onClick={onSteer} 
              className="min-w-0 gap-1.5 rounded-md border-border-subtle bg-surface-raised hover:bg-surface-hover text-text-primary cursor-pointer h-8 px-2 transition-colors font-bold text-[11px]"
            >
              <RotateCcw size={13} />
              <span className="truncate">{t("issue.command.restartSteer")}</span>
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={onReset}
              className="min-w-0 gap-1.5 rounded-md h-8 border-status-failed/25 text-status-failed/90 bg-status-failed-bg hover:bg-status-failed/12 hover:border-status-failed/50 hover:text-status-failed cursor-pointer transition-colors font-bold text-[11px]"
            >
              <Trash2 size={13} />
              <span className="truncate">{t("issue.command.reset")}</span>
            </Button>

            <Button variant="outline" size="sm" className="min-w-0 gap-1.5 rounded-md h-8 bg-surface-raised/40 hover:bg-surface-hover text-text-secondary hover:text-text-primary cursor-pointer transition-colors border-border-subtle/40 text-[11px] font-bold">
              <FileText size={13} />
              <span className="truncate">{t("issue.command.backendLog")}</span>
            </Button>
            
            <Button
              variant="ghost"
              size="sm"
              aria-label={t("issue.command.moreActions")}
              title={t("issue.command.moreActions")}
              className="hidden rounded-md h-8 w-8 p-0 text-text-muted hover:text-foreground cursor-pointer transition-colors 2xl:inline-flex"
            >
              <MoreHorizontal size={15} />
            </Button>
          </div>
        </div>

        <div
          data-density="conductor-strip"
          className={cn(
            "hidden rounded-lg border px-3 py-2 transition-colors sm:block",
            phase.severity === "danger"
              ? "border-status-failed/40 bg-status-failed/5"
              : phase.severity === "warn"
                ? "border-status-awaiting/40 bg-status-awaiting/5"
                : "border-border-subtle bg-surface-input/35",
          )}
        >
          <div className="min-w-0 flex items-center gap-3">
            <span
              className={cn(
                "size-2.5 shrink-0 rounded-full",
                isDone ? "bg-status-done" :
                isPaused ? "bg-status-awaiting" :
                isAbandoned ? "bg-text-muted" : "bg-brand"
              )}
            />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="text-[10px] uppercase tracking-wider font-black text-text-muted">
                  {t("issue.command.conductorPhase")}
                </span>
                <span className="font-mono text-sm font-bold text-foreground">
                  {isDone ? t("issue.command.complete") : phase.phase ?? t("issue.command.idle")}
                </span>
                <span className="inline-flex items-center gap-1 font-mono text-xs text-text-muted">
                  <Clock3 size={12} />
                  {isDone ? t("issue.command.complete") : phase.phaseDurationMs != null ? formatDuration(phase.phaseDurationMs) : "—"}
                </span>
                <span className="hidden min-w-0 items-center gap-1.5 font-mono text-xs text-text-muted sm:inline-flex">
                  <Terminal size={12} className="shrink-0 text-text-faint" />
                  <span className="shrink-0">{t("issue.command.activeTask")}</span>
                  <span className="truncate text-foreground font-bold">
                    {activeTask
                      ? `${activeTask.role}#${activeTask.id.slice(0, 6)} [${activeTask.status.toUpperCase()}]`
                      : t("issue.command.none")}
                  </span>
                </span>
              </div>
              <div className="mt-1 hidden text-xs leading-relaxed text-text-secondary sm:line-clamp-1">
                {phase.detail || t("issue.command.noConductorDetail")}
              </div>
            </div>
          </div>
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
