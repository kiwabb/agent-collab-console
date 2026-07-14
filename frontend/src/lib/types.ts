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
  settings?: {
    plan_first_pm?: boolean;
  };
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
  run_command: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface GitBranch {
  name: string;
  is_current: boolean;
  is_remote: boolean;
  last_commit_date: string | null;
  last_commit_sha: string | null;
}

export type {
  BenchmarkDiff,
  BenchmarkDiffFixture,
  BenchmarkJob,
  BenchmarkJobStatus,
  BenchmarkRun,
  CalibrationItem,
  CalibrationReport,
} from "./types/benchmarks";
export type {
  IssueBudgetStatus,
  IssueOrchestrationPolicy,
  OrchestrationRecommendation,
  OrchestrationSignal,
} from "./types/issues";
export type {
  ProjectConductorAskResult,
  ProjectConductorLoopResult,
  ProjectConductorState,
  ProjectConductorToolEvent,
  ProjectPullResult,
  ProjectRunEnvError,
  ProjectRunLogLine,
  ProjectRunLogsResponse,
  ProjectRunServiceState,
  ProjectRunServiceStatus,
  ProjectRunStartReason,
  ProjectRunStatus,
  ProjectRemoteStatus,
} from "./types/projects";
export type {
  CreateSkillRequest,
  Skill,
  SkillImportResult,
  UpdateSkillRequest,
} from "./types/skills";

export type GitMergeStatus = "open" | "merged" | "abandoned";

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
  is_pinned?: boolean;
  milestone?: string | null;
  git_branch: string | null;
  git_base_branch: string | null;
  git_worktree_path: string | null;
  git_merge_status: GitMergeStatus;
  git_last_commit_sha: string | null;
  github_pr_url?: string | null;
  github_pr_state?: string | null;
  budget_usd?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
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
  last_run?: {
    executor?: string | null;
    provider?: string | null;
    model?: string | null;
    input_tokens?: number | null;
    output_tokens?: number | null;
    cache_read_tokens?: number | null;
    total_cost_usd?: number | null;
    duration_seconds?: number | null;
    status?: string | null;
  } | null;
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
export type NormalizedEntryType =
  "status" | "error" | "assistant" | "thinking" | "command" | "tool" | "help" | "raw";

export type ToolCategory =
  "bash" | "read" | "edit" | "search" | "todo" | "web" | "mcp" | "fileChange" | "other";

export interface NormalizedEntry {
  id: string;
  type: NormalizedEntryType;
  label: string;
  content?: string | undefined;
  command?: string | undefined;
  hidden?: boolean | undefined;
  output?: string | undefined;
  exitCode?: number | undefined;
  status?: "running" | "success" | "failed" | undefined;
  variant?: string | undefined;
  raw?: string | undefined;
  executionProcessId?: string | null | undefined;
  timestamp?: string | undefined;
  itemId?: string | null | undefined;
  // Structured tool entry (when type === "tool")
  toolName?: string | undefined;
  toolUseId?: string | undefined;
  category?: ToolCategory | undefined;
  args?: Record<string, unknown> | undefined;
  filePath?: string | undefined;
  durationMs?: number | undefined;
  isError?: boolean | undefined;
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
  run_command?: string;
}

export interface ProjectEnvVarEntry {
  name: string;
  value: string | null;
  secret: boolean;
  source: string;
}

export interface ProjectEnvVarDisplay {
  name: string;
  secret: boolean;
  source: string;
  is_set: boolean;
  value?: string; // only for non-secret vars
}

export interface ProjectEnvListResponse {
  env_vars: ProjectEnvVarDisplay[];
}

export interface ProjectEnvPutBody {
  name: string;
  value: string;
  secret?: boolean;
  source?: string;
}

export interface ProjectEnvPutBatchBody {
  vars: ProjectEnvPutBody[];
}

export interface ProjectEnvPutResponse {
  saved: string[];
}

export interface ProjectScriptSuggestionResponse {
  setup_script: string;
  run_command: string;
  agent_name: string;
  access_url: string | null;
  notes: string[];
  env_vars?: ProjectEnvVarEntry[];
  verification: {
    status: "verified" | "started" | "failed" | "skipped";
    message: string;
    exit_code?: number | null;
    access_url?: string | null;
    logs?: string[];
  } | null;
}

export interface ProjectScriptSuggestionRequest {
  setup_script?: string | null;
  run_command?: string | null;
  verify?: boolean;
}

export interface ProjectScriptTaskRequest extends ProjectScriptSuggestionRequest {
  executor?: string | null;
  provider?: string | null;
  model?: string | null;
}

export interface ProjectScriptTaskResponse {
  task_id: string;
  status: string;
  title: string;
  execution_process_id?: string | null;
  reused: boolean;
}

export interface ProjectStartupService {
  project_id: string;
  service_id: string;
  name: string;
  working_directory: string;
  setup_command: string;
  run_command: string;
  access_url: string | null;
  depends_on: string[];
  evidence: string[];
  created_at: string | null;
  updated_at: string | null;
}

export interface ProjectStartupConfig {
  project_id: string;
  task_id: string | null;
  notes: string[];
  updated_at: string | null;
  services: ProjectStartupService[];
}

export interface ProjectServiceRunResult {
  service_id: string;
  status: import("./types/projects").ProjectRunStatus;
}

export interface ProjectServicesRunResponse {
  services: ProjectServiceRunResult[];
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

export interface ProjectStats {
  workspaces: number;
  issues_total: number;
  issues_open: number;
  issues_merged: number;
  issues_abandoned: number;
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

export interface ProjectAuditEntry {
  id: number;
  project_id: string | null;
  issue_id: string | null;
  event: string;
  sha: string | null;
  base_branch: string | null;
  created_at: string;
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
  executor?: string | null;
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
  api_key_configured?: boolean;
  default_model?: string | null;
  protocol?: "anthropic" | "openai";
  providers: RuntimeProviderConfig[];
  default_provider_id: string | null;
}

export interface RuntimeCatalog {
  executors: RuntimeExecutorConfig[];
  conductor_llm?: ConductorLLMConfig;
}

export interface ConductorLLMConfig {
  executor_id?: string | null;
  model?: string | null;
  max_tokens?: number;
  timeout_s?: number;
  output_language?: string;
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
  mode?: string;
  detail?: string;
}

export interface IssueTemplate {
  id: string;
  workspace_id: string | null;
  title: string;
  description: string | null;
  phases: string[];
  created_at: string | null;
}

// --- Workflow DAG (PR1) ---

export interface Agent {
  id: string;
  workspace_id: string | null;
  name: string;
  role_key: string;
  description: string | null;
  system_prompt_template: string;
  input_schema: Array<Record<string, unknown>>;
  output_schema: Record<string, unknown>;
  default_executor: string | null;
  default_provider: string | null;
  default_model: string | null;
  artifact_subdir: string | null;
  persist_kind: string | null;
  agent_tier: "managed" | "specialist" | "custom";
  triggers_replan_on_done: boolean;
  triggers_replan_on_fail: boolean;
  is_builtin: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface CreateAgentRequest {
  name: string;
  role_key: string;
  description?: string | null;
  system_prompt_template: string;
  workspace_id?: string | null;
  input_schema?: Array<Record<string, unknown>>;
  output_schema?: Record<string, unknown>;
  default_executor?: string | null;
  default_provider?: string | null;
  default_model?: string | null;
  artifact_subdir?: string | null;
  persist_kind?: string | null;
  triggers_replan_on_done?: boolean;
  triggers_replan_on_fail?: boolean;
}

export interface UpdateAgentRequest {
  name?: string;
  description?: string | null;
  system_prompt_template?: string;
  input_schema?: Array<Record<string, unknown>>;
  output_schema?: Record<string, unknown>;
  default_executor?: string | null;
  default_provider?: string | null;
  default_model?: string | null;
  artifact_subdir?: string | null;
  persist_kind?: string | null;
  triggers_replan_on_done?: boolean;
  triggers_replan_on_fail?: boolean;
}

export type WorkflowNodeStatus =
  "pending" | "blocked" | "ready" | "running" | "done" | "failed" | "skipped" | "needs_rework";

export type WorkflowEdgeType =
  "sequence" | "parallel-fanout" | "refine-loop" | "retry-on-fail" | "conditional";

export interface WorkflowNode {
  id: string;
  graph_id: string;
  node_key: string;
  agent_id: string;
  title: string | null;
  prompt_override: string | null;
  status: WorkflowNodeStatus;
  task_id: string | null;
  artifact_dir: string | null;
  retries: number;
  max_retries: number;
  batch_key?: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface WorkflowEdge {
  id: string;
  graph_id: string;
  from_node_key: string;
  to_node_key: string;
  edge_type: WorkflowEdgeType;
  condition_expr: string | null;
  created_at: string | null;
}

export interface WorkflowGraph {
  id: string;
  issue_id: string;
  preset_id: string | null;
  status: string;
  dag_json: string;
  created_by: string | null;
  locked_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

export interface ProposedDAGNode {
  node_key: string;
  agent_id: string;
  role_key: string;
  title: string;
}

export interface ProposedDAGEdge {
  from_node_key: string;
  to_node_key: string;
  edge_type: WorkflowEdgeType;
  condition_expr?: string | null;
}

export interface ProposedDAG {
  meta: { intent?: string; rationale?: string; created_by?: string };
  nodes: ProposedDAGNode[];
  edges: ProposedDAGEdge[];
}
