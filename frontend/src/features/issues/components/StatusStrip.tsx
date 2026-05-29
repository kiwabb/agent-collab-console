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
      className={cn(
        "relative overflow-hidden rounded-[28px] border p-6 transition-all duration-300 shadow-[0_24px_80px_rgba(0,0,0,0.4)]",
        isAbandoned 
          ? "border-border-subtle bg-slate-950/20 grayscale" 
          : "enterprise-panel border-border-subtle/40 bg-surface/70 backdrop-blur-xl",
      )}
    >
      {/* Visual Blueprint Grid Overlay */}
      <div aria-hidden className="agent-mesh-grid pointer-events-none absolute inset-0 opacity-[0.14] z-0" />
      
      {/* Decorative ambient background glows */}
      <div className="absolute -top-12 -right-12 w-48 h-48 bg-brand/10 rounded-full blur-[64px] pointer-events-none z-0" />
      {isRunning && (
        <div className="absolute -bottom-16 -left-16 w-56 h-56 bg-cyan-500/5 rounded-full blur-[80px] pointer-events-none z-0" />
      )}

      <div className="relative z-10 grid gap-6 xl:grid-cols-[minmax(0,1.2fr)_minmax(340px,0.8fr)_auto] xl:items-center">
        
        {/* Left Column: Metadata, Title & Branch Info */}
        <div className="min-w-0 flex flex-col gap-2.5">
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
            className="line-clamp-2 break-words text-2xl md:text-3xl font-black leading-tight tracking-[-0.04em] text-foreground bg-gradient-to-r from-foreground via-foreground to-text-secondary bg-clip-text"
            title={issue?.title ?? undefined}
          >
            {issue?.title ?? t("issue.command.loadingIssue")}
          </h1>

          {/* Active Git Branch Telemetry Tag */}
          {issue?.git_branch && (
            <div className="flex flex-wrap items-center gap-2 mt-1">
              <div className="flex items-center gap-1.5 text-xs font-mono font-bold text-cyan-400 bg-cyan-950/30 border border-cyan-800/40 px-2.5 py-0.5 rounded-full shadow-[0_0_12px_rgba(34,211,238,0.12)]">
                <GitBranch size={12} className="shrink-0 text-cyan-400 animate-pulse" />
                <span>{issue.git_branch}</span>
                {issue.git_merge_status && (
                  <span className="text-[10px] uppercase font-black bg-cyan-800/40 text-cyan-300 px-1.5 py-0.2 rounded-sm border border-cyan-700/30 ml-1">
                    {issue.git_merge_status}
                  </span>
                )}
              </div>
            </div>
          )}

          {isPaused && (
            <div className="mt-1 self-start rounded-xl border border-status-awaiting/30 bg-status-awaiting/10 px-3 py-1.5 text-xs font-bold uppercase tracking-wider text-status-awaiting shadow-[0_0_12px_rgba(234,179,8,0.08)]">
              {t("issue.command.pausedResumePhase", { phase: phase.phase ?? "unknown" })}
            </div>
          )}
          {isAbandoned && (
            <div className="mt-1 self-start rounded-xl border border-border-subtle bg-surface-input px-3 py-1.5 text-xs text-text-muted">
              {t("issue.command.abandonedHint")}
            </div>
          )}
        </div>

        {/* Center Column: Conductor Real-time Telemetry Monitor */}
        <div className={cn(
          "rounded-2xl border px-5 py-4 transition-all duration-300 relative overflow-hidden group shadow-md",
          phase.severity === "danger"
            ? "border-status-failed/40 bg-status-failed/5 shadow-[0_0_20px_rgba(239,68,68,0.06)]"
            : phase.severity === "warn"
              ? "border-status-awaiting/40 bg-status-awaiting/5 shadow-[0_0_20px_rgba(234,179,8,0.06)]"
              : "border-border-subtle bg-slate-900/30 backdrop-blur-md",
        )}>
          {/* Accent lighting for Conductor panel */}
          <div className={cn(
            "absolute top-0 left-0 w-1.5 h-full",
            isDone ? "bg-status-done" :
            isPaused ? "bg-status-awaiting" :
            isAbandoned ? "bg-text-muted" : "bg-brand animate-pulse"
          )} />

          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              {/* Dynamic Status Breathing Orb */}
              <div className="relative shrink-0 flex items-center justify-center">
                <div className={cn(
                  "w-3 h-3 rounded-full transition-all duration-300",
                  isDone ? "bg-status-done shadow-[0_0_12px_rgba(74,222,128,0.6)]" :
                  isPaused ? "bg-status-awaiting shadow-[0_0_12px_rgba(234,179,8,0.6)]" :
                  isAbandoned ? "bg-text-muted" : "bg-brand shadow-[0_0_14px_rgba(230,149,82,0.8)] animate-pulse"
                )} />
                {isRunning && (
                  <div className="absolute w-5 h-5 rounded-full border border-brand/40 animate-ping opacity-60 pointer-events-none" />
                )}
              </div>
              
              <div>
                <div className="text-[10px] uppercase tracking-[0.25em] font-black text-text-muted">{t("issue.command.conductorPhase")}</div>
                <div className="mt-1 font-mono text-sm font-bold text-foreground">
                  {isDone ? t("issue.command.complete") : phase.phase ?? t("issue.command.idle")}
                </div>
              </div>
            </div>
            
            <div className="text-right font-mono text-sm font-bold text-text-secondary bg-surface-input px-2 py-0.5 rounded-md border border-border-subtle/50">
              {isDone ? "✓" : phase.phaseDurationMs != null ? formatDuration(phase.phaseDurationMs) : "—"}
            </div>
          </div>

          <div className="mt-3 text-xs text-text-secondary leading-relaxed bg-surface/30 p-2 rounded-lg border border-border-subtle/30 font-sans italic">
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
          <div className="flex items-center gap-2 bg-slate-900/40 p-1.5 rounded-2xl border border-border-subtle/50 backdrop-blur-md">
            <Button 
              variant="outline" 
              size="sm" 
              onClick={isPaused ? onResume : onPause} 
              className={cn(
                "gap-2 rounded-xl border-none shadow-none cursor-pointer h-9 px-3.5 transition-all font-bold text-xs",
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
              className="gap-2 rounded-xl border-none bg-surface-raised hover:bg-surface-hover text-text-primary cursor-pointer h-9 px-3.5 transition-all font-bold text-xs"
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
              className="gap-2 rounded-xl h-9 border-status-failed/25 text-status-failed/90 bg-status-failed-bg hover:bg-status-failed/12 hover:border-status-failed/50 hover:text-status-failed cursor-pointer transition-all font-bold text-xs"
            >
              <Trash2 size={14} />
              {t("issue.command.reset")}
            </Button>

            <Button variant="outline" size="sm" className="gap-2 rounded-xl h-9 bg-surface-raised/40 hover:bg-surface-hover text-text-secondary hover:text-text-primary cursor-pointer transition-all border-border-subtle/40 text-xs font-bold">
              <FileText size={14} />
              {t("issue.command.backendLog")}
            </Button>
            
            <Button variant="ghost" size="sm" className="rounded-xl h-9 w-9 p-0 text-text-muted hover:text-foreground cursor-pointer transition-all">
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
