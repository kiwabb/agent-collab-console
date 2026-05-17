"use client";

import { useCallback, useMemo } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  type Edge,
  MarkerType,
  type Node,
  type NodeMouseHandler,
} from "reactflow";
import "reactflow/dist/style.css";

import type { ProposedDAG, WorkflowGraph } from "@/lib/types";
import { AgentDagNode, type AgentDagNodeData } from "./AgentDagNode";
import type { RoleId } from "@/features/agents/dock/personas";
import { cn } from "@/lib/utils";

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

const EDGE_COLOR: Record<string, string> = {
  sequence: "#8b5cf6", // Violet
  "parallel-fanout": "#10b981", // Emerald
  "refine-loop": "#f59e0b", // Amber
  "retry-on-fail": "#ef4444", // Red
  conditional: "#6366f1", // Indigo
};

const CONDUCTOR_KEY = "__conductor__";
const VALID_ROLES = new Set<RoleId>([
  "product_manager",
  "architect",
  "engineer",
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
        onClick: onNodeClick,
      },
    };
  });

  const rfEdges: Edge[] = edgesWithConductor.map((e, idx) => {
    const color = EDGE_COLOR[e.edge_type] || "#7a9dcc";
    return {
      id: `e${idx}`,
      source: e.from_node_key,
      target: e.to_node_key,
      type: "smoothstep",
      label: e.edge_type === "sequence" ? undefined : e.edge_type,
      animated: e.edge_type === "refine-loop" || e.edge_type === "retry-on-fail",
      style: { 
        stroke: color, 
        strokeWidth: 2.5,
        filter: `drop-shadow(0 0 4px ${color}80)` 
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
}

export function WorkflowGraphView({ graph, className, onNodeClick }: Props) {
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
    );
  }, [graph, onNodeClick]);

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
    <div className={cn("relative w-full flex-1 min-h-[420px] rounded-xl overflow-hidden shadow-inner border border-border-subtle bg-background/50", className)}>
      {/* Radial gradient background accent */}
      <div className="absolute inset-0 pointer-events-none bg-[radial-gradient(ellipse_at_center,rgba(139,92,246,0.08)_0%,transparent_60%)]" />
      <ReactFlow
        nodes={flow.nodes}
        edges={flow.edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.25 }}
        proOptions={{ hideAttribution: true }}
        nodesDraggable
        nodesConnectable={false}
        elementsSelectable
        onNodeClick={onNodeClick ? handleNodeClick : undefined}
      >
        <Background 
          variant={BackgroundVariant.Dots} 
          gap={20} 
          size={1.5} 
          color="rgba(128,128,128,0.2)" 
        />
        <Controls position="bottom-right" showInteractive={false} className="opacity-50 hover:opacity-100 transition-opacity" />
      </ReactFlow>
    </div>
  );
}
