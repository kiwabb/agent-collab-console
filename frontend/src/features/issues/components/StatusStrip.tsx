"use client";

import { Clock3, Pause, Play, RotateCcw, Trash2, GitBranch, Terminal } from "lucide-react";

import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
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
  const conductorStatus = phase.state?.conductor_status;
  const isConductorDone = conductorStatus === "success" || phase.phase === "done";
  const status = issue?.status === "open" && (issue.current_phase === "done" || issue.current_phase === "completed")
    ? "completed"
    : !issue && isConductorDone
    ? "completed"
    : issue?.status ?? "open";
  const isPaused = conductorStatus === "paused" || status === "awaiting_approval";
  const isDone = status === "completed" || issue?.current_phase === "done" || isConductorDone;
  const isAbandoned = status === "abandoned" || issue?.git_merge_status === "abandoned";
  const isConductorActive = !isDone && !isPaused && !isAbandoned && (conductorStatus === "running" || Boolean(phase.phase));
  const conductorMotionPhase = isConductorActive ? phase.phase ?? "working" : isPaused ? "paused" : "idle";

  return (
    <section
      data-density="command-header"
      className={cn(
        "relative rounded-lg border p-2.5 transition-colors",
        isAbandoned
          ? "border-border-subtle bg-slate-950/20 grayscale"
          : "enterprise-panel border-border-subtle/60 bg-surface/90",
      )}
    >
      <div className="relative z-10 flex flex-col gap-2.5">
        <div className="grid gap-2.5 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-start">
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
              className="break-words text-base font-black leading-snug text-foreground md:text-lg"
              title={issue?.title ?? undefined}
            >
              {issue?.title ?? t("issue.command.loadingIssue")}
            </h1>

            <div className="flex flex-wrap items-center gap-2 text-xs text-text-muted">
              {issue?.git_branch && (
                <div className="flex max-w-full min-w-0 items-center gap-1.5 rounded-md border border-brand/25 bg-brand-muted/10 px-2 py-0.5 font-mono font-bold text-brand">
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

          <div data-density="command-actions" className="grid grid-cols-3 gap-1.5 sm:max-w-[420px] xl:flex xl:flex-wrap xl:items-center xl:justify-end">
            <Button
              variant="outline"
              size="sm"
              onClick={isPaused ? onResume : onPause}
              className={cn(
                "min-w-0 gap-1.5 rounded-md border-border-subtle px-2 text-[11px] font-bold shadow-none transition-colors cursor-pointer h-8",
                isPaused
                  ? "bg-brand text-background hover:bg-brand-strong"
                  : "bg-surface-raised text-text-primary hover:bg-surface-hover",
              )}
            >
              {isPaused ? <Play size={13} fill="currentColor" /> : <Pause size={13} fill="currentColor" />}
              <span className="truncate">{isPaused ? t("issue.command.resume") : t("issue.command.pause")}</span>
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={onSteer}
              className="min-w-0 gap-1.5 rounded-md border-border-subtle bg-surface-raised px-2 text-[11px] font-bold text-text-primary transition-colors hover:bg-surface-hover cursor-pointer h-8"
            >
              <RotateCcw size={13} />
              <span className="truncate">{t("issue.command.restartSteer")}</span>
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={onReset}
              className="min-w-0 gap-1.5 rounded-md border-status-failed/25 bg-status-failed-bg px-2 text-[11px] font-bold text-status-failed/90 transition-colors hover:border-status-failed/50 hover:bg-status-failed/12 hover:text-status-failed cursor-pointer h-8"
            >
              <Trash2 size={13} />
              <span className="truncate">{t("issue.command.reset")}</span>
            </Button>
          </div>
        </div>

        <div
          data-density="conductor-strip"
          className={cn(
            "relative overflow-hidden rounded-md border px-2.5 py-2 transition-colors",
            phase.severity === "danger"
              ? "border-status-failed/40 bg-status-failed/5"
              : phase.severity === "warn"
                ? "border-status-awaiting/40 bg-status-awaiting/5"
                : "border-border-subtle bg-surface-input/35",
            isConductorActive && "border-brand/35 bg-brand-muted/10",
              )}
        >
          {isConductorActive && (
            <span
              aria-hidden
              className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-brand/70 to-transparent"
            />
          )}
          <div className="grid gap-2 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] lg:items-start">
            <div className="min-w-0 flex items-start gap-2">
              <span className="mt-0.5 flex size-4 shrink-0 items-center justify-center">
                {isConductorActive ? (
                  <AgentThinkingIndicator phase={conductorMotionPhase} size={14} />
                ) : (
                  <span
                    className={cn(
                      "size-2.5 rounded-full",
                      isDone ? "bg-status-done" :
                      isPaused ? "bg-status-awaiting" :
                      isAbandoned ? "bg-text-muted" : "bg-brand",
                    )}
                  />
                )}
              </span>
              <div className="min-w-0 space-y-1">
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
                </div>
                <div className="flex min-w-0 items-start gap-1.5 font-mono text-xs text-text-muted">
                  <Terminal size={12} className="mt-0.5 shrink-0 text-text-faint" />
                  <span className="shrink-0">{t("issue.command.activeTask")}</span>
                  <span className="min-w-0 break-all font-bold text-foreground">
                    {activeTask
                      ? `${activeTask.role}#${activeTask.id.slice(0, 6)} [${activeTask.status.toUpperCase()}]`
                      : t("issue.command.none")}
                  </span>
                </div>
              </div>
            </div>
            <p data-density="conductor-detail" className="min-w-0 whitespace-pre-wrap break-words rounded-md border border-border-subtle/50 bg-background/45 px-2.5 py-1.5 text-xs leading-relaxed text-text-secondary">
              {phase.detail || t("issue.command.noConductorDetail")}
            </p>
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
