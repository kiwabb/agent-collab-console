// AUTO-SPLIT from lib/types.ts by domain (frontend lib split).

export interface GitBranch {
  name: string;
  is_current: boolean;
  is_remote: boolean;
  last_commit_date: string | null;
  last_commit_sha: string | null;
}

export type GitMergeStatus = "open" | "merged" | "abandoned";

// API response types
export interface HealthResponse {
  service: string;
  status?: string;
}

export interface CreateWorkspaceRequest {
  title: string;
  project_id: string;
  cwd?: string;
}

export interface CodexStats {
  workspaces_total: number;
  sessions_total: number;
  sessions_active: number;
  tasks_total: number;
  tasks_pending: number;
  tasks_running: number;
  tasks_completed: number;
  tasks_failed: number;
  executor_codex_available: boolean;
  executor_claude_available: boolean;
  last_activity_at: string | null;
}

export interface ResolveApprovalRequest {
  item_id: string;
  decision: string;
  feedback?: string | null;
}
