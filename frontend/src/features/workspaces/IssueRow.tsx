"use client";

import {
  ArrowRight,
  CheckCircle2,
  Clock3,
  GitBranch,
  PauseCircle,
  PlayCircle,
  Trash2,
  XCircle,
} from "lucide-react";

import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { StatusBadge, inferStatusKind } from "@/components/ui/status-badge";
import { PHASES, PHASE_CONFIG, type Phase } from "@/lib/task-selection";
import type { CodexIssue, CodexTask, Project } from "@/lib/types";
import { useI18n } from "@/providers/I18nProvider";
import { cn } from "@/lib/utils";
import { getWorkspaceConsoleRoleLabel } from "./workspaceConsoleState";

export type IssueStatusBucket = "running" | "awaiting" | "queued" | "done" | "failed";

const BUCKET_ICON = {
  running: PlayCircle,
  awaiting: PauseCircle,
  queued: Clock3,
  done: CheckCircle2,
  failed: XCircle,
};

export function getIssueStatusBucket(status: string | null | undefined): IssueStatusBucket {
  const value = String(status || "open").toLowerCase();
  if (value === "completed" || value === "done" || value === "success") return "done";
  if (value === "failed" || value.includes("error") || value === "cancelled") return "failed";
  if (value.includes("await") || value === "review" || value === "ready") return "awaiting";
  if (value === "in_progress" || value === "running" || value === "active") return "running";
  return "queued";
}

export function getPhaseProgress(phase: string | null | undefined): {
  index: number;
  total: number;
  label: string;
  role: string;
} {
  const normalized = PHASES.includes(phase as Phase) ? (phase as Phase) : "requirements";
  const index = PHASES.indexOf(normalized) + 1;
  return {
    index,
    total: PHASES.length,
    label: normalized,
    role: PHASE_CONFIG[normalized].role,
  };
}

export function pickCurrentRole(issue: CodexIssue, tasks: CodexTask[]): string {
  const active = tasks.find((task) => {
    const status = String(task.status || "").toLowerCase();
    return (
      status === "running" ||
      status === "responding" ||
      status === "pending" ||
      status === "awaiting_review"
    );
  });
  return active?.role || getPhaseProgress(issue.current_phase).role;
}

interface Props {
  issue: CodexIssue;
  tasks: CodexTask[];
  project: Project | null;
  onOpen: () => void;
  onDelete?: (() => void) | undefined;
}

export function IssueRow({ issue, tasks, project, onOpen, onDelete }: Props) {
  const { t } = useI18n();
  const bucket = getIssueStatusBucket(issue.status);
  const Icon = BUCKET_ICON[bucket];
  const progress = getPhaseProgress(issue.current_phase);
  const currentRole = pickCurrentRole(issue, tasks);
  // Terminal completion is authoritative over current_phase: a Conductor-driven
  // issue often finishes without advancing current_phase past "requirements"
  // (no fixed DAG), so a completed issue must still render as fully done rather
  // than stuck at 1/4. See CLAUDE.md "WorkflowGraph 是 Conductor 决策时间线".
  const isComplete = bucket === "done";
  const displayIndex = isComplete ? progress.total : progress.index;
  const percent = isComplete
    ? 100
    : Math.max(8, Math.round((progress.index / progress.total) * 100));
  const phaseLabel = isComplete ? t("workspace.console.status.done") : progress.label;
  const isIssueScheduling = bucket === "running";
  const statusLabel =
    bucket === "running"
      ? t("workspace.console.status.running")
      : bucket === "done"
        ? t("workspace.console.status.done")
        : bucket === "failed"
          ? t("workspace.console.status.failed")
          : bucket === "awaiting"
            ? t("workspace.console.status.awaitingApproval")
            : t("workspace.console.status.queued");

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onOpen();
      }}
      data-density="workspace-scheduling-row"
      className={cn(
        "group relative grid min-h-[72px] w-full cursor-pointer grid-cols-[minmax(0,1fr)_128px_156px_84px] gap-3 overflow-hidden border-border-subtle bg-surface-input/25 px-4 py-3 text-left transition-colors hover:bg-surface-hover max-lg:grid-cols-1",
        isIssueScheduling && "motion-essential border-brand/35 bg-brand-muted/10",
      )}
      aria-label={`Open issue ${issue.title}`}
    >
      {isIssueScheduling && (
        <div
          aria-hidden
          className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-brand/70 to-transparent"
        />
      )}
      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-3">
          <span
            className={cn(
              "inline-flex size-8 shrink-0 items-center justify-center rounded-lg border",
              isIssueScheduling && "motion-essential border-brand/35 bg-brand-muted/15 text-brand",
              bucket === "awaiting" &&
                "border-status-awaiting/30 bg-status-awaiting/10 text-status-awaiting",
              bucket === "queued" && "border-border-subtle bg-surface-raised text-text-muted",
              bucket === "done" && "border-status-done/30 bg-status-done/10 text-status-done",
              bucket === "failed" &&
                "border-status-failed/30 bg-status-failed/10 text-status-failed",
            )}
          >
            {isIssueScheduling ? (
              <AgentThinkingIndicator phase="dispatching" size={16} />
            ) : (
              <Icon size={17} />
            )}
          </span>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-mono text-[11px] text-text-muted">#{issue.id.slice(0, 6)}</span>
              {bucket === "awaiting" && (
                <span className="rounded-md border border-status-awaiting/30 bg-status-awaiting/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-status-awaiting">
                  {t("workspace.console.status.awaitingReview")}
                </span>
              )}
            </div>
            <h2 className="mt-1 truncate text-sm font-bold text-foreground">{issue.title}</h2>
          </div>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-text-muted">
          <span className="inline-flex items-center gap-1.5 font-mono">
            <GitBranch size={12} />
            {issue.git_branch || project?.default_branch || "main"}
          </span>
          <span>
            {issue.updated_at ? relTime(issue.updated_at, t("workspace.console.time.now")) : "—"}
          </span>
        </div>
      </div>

      <div className="flex items-center max-lg:justify-between">
        <StatusBadge kind={inferStatusKind(issue.status)} label={statusLabel} />
      </div>

      <div className="min-w-0">
        <div className="flex items-center justify-between gap-2 text-xs">
          <span
            data-density="workspace-scheduling-role"
            className={cn(
              "inline-flex min-w-0 items-center gap-1.5 rounded-md border border-border-subtle bg-surface-raised px-2 py-1 font-bold text-foreground",
              isIssueScheduling && "motion-essential border-brand/30 bg-brand-muted/10 text-brand",
            )}
          >
            {isIssueScheduling && (
              <AgentThinkingIndicator phase="dispatching" size={10} className="shrink-0" />
            )}
            <span className="truncate">{getWorkspaceConsoleRoleLabel(currentRole)}</span>
          </span>
          <span className="font-mono text-text-muted">
            {displayIndex}/{progress.total}
          </span>
        </div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-raised">
          <div
            className="h-full rounded-full bg-[linear-gradient(90deg,#22d3ee,#84cc16)] transition-all"
            style={{ width: `${percent}%` }}
          />
        </div>
        <div className="mt-1 text-[11px] capitalize text-text-muted">{phaseLabel}</div>
      </div>

      <div className="flex items-center justify-end gap-2 max-lg:justify-start">
        {onDelete && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            className="rounded-lg p-1.5 text-text-muted opacity-0 transition-all hover:bg-error/10 hover:text-error group-hover:opacity-100"
            aria-label={t("issue.delete")}
            title={t("issue.delete")}
          >
            <Trash2 size={13} />
          </button>
        )}
        <span className="text-xs font-bold text-text-muted transition-colors group-hover:text-foreground">
          {t("workspace.console.openIssue")}
        </span>
        <ArrowRight
          size={15}
          className="text-text-muted transition-all group-hover:translate-x-1 group-hover:text-foreground"
        />
      </div>
    </div>
  );
}

function relTime(iso: string, nowLabel: string): string {
  const timestamp = new Date(iso).getTime();
  if (!Number.isFinite(timestamp)) return "—";
  const diff = Date.now() - timestamp;
  if (diff < 60_000) return nowLabel;
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h`;
  return `${Math.floor(diff / 86_400_000)}d`;
}
