// Types matching backend models from backend/app/domain/models.py

export interface Task {
  id: string;
  session_id: string;
  title: string;
  assignee: string | null;
  status: string;
  created_at: string | null;
}

export interface AgentRun {
  id: string;
  task_id: string;
  agent_id: string;
  role: string;
  status: string;
  summary: string | null;
  payload: Record<string, unknown> | null;
  created_at: string | null;
}

export interface Approval {
  id: string;
  session_id: string;
  task_id: string;
  action: string;
  status: string;
  created_at: string | null;
}

export interface ApprovalEvent {
  id: string;
  session_id: string;
  task_id: string;
  approval_id: string;
  event_type: string;
  created_at: string | null;
}

export interface PlanDetails {
  summary: string;
  next_steps: string[];
  task_title: string;
}

export interface Artifact {
  id: string;
  task_id: string | null;
  kind: string;
  name?: string;
  content: string | PlanDetails;
  steps: string[] | null;
  created_at: string | null;
}

export interface Message {
  id: string;
  task_id: string;
  agent_id: string;
  role: string;
  content: string;
  created_at: string | null;
}

export interface Session {
  id: string;
  title: string;
  state: string;
  tasks: Task[];
  artifacts: Artifact[];
  messages: Message[];
  runs: AgentRun[];
  approvals: Approval[];
  approval_events: ApprovalEvent[];
}

export interface CodexMessage {
  id: string;
  session_id: string;
  role: string;
  content: string;
  created_at: string | null;
}

export interface CodexSession {
  id: string;
  title: string;
  cwd: string;
  project_id: string | null;
  status: string;
  created_at: string | null;
  last_active_at: string | null;
  log_path: string | null;
  thread_id: string | null;
  claude_thread_id: string | null;
  messages: CodexMessage[];
}

export type Workspace = CodexSession;

export interface Project {
  id: string;
  name: string;
  repo_path: string;
  default_branch: string;
  origin_url: string | null;
  setup_script: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface GitBranch {
  name: string;
  is_current: boolean;
  is_remote: boolean;
  last_commit_date: string | null;
  last_commit_sha: string | null;
}

export type GitMergeStatus = "open" | "merged" | "abandoned";

export interface CodexIssue {
  id: string;
  session_id: string;
  project_id: string | null;
  title: string;
  description: string | null;
  current_phase: string;
  status: string;
  is_pinned?: boolean;
  milestone?: string | null;
  git_branch: string | null;
  git_base_branch: string | null;
  git_worktree_path: string | null;
  git_merge_status: GitMergeStatus;
  git_last_commit_sha: string | null;
  created_at: string | null;
  updated_at: string | null;
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
export type NormalizedEntryType = "status" | "error" | "assistant" | "command" | "help" | "raw";

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
}

// Execution processes state
export interface ExecutionProcessesState {
  execution_processes: Record<string, ExecutionProcess>;
}

// API response types
export interface HealthResponse {
  service: string;
  status?: string;
}

export interface PendingApprovalsResponse {
  pending: Approval[];
}

export interface CreateWorkspaceRequest {
  title: string;
  project_id: string;
  cwd?: string;
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
}

export interface MergeIssueResult {
  sha: string;
  base_branch: string;
  message: string;
  issue: CodexIssue;
}

export interface IssueDiffResult {
  diff: string;
  base_branch: string | null;
  branch: string | null;
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

export interface CreateIssueRequest {
  session_id: string;
  title: string;
  description?: string;
  base_branch?: string | null;
}

export interface UpdateIssuePhaseRequest {
  current_phase: string;
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

export interface ResolveApprovalRequest {
  item_id: string;
  decision: string;
  feedback?: string | null;
}

export interface UpdateCodexTaskRequest {
  executor?: "codex" | "claude";
  provider?: string | null;
  model?: string | null;
}

// Runtime Catalog Types

export interface RuntimeModelConfig {
  id: string;
  label: string;
  enabled: boolean;
}

export interface RuntimeProviderConfig {
  id: string;
  label: string;
  enabled: boolean;
  models: RuntimeModelConfig[];
  default_model_id: string | null;
  command_template?: string | null;
  env_template?: Record<string, string> | null;
}

export interface RuntimeExecutorConfig {
  id: string;
  label: string;
  enabled: boolean;
  executor_type: "claude" | "codex";
  api_endpoint?: string | null;
  api_key?: string | null;
  default_model?: string | null;
  providers: RuntimeProviderConfig[];
  default_provider_id: string | null;
}

export interface RuntimeCatalog {
  executors: RuntimeExecutorConfig[];
}

export interface RuntimeCatalogRequest {
  catalog: RuntimeCatalog;
}

export interface ValidateRuntimeCatalogResponse {
  valid: boolean;
  error?: string;
}

export interface TestExecutorResponse {
  success: boolean;
  latency_ms?: number;
  error?: string;
}

export interface IssueTemplate {
  id: string;
  workspace_id: string | null;
  title: string;
  description: string | null;
  phases: string[];
  created_at: string | null;
}
