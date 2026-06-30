// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, WS_BASE, dedupedFetch, handleResponse } from "./fetch";
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
export async function getCodexTasks(
  sessionId: string | null = null,
  issueId: string | null = null,
): Promise<CodexTask[]> {
  const params = new URLSearchParams();
  if (sessionId) params.set("session_id", sessionId);
  if (issueId) params.set("issue_id", issueId);
  const query = params.toString();
  const url = query ? `${API_BASE}/codex/tasks?${query}` : `${API_BASE}/codex/tasks`;
  const response = await dedupedFetch(url);
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
  overrides?: { executor?: string | null; provider?: string | null; model?: string | null },
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
  contextSummary = "",
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
export async function sendCodexTaskMessage(
  taskId: string,
  content: string,
): Promise<SendMessageResult> {
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
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}/rerun`, init);
  return handleResponse<SendMessageResult>(response);
}
export async function updateCodexTaskExecutor(
  taskId: string,
  executor: "codex" | "claude",
): Promise<CodexTask> {
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
  executor?: string | null,
  provider?: string | null,
  model?: string | null,
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
export async function submitCodexTask(taskId: string): Promise<CodexTask> {
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}/submit`, {
    method: "POST",
  });
  return handleResponse<CodexTask>(response);
}
export async function reviewCodexTask(
  taskId: string,
  decision: "approve" | "reject",
  comment: string | null,
): Promise<CodexTask> {
  const body = { decision, comment };
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<CodexTask>(response);
}
/** Answer a task that paused waiting for clarification. Re-runs the task
 * with the answer threaded through review_comment. */
export async function answerCodexTaskClarification(
  taskId: string,
  answer: string,
): Promise<CodexTask> {
  const response = await fetch(`${API_BASE}/codex/tasks/${taskId}/answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answer }),
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
  const url = query
    ? `${API_BASE}/codex/execution-processes?${query}`
    : `${API_BASE}/codex/execution-processes`;
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
  const response = await fetch(
    `${API_BASE}/codex/tasks/import?session_id=${encodeURIComponent(sessionId)}`,
    {
      method: "POST",
      body: formData,
    },
  );
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
export function getProcessLogsUrl(processId: string): string {
  return `${WS_BASE}/api/execution-processes/${processId}/logs/ws`;
}
export function getProcessMessagesUrl(processId: string): string {
  return `${WS_BASE}/api/execution-processes/${processId}/messages/ws`;
}
