// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, apiDedupedRequest, apiJsonRequest, apiRequest, apiRequestOr } from "./fetch";
import type {
  Artifact,
  CodexIssue,
  CodexTask,
  CreateIssueRequest,
  IssueDiffResult,
  MergeIssueResult,
  UpdateIssuePhaseRequest,
} from "../types";
import { autoStartIssueGraph } from "./conductors";

export async function mergeCodexIssue(
  issueId: string,
  message: string | null = null,
  allowDivergedBase = false,
): Promise<MergeIssueResult> {
  return apiJsonRequest<MergeIssueResult>(`${API_BASE}/codex/issues/${issueId}/merge`, "POST", {
    message,
    allow_diverged_base: allowDivergedBase,
  });
}
export async function getCodexIssueDiff(
  issueId: string,
  statOnly = false,
): Promise<IssueDiffResult> {
  const url = statOnly
    ? `${API_BASE}/codex/issues/${issueId}/diff?stat_only=true`
    : `${API_BASE}/codex/issues/${issueId}/diff`;
  return apiRequest<IssueDiffResult>(url);
}
/** B1: inject a mid-run hint into the issue's worktree. The next dispatched
 *  agent picks it up via `_steer.md` and treats it as authoritative. */
/** S2-PR: open a GitHub PR for this issue. Devin-killer differentiator. */
export async function createGithubPR(
  issueId: string,
  opts: { title?: string; body?: string; draft?: boolean } = {},
): Promise<CodexIssue> {
  return apiJsonRequest<CodexIssue>(`${API_BASE}/codex/issues/${issueId}/pr/create`, "POST", {
    title: opts.title ?? null,
    body: opts.body ?? null,
    draft: opts.draft ?? false,
  });
}
export async function refreshGithubPR(issueId: string): Promise<CodexIssue> {
  return apiRequest<CodexIssue>(`${API_BASE}/codex/issues/${issueId}/pr/refresh`, {
    method: "POST",
  });
}
export async function steerCodexIssue(issueId: string, message: string): Promise<{ ok: boolean }> {
  return apiJsonRequest<{ ok: boolean }>(`${API_BASE}/codex/issues/${issueId}/steer`, "POST", {
    message,
  });
}
export async function abandonCodexIssue(issueId: string): Promise<CodexIssue> {
  return apiRequest<CodexIssue>(`${API_BASE}/codex/issues/${issueId}/abandon`, {
    method: "POST",
  });
}
export async function restoreCodexIssue(issueId: string): Promise<CodexIssue> {
  return apiRequest<CodexIssue>(`${API_BASE}/codex/issues/${issueId}/restore`, {
    method: "POST",
  });
}
export async function finalizeAbandonedCodexIssue(issueId: string): Promise<CodexIssue> {
  return apiRequest<CodexIssue>(`${API_BASE}/codex/issues/${issueId}/abandon/finalize`, {
    method: "POST",
  });
}
export async function pinCodexIssue(issueId: string, isPinned: boolean): Promise<CodexIssue> {
  return apiJsonRequest<CodexIssue>(`${API_BASE}/codex/issues/${issueId}/pin`, "POST", {
    is_pinned: isPinned,
  });
}
export async function duplicateCodexIssue(issueId: string): Promise<CodexIssue> {
  return apiRequest<CodexIssue>(`${API_BASE}/codex/issues/${issueId}/duplicate`, {
    method: "POST",
  });
}
/** B3: fork an issue from its CURRENT branch state. The new issue inherits
 * all in-progress commits so you can try an alternate direction without
 * losing the original work. */
export async function forkCodexIssue(issueId: string): Promise<CodexIssue> {
  return apiRequest<CodexIssue>(`${API_BASE}/codex/issues/${issueId}/duplicate?from_current=true`, {
    method: "POST",
  });
}
export async function getCodexIssue(issueId: string): Promise<CodexIssue> {
  return apiDedupedRequest<CodexIssue>(`${API_BASE}/codex/issues/${issueId}`);
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
  return apiJsonRequest<CodexIssue>(`${API_BASE}/codex/issues`, "POST", body);
}
export async function approveCodexIssuePlan(
  issueId: string,
  reviewComment: string,
): Promise<CodexIssue> {
  return apiJsonRequest<CodexIssue>(`${API_BASE}/codex/issues/${issueId}/approve-plan`, "POST", {
    review_comment: reviewComment,
  });
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
  return apiJsonRequest<CodexIssue>(`${API_BASE}/codex/issues/${issueId}/qa-review`, "POST", {
    decision,
    comment,
  });
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
  return apiRequestOr<CodexIssue[]>(url, [], {
    errorMessage: (status) => `getCodexIssues failed: HTTP ${status}`,
  });
}
export interface IssueChecklist {
  criteria: { text: string; covered: boolean; source: string | null }[];
  qa_status: string | null;
  engineer_status: string | null;
}
export async function getCodexIssueChecklist(issueId: string): Promise<IssueChecklist> {
  return apiDedupedRequest<IssueChecklist>(`${API_BASE}/codex/issues/${issueId}/checklist`);
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
  return apiRequestOr<PipelineStagesResponse | null>(
    `${API_BASE}/codex/issues/${issueId}/pipeline-stages`,
    null,
    {
      dedupe: true,
      errorMessage: (status) => `getIssuePipelineStages(${issueId}) failed: HTTP ${status}`,
    },
  );
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
  return apiRequestOr<ActivityResponse | null>(
    `${API_BASE}/codex/issues/${issueId}/activity?limit=${limit}`,
    null,
    {
      dedupe: true,
      errorMessage: (status) => `getIssueActivity(${issueId}) failed: HTTP ${status}`,
    },
  );
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
export async function getIssueGraphStats(issueId: string): Promise<GraphStatsResponse | null> {
  return apiRequestOr<GraphStatsResponse | null>(
    `${API_BASE}/codex/issues/${issueId}/graph-stats`,
    null,
    {
      dedupe: true,
      errorMessage: (status) => `getIssueGraphStats(${issueId}) failed: HTTP ${status}`,
    },
  );
}
export async function getCodexIssueArtifacts(issueId: string): Promise<Artifact[]> {
  return apiRequestOr<Artifact[]>(`${API_BASE}/codex/issues/${issueId}/artifacts`, [], {
    errorMessage: (status) => `getCodexIssueArtifacts(${issueId}) failed: HTTP ${status}`,
  });
}
export async function updateCodexIssuePhase(
  issueId: string,
  currentPhase: string,
): Promise<CodexIssue> {
  const body: UpdateIssuePhaseRequest = { current_phase: currentPhase };
  return apiJsonRequest<CodexIssue>(`${API_BASE}/codex/issues/${issueId}/phase`, "POST", body);
}

export interface TransitionIssueToArchitectureResult {
  issue: CodexIssue;
  task: CodexTask | null;
}

export interface TransitionIssueToDevelopmentResult {
  issue: CodexIssue;
  tasks: CodexTask[];
}

export interface TransitionIssueToTestingResult {
  issue: CodexIssue;
  task: CodexTask | null;
}

async function transitionIssueViaGraph(issueId: string, phase: string): Promise<CodexIssue> {
  const issue = await updateCodexIssuePhase(issueId, phase);
  await autoStartIssueGraph(issueId);
  return issue;
}

export async function transitionIssueToArchitecture(
  issueId: string,
): Promise<TransitionIssueToArchitectureResult> {
  return {
    issue: await transitionIssueViaGraph(issueId, "architecture"),
    task: null,
  };
}

export async function transitionIssueToDevelopment(
  issueId: string,
): Promise<TransitionIssueToDevelopmentResult> {
  return {
    issue: await transitionIssueViaGraph(issueId, "development"),
    tasks: [],
  };
}

export async function transitionIssueToTesting(
  issueId: string,
): Promise<TransitionIssueToTestingResult> {
  return {
    issue: await transitionIssueViaGraph(issueId, "testing"),
    task: null,
  };
}
export async function deleteCodexIssue(issueId: string): Promise<unknown> {
  return apiRequest<unknown>(`${API_BASE}/codex/issues/${issueId}`, {
    method: "DELETE",
  });
}
export async function updateCodexIssue(
  issueId: string,
  updates: { title?: string; description?: string },
): Promise<CodexIssue> {
  return apiJsonRequest<CodexIssue>(`${API_BASE}/codex/issues/${issueId}`, "PATCH", updates);
}
export async function exportCodexIssues(
  sessionId: string | null = null,
  format: "csv" | "json" = "json",
): Promise<string> {
  const params = new URLSearchParams();
  if (sessionId) params.set("session_id", sessionId);
  const query = params.toString();
  const url = query
    ? `${API_BASE}/codex/issues/export?${query}`
    : `${API_BASE}/codex/issues/export`;
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
export async function importCodexIssues(
  sessionId: string,
  data: string,
  format: "csv" | "json",
): Promise<CodexIssue[]> {
  const formData = new FormData();
  formData.append("data", data);
  formData.append("format", format);
  return apiRequest<CodexIssue[]>(
    `${API_BASE}/codex/issues/import?session_id=${encodeURIComponent(sessionId)}`,
    {
      method: "POST",
      body: formData,
    },
  );
}
export async function bulkUpdateIssues(
  issueIds: string[],
  updates: { current_phase?: string; status?: string },
): Promise<CodexIssue[]> {
  return apiJsonRequest<CodexIssue[]>(`${API_BASE}/codex/issues/bulk-update`, "POST", {
    issue_ids: issueIds,
    updates,
  });
}
export async function bulkDeleteIssues(issueIds: string[]): Promise<void> {
  return apiJsonRequest<void>(`${API_BASE}/codex/issues/bulk-delete`, "POST", {
    issue_ids: issueIds,
  });
}
// Per-issue: artifacts zip (graph-stats helper already exists above)
export function getIssueArtifactsDownloadUrl(issueId: string): string {
  return `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/artifacts/download`;
}
