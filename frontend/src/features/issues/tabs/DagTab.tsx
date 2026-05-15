"use client";

import { useCallback, useEffect, useState } from "react";
import {
  confirmReplan,
  getIssueGraph,
  listReplanPending,
  planIssue,
  rejectReplan,
  saveIssueGraph,
  startIssueGraph,
  type ReplanPending,
} from "@/lib/api";
import type { ProposedDAG, WorkflowGraph } from "@/lib/types";
import { ReplanDiffModal } from "@/features/workflow/ReplanDiffModal";
import { WorkflowGraphView } from "@/features/workflow/WorkflowGraphView";
import { Button } from "@/components/ui/button";

interface Props {
  issueId: string;
}

type View = "loading" | "no-graph" | "preview" | "saved";

export function DagTab({ issueId }: Props) {
  const [view, setView] = useState<View>("loading");
  const [graph, setGraph] = useState<WorkflowGraph | null>(null);
  const [proposal, setProposal] = useState<ProposedDAG | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pendingReplans, setPendingReplans] = useState<ReplanPending[]>([]);

  const loadPendingReplans = useCallback(async () => {
    try {
      const list = await listReplanPending(issueId);
      setPendingReplans(list);
    } catch {
      setPendingReplans([]);
    }
  }, [issueId]);

  const loadGraph = useCallback(async () => {
    try {
      const g = await getIssueGraph(issueId);
      if (g) {
        setGraph(g);
        setView("saved");
      } else {
        setGraph(null);
        setView("no-graph");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setView("no-graph");
    }
    await loadPendingReplans();
  }, [issueId, loadPendingReplans]);

  useEffect(() => {
    void loadGraph();
  }, [loadGraph]);

  async function handleReplanDecision(replanId: string, decision: "confirm" | "reject") {
    setBusy(true);
    setError(null);
    try {
      const updated = decision === "confirm"
        ? await confirmReplan(issueId, replanId)
        : await rejectReplan(issueId, replanId);
      setGraph(updated);
      await loadPendingReplans();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleAutoPlan() {
    setBusy(true);
    setError(null);
    try {
      const proposed = await planIssue(issueId);
      setProposal(proposed);
      setView("preview");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleSave() {
    if (!proposal) return;
    setBusy(true);
    setError(null);
    try {
      const saved = await saveIssueGraph(issueId, proposal);
      setGraph(saved);
      setProposal(null);
      setView("saved");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleStart() {
    if (!graph) return;
    setBusy(true);
    setError(null);
    try {
      const started = await startIssueGraph(issueId);
      setGraph(started);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-4 p-6">
      <div className="flex justify-end gap-2">
        {(view === "no-graph" || view === "saved") && (
          <Button onClick={handleAutoPlan} disabled={busy}>
            {busy ? "Planning…" : "Auto-plan"}
          </Button>
        )}
        {view === "preview" && (
          <>
            <Button variant="outline" disabled={busy} onClick={() => { setProposal(null); void loadGraph(); }}>
              Cancel
            </Button>
            <Button disabled={busy} onClick={handleSave}>
              {busy ? "Saving…" : "Save graph"}
            </Button>
          </>
        )}
        {view === "saved" && graph && graph.status === "draft" && (
          <Button disabled={busy} onClick={handleStart}>
            {busy ? "Starting…" : "Start"}
          </Button>
        )}
      </div>

      {error && (
        <div className="rounded border border-error/40 bg-error/10 px-3 py-2 text-sm text-error">
          {error}
        </div>
      )}

      {view === "loading" && <div className="text-sm text-text-muted">Loading…</div>}

      {view === "no-graph" && (
        <div className="rounded border border-dashed border-border-subtle p-6 text-center text-sm text-text-muted">
          No workflow graph yet for this issue. Click <b>Auto-plan</b> to ask the orchestrator for a DAG proposal.
        </div>
      )}

      {view === "preview" && proposal && (
        <div className="flex flex-col gap-3">
          <div className="rounded border border-border-subtle bg-surface/40 px-3 py-2 text-xs">
            <div><b>Intent:</b> {proposal.meta?.intent ?? "(unknown)"}</div>
            <div className="text-text-muted">{proposal.meta?.rationale}</div>
          </div>
          <WorkflowGraphView graph={proposal} className="rounded border border-border-subtle bg-surface" />
        </div>
      )}

      {view === "saved" && graph && (
        <div className="flex flex-col gap-3">
          <div className="text-xs text-text-muted">
            Graph <code className="font-mono">{graph.id.slice(0, 8)}…</code> · status: <b>{graph.status}</b> · created_by: {graph.created_by ?? "—"}
          </div>
          <WorkflowGraphView graph={graph} className="rounded border border-border-subtle bg-surface" />
        </div>
      )}

      {pendingReplans.length > 0 && (
        <ReplanDiffModal
          issueId={issueId}
          pending={pendingReplans[0]}
          busy={busy}
          onConfirm={() => handleReplanDecision(pendingReplans[0].id, "confirm")}
          onReject={() => handleReplanDecision(pendingReplans[0].id, "reject")}
        />
      )}
    </div>
  );
}
