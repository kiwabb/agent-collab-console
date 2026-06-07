"use client";

import { FileText, MoreHorizontal, Pause, Play, RotateCcw, Trash2, GitBranch, Terminal } from "lucide-react";

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
  const isRunning = phase.state?.conductor_status === "running" && !isDone && !isAbandoned;

  return (
    <section
      data-density="command-header"
      className={cn(
        "relative overflow-hidden rounded-lg border p-4 transition-colors",
        isAbandoned 
          ? "border-border-subtle bg-slate-950/20 grayscale" 
          : "enterprise-panel border-border-subtle/60 bg-surface/90",
      )}
    >
      <div className="relative z-10 grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.72fr)_auto] xl:items-center">
        
        {/* Left Column: Metadata, Title & Branch Info */}
        <div className="min-w-0 flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2 text-xs text-text-secondary/80">
            <StatusBadge kind={inferStatusKind(status)} label={t(STATUS_LABEL_KEY[status] ?? "issue.command.status.queued")} />
            <span className="font-mono bg-surface-input px-2 py-0.5 rounded-md text-text-muted text-[11px] border border-border-subtle/50">
              #{issue?.id.slice(0, 8) ?? t("issue.command.loading")}
            </span>
            {issue?.created_at && (
              <span className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-text-faint" />
                {t("issue.command.created", { time: formatClock(issue.created_at, locale) })}
              </span>
            )}
            {issue?.updated_at && (
              <span className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-text-faint" />
                {t("issue.command.updated", { time: formatClock(issue.updated_at, locale) })}
              </span>
            )}
          </div>
          
          <h1
            className="line-clamp-2 break-words text-xl md:text-2xl font-black leading-tight text-foreground"
            title={issue?.title ?? undefined}
          >
            {issue?.title ?? t("issue.command.loadingIssue")}
          </h1>

          {/* Active Git Branch Telemetry Tag */}
          {issue?.git_branch && (
            <div className="flex flex-wrap items-center gap-2 mt-1">
              <div className="flex items-center gap-1.5 text-xs font-mono font-bold text-brand bg-brand-muted/10 border border-brand/25 px-2.5 py-0.5 rounded-md">
                <GitBranch size={12} className="shrink-0 text-brand" />
                <span>{issue.git_branch}</span>
                {issue.git_merge_status && (
                  <span className="text-[10px] uppercase font-black bg-brand-muted/20 text-brand px-1.5 py-0.2 rounded-sm border border-brand/20 ml-1">
                    {issue.git_merge_status}
                  </span>
                )}
              </div>
            </div>
          )}

          {isPaused && (
            <div className="mt-1 self-start rounded-md border border-status-awaiting/30 bg-status-awaiting/10 px-3 py-1.5 text-xs font-bold uppercase tracking-wider text-status-awaiting">
              {t("issue.command.pausedResumePhase", { phase: phase.phase ?? "unknown" })}
            </div>
          )}
          {isAbandoned && (
            <div className="mt-1 self-start rounded-md border border-border-subtle bg-surface-input px-3 py-1.5 text-xs text-text-muted">
              {t("issue.command.abandonedHint")}
            </div>
          )}
        </div>

        {/* Center Column: Conductor Real-time Telemetry Monitor */}
        <div className={cn(
          "rounded-lg border px-4 py-3 transition-colors relative overflow-hidden group",
          phase.severity === "danger"
            ? "border-status-failed/40 bg-status-failed/5"
            : phase.severity === "warn"
              ? "border-status-awaiting/40 bg-status-awaiting/5"
              : "border-border-subtle bg-surface-input/35",
        )}>
          {/* Accent lighting for Conductor panel */}
          <div className={cn(
            "absolute top-0 left-0 w-1 h-full",
            isDone ? "bg-status-done" :
            isPaused ? "bg-status-awaiting" :
            isAbandoned ? "bg-text-muted" : "bg-brand"
          )} />

          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              {/* Dynamic Status Breathing Orb */}
              <div className="relative shrink-0 flex items-center justify-center">
                <div className={cn(
                  "w-2.5 h-2.5 rounded-full transition-colors",
                  isDone ? "bg-status-done" :
                  isPaused ? "bg-status-awaiting" :
                  isAbandoned ? "bg-text-muted" : "bg-brand"
                )} />
              </div>
              
              <div>
                <div className="text-[10px] uppercase tracking-wider font-black text-text-muted">{t("issue.command.conductorPhase")}</div>
                <div className="mt-1 font-mono text-sm font-bold text-foreground">
                  {isDone ? t("issue.command.complete") : phase.phase ?? t("issue.command.idle")}
                </div>
              </div>
            </div>
            
            <div className="text-right font-mono text-sm font-bold text-text-secondary bg-surface-input px-2 py-0.5 rounded-md border border-border-subtle/50">
              {isDone ? t("issue.command.complete") : phase.phaseDurationMs != null ? formatDuration(phase.phaseDurationMs) : "—"}
            </div>
          </div>

          <div className="mt-3 text-xs text-text-secondary leading-relaxed bg-surface/50 p-2 rounded-md border border-border-subtle/30 font-sans">
            {phase.detail || t("issue.command.noConductorDetail")}
          </div>

          <div className="mt-3 flex items-center gap-1.5 text-xs text-text-muted font-mono border-t border-border-subtle/30 pt-2.5">
            <Terminal size={12} className="shrink-0 text-text-faint" />
            <span>{t("issue.command.activeTask")}</span>
            <span className="text-foreground font-bold">
              {activeTask 
                ? `${activeTask.role}#${activeTask.id.slice(0, 6)} [${activeTask.status.toUpperCase()}]` 
                : t("issue.command.none")}
            </span>
          </div>
        </div>

        {/* Right Column: Integrated Frosted Action Button Group */}
        <div className="flex flex-wrap items-center justify-start gap-2.5 xl:justify-end xl:pl-4">
          <div className="flex items-center gap-2 bg-surface-input/35 p-1.5 rounded-lg border border-border-subtle/50">
            <Button 
              variant="outline" 
              size="sm" 
              onClick={isPaused ? onResume : onPause} 
              className={cn(
                "gap-2 rounded-md border-none shadow-none cursor-pointer h-9 px-3.5 transition-colors font-bold text-xs",
                isPaused 
                  ? "bg-brand text-background hover:bg-brand-strong" 
                  : "bg-surface-raised hover:bg-surface-hover text-text-primary"
              )}
            >
              {isPaused ? <Play size={14} fill="currentColor" /> : <Pause size={14} fill="currentColor" />}
              {isPaused ? t("issue.command.resume") : t("issue.command.pause")}
            </Button>
            
            <Button 
              variant="outline" 
              size="sm" 
              onClick={onSteer} 
              className="gap-2 rounded-md border-none bg-surface-raised hover:bg-surface-hover text-text-primary cursor-pointer h-9 px-3.5 transition-colors font-bold text-xs"
            >
              <RotateCcw size={14} />
              {t("issue.command.restartSteer")}
            </Button>
          </div>

          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="sm"
              onClick={onReset}
              className="gap-2 rounded-md h-9 border-status-failed/25 text-status-failed/90 bg-status-failed-bg hover:bg-status-failed/12 hover:border-status-failed/50 hover:text-status-failed cursor-pointer transition-colors font-bold text-xs"
            >
              <Trash2 size={14} />
              {t("issue.command.reset")}
            </Button>

            <Button variant="outline" size="sm" className="gap-2 rounded-md h-9 bg-surface-raised/40 hover:bg-surface-hover text-text-secondary hover:text-text-primary cursor-pointer transition-colors border-border-subtle/40 text-xs font-bold">
              <FileText size={14} />
              {t("issue.command.backendLog")}
            </Button>
            
            <Button variant="ghost" size="sm" className="rounded-md h-9 w-9 p-0 text-text-muted hover:text-foreground cursor-pointer transition-colors">
              <MoreHorizontal size={16} />
            </Button>
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
