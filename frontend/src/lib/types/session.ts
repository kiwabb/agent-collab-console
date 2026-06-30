// AUTO-SPLIT from lib/types.ts by domain (frontend lib split).

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
  settings: {
    plan_first_pm?: boolean;
  };
  messages: CodexMessage[];
}

export type Workspace = CodexSession;

export interface PendingApprovalsResponse {
  pending: Approval[];
}
