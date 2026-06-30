// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, dedupedFetch, handleResponse } from "./fetch";
import type { WorkflowGraph } from "../types";

export async function getIssueGraph(issueId: string): Promise<WorkflowGraph | null> {
  const response = await dedupedFetch(`${API_BASE}/codex/issues/${issueId}/graph`);
  if (response.status === 404) return null;
  return handleResponse<WorkflowGraph>(response);
}
export async function autoStartIssueGraph(issueId: string): Promise<WorkflowGraph> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/graph/auto-start`, {
    method: "POST",
  });
  return handleResponse<WorkflowGraph>(response);
}
export async function restartConductor(issueId: string): Promise<WorkflowGraph> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/conductor/restart`, {
    method: "POST",
  });
  return handleResponse<WorkflowGraph>(response);
}
export async function resetIssue(issueId: string): Promise<WorkflowGraph> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/reset`, { method: "POST" });
  return handleResponse<WorkflowGraph>(response);
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
  const res = await fetch(`${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/agent-messages`);
  if (!res.ok) return [];
  const data = (await res.json()) as { messages: AgentMessage[] };
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
  const res = await fetch(`${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor-log`);
  if (!res.ok) return [];
  const data = (await res.json()) as { decisions: ConductorDecision[] };
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
  const res = await fetch(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor-turns${suffix}`,
  );
  if (!res.ok) return [];
  const data = (await res.json()) as { turns: ConductorTurn[] };
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
  const res = await fetch(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor-state`,
  );
  if (!res.ok) return null;
  return (await res.json()) as ConductorStatePayload;
}
export async function getConductorStateLog(
  issueId: string,
  opts?: { limit?: number },
): Promise<ConductorStateLogEntry[]> {
  const sp = new URLSearchParams();
  if (opts?.limit) sp.set("limit", String(opts.limit));
  const suffix = sp.size > 0 ? `?${sp.toString()}` : "";
  const res = await fetch(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor-state-log${suffix}`,
  );
  if (!res.ok) return [];
  const data = (await res.json()) as { entries: ConductorStateLogEntry[] };
  return data.entries ?? [];
}
export async function getConductorPhaseEstimates(
  issueId: string,
): Promise<Record<string, ConductorPhaseEstimate>> {
  const res = await fetch(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor-phase-estimates`,
  );
  if (!res.ok) return {};
  const data = (await res.json()) as { estimates: Record<string, ConductorPhaseEstimate> };
  return data.estimates ?? {};
}
export async function sendConductorMessage(
  issueId: string,
  message: string,
): Promise<{ ok: boolean; status: string; conductor_task_id: string }> {
  const response = await fetch(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor/message`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    },
  );
  return handleResponse(response);
}
export async function pauseConductor(
  issueId: string,
): Promise<{ ok: boolean; status: string; conductor_task_id: string }> {
  const response = await fetch(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor/pause`,
    {
      method: "POST",
    },
  );
  return handleResponse(response);
}
export async function resumeConductor(
  issueId: string,
): Promise<{ ok: boolean; status: string; conductor_task_id: string }> {
  const response = await fetch(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor/resume`,
    {
      method: "POST",
    },
  );
  return handleResponse(response);
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
  const response = await fetch(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/subagent-results`,
  );
  return handleResponse<SubAgentResultPayload[]>(response);
}
export async function getAgentMesh(issueId: string): Promise<AgentMessage[]> {
  const response = await fetch(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/agent-mesh`,
  );
  return handleResponse<AgentMessage[]>(response);
}
export async function appendConductorMessage(
  projectId: string,
  message: string,
): Promise<{ status: string }> {
  const response = await fetch(
    `${API_BASE}/codex/projects/${encodeURIComponent(projectId)}/conductor/message`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    },
  );
  return handleResponse<{ status: string }>(response);
}
