"use client";

import { useCallback, useEffect, useState } from "react";
import {
  abandonCodexIssue,
  getCodexIssueDiff,
  getCodexTasks,
  mergeCodexIssue,
  reviewCodexTask,
  submitCodexTask,
} from "@/lib/api";
import type { CodexIssue, CodexTask, IssueDiffResult } from "@/lib/types";
import { DiffPanel } from "@/features/issues/components/DiffPanel";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";

interface Props {
  issueId: string;
  issue: CodexIssue | null;
}

export function DiffMergeTab({ issueId, issue }: Props) {
  const { addToast } = useToast();
  const [diff, setDiff] = useState<IssueDiffResult | null>(null);
  const [tasks, setTasks] = useState<CodexTask[]>([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [d, t] = await Promise.all([
        getCodexIssueDiff(issueId),
        getCodexTasks(null, issueId),
      ]);
      setDiff(d);
      setTasks(t);
    } catch (err) {
      addToast({ type: "error", title: "Failed to load diff", message: err instanceof Error ? err.message : String(err) });
    }
  }, [issueId, addToast]);

  useEffect(() => {
    void load();
  }, [load]);

  const reviewableTask = tasks.find((t) => t.status === "awaiting_review");
  const doneTaskForSubmit = tasks.find((t) => t.status === "done");

  const handleSubmit = useCallback(async () => {
    if (!doneTaskForSubmit) return;
    setBusy(true);
    try {
      await submitCodexTask(doneTaskForSubmit.id);
      addToast({ type: "success", title: "Submitted for review" });
      await load();
    } catch (err) {
      addToast({ type: "error", title: "Submit failed", message: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  }, [doneTaskForSubmit, addToast, load]);

  const handleReview = useCallback(
    async (decision: "approve" | "reject", comment?: string) => {
      if (!reviewableTask) return;
      setBusy(true);
      try {
        await reviewCodexTask(reviewableTask.id, decision, comment ?? null);
        addToast({ type: "success", title: decision === "approve" ? "Approved" : "Sent back for rework" });
        await load();
      } catch (err) {
        addToast({ type: "error", title: "Review failed", message: err instanceof Error ? err.message : String(err) });
      } finally {
        setBusy(false);
      }
    },
    [reviewableTask, addToast, load]
  );

  const handleMerge = useCallback(async () => {
    if (!confirm("Squash-merge this issue into the base branch?")) return;
    setBusy(true);
    try {
      await mergeCodexIssue(issueId);
      addToast({ type: "success", title: "Merged" });
      await load();
    } catch (err) {
      addToast({ type: "error", title: "Merge failed", message: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  }, [issueId, addToast, load]);

  const handleAbandon = useCallback(async () => {
    if (!confirm("Abandon this issue and clean its worktree?")) return;
    setBusy(true);
    try {
      await abandonCodexIssue(issueId);
      addToast({ type: "success", title: "Abandoned" });
      await load();
    } catch (err) {
      addToast({ type: "error", title: "Abandon failed", message: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  }, [issueId, addToast, load]);

  return (
    <div className="p-6 flex flex-col gap-6">
      <section className="rounded-lg border border-border-subtle p-4">
        <h3 className="text-xs font-black uppercase tracking-widest text-text-muted mb-3">Review</h3>
        {reviewableTask ? (
          <div className="flex flex-col gap-2">
            <div className="text-sm">
              Task <b>{reviewableTask.title}</b> is awaiting architect review.
            </div>
            <div className="flex gap-2">
              <Button disabled={busy} onClick={() => void handleReview("approve")}>Approve</Button>
              <Button disabled={busy} variant="outline" onClick={() => {
                const comment = prompt("Reason for rejecting?") ?? undefined;
                void handleReview("reject", comment);
              }}>Reject</Button>
            </div>
          </div>
        ) : doneTaskForSubmit ? (
          <Button disabled={busy} onClick={() => void handleSubmit()}>Submit for review</Button>
        ) : (
          <div className="text-sm text-text-muted">No tasks are ready to submit yet.</div>
        )}
      </section>

      <section className="rounded-lg border border-border-subtle p-4 flex flex-col gap-3">
        <h3 className="text-xs font-black uppercase tracking-widest text-text-muted">Branch operations</h3>
        <div className="text-xs text-text-muted">
          Branch: <code className="font-mono">{issue?.git_branch ?? "—"}</code> → base: <code className="font-mono">{diff?.base_branch ?? "—"}</code>
        </div>
        <div className="flex gap-2">
          <Button disabled={busy} onClick={() => void handleMerge()}>Squash-merge</Button>
          <Button disabled={busy} variant="outline" onClick={() => void handleAbandon()}>Abandon</Button>
        </div>
      </section>

      <section className="rounded-lg border border-border-subtle p-4">
        <h3 className="text-xs font-black uppercase tracking-widest text-text-muted mb-3">Diff</h3>
        {!diff ? (
          <div className="text-sm text-text-muted">Loading…</div>
        ) : diff.diff.length === 0 ? (
          <div className="text-sm text-text-muted">No changes vs base.</div>
        ) : (
          <DiffPanel diff={diff.diff} baseBranch={diff.base_branch} branch={diff.branch} stat={diff.stat ?? null} />
        )}
      </section>
    </div>
  );
}
