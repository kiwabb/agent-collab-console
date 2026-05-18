"use client";

import { useCallback, useEffect, useState } from "react";
import { GitBranch, GitMerge, FileText, Loader2, Ban, Copy, Check } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { useI18n } from "@/providers/I18nProvider";
import { abandonCodexIssue, getCodexIssueDiff, mergeCodexIssue } from "@/lib/api";
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

function formatFileCount(count: number, t: (key: string, params?: Record<string, string | number>) => string): string {
  const key = count === 1 ? "task.diff.fileCountOne" : "task.diff.fileCount";
  return t(key).replace("{count}", String(count));
}

const MERGE_STATUS_KEY = {
  open: "task.mergeStatus.open",
  merged: "task.mergeStatus.merged",
  abandoned: "task.mergeStatus.abandoned",
} as const satisfies Record<GitMergeStatus, "task.mergeStatus.open" | "task.mergeStatus.merged" | "task.mergeStatus.abandoned">;

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
    onEvent: () => { void fetchStat(); },
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
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-medium flex-wrap">
          <GitBranch size={14} />
          {t("task.git.title")}
          <Badge variant={statusVariant(issue.git_merge_status)}>
            {t(MERGE_STATUS_KEY[issue.git_merge_status])}
          </Badge>
          {stat && stat.files > 0 && (
            <span className="text-xs font-normal font-mono text-muted-foreground">
              <span className="text-success">+{stat.insertions}</span>{" "}
              <span className="text-error">−{stat.deletions}</span>{" "}
              <span>/ {formatFileCount(stat.files, t)}</span>
            </span>
          )}
          {commitsAhead > 0 && (
            <Badge variant="outline" className="font-mono">
              ↑{commitsAhead}
            </Badge>
          )}
        </CardTitle>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={handleViewDiff}
            disabled={!issue.git_worktree_path}
          >
            <FileText size={14} className="mr-1" />
            {t("task.viewDiff")}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setAbandonOpen(true)}
            disabled={!issue.git_branch || issue.git_merge_status !== "open"}
            title={t("task.abandonHelp")}
          >
            <Ban size={14} className="mr-1" />
            {t("task.abandon")}
          </Button>
          <Button
            size="sm"
            onClick={() => setConfirmOpen(true)}
            disabled={!issue.git_branch || issue.git_merge_status !== "open"}
          >
            <GitMerge size={14} className="mr-1" />
            {t("task.mergeBack")}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="grid grid-cols-1 sm:grid-cols-3 gap-x-6 gap-y-2 text-xs">
        <div>
          <div className="text-muted-foreground">{t("task.branch")}</div>
          <div className="font-mono truncate">{issue.git_branch ?? "—"}</div>
        </div>
        <div>
          <div className="text-muted-foreground">{t("task.base")}</div>
          <div className="font-mono truncate">{issue.git_base_branch ?? "—"}</div>
        </div>
        <div>
          <div className="text-muted-foreground">{t("task.worktree")}</div>
          <div className="flex items-center gap-1.5 min-w-0">
            <div className="font-mono truncate" title={issue.git_worktree_path ?? undefined}>
              {issue.git_worktree_path ?? "—"}
            </div>
            {issue.git_worktree_path && (
              <button
                type="button"
                onClick={copyWorktreePath}
                className="shrink-0 p-0.5 text-muted-foreground hover:text-foreground"
                aria-label={t("task.copyPath")}
                title={t("task.copyPath")}
              >
                {copiedPath ? <Check size={12} className="text-success" /> : <Copy size={12} />}
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
        variant="default"
      />

      <Dialog open={diffOpen} onOpenChange={setDiffOpen}>
        <DialogContent className="sm:w-[95vw] sm:max-w-[1200px] p-0 gap-0">
          <DialogHeader className="px-4 py-3 border-b border-border">
            <DialogTitle>{t("task.viewDiff")}</DialogTitle>
          </DialogHeader>
          {/* Explicit maxHeight so overflow-y-auto has a constraint to work against */}
          <div className="overflow-y-auto" style={{ maxHeight: "calc(82vh - 4rem)" }}>
            {diffLoading ? (
              <span className="inline-flex items-center gap-2 p-4 text-sm">
                <Loader2 className="animate-spin" size={14} /> {t("task.diffMerge.loading")}
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
