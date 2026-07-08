// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import {
  API_BASE,
  apiJsonRequest,
  apiRequest,
  apiRequestOr,
  dedupedFetch,
  handleResponse,
} from "./fetch";
import type { ProposedDAG, WorkflowGraph } from "../types";

export async function getIssueGraph(issueId: string): Promise<WorkflowGraph | null> {
  const response = await dedupedFetch(`${API_BASE}/codex/issues/${issueId}/graph`);
  if (response.status === 404) return null;
  return handleResponse<WorkflowGraph>(response);
}
export async function autoStartIssueGraph(issueId: string): Promise<WorkflowGraph> {
  return apiRequest<WorkflowGraph>(`${API_BASE}/codex/issues/${issueId}/graph/start`, {
    method: "POST",
  });
}
export async function restartConductor(issueId: string): Promise<WorkflowGraph> {
  return apiRequest<WorkflowGraph>(`${API_BASE}/codex/issues/${issueId}/conductor/restart`, {
    method: "POST",
  });
}
export async function resetIssue(issueId: string): Promise<WorkflowGraph> {
  return apiRequest<WorkflowGraph>(`${API_BASE}/codex/issues/${issueId}/reset`, {
    method: "POST",
  });
}

export async function planIssue(issueId: string): Promise<ProposedDAG> {
  return apiRequest<ProposedDAG>(`${API_BASE}/codex/issues/${issueId}/plan`, {
    method: "POST",
  });
}

export async function saveIssueGraph(
  issueId: string,
  dag: ProposedDAG,
  createdBy = "user",
): Promise<WorkflowGraph> {
  return apiJsonRequest<WorkflowGraph>(`${API_BASE}/codex/issues/${issueId}/graph`, "POST", {
    dag,
    created_by: createdBy,
  });
}

export async function startIssueGraph(issueId: string): Promise<WorkflowGraph> {
  return autoStartIssueGraph(issueId);
}

export interface ReplanPending {
  id: string;
  graph_id: string;
  triggered_by_node_key: string;
  trigger_reason: string;
  diff: {
    added_nodes?: Array<{ node_key: string; role_key?: string; title?: string }>;
    added_edges?: Array<{ from_node_key: string; to_node_key: string; edge_type: string }>;
    removed_node_keys?: string[];
    rationale?: string;
  };
  rationale: string | null;
  status: string;
  created_at: string | null;
}

export async function listReplanPending(issueId: string): Promise<ReplanPending[]> {
  return apiRequest<ReplanPending[]>(`${API_BASE}/codex/issues/${issueId}/graph/replan-pending`);
}

export async function confirmReplan(issueId: string, replanId: string): Promise<WorkflowGraph> {
  return apiRequest<WorkflowGraph>(
    `${API_BASE}/codex/issues/${issueId}/graph/replan/${replanId}/confirm`,
    { method: "POST" },
  );
}

export async function rejectReplan(issueId: string, replanId: string): Promise<WorkflowGraph> {
  return apiRequest<WorkflowGraph>(
    `${API_BASE}/codex/issues/${issueId}/graph/replan/${replanId}/reject`,
    { method: "POST" },
  );
}
export interface AgentMessage {
  id: string;
  issue_id: string;
  graph_id: string;
  from_node_key: string;
  to_node_key: string;
  message_type:
    "handoff" | "critique" | "clarification" | "answer" | "specialist_call" | "specialist_result";
  body: string;
  created_at: string | null;
}
export async function getAgentMessages(issueId: string): Promise<AgentMessage[]> {
  const data = await apiRequestOr<{ messages?: AgentMessage[] }>(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/agent-messages`,
    { messages: [] },
  );
  return data.messages ?? [];
}
export interface ConductorDecision {
  id: string;
  issue_id: string;
  task_id: string;
  action: "proceed" | "note" | "escalate" | "reroute" | "insert_node" | "request_clarification";
  reason: string | null;
  diff_json: string | null;
  applied_at: string | null;
  created_at: string | null;
}
export async function getConductorLog(issueId: string): Promise<ConductorDecision[]> {
  const data = await apiRequestOr<{ decisions?: ConductorDecision[] }>(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor-log`,
    { decisions: [] },
  );
  return data.decisions ?? [];
}
export interface ConductorTurn {
  id: string;
  conductor_task_id: string;
  issue_id: string;
  turn_index: number;
  sub_index: number;
  kind:
    | "llm_request"
    | "llm_response"
    | "tool_use"
    | "tool_result"
    | "user_message"
    | "error"
    | "finalize";
  payload: Record<string, unknown>;
  created_at: string | null;
  consumed_at?: string | null;
}
export async function getConductorTurns(
  issueId: string,
  opts?: { conductorTaskId?: string; limit?: number },
): Promise<ConductorTurn[]> {
  const sp = new URLSearchParams();
  if (opts?.conductorTaskId) sp.set("conductor_task_id", opts.conductorTaskId);
  if (opts?.limit) sp.set("limit", String(opts.limit));
  const suffix = sp.size > 0 ? `?${sp.toString()}` : "";
  const data = await apiRequestOr<{ turns?: ConductorTurn[] }>(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor-turns${suffix}`,
    { turns: [] },
  );
  return data.turns ?? [];
}
export interface ConductorStatePayload {
  issue_id: string;
  conductor_task_id?: string | null;
  conductor_status?: string | null;
  phase?: string | null;
  detail?: string | null;
  running_thread: Array<{
    task_id: string;
    completed_node_key: string;
    action: string;
    reason?: string | null;
    note?: string | null;
    created_at: string;
  }>;
  pending_dispatches: Array<{
    action: string;
    target_node_key?: string | null;
    prompt_override?: string | null;
    context_inject?: string | null;
    context_message?: string | null;
    reason?: string | null;
  }>;
  scratchpad: string;
  decision_count: number;
  updated_at?: string | null;
}
export interface ConductorStateLogEntry {
  id: string;
  issue_id: string;
  from_phase: string | null;
  to_phase: string;
  from_detail: string | null;
  to_detail: string | null;
  transition_at: string | null;
  duration_ms: number | null;
  is_legal: boolean;
}
export interface ConductorPhaseEstimate {
  p50_ms: number | null;
  p95_ms: number | null;
  n_samples: number;
}
export async function getConductorState(issueId: string): Promise<ConductorStatePayload | null> {
  return apiRequestOr<ConductorStatePayload | null>(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor-state`,
    null,
  );
}
export async function getConductorStateLog(
  issueId: string,
  opts?: { limit?: number },
): Promise<ConductorStateLogEntry[]> {
  const sp = new URLSearchParams();
  if (opts?.limit) sp.set("limit", String(opts.limit));
  const suffix = sp.size > 0 ? `?${sp.toString()}` : "";
  const data = await apiRequestOr<{ entries?: ConductorStateLogEntry[] }>(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor-state-log${suffix}`,
    { entries: [] },
  );
  return data.entries ?? [];
}
export async function getConductorPhaseEstimates(
  issueId: string,
): Promise<Record<string, ConductorPhaseEstimate>> {
  const data = await apiRequestOr<{ estimates?: Record<string, ConductorPhaseEstimate> }>(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor-phase-estimates`,
    { estimates: {} },
  );
  return data.estimates ?? {};
}
export async function sendConductorMessage(
  issueId: string,
  message: string,
): Promise<{ ok: boolean; status: string; conductor_task_id: string }> {
  return apiJsonRequest<{ ok: boolean; status: string; conductor_task_id: string }>(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor/message`,
    "POST",
    { message },
  );
}
export async function pauseConductor(
  issueId: string,
): Promise<{ ok: boolean; status: string; conductor_task_id: string }> {
  return apiRequest<{ ok: boolean; status: string; conductor_task_id: string }>(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor/pause`,
    {
      method: "POST",
    },
  );
}
export async function resumeConductor(
  issueId: string,
): Promise<{ ok: boolean; status: string; conductor_task_id: string }> {
  return apiRequest<{ ok: boolean; status: string; conductor_task_id: string }>(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor/resume`,
    {
      method: "POST",
    },
  );
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
export async function getSubAgentResults(issueId: string): Promise<SubAgentResultPayload[]> {
  return apiRequest<SubAgentResultPayload[]>(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/subagent-results`,
  );
}
export async function getAgentMesh(issueId: string): Promise<AgentMessage[]> {
  return apiRequest<AgentMessage[]>(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/agent-mesh`,
  );
}
export async function appendConductorMessage(
  projectId: string,
  message: string,
): Promise<{ status: string }> {
  return apiJsonRequest<{ status: string }>(
    `${API_BASE}/codex/projects/${encodeURIComponent(projectId)}/conductor/message`,
    "POST",
    { message },
  );
}
