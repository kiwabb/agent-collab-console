"use client";

import { useEffect, useState } from "react";
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
import type { CodexIssue, DiffStat, GitMergeStatus } from "@/lib/types";

interface Props {
  issue: CodexIssue;
  onIssueUpdated: (issue: CodexIssue) => void;
}

function statusVariant(status: GitMergeStatus) {
  if (status === "merged") return "secondary" as const;
  if (status === "abandoned") return "destructive" as const;
  return "default" as const;
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
  const [diff, setDiff] = useState<string | null>(null);
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
      addToast({ type: "error", title: "Clipboard unavailable" });
    }
  }

  // Pull a compact diffstat whenever this issue or its head sha changes; gives
  // the user a "+N −M / K files" surface without opening the diff modal.
  useEffect(() => {
    if (!issue.git_worktree_path || issue.git_merge_status !== "open") {
      setStat(null);
      setCommitsAhead(0);
      return;
    }
    let cancelled = false;
    getCodexIssueDiff(issue.id, true)
      .then((res) => {
        if (cancelled) return;
        setStat(res.stat ?? null);
        setCommitsAhead(res.commits_ahead ?? 0);
      })
      .catch(() => {
        if (!cancelled) {
          setStat(null);
          setCommitsAhead(0);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [issue.id, issue.git_worktree_path, issue.git_merge_status, issue.git_last_commit_sha]);

  async function handleConfirmAbandon() {
    setAbandoning(true);
    try {
      const next = await abandonCodexIssue(issue.id);
      onIssueUpdated(next);
      addToast({ type: "success", title: t("task.abandonSuccess") });
      setAbandonOpen(false);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to abandon";
      addToast({ type: "error", title: msg });
    } finally {
      setAbandoning(false);
    }
  }

  async function handleViewDiff() {
    setDiffOpen(true);
    if (diff !== null) return;
    setDiffLoading(true);
    try {
      const res = await getCodexIssueDiff(issue.id);
      setDiff(res.diff);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load diff";
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
      const msg = err instanceof Error ? err.message : "Failed to merge";
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
          Git
          <Badge variant={statusVariant(issue.git_merge_status)}>
            {t(MERGE_STATUS_KEY[issue.git_merge_status])}
          </Badge>
          {stat && stat.files > 0 && (
            <span className="text-xs font-normal font-mono text-muted-foreground">
              <span className="text-success">+{stat.insertions}</span>{" "}
              <span className="text-error">−{stat.deletions}</span>{" "}
              <span>/ {stat.files} {stat.files === 1 ? "file" : "files"}</span>
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
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>{t("task.viewDiff")}</DialogTitle>
          </DialogHeader>
          <div className="text-xs bg-muted/40 rounded max-h-[60vh] overflow-auto">
            {diffLoading ? (
              <span className="inline-flex items-center gap-2 p-4">
                <Loader2 className="animate-spin" size={14} /> Loading…
              </span>
            ) : diff && diff.trim().length > 0 ? (
              <DiffView diff={diff} />
            ) : (
              <span className="block p-4">{t("task.diffEmpty")}</span>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

/** Bare-bones unified-diff renderer.
 *
 * Colours additions/removals/hunk-headers/file-headers without bringing in a
 * heavyweight diff lib. Good enough until someone needs side-by-side view.
 */
function DiffView({ diff }: { diff: string }) {
  const lines = diff.split("\n");
  return (
    <pre className="font-mono leading-relaxed">
      {lines.map((line, i) => {
        let cls = "block px-3 whitespace-pre-wrap";
        if (line.startsWith("diff --git") || line.startsWith("index ") || line.startsWith("--- ") || line.startsWith("+++ ")) {
          cls += " bg-muted/60 text-muted-foreground font-semibold";
        } else if (line.startsWith("@@")) {
          cls += " bg-brand/10 text-brand";
        } else if (line.startsWith("+")) {
          cls += " bg-success/10 text-success";
        } else if (line.startsWith("-")) {
          cls += " bg-error/10 text-error";
        } else {
          cls += " text-foreground/70";
        }
        return (
          <span key={i} className={cls}>
            {line || " "}
          </span>
        );
      })}
    </pre>
  );
}
