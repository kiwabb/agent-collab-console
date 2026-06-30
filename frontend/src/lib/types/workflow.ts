// AUTO-SPLIT from lib/types.ts by domain (frontend lib split).

export type WorkflowNodeStatus =
  "pending" | "blocked" | "ready" | "running" | "done" | "failed" | "skipped" | "needs_rework";

export type WorkflowEdgeType =
  "sequence" | "parallel-fanout" | "refine-loop" | "retry-on-fail" | "conditional";

export interface WorkflowNode {
  id: string;
  graph_id: string;
  node_key: string;
  agent_id: string;
  title: string | null;
  prompt_override: string | null;
  status: WorkflowNodeStatus;
  task_id: string | null;
  artifact_dir: string | null;
  retries: number;
  max_retries: number;
  /** Shared key for nodes dispatched together via dispatch_batch (parallel
   * swarm fan-out); null for serial dispatches. */
  batch_key: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface WorkflowEdge {
  id: string;
  graph_id: string;
  from_node_key: string;
  to_node_key: string;
  edge_type: WorkflowEdgeType;
  condition_expr: string | null;
  created_at: string | null;
}

export interface WorkflowGraph {
  id: string;
  issue_id: string;
  preset_id: string | null;
  status: string;
  dag_json: string;
  created_by: string | null;
  locked_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

export interface SubAgentResultPayload {
  task_id: string;
  role: string;
  title: string;
  status: string;
  task_kind: string;
  parent_task_id: string | null;
  summary: string;
  artifact_json: Record<string, unknown> | null;
  updated_at: string | null;
}
