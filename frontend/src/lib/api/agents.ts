// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, handleResponse } from "./fetch";
import type { Agent, CreateAgentRequest, UpdateAgentRequest } from "../types";

export async function listAgents(
  opts: { workspaceId?: string; roleKey?: string } = {},
): Promise<Agent[]> {
  const params = new URLSearchParams();
  if (opts.workspaceId) params.set("workspace_id", opts.workspaceId);
  if (opts.roleKey) params.set("role_key", opts.roleKey);
  const qs = params.toString();
  const response = await fetch(`${API_BASE}/agents${qs ? `?${qs}` : ""}`);
  return handleResponse<Agent[]>(response);
}
export async function getAgent(agentId: string): Promise<Agent> {
  const response = await fetch(`${API_BASE}/agents/${agentId}`);
  return handleResponse<Agent>(response);
}
export async function createAgent(body: CreateAgentRequest): Promise<Agent> {
  const response = await fetch(`${API_BASE}/agents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<Agent>(response);
}
export async function updateAgent(agentId: string, body: UpdateAgentRequest): Promise<Agent> {
  const response = await fetch(`${API_BASE}/agents/${agentId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<Agent>(response);
}
export async function deleteAgent(agentId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/agents/${agentId}`, { method: "DELETE" });
  if (!response.ok && response.status !== 204) {
    return handleResponse(response);
  }
}
