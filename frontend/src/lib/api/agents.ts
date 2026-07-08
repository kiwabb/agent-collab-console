// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, apiJsonRequest, apiRequest } from "./fetch";
import type { Agent, CreateAgentRequest, UpdateAgentRequest } from "../types";

export async function listAgents(
  opts: { workspaceId?: string; roleKey?: string } = {},
): Promise<Agent[]> {
  const params = new URLSearchParams();
  if (opts.workspaceId) params.set("workspace_id", opts.workspaceId);
  if (opts.roleKey) params.set("role_key", opts.roleKey);
  const qs = params.toString();
  return apiRequest<Agent[]>(`${API_BASE}/agents${qs ? `?${qs}` : ""}`);
}
export async function getAgent(agentId: string): Promise<Agent> {
  return apiRequest<Agent>(`${API_BASE}/agents/${agentId}`);
}
export async function createAgent(body: CreateAgentRequest): Promise<Agent> {
  return apiJsonRequest<Agent>(`${API_BASE}/agents`, "POST", body);
}
export async function updateAgent(agentId: string, body: UpdateAgentRequest): Promise<Agent> {
  return apiJsonRequest<Agent>(`${API_BASE}/agents/${agentId}`, "PATCH", body);
}
export async function deleteAgent(agentId: string): Promise<void> {
  return apiRequest<void>(`${API_BASE}/agents/${agentId}`, { method: "DELETE" });
}
