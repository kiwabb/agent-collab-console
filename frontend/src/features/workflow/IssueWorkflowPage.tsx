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

import { ReplanDiffModal } from "./ReplanDiffModal";
import { WorkflowGraphView } from "./WorkflowGraphView";

interface Props {
  issueId: string;
}

type View = "loading" | "no-graph" | "preview" | "saved";

export function IssueWorkflowPage({ issueId }: Props) {
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
    loadGraph();
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
      <header className="flex items-baseline justify-between">
        <div>
          <h1 className="text-xl font-semibold">Issue Workflow</h1>
          <p className="text-xs text-muted-foreground">Issue ID: {issueId}</p>
        </div>
        <div className="flex gap-2">
          {(view === "no-graph" || view === "saved") && (
            <button
              type="button"
              className="rounded border border-border bg-card px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
              disabled={busy}
              onClick={handleAutoPlan}
            >
              {busy ? "Planning…" : "Auto-plan"}
            </button>
          )}
          {view === "preview" && (
            <>
              <button
                type="button"
                className="rounded border border-border bg-card px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
                disabled={busy}
                onClick={() => {
                  setProposal(null);
                  loadGraph();
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                className="rounded border border-primary bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:opacity-90 disabled:opacity-50"
                disabled={busy}
                onClick={handleSave}
              >
                {busy ? "Saving…" : "Save graph"}
              </button>
            </>
          )}
          {view === "saved" && graph && graph.status === "draft" && (
            <button
              type="button"
              className="rounded border border-primary bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:opacity-90 disabled:opacity-50"
              disabled={busy}
              onClick={handleStart}
            >
              {busy ? "Starting…" : "Start"}
            </button>
          )}
        </div>
      </header>

      {error && (
        <div className="rounded border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {view === "loading" && <div className="text-sm text-muted-foreground">Loading…</div>}

      {view === "no-graph" && (
        <div className="rounded border border-dashed border-border bg-muted/30 p-6 text-center text-sm text-muted-foreground">
          No workflow graph yet for this issue. Click <b>Auto-plan</b> to ask the orchestrator for a DAG proposal.
        </div>
      )}

      {view === "preview" && proposal && (
        <div className="flex flex-col gap-3">
          <div className="rounded border border-border bg-muted/30 px-3 py-2 text-xs">
            <div>
              <b>Intent:</b> {proposal.meta?.intent ?? "(unknown)"}
            </div>
            <div className="text-muted-foreground">{proposal.meta?.rationale}</div>
          </div>
          <WorkflowGraphView graph={proposal} className="rounded border border-border bg-card" />
        </div>
      )}

      {view === "saved" && graph && (
        <div className="flex flex-col gap-3">
          <div className="text-xs text-muted-foreground">
            Graph <code className="font-mono">{graph.id.slice(0, 8)}…</code> · status:{" "}
            <b>{graph.status}</b> · created_by: {graph.created_by ?? "—"}
          </div>
          <WorkflowGraphView graph={graph} className="rounded border border-border bg-card" />
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
