// AUTO-SPLIT from lib/types.ts by domain (frontend lib split).

import type { GitMergeStatus } from "./common";
import type { CodexTask } from "./tasks";

export interface CodexIssue {
  id: string;
  session_id: string;
  project_id: string | null;
  title: string;
  description: string | null;
  acceptance_criteria: string[];
  acceptance_criteria_confirmed: boolean;
  current_phase: string;
  status: string;
  review_comment?: string | null;
  is_pinned?: boolean;
  milestone?: string | null;
  git_branch: string | null;
  git_base_branch: string | null;
  git_worktree_path: string | null;
  git_merge_status: GitMergeStatus;
  git_last_commit_sha: string | null;
  /** S2-PR — `gh pr create` URL once a PR is opened for this issue. */
  github_pr_url?: string | null;
  /** Mirror of `gh pr view --json state,reviewDecision` → "STATE:DECISION". */
  github_pr_state?: string | null;
  /** Per-issue USD budget ceiling. 0 or null means "no ceiling" (unlimited). */
  budget_usd?: number | null;
  created_at: string | null;
  updated_at: string | null;
}

/**
 * Per-issue budget snapshot returned by `GET /codex/issues/{id}/budget`.
 * Mirrors the backend `IssueBudgetStatus.to_dict()` shape.
 *
 * - `has_ceiling === false` means the issue has no USD cap (unlimited). In
 *   that branch `remaining_usd` and `used_ratio` are explicitly `null` so the
 *   UI can render an "unlimited" state without misleading bar math.
 * - `over_budget` is a *derived* flag and is always false when has_ceiling is
 *   false.
 * - The `budget_source` is "issue" when the per-issue override is set,
 *   otherwise "default" (the global default from `timeouts`).
 */
export interface IssueBudgetStatus {
  issue_id: string;
  spent_usd: number;
  budget_usd: number;
  remaining_usd: number | null;
  used_ratio: number | null;
  soft_warn: boolean;
  over_budget: boolean;
  soft_warn_ratio: number;
  has_ceiling: boolean;
  budget_source: "issue" | "default";
}

export type OrchestrationRecommendation =
  "pm_first" | "architect_first" | "batch_allowed" | "single_engineer";

export type OrchestrationSignal =
  | "explicit_parallel"
  | "independent_slices"
  | "trivial"
  | "ambiguous_scope"
  | "risk_or_cross_layer"
  | "default_serial";

/**
 * Deterministic Conductor policy returned by
 * `GET /codex/issues/{id}/orchestration-policy`.
 */
export interface IssueOrchestrationPolicy {
  issue_id: string;
  recommendation: OrchestrationRecommendation | string;
  batch_allowed: boolean;
  signals: string[];
  guidance: string[];
}

export interface IssuePhaseTransitionResult {
  issue: CodexIssue;
  task: CodexTask | null;
  created: boolean;
}

export interface IssuePhaseMultiTaskTransitionResult {
  issue: CodexIssue;
  tasks: CodexTask[];
  created: boolean;
}

export interface MergeIssueResult {
  sha: string;
  base_branch: string;
  message: string;
  issue: CodexIssue;
}

export interface DiffStat {
  files: number;
  insertions: number;
  deletions: number;
}

export interface IssueDiffResult {
  diff: string;
  base_branch: string | null;
  branch: string | null;
  stat?: DiffStat | null;
  commits_ahead?: number;
}

export interface CreateIssueRequest {
  session_id: string;
  title: string;
  description?: string;
  acceptance_criteria?: string[];
  acceptance_criteria_confirmed?: boolean;
  base_branch?: string | null;
  executor?: string | null;
  provider?: string | null;
  model?: string | null;
}

export interface UpdateIssuePhaseRequest {
  current_phase: string;
}

export interface ConfirmIssueAcceptanceCriteriaRequest {
  acceptance_criteria: string[];
}

export interface IssueTemplate {
  id: string;
  workspace_id: string | null;
  title: string;
  description: string | null;
  phases: string[];
  created_at: string | null;
}
