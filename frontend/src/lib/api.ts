import type {
  HealthResponse,
  Workspace,
  CodexIssue,
  CodexTask,
  CodexTaskMessage,
  ExecutionProcess,
  LogEvent,
  Artifact,
  PendingApprovalsResponse,
  CreateWorkspaceRequest,
  CreateTaskRequest,
  CreateIssueRequest,
  UpdateIssuePhaseRequest,
  RequestHelpRequest,
  SendMessageRequest,
  SendMessageResult,
  ResolveApprovalRequest,
  HelpRequest,
  IssuePhaseTransitionResult,
  IssuePhaseMultiTaskTransitionResult,
  UpdateCodexTaskRequest,
  RuntimeCatalog,
  RuntimeCatalogRequest,
  ValidateRuntimeCatalogResponse,
  TestExecutorResponse,
  Project,
  GitBranch,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api";
const WS_BASE = process.env.NEXT_PUBLIC_WS_BASE ?? "ws://localhost:8000";

export { API_BASE, WS_BASE };

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let errorMessage = `HTTP ${response.status}`;
    try {
      const err = await response.json();
      errorMessage = (err as { detail?: string }).detail || errorMessage;
    } catch {
      // If JSON parsing fails, try reading as text
      try {
        const text = await response.text();
        if (text.includes("<html>") || text.includes("<!DOCTYPE html>")) {
          errorMessage = `Server Error (${response.status}): The request returned an invalid response. This often happens if the API endpoint is incorrect or the server is down.`;
        } else if (text.length > 0 && text.length < 200) {
          errorMessage = text;
        }
      } catch {
        // Fallback to default errorMessage
      }
    }
    throw new Error(errorMessage);
  }
  return response.json() as Promise<T>;
}

export async function checkBackendHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE}/health`);
  if (!response.ok) {
    throw new Error(`Backend unreachable: HTTP ${response.status}`);
  }
  const data = await response.json();
  if (data.service !== "agent-collab-console") {
    throw new Error(`Wrong backend: ${data.service}`);
  }
  return data;
}

export async function getCodexStatus(): Promise<unknown> {
  const response = await fetch(`${API_BASE}/codex/status`);
  if (!response.ok) {
    throw new Error(`Failed to get Codex status: HTTP ${response.status}`);
  }
  return response.json();
}

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

// --- Project APIs ---

export async function listProjects(): Promise<Project[]> {
  const response = await fetch(`${API_BASE}/projects`);
  return handleResponse<Project[]>(response);
}

export async function getProject(projectId: string): Promise<Project> {
  const response = await fetch(`${API_BASE}/projects/${projectId}`);
  return handleResponse<Project>(response);
}

export async function createProject(body: import("./types").CreateProjectRequest): Promise<Project> {
  const response = await fetch(`${API_BASE}/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<Project>(response);
}

export async function updateProject(
  projectId: string,
  updates: import("./types").UpdateProjectRequest,
): Promise<Project> {
  const response = await fetch(`${API_BASE}/projects/${projectId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  return handleResponse<Project>(response);
}

export async function deleteProject(projectId: string, force = false): Promise<unknown> {
  const url = force
    ? `${API_BASE}/projects/${projectId}?force=true`
    : `${API_BASE}/projects/${projectId}`;
  const response = await fetch(url, { method: "DELETE" });
  return handleResponse(response);
}

export async function getProjectBranches(projectId: string): Promise<GitBranch[]> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/branches`);
  return handleResponse<GitBranch[]>(response);
}

export async function repairProject(projectId: string): Promise<{ pruned: boolean; issues_reset: number }> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/repair`, { method: "POST" });
  return handleResponse(response);
}

export async function mergeCodexIssue(
  issueId: string,
  message: string | null = null,
): Promise<import("./types").MergeIssueResult> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/merge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  return handleResponse<import("./types").MergeIssueResult>(response);
}

export async function getCodexIssueDiff(issueId: string): Promise<import("./types").IssueDiffResult> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/diff`);
  return handleResponse<import("./types").IssueDiffResult>(response);
}

export async function abandonCodexIssue(issueId: string): Promise<CodexIssue> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/abandon`, { method: "POST" });
  return handleResponse<CodexIssue>(response);
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

export const getCodexSessions = getWorkspaces;
export const createCodexSession = createWorkspace;
export const getCodexSession = getWorkspace;
export const deleteCodexSession = deleteWorkspace;
export const deleteAllCodexSessions = deleteAllWorkspaces;

export async function createCodexTask(
  sessionId: string,
  title: string,
  prompt: string,
  parentTaskId: string | null = null,
  executor = "codex",
  role = "general",
  issueId: string | null = null,
  phase = "requirements",
  provider: string | null = null,
  model: string | null = null
): Promise<CodexTask> {
  const body: CreateTaskRequest = {
    session_id: sessionId,
    issue_id: issueId,
    phase,
    title,
    prompt,
    parent_task_id: parentTaskId,
    executor,
    provider,
    model,
    role,
  };
  const response = await fetch(`${API_BASE}/codex/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<CodexTask>(response);
}

export async function createCodexIssue(
  sessionId: string,
  title: string,
  description = "",
  baseBranch: string | null = null,
): Promise<CodexIssue> {
  const body: CreateIssueRequest = { session_id: sessionId, title, description };
  if (baseBranch) body.base_branch = baseBranch;
  const response = await fetch(`${API_BASE}/codex/issues`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<CodexIssue>(response);
}

export async function getCodexIssues(
  sessionId: string | null = null,
  projectId: string | null = null,
): Promise<CodexIssue[]> {
  const params = new URLSearchParams();
  if (sessionId) params.set("session_id", sessionId);
  if (projectId) params.set("project_id", projectId);
  const query = params.toString();
  const url = query ? `${API_BASE}/codex/issues?${query}` : `${API_BASE}/codex/issues`;
  const response = await fetch(url);
  if (!response.ok) {
    console.error(`getCodexIssues failed: HTTP ${response.status}`);
    return [];
  }
  return response.json();
}

export async function getCodexIssueArtifacts(issueId: string): Promise<Artifact[]> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/artifacts`);
  if (!response.ok) {
    console.error(`getCodexIssueArtifacts(${issueId}) failed: HTTP ${response.status}`);
    return [];
  }
  return response.json();
}

export async function updateCodexIssuePhase(issueId: string, currentPhase: string): Promise<CodexIssue> {
  const body: UpdateIssuePhaseRequest = { current_phase: currentPhase };
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/phase`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<CodexIssue>(response);
}

export async function transitionIssueToArchitecture(issueId: string): Promise<IssuePhaseTransitionResult> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/transition-to-architecture`, {
    method: "POST",
  });
  return handleResponse<IssuePhaseTransitionResult>(response);
}

export async function transitionIssueToDevelopment(issueId: string): Promise<IssuePhaseMultiTaskTransitionResult> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/transition-to-development`, {
    method: "POST",
  });
  return handleResponse<IssuePhaseMultiTaskTransitionResult>(response);
}

export async function transitionIssueToTesting(issueId: string): Promise<IssuePhaseTransitionResult> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/transition-to-testing`, {
    method: "POST",
  });
  return handleResponse<IssuePhaseTransitionResult>(response);
}

export async function deleteCodexIssue(issueId: string): Promise<unknown> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}`, {
    method: "DELETE",
  });
  return handleResponse(response);
}

export async function updateCodexIssue(
  issueId: string,
  updates: { title?: string; description?: string }
): Promise<CodexIssue> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  return handleResponse<CodexIssue>(response);
}

export async function getCodexTasks(sessionId: string | null = null, issueId: string | null = null): Promise<CodexTask[]> {
  const params = new URLSearchParams();
  if (sessionId) params.set("session_id", sessionId);
  if (issueId) params.set("issue_id", issueId);
  const query = params.toString();
  const url = query ? `${API_BASE}/codex/tasks?${query}` : `${API_BASE}/codex/tasks`;
  const response = await fetch(url);
  if (!response.ok) {
    console.error(`getCodexTasks failed: HTTP ${response.status}`);
    return [];
  }
  return response.json();
}

export async function getCodexTask(taskId: string): Promise<CodexTask> {
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}`);
  return handleResponse<CodexTask>(response);
}

export async function runCodexTask(
  taskId: string,
  overrides?: { executor?: "codex" | "claude"; provider?: string | null; model?: string | null }
): Promise<ExecutionProcess> {
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}/run`, {
    method: "POST",
    headers: overrides ? { "Content-Type": "application/json" } : undefined,
    body: overrides ? JSON.stringify(overrides) : undefined,
  });
  return handleResponse<ExecutionProcess>(response);
}

export async function requestCodexTaskHelp(
  taskId: string,
  targetExecutor: string,
  title = "",
  prompt = "",
  contextSummary = ""
): Promise<unknown> {
  const body: RequestHelpRequest = {
    target_executor: targetExecutor,
    title: title || undefined,
    prompt: prompt || undefined,
    context_summary: contextSummary || undefined,
  };
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}/request-help`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse(response);
}

export async function deleteCodexTask(taskId: string): Promise<unknown> {
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}`, {
    method: "DELETE",
  });
  return handleResponse(response);
}

export async function terminateCodexTask(taskId: string): Promise<unknown> {
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}/terminate`, {
    method: "POST",
  });
  return handleResponse(response);
}

export async function getCodexTaskLogs(taskId: string): Promise<unknown[]> {
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}/logs`);
  if (!response.ok) {
    console.error(`getCodexTaskLogs(${taskId}) failed: HTTP ${response.status}`);
    return [];
  }
  return response.json();
}

export async function getCodexTaskMessages(taskId: string): Promise<CodexTaskMessage[]> {
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}/messages`);
  if (!response.ok) {
    console.error(`getCodexTaskMessages(${taskId}) failed: HTTP ${response.status}`);
    return [];
  }
  return response.json();
}

export async function getTaskHelpRequests(taskId: string): Promise<HelpRequest[]> {
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}/help-requests`);
  if (!response.ok) {
    console.error(`getTaskHelpRequests(${taskId}) failed: HTTP ${response.status}`);
    return [];
  }
  return response.json();
}

export async function sendCodexTaskMessage(taskId: string, content: string): Promise<SendMessageResult> {
  const body: SendMessageRequest = { content };
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<SendMessageResult>(response);
}

export async function chatCodexTask(taskId: string, content: string): Promise<SendMessageResult> {
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  return handleResponse<SendMessageResult>(response);
}

export async function sendCodexTask(
  taskId: string,
  content: string,
  forceMode?: "chat" | "refine",
): Promise<SendMessageResult> {
  const body: { content: string; force_mode?: "chat" | "refine" } = { content };
  if (forceMode) body.force_mode = forceMode;
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}/send`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<SendMessageResult>(response);
}

export async function refineCodexTask(taskId: string, content: string): Promise<SendMessageResult> {
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}/refine`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  return handleResponse<SendMessageResult>(response);
}

export async function rerunCodexTask(
  taskId: string,
  overrides?: { executor?: string | null; provider?: string | null; model?: string | null },
): Promise<SendMessageResult> {
  const hasOverrides = !!(overrides && (overrides.executor || overrides.provider || overrides.model));
  const init: RequestInit = { method: "POST" };
  if (hasOverrides) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(overrides);
  } else {
    init.headers = { "Content-Type": "application/json" };
  }
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}/rerun`, init);
  return handleResponse<SendMessageResult>(response);
}

export async function updateCodexTaskExecutor(taskId: string, executor: "codex" | "claude"): Promise<CodexTask> {
  const body: UpdateCodexTaskRequest = { executor };
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<CodexTask>(response);
}

export async function updateCodexTask(
  taskId: string,
  executor?: "codex" | "claude",
  provider?: string | null,
  model?: string | null
): Promise<CodexTask> {
  const body: UpdateCodexTaskRequest = {};
  if (executor !== undefined) body.executor = executor;
  if (provider !== undefined) body.provider = provider;
  if (model !== undefined) body.model = model;
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<CodexTask>(response);
}

// Runtime Catalog APIs

export async function getRuntimeCatalog(): Promise<RuntimeCatalog> {
  try {
    const response = await fetch(`${API_BASE}/runtime-catalog`);
    return handleResponse<RuntimeCatalog>(response);
  } catch (err) {
    console.error(`getRuntimeCatalog failed:`, err);
    throw err;
  }
}

export async function updateRuntimeCatalog(catalog: RuntimeCatalog): Promise<RuntimeCatalog> {
  const body: RuntimeCatalogRequest = { catalog };
  const response = await fetch(`${API_BASE}/runtime-catalog`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<RuntimeCatalog>(response);
}

export async function validateRuntimeCatalog(catalog: RuntimeCatalog): Promise<ValidateRuntimeCatalogResponse> {
  const body: RuntimeCatalogRequest = { catalog };
  const response = await fetch(`${API_BASE}/runtime-catalog/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<ValidateRuntimeCatalogResponse>(response);
}

export interface TestExecutorRequest {
  executor_id: string;
  provider_id?: string | null;
  model_id?: string | null;
  api_endpoint?: string | null;
  api_key?: string | null;
}

export async function testRuntimeExecutor(request: TestExecutorRequest): Promise<TestExecutorResponse> {
  const response = await fetch(`${API_BASE}/runtime-catalog/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return handleResponse<TestExecutorResponse>(response);
}

export async function submitCodexTask(taskId: string): Promise<CodexTask> {
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}/submit`, {
    method: "POST",
  });
  return handleResponse<CodexTask>(response);
}

export async function reviewCodexTask(taskId: string, decision: "approve" | "reject", comment: string | null): Promise<CodexTask> {
  const body = { decision, comment };
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<CodexTask>(response);
}

export async function getExecutionProcess(processId: string): Promise<ExecutionProcess> {
  try {
    const response = await fetch(`${API_BASE}/codex/execution-processes/${processId}`);
    return handleResponse<ExecutionProcess>(response);
  } catch (err) {
    console.error(`getExecutionProcess(${processId}) failed:`, err);
    throw err;
  }
}

export async function getExecutionProcesses(
  sessionId: string | null = null,
  taskId: string | null = null,
): Promise<ExecutionProcess[]> {
  const params = new URLSearchParams();
  if (sessionId) params.set("session_id", sessionId);
  if (taskId) params.set("task_id", taskId);
  const query = params.toString();
  const url = query ? `${API_BASE}/codex/execution-processes?${query}` : `${API_BASE}/codex/execution-processes`;
  const response = await fetch(url);
  if (!response.ok) {
    console.error(`getExecutionProcesses failed: HTTP ${response.status}`);
    return [];
  }
  return response.json();
}

export async function continueCodexTask(taskId: string): Promise<unknown> {
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}/continue`, {
    method: "POST",
  });
  return handleResponse(response);
}

export async function getExecutionProcessMessages(processId: string): Promise<CodexTaskMessage[]> {
  try {
    const response = await fetch(`${API_BASE}/codex/execution-processes/${processId}/messages`);
    return handleResponse<CodexTaskMessage[]>(response);
  } catch (err) {
    console.error(`getExecutionProcessMessages(${processId}) failed:`, err);
    throw err;
  }
}

export async function getExecutionProcessLogs(processId: string): Promise<LogEvent[]> {
  try {
    const response = await fetch(`${API_BASE}/codex/execution-processes/${processId}/logs`);
    return handleResponse<LogEvent[]>(response);
  } catch (err) {
    console.error(`getExecutionProcessLogs(${processId}) failed:`, err);
    throw err;
  }
}

export async function resolveApproval(itemId: string, decision: string, feedback: string | null = null): Promise<unknown> {
  const body: ResolveApprovalRequest = { item_id: itemId, decision, feedback };
  const response = await fetch(`${API_BASE}/codex/approvals/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse(response);
}

export async function getPendingApprovals(): Promise<PendingApprovalsResponse> {
  const response = await fetch(`${API_BASE}/codex/approvals/pending`);
  if (!response.ok) {
    console.error(`getPendingApprovals failed: HTTP ${response.status}`);
    return { pending: [] };
  }
  return response.json();
}

export async function exportCodexIssues(sessionId: string | null = null, format: "csv" | "json" = "json"): Promise<string> {
  const params = new URLSearchParams();
  if (sessionId) params.set("session_id", sessionId);
  const query = params.toString();
  const url = query ? `${API_BASE}/codex/issues/export?${query}` : `${API_BASE}/codex/issues/export`;
  const response = await fetch(`${url}&format=${format}`);
  if (!response.ok) {
    throw new Error(`Export failed: HTTP ${response.status}`);
  }
  if (format === "csv") {
    return response.text();
  }
  const data = await response.json();
  return JSON.stringify(data, null, 2);
}

export async function exportCodexTasks(sessionId: string | null = null, issueId: string | null = null, format: "csv" | "json" = "json"): Promise<string> {
  const params = new URLSearchParams();
  if (sessionId) params.set("session_id", sessionId);
  if (issueId) params.set("issue_id", issueId);
  const query = params.toString();
  const url = query ? `${API_BASE}/codex/tasks/export?${query}` : `${API_BASE}/codex/tasks/export`;
  const response = await fetch(`${url}&format=${format}`);
  if (!response.ok) {
    throw new Error(`Export failed: HTTP ${response.status}`);
  }
  if (format === "csv") {
    return response.text();
  }
  const data = await response.json();
  return JSON.stringify(data, null, 2);
}

export async function importCodexIssues(sessionId: string, data: string, format: "csv" | "json"): Promise<CodexIssue[]> {
  const formData = new FormData();
  formData.append("data", data);
  formData.append("format", format);
  const response = await fetch(`${API_BASE}/codex/issues/import?session_id=${encodeURIComponent(sessionId)}`, {
    method: "POST",
    body: formData,
  });
  return handleResponse<CodexIssue[]>(response);
}

export async function importCodexTasks(sessionId: string, data: string, format: "csv" | "json"): Promise<CodexTask[]> {
  const formData = new FormData();
  formData.append("data", data);
  formData.append("format", format);
  const response = await fetch(`${API_BASE}/codex/tasks/import?session_id=${encodeURIComponent(sessionId)}`, {
    method: "POST",
    body: formData,
  });
  return handleResponse<CodexTask[]>(response);
}

export function downloadFile(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export async function bulkUpdateIssues(issueIds: string[], updates: { current_phase?: string; status?: string }): Promise<CodexIssue[]> {
  const response = await fetch(`${API_BASE}/codex/issues/bulk-update`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ issue_ids: issueIds, updates }),
  });
  return handleResponse<CodexIssue[]>(response);
}

export async function bulkDeleteIssues(issueIds: string[]): Promise<void> {
  const response = await fetch(`${API_BASE}/codex/issues/bulk-delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ issue_ids: issueIds }),
  });
  return handleResponse(response);
}

// WebSocket URL builders
export function getWorkspaceStreamUrl(workspaceId: string): string {
  return `${WS_BASE}/api/workspaces/${workspaceId}/execution_processes/ws`;
}

export function getProcessLogsUrl(processId: string): string {
  return `${WS_BASE}/api/execution-processes/${processId}/logs/ws`;
}

export function getProcessMessagesUrl(processId: string): string {
  return `${WS_BASE}/api/execution-processes/${processId}/messages/ws`;
}
