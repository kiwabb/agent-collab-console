"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { autoStartIssueGraph, getIssueGraph } from "@/lib/api/conductors";
import { getIssueGraphStats, type GraphStatsResponse } from "@/lib/api/issues";
import { runCodexTask } from "@/lib/api/tasks";
import type { WorkflowGraph } from "@/lib/types";
import {
  WorkflowGraphView,
  type WorkflowNodeClickPayload,
} from "@/features/workflow/WorkflowGraphView";
import { ConductorLogPanel } from "@/features/workflow/ConductorLogPanel";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import { agentBus } from "@/features/agents/dock/agentBus";
import {
  AgentStatusProvider,
  useAgentStatusContext,
} from "@/features/agents/dock/AgentStatusProvider";
import { AgentDecisionDrawer } from "@/features/issues/components/AgentDecisionDrawer";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";
import { useI18n } from "@/providers/I18nProvider";

interface Props {
  issueId: string;
}

type View = "loading" | "no-graph" | "saved";

export function DagTab({ issueId }: Props) {
  const router = useRouter();
  const { t } = useI18n();
  const { addToast } = useToast();
  const [view, setView] = useState<View>("loading");
  const [graph, setGraph] = useState<WorkflowGraph | null>(null);
  const [graphStats, setGraphStats] = useState<GraphStatsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Conductor click opens its own timeline drawer (the role-node click
  // path routes to /tasks?taskId=…; Conductor has no task).
  const [conductorPanelOpen, setConductorPanelOpen] = useState(false);
  // Failed-node retry confirmation. Holds the payload while the dialog is
  // open so we can dispatch on confirm.
  const [retryTarget, setRetryTarget] = useState<WorkflowNodeClickPayload | null>(null);
  const [retryBusy, setRetryBusy] = useState(false);
  // C2: explain decision drawer. Holds the task_id of the node whose
  // reasoning the user wants to inspect.
  const [explainTaskId, setExplainTaskId] = useState<string | null>(null);

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
    // Refresh per-node telemetry alongside the graph. Errors are silent —
    // the DAG still renders without stats.
    try {
      const s = await getIssueGraphStats(issueId);
      setGraphStats(s);
    } catch {
      setGraphStats(null);
    }
  }, [issueId]);

  useEffect(() => {
    void loadGraph();
  }, [loadGraph]);

  useEffect(() => {
    const onOpenConductorLog = (event: Event) => {
      const detail = (event as CustomEvent<{ issueId?: string }>).detail;
      if (detail?.issueId !== issueId) return;
      setConductorPanelOpen(true);
    };
    window.addEventListener("open-conductor-log", onOpenConductorLog);
    return () => window.removeEventListener("open-conductor-log", onOpenConductorLog);
  }, [issueId]);

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
      router.push(`/issues/${issueId}?tab=timeline&taskId=${payload.task_id}`);
    },
    [router, issueId, addToast],
  );

  const handleRetryConfirm = useCallback(async () => {
    if (!retryTarget?.task_id) return;
    setRetryBusy(true);
    try {
      await runCodexTask(retryTarget.task_id);
      addToast({ type: "success", title: t("issue.retryDispatched") });
      const fresh = await getIssueGraph(issueId).catch(() => null);
      if (fresh) setGraph(fresh);
      setRetryTarget(null);
    } catch (err) {
      addToast({
        type: "error",
        title: t("issue.retryFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setRetryBusy(false);
    }
  }, [retryTarget, addToast, issueId, t]);

  async function handleStart() {
    setBusy(true);
    setError(null);
    agentBus.onConductorConnecting(issueId);
    try {
      const started = await autoStartIssueGraph(issueId);
      setGraph(started);
      setView("saved");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      agentBus.onConductorError(issueId, e instanceof Error ? e.message : String(e));
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
        {error && (
          <div className="rounded border border-error/40 bg-error/10 px-3 py-2 text-sm text-error">
            {error}
          </div>
        )}

        {view === "loading" && (
          <div
            data-density="dag-tab-graph-dispatch-loading"
            className="motion-essential relative flex min-h-[220px] items-center justify-center gap-2 overflow-hidden rounded-lg border border-brand/25 bg-brand-muted/10 text-sm font-semibold text-text-muted"
          >
            <span
              aria-hidden
              className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-brand/70 to-transparent"
            />
            <AgentThinkingIndicator phase="dispatching" size={16} />
            {t("issue.workflow.loading")}
          </div>
        )}

        {view === "no-graph" && (
          <div className="flex flex-col gap-4 items-center justify-center py-12">
            <div className="rounded border border-dashed border-border-subtle p-6 text-center text-sm text-text-muted">
              No workflow graph yet. Click <b>Start Conductor</b> to begin Conductor-driven
              orchestration.
            </div>
            <Button
              onClick={() => void handleStart()}
              disabled={busy}
              data-density={
                busy ? "dag-tab-start-conductor-dispatch-cta" : "dag-tab-start-conductor-cta"
              }
              className={cn(
                "bg-brand text-black hover:bg-brand-strong font-semibold shadow-sm",
                busy && "motion-essential",
              )}
            >
              {busy ? (
                <>
                  <AgentThinkingIndicator phase="dispatching" size={12} />
                  Starting…
                </>
              ) : (
                "Start Conductor"
              )}
            </Button>
          </div>
        )}

        {view === "saved" && graph && (
          <div className="flex flex-col flex-1 min-h-[520px] relative bg-surface overflow-hidden">
            {/* === dag-toolbar === */}
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
                    data-density={
                      graph.status === "running" ? "dag-tab-running-status" : "dag-tab-status"
                    }
                    className={cn(
                      "inline-flex items-center gap-1.5 px-1.5 py-0.5 rounded-md border text-[11px] font-mono",
                      graph.status === "done"
                        ? "border-status-done/30 text-status-done"
                        : graph.status === "running"
                          ? "border-brand/40 text-brand"
                          : graph.status === "failed"
                            ? "border-status-failed/40 text-status-failed"
                            : "border-border-muted text-text-secondary",
                      graph.status === "running" && "motion-essential",
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
                      <AgentThinkingIndicator phase="dispatching" size={10} />
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
                  disabled={busy}
                  onClick={() => void handleStart()}
                  size="sm"
                  data-density={
                    busy ? "dag-tab-toolbar-start-dispatch-cta" : "dag-tab-toolbar-start-cta"
                  }
                  className={cn(
                    "h-7 px-2.5 text-[12px] bg-brand hover:bg-brand-strong text-black font-semibold",
                    busy && "motion-essential",
                  )}
                >
                  {busy ? (
                    <>
                      <AgentThinkingIndicator phase="dispatching" size={11} />
                      Starting…
                    </>
                  ) : graph.status === "running" ? (
                    "Re-run"
                  ) : graph.status === "failed" ? (
                    "Retry"
                  ) : (
                    "Re-run"
                  )}
                </Button>
              </div>
            </div>

            <WorkflowGraphView graph={graph} onNodeClick={handleNodeClick} stats={graphStats} />
          </div>
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
          title={t("issue.retryNodeTitle")}
          description={retryTarget ? t("issue.retryNodeBody", { node: retryTarget.node_key }) : ""}
          confirmText={t("issue.retry")}
          variant="warning"
          isLoading={retryBusy}
          loadingMotionPhase="dispatching"
          loadingDensity="dag-tab-retry-node-dispatch-confirm"
          loadingIndicatorSize={12}
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
