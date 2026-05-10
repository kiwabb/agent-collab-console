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
  ResolveApprovalRequest,
  HelpRequest,
  IssuePhaseTransitionResult,
  IssuePhaseMultiTaskTransitionResult,
  UpdateCodexTaskRequest,
  RuntimeCatalog,
  RuntimeCatalogRequest,
  ValidateRuntimeCatalogResponse,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api";
const WS_BASE = process.env.NEXT_PUBLIC_WS_BASE ?? "ws://localhost:8000";

export { API_BASE, WS_BASE };

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || `HTTP ${response.status}`);
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

export async function getWorkspaces(): Promise<Workspace[]> {
  const response = await fetch(`${API_BASE}/codex/workspaces`);
  if (!response.ok) {
    throw new Error(`Failed to load workspaces: HTTP ${response.status}`);
  }
  return response.json();
}

export async function createWorkspace(title: string, cwd = ""): Promise<Workspace> {
  const body: CreateWorkspaceRequest = { title, cwd };
  const response = await fetch(`${API_BASE}/codex/workspaces`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
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
  description = ""
): Promise<CodexIssue> {
  const body: CreateIssueRequest = { session_id: sessionId, title, description };
  const response = await fetch(`${API_BASE}/codex/issues`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<CodexIssue>(response);
}

export async function getCodexIssues(sessionId: string | null = null): Promise<CodexIssue[]> {
  const url = sessionId
    ? `${API_BASE}/codex/issues?session_id=${encodeURIComponent(sessionId)}`
    : `${API_BASE}/codex/issues`;
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

export async function sendCodexTaskMessage(taskId: string, content: string): Promise<unknown> {
  const body: SendMessageRequest = { content };
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse(response);
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
