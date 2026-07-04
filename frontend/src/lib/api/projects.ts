// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, handleResponse } from "./fetch";
import type {
  CreateProjectRequest,
  GitBranch,
  Project,
  ProjectAuditEntry,
  ProjectConductorAskResult,
  ProjectConductorLoopResult,
  ProjectConductorState,
  ProjectPullResult,
  ProjectRemoteStatus,
  ProjectRunLogsResponse,
  ProjectRunStartReason,
  ProjectRunStatus,
  ProjectScriptSuggestionRequest,
  ProjectScriptSuggestionResponse,
  ProjectScriptTaskRequest,
  ProjectScriptTaskResponse,
  ProjectStats,
  UpdateProjectRequest,
} from "../types";

export async function listProjects(): Promise<Project[]> {
  const response = await fetch(`${API_BASE}/projects`);
  return handleResponse<Project[]>(response);
}
export async function getProject(projectId: string): Promise<Project> {
  const response = await fetch(`${API_BASE}/projects/${projectId}`);
  return handleResponse<Project>(response);
}
export async function createProject(
  body: CreateProjectRequest,
): Promise<Project> {
  const response = await fetch(`${API_BASE}/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<Project>(response);
}
export async function updateProject(
  projectId: string,
  updates: UpdateProjectRequest,
): Promise<Project> {
  const response = await fetch(`${API_BASE}/projects/${projectId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  return handleResponse<Project>(response);
}
export async function suggestProjectScript(
  projectId: string,
  body: ProjectScriptSuggestionRequest,
): Promise<ProjectScriptSuggestionResponse> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/script-suggestion`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<ProjectScriptSuggestionResponse>(response);
}
export async function startProjectScriptTask(
  projectId: string,
  body: ProjectScriptTaskRequest,
): Promise<ProjectScriptTaskResponse> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/script-task`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<ProjectScriptTaskResponse>(response);
}
export async function deleteProject(projectId: string, force = false): Promise<unknown> {
  const url = force
    ? `${API_BASE}/projects/${projectId}?force=true`
    : `${API_BASE}/projects/${projectId}`;
  const response = await fetch(url, { method: "DELETE" });
  return handleResponse(response);
}
export async function selectDirectory(): Promise<string | null> {
  const response = await fetch(`${API_BASE}/utils/select-directory`);
  const data = await handleResponse<{ path: string | null }>(response);
  return data.path;
}
export async function getProjectBranches(projectId: string): Promise<GitBranch[]> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/branches`);
  return handleResponse<GitBranch[]>(response);
}
export async function repairProject(
  projectId: string,
): Promise<{ pruned: boolean; issues_reset: number }> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/repair`, { method: "POST" });
  return handleResponse(response);
}
export async function getProjectStats(projectId: string): Promise<ProjectStats> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/stats`);
  return handleResponse<ProjectStats>(response);
}
export async function getProjectRemoteStatus(
  projectId: string,
  options: { fetch?: boolean } = {},
): Promise<ProjectRemoteStatus> {
  const doFetch = options.fetch ?? true;
  const response = await fetch(
    `${API_BASE}/projects/${projectId}/remote-status?fetch=${doFetch ? "true" : "false"}`,
  );
  return handleResponse<ProjectRemoteStatus>(response);
}
export async function pullProject(
  projectId: string,
): Promise<ProjectPullResult> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/pull`, { method: "POST" });
  // 200 → the ProjectPullResult directly. 409 → FastAPI wraps our refusal
  // payload as {detail: ProjectPullResult}. Both carry the structured reason we
  // want to show, so unwrap them here rather than throwing on 409.
  if (response.status === 200) {
    return (await response.json()) as ProjectPullResult;
  }
  if (response.status === 409) {
    const body = (await response.json()) as { detail: ProjectPullResult };
    return body.detail;
  }
  // 404 / 500 etc. are genuine errors — surface them.
  return handleResponse<ProjectPullResult>(response);
}
/**
 * Result of starting a project's run_command. On success the live
 * {@link ProjectRunStatus} is returned. On a 409 refusal we unwrap FastAPI's
 * `{detail: {reason, pattern?}}` into `{error, pattern?}` so the caller can
 * branch on the reason without catching a thrown error.
 */
export type StartProjectRunResult =
  | ProjectRunStatus
  | { error: ProjectRunStartReason; pattern?: string };
export function isProjectRunStartError(
  result: StartProjectRunResult,
): result is { error: ProjectRunStartReason; pattern?: string } {
  return "error" in result;
}
export async function startProjectRun(projectId: string): Promise<StartProjectRunResult> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/run/start`, { method: "POST" });
  if (response.status === 200) {
    return (await response.json()) as ProjectRunStatus;
  }
  if (response.status === 409) {
    // FastAPI wraps the refusal payload as {detail: {reason, pattern?}}.
    const body = (await response.json()) as {
      detail: { reason: ProjectRunStartReason; pattern?: string };
    };
    return { error: body.detail.reason, pattern: body.detail.pattern };
  }
  // 404 / 500 etc. are genuine errors — surface them.
  return handleResponse<ProjectRunStatus>(response);
}
export async function stopProjectRun(
  projectId: string,
): Promise<ProjectRunStatus> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/run/stop`, { method: "POST" });
  return handleResponse<ProjectRunStatus>(response);
}
export async function getProjectRunStatus(
  projectId: string,
): Promise<ProjectRunStatus> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/run/status`);
  return handleResponse<ProjectRunStatus>(response);
}
export async function getProjectRunLogs(
  projectId: string,
  after = 0,
): Promise<ProjectRunLogsResponse> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/run/logs?after=${after}`);
  return handleResponse<ProjectRunLogsResponse>(response);
}
export async function getProjectConductorState(projectId: string): Promise<ProjectConductorState> {
  const response = await fetch(`${API_BASE}/codex/projects/${projectId}/conductor-state`);
  return handleResponse<ProjectConductorState>(response);
}
export interface ConductorSession {
  conductor_task_id: string;
  issue_id: string;
  issue_title: string | null;
  project_id: string | null;
  status: string;
  phase: string | null;
  detail: string | null;
  phase_started_at: string | null;
  phase_duration_ms: number | null;
  health: "ok" | "warn" | "danger" | "stalled" | "failed" | "paused";
  lease_owner: string | null;
  alive: boolean;
  updated_at: string | null;
}
export async function getConductors(projectId?: string | null): Promise<ConductorSession[]> {
  const url = projectId
    ? `${API_BASE}/codex/conductors?project_id=${encodeURIComponent(projectId)}`
    : `${API_BASE}/codex/conductors`;
  const response = await fetch(url);
  if (!response.ok) {
    console.error(`getConductors failed: HTTP ${response.status}`);
    return [];
  }
  const data = (await response.json()) as { conductors: ConductorSession[] };
  return data.conductors ?? [];
}
export async function askProjectConductor(
  projectId: string,
  question: string,
): Promise<ProjectConductorAskResult> {
  const response = await fetch(`${API_BASE}/codex/projects/${projectId}/conductor/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  return handleResponse<ProjectConductorAskResult>(response);
}
export async function scheduleProjectConductorReview(
  projectId: string,
): Promise<ProjectConductorAskResult> {
  const response = await fetch(
    `${API_BASE}/codex/projects/${projectId}/conductor/schedule-review`,
    {
      method: "POST",
    },
  );
  return handleResponse<ProjectConductorAskResult>(response);
}
export async function startProjectConductorLoop(
  projectId: string,
  prompt?: string,
): Promise<ProjectConductorLoopResult> {
  const response = await fetch(`${API_BASE}/codex/projects/${projectId}/conductor/start-loop`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
  return handleResponse<ProjectConductorLoopResult>(response);
}
export async function getProjectAudit(
  projectId: string,
  limit = 10,
): Promise<ProjectAuditEntry[]> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/audit?limit=${limit}`);
  return handleResponse<ProjectAuditEntry[]>(response);
}
