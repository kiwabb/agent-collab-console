// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, dedupedFetch, handleResponse } from "./fetch";
import type { CodexStats, IssueBudgetStatus, IssueOrchestrationPolicy } from "../types";

export async function getCodexStats(): Promise<import("../types").CodexStats> {
  const response = await fetch(`${API_BASE}/codex/stats`);
  return handleResponse<import("../types").CodexStats>(response);
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
export async function getCodexCostStats(
  opts: {
    issueId?: string | null;
    workspaceId?: string | null;
  } = {},
): Promise<CodexCostStats> {
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
): Promise<import("../types").IssueBudgetStatus | null> {
  const response = await dedupedFetch(`${API_BASE}/codex/issues/${issueId}/budget`);
  if (!response.ok) {
    console.error(`getIssueBudget(${issueId}) failed: HTTP ${response.status}`);
    return null;
  }
  return response.json() as Promise<import("../types").IssueBudgetStatus>;
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
