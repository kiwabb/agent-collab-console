"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  applyWorkflowTemplate,
  confirmReplan,
  getIssueGraph,
  getIssueGraphStats,
  listReplanPending,
  listWorkflowTemplates,
  planIssueStream,
  rejectReplan,
  runCodexTask,
  saveIssueGraph,
  startIssueGraph,
  type GraphStatsResponse,
  type ReplanPending,
  type WorkflowTemplateSummary,
} from "@/lib/api";
import type { ProposedDAG, WorkflowGraph } from "@/lib/types";
import { Loader2 } from "lucide-react";
import { ReplanDiffModal } from "@/features/workflow/ReplanDiffModal";
import { WorkflowGraphView, type WorkflowNodeClickPayload } from "@/features/workflow/WorkflowGraphView";
import { ConductorLogPanel } from "@/features/workflow/ConductorLogPanel";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import { agentBus } from "@/features/agents/dock/agentBus";
import { AgentStatusProvider, useAgentStatusContext } from "@/features/agents/dock/AgentStatusProvider";
import { AgentDecisionDrawer } from "@/features/issues/components/AgentDecisionDrawer";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";

interface Props {
  issueId: string;
}

type View = "loading" | "no-graph" | "preview" | "saved" | "streaming";

interface StreamMeta {
  executor: string | null;
  model: string | null;
  reason?: string;
}

const EMPTY_DAG: ProposedDAG = {
  meta: { intent: "", rationale: "", created_by: "stream" },
  nodes: [],
  edges: [],
};

export function DagTab({ issueId }: Props) {
  const router = useRouter();
  const { addToast } = useToast();
  const [view, setView] = useState<View>("loading");
  const [graph, setGraph] = useState<WorkflowGraph | null>(null);
  const [graphStats, setGraphStats] = useState<GraphStatsResponse | null>(null);
  const [proposal, setProposal] = useState<ProposedDAG | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pendingReplans, setPendingReplans] = useState<ReplanPending[]>([]);
  // Streaming state
  const [streamMeta, setStreamMeta] = useState<StreamMeta | null>(null);
  const [streamLog, setStreamLog] = useState<string>("");
  const [streamDag, setStreamDag] = useState<ProposedDAG>(EMPTY_DAG);
  // Conductor click opens its own timeline drawer (the role-node click
  // path routes to /tasks?taskId=…; Conductor has no task).
  const [conductorPanelOpen, setConductorPanelOpen] = useState(false);
  // Failed-node retry confirmation. Holds the payload while the dialog is
  // open so we can dispatch on confirm.
  const [retryTarget, setRetryTarget] = useState<WorkflowNodeClickPayload | null>(null);
  const [retryBusy, setRetryBusy] = useState(false);
  // C2: explain decision drawer. Holds the task_id of the node whose
  // reasoning the user wants to inspect. Triggered by alt/shift/cmd-click
  // on any DAG node — leaves the default left-click → Tasks·Runs route
  // untouched for muscle memory.
  const [explainTaskId, setExplainTaskId] = useState<string | null>(null);
  // S3a: workflow templates. Listed once at mount; rendered as cards when
  // there's no graph yet so the user can skip Auto-plan for common shapes.
  // (Handler defined below `loadGraph` to satisfy the let-temporal-dead-zone.)
  const [templates, setTemplates] = useState<WorkflowTemplateSummary[]>([]);
  const [applyingTemplate, setApplyingTemplate] = useState<string | null>(null);

  useEffect(() => {
    void listWorkflowTemplates().then(setTemplates).catch(() => setTemplates([]));
  }, []);
  const logRef = useRef<HTMLPreElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [streamLog]);

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
    // Refresh per-node telemetry alongside the graph. Errors are silent —
    // the DAG still renders without stats.
    try {
      const s = await getIssueGraphStats(issueId);
      setGraphStats(s);
    } catch {
      setGraphStats(null);
    }
  }, [issueId, loadPendingReplans]);

  useEffect(() => {
    void loadGraph();
  }, [loadGraph]);

  const handleApplyTemplate = useCallback(
    async (templateId: string) => {
      setApplyingTemplate(templateId);
      setError(null);
      try {
        await applyWorkflowTemplate(issueId, templateId);
        addToast({
          type: "success",
          title: "Template applied",
          message: "Graph materialized — click Start to dispatch.",
        });
        await loadGraph();
      } catch (err) {
        addToast({
          type: "error",
          title: "Apply template failed",
          message: err instanceof Error ? err.message : String(err),
        });
      } finally {
        setApplyingTemplate(null);
      }
    },
    [issueId, addToast, loadGraph],
  );

  useEffect(() => () => abortRef.current?.abort(), []);

  // Event-driven graph refresh. workflow_node_updated fires on every node
  // transition; task_status fires terminal events. We refetch in either case
  // so the UI flips state in the same tick the scheduler updates the DB.
  const refreshGraph = useCallback(() => {
    if (view !== "saved") return;
    getIssueGraph(issueId)
      .then((g) => g && setGraph(g))
      .catch(() => {});
  }, [issueId, view]);

  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn("workflow_node_updated", "task_status", "task_created"),
    ),
    onEvent: refreshGraph,
    throttleMs: 300,
    enabled: view === "saved",
  });

  // Fallback poll while the graph is actively running, in case events drop.
  useEffect(() => {
    if (view !== "saved" || graph?.status !== "running") return;
    const id = window.setInterval(() => {
      getIssueGraph(issueId)
        .then((g) => g && setGraph(g))
        .catch(() => {});
    }, 20000);
    return () => window.clearInterval(id);
  }, [view, graph?.status, issueId]);

  const handleNodeClick = useCallback(
    async (payload: WorkflowNodeClickPayload) => {
      // Virtual Conductor root → open timeline drawer instead of routing.
      if (payload.node_key === "__conductor__" || payload.node_key === "conductor") {
        setConductorPanelOpen(true);
        return;
      }
      if (!payload.task_id) {
        addToast({
          type: "info",
          title: `Node "${payload.node_key}"`,
          message: payload.status
            ? `Status: ${payload.status} — no task spawned yet.`
            : "No task spawned yet for this node.",
        });
        return;
      }
      // C2: alt/option-click opens the "explain decision" drawer with
      // structured prose from task.result instead of routing to the raw
      // Tasks·Runs view. Default (plain) click keeps the legacy behavior.
      if (payload.altKey || payload.shiftKey) {
        setExplainTaskId(payload.task_id);
        return;
      }
      // Failed QA node: open the explain drawer so the user can read bugs/risks
      // before deciding to retry. Other failed nodes keep the retry dialog.
      if (payload.status === "failed") {
        if (payload.node_key === "qa") {
          setExplainTaskId(payload.task_id);
        } else {
          setRetryTarget(payload);
        }
        return;
      }
      router.push(`/issues/${issueId}?tab=tasks&taskId=${payload.task_id}`);
    },
    [router, issueId, addToast],
  );

  const handleRetryConfirm = useCallback(async () => {
    if (!retryTarget?.task_id) return;
    setRetryBusy(true);
    try {
      await runCodexTask(retryTarget.task_id);
      addToast({ type: "success", title: "Retry dispatched" });
      const fresh = await getIssueGraph(issueId).catch(() => null);
      if (fresh) setGraph(fresh);
      setRetryTarget(null);
    } catch (err) {
      addToast({
        type: "error",
        title: "Retry failed",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setRetryBusy(false);
    }
  }, [retryTarget, addToast, issueId]);

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
    setStreamMeta(null);
    setStreamLog("");
    setStreamDag(EMPTY_DAG);
    setProposal(null);
    setView("streaming");

    // Notify the AgentDock — Conductor goes live.
    agentBus.onConductorConnecting(issueId);

    const ac = new AbortController();
    abortRef.current = ac;
    try {
      await planIssueStream(issueId, {
        signal: ac.signal,
        onMeta: (m) => {
          setStreamMeta(m);
          agentBus.onConductorMeta(issueId, m);
          if (m.executor) {
            setStreamLog((s) => s + `▶ Using ${m.executor} / ${m.model}\n`);
          } else if (m.reason) {
            setStreamLog((s) => s + `! ${m.reason}\n`);
          }
        },
        onLog: (msg) => {
          setStreamLog((s) => s + `· ${msg}\n`);
          agentBus.onConductorLog(issueId, msg);
        },
        onChunk: (text) => setStreamLog((s) => s + text),
        onNode: (node) => {
          setStreamDag((d) => ({ ...d, nodes: [...d.nodes, node as unknown as ProposedDAG["nodes"][number]] }));
          agentBus.onConductorNode(issueId, node as { node_key?: string; title?: string });
        },
        onEdge: (edge) => {
          setStreamDag((d) => ({ ...d, edges: [...d.edges, edge as unknown as ProposedDAG["edges"][number]] }));
          agentBus.onConductorEdge(issueId, edge as { from_node_key?: string; to_node_key?: string });
        },
        onDone: (dag) => {
          setProposal(dag);
          setView("preview");
          agentBus.onConductorDone(issueId);
        },
        onError: (msg) => {
          setError(msg);
          setStreamLog((s) => s + `\n✗ ${msg}\n`);
          setView("no-graph");
          agentBus.onConductorError(issueId, msg);
        },
      });
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setError(e instanceof Error ? e.message : String(e));
        setView("no-graph");
      }
    } finally {
      setBusy(false);
      abortRef.current = null;
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
    <AgentStatusProvider issueId={issueId}>
      <ConductorPanelHost
        issueId={issueId}
        open={conductorPanelOpen}
        onClose={() => setConductorPanelOpen(false)}
      />
    <div className="flex flex-col gap-4 p-6 flex-1 min-h-0 h-full relative">
      {view !== "saved" && (
        <div className="flex justify-end gap-3 items-center">
          {(view === "no-graph" || view === "preview") && (
            <Button onClick={handleAutoPlan} disabled={busy} className="shadow-sm">
              {busy ? "Planning…" : "Auto-plan"}
            </Button>
          )}
          {view === "streaming" && (
            <>
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-brand/10 border border-brand/30 text-brand text-xs font-semibold mr-auto">
                <Loader2 size={14} className="animate-spin" />
                {streamMeta?.executor
                  ? `Planning · ${streamMeta.executor}/${streamMeta.model}`
                  : "Connecting to LLM…"}
              </div>
              <Button variant="outline" onClick={() => abortRef.current?.abort()}>
                Cancel
              </Button>
            </>
          )}
          {view === "preview" && proposal && (
            <>
              <Button variant="outline" disabled={busy} onClick={() => { setProposal(null); void loadGraph(); }}>
                Discard
              </Button>
              <Button disabled={busy} onClick={handleSave} className="bg-brand text-black hover:bg-brand-strong">
                {busy ? "Saving…" : "Save graph"}
              </Button>
            </>
          )}
        </div>
      )}

      {error && (
        <div className="rounded border border-error/40 bg-error/10 px-3 py-2 text-sm text-error">
          {error}
        </div>
      )}

      {view === "loading" && <div className="text-sm text-text-muted">Loading…</div>}

      {view === "no-graph" && (
        <div className="flex flex-col gap-4">
          <div className="rounded border border-dashed border-border-subtle p-6 text-center text-sm text-text-muted">
            No workflow graph yet. Click <b>Auto-plan</b> for an LLM proposal,
            or pick a template below to skip straight to a known shape.
          </div>
          {templates.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
              {templates.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  disabled={!!applyingTemplate}
                  onClick={() => void handleApplyTemplate(t.id)}
                  className={
                    "text-left rounded-lg border border-border-subtle bg-surface px-3 py-2.5 " +
                    "hover:border-brand/50 hover:bg-surface-hover transition-colors " +
                    (applyingTemplate === t.id ? "opacity-60" : "")
                  }
                >
                  <div className="flex items-baseline justify-between mb-0.5 gap-2">
                    <span className="text-[13px] font-semibold">{t.name}</span>
                    <span className="text-[10px] uppercase tracking-wider text-text-muted shrink-0">
                      {t.role_order.length} phase{t.role_order.length === 1 ? "" : "s"}
                    </span>
                  </div>
                  <p className="text-[11px] text-text-muted leading-snug">
                    {t.description}
                  </p>
                  <div className="flex flex-wrap gap-1 mt-1.5">
                    {t.role_order.map((r) => (
                      <span
                        key={r}
                        className="text-[9px] uppercase tracking-wider bg-surface-input rounded px-1 py-0.5 text-text-muted"
                      >
                        {r.replace("_", " ")}
                      </span>
                    ))}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {(view === "streaming" || view === "preview") && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="rounded border border-border-subtle bg-surface flex flex-col min-h-[300px]">
            <div className="px-3 py-2 border-b border-border-subtle flex items-center justify-between">
              <div className="text-[10px] font-black uppercase tracking-widest text-text-muted">
                LLM stream
              </div>
              {streamMeta?.executor && (
                <div className="text-[11px] font-mono text-text-muted">
                  {streamMeta.executor} / {streamMeta.model}
                </div>
              )}
            </div>
            <pre
              ref={logRef}
              className="flex-1 overflow-auto p-3 text-[11px] font-mono leading-relaxed whitespace-pre-wrap text-text-secondary"
            >
              {streamLog ? (
                <>
                  {streamLog}
                  {view === "streaming" && <span className="inline-block w-2 h-3 ml-0.5 bg-brand animate-pulse" aria-hidden />}
                </>
              ) : view === "streaming" ? (
                <span className="text-text-muted">
                  Waiting for LLM
                  <span className="inline-flex w-6 justify-start">
                    <span className="animate-pulse [animation-delay:0ms]">.</span>
                    <span className="animate-pulse [animation-delay:200ms]">.</span>
                    <span className="animate-pulse [animation-delay:400ms]">.</span>
                  </span>
                </span>
              ) : (
                ""
              )}
            </pre>
          </div>

          <div className="rounded border border-border-subtle bg-surface flex flex-col min-h-[300px]">
            <div className="px-3 py-2 border-b border-border-subtle flex items-center justify-between">
              <div className="text-[10px] font-black uppercase tracking-widest text-text-muted">
                {view === "streaming" ? (streamDag.nodes.length === 0 ? "Building DAG…" : `Building DAG · ${streamDag.nodes.length} nodes · ${streamDag.edges.length} edges`) : "Proposed DAG"}
              </div>
              {view !== "streaming" && (
                <div className="text-[11px] text-text-muted">
                  {(proposal?.nodes ?? streamDag.nodes).length} nodes · {(proposal?.edges ?? streamDag.edges).length} edges
                </div>
              )}
            </div>
            <div className="flex-1 overflow-auto">
              {/* Conductor is auto-injected by WorkflowGraphView as a virtual
                  root node, so even an empty streamDag renders a single live
                  Conductor character — the previous SkeletonDag placeholder
                  is no longer needed. */}
              <WorkflowGraphView
                graph={proposal ?? streamDag}
                className="bg-surface"
                onNodeClick={handleNodeClick}
              />
            </div>
          </div>
        </div>
      )}

      {view === "preview" && proposal && proposal.meta && (
        <div className="rounded border border-border-subtle bg-surface/40 px-3 py-2 text-xs">
          <div><b>Intent:</b> {proposal.meta.intent ?? "(unknown)"}</div>
          <div className="text-text-muted">{proposal.meta.rationale}</div>
          <div className="text-[10px] text-text-muted mt-1">
            created_by: <code className="font-mono">{proposal.meta.created_by ?? "—"}</code>
          </div>
        </div>
      )}

      {view === "saved" && graph && (
        <div className="flex flex-col flex-1 min-h-[520px] relative bg-surface overflow-hidden">
          {/* === dag-toolbar (matches design handoff) === */}
          <div
            className="flex items-center justify-between gap-2.5 px-4 py-3 border-b border-border-subtle font-mono text-[12px] text-text-muted"
            style={{
              background:
                "linear-gradient(180deg, color-mix(in srgb, var(--color-surface-raised) 40%, transparent), transparent)",
            }}
          >
            <div className="flex items-center gap-3.5 min-w-0">
              <span className="truncate">
                <b className="text-foreground font-medium">Graph</b>{" "}
                <span className="text-text-secondary">{graph.id.slice(0, 8)}</span>
              </span>
              <span className="text-text-faint">·</span>
              <span className="inline-flex items-center gap-1.5">
                <span>status</span>
                <span
                  className={cn(
                    "inline-flex items-center gap-1.5 px-1.5 py-0.5 rounded-md border text-[11px] font-mono",
                    graph.status === "done"
                      ? "border-status-done/30 text-status-done"
                      : graph.status === "running"
                        ? "border-brand/40 text-brand"
                        : graph.status === "failed"
                          ? "border-status-failed/40 text-status-failed"
                          : "border-border-muted text-text-secondary",
                  )}
                  style={
                    graph.status === "done"
                      ? { backgroundColor: "var(--color-done-bg)" }
                      : graph.status === "running"
                        ? { backgroundColor: "var(--color-brand-bg)" }
                        : undefined
                  }
                >
                  {graph.status === "running" && (
                    <span className="size-1.5 rounded-full bg-brand animate-pulse" />
                  )}
                  <span className="capitalize">{graph.status}</span>
                </span>
              </span>
              <span className="text-text-faint">·</span>
              <span>
                {graph.nodes.length} nodes · {graph.edges.length} edges
              </span>
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
              <Button
                onClick={handleAutoPlan}
                disabled={busy}
                variant="outline"
                size="sm"
                className="h-7 px-2.5 text-[12px]"
              >
                {busy ? "Planning…" : "Auto-plan"}
              </Button>
              <Button
                disabled={busy}
                onClick={handleStart}
                size="sm"
                className="h-7 px-2.5 text-[12px] bg-brand hover:bg-brand-strong text-black font-semibold"
              >
                {busy
                  ? graph.status === "draft"
                    ? "Starting…"
                    : "Running…"
                  : graph.status === "draft"
                    ? "Start"
                    : graph.status === "running"
                      ? "Re-run"
                      : graph.status === "failed"
                        ? "Retry"
                        : "Re-run"}
              </Button>
            </div>
          </div>

          <WorkflowGraphView
            graph={graph}
            onNodeClick={handleNodeClick}
            stats={graphStats}
          />
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

      <AgentDecisionDrawer
        taskId={explainTaskId}
        open={explainTaskId !== null}
        onClose={() => setExplainTaskId(null)}
      />

      <ConfirmDialog
        open={retryTarget !== null}
        onOpenChange={(o) => {
          if (!o) {
            setRetryTarget(null);
            setRetryBusy(false);
          }
        }}
        title="Retry this failed node?"
        description={
          retryTarget
            ? `Node "${retryTarget.node_key}" failed previously. Re-dispatch the task now? The run history is preserved.`
            : ""
        }
        confirmText="Retry"
        variant="warning"
        isLoading={retryBusy}
        onConfirm={() => void handleRetryConfirm()}
      />
    </div>
    </AgentStatusProvider>
  );
}

/** Pulls Conductor history from context + API log and renders ConductorLogPanel.
 * Must live INSIDE <AgentStatusProvider>. */
function ConductorPanelHost({
  issueId,
  open,
  onClose,
}: {
  issueId: string;
  open: boolean;
  onClose: () => void;
}) {
  const snap = useAgentStatusContext();
  return (
    <ConductorLogPanel
      issueId={issueId}
      open={open}
      liveHistory={snap.history.conductor}
      onClose={onClose}
    />
  );
}

