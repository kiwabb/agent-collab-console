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
  UpdateCodexTaskRequest,
  RuntimeCatalog,
  RuntimeCatalogRequest,
  ValidateRuntimeCatalogResponse,
  TestExecutorResponse,
  Project,
  GitBranch,
  Agent,
  CreateAgentRequest,
  UpdateAgentRequest,
  WorkflowGraph,
  ProposedDAG,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api";
const WS_BASE = process.env.NEXT_PUBLIC_WS_BASE ?? "ws://localhost:9000";

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

export async function selectDirectory(): Promise<string | null> {
  const response = await fetch(`${API_BASE}/utils/select-directory`);
  const data = await handleResponse<{ path: string | null }>(response);
  return data.path;
}

export async function getProjectBranches(projectId: string): Promise<GitBranch[]> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/branches`);
  return handleResponse<GitBranch[]>(response);
}

export async function repairProject(projectId: string): Promise<{ pruned: boolean; issues_reset: number }> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/repair`, { method: "POST" });
  return handleResponse(response);
}

export async function getProjectStats(projectId: string): Promise<import("./types").ProjectStats> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/stats`);
  return handleResponse<import("./types").ProjectStats>(response);
}

export async function getCodexStats(): Promise<import("./types").CodexStats> {
  const response = await fetch(`${API_BASE}/codex/stats`);
  return handleResponse<import("./types").CodexStats>(response);
}

export interface CodexCostStats {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  est_cost_usd: number;
  sample_size: number;
  pricing: {
    input_per_m: number;
    output_per_m: number;
    cache_per_m: number;
  };
}

export async function getCodexCostStats(opts: {
  issueId?: string | null;
  workspaceId?: string | null;
} = {}): Promise<CodexCostStats> {
  const params = new URLSearchParams();
  if (opts.issueId) params.set("issue_id", opts.issueId);
  if (opts.workspaceId) params.set("workspace_id", opts.workspaceId);
  const qs = params.toString();
  const response = await fetch(`${API_BASE}/codex/cost-stats${qs ? `?${qs}` : ""}`);
  return handleResponse<CodexCostStats>(response);
}

export async function getProjectAudit(
  projectId: string,
  limit = 10,
): Promise<import("./types").ProjectAuditEntry[]> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/audit?limit=${limit}`);
  return handleResponse<import("./types").ProjectAuditEntry[]>(response);
}

export async function mergeCodexIssue(
  issueId: string,
  message: string | null = null,
  allowDivergedBase = false,
): Promise<import("./types").MergeIssueResult> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/merge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, allow_diverged_base: allowDivergedBase }),
  });
  return handleResponse<import("./types").MergeIssueResult>(response);
}

export async function getCodexIssueDiff(
  issueId: string,
  statOnly = false,
): Promise<import("./types").IssueDiffResult> {
  const url = statOnly
    ? `${API_BASE}/codex/issues/${issueId}/diff?stat_only=true`
    : `${API_BASE}/codex/issues/${issueId}/diff`;
  const response = await fetch(url);
  return handleResponse<import("./types").IssueDiffResult>(response);
}

export interface WorkflowTemplateSummary {
  id: string;
  name: string;
  description: string;
  intent: string;
  role_order: string[];
}

export async function listWorkflowTemplates(): Promise<WorkflowTemplateSummary[]> {
  const response = await fetch(`${API_BASE}/codex/workflow-templates`);
  const data = await handleResponse<{ templates: WorkflowTemplateSummary[] }>(response);
  return data.templates;
}

export async function applyWorkflowTemplate(
  issueId: string,
  templateId: string,
): Promise<{ graph_id: string; template_id: string; nodes: number; edges: number }> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/apply-template`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ template_id: templateId }),
  });
  return handleResponse(response);
}

/** B1: inject a mid-run hint into the issue's worktree. The next dispatched
 *  agent picks it up via `_steer.md` and treats it as authoritative. */
/** S2-PR: open a GitHub PR for this issue. Devin-killer differentiator. */
export async function createGithubPR(
  issueId: string,
  opts: { title?: string; body?: string; draft?: boolean } = {},
): Promise<CodexIssue> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/pr/create`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: opts.title ?? null,
      body: opts.body ?? null,
      draft: opts.draft ?? false,
    }),
  });
  return handleResponse<CodexIssue>(response);
}

export async function refreshGithubPR(issueId: string): Promise<CodexIssue> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/pr/refresh`, {
    method: "POST",
  });
  return handleResponse<CodexIssue>(response);
}

export async function steerCodexIssue(issueId: string, message: string): Promise<{ ok: boolean }> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/steer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  return handleResponse<{ ok: boolean }>(response);
}

export async function abandonCodexIssue(issueId: string): Promise<CodexIssue> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/abandon`, { method: "POST" });
  return handleResponse<CodexIssue>(response);
}

export async function restoreCodexIssue(issueId: string): Promise<CodexIssue> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/restore`, { method: "POST" });
  return handleResponse<CodexIssue>(response);
}

export async function finalizeAbandonedCodexIssue(issueId: string): Promise<CodexIssue> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/abandon/finalize`, {
    method: "POST",
  });
  return handleResponse<CodexIssue>(response);
}

export async function pinCodexIssue(issueId: string, isPinned: boolean): Promise<CodexIssue> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/pin`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_pinned: isPinned }),
  });
  return handleResponse<CodexIssue>(response);
}

export async function duplicateCodexIssue(issueId: string): Promise<CodexIssue> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/duplicate`, { method: "POST" });
  return handleResponse<CodexIssue>(response);
}

/** B3: fork an issue from its CURRENT branch state. The new issue inherits
 * all in-progress commits so you can try an alternate direction without
 * losing the original work. */
export async function forkCodexIssue(issueId: string): Promise<CodexIssue> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/duplicate?from_current=true`, {
    method: "POST",
  });
  return handleResponse<CodexIssue>(response);
}

export async function getCodexIssue(issueId: string): Promise<CodexIssue> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}`);
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

export async function approveCodexIssuePlan(
  issueId: string,
  reviewComment: string,
): Promise<CodexIssue> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/approve-plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ review_comment: reviewComment }),
  });
  return handleResponse<CodexIssue>(response);
}

/** Human verdict on a QA-passed issue.
 * - approve → issue.status becomes "awaiting_merge"
 * - reject  → workflow scheduler resets the engineer node to pending and
 *             reruns. Bounded by engineer.max_retries.
 */
export async function qaReviewCodexIssue(
  issueId: string,
  decision: "approve" | "reject",
  comment: string | null,
): Promise<CodexIssue> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/qa-review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, comment }),
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

export interface IssueChecklist {
  criteria: { text: string; covered: boolean; source: string | null }[];
  qa_status: string | null;
  engineer_status: string | null;
}

export async function getCodexIssueChecklist(issueId: string): Promise<IssueChecklist> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/checklist`);
  return handleResponse<IssueChecklist>(response);
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

// Legacy transitionIssueTo{Architecture,Development,Testing} helpers removed
// in the DAG migration. Use planIssue / saveIssueGraph / startIssueGraph /
// the workflow scheduler endpoints instead.

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
  overrides?: { executor?: string | null; provider?: string | null; model?: string | null }
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
  executor?: string | null,
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

// --- Agents (PR1: Workflow DAG) ---

export async function listAgents(opts: { workspaceId?: string; roleKey?: string } = {}): Promise<Agent[]> {
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

// --- Workflow plan / graph (PR2 + PR3) ---

export async function planIssue(issueId: string): Promise<ProposedDAG> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/plan`, { method: "POST" });
  return handleResponse<ProposedDAG>(response);
}

export interface PlanStreamCallbacks {
  onMeta?: (meta: { executor: string | null; model: string | null; reason?: string }) => void;
  onLog?: (msg: string) => void;
  onChunk?: (text: string) => void;
  onNode?: (node: Record<string, unknown>) => void;
  onEdge?: (edge: Record<string, unknown>) => void;
  onDone?: (dag: ProposedDAG) => void;
  onError?: (msg: string) => void;
  signal?: AbortSignal;
}

export async function planIssueStream(issueId: string, cb: PlanStreamCallbacks): Promise<void> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/plan/stream`, {
    method: "POST",
    headers: { Accept: "text/event-stream" },
    signal: cb.signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(`stream failed: HTTP ${response.status}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE events terminated by blank line.
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;
      let payload: unknown;
      try {
        payload = JSON.parse(data);
      } catch {
        continue;
      }
      switch (event) {
        case "meta":
          cb.onMeta?.(payload as { executor: string | null; model: string | null; reason?: string });
          break;
        case "log":
          cb.onLog?.(String(payload));
          break;
        case "chunk":
          cb.onChunk?.((payload as { text: string }).text);
          break;
        case "node":
          cb.onNode?.(payload as Record<string, unknown>);
          break;
        case "edge":
          cb.onEdge?.(payload as Record<string, unknown>);
          break;
        case "done":
          cb.onDone?.((payload as { dag: ProposedDAG }).dag);
          break;
        case "error":
          cb.onError?.(String((payload as { message?: string }).message ?? payload));
          break;
      }
    }
  }
}

export async function getIssueGraph(issueId: string): Promise<WorkflowGraph | null> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/graph`);
  if (response.status === 404) return null;
  return handleResponse<WorkflowGraph>(response);
}

export async function saveIssueGraph(issueId: string, dag: ProposedDAG, createdBy = "user"): Promise<WorkflowGraph> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/graph`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dag, created_by: createdBy }),
  });
  return handleResponse<WorkflowGraph>(response);
}

export async function startIssueGraph(issueId: string): Promise<WorkflowGraph> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/graph/start`, { method: "POST" });
  return handleResponse<WorkflowGraph>(response);
}

export async function autoStartIssueGraph(issueId: string): Promise<WorkflowGraph> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/graph/auto-start`, { method: "POST" });
  return handleResponse<WorkflowGraph>(response);
}

export interface ReplanPending {
  id: string;
  graph_id: string;
  triggered_by_node_key: string;
  trigger_reason: string;
  diff: {
    added_nodes?: Array<{ node_key: string; role_key?: string; title?: string }>;
    added_edges?: Array<{ from_node_key: string; to_node_key: string; edge_type: string }>;
    removed_node_keys?: string[];
    rationale?: string;
  };
  rationale: string | null;
  status: string;
  created_at: string | null;
}

export async function listReplanPending(issueId: string): Promise<ReplanPending[]> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/graph/replan-pending`);
  return handleResponse<ReplanPending[]>(response);
}

export async function confirmReplan(issueId: string, replanId: string): Promise<WorkflowGraph> {
  const response = await fetch(
    `${API_BASE}/codex/issues/${issueId}/graph/replan/${replanId}/confirm`,
    { method: "POST" }
  );
  return handleResponse<WorkflowGraph>(response);
}

export async function rejectReplan(issueId: string, replanId: string): Promise<WorkflowGraph> {
  const response = await fetch(
    `${API_BASE}/codex/issues/${issueId}/graph/replan/${replanId}/reject`,
    { method: "POST" }
  );
  return handleResponse<WorkflowGraph>(response);
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
