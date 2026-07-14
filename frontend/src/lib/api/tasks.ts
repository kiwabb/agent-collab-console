// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, apiJsonRequest, apiRequest, apiRequestOr, getWebSocketBase } from "./fetch";
import type {
  CodexTask,
  CodexTaskMessage,
  CreateTaskRequest,
  ExecutionProcess,
  HelpRequest,
  LogEvent,
  RequestHelpRequest,
  SendMessageRequest,
  SendMessageResult,
  UpdateCodexTaskRequest,
} from "../types";

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
  model: string | null = null,
): Promise<CodexTask> {
  const body: CreateTaskRequest = {
    session_id: sessionId,
    issue_id: issueId,
    phase,
    title,
    prompt,
    parent_task_id: parentTaskId,
    executor: executor ?? undefined,
    provider,
    model,
    role,
  };
  return apiJsonRequest<CodexTask>(`${API_BASE}/codex/tasks`, "POST", body);
}
export async function getCodexTasks(
  sessionId: string | null = null,
  issueId: string | null = null,
): Promise<CodexTask[]> {
  const params = new URLSearchParams();
  if (sessionId) params.set("session_id", sessionId);
  if (issueId) params.set("issue_id", issueId);
  const query = params.toString();
  const url = query ? `${API_BASE}/codex/tasks?${query}` : `${API_BASE}/codex/tasks`;
  return apiRequestOr<CodexTask[]>(url, [], {
    dedupe: true,
    errorMessage: (status) => `getCodexTasks failed: HTTP ${status}`,
  });
}

export async function getProjectTasks(projectId: string): Promise<CodexTask[]> {
  return apiRequest<CodexTask[]>(
    `${API_BASE}/codex/tasks?project_id=${encodeURIComponent(projectId)}`,
  );
}

export async function getCodexTask(taskId: string): Promise<CodexTask> {
  return apiRequest<CodexTask>(`${API_BASE}/codex/tasks/${taskId}`);
}
export async function runCodexTask(
  taskId: string,
  overrides?: {
    executor?: string | null | undefined;
    provider?: string | null | undefined;
    model?: string | null | undefined;
  },
): Promise<ExecutionProcess> {
  const init: RequestInit = overrides
    ? {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(overrides),
      }
    : { method: "POST" };
  return apiRequest<ExecutionProcess>(`${API_BASE}/codex/tasks/${taskId}/run`, init);
}
export async function requestCodexTaskHelp(
  taskId: string,
  targetExecutor: string,
  title = "",
  prompt = "",
  contextSummary = "",
): Promise<unknown> {
  const body: RequestHelpRequest = { target_executor: targetExecutor };
  if (title) body.title = title;
  if (prompt) body.prompt = prompt;
  if (contextSummary) body.context_summary = contextSummary;
  return apiJsonRequest<unknown>(`${API_BASE}/codex/tasks/${taskId}/request-help`, "POST", body);
}
export async function deleteCodexTask(taskId: string): Promise<unknown> {
  return apiRequest<unknown>(`${API_BASE}/codex/tasks/${taskId}`, {
    method: "DELETE",
  });
}
export async function terminateCodexTask(taskId: string): Promise<unknown> {
  return apiRequest<unknown>(`${API_BASE}/codex/tasks/${taskId}/terminate`, {
    method: "POST",
  });
}
export async function getCodexTaskLogs(taskId: string): Promise<unknown[]> {
  return apiRequestOr<unknown[]>(`${API_BASE}/codex/tasks/${taskId}/logs`, [], {
    errorMessage: (status) => `getCodexTaskLogs(${taskId}) failed: HTTP ${status}`,
  });
}
export async function getCodexTaskMessages(taskId: string): Promise<CodexTaskMessage[]> {
  return apiRequestOr<CodexTaskMessage[]>(`${API_BASE}/codex/tasks/${taskId}/messages`, [], {
    errorMessage: (status) => `getCodexTaskMessages(${taskId}) failed: HTTP ${status}`,
  });
}
export async function getTaskHelpRequests(taskId: string): Promise<HelpRequest[]> {
  return apiRequestOr<HelpRequest[]>(`${API_BASE}/codex/tasks/${taskId}/help-requests`, [], {
    errorMessage: (status) => `getTaskHelpRequests(${taskId}) failed: HTTP ${status}`,
  });
}
export async function sendCodexTaskMessage(
  taskId: string,
  content: string,
): Promise<SendMessageResult> {
  const body: SendMessageRequest = { content };
  return apiJsonRequest<SendMessageResult>(
    `${API_BASE}/codex/tasks/${taskId}/messages`,
    "POST",
    body,
  );
}
export async function chatCodexTask(taskId: string, content: string): Promise<SendMessageResult> {
  return apiJsonRequest<SendMessageResult>(`${API_BASE}/codex/tasks/${taskId}/chat`, "POST", {
    content,
  });
}
export async function sendCodexTask(
  taskId: string,
  content: string,
  forceMode?: "chat" | "refine",
): Promise<SendMessageResult> {
  const body: { content: string; force_mode?: "chat" | "refine" } = { content };
  if (forceMode) body.force_mode = forceMode;
  return apiJsonRequest<SendMessageResult>(`${API_BASE}/codex/tasks/${taskId}/send`, "POST", body);
}
export async function refineCodexTask(taskId: string, content: string): Promise<SendMessageResult> {
  return apiJsonRequest<SendMessageResult>(`${API_BASE}/codex/tasks/${taskId}/refine`, "POST", {
    content,
  });
}
export async function rerunCodexTask(
  taskId: string,
  overrides?: {
    executor?: string | null | undefined;
    provider?: string | null | undefined;
    model?: string | null | undefined;
  },
): Promise<SendMessageResult> {
  const hasOverrides = !!(
    overrides &&
    (overrides.executor || overrides.provider || overrides.model)
  );
  const init: RequestInit = { method: "POST" };
  if (hasOverrides) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(overrides);
  } else {
    init.headers = { "Content-Type": "application/json" };
  }
  return apiRequest<SendMessageResult>(`${API_BASE}/codex/tasks/${taskId}/rerun`, init);
}
export async function updateCodexTaskExecutor(
  taskId: string,
  executor: "codex" | "claude",
): Promise<CodexTask> {
  const body: UpdateCodexTaskRequest = { executor };
  return apiJsonRequest<CodexTask>(`${API_BASE}/codex/tasks/${taskId}`, "PATCH", body);
}
export async function updateCodexTask(
  taskId: string,
  executor?: string | null,
  provider?: string | null,
  model?: string | null,
): Promise<CodexTask> {
  const body: UpdateCodexTaskRequest = {};
  if (executor !== undefined) {
    body.executor = executor;
  }
  if (provider !== undefined) body.provider = provider;
  if (model !== undefined) body.model = model;
  return apiJsonRequest<CodexTask>(`${API_BASE}/codex/tasks/${taskId}`, "PATCH", body);
}
export async function submitCodexTask(taskId: string): Promise<CodexTask> {
  return apiRequest<CodexTask>(`${API_BASE}/codex/tasks/${taskId}/submit`, {
    method: "POST",
  });
}
export async function reviewCodexTask(
  taskId: string,
  decision: "approve" | "reject",
  comment: string | null,
): Promise<CodexTask> {
  const body = { decision, comment };
  return apiJsonRequest<CodexTask>(`${API_BASE}/codex/tasks/${taskId}/review`, "POST", body);
}
/** Answer a task that paused waiting for clarification. Re-runs the task
 * with the answer threaded through review_comment. */
export async function answerCodexTaskClarification(
  taskId: string,
  answer: string,
): Promise<CodexTask> {
  return apiJsonRequest<CodexTask>(`${API_BASE}/codex/tasks/${taskId}/answer`, "POST", {
    answer,
  });
}
export async function getExecutionProcess(processId: string): Promise<ExecutionProcess> {
  try {
    return await apiRequest<ExecutionProcess>(`${API_BASE}/codex/execution-processes/${processId}`);
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
  const url = query
    ? `${API_BASE}/codex/execution-processes?${query}`
    : `${API_BASE}/codex/execution-processes`;
  return apiRequestOr<ExecutionProcess[]>(url, [], {
    errorMessage: (status) => `getExecutionProcesses failed: HTTP ${status}`,
  });
}
export async function continueCodexTask(taskId: string): Promise<unknown> {
  return apiRequest<unknown>(`${API_BASE}/codex/tasks/${taskId}/continue`, {
    method: "POST",
  });
}
export async function getExecutionProcessMessages(processId: string): Promise<CodexTaskMessage[]> {
  try {
    return await apiRequest<CodexTaskMessage[]>(
      `${API_BASE}/codex/execution-processes/${processId}/messages`,
    );
  } catch (err) {
    console.error(`getExecutionProcessMessages(${processId}) failed:`, err);
    throw err;
  }
}
export async function getExecutionProcessLogs(processId: string): Promise<LogEvent[]> {
  try {
    return await apiRequest<LogEvent[]>(`${API_BASE}/codex/execution-processes/${processId}/logs`);
  } catch (err) {
    console.error(`getExecutionProcessLogs(${processId}) failed:`, err);
    throw err;
  }
}
export async function exportCodexTasks(
  sessionId: string | null = null,
  issueId: string | null = null,
  format: "csv" | "json" = "json",
): Promise<string> {
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
export async function importCodexTasks(
  sessionId: string,
  data: string,
  format: "csv" | "json",
): Promise<CodexTask[]> {
  const formData = new FormData();
  formData.append("data", data);
  formData.append("format", format);
  return apiRequest<CodexTask[]>(
    `${API_BASE}/codex/tasks/import?session_id=${encodeURIComponent(sessionId)}`,
    {
      method: "POST",
      body: formData,
    },
  );
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
export function getProcessLogsUrl(processId: string): string {
  return `${getWebSocketBase()}/api/execution-processes/${processId}/logs/ws`;
}
export function getProcessMessagesUrl(processId: string): string {
  return `${getWebSocketBase()}/api/execution-processes/${processId}/messages/ws`;
}
