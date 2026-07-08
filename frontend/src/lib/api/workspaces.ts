// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, WS_BASE, apiJsonRequest, apiRequest } from "./fetch";
import type { CreateWorkspaceRequest, Workspace } from "../types";

export async function getWorkspaces(projectId: string | null = null): Promise<Workspace[]> {
  const url = projectId
    ? `${API_BASE}/codex/workspaces?project_id=${encodeURIComponent(projectId)}`
    : `${API_BASE}/codex/workspaces`;
  return apiRequest<Workspace[]>(url);
}
export async function createWorkspace(
  title: string,
  projectId: string,
  cwd = "",
): Promise<Workspace> {
  const body: CreateWorkspaceRequest = { title, project_id: projectId, cwd };
  return apiJsonRequest<Workspace>(`${API_BASE}/codex/workspaces`, "POST", body);
}
export async function updateWorkspace(
  workspaceId: string,
  patch: { title?: string; cwd?: string; plan_first_pm?: boolean },
): Promise<Workspace> {
  return apiJsonRequest<Workspace>(`${API_BASE}/codex/workspaces/${workspaceId}`, "PATCH", patch);
}
export async function getWorkspace(workspaceId: string): Promise<Workspace> {
  return apiRequest<Workspace>(`${API_BASE}/codex/workspaces/${workspaceId}`);
}
export async function deleteWorkspace(workspaceId: string): Promise<unknown> {
  return apiRequest<unknown>(`${API_BASE}/codex/workspaces/${workspaceId}`, {
    method: "DELETE",
  });
}
export async function deleteAllWorkspaces(): Promise<unknown> {
  return apiRequest<unknown>(`${API_BASE}/codex/workspaces`, {
    method: "DELETE",
  });
}
export async function sendWorkspaceInput(workspaceId: string, input: string): Promise<unknown> {
  return apiJsonRequest<unknown>(`${API_BASE}/codex/workspaces/${workspaceId}/input`, "POST", {
    input,
  });
}
export async function terminateWorkspace(workspaceId: string): Promise<unknown> {
  return apiRequest<unknown>(`${API_BASE}/codex/workspaces/${workspaceId}/terminate`, {
    method: "POST",
  });
}
export const getCodexSessions = getWorkspaces;
export const createCodexSession = createWorkspace;
export const getCodexSession = getWorkspace;
export const deleteCodexSession = deleteWorkspace;
export const deleteAllCodexSessions = deleteAllWorkspaces;
// WebSocket URL builders
export function getWorkspaceStreamUrl(workspaceId: string): string {
  return `${WS_BASE}/api/workspaces/${workspaceId}/execution_processes/ws`;
}
