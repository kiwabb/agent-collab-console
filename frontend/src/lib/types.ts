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
  task_id: string;
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
  status: string;
  created_at: string | null;
  last_active_at: string | null;
  log_path: string | null;
  thread_id: string | null;
  claude_thread_id: string | null;
  messages: CodexMessage[];
}

export type Workspace = CodexSession;

export interface CodexIssue {
  id: string;
  session_id: string;
  title: string;
  description: string | null;
  current_phase: string;
  status: string;
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
  issue_id: string | null;
  phase: string;
  title: string;
  prompt: string;
  role: string;
  executor: string;
  status: string;
  result: string | null;
  parent_task_id: string | null;
  task_kind: string;
  blocked_by_help_id: string | null;
  workspace_path: string | null;
  resume_session_id: string | null;
  resume_message_id: string | null;
  last_execution_process_id: string | null;
  sequence_index: number | null;
  sequence_group: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface CodexTaskMessage {
  id: string;
  task_id: string;
  execution_process_id: string | null;
  role: string;
  content: string;
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

export interface ExecutionProcess {
  id: string;
  task_id: string;
  session_id: string;
  status: string;
  exit_code: number | null;
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
  cwd?: string;
}

export interface CreateTaskRequest {
  session_id: string;
  issue_id?: string | null;
  phase: string;
  title: string;
  prompt: string;
  parent_task_id?: string | null;
  executor?: string;
  role?: string;
}

export interface CreateIssueRequest {
  session_id: string;
  title: string;
  description?: string;
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

export interface ResolveApprovalRequest {
  item_id: string;
  decision: string;
  feedback?: string | null;
}

export interface UpdateCodexTaskRequest {
  executor?: "codex" | "claude";
}
