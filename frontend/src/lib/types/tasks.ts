// AUTO-SPLIT from lib/types.ts by domain (frontend lib split).

import type { GitMergeStatus } from "./common";

export interface TaskRunUsage {
  executor?: string | null;
  provider?: string | null;
  model?: string | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  cache_read_tokens?: number | null;
  total_cost_usd?: number | null;
  duration_seconds?: number | null;
  status?: string | null;
}

export interface CodexTask {
  id: string;
  session_id: string;
  project_id: string | null;
  issue_id: string | null;
  phase: string;
  title: string;
  prompt: string;
  role: string;
  executor: string;
  provider?: string | null;
  model?: string | null;
  status: string;
  result: string | null;
  parent_task_id: string | null;
  task_kind: string;
  blocked_by_help_id: string | null;
  workspace_path: string | null;
  git_branch: string | null;
  git_base_branch: string | null;
  git_worktree_path: string | null;
  git_merge_status: GitMergeStatus;
  git_last_commit_sha: string | null;
  resume_session_id: string | null;
  resume_message_id: string | null;
  last_execution_process_id: string | null;
  last_run?: TaskRunUsage | null;
  sequence_index?: number | null;
  sequence_group?: string | null;
  review_comment?: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface CodexTaskMessage {
  id: string;
  task_id: string;
  execution_process_id: string | null;
  role: string;
  content: string;
  mentions?: string[];
  issue_refs?: string[];
  created_at: string | null;
}

export interface LogEvent {
  id: string;
  session_id: string;
  stream: string;
  content: string;
  task_id: string | null;
  execution_process_id: string | null;
  created_at: string | null;
}

export type RunKind = "initial" | "rerun" | "refine" | "chat";

export type RunMode = "auto" | "chat" | "refine";

export interface ExecutionProcess {
  id: string;
  task_id: string;
  session_id: string;
  status: string;
  exit_code: number | null;
  executor?: string | null;
  provider?: string | null;
  model?: string | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  cache_read_tokens?: number | null;
  total_cost_usd?: number | null;
  duration_seconds?: number | null;
  kind?: RunKind;
  triggering_message_id?: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  messages?: Record<string, CodexTaskMessage>;
  logs?: LogEvent[];
}

export interface HelpRequest {
  id: string;
  workspace_id: string;
  parent_task_id: string;
  child_task_id: string;
  source_executor: string;
  target_executor: string;
  title: string;
  prompt: string;
  context_summary: string | null;
  status: string;
  error_message: string | null;
  continuation_payload: Record<string, unknown> | null;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  timeout_at: string | null;
  consumed_at: string | null;
}

// Normalized log entry types for UI
export type NormalizedEntryType =
  "status" | "error" | "assistant" | "thinking" | "command" | "tool" | "help" | "raw";

export type ToolCategory =
  "bash" | "read" | "edit" | "search" | "todo" | "web" | "mcp" | "fileChange" | "other";

export interface NormalizedEntry {
  id: string;
  type: NormalizedEntryType;
  label: string;
  content?: string;
  command?: string;
  hidden?: boolean;
  output?: string;
  exitCode?: number;
  status?: "running" | "success" | "failed";
  variant?: string;
  raw?: string;
  executionProcessId?: string | null;
  timestamp?: string;
  itemId?: string | null;
  // Structured tool entry (when type === "tool")
  toolName?: string;
  toolUseId?: string;
  category?: ToolCategory;
  args?: Record<string, unknown>;
  filePath?: string;
  durationMs?: number;
  isError?: boolean;
}

// Execution processes state
export interface ExecutionProcessesState {
  execution_processes: Record<string, ExecutionProcess>;
}

export interface CreateTaskRequest {
  session_id: string;
  issue_id?: string | null;
  phase: string;
  title: string;
  prompt: string;
  parent_task_id?: string | null;
  executor?: string;
  provider?: string | null;
  model?: string | null;
  role?: string;
}

export interface RequestHelpRequest {
  target_executor: string;
  title?: string;
  prompt?: string;
  context_summary?: string;
}

export interface SendMessageRequest {
  content: string;
}

export interface SendMessageResult {
  message: CodexTaskMessage | null;
  assistant_message: CodexTaskMessage | null;
  task: CodexTask;
  execution_process: ExecutionProcess;
  resolved_mode?: "chat" | "refine";
}

export interface UpdateCodexTaskRequest {
  // Catalog executor id (or legacy "codex"/"claude" type string).
  // Backend `UpdateCodexTaskRequest.executor: str | None` accepts any string.
  executor?: string | null;
  provider?: string | null;
  model?: string | null;
}
