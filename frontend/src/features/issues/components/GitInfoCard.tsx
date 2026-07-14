"use client";

import { useCallback, useEffect, useState } from "react";
import { GitBranch, GitMerge, FileText, Ban, Copy, Check } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { useI18n } from "@/providers/I18nProvider";
import { abandonCodexIssue, getCodexIssueDiff, mergeCodexIssue } from "@/lib/api/issues";
import type { CodexIssue, DiffStat, GitMergeStatus, IssueDiffResult } from "@/lib/types";
import { DiffPanel } from "./DiffPanel";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";

interface Props {
  issue: CodexIssue;
  onIssueUpdated: (issue: CodexIssue) => void;
}

function statusVariant(status: GitMergeStatus) {
  if (status === "merged") return "secondary" as const;
  if (status === "abandoned") return "destructive" as const;
  return "default" as const;
}

function formatFileCount(
  count: number,
  t: (key: string, params?: Record<string, string | number>) => string,
): string {
  const key = count === 1 ? "task.diff.fileCountOne" : "task.diff.fileCount";
  return t(key).replace("{count}", String(count));
}

const MERGE_STATUS_KEY = {
  open: "task.mergeStatus.open",
  merged: "task.mergeStatus.merged",
  abandoned: "task.mergeStatus.abandoned",
} as const satisfies Record<
  GitMergeStatus,
  "task.mergeStatus.open" | "task.mergeStatus.merged" | "task.mergeStatus.abandoned"
>;

export function GitInfoCard({ issue, onIssueUpdated }: Props) {
  const { t } = useI18n();
  const { addToast } = useToast();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [merging, setMerging] = useState(false);
  const [diffOpen, setDiffOpen] = useState(false);
  const [diffResult, setDiffResult] = useState<IssueDiffResult | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [abandonOpen, setAbandonOpen] = useState(false);
  const [abandoning, setAbandoning] = useState(false);
  const [stat, setStat] = useState<DiffStat | null>(null);
  const [commitsAhead, setCommitsAhead] = useState<number>(0);
  const [copiedPath, setCopiedPath] = useState(false);

  async function copyWorktreePath() {
    if (!issue.git_worktree_path) return;
    try {
      await navigator.clipboard.writeText(issue.git_worktree_path);
      setCopiedPath(true);
      setTimeout(() => setCopiedPath(false), 1500);
    } catch {
      addToast({ type: "error", title: t("task.diffMerge.clipboardUnavailable") });
    }
  }

  // Pull a compact diffstat whenever this issue or its head sha changes; gives
  // the user a "+N −M / K files" surface without opening the diff modal.
  const fetchStat = useCallback(async () => {
    if (!issue.git_worktree_path || issue.git_merge_status !== "open") {
      setStat(null);
      setCommitsAhead(0);
      return;
    }
    try {
      const res = await getCodexIssueDiff(issue.id, true);
      setStat(res.stat ?? null);
      setCommitsAhead(res.commits_ahead ?? 0);
    } catch {
      setStat(null);
      setCommitsAhead(0);
    }
  }, [issue.id, issue.git_worktree_path, issue.git_merge_status]);

  useEffect(() => {
    let cancelled = false;
    void fetchStat();
    return () => {
      cancelled = true;
      // Keep `cancelled` referenced so eslint-no-unused-vars stays happy if we
      // re-add async-aware fetching later; the noop assignment is intentional.
      void cancelled;
    };
  }, [fetchStat, issue.git_last_commit_sha]);

  // Engineer is writing files → backend emits worktree_dirty (throttled to 5s
  // per process). Refresh the stat so the user sees +N/−M crawl up live
  // instead of frozen until commit. We add our own 1s debounce on top.
  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issue.id),
      busEventMatchers.typeIn("worktree_dirty", "task_status"),
    ),
    onEvent: () => {
      void fetchStat();
    },
    throttleMs: 1000,
    enabled: issue.git_merge_status === "open",
  });

  async function handleConfirmAbandon() {
    setAbandoning(true);
    try {
      const next = await abandonCodexIssue(issue.id);
      onIssueUpdated(next);
      addToast({ type: "success", title: t("task.abandonSuccess") });
      setAbandonOpen(false);
    } catch (err) {
      const msg = err instanceof Error ? err.message : t("task.diffMerge.abandonFailed");
      addToast({ type: "error", title: msg });
    } finally {
      setAbandoning(false);
    }
  }

  async function handleViewDiff() {
    setDiffOpen(true);
    if (diffResult !== null) return;
    setDiffLoading(true);
    try {
      const res = await getCodexIssueDiff(issue.id);
      setDiffResult(res);
    } catch (err) {
      const msg = err instanceof Error ? err.message : t("task.diffMerge.loadFailed");
      addToast({ type: "error", title: msg });
    } finally {
      setDiffLoading(false);
    }
  }

  async function handleConfirmMerge() {
    setMerging(true);
    try {
      const res = await mergeCodexIssue(issue.id, null);
      onIssueUpdated(res.issue);
      addToast({ type: "success", title: t("task.mergeSuccess") });
      setConfirmOpen(false);
    } catch (err) {
      const msg = err instanceof Error ? err.message : t("task.diffMerge.mergeFailed");
      addToast({ type: "error", title: msg });
    } finally {
      setMerging(false);
    }
  }

  return (
    <Card
      data-density="git-ops"
      className="overflow-hidden border-b border-border-subtle bg-surface p-1"
    >
      <CardHeader className="flex flex-col gap-3 space-y-0 px-3 pb-3 pt-3 sm:px-4 lg:flex-row lg:items-start lg:justify-between">
        <CardTitle className="flex min-w-0 flex-wrap items-center gap-2 text-sm font-bold tracking-wide text-foreground">
          <GitBranch size={15} className="text-brand shrink-0" />
          <span>{t("task.git.title")}</span>
          <Badge
            variant={statusVariant(issue.git_merge_status)}
            className="rounded-md uppercase text-[10px] tracking-wider font-extrabold"
          >
            {t(MERGE_STATUS_KEY[issue.git_merge_status])}
          </Badge>
          {stat && stat.files > 0 && (
            <span className="text-xs font-bold font-mono text-text-secondary bg-surface-input px-2 py-0.5 rounded border border-border-subtle/40">
              <span className="text-status-done">+{stat.insertions}</span>{" "}
              <span className="text-status-failed">−{stat.deletions}</span>{" "}
              <span>/ {formatFileCount(stat.files, t)}</span>
            </span>
          )}
          {commitsAhead > 0 && (
            <Badge
              variant="outline"
              className="font-mono border-brand/40 text-brand bg-brand-muted/10 rounded"
            >
              ↑{" "}
              {t(commitsAhead === 1 ? "task.git.commitCountOne" : "task.git.commitCount", {
                count: commitsAhead,
              })}
            </Badge>
          )}
        </CardTitle>
        <div className="grid w-full grid-cols-3 gap-1.5 lg:w-auto lg:flex lg:items-center">
          <Button
            size="sm"
            variant="outline"
            onClick={handleViewDiff}
            disabled={!issue.git_worktree_path}
            className="min-w-0 rounded-md border-border-subtle text-[11px] font-bold transition-colors hover:bg-surface-hover cursor-pointer h-8"
          >
            <FileText size={13} className="mr-1 text-text-muted" />
            <span className="truncate">{t("task.viewDiff")}</span>
          </Button>

          <Button
            size="sm"
            variant="outline"
            onClick={() => setAbandonOpen(true)}
            disabled={!issue.git_branch || issue.git_merge_status !== "open"}
            title={t("task.abandonHelp")}
            className="min-w-0 rounded-md border-status-failed/25 bg-status-failed-bg text-[11px] font-bold text-status-failed transition-colors hover:border-status-failed/50 hover:bg-status-failed/12 hover:text-status-failed cursor-pointer h-8"
          >
            <Ban size={13} className="mr-1" />
            <span className="truncate">{t("task.abandon")}</span>
          </Button>

          <Button
            size="sm"
            onClick={handleConfirmMerge}
            disabled={!issue.git_branch || issue.git_merge_status !== "open"}
            className="min-w-0 rounded-md bg-brand text-[11px] font-bold text-background transition-colors hover:bg-brand-strong cursor-pointer h-8"
          >
            <GitMerge size={13} className="mr-1" />
            <span className="truncate">{t("task.mergeBack")}</span>
          </Button>
        </div>
      </CardHeader>

      <CardContent className="m-2 grid grid-cols-1 gap-2 rounded-lg border border-border-subtle/50 bg-surface-input/30 p-2.5 text-xs md:grid-cols-3">
        <div className="flex flex-col gap-1.5 min-w-0">
          <div className="text-[10px] uppercase tracking-wider font-extrabold text-text-muted">
            {t("task.branch")}
          </div>
          <div
            className="font-mono text-foreground font-bold truncate bg-surface-input px-2 py-1 rounded border border-border-subtle/50 select-all"
            title={issue.git_branch ?? undefined}
          >
            {issue.git_branch ?? "—"}
          </div>
        </div>

        <div className="flex flex-col gap-1.5 min-w-0">
          <div className="text-[10px] uppercase tracking-wider font-extrabold text-text-muted">
            {t("task.base")}
          </div>
          <div
            className="font-mono text-foreground font-bold truncate bg-surface-input px-2 py-1 rounded border border-border-subtle/50 select-all"
            title={issue.git_base_branch ?? undefined}
          >
            {issue.git_base_branch ?? "—"}
          </div>
        </div>

        <div className="flex flex-col gap-1.5 min-w-0">
          <div className="text-[10px] uppercase tracking-wider font-extrabold text-text-muted">
            {t("task.worktree")}
          </div>
          <div className="flex items-center gap-1 min-w-0 bg-surface-input px-2 py-1 rounded border border-border-subtle/50">
            <div
              className="font-mono text-foreground font-bold truncate flex-1 select-all"
              title={issue.git_worktree_path ?? undefined}
            >
              {issue.git_worktree_path ?? "—"}
            </div>
            {issue.git_worktree_path && (
              <button
                type="button"
                onClick={copyWorktreePath}
                className="shrink-0 p-0.5 text-text-muted hover:text-foreground cursor-pointer transition-all"
                aria-label={t("task.copyPath")}
                title={t("task.copyPath")}
              >
                {copiedPath ? <Check size={12} className="text-status-done" /> : <Copy size={12} />}
              </button>
            )}
          </div>
        </div>
      </CardContent>

      <ConfirmDialog
        open={abandonOpen}
        onOpenChange={(next) => (!next ? setAbandonOpen(false) : null)}
        title={t("task.abandonConfirmTitle")}
        description={t("task.abandonConfirmBody").replace("{branch}", issue.git_branch ?? "")}
        confirmText={t("task.abandon")}
        onConfirm={handleConfirmAbandon}
        isLoading={abandoning}
        loadingMotionPhase="dispatching"
        loadingDensity="git-info-abandon-dispatch-confirm"
        loadingIndicatorSize={12}
        variant="destructive"
      />

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={(next) => (!next ? setConfirmOpen(false) : null)}
        title={t("task.mergeConfirmTitle")}
        description={t("task.mergeConfirmBody")
          .replace("{branch}", issue.git_branch ?? "")
          .replace("{base}", issue.git_base_branch ?? "")}
        confirmText={t("task.mergeBack")}
        onConfirm={handleConfirmMerge}
        isLoading={merging}
        loadingMotionPhase="dispatching"
        loadingDensity="git-info-merge-dispatch-confirm"
        loadingIndicatorSize={12}
        variant="default"
      />

      <Dialog open={diffOpen} onOpenChange={setDiffOpen}>
        <DialogContent className="sm:w-[95vw] sm:max-w-[1200px] p-0 gap-0 border-border-subtle bg-background">
          <DialogHeader className="px-4 py-3 border-b border-border-subtle/60">
            <DialogTitle className="font-bold text-base text-foreground flex items-center gap-2">
              <FileText size={16} className="text-brand" />
              <span>{t("task.viewDiff")}</span>
            </DialogTitle>
          </DialogHeader>
          {/* Explicit maxHeight so overflow-y-auto has a constraint to work against */}
          <div className="overflow-y-auto" style={{ maxHeight: "calc(82vh - 4rem)" }}>
            {diffLoading ? (
              <span
                data-density="git-ops-diff-tool-loading"
                className="motion-essential inline-flex items-center gap-2 p-4 text-sm font-semibold text-text-secondary"
              >
                <AgentThinkingIndicator phase="tool" size={14} /> {t("task.diffMerge.loading")}
              </span>
            ) : (
              <DiffPanel
                diff={diffResult?.diff ?? ""}
                baseBranch={diffResult?.base_branch}
                branch={diffResult?.branch}
                stat={diffResult?.stat}
              />
            )}
          </div>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
