"use client";

import { useMemo } from "react";
import ReactFlow, {
  Background,
  Controls,
  type Edge,
  MarkerType,
  type Node,
} from "reactflow";
import "reactflow/dist/style.css";

import type { ProposedDAG, WorkflowGraph } from "@/lib/types";

const STATUS_COLOR: Record<string, string> = {
  pending: "#6b7280",
  blocked: "#9ca3af",
  ready: "#7a9dcc",
  running: "#3b82f6",
  done: "#22c55e",
  failed: "#ef4444",
  skipped: "#a3a3a3",
  needs_rework: "#f97316",
};

const EDGE_COLOR: Record<string, string> = {
  sequence: "#7a9dcc",
  "parallel-fanout": "#22c55e",
  "refine-loop": "#f97316",
  "retry-on-fail": "#ef4444",
  conditional: "#a855f7",
};

interface GraphLike {
  nodes: Array<{
    node_key: string;
    title?: string | null;
    role_key?: string;
    status?: string;
  }>;
  edges: Array<{
    from_node_key: string;
    to_node_key: string;
    edge_type: string;
  }>;
}

function toReactFlow(graph: GraphLike) {
  const colWidth = 220;
  const rowHeight = 110;
  // Topological layered layout: simple Kahn's algorithm by depth.
  const depthByKey = new Map<string, number>();
  const incoming = new Map<string, Set<string>>();
  graph.nodes.forEach((n) => incoming.set(n.node_key, new Set()));
  graph.edges.forEach((e) => {
    if (e.edge_type === "refine-loop") return;
    incoming.get(e.to_node_key)?.add(e.from_node_key);
  });
  const pending = graph.nodes
    .filter((n) => !incoming.get(n.node_key)?.size)
    .map((n) => n.node_key);
  for (const k of pending) depthByKey.set(k, 0);
  let i = 0;
  while (i < pending.length) {
    const k = pending[i++];
    const d = depthByKey.get(k) ?? 0;
    graph.edges.forEach((e) => {
      if (e.edge_type === "refine-loop") return;
      if (e.from_node_key !== k) return;
      const deps = incoming.get(e.to_node_key);
      deps?.delete(k);
      if (deps && deps.size === 0 && !depthByKey.has(e.to_node_key)) {
        depthByKey.set(e.to_node_key, d + 1);
        pending.push(e.to_node_key);
      }
    });
  }
  const rowSeenInDepth = new Map<number, number>();
  const rfNodes: Node[] = graph.nodes.map((n) => {
    const depth = depthByKey.get(n.node_key) ?? 0;
    const seen = rowSeenInDepth.get(depth) ?? 0;
    rowSeenInDepth.set(depth, seen + 1);
    return {
      id: n.node_key,
      position: { x: depth * colWidth, y: seen * rowHeight },
      data: { label: n.title || n.role_key || n.node_key, status: n.status ?? "pending" },
      style: {
        border: `2px solid ${STATUS_COLOR[n.status ?? "pending"]}`,
        background: "var(--card)",
        color: "var(--card-foreground)",
        borderRadius: 8,
        padding: 8,
        fontSize: 12,
        width: 180,
      },
    };
  });
  const rfEdges: Edge[] = graph.edges.map((e, idx) => ({
    id: `e${idx}`,
    source: e.from_node_key,
    target: e.to_node_key,
    label: e.edge_type === "sequence" ? undefined : e.edge_type,
    animated: e.edge_type === "refine-loop" || e.edge_type === "retry-on-fail",
    style: { stroke: EDGE_COLOR[e.edge_type] || "#7a9dcc" },
    markerEnd: { type: MarkerType.ArrowClosed, color: EDGE_COLOR[e.edge_type] || "#7a9dcc" },
  }));
  return { nodes: rfNodes, edges: rfEdges };
}

interface Props {
  graph: WorkflowGraph | ProposedDAG;
  className?: string;
}

export function WorkflowGraphView({ graph, className }: Props) {
  const flow = useMemo(() => {
    if ("dag_json" in graph) {
      // WorkflowGraph (persisted) — nodes have role_key inside `data` only if we add it.
      // Re-shape to GraphLike, pulling status from materialized nodes.
      return toReactFlow({
        nodes: graph.nodes.map((n) => ({
          node_key: n.node_key,
          title: n.title,
          status: n.status,
        })),
        edges: graph.edges.map((e) => ({
          from_node_key: e.from_node_key,
          to_node_key: e.to_node_key,
          edge_type: e.edge_type,
        })),
      });
    }
    return toReactFlow({
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
    });
  }, [graph]);

  return (
    <div className={className} style={{ height: 360 }}>
      <ReactFlow
        nodes={flow.nodes}
        edges={flow.edges}
        fitView
        proOptions={{ hideAttribution: true }}
        nodesDraggable
        nodesConnectable={false}
        elementsSelectable
      >
        <Background gap={16} size={1} color="rgba(255,255,255,0.06)" />
        <Controls position="bottom-right" showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
