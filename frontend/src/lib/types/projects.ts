// AUTO-SPLIT from lib/types.ts by domain (frontend lib split).

export interface Project {
  id: string;
  name: string;
  repo_path: string;
  default_branch: string;
  origin_url: string | null;
  setup_script: string | null;
  run_command?: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Live status of a project's one-click `run_command` dev process. */
export type ProjectRunServiceState =
  "reachable" | "unreachable" | "not_configured" | "invalid_url" | "unknown";

export interface ProjectRunServiceStatus {
  state: ProjectRunServiceState;
  url: string | null;
  http_status: number | null;
  checked_at: string | null;
  error: string | null;
}

export interface ProjectRunStatus {
  running: boolean;
  command: string | null;
  pid: number | null;
  started_at: string | null;
  exit_code: number | null;
  service: ProjectRunServiceStatus;
}

/** One captured line from a running project process. */
export interface ProjectRunLogLine {
  seq: number;
  stream: "stdout" | "stderr";
  line: string;
  ts: string;
}

/** Incremental log response from `GET /run/logs?after=<seq>`. */
export interface ProjectRunLogsResponse {
  lines: ProjectRunLogLine[];
  last_seq: number;
  running: boolean;
  exit_code: number | null;
}

/** Refusal reason returned (409) by `POST /run/start`. */
export type ProjectRunStartReason =
  "no_run_command" | "already_running" | "service_already_reachable" | "refused" | "env_incomplete";

export interface ProjectRunEnvError {
  name: string;
  reason: string;
  description: string;
}

export interface CreateProjectRequest {
  name: string;
  source: "local" | "clone";
  repo_path?: string;
  origin_url?: string;
  dest_parent?: string;
}

export interface UpdateProjectRequest {
  name?: string;
  default_branch?: string;
  setup_script?: string;
  run_command?: string | null;
}

export interface ProjectStats {
  workspaces: number;
  issues_total: number;
  issues_open: number;
  issues_merged: number;
  issues_abandoned: number;
}

export type ProjectRemoteError =
  "not_a_git_repo" | "no_origin" | "fetch_failed" | "no_remote_branch" | null;

export interface ProjectRemoteStatus {
  branch: string;
  current_branch: string;
  has_origin: boolean;
  dirty: boolean;
  behind: number;
  ahead: number;
  can_fast_forward: boolean;
  fetched: boolean;
  error: ProjectRemoteError;
}

export type ProjectPullReason =
  | "no_origin"
  | "fetch_failed"
  | "no_remote_branch"
  | "not_on_default"
  | "dirty"
  | "diverged"
  | "already_up_to_date";

export interface ProjectPullResult {
  success: boolean;
  branch: string;
  new_sha?: string | undefined;
  behind_before?: number | undefined;
  reason?: ProjectPullReason | undefined;
}

export interface ProjectConductorState {
  project_id: string;
  hot_thread: Array<Record<string, unknown>>;
  warm_summaries: Array<Record<string, unknown>>;
  cold_memories: Array<{
    id: string;
    source_kind: string;
    source_id: string;
    summary_text: string;
    created_at: string | null;
  }>;
  pinned_text: string;
  hot_tokens: number;
  warm_tokens: number;
  total_tasks_handled: number;
  last_compaction_at: string | null;
  updated_at: string | null;
}

export interface ProjectConductorAskResult {
  status: string;
  answer: string;
  task_id: string;
}

export interface ProjectConductorToolEvent {
  id: string;
  name: string;
  input: Record<string, unknown>;
  result: unknown;
  is_error: boolean;
}

export interface ProjectConductorLoopResult extends ProjectConductorAskResult {
  tool_events: ProjectConductorToolEvent[];
  turn_count: number;
  llm?: {
    executor: string;
    model: string;
  } | null;
}

export interface ProjectAuditEntry {
  id: number;
  project_id: string | null;
  issue_id: string | null;
  event: string;
  sha: string | null;
  base_branch: string | null;
  created_at: string;
}
