// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, apiJsonRequest, apiRequest, apiRequestOr, handleResponse } from "./fetch";
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
  ProjectRunEnvError,
  ProjectRunStartReason,
  ProjectRunStatus,
  ProjectScriptSuggestionRequest,
  ProjectScriptSuggestionResponse,
  ProjectScriptTaskRequest,
  ProjectScriptTaskResponse,
  ProjectStartupConfig,
  ProjectServicesRunResponse,
  ProjectStats,
  UpdateProjectRequest,
} from "../types";

export async function listProjects(): Promise<Project[]> {
  return apiRequest<Project[]>(`${API_BASE}/projects`);
}
export async function getProject(projectId: string): Promise<Project> {
  return apiRequest<Project>(`${API_BASE}/projects/${projectId}`);
}
export async function createProject(body: CreateProjectRequest): Promise<Project> {
  return apiJsonRequest<Project>(`${API_BASE}/projects`, "POST", body);
}
export async function updateProject(
  projectId: string,
  updates: UpdateProjectRequest,
): Promise<Project> {
  return apiJsonRequest<Project>(`${API_BASE}/projects/${projectId}`, "PATCH", updates);
}
export async function suggestProjectScript(
  projectId: string,
  body: ProjectScriptSuggestionRequest,
): Promise<ProjectScriptSuggestionResponse> {
  return apiJsonRequest<ProjectScriptSuggestionResponse>(
    `${API_BASE}/projects/${projectId}/script-suggestion`,
    "POST",
    body,
  );
}
export async function startProjectScriptTask(
  projectId: string,
  body: ProjectScriptTaskRequest,
): Promise<ProjectScriptTaskResponse> {
  return apiJsonRequest<ProjectScriptTaskResponse>(
    `${API_BASE}/projects/${projectId}/script-task`,
    "POST",
    body,
  );
}
export async function deleteProject(projectId: string, force = false): Promise<unknown> {
  const url = force
    ? `${API_BASE}/projects/${projectId}?force=true`
    : `${API_BASE}/projects/${projectId}`;
  return apiRequest<unknown>(url, { method: "DELETE" });
}
export async function selectDirectory(): Promise<string | null> {
  const data = await apiRequest<{ path: string | null }>(`${API_BASE}/utils/select-directory`);
  return data.path;
}
export async function getProjectBranches(projectId: string): Promise<GitBranch[]> {
  return apiRequest<GitBranch[]>(`${API_BASE}/projects/${projectId}/branches`);
}
export async function repairProject(
  projectId: string,
): Promise<{ pruned: boolean; issues_reset: number }> {
  return apiRequest<{ pruned: boolean; issues_reset: number }>(
    `${API_BASE}/projects/${projectId}/repair`,
    { method: "POST" },
  );
}
export async function getProjectStats(projectId: string): Promise<ProjectStats> {
  return apiRequest<ProjectStats>(`${API_BASE}/projects/${projectId}/stats`);
}
export async function getProjectRemoteStatus(
  projectId: string,
  options: { fetch?: boolean } = {},
): Promise<ProjectRemoteStatus> {
  const doFetch = options.fetch ?? true;
  return apiRequest<ProjectRemoteStatus>(
    `${API_BASE}/projects/${projectId}/remote-status?fetch=${doFetch ? "true" : "false"}`,
  );
}
export async function pullProject(projectId: string): Promise<ProjectPullResult> {
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
  | {
      error: ProjectRunStartReason;
      pattern?: string | undefined;
      errors?: ProjectRunEnvError[] | undefined;
      message?: string | undefined;
      url?: string | null | undefined;
      http_status?: number | null | undefined;
    };
export function isProjectRunStartError(
  result: StartProjectRunResult,
): result is Exclude<StartProjectRunResult, ProjectRunStatus> {
  return "error" in result;
}
export async function startProjectRun(projectId: string): Promise<StartProjectRunResult> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/run/start`, { method: "POST" });
  if (response.status === 200) {
    return (await response.json()) as ProjectRunStatus;
  }
  if (response.status === 409) {
    // FastAPI wraps the refusal payload as {detail: {reason, pattern?, errors?, message?}}.
    const body = (await response.json()) as {
      detail: {
        reason: ProjectRunStartReason;
        pattern?: string;
        errors?: ProjectRunEnvError[];
        message?: string;
        url?: string | null;
        http_status?: number | null;
      };
    };
    return {
      error: body.detail.reason,
      ...(body.detail.pattern !== undefined ? { pattern: body.detail.pattern } : {}),
      ...(body.detail.errors !== undefined ? { errors: body.detail.errors } : {}),
      ...(body.detail.message !== undefined ? { message: body.detail.message } : {}),
      ...(body.detail.url !== undefined ? { url: body.detail.url } : {}),
      ...(body.detail.http_status !== undefined ? { http_status: body.detail.http_status } : {}),
    };
  }
  // 404 / 500 etc. are genuine errors — surface them.
  return handleResponse<ProjectRunStatus>(response);
}
export async function stopProjectRun(projectId: string): Promise<ProjectRunStatus> {
  return apiRequest<ProjectRunStatus>(`${API_BASE}/projects/${projectId}/run/stop`, {
    method: "POST",
  });
}
export async function getProjectRunStatus(projectId: string): Promise<ProjectRunStatus> {
  return apiRequest<ProjectRunStatus>(`${API_BASE}/projects/${projectId}/run/status`);
}
export async function getProjectRunLogs(
  projectId: string,
  after = 0,
): Promise<ProjectRunLogsResponse> {
  return apiRequest<ProjectRunLogsResponse>(
    `${API_BASE}/projects/${projectId}/run/logs?after=${after}`,
  );
}
export async function getProjectStartupConfig(projectId: string): Promise<ProjectStartupConfig> {
  return apiRequest<ProjectStartupConfig>(`${API_BASE}/projects/${projectId}/startup-config`);
}
export async function getProjectServiceRunStatus(
  projectId: string,
  serviceId: string,
): Promise<ProjectRunStatus> {
  return apiRequest<ProjectRunStatus>(
    `${API_BASE}/projects/${projectId}/services/${encodeURIComponent(serviceId)}/run/status`,
  );
}
export async function getProjectServiceRunLogs(
  projectId: string,
  serviceId: string,
  after = 0,
): Promise<ProjectRunLogsResponse> {
  return apiRequest<ProjectRunLogsResponse>(
    `${API_BASE}/projects/${projectId}/services/${encodeURIComponent(serviceId)}/run/logs?after=${after}`,
  );
}
export async function startProjectServiceRun(
  projectId: string,
  serviceId: string,
): Promise<ProjectRunStatus> {
  return apiRequest<ProjectRunStatus>(
    `${API_BASE}/projects/${projectId}/services/${encodeURIComponent(serviceId)}/run/start`,
    { method: "POST" },
  );
}
export async function stopProjectServiceRun(
  projectId: string,
  serviceId: string,
): Promise<ProjectRunStatus> {
  return apiRequest<ProjectRunStatus>(
    `${API_BASE}/projects/${projectId}/services/${encodeURIComponent(serviceId)}/run/stop`,
    { method: "POST" },
  );
}
export async function startAllProjectServices(
  projectId: string,
): Promise<ProjectServicesRunResponse> {
  return apiRequest<ProjectServicesRunResponse>(`${API_BASE}/projects/${projectId}/run/start-all`, {
    method: "POST",
  });
}
export async function stopAllProjectServices(
  projectId: string,
): Promise<ProjectServicesRunResponse> {
  return apiRequest<ProjectServicesRunResponse>(`${API_BASE}/projects/${projectId}/run/stop-all`, {
    method: "POST",
  });
}
export async function getProjectConductorState(projectId: string): Promise<ProjectConductorState> {
  return apiRequest<ProjectConductorState>(
    `${API_BASE}/codex/projects/${projectId}/conductor-state`,
  );
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
  const data = await apiRequestOr<{ conductors?: ConductorSession[] }>(
    url,
    { conductors: [] },
    {
      errorMessage: (status) => `getConductors failed: HTTP ${status}`,
    },
  );
  return data.conductors ?? [];
}
export async function askProjectConductor(
  projectId: string,
  question: string,
): Promise<ProjectConductorAskResult> {
  return apiJsonRequest<ProjectConductorAskResult>(
    `${API_BASE}/codex/projects/${projectId}/conductor/ask`,
    "POST",
    { question },
  );
}
export async function scheduleProjectConductorReview(
  projectId: string,
): Promise<ProjectConductorAskResult> {
  return apiRequest<ProjectConductorAskResult>(
    `${API_BASE}/codex/projects/${projectId}/conductor/schedule-review`,
    {
      method: "POST",
    },
  );
}
export async function startProjectConductorLoop(
  projectId: string,
  prompt?: string,
): Promise<ProjectConductorLoopResult> {
  return apiJsonRequest<ProjectConductorLoopResult>(
    `${API_BASE}/codex/projects/${projectId}/conductor/start-loop`,
    "POST",
    { prompt },
  );
}
export async function getProjectAudit(projectId: string, limit = 10): Promise<ProjectAuditEntry[]> {
  return apiRequest<ProjectAuditEntry[]>(`${API_BASE}/projects/${projectId}/audit?limit=${limit}`);
}

export async function getProjectEnvVars(projectId: string): Promise<{
  env_vars: Array<{
    name: string;
    secret: boolean;
    source: string;
    is_set: boolean;
    value?: string;
  }>;
}> {
  return apiRequest(`${API_BASE}/projects/${projectId}/env`);
}

export async function putProjectEnvVars(
  projectId: string,
  body:
    | { name: string; value: string; secret?: boolean; source?: string }
    | { vars: Array<{ name: string; value: string; secret?: boolean; source?: string }> },
): Promise<{ saved: string[] }> {
  return apiJsonRequest(`${API_BASE}/projects/${projectId}/env`, "PUT", body);
}

export async function deleteProjectEnvVar(
  projectId: string,
  name: string,
): Promise<{ deleted: string }> {
  return apiRequest(`${API_BASE}/projects/${projectId}/env/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
}
