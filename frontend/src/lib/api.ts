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
  ProjectConductorAskResult,
  ProjectConductorLoopResult,
  ProjectConductorState,
  GitBranch,
  Agent,
  CreateAgentRequest,
  UpdateAgentRequest,
  WorkflowGraph,
  IssueOrchestrationPolicy,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api";
const WS_BASE = process.env.NEXT_PUBLIC_WS_BASE ?? "ws://localhost:9000";

export { API_BASE, WS_BASE };

interface ApiValidationError {
  loc?: unknown;
  msg?: unknown;
}

export function formatApiErrorDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (!item || typeof item !== "object") return String(item);
      const error = item as ApiValidationError;
      const loc = Array.isArray(error.loc)
        ? error.loc.map((part) => String(part)).join(".")
        : typeof error.loc === "string"
          ? error.loc
          : "";
      const msg = typeof error.msg === "string" ? error.msg : "";
      if (loc && msg) return `${loc}: ${msg}`;
      return msg || loc || JSON.stringify(item);
    }).filter(Boolean);
    if (parts.length > 0) return parts.join("; ");
  }
  return fallback;
}

/**
 * Short-window GET dedupe. When multiple components ask for the same URL
 * within `ttlMs`, they share one in-flight Promise instead of each firing
 * its own request. Cuts the 80+ XHR storm on the issue detail page
 * (pipeline-stages × 12, graph × 13, tasks × 15, etc) down to ~10.
 *
 * Only applies to GETs. POST/PUT/DELETE bypass — those mutate state.
 */
const _dedupeCache = new Map<string, { promise: Promise<Response>; expires: number }>();
const _DEDUPE_TTL_MS = 1500;
export async function dedupedFetch(
  url: string,
  init?: RequestInit,
): Promise<Response> {
  // Bypass dedupe for non-GET — those have side effects.
  const method = (init?.method ?? "GET").toUpperCase();
  if (method !== "GET") {
    return fetch(url, init);
  }
  const now = Date.now();
  const key = url;
  const cached = _dedupeCache.get(key);
  if (cached && cached.expires > now) {
    // Clone is required because Response bodies can only be read once.
    return cached.promise.then((r) => r.clone());
  }
  const p = fetch(url, init);
  _dedupeCache.set(key, { promise: p, expires: now + _DEDUPE_TTL_MS });
  // Garbage-collect after TTL so stale errors don't linger.
  p.finally(() => {
    const c = _dedupeCache.get(key);
    if (c && c.expires <= Date.now()) _dedupeCache.delete(key);
  });
  return p.then((r) => r.clone());
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let errorMessage = `HTTP ${response.status}`;
    try {
      const err = await response.json();
      errorMessage = formatApiErrorDetail((err as { detail?: unknown }).detail, errorMessage);
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

export async function getProjectRemoteStatus(
  projectId: string,
  options: { fetch?: boolean } = {},
): Promise<import("./types").ProjectRemoteStatus> {
  const doFetch = options.fetch ?? true;
  const response = await fetch(
    `${API_BASE}/projects/${projectId}/remote-status?fetch=${doFetch ? "true" : "false"}`,
  );
  return handleResponse<import("./types").ProjectRemoteStatus>(response);
}

export async function pullProject(
  projectId: string,
): Promise<import("./types").ProjectPullResult> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/pull`, { method: "POST" });
  // 200 → the ProjectPullResult directly. 409 → FastAPI wraps our refusal
  // payload as {detail: ProjectPullResult}. Both carry the structured reason we
  // want to show, so unwrap them here rather than throwing on 409.
  if (response.status === 200) {
    return (await response.json()) as import("./types").ProjectPullResult;
  }
  if (response.status === 409) {
    const body = (await response.json()) as { detail: import("./types").ProjectPullResult };
    return body.detail;
  }
  // 404 / 500 etc. are genuine errors — surface them.
  return handleResponse<import("./types").ProjectPullResult>(response);
}

// --- Project run (one-click dev server) APIs ---

/**
 * Result of starting a project's run_command. On success the live
 * {@link ProjectRunStatus} is returned. On a 409 refusal we unwrap FastAPI's
 * `{detail: {reason, pattern?}}` into `{error, pattern?}` so the caller can
 * branch on the reason without catching a thrown error.
 */
export type StartProjectRunResult =
  | import("./types").ProjectRunStatus
  | { error: import("./types").ProjectRunStartReason; pattern?: string };

export function isProjectRunStartError(
  result: StartProjectRunResult,
): result is { error: import("./types").ProjectRunStartReason; pattern?: string } {
  return "error" in result;
}

export async function startProjectRun(projectId: string): Promise<StartProjectRunResult> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/run/start`, { method: "POST" });
  if (response.status === 200) {
    return (await response.json()) as import("./types").ProjectRunStatus;
  }
  if (response.status === 409) {
    // FastAPI wraps the refusal payload as {detail: {reason, pattern?}}.
    const body = (await response.json()) as {
      detail: { reason: import("./types").ProjectRunStartReason; pattern?: string };
    };
    return { error: body.detail.reason, pattern: body.detail.pattern };
  }
  // 404 / 500 etc. are genuine errors — surface them.
  return handleResponse<import("./types").ProjectRunStatus>(response);
}

export async function stopProjectRun(projectId: string): Promise<import("./types").ProjectRunStatus> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/run/stop`, { method: "POST" });
  return handleResponse<import("./types").ProjectRunStatus>(response);
}

export async function getProjectRunStatus(projectId: string): Promise<import("./types").ProjectRunStatus> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/run/status`);
  return handleResponse<import("./types").ProjectRunStatus>(response);
}

export async function getProjectRunLogs(
  projectId: string,
  after = 0,
): Promise<import("./types").ProjectRunLogsResponse> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/run/logs?after=${after}`);
  return handleResponse<import("./types").ProjectRunLogsResponse>(response);
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

export async function scheduleProjectConductorReview(projectId: string): Promise<ProjectConductorAskResult> {
  const response = await fetch(`${API_BASE}/codex/projects/${projectId}/conductor/schedule-review`, {
    method: "POST",
  });
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
  const response = await dedupedFetch(`${API_BASE}/codex/cost-stats${qs ? `?${qs}` : ""}`);
  return handleResponse<CodexCostStats>(response);
}

/**
 * Per-issue budget snapshot from `GET /codex/issues/{id}/budget`.
 *
 * Returns `null` on any failure (404 / 503 / network) so callers can render a
 * graceful "no data" branch without exception plumbing.
 */
export async function getIssueBudget(
  issueId: string,
): Promise<import("./types").IssueBudgetStatus | null> {
  const response = await dedupedFetch(`${API_BASE}/codex/issues/${issueId}/budget`);
  if (!response.ok) {
    console.error(`getIssueBudget(${issueId}) failed: HTTP ${response.status}`);
    return null;
  }
  return response.json() as Promise<import("./types").IssueBudgetStatus>;
}

export async function getIssueOrchestrationPolicy(
  issueId: string,
): Promise<IssueOrchestrationPolicy | null> {
  const response = await dedupedFetch(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/orchestration-policy`,
  );
  if (!response.ok) {
    console.error(`getIssueOrchestrationPolicy(${issueId}) failed: HTTP ${response.status}`);
    return null;
  }
  return response.json() as Promise<IssueOrchestrationPolicy>;
}

// ---------------------------------------------------------------------------
// Benchmark harness (PR4)
// ---------------------------------------------------------------------------
// All endpoints return `T | null` on failure so the page renders a
// "no data" branch without exception plumbing. ``triggerBenchmarkRun`` is
// the one exception: it returns the job id on a 202, and throws on 4xx so
// the form can surface the validation error inline.
// ---------------------------------------------------------------------------

export async function listBenchmarkRuns(
  limit = 50,
): Promise<import("./types").BenchmarkRun[]> {
  const response = await dedupedFetch(
    `${API_BASE}/codex/benchmark/runs?limit=${limit}`,
  );
  if (!response.ok) {
    console.error(`listBenchmarkRuns failed: HTTP ${response.status}`);
    return [];
  }
  const body = await response.json();
  return (body.runs ?? []) as import("./types").BenchmarkRun[];
}

export async function getBenchmarkRun(
  runId: string,
): Promise<import("./types").BenchmarkRun | null> {
  const response = await dedupedFetch(
    `${API_BASE}/codex/benchmark/runs/${runId}`,
  );
  if (!response.ok) {
    console.error(`getBenchmarkRun(${runId}) failed: HTTP ${response.status}`);
    return null;
  }
  return response.json() as Promise<import("./types").BenchmarkRun>;
}

export async function getBenchmarkRunDiff(
  runId: string,
): Promise<import("./types").BenchmarkDiff | null> {
  const response = await dedupedFetch(
    `${API_BASE}/codex/benchmark/runs/${runId}/diff`,
  );
  if (!response.ok) {
    console.error(`getBenchmarkRunDiff(${runId}) failed: HTTP ${response.status}`);
    return null;
  }
  return response.json() as Promise<import("./types").BenchmarkDiff>;
}

export interface TriggerBenchmarkBody {
  label?: string;
  epochs?: number;
  fixture_ids?: string[];
  is_baseline?: boolean;
  max_budget_usd?: number;
  project_id?: string;
  workspace_id?: string;
  dry_run?: boolean;
}

export interface TriggerBenchmarkResponse {
  job_id: string;
  status: import("./types").BenchmarkJobStatus;
  status_url: string;
}

export async function triggerBenchmarkRun(
  body: TriggerBenchmarkBody,
): Promise<TriggerBenchmarkResponse> {
  const response = await fetch(`${API_BASE}/codex/benchmark/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(
      `triggerBenchmarkRun failed: HTTP ${response.status} — ${JSON.stringify(detail.detail)}`,
    );
  }
  return response.json() as Promise<TriggerBenchmarkResponse>;
}

export async function getBenchmarkJob(
  jobId: string,
): Promise<import("./types").BenchmarkJob | null> {
  const response = await dedupedFetch(
    `${API_BASE}/codex/benchmark/jobs/${jobId}`,
  );
  if (!response.ok) {
    console.error(`getBenchmarkJob(${jobId}) failed: HTTP ${response.status}`);
    return null;
  }
  return response.json() as Promise<import("./types").BenchmarkJob>;
}

export async function getBaselineRun(): Promise<import("./types").BenchmarkRun | null> {
  const response = await dedupedFetch(`${API_BASE}/codex/benchmark/baseline`);
  if (!response.ok) {
    console.error(`getBaselineRun failed: HTTP ${response.status}`);
    return null;
  }
  const body = await response.json();
  return (body.baseline ?? null) as import("./types").BenchmarkRun | null;
}

export async function setBaselineRun(runId: string): Promise<boolean> {
  const response = await fetch(
    `${API_BASE}/codex/benchmark/baseline/${runId}`,
    { method: "POST" },
  );
  if (!response.ok) {
    console.error(`setBaselineRun(${runId}) failed: HTTP ${response.status}`);
    return false;
  }
  return true;
}

export async function getCalibrationReport(
  floor = 0.7,
): Promise<import("./types").CalibrationReport | null> {
  const response = await dedupedFetch(
    `${API_BASE}/codex/benchmark/calibration?floor=${floor}`,
  );
  if (!response.ok) {
    console.error(`getCalibrationReport failed: HTTP ${response.status}`);
    return null;
  }
  return response.json() as Promise<import("./types").CalibrationReport>;
}

export async function getProjectAudit(
  projectId: string,
  limit = 10,
): Promise<import("./types").ProjectAuditEntry[]> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/audit?limit=${limit}`);
  return handleResponse<import("./types").ProjectAuditEntry[]>(response);
}

export type AuditLogCategory =
  | "llm_call"
  | "llm_return"
  | "tool_use"
  | "tool_result"
  | "command_exec"
  | "git_command"
  | "cli_spawn"
  | "event"
  | "agent_finalize";

export interface AuditLog {
  id: string;
  created_at: string | null;
  category: string;
  actor: string | null;
  issue_id: string | null;
  task_id: string | null;
  conductor_task_id: string | null;
  execution_process_id: string | null;
  correlation_id: string | null;
  status: string | null;
  duration_ms: number | null;
  /** Raw (already-truncated) JSON string; parse on the client. */
  payload_json: string | null;
  error: string | null;
}

export interface AuditLogPage {
  items: AuditLog[];
  next_cursor: string | null;
}

export async function getAuditLog(params: {
  category?: string[] | null;
  issueId?: string | null;
  taskId?: string | null;
  since?: string | null;
  until?: string | null;
  q?: string | null;
  cursor?: string | null;
  limit?: number | null;
} = {}): Promise<AuditLogPage> {
  const search = new URLSearchParams();
  for (const cat of params.category ?? []) {
    if (cat) search.append("category", cat);
  }
  if (params.issueId) search.set("issue_id", params.issueId);
  if (params.taskId) search.set("task_id", params.taskId);
  if (params.since) search.set("since", params.since);
  if (params.until) search.set("until", params.until);
  if (params.q) search.set("q", params.q);
  if (params.cursor) search.set("cursor", params.cursor);
  if (params.limit != null) search.set("limit", String(params.limit));
  const qs = search.toString();
  const response = await fetch(`${API_BASE}/codex/audit-log${qs ? `?${qs}` : ""}`);
  return handleResponse<AuditLogPage>(response);
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
  const response = await dedupedFetch(`${API_BASE}/codex/issues/${issueId}`);
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
  executor: string | null = null,
  provider: string | null = null,
  model: string | null = null,
): Promise<CodexIssue> {
  const body: CreateIssueRequest = { session_id: sessionId, title, description };
  if (baseBranch) body.base_branch = baseBranch;
  if (executor) body.executor = executor;
  if (provider) body.provider = provider;
  if (model) body.model = model;
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
  const response = await dedupedFetch(`${API_BASE}/codex/issues/${issueId}/checklist`);
  return handleResponse<IssueChecklist>(response);
}

export interface PipelineStage {
  role: "product_manager" | "architect" | "engineer" | "qa" | string;
  label: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  summary: string;
  foot: string;
  task_id: string | null;
}

export interface PipelineStagesResponse {
  stages: PipelineStage[];
  started_at: string | null;
  completed_at: string | null;
  total_duration_seconds: number | null;
}

export async function getIssuePipelineStages(
  issueId: string,
): Promise<PipelineStagesResponse | null> {
  const response = await dedupedFetch(`${API_BASE}/codex/issues/${issueId}/pipeline-stages`);
  if (!response.ok) {
    console.error(`getIssuePipelineStages(${issueId}) failed: HTTP ${response.status}`);
    return null;
  }
  return response.json();
}

export interface ActivityEvent {
  type: string;
  timestamp: string;
  actor: string;
  role: string | null;
  text: string;
  aux: string | null;
}

export interface ActivityResponse {
  events: ActivityEvent[];
}

export async function getIssueActivity(
  issueId: string,
  limit = 50,
): Promise<ActivityResponse | null> {
  const response = await dedupedFetch(
    `${API_BASE}/codex/issues/${issueId}/activity?limit=${limit}`,
  );
  if (!response.ok) {
    console.error(`getIssueActivity(${issueId}) failed: HTTP ${response.status}`);
    return null;
  }
  return response.json();
}

export interface GraphNodeSummaryStat {
  num: number;
  label: string;
  tone?: "good" | "bad" | null;
}

export interface GraphNodeStat {
  task_id: string | null;
  role_key: string;
  tokens: { input: number; output: number; total: number } | null;
  duration_seconds: number | null;
  tools: string[];
  est_cost_usd: number | null;
  summary_stats?: GraphNodeSummaryStat[];
}

export interface GraphStatsResponse {
  nodes: Record<string, GraphNodeStat>;
  conductor: GraphNodeStat;
}

export async function getIssueGraphStats(
  issueId: string,
): Promise<GraphStatsResponse | null> {
  const response = await dedupedFetch(`${API_BASE}/codex/issues/${issueId}/graph-stats`);
  if (!response.ok) {
    console.error(`getIssueGraphStats(${issueId}) failed: HTTP ${response.status}`);
    return null;
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

// --- Workflow graph (Conductor-driven) ---

export async function getIssueGraph(issueId: string): Promise<WorkflowGraph | null> {
  const response = await dedupedFetch(`${API_BASE}/codex/issues/${issueId}/graph`);
  if (response.status === 404) return null;
  return handleResponse<WorkflowGraph>(response);
}

export async function autoStartIssueGraph(issueId: string): Promise<WorkflowGraph> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/graph/auto-start`, { method: "POST" });
  return handleResponse<WorkflowGraph>(response);
}

export async function restartConductor(issueId: string): Promise<WorkflowGraph> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/conductor/restart`, { method: "POST" });
  return handleResponse<WorkflowGraph>(response);
}

export async function resetIssue(issueId: string): Promise<WorkflowGraph> {
  const response = await fetch(`${API_BASE}/codex/issues/${issueId}/reset`, { method: "POST" });
  return handleResponse<WorkflowGraph>(response);
}

// WebSocket URL builders
export function getWorkspaceStreamUrl(workspaceId: string): string {
  return `${WS_BASE}/api/workspaces/${workspaceId}/execution_processes/ws`;
}

export function getGlobalEventsStreamUrl(lastEventId?: string | null): string {
  const sp = new URLSearchParams();
  if (lastEventId) sp.set("last_event_id", lastEventId);
  const suffix = sp.size > 0 ? `?${sp.toString()}` : "";
  return `${WS_BASE}/api/ws/events${suffix}`;
}

export function getProcessLogsUrl(processId: string): string {
  return `${WS_BASE}/api/execution-processes/${processId}/logs/ws`;
}

export function getProcessMessagesUrl(processId: string): string {
  return `${WS_BASE}/api/execution-processes/${processId}/messages/ws`;
}

// ----------------------------------------------------------------------------
// Knowledge stack: cross-issue search, similar issues, team-notes CRUD
// ----------------------------------------------------------------------------

export type KnowledgeSearchScope = "all" | "issues" | "artifacts";
export type KnowledgeSearchMode = "fts" | "semantic" | "hybrid";

export interface KnowledgeIssueHit {
  kind: "issue";
  issue_id: string;
  project_id: string | null;
  title: string;
  snippet?: string;
  score?: number;
  source?: string;
  rrf?: number;
}

export interface KnowledgeArtifactHit {
  kind: "artifact";
  artifact_id: string;
  issue_id: string;
  project_id: string | null;
  role: string;
  name: string;
  snippet?: string;
  score?: number;
  source?: string;
  rrf?: number;
}

export interface KnowledgeSearchResponse {
  issues: KnowledgeIssueHit[];
  artifacts: KnowledgeArtifactHit[];
  mode: KnowledgeSearchMode;
  query: string;
}

export async function searchKnowledge(opts: {
  q: string;
  scope?: KnowledgeSearchScope;
  projectId?: string;
  mode?: KnowledgeSearchMode;
  limit?: number;
}): Promise<KnowledgeSearchResponse> {
  const params = new URLSearchParams({ q: opts.q });
  if (opts.scope) params.set("scope", opts.scope);
  if (opts.projectId) params.set("project_id", opts.projectId);
  if (opts.mode) params.set("mode", opts.mode);
  if (typeof opts.limit === "number") params.set("limit", String(opts.limit));
  const response = await fetch(`${API_BASE}/codex/search?${params.toString()}`);
  return handleResponse(response);
}

export interface SimilarIssue {
  issue_id: string;
  title: string;
  project_id: string | null;
  score?: number;
  source?: string;
}

export async function getSimilarIssues(issueId: string, k = 5): Promise<SimilarIssue[]> {
  const response = await fetch(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/similar?k=${k}`
  );
  const data = await handleResponse<{ items: SimilarIssue[] }>(response);
  return data.items ?? [];
}

export interface EmbeddingStatus {
  enabled: boolean;
  model: string | null;
  provider_type: string | null;
}

export async function getEmbeddingStatus(): Promise<EmbeddingStatus> {
  const response = await fetch(`${API_BASE}/codex/embedding/status`);
  return handleResponse(response);
}

export async function triggerKnowledgeReindex(projectId?: string): Promise<{
  indexed_issues: number;
  indexed_artifacts: number;
  embedded_issues: number;
  embedded_artifacts: number;
}> {
  const url = projectId
    ? `${API_BASE}/codex/index/reindex?project_id=${encodeURIComponent(projectId)}`
    : `${API_BASE}/codex/index/reindex`;
  const response = await fetch(url, { method: "POST" });
  return handleResponse(response);
}

export interface TeamNoteBlock {
  block_id: string;
  issue_id: string | null;
  heading: string;
  body: string;
  timestamp: string | null;
  pinned: boolean;
  deleted_at: string | null;
  distilled: boolean;
}

export interface TeamNotesResponse {
  project_id: string;
  raw_markdown: string;
  blocks: TeamNoteBlock[];
}

export async function getTeamNotes(
  projectId: string,
  includeDeleted = false
): Promise<TeamNotesResponse> {
  const params = new URLSearchParams();
  if (includeDeleted) params.set("include_deleted", "true");
  const response = await fetch(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/team-notes?${params.toString()}`
  );
  return handleResponse(response);
}

export async function deleteTeamNotesBlock(
  projectId: string,
  blockId: string
): Promise<void> {
  const response = await fetch(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/team-notes/${encodeURIComponent(blockId)}`,
    { method: "DELETE" }
  );
  await handleResponse(response);
}

export async function restoreTeamNotesBlock(
  projectId: string,
  blockId: string
): Promise<void> {
  const response = await fetch(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/team-notes/${encodeURIComponent(blockId)}/restore`,
    { method: "POST" }
  );
  await handleResponse(response);
}

export async function pinTeamNotesBlock(
  projectId: string,
  blockId: string,
  pinned: boolean
): Promise<void> {
  const response = await fetch(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/team-notes/${encodeURIComponent(blockId)}/pin`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pinned }),
    }
  );
  await handleResponse(response);
}

// Per-issue: artifacts zip (graph-stats helper already exists above)
export function getIssueArtifactsDownloadUrl(issueId: string): string {
  return `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/artifacts/download`;
}

export interface AgentMessage {
  id: string;
  issue_id: string;
  graph_id: string;
  from_node_key: string;
  to_node_key: string;
  message_type: "handoff" | "critique" | "clarification" | "answer" | "specialist_call" | "specialist_result";
  body: string;
  created_at: string | null;
}

export async function getAgentMessages(issueId: string): Promise<AgentMessage[]> {
  const res = await fetch(`${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/agent-messages`);
  if (!res.ok) return [];
  const data = (await res.json()) as { messages: AgentMessage[] };
  return data.messages ?? [];
}

export interface ConductorDecision {
  id: string;
  issue_id: string;
  task_id: string;
  action: "proceed" | "note" | "escalate" | "reroute" | "insert_node" | "request_clarification";
  reason: string | null;
  diff_json: string | null;
  applied_at: string | null;
  created_at: string | null;
}

export async function getConductorLog(issueId: string): Promise<ConductorDecision[]> {
  const res = await fetch(`${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor-log`);
  if (!res.ok) return [];
  const data = (await res.json()) as { decisions: ConductorDecision[] };
  return data.decisions ?? [];
}

export interface ConductorTurn {
  id: string;
  conductor_task_id: string;
  issue_id: string;
  turn_index: number;
  sub_index: number;
  kind: "llm_request" | "llm_response" | "tool_use" | "tool_result" | "user_message" | "error" | "finalize";
  payload: Record<string, unknown>;
  created_at: string | null;
  consumed_at?: string | null;
}

export async function getConductorTurns(
  issueId: string,
  opts?: { conductorTaskId?: string; limit?: number },
): Promise<ConductorTurn[]> {
  const sp = new URLSearchParams();
  if (opts?.conductorTaskId) sp.set("conductor_task_id", opts.conductorTaskId);
  if (opts?.limit) sp.set("limit", String(opts.limit));
  const suffix = sp.size > 0 ? `?${sp.toString()}` : "";
  const res = await fetch(`${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor-turns${suffix}`);
  if (!res.ok) return [];
  const data = (await res.json()) as { turns: ConductorTurn[] };
  return data.turns ?? [];
}

export interface ConductorStatePayload {
  issue_id: string;
  conductor_task_id?: string | null;
  conductor_status?: string | null;
  phase?: string | null;
  detail?: string | null;
  running_thread: Array<{
    task_id: string;
    completed_node_key: string;
    action: string;
    reason?: string | null;
    note?: string | null;
    created_at: string;
  }>;
  pending_dispatches: Array<{
    action: string;
    target_node_key?: string | null;
    prompt_override?: string | null;
    context_inject?: string | null;
    context_message?: string | null;
    reason?: string | null;
  }>;
  scratchpad: string;
  decision_count: number;
  updated_at?: string | null;
}

export interface ConductorStateLogEntry {
  id: string;
  issue_id: string;
  from_phase: string | null;
  to_phase: string;
  from_detail: string | null;
  to_detail: string | null;
  transition_at: string | null;
  duration_ms: number | null;
  is_legal: boolean;
}

export interface ConductorPhaseEstimate {
  p50_ms: number | null;
  p95_ms: number | null;
  n_samples: number;
}

export async function getConductorState(issueId: string): Promise<ConductorStatePayload | null> {
  const res = await fetch(`${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor-state`);
  if (!res.ok) return null;
  return (await res.json()) as ConductorStatePayload;
}

export async function getConductorStateLog(
  issueId: string,
  opts?: { limit?: number },
): Promise<ConductorStateLogEntry[]> {
  const sp = new URLSearchParams();
  if (opts?.limit) sp.set("limit", String(opts.limit));
  const suffix = sp.size > 0 ? `?${sp.toString()}` : "";
  const res = await fetch(`${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor-state-log${suffix}`);
  if (!res.ok) return [];
  const data = (await res.json()) as { entries: ConductorStateLogEntry[] };
  return data.entries ?? [];
}

export async function getConductorPhaseEstimates(issueId: string): Promise<Record<string, ConductorPhaseEstimate>> {
  const res = await fetch(`${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor-phase-estimates`);
  if (!res.ok) return {};
  const data = (await res.json()) as { estimates: Record<string, ConductorPhaseEstimate> };
  return data.estimates ?? {};
}

export async function sendConductorMessage(issueId: string, message: string): Promise<{ ok: boolean; status: string; conductor_task_id: string }> {
  const response = await fetch(`${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  return handleResponse(response);
}

export async function pauseConductor(issueId: string): Promise<{ ok: boolean; status: string; conductor_task_id: string }> {
  const response = await fetch(`${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor/pause`, {
    method: "POST",
  });
  return handleResponse(response);
}

export async function resumeConductor(issueId: string): Promise<{ ok: boolean; status: string; conductor_task_id: string }> {
  const response = await fetch(`${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/conductor/resume`, {
    method: "POST",
  });
  return handleResponse(response);
}

export interface SubAgentResultPayload {
  task_id: string;
  role: string;
  title: string;
  status: string;
  task_kind: string;
  parent_task_id: string | null;
  summary: string;
  artifact_json: Record<string, unknown> | null;
  updated_at: string | null;
}

export async function getSubAgentResults(issueId: string): Promise<SubAgentResultPayload[]> {
  const response = await fetch(`${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/subagent-results`);
  return handleResponse<SubAgentResultPayload[]>(response);
}

export async function getAgentMesh(issueId: string): Promise<AgentMessage[]> {
  const response = await fetch(`${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/agent-mesh`);
  return handleResponse<AgentMessage[]>(response);
}

export async function appendConductorMessage(projectId: string, message: string): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE}/codex/projects/${encodeURIComponent(projectId)}/conductor/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  return handleResponse<{ status: string }>(response);
}

// --- Skills library ---

export async function listSkills(opts: { search?: string; category?: string } = {}): Promise<import("./types").Skill[]> {
  const params = new URLSearchParams();
  if (opts.search) params.set("search", opts.search);
  if (opts.category) params.set("category", opts.category);
  const qs = params.toString();
  const response = await fetch(`${API_BASE}/skills${qs ? `?${qs}` : ""}`);
  return handleResponse(response);
}

export async function listSkillCategories(): Promise<string[]> {
  const response = await fetch(`${API_BASE}/skills/categories`);
  return handleResponse(response);
}

export async function createSkillCategory(name: string): Promise<{ name: string }> {
  const response = await fetch(`${API_BASE}/skills/categories`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  return handleResponse(response);
}

export async function deleteSkillCategory(name: string, force = false): Promise<void> {
  const url = new URL(`${API_BASE}/skills/categories/${encodeURIComponent(name)}`, window.location.origin);
  if (force) url.searchParams.set("force", "true");
  const response = await fetch(url.toString(), { method: "DELETE" });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(text || `HTTP ${response.status}`);
  }
}

export async function createSkill(body: import("./types").CreateSkillRequest): Promise<import("./types").Skill> {
  const response = await fetch(`${API_BASE}/skills`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse(response);
}

export async function updateSkill(skillId: string, body: import("./types").UpdateSkillRequest): Promise<import("./types").Skill> {
  const response = await fetch(`${API_BASE}/skills/${encodeURIComponent(skillId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse(response);
}

export async function deleteSkill(skillId: string): Promise<{ deleted: string }> {
  const response = await fetch(`${API_BASE}/skills/${encodeURIComponent(skillId)}`, { method: "DELETE" });
  return handleResponse(response);
}

export async function importSkillsMarkdown(files: File[]): Promise<import("./types").SkillImportResult> {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  const response = await fetch(`${API_BASE}/skills/import/md`, { method: "POST", body: fd });
  return handleResponse(response);
}

export async function importSkillsExcel(file: File): Promise<import("./types").SkillImportResult> {
  const fd = new FormData();
  fd.append("file", file);
  const response = await fetch(`${API_BASE}/skills/import/excel`, { method: "POST", body: fd });
  return handleResponse(response);
}

export async function fetchSkillContent(url: string): Promise<string> {
  const response = await fetch(`${API_BASE}/skills/proxy?url=${encodeURIComponent(url)}`);
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.text();
}

export interface TranslateSkillResult {
  translated: string;
  target: "zh" | "en";
  truncated: boolean;
  model: string;
}

export async function translateSkillContent(
  text: string,
  target: "zh" | "en",
): Promise<TranslateSkillResult> {
  const response = await fetch(`${API_BASE}/skills/translate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, target }),
  });
  return handleResponse(response);
}
