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
import { DiffPanel } from "@/features/issues/components/DiffPanel";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";
import { UndoBar } from "@/components/ui/undo-bar";
import { cn } from "@/lib/utils";

interface Props {
  issueId: string;
  issue: CodexIssue | null;
  /** Active state from parent — refetch when this becomes true. */
  active: boolean;
}

const ACTIVE_STATUSES = new Set(["open", "in_progress"]);

type BusyKind = "submit" | "review-approve" | "review-reject" | "merge" | "abandon" | "pr-create" | "pr-refresh" | null;
type ConfirmKind = "merge" | "merge-force" | "abandon" | "reject" | null;

export function DiffMergeTab({ issueId, issue, active }: Props) {
  const { addToast } = useToast();
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
            title: "Failed to load diff",
            message: err instanceof Error ? err.message : String(err),
          });
        }
      } finally {
        if (mode === "refresh") setIsRefreshing(false);
        inFlight.current = false;
      }
    },
    [issueId, addToast],
  );

  useEffect(() => {
    if (!active) return;
    void load(lastFetched === null ? "initial" : "refresh");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, issueId]);

  useEffect(() => {
    if (!active) return;
    if (!issue || !ACTIVE_STATUSES.has(issue.status ?? "")) return;
    const id = window.setInterval(() => void load("poll"), 5000);
    return () => window.clearInterval(id);
  }, [active, issue, load]);

  const reviewableTask = tasks.find((t) => t.status === "awaiting_review");
  const doneTaskForSubmit = tasks.find((t) => t.status === "done");
  const isAbandoned = issue?.status === "cancelled";
  // C3: which Engineer run produced these changes. Only Engineer touches
  // code in this system, so a single attribution covers the whole diff.
  const engineerAttribution = (() => {
    const engs = tasks.filter((t) => t.role === "engineer" && t.status === "done");
    if (engs.length === 0) return null;
    const latest = engs[engs.length - 1];
    return {
      agentName: "Engineer",
      runId: latest.last_execution_process_id ?? latest.id,
      timestamp: latest.updated_at ?? null,
    };
  })();

  const handleSubmit = useCallback(async () => {
    if (!doneTaskForSubmit) return;
    setBusy("submit");
    try {
      await submitCodexTask(doneTaskForSubmit.id);
      addToast({ type: "success", title: "Submitted for review" });
      await load("refresh");
    } catch (err) {
      addToast({
        type: "error",
        title: "Submit failed",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBusy(null);
    }
  }, [doneTaskForSubmit, addToast, load]);

  const handleApprove = useCallback(async () => {
    if (!reviewableTask) return;
    setBusy("review-approve");
    try {
      await reviewCodexTask(reviewableTask.id, "approve", null);
      addToast({ type: "success", title: "Approved" });
      await load("refresh");
    } catch (err) {
      addToast({
        type: "error",
        title: "Review failed",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBusy(null);
    }
  }, [reviewableTask, addToast, load]);

  const handleRejectConfirm = useCallback(async () => {
    if (!reviewableTask) return;
    setBusy("review-reject");
    setConfirmKind(null);
    try {
      await reviewCodexTask(reviewableTask.id, "reject", rejectReason || null);
      addToast({ type: "success", title: "Sent back for rework" });
      setRejectReason("");
      await load("refresh");
    } catch (err) {
      addToast({
        type: "error",
        title: "Review failed",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBusy(null);
    }
  }, [reviewableTask, rejectReason, addToast, load]);

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
          title: force ? "Merged (forced over diverged base)" : "Merged",
          message: weekly !== null
            ? `${weekly} ${weekly === 1 ? "issue" : "issues"} merged this week.`
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
        addToast({ type: "error", title: "Merge failed", message: msg });
      } finally {
        setBusy(null);
      }
    },
    [issueId, addToast, load],
  );

  const handleCreatePR = useCallback(async () => {
    setBusy("pr-create");
    try {
      const updated = await createGithubPR(issueId, {});
      addToast({
        type: "success",
        title: "GitHub PR opened",
        message: updated.github_pr_url ?? undefined,
      });
      await load("refresh");
    } catch (err) {
      addToast({
        type: "error",
        title: "Create PR failed",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBusy(null);
    }
  }, [issueId, addToast, load]);

  const handleRefreshPR = useCallback(async () => {
    setBusy("pr-refresh");
    try {
      await refreshGithubPR(issueId);
      addToast({ type: "success", title: "PR state refreshed" });
      await load("refresh");
    } catch (err) {
      addToast({
        type: "error",
        title: "Refresh PR failed",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBusy(null);
    }
  }, [issueId, addToast, load]);

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
        title: "Abandon failed",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBusy(null);
    }
  }, [issueId, issue?.title, addToast, load]);

  const handleAbandonUndo = useCallback(async () => {
    if (!pendingAbandon) return;
    try {
      await restoreCodexIssue(pendingAbandon.issueId);
      addToast({ type: "success", title: "Restored" });
    } catch (err) {
      addToast({
        type: "error",
        title: "Restore failed",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setPendingAbandon(null);
      await load("refresh");
    }
  }, [pendingAbandon, addToast, load]);

  const handleAbandonExpire = useCallback(async () => {
    if (!pendingAbandon) return;
    try {
      await finalizeAbandonedCodexIssue(pendingAbandon.issueId);
    } catch {
      // Silent — the issue is already in abandoned state; finalize is just
      // a worktree-cleanup hint. Surface in toast as a soft warning.
      addToast({ type: "info", title: "Worktree cleanup deferred — retry from issue menu if needed" });
    } finally {
      setPendingAbandon(null);
    }
  }, [pendingAbandon, addToast]);

  return (
    <div className="p-6 flex flex-col gap-6">
      <div className="flex items-center justify-between -mt-2">
        <div className="text-[11px] text-text-muted">
          {lastFetched ? <>Last refreshed {timeAgo(lastFetched)}</> : "—"}
        </div>
        <Button
          size="sm"
          variant="outline"
          disabled={isRefreshing || !!busy}
          onClick={() => void load("refresh")}
        >
          <RefreshCw size={12} className={cn("mr-1.5", isRefreshing && "animate-spin")} />
          Refresh
        </Button>
      </div>

      <section className="rounded-lg border border-border-subtle p-4">
        <h3 className="text-xs font-black uppercase tracking-widest text-text-muted mb-3">Review</h3>
        {reviewableTask ? (
          <div className="flex flex-col gap-3">
            <div className="text-sm">
              Task <b>{reviewableTask.title}</b> is awaiting architect review.
            </div>
            <div className="flex gap-2">
              <Button
                disabled={!!busy}
                onClick={() => void handleApprove()}
              >
                {busy === "review-approve" ? (
                  <span className="flex items-center gap-1.5">
                    <Loader2 size={12} className="animate-spin" /> Approving…
                  </span>
                ) : (
                  "Approve"
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
                Reject
              </Button>
            </div>
          </div>
        ) : doneTaskForSubmit ? (
          <Button disabled={!!busy} onClick={() => void handleSubmit()}>
            {busy === "submit" ? (
              <span className="flex items-center gap-1.5">
                <Loader2 size={12} className="animate-spin" /> Submitting…
              </span>
            ) : (
              "Submit for review"
            )}
          </Button>
        ) : (
          <div className="text-sm text-text-muted">No tasks are ready to submit yet.</div>
        )}
      </section>

      <section className="rounded-lg border border-border-subtle p-4 flex flex-col gap-3">
        <h3 className="text-xs font-black uppercase tracking-widest text-text-muted">Branch operations</h3>
        <div className="text-xs text-text-muted">
          Branch: <code className="font-mono">{issue?.git_branch ?? "—"}</code> → base: <code className="font-mono">{diff?.base_branch ?? "—"}</code>
        </div>
        {issue?.git_worktree_path && (
          <div className="flex items-center gap-2 text-[11px] text-text-muted bg-surface-input/40 rounded-md px-3 py-1.5 border border-border-subtle">
            <Terminal size={11} className="shrink-0" />
            <code className="font-mono truncate flex-1">{issue.git_worktree_path}</code>
            <button
              type="button"
              onClick={() => {
                const cmd = `cd "${issue.git_worktree_path}" && code .`;
                void navigator.clipboard.writeText(cmd);
                addToast({
                  type: "success",
                  title: "Copied to clipboard",
                  message: `Paste in terminal to take over locally`,
                });
              }}
              className="flex items-center gap-1 px-2 py-1 rounded text-[11px] hover:bg-surface-hover text-foreground transition-colors"
              title="Copy cd + code . to clipboard so you can take over manually"
            >
              <Copy size={11} />
              Take over locally
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
              className="ml-auto"
              title="Re-poll gh pr view; if reviewers requested changes the engineer is auto-re-dispatched"
            >
              {busy === "pr-refresh" ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <RefreshCw size={12} />
              )}
              <span className="ml-1">Refresh PR</span>
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
                  ? "Issue is abandoned"
                  : diff && diff.diff.length === 0
                    ? "Nothing to open a PR for"
                    : "git push + gh pr create"
              }
              className="bg-foreground text-background hover:bg-foreground/90"
            >
              {busy === "pr-create" ? (
                <span className="flex items-center gap-1.5">
                  <Loader2 size={12} className="animate-spin" /> Opening PR…
                </span>
              ) : (
                <span className="flex items-center gap-1.5">
                  <GitPullRequest size={12} /> Open GitHub PR
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
                ? "Issue is abandoned"
                : diff && diff.diff.length === 0
                  ? "Nothing to merge"
                  : "Squash-merge locally without going through GitHub"
            }
          >
            {busy === "merge" ? (
              <span className="flex items-center gap-1.5">
                <Loader2 size={12} className="animate-spin" /> Merging…
              </span>
            ) : (
              "Squash-merge"
            )}
          </Button>
          <Button
            disabled={!!busy || isAbandoned}
            variant="outline"
            onClick={() => setConfirmKind("abandon")}
          >
            {busy === "abandon" ? (
              <span className="flex items-center gap-1.5">
                <Loader2 size={12} className="animate-spin" /> Abandoning…
              </span>
            ) : isAbandoned ? (
              "Abandoned"
            ) : (
              "Abandon"
            )}
          </Button>
        </div>
      </section>

      <section className="rounded-lg border border-border-subtle p-4">
        <h3 className="text-xs font-black uppercase tracking-widest text-text-muted mb-3">Diff</h3>
        {!diff ? (
          <div className="text-sm text-text-muted">Loading…</div>
        ) : diff.diff.length === 0 ? (
          <div className="text-sm text-text-muted">No changes vs base.</div>
        ) : (
          <DiffPanel
            diff={diff.diff}
            baseBranch={diff.base_branch}
            branch={diff.branch}
            stat={diff.stat ?? null}
            attribution={engineerAttribution}
          />
        )}
      </section>

      <ConfirmDialog
        open={confirmKind === "merge"}
        onOpenChange={(o) => !o && setConfirmKind(null)}
        title="Squash-merge this issue?"
        description={`This squashes "${issue?.title ?? "issue"}" onto ${diff?.base_branch ?? "the base branch"} and discards the worktree.`}
        confirmText="Squash-merge"
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
        title="Base has advanced — force merge?"
        description={
          mergeForceMessage
            ? `${mergeForceMessage}\n\nForce-merge anyway (your changes will be squashed on top of the new base).`
            : "Force-merge anyway?"
        }
        confirmText="Force-merge"
        variant="warning"
        isLoading={busy === "merge"}
        onConfirm={() => void performMerge(true)}
      />

      <ConfirmDialog
        open={confirmKind === "abandon"}
        onOpenChange={(o) => !o && setConfirmKind(null)}
        title="Abandon this issue?"
        description="The worktree will be removed and the issue marked cancelled. This cannot be undone."
        confirmText="Abandon"
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
          message={`"${pendingAbandon.title}" abandoned`}
          countdownSeconds={60}
          onUndo={handleAbandonUndo}
          onExpire={handleAbandonExpire}
          onDismiss={() => setPendingAbandon(null)}
        />
      )}
    </div>
  );
}

function timeAgo(ts: number): string {
  const delta = Date.now() - ts;
  if (delta < 1500) return "just now";
  if (delta < 60_000) return `${Math.floor(delta / 1000)}s ago`;
  if (delta < 3_600_000) return `${Math.floor(delta / 60_000)}m ago`;
  return `${Math.floor(delta / 3_600_000)}h ago`;
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
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-xl bg-popover p-5 ring-1 ring-foreground/10 shadow-xl">
        <h3 className="font-heading text-base font-medium mb-1">Reject this submission?</h3>
        <p className="text-xs text-text-muted mb-3">
          The task is sent back to the engineer with this feedback.
        </p>
        <textarea
          autoFocus
          value={reason}
          onChange={(e) => onReasonChange(e.target.value)}
          rows={4}
          placeholder="What needs to change?"
          className="w-full rounded-md border border-border-subtle bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/50"
        />
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" disabled={isLoading} onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={isLoading}
            className="bg-warning text-background hover:bg-warning/90"
            onClick={onConfirm}
          >
            {isLoading ? (
              <span className="flex items-center gap-1.5">
                <Loader2 size={12} className="animate-spin" /> Rejecting…
              </span>
            ) : (
              "Reject"
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}
