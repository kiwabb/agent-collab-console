"use client";

import { useCallback, useMemo } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  type Edge,
  MarkerType,
  type Node,
  type NodeMouseHandler,
  useReactFlow,
} from "reactflow";
import "reactflow/dist/style.css";
import { Maximize2, Minus, Plus } from "lucide-react";

import type { ProposedDAG, WorkflowGraph } from "@/lib/types";
import type { GraphStatsResponse } from "@/lib/api";
import {
  AgentDagNode,
  type AgentDagNodeData,
  type AgentDagNodeStats,
} from "./AgentDagNode";
import type { RoleId } from "@/features/agents/dock/personas";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

export interface WorkflowNodeClickPayload {
  node_key: string;
  task_id: string | null;
  status: string | null;
  /** Modifier keys at click time. alt-click opens the explain drawer;
   * regular click routes to Tasks·Runs. */
  altKey?: boolean;
  shiftKey?: boolean;
  metaKey?: boolean;
}

// Design-handoff edge palette: green for normal flow, amber for refine
// loops, red for retries, brand orange for the Conductor-out edges (set
// per-edge in toReactFlow when source === CONDUCTOR_KEY).
const EDGE_COLOR: Record<string, string> = {
  sequence: "#4ade80",
  "parallel-fanout": "#34d977",
  "refine-loop": "#f59e0b",
  "retry-on-fail": "#ef4444",
  conditional: "#60a5fa",
};
const EDGE_START_COLOR = "#a8d56b"; // Conductor → root: brand-tinted green

const CONDUCTOR_KEY = "__conductor__";
const VALID_ROLES = new Set<RoleId>([
  "product_manager",
  "architect",
  "engineer",
  "engineer_frontend",
  "engineer_backend",
  "qa",
]);

interface GraphLike {
  nodes: Array<{
    node_key: string;
    title?: string | null;
    role_key?: string;
    status?: string;
    task_id?: string | null;
  }>;
  edges: Array<{
    from_node_key: string;
    to_node_key: string;
    edge_type: string;
  }>;
}

const nodeTypes = { agent: AgentDagNode };

function toReactFlow(
  graph: GraphLike,
  onNodeClick?: (payload: WorkflowNodeClickPayload) => void,
  stats?: GraphStatsResponse | null,
) {
  const colWidth = 280;
  const rowHeight = 120;

  // ---- Inject virtual Conductor root ----
  // Conductor sits at depth 0. We add directed edges from Conductor to
  // every "original root" — any node whose only incoming edges (ignoring
  // refine-loops) would otherwise have left it without a predecessor.
  const incoming = new Map<string, Set<string>>();
  graph.nodes.forEach((n) => incoming.set(n.node_key, new Set()));
  graph.edges.forEach((e) => {
    if (e.edge_type === "refine-loop") return;
    incoming.get(e.to_node_key)?.add(e.from_node_key);
  });
  const originalRoots = graph.nodes
    .filter((n) => (incoming.get(n.node_key)?.size ?? 0) === 0)
    .map((n) => n.node_key);

  const nodesWithConductor: GraphLike["nodes"] = [
    {
      node_key: CONDUCTOR_KEY,
      title: "Conductor",
      role_key: "conductor",
    },
    ...graph.nodes,
  ];
  const edgesWithConductor: GraphLike["edges"] = [
    ...originalRoots.map((to) => ({
      from_node_key: CONDUCTOR_KEY,
      to_node_key: to,
      edge_type: "sequence",
    })),
    ...graph.edges,
  ];

  // ---- Topological layout (Kahn) ----
  const depthByKey = new Map<string, number>();
  const incoming2 = new Map<string, Set<string>>();
  nodesWithConductor.forEach((n) => incoming2.set(n.node_key, new Set()));
  edgesWithConductor.forEach((e) => {
    if (e.edge_type === "refine-loop") return;
    incoming2.get(e.to_node_key)?.add(e.from_node_key);
  });
  const pending = nodesWithConductor
    .filter((n) => !incoming2.get(n.node_key)?.size)
    .map((n) => n.node_key);
  for (const k of pending) depthByKey.set(k, 0);
  let i = 0;
  while (i < pending.length) {
    const k = pending[i++];
    const d = depthByKey.get(k) ?? 0;
    edgesWithConductor.forEach((e) => {
      if (e.edge_type === "refine-loop") return;
      if (e.from_node_key !== k) return;
      const deps = incoming2.get(e.to_node_key);
      deps?.delete(k);
      if (deps && deps.size === 0 && !depthByKey.has(e.to_node_key)) {
        depthByKey.set(e.to_node_key, d + 1);
        pending.push(e.to_node_key);
      }
    });
  }

  const rowSeenInDepth = new Map<number, number>();
  const rfNodes: Node<AgentDagNodeData>[] = nodesWithConductor.map((n) => {
    const depth = depthByKey.get(n.node_key) ?? 0;
    const seen = rowSeenInDepth.get(depth) ?? 0;
    rowSeenInDepth.set(depth, seen + 1);
    const isConductor = n.node_key === CONDUCTOR_KEY;
    const roleCandidate = (n.role_key ?? n.node_key) as RoleId;
    const role: RoleId = isConductor
      ? "conductor"
      : VALID_ROLES.has(roleCandidate)
        ? roleCandidate
        : "engineer"; // graceful fallback for unknown roles
    const stat: AgentDagNodeStats | null = isConductor
      ? stats?.conductor ?? null
      : stats?.nodes?.[n.node_key] ?? null;
    return {
      id: n.node_key,
      type: "agent",
      position: { x: depth * colWidth, y: seen * rowHeight + 60 },
      data: {
        role,
        label: n.title || n.role_key || n.node_key,
        status: n.status ?? "pending",
        task_id: n.task_id ?? null,
        isConductor,
        node_key: n.node_key,
        stats: stat,
        onClick: onNodeClick,
      },
    };
  });

  const rfEdges: Edge[] = edgesWithConductor.map((e, idx) => {
    const isStart = e.from_node_key === CONDUCTOR_KEY;
    const color = isStart
      ? EDGE_START_COLOR
      : EDGE_COLOR[e.edge_type] || "#4ade80";
    return {
      id: `e${idx}`,
      source: e.from_node_key,
      target: e.to_node_key,
      // straight = literal line between handles. Matches the design
      // handoff's horizontal SVG rail with arrowheads.
      type: "straight",
      label: e.edge_type === "sequence" ? undefined : e.edge_type,
      animated:
        e.edge_type === "refine-loop" || e.edge_type === "retry-on-fail",
      style: {
        stroke: color,
        strokeWidth: 3.4,
        filter: `drop-shadow(0 0 6px ${color}66)`,
      },
      markerEnd: { type: MarkerType.ArrowClosed, color },
    };
  });
  return { nodes: rfNodes, edges: rfEdges };
}

interface Props {
  graph: WorkflowGraph | ProposedDAG;
  className?: string;
  onNodeClick?: (payload: WorkflowNodeClickPayload) => void;
  /** Optional per-node telemetry from /graph-stats. */
  stats?: GraphStatsResponse | null;
}

export function WorkflowGraphView({
  graph,
  className,
  onNodeClick,
  stats,
}: Props) {
  const { t } = useI18n();
  const flow = useMemo(() => {
    if ("dag_json" in graph) {
      return toReactFlow(
        {
          nodes: graph.nodes.map((n) => ({
            node_key: n.node_key,
            title: n.title,
            // WorkflowGraph nodes don't carry role_key explicitly, but
            // node_key matches role_key for the seeded 4-phase preset.
            role_key: n.node_key,
            status: n.status,
            task_id: n.task_id,
          })),
          edges: graph.edges.map((e) => ({
            from_node_key: e.from_node_key,
            to_node_key: e.to_node_key,
            edge_type: e.edge_type,
          })),
        },
        onNodeClick,
        stats,
      );
    }
    return toReactFlow(
      {
        nodes: graph.nodes.map((n) => ({
          node_key: n.node_key,
          title: n.title,
          role_key: n.role_key,
        })),
        edges: graph.edges.map((e) => ({
          from_node_key: e.from_node_key,
          to_node_key: e.to_node_key,
          edge_type: e.edge_type,
        })),
      },
      onNodeClick,
      stats,
    );
  }, [graph, onNodeClick, stats]);

  const handleNodeClick = useCallback<NodeMouseHandler>(
    (event, node) => {
      if (!onNodeClick) return;
      const data = node.data as AgentDagNodeData;
      onNodeClick({
        node_key: data.node_key ?? node.id,
        task_id: data.task_id ?? null,
        status: data.status ?? null,
        altKey: event.altKey,
        shiftKey: event.shiftKey,
        metaKey: event.metaKey,
      });
    },
    [onNodeClick],
  );

  return (
    <div
      className={cn(
        "relative w-full flex-1 min-h-[460px] overflow-hidden",
        className,
      )}
      style={{
        background: `
          radial-gradient(800px 400px at 50% 60%, var(--color-brand-bg), transparent 60%),
          radial-gradient(circle at center, color-mix(in srgb, var(--color-background) 92%, white 4%) 0%, var(--color-background) 100%)
        `,
      }}
    >
      {/* Soft 22px dot grid layered over a 88px square grid — same look
          as the design handoff. */}
      <div
        aria-hidden
        className="absolute inset-0 pointer-events-none opacity-70"
        style={{
          backgroundImage: `
            linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px),
            radial-gradient(rgba(255,255,255,0.055) 1px, transparent 1px)
          `,
          backgroundSize: "88px 88px, 88px 88px, 22px 22px",
        }}
      />

      {/* Top-left legend chip */}
      <div className="absolute left-3.5 top-3.5 z-[2] flex items-center gap-3 px-2.5 py-1.5 rounded-lg bg-background/80 backdrop-blur-sm border border-border-subtle font-mono text-[11px] text-text-muted">
        <span className="inline-flex items-center gap-1.5">
          <span
            className="size-2 rounded-full"
            style={{ background: "var(--color-brand)" }}
          />
          {t("issue.dag.legendStart")}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span
            className="size-2 rounded-full"
            style={{ background: "var(--color-status-done)" }}
          />
          {t("issue.dag.legendDone")}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span
            className="size-2 rounded-full"
            style={{ background: "var(--color-text-muted)" }}
          />
          {t("issue.dag.legendQueued")}
        </span>
        <span className="text-text-faint">·</span>
        <span className="text-text-faint">{t("issue.dag.legendHint")}</span>
      </div>

      <div className="absolute inset-0">
        <ReactFlow
          nodes={flow.nodes}
          edges={flow.edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.18 }}
          proOptions={{ hideAttribution: true }}
          nodesDraggable
          nodesConnectable={false}
          elementsSelectable
          onNodeClick={onNodeClick ? handleNodeClick : undefined}
        >
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={0}
          color="transparent"
        />
        <DagFab />
      </ReactFlow>
      </div>
    </div>
  );
}

/** Custom zoom +/-/fit FAB matching the design handoff's dag-fab. */
function DagFab() {
  const { zoomIn, zoomOut, fitView } = useReactFlow();
  const { t } = useI18n();
  return (
    <div className="absolute right-3.5 bottom-3.5 flex flex-col gap-1.5 z-[2]">
      <FabButton
        title={t("issue.dag.zoomIn")}
        onClick={() => zoomIn({ duration: 200 })}
      >
        <Plus size={12} strokeWidth={2.4} />
      </FabButton>
      <FabButton
        title={t("issue.dag.zoomOut")}
        onClick={() => zoomOut({ duration: 200 })}
      >
        <Minus size={12} strokeWidth={2.4} />
      </FabButton>
      <FabButton
        title={t("issue.dag.fit")}
        onClick={() => fitView({ duration: 200, padding: 0.18 })}
      >
        <Maximize2 size={11} strokeWidth={2} />
      </FabButton>
    </div>
  );
}

function FabButton({
  children,
  onClick,
  title,
}: {
  children: React.ReactNode;
  onClick: () => void;
  title: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className="size-7 rounded-md bg-surface-raised border border-border-muted text-text-muted hover:text-foreground hover:border-border-strong flex items-center justify-center transition-colors"
    >
      {children}
    </button>
  );
}
