// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, apiDedupedRequest, apiRequest, apiRequestOr } from "./fetch";
import type { CodexStats, IssueBudgetStatus, IssueOrchestrationPolicy } from "../types";

export async function getCodexStats(): Promise<CodexStats> {
  return apiRequest<CodexStats>(`${API_BASE}/codex/stats`);
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
  return apiDedupedRequest<CodexCostStats>(`${API_BASE}/codex/cost-stats${qs ? `?${qs}` : ""}`);
}
/**
 * Per-issue budget snapshot from `GET /codex/issues/{id}/budget`.
 *
 * Returns `null` on any failure (404 / 503 / network) so callers can render a
 * graceful "no data" branch without exception plumbing.
 */
export async function getIssueBudget(issueId: string): Promise<IssueBudgetStatus | null> {
  return apiRequestOr<IssueBudgetStatus | null>(
    `${API_BASE}/codex/issues/${issueId}/budget`,
    null,
    {
      dedupe: true,
      errorMessage: (status) => `getIssueBudget(${issueId}) failed: HTTP ${status}`,
    },
  );
}
export async function getIssueOrchestrationPolicy(
  issueId: string,
): Promise<IssueOrchestrationPolicy | null> {
  return apiRequestOr<IssueOrchestrationPolicy | null>(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/orchestration-policy`,
    null,
    {
      dedupe: true,
      errorMessage: (status) => `getIssueOrchestrationPolicy(${issueId}) failed: HTTP ${status}`,
    },
  );
}
