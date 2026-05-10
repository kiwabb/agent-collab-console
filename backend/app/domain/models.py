from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.states import SessionState


class Task(BaseModel):
    id: str
    session_id: str
    title: str
    assignee: str | None = None
    status: str = "pending"
    created_at: datetime | None = None


class AgentRun(BaseModel):
    id: str
    task_id: str
    agent_id: str
    role: str
    status: str = "running"
    summary: str | None = None
    payload: dict | None = None
    created_at: datetime | None = None


class Approval(BaseModel):
    id: str
    session_id: str
    task_id: str
    action: str
    status: str = "pending"
    created_at: datetime | None = None


class ApprovalEvent(BaseModel):
    """Tracks individual state transitions in an approval lifecycle."""
    id: str
    session_id: str
    task_id: str
    approval_id: str
    event_type: str  # "requested", "approved", "rejected"
    created_at: datetime | None = None


class PlanDetails(BaseModel):
    summary: str
    next_steps: list[str]
    task_title: str


class Artifact(BaseModel):
    id: str
    task_id: str
    kind: str
    content: str | PlanDetails
    steps: list[str] | None = None
    created_at: datetime | None = None


class Message(BaseModel):
    id: str
    task_id: str
    agent_id: str
    role: str
    content: str
    created_at: datetime | None = None


class Session(BaseModel):
    id: str
    title: str
    state: SessionState = SessionState.DRAFT
    tasks: list[Task] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)
    runs: list[AgentRun] = Field(default_factory=list)
    approvals: list[Approval] = Field(default_factory=list)
    approval_events: list[ApprovalEvent] = Field(default_factory=list)


class CodexMessage(BaseModel):
    """A single message in a Codex chat session (user or assistant)."""
    id: str
    session_id: str
    role: str  # "user" or "assistant"
    content: str
    created_at: datetime | None = None


class CodexSession(BaseModel):
    """Represents a local Codex CLI session managed by this console.

    In the per-turn model, a session is a chat history container.
    Each user message triggers one isolated `codex exec --json <prompt>` job.
    The session does not own a persistent process between turns.
    """
    id: str
    title: str
    cwd: str
    # Status is request-oriented (not process-oriented):
    # "idle" = ready for input, "responding" = turn in progress,
    # "done" = turn completed, "failed" = turn errored
    status: str = "idle"
    created_at: datetime | None = None
    last_active_at: datetime | None = None
    log_path: str | None = None
    thread_id: str | None = None  # Codex app-server thread id, used for Codex resume
    claude_thread_id: str | None = None  # Claude session id, stored separately to avoid cross-executor pollution
    messages: list[CodexMessage] = []  # Persisted chat history


CodexWorkspace = CodexSession


class CodexIssue(BaseModel):
    id: str
    session_id: str
    title: str
    description: str | None = None
    current_phase: str = "requirements"
    status: str = "open"
    is_pinned: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def workspace_id(self) -> str:
        return self.session_id


class CodexTask(BaseModel):
    """A single task run within a CodexSession workspace.

    One task = one isolated CLI agent run.
    The task owns its prompt, execution status, result, and resumable
    conversation metadata for follow-up runs.
    """
    id: str
    session_id: str  # The workspace this task belongs to
    issue_id: str | None = None
    phase: str = "requirements"
    title: str
    prompt: str
    role: str = "general"
    executor: str = "codex" # "codex" or "claude"
    provider: str | None = None  # Provider override (e.g., "anthropic", "openai")
    model: str | None = None     # Model override (e.g., "claude-sonnet-4-6", "gpt-4o")
    status: str = "pending"
    result: str | None = None
    parent_task_id: str | None = None  # Task this was continued from, if any
    task_kind: str = "normal"
    blocked_by_help_id: str | None = None
    workspace_path: str | None = None  # Dedicated workspace directory for this task
    resume_session_id: str | None = None  # Agent-native conversation/thread id for follow-up (passed to agent)
    resume_message_id: str | None = None  # Optional last assistant message id for targeted resume
    last_execution_process_id: str | None = None  # FK → ExecutionProcess.id of most recent run
    sequence_index: int | None = None  # Position in development task sequence (0-based)
    sequence_group: str | None = None  # Group identifier for sequencing (typically issue_id)
    review_comment: str | None = None  # Architect's review feedback
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def workspace_id(self) -> str:
        return self.session_id


class CodexTaskMessage(BaseModel):
    """A single message in a task's conversation history (user or assistant).

    These are stored separately from session-level CodexMessages because
    they belong to a specific task workspace and can trigger follow-up runs.
    """
    id: str
    task_id: str
    execution_process_id: str | None = None
    role: str  # "user" or "assistant"
    content: str
    created_at: datetime | None = None


class LogEvent(BaseModel):
    """A single log line from a Codex session or task run (raw JSONL for debugging)."""
    id: str
    session_id: str
    stream: str = "stdout"  # "stdout" or "stderr"
    content: str
    task_id: str | None = None  # The task run that produced this log (if any)
    execution_process_id: str | None = None
    created_at: datetime | None = None

    @property
    def workspace_id(self) -> str:
        return self.session_id


class ExecutionProcess(BaseModel):
    """A single runtime execution for a CodexTask.

    ExecutionProcess is the primary live runtime entity for streaming state,
    logs, messages, approvals, and lifecycle updates.
    """
    id: str
    task_id: str
    session_id: str
    status: str = "Running"  # Running | Completed | Failed | Killed
    exit_code: int | None = None
    executor: str | None = None  # Resolved executor at run time
    provider: str | None = None  # Resolved provider at run time
    model: str | None = None     # Resolved model at run time
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def workspace_id(self) -> str:
        return self.session_id


class HelpRequest(BaseModel):
    id: str
    workspace_id: str
    parent_task_id: str
    child_task_id: str
    source_executor: str
    target_executor: str
    title: str
    prompt: str
    context_summary: str | None = None
    status: str = "pending"
    error_message: str | None = None
    continuation_payload: dict | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    timeout_at: datetime | None = None
    consumed_at: datetime | None = None


# --- Runtime Catalog Models ---

class RuntimeModelConfig(BaseModel):
    """Configuration for a single model within a provider."""
    id: str  # Unique ID within the catalog (e.g., "claude-sonnet-4-6")
    label: str  # Human-readable label (e.g., "Claude Sonnet 4.6")
    enabled: bool = True


class RuntimeProviderConfig(BaseModel):
    """Configuration for a provider that belongs to an executor."""
    id: str  # Unique ID within the catalog (e.g., "anthropic")
    label: str  # Human-readable label (e.g., "Anthropic")
    enabled: bool = True
    models: list[RuntimeModelConfig] = Field(default_factory=list)
    default_model_id: str | None = None  # ID of the default model
    # Template for additional command-line arguments (supports {model}, {provider}, {workspace_cwd}, {task_id})
    command_template: str | None = None
    # Template for environment variable overrides (key = env var name, value = template)
    env_template: dict[str, str] | None = None


class RuntimeExecutorConfig(BaseModel):
    """Configuration for a top-level executor (e.g., codex, claude)."""
    id: str  # Unique ID (e.g., "codex", "claude")
    label: str  # Human-readable label
    enabled: bool = True
    executor_type: Literal["claude", "codex"] = "claude"
    api_endpoint: str | None = None
    api_key: str | None = None
    default_model: str | None = None
    providers: list[RuntimeProviderConfig] = Field(default_factory=list)
    default_provider_id: str | None = None  # ID of the default provider


class RuntimeCatalog(BaseModel):
    """Global runtime catalog containing all executor/provider/model configurations."""
    executors: list[RuntimeExecutorConfig] = Field(default_factory=list)

