"use client";

import { FileText, MoreHorizontal, Pause, Play, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { StatusBadge, inferStatusKind } from "@/components/ui/status-badge";
import type { CodexIssue, CodexTask } from "@/lib/types";
import { cn } from "@/lib/utils";
import type { ConductorPhaseView } from "../hooks/useConductorPhase";

interface Props {
  issue: CodexIssue | null;
  phase: ConductorPhaseView;
  activeTask: CodexTask | null;
  onPause: () => void;
  onResume: () => void;
  onSteer: () => void;
}

const STATUS_LABEL: Record<string, string> = {
  open: "Queued",
  in_progress: "Running",
  completed: "Done",
  failed: "Failed",
  awaiting_approval: "Paused",
  awaiting_review: "Awaiting review",
  abandoned: "Abandoned",
};

export function StatusStrip({ issue, phase, activeTask, onPause, onResume, onSteer }: Props) {
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
            <StatusBadge kind={inferStatusKind(status)} label={STATUS_LABEL[status] ?? status} />
            <span className="font-mono">#{issue?.id.slice(0, 8) ?? "loading"}</span>
            {issue?.created_at && <span>created {formatClock(issue.created_at)}</span>}
            {issue?.updated_at && <span>updated {formatClock(issue.updated_at)}</span>}
          </div>
          <h1 className="truncate text-2xl font-black tracking-[-0.04em] text-foreground">
            {issue?.title ?? "Loading issue"}
          </h1>
          {isPaused && (
            <div className="mt-2 rounded-xl border border-status-awaiting/30 bg-status-awaiting/10 px-3 py-2 text-xs font-bold uppercase tracking-wider text-status-awaiting">
              Paused · resume phase: {phase.phase ?? "unknown"}
            </div>
          )}
          {isAbandoned && (
            <div className="mt-2 rounded-xl border border-border-subtle bg-surface-input px-3 py-2 text-xs text-text-muted">
              This issue is abandoned. Timeline and artifacts remain read-only.
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
              <div className="text-[10px] uppercase tracking-[0.2em] text-text-muted">Conductor phase</div>
              <div className="mt-1 font-mono text-sm font-bold text-foreground">
                {isDone ? "complete" : phase.phase ?? "idle"}
              </div>
            </div>
            <div className="text-right font-mono text-sm text-text-secondary">
              {isDone ? "✓" : phase.phaseDurationMs != null ? formatDuration(phase.phaseDurationMs) : "—"}
            </div>
          </div>
          <div className="mt-2 text-xs text-text-muted">
            {phase.detail || "No conductor detail yet"}
          </div>
          <div className="mt-2 text-xs text-text-secondary">
            Active task:{" "}
            <span className="font-mono text-foreground">
              {activeTask ? `${activeTask.role}#${activeTask.id.slice(0, 6)} ${activeTask.status}` : "none"}
            </span>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-start gap-2 xl:justify-end">
          <Button variant="outline" size="sm" onClick={isPaused ? onResume : onPause} className="gap-2 rounded-xl">
            {isPaused ? <Play size={14} /> : <Pause size={14} />}
            {isPaused ? "Resume" : "Pause"}
          </Button>
          <Button variant="outline" size="sm" onClick={onSteer} className="gap-2 rounded-xl">
            <RotateCcw size={14} />
            Restart / steer
          </Button>
          <Button variant="outline" size="sm" className="gap-2 rounded-xl">
            <FileText size={14} />
            Backend log
          </Button>
          <Button variant="ghost" size="sm" className="rounded-xl">
            <MoreHorizontal size={16} />
          </Button>
        </div>
      </div>
    </section>
  );
}

function formatClock(iso: string): string {
  return new Date(iso).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function formatDuration(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes < 60) return `${minutes}m ${String(rest).padStart(2, "0")}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}
