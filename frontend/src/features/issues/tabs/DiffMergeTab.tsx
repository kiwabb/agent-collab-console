"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Copy, ExternalLink, GitPullRequest, Loader2, RefreshCw, Terminal } from "lucide-react";
import {
  abandonCodexIssue,
  createGithubPR,
  finalizeAbandonedCodexIssue,
  getCodexIssueDiff,
  getCodexIssues,
  getCodexTasks,
  mergeCodexIssue,
  refreshGithubPR,
  restoreCodexIssue,
  reviewCodexTask,
  submitCodexTask,
} from "@/lib/api";
import type { CodexIssue, CodexTask, IssueDiffResult } from "@/lib/types";
import { DiffSplitView } from "@/features/issues/components/DiffSplitView";
import { DiffStatBar } from "@/features/issues/components/DiffStatBar";
import { Button } from "@/components/ui/button";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";
import { useI18n } from "@/providers/I18nProvider";
import { UndoBar } from "@/components/ui/undo-bar";
import { cn } from "@/lib/utils";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";

interface Props {
  issueId: string;
  issue: CodexIssue | null;
  /** Active state from parent — refetch when this becomes true. */
  active: boolean;
}

const ACTIVE_STATUSES = new Set(["open", "in_progress"]);

type BusyKind = "submit" | "review-approve" | "review-reject" | "merge" | "abandon" | "pr-create" | "pr-refresh" | null;
type ConfirmKind = "merge" | "merge-force" | "abandon" | "reject" | null;
type TranslateFn = (key: string, params?: Record<string, string | number>) => string;

function formatTimeAgo(ts: number, t: TranslateFn): string {
  const delta = Date.now() - ts;
  if (delta < 1500) return t("task.diffMerge.timeAgo.justNow");
  if (delta < 60_000) return t("task.diffMerge.timeAgo.secondsAgo", { count: Math.floor(delta / 1000) });
  if (delta < 3_600_000) return t("task.diffMerge.timeAgo.minutesAgo", { count: Math.floor(delta / 60_000) });
  return t("task.diffMerge.timeAgo.hoursAgo", { count: Math.floor(delta / 3_600_000) });
}

export function DiffMergeTab({ issueId, issue, active }: Props) {
  const { addToast } = useToast();
  const { t } = useI18n();
  const router = useRouter();
  const [diff, setDiff] = useState<IssueDiffResult | null>(null);
  const [tasks, setTasks] = useState<CodexTask[]>([]);
  const [busy, setBusy] = useState<BusyKind>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastFetched, setLastFetched] = useState<number | null>(null);
  const [confirmKind, setConfirmKind] = useState<ConfirmKind>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [mergeForceMessage, setMergeForceMessage] = useState<string | null>(null);
  // D4: undo-bar visibility for the most recent abandon.
  const [pendingAbandon, setPendingAbandon] = useState<{ issueId: string; title: string } | null>(null);
  const inFlight = useRef(false);

  const load = useCallback(
    async (mode: "initial" | "refresh" | "poll" = "refresh") => {
      if (inFlight.current) return;
      inFlight.current = true;
      if (mode === "refresh") setIsRefreshing(true);
      try {
        const [d, t] = await Promise.all([
          getCodexIssueDiff(issueId),
          getCodexTasks(null, issueId),
        ]);
        setDiff(d);
        setTasks(t);
        setLastFetched(Date.now());
      } catch (err) {
        if (mode !== "poll") {
          addToast({
            type: "error",
            title: t("task.diffMerge.loadFailed"),
            message: err instanceof Error ? err.message : String(err),
          });
        }
      } finally {
        if (mode === "refresh") setIsRefreshing(false);
        inFlight.current = false;
      }
    },
    [issueId, addToast, t],
  );

  useEffect(() => {
    if (!active) return;
    void load(lastFetched === null ? "initial" : "refresh");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, issueId]);

  // Event-driven refresh: engineer writes → worktree_dirty fires (5s throttle
  // server-side); also refetch on task_status changes for the tasks list.
  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn("worktree_dirty", "task_status", "task_created"),
    ),
    onEvent: () => { void load("poll"); },
    throttleMs: 1500,
    enabled: active,
  });

  // Fallback poll while in flight at a relaxed 15s interval.
  useEffect(() => {
    if (!active) return;
    if (!issue || !ACTIVE_STATUSES.has(issue.status ?? "")) return;
    const id = window.setInterval(() => void load("poll"), 15000);
    return () => window.clearInterval(id);
  }, [active, issue, load]);

  // Skip auto-spawned architect-review child tasks. They share the same
  // task list but are not the "main" engineer/QA work — counting them here
  // makes the Approve/Reject and "提交评审" buttons reappear after the user
  // already moved past that step.
  const mainTasks = tasks.filter((t) => t.task_kind !== "review");
  const reviewableTask = mainTasks.find((t) => t.status === "awaiting_review");
  const doneTaskForSubmit = mainTasks.find((t) => t.status === "done");
  const isAbandoned = issue?.status === "cancelled";

  const handleSubmit = useCallback(async () => {
    if (!doneTaskForSubmit) return;
    setBusy("submit");
    try {
      await submitCodexTask(doneTaskForSubmit.id);
      addToast({ type: "success", title: t("task.review.submitted") });
      await load("refresh");
    } catch (err) {
      addToast({
        type: "error",
        title: t("task.review.submitFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBusy(null);
    }
  }, [doneTaskForSubmit, addToast, load, t]);

  const handleApprove = useCallback(async () => {
    if (!reviewableTask) return;
    setBusy("review-approve");
    try {
      await reviewCodexTask(reviewableTask.id, "approve", null);
      addToast({ type: "success", title: t("task.review.approved") });
      await load("refresh");
    } catch (err) {
      addToast({
        type: "error",
        title: t("task.review.failed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBusy(null);
    }
  }, [reviewableTask, addToast, load, t]);

  const handleRejectConfirm = useCallback(async () => {
    if (!reviewableTask) return;
    setBusy("review-reject");
    setConfirmKind(null);
    try {
      await reviewCodexTask(reviewableTask.id, "reject", rejectReason || null);
      addToast({ type: "success", title: t("task.review.sentBackForRework") });
      setRejectReason("");
      await load("refresh");
    } catch (err) {
      addToast({
        type: "error",
        title: t("task.review.failed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBusy(null);
    }
  }, [reviewableTask, rejectReason, addToast, load, t]);

  const performMerge = useCallback(
    async (force: boolean) => {
      setBusy("merge");
      setConfirmKind(null);
      try {
        await mergeCodexIssue(issueId, null, force);
        // D1: count how many issues merged this week so the toast can lead
        // with a stat instead of just confirming the action.
        const weekly = await getCodexIssues(null, issue?.project_id ?? null)
          .then((list) => {
            const oneWeekAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
            return list.filter((i) => {
              if (i.git_merge_status !== "merged") return false;
              const updated = new Date(i.updated_at ?? i.created_at ?? 0).getTime();
              return updated >= oneWeekAgo;
            }).length;
          })
          .catch(() => null);
        addToast({
          type: "success",
          title: force ? t("task.diffMerge.mergedForced") : t("task.mergeSuccess"),
          message: weekly !== null
            ? weekly === 1
              ? t("task.diffMerge.weeklyMergedOne")
              : t("task.diffMerge.weeklyMergedMany", { count: weekly })
            : undefined,
        });
        // Land back on the Inbox so the user can immediately pick up the
        // next thing — they're done with this issue.
        setTimeout(() => router.push("/"), 600);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        if (!force && /diverged|ahead of this issue|allow_diverged_base/i.test(msg)) {
          setMergeForceMessage(msg);
          setConfirmKind("merge-force");
          return;
        }
        addToast({ type: "error", title: t("task.diffMerge.mergeFailed"), message: msg });
      } finally {
        setBusy(null);
      }
    },
    [issue?.project_id, issueId, addToast, router, t],
  );

  const handleCreatePR = useCallback(async () => {
    setBusy("pr-create");
    try {
      const updated = await createGithubPR(issueId, {});
      addToast({
        type: "success",
        title: t("task.diffMerge.prOpened"),
        message: updated.github_pr_url ?? undefined,
      });
      await load("refresh");
    } catch (err) {
      addToast({
        type: "error",
        title: t("task.diffMerge.createPrFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBusy(null);
    }
  }, [issueId, addToast, load, t]);

  const handleRefreshPR = useCallback(async () => {
    setBusy("pr-refresh");
    try {
      await refreshGithubPR(issueId);
      addToast({ type: "success", title: t("task.diffMerge.prRefreshed") });
      await load("refresh");
    } catch (err) {
      addToast({
        type: "error",
        title: t("task.diffMerge.refreshPrFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBusy(null);
    }
  }, [issueId, addToast, load, t]);

  const handleAbandon = useCallback(async () => {
    setBusy("abandon");
    setConfirmKind(null);
    try {
      await abandonCodexIssue(issueId);
      // D4: optimistic abandon — the worktree is still on disk for ~60s.
      // The UndoBar component handles both restore-on-click and
      // finalize-on-timeout below.
      setPendingAbandon({ issueId, title: issue?.title || issueId.slice(0, 8) });
      await load("refresh");
    } catch (err) {
      addToast({
        type: "error",
        title: t("task.diffMerge.abandonFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBusy(null);
    }
  }, [issueId, issue?.title, addToast, load, t]);

  const handleAbandonUndo = useCallback(async () => {
    if (!pendingAbandon) return;
    try {
      await restoreCodexIssue(pendingAbandon.issueId);
      addToast({ type: "success", title: t("task.diffMerge.restored") });
    } catch (err) {
      addToast({
        type: "error",
        title: t("task.diffMerge.restoreFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setPendingAbandon(null);
      await load("refresh");
    }
  }, [pendingAbandon, addToast, load, t]);

  const handleAbandonExpire = useCallback(async () => {
    if (!pendingAbandon) return;
    try {
      await finalizeAbandonedCodexIssue(pendingAbandon.issueId);
    } catch {
      // Silent — the issue is already in abandoned state; finalize is just
      // a worktree-cleanup hint. Surface in toast as a soft warning.
      addToast({ type: "info", title: t("task.diffMerge.worktreeCleanupDeferred") });
    } finally {
      setPendingAbandon(null);
    }
  }, [pendingAbandon, addToast, t]);

  return (
    <div className="h-full min-h-0 overflow-y-auto p-6 flex flex-col gap-6">
      <div className="flex items-center justify-between -mt-2 shrink-0">
        <div className="text-[11px] text-text-muted">
          {lastFetched ? <>{t("task.diffMerge.lastRefreshed", { time: formatTimeAgo(lastFetched, t) })}</> : "—"}
        </div>
        <Button
          size="sm"
          variant="outline"
          disabled={isRefreshing || !!busy}
          onClick={() => void load("refresh")}
        >
          <RefreshCw size={12} className={cn("mr-1.5", isRefreshing && "animate-spin")} />
          {t("task.diffMerge.refresh")}
        </Button>
      </div>

      <section className="rounded-lg border border-border-subtle p-4 shrink-0">
        <h3 className="text-xs font-black uppercase tracking-widest text-text-muted mb-3">{t("task.review.title")}</h3>
        {reviewableTask ? (
          <div className="flex flex-col gap-3">
            <div className="text-sm">
              {t("task.diffMerge.awaitingArchitectReview", { title: reviewableTask.title })}
            </div>
            <div className="flex gap-2">
              <Button
                disabled={!!busy}
                onClick={() => void handleApprove()}
              >
                {busy === "review-approve" ? (
                  <span className="flex items-center gap-1.5">
                    <Loader2 size={12} className="animate-spin" /> {t("task.review.approving")}
                  </span>
                ) : (
                  t("task.review.approve")
                )}
              </Button>
              <Button
                disabled={!!busy}
                variant="outline"
                onClick={() => {
                  setRejectReason("");
                  setConfirmKind("reject");
                }}
              >
                {t("task.review.reject")}
              </Button>
            </div>
          </div>
        ) : doneTaskForSubmit ? (
          <Button
            disabled={!!busy}
            onClick={() => void handleSubmit()}
            data-density={busy === "submit" ? "diff-merge-submit-review-thinking" : "diff-merge-submit-review"}
            className={cn(busy === "submit" && "motion-essential")}
          >
            {busy === "submit" ? (
              <span className="flex items-center gap-1.5">
                <AgentThinkingIndicator phase="thinking" size={12} /> {t("task.review.submitting")}
              </span>
            ) : (
              t("task.submitForReview")
            )}
          </Button>
        ) : (
          <div className="text-sm text-text-muted">{t("task.diffMerge.noReadyTask")}</div>
        )}
      </section>

      <section className="rounded-lg border border-border-subtle p-4 flex flex-col gap-3 shrink-0">
        <h3 className="text-xs font-black uppercase tracking-widest text-text-muted">{t("task.diffMerge.branchOperations")}</h3>
        <div className="text-xs text-text-muted">
          {t("task.branch")}: <code className="font-mono">{issue?.git_branch ?? "—"}</code> → {t("task.base")}: <code className="font-mono">{diff?.base_branch ?? "—"}</code>
        </div>
        {issue?.git_worktree_path && (
          <div className="flex items-center gap-2 text-[11px] text-text-muted bg-surface-input/40 rounded-md px-3 py-1.5 border border-border-subtle">
            <Terminal size={11} className="shrink-0" />
            <code className="font-mono truncate flex-1">{issue.git_worktree_path}</code>
            <button
              type="button"
              onClick={async () => {
                const cmd = `cd "${issue.git_worktree_path}" && code .`;
                try {
                  await navigator.clipboard.writeText(cmd);
                  addToast({
                    type: "success",
                    title: t("task.diffMerge.copiedToClipboard"),
                    message: t("task.diffMerge.takeOverHint"),
                  });
                } catch {
                  addToast({ type: "error", title: t("task.diffMerge.clipboardUnavailable") });
                }
              }}
              className="flex items-center gap-1 px-2 py-1 rounded text-[11px] hover:bg-surface-hover text-foreground transition-colors"
              title={t("task.diffMerge.copyWorktreeHint")}
            >
              <Copy size={11} />
              {t("task.diffMerge.takeOverLocally")}
            </button>
          </div>
        )}
        {issue?.github_pr_url ? (
          <div className="flex items-center gap-2 text-[12px] -mt-1">
            <GitPullRequest size={12} className="text-text-muted" />
            <a
              href={issue.github_pr_url}
              target="_blank"
              rel="noreferrer"
              className="text-brand hover:underline flex items-center gap-1 truncate"
              title={issue.github_pr_url}
            >
              {issue.github_pr_url}
              <ExternalLink size={11} />
            </a>
            {issue.github_pr_state && (
              <span className="text-[11px] text-text-muted">
                · {issue.github_pr_state}
              </span>
            )}
            <Button
              size="sm"
              variant="ghost"
              disabled={!!busy}
              onClick={() => void handleRefreshPR()}
              data-density={busy === "pr-refresh" ? "diff-merge-pr-refresh-tool" : "diff-merge-pr-refresh"}
              className={cn("ml-auto", busy === "pr-refresh" && "motion-essential")}
              title={t("task.diffMerge.refreshPrHint")}
            >
              {busy === "pr-refresh" ? (
                <AgentThinkingIndicator phase="tool" size={12} />
              ) : (
                <RefreshCw size={12} />
              )}
              <span className="ml-1">{t("task.diffMerge.refreshPrButton")}</span>
            </Button>
          </div>
        ) : null}
        <div className="flex gap-2 flex-wrap">
          {!issue?.github_pr_url && (
            <Button
              disabled={!!busy || isAbandoned || !diff || diff.diff.length === 0}
              onClick={() => void handleCreatePR()}
              title={
                isAbandoned
                  ? t("task.diffMerge.issueAbandoned")
                  : diff && diff.diff.length === 0
                    ? t("task.diffMerge.nothingToOpenPr")
                    : t("task.diffMerge.createPrHint")
              }
              data-density={busy === "pr-create" ? "diff-merge-create-pr-dispatch" : "diff-merge-create-pr"}
              className={cn("bg-foreground text-background hover:bg-foreground/90", busy === "pr-create" && "motion-essential")}
            >
              {busy === "pr-create" ? (
                <span className="flex items-center gap-1.5">
                  <AgentThinkingIndicator phase="dispatching" size={12} /> {t("task.diffMerge.openingPr")}
                </span>
              ) : (
                <span className="flex items-center gap-1.5">
                  <GitPullRequest size={12} /> {t("task.diffMerge.openGitHubPr")}
                </span>
              )}
            </Button>
          )}
          <Button
            disabled={!!busy || isAbandoned || !diff || diff.diff.length === 0}
            onClick={() => setConfirmKind("merge")}
            variant="outline"
            title={
              isAbandoned
                ? t("task.diffMerge.issueAbandoned")
                : diff && diff.diff.length === 0
                  ? t("task.diffMerge.nothingToMerge")
                  : t("task.diffMerge.mergeHint")
            }
            data-density={busy === "merge" ? "diff-merge-back-dispatch" : "diff-merge-back"}
            className={cn(busy === "merge" && "motion-essential")}
          >
            {busy === "merge" ? (
              <span className="flex items-center gap-1.5">
                <AgentThinkingIndicator phase="dispatching" size={12} /> {t("task.diffMerge.merging")}
              </span>
            ) : (
              t("task.mergeBack")
            )}
          </Button>
          <Button
            disabled={!!busy || isAbandoned}
            variant="outline"
            onClick={() => setConfirmKind("abandon")}
            data-density={busy === "abandon" ? "diff-merge-abandon-dispatch" : "diff-merge-abandon"}
            className={cn(busy === "abandon" && "motion-essential")}
          >
            {busy === "abandon" ? (
              <span className="flex items-center gap-1.5">
                <AgentThinkingIndicator phase="dispatching" size={12} /> {t("task.diffMerge.abandoning")}
              </span>
            ) : isAbandoned ? (
              t("task.mergeStatus.abandoned")
            ) : (
              t("task.abandon")
            )}
          </Button>
        </div>
      </section>

      <section className="rounded-2xl border border-border-subtle overflow-hidden flex-1 min-h-[420px] flex flex-col">
        {/* === diff-toolbar (matches design handoff) === */}
        <div className="flex items-center justify-between gap-3.5 px-4 py-3 border-b border-border-subtle bg-surface flex-wrap shrink-0">
          <div className="flex items-center gap-4 font-mono text-[12px] text-text-muted flex-wrap">
            <span>
              <b className="text-foreground font-medium">
                {diff?.stat?.files ?? 0}
              </b>{" "}
              files changed
            </span>
            <span>
              <b className="text-status-done">
                +{diff?.stat?.insertions ?? 0}
              </b>{" "}
              <b className="text-status-failed">
                −{diff?.stat?.deletions ?? 0}
              </b>
            </span>
            <DiffStatBar
              add={diff?.stat?.insertions ?? 0}
              rm={diff?.stat?.deletions ?? 0}
            />
            <span className="text-text-faint">·</span>
            <span>
              base <b className="text-foreground font-medium">
                {diff?.base_branch ?? "—"}
              </b>{" "}
              ← head{" "}
              <b className="text-foreground font-medium">
                {diff?.branch ?? issue?.git_branch ?? "—"}
              </b>
            </span>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            {!issue?.github_pr_url && (
              <Button
                size="sm"
                variant="outline"
                disabled={!!busy || isAbandoned || !diff || diff.diff.length === 0}
                onClick={() => void handleCreatePR()}
                className="h-7 px-2.5 text-[12px]"
              >
                {busy === "pr-create" ? (
                  <Loader2 size={11} className="animate-spin" />
                ) : (
                  <GitPullRequest size={11} className="mr-1.5" />
                )}
                {t("task.diffMerge.openGitHubPr")}
              </Button>
            )}
            <Button
              size="sm"
              disabled={!!busy || isAbandoned || !diff || diff.diff.length === 0}
              onClick={() => setConfirmKind("merge")}
              className="h-7 px-2.5 text-[12px] bg-brand hover:bg-brand-strong text-black font-semibold"
            >
              {busy === "merge" ? (
                <span className="flex items-center gap-1.5">
                  <Loader2 size={11} className="animate-spin" />
                  {t("task.diffMerge.merging")}
                </span>
              ) : (
                t("task.mergeBack")
              )}
            </Button>
          </div>
        </div>
        {!diff ? (
          <div className="p-4 text-sm text-text-muted">{t("task.diffMerge.loading")}</div>
        ) : diff.diff.length === 0 ? (
          <div className="p-4 text-sm text-text-muted">{t("task.diffMerge.noChanges")}</div>
        ) : (
          <DiffSplitView diff={diff.diff} />
        )}
      </section>

      <ConfirmDialog
        open={confirmKind === "merge"}
        onOpenChange={(o) => !o && setConfirmKind(null)}
        title={t("task.mergeConfirmTitle")}
        description={t("task.diffMerge.mergeConfirmBody", {
          title: issue?.title ?? t("task.diffMerge.issueFallback"),
          base: diff?.base_branch ?? t("task.diffMerge.baseBranchFallback"),
        })}
        confirmText={t("task.mergeBack")}
        variant="default"
        isLoading={busy === "merge"}
        onConfirm={() => void performMerge(false)}
      />

      <ConfirmDialog
        open={confirmKind === "merge-force"}
        onOpenChange={(o) => {
          if (!o) {
            setConfirmKind(null);
            setMergeForceMessage(null);
          }
        }}
        title={t("task.diffMerge.forceMergeTitle")}
        description={
          mergeForceMessage
            ? `${mergeForceMessage}\n\n${t("task.diffMerge.forceMergeAnyway")}`
            : t("task.diffMerge.forceMergePrompt")
        }
        confirmText={t("task.diffMerge.forceMerge")}
        variant="warning"
        isLoading={busy === "merge"}
        onConfirm={() => void performMerge(true)}
      />

      <ConfirmDialog
        open={confirmKind === "abandon"}
        onOpenChange={(o) => !o && setConfirmKind(null)}
        title={t("task.abandonConfirmTitle")}
        description={t("task.abandonConfirmBody").replace("{branch}", issue?.git_branch ?? t("task.diffMerge.branchFallback"))}
        confirmText={t("task.abandon")}
        variant="destructive"
        isLoading={busy === "abandon"}
        onConfirm={() => void handleAbandon()}
      />

      <RejectDialog
        open={confirmKind === "reject"}
        reason={rejectReason}
        onReasonChange={setRejectReason}
        isLoading={busy === "review-reject"}
        onClose={() => setConfirmKind(null)}
        onConfirm={() => void handleRejectConfirm()}
      />

      {pendingAbandon && (
        <UndoBar
          message={t("task.diffMerge.abandonedUndoMessage", { title: pendingAbandon.title })}
          countdownSeconds={60}
          onUndo={handleAbandonUndo}
          onExpire={handleAbandonExpire}
          onDismiss={() => setPendingAbandon(null)}
        />
      )}
    </div>
  );
}

interface RejectDialogProps {
  open: boolean;
  reason: string;
  onReasonChange: (s: string) => void;
  isLoading: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

function RejectDialog({ open, reason, onReasonChange, isLoading, onClose, onConfirm }: RejectDialogProps) {
  const { t } = useI18n();
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-xl bg-popover p-5 ring-1 ring-foreground/10 shadow-xl">
        <h3 className="font-heading text-base font-medium mb-1">{t("task.review.rejectConfirmTitle")}</h3>
        <p className="text-xs text-text-muted mb-3">
          {t("task.review.rejectConfirmBody")}
        </p>
        <textarea
          autoFocus
          value={reason}
          onChange={(e) => onReasonChange(e.target.value)}
          rows={4}
          placeholder={t("task.review.rejectPlaceholder")}
          className="w-full rounded-md border border-border-subtle bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/50"
        />
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" disabled={isLoading} onClick={onClose}>
            {t("issue.cancel")}
          </Button>
          <Button
            disabled={isLoading}
            className="bg-warning text-background hover:bg-warning/90"
            onClick={onConfirm}
          >
            {isLoading ? (
              <span className="flex items-center gap-1.5">
                <Loader2 size={12} className="animate-spin" /> {t("task.review.rejecting")}
              </span>
            ) : (
              t("task.review.reject")
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}
