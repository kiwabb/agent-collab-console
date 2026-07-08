"use client";

import type { CodexIssue, GitMergeStatus } from "@/lib/types";

const MERGE_STATUS_KEY = {
  open: "task.mergeStatus.open",
  merged: "task.mergeStatus.merged",
  abandoned: "task.mergeStatus.abandoned",
} as const satisfies Record<
  GitMergeStatus,
  "task.mergeStatus.open" | "task.mergeStatus.merged" | "task.mergeStatus.abandoned"
>;
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";
import { InlineEdit } from "@/components/ui/inline-edit";
import { Link, Check, Pin, PinOff, Copy as Duplicate } from "lucide-react";
import { useState } from "react";

function formatRelativeTime(dateStr: string | null): string {
  if (!dateStr) return "";
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);
  if (diffSec < 60) return `${diffSec}s ago`;
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHour < 24) return `${diffHour}h ago`;
  if (diffDay < 7) return `${diffDay}d ago`;
  return date.toLocaleDateString();
}

interface IssueCardProps {
  issue: CodexIssue;
  isSelected: boolean;
  taskCount: number;
  runningCount: number;
  failedCount: number;
  waitingCount: number;
  onClick: () => void;
  onUpdateIssue?:
    ((id: string, updates: { title?: string; description?: string }) => void) | undefined;
  onPinIssue?: ((id: string, isPinned: boolean) => void) | undefined;
  onDuplicateIssue?: ((id: string) => void) | undefined;
}

export function IssueCard({
  issue,
  isSelected,
  taskCount,
  runningCount,
  failedCount,
  waitingCount,
  onClick,
  onUpdateIssue,
  onPinIssue,
  onDuplicateIssue,
}: IssueCardProps) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);

  const handleTitleSave = (newTitle: string) => {
    if (onUpdateIssue) {
      onUpdateIssue(issue.id, { title: newTitle });
    }
  };

  const handleCopyLink = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const url = `${window.location.origin}?workspace=${issue.session_id}&issue=${issue.id}`;
    await navigator.clipboard.writeText(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handlePin = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (onPinIssue) {
      onPinIssue(issue.id, !issue.is_pinned);
    }
  };

  const handleDuplicate = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (onDuplicateIssue) {
      onDuplicateIssue(issue.id);
    }
  };

  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full text-left p-5 transition-all duration-200 group relative overflow-hidden outline-none",
        isSelected ? "bg-surface-active" : "bg-transparent hover:bg-surface-hover",
      )}
    >
      {isSelected && <div className="absolute left-0 top-0 bottom-0 w-1 bg-brand" />}

      <div className="flex flex-col gap-3 relative z-10">
        <div className="flex items-start justify-between gap-2">
          <InlineEdit
            value={issue.title}
            onSave={handleTitleSave}
            textClassName={cn(
              "text-[13.5px] font-bold tracking-tight line-clamp-2 leading-snug transition-colors",
              isSelected ? "text-brand" : "text-foreground group-hover:text-foreground",
            )}
            disabled={!onUpdateIssue}
          />
          <div className="flex gap-1 shrink-0">
            <button
              onClick={handleDuplicate}
              className="p-1.5 rounded-md hover:bg-surface-hover text-text-muted hover:text-brand transition-all opacity-0 group-hover:opacity-100"
              title={t("issue.duplicate")}
            >
              <Duplicate size={12} />
            </button>
            <button
              onClick={handlePin}
              className={cn(
                "p-1.5 rounded-md hover:bg-surface-hover transition-all opacity-0 group-hover:opacity-100",
                issue.is_pinned ? "text-warning" : "text-text-muted hover:text-warning",
              )}
              title={issue.is_pinned ? t("issue.unpin") : t("issue.pin")}
            >
              {issue.is_pinned ? <PinOff size={12} /> : <Pin size={12} />}
            </button>
            <button
              onClick={handleCopyLink}
              className="p-1.5 rounded-md hover:bg-surface-hover text-text-muted hover:text-brand transition-all opacity-0 group-hover:opacity-100"
              title={t("issue.copyLink")}
            >
              {copied ? <Check size={12} className="text-success" /> : <Link size={12} />}
            </button>
          </div>
        </div>

        {issue.description && (
          <p className="text-[12px] leading-relaxed text-text-secondary line-clamp-2 opacity-70">
            {issue.description}
          </p>
        )}

        <div className="flex items-center justify-between mt-1">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5 bg-surface-raised/50 px-2 py-0.5 rounded-md border border-border-subtle">
              <span className="text-[10px] font-black text-text-muted uppercase tracking-wider">
                {t("issue.tasks")}
              </span>
              <span className="text-[11px] font-bold text-text-secondary">{taskCount}</span>
            </div>

            {runningCount > 0 && (
              <div
                data-density="issue-card-live-dispatch"
                className="motion-essential relative flex items-center gap-1.5 overflow-hidden bg-brand/10 px-2 py-0.5 rounded-md border border-brand/20"
              >
                <span
                  aria-hidden
                  className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-brand/70 to-transparent"
                />
                <AgentThinkingIndicator phase="dispatching" size={12} />
                <span className="text-[10px] font-black text-brand uppercase tracking-wider">
                  {t("issue.live")}
                </span>
                <span className="text-[11px] font-bold text-brand">{runningCount}</span>
              </div>
            )}

            {issue.git_branch && (
              <div
                className={cn(
                  "flex items-center gap-1 px-2 py-0.5 rounded-md border text-[10px] font-black uppercase tracking-wider",
                  issue.git_merge_status === "merged"
                    ? "bg-success/10 border-success/20 text-success"
                    : issue.git_merge_status === "abandoned"
                      ? "bg-error/10 border-error/20 text-error"
                      : "bg-surface-raised/50 border-border-subtle text-text-muted",
                )}
                title={issue.git_branch}
              >
                {t(MERGE_STATUS_KEY[issue.git_merge_status])}
              </div>
            )}
          </div>

          <div className="flex gap-1.5">
            {failedCount > 0 && (
              <div
                className="size-1.5 rounded-full bg-error shadow-[0_0_5px_rgba(255,110,110,0.5)]"
                title={`${failedCount} failed`}
              />
            )}
            {waitingCount > 0 && (
              <div className="size-1.5 rounded-full bg-warning" title={`${waitingCount} waiting`} />
            )}
          </div>
        </div>

        <div className="text-[9px] font-mono text-text-muted/50 mt-1">
          {formatRelativeTime(issue.updated_at || issue.created_at || null)}
        </div>
      </div>
    </button>
  );
}
