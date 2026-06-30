// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, WS_BASE, handleResponse } from "./fetch";
import type { CreateWorkspaceRequest, Workspace } from "../types";

export async function getWorkspaces(projectId: string | null = null): Promise<Workspace[]> {
  const url = projectId
    ? `${API_BASE}/codex/workspaces?project_id=${encodeURIComponent(projectId)}`
    : `${API_BASE}/codex/workspaces`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to load workspaces: HTTP ${response.status}`);
  }
  return response.json();
}
export async function createWorkspace(
  title: string,
  projectId: string,
  cwd = "",
): Promise<Workspace> {
  const body: CreateWorkspaceRequest = { title, project_id: projectId, cwd };
  const response = await fetch(`${API_BASE}/codex/workspaces`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<Workspace>(response);
}
export async function updateWorkspace(
  workspaceId: string,
  patch: { title?: string; cwd?: string; plan_first_pm?: boolean },
): Promise<Workspace> {
  const response = await fetch(`${API_BASE}/codex/workspaces/${workspaceId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return handleResponse<Workspace>(response);
}
export async function getWorkspace(workspaceId: string): Promise<Workspace> {
  const response = await fetch(`${API_BASE}/codex/workspaces/${workspaceId}`);
  return handleResponse<Workspace>(response);
}
export async function deleteWorkspace(workspaceId: string): Promise<unknown> {
  const response = await fetch(`${API_BASE}/codex/workspaces/${workspaceId}`, {
    method: "DELETE",
  });
  return handleResponse(response);
}
export async function deleteAllWorkspaces(): Promise<unknown> {
  const response = await fetch(`${API_BASE}/codex/workspaces`, {
    method: "DELETE",
  });
  return handleResponse(response);
}
export async function sendWorkspaceInput(workspaceId: string, input: string): Promise<unknown> {
  const response = await fetch(`${API_BASE}/codex/workspaces/${workspaceId}/input`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input }),
  });
  return handleResponse(response);
}
export async function terminateWorkspace(workspaceId: string): Promise<unknown> {
  const response = await fetch(`${API_BASE}/codex/workspaces/${workspaceId}/terminate`, {
    method: "POST",
  });
  return handleResponse(response);
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
