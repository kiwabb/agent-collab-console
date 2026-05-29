from dataclasses import dataclass
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


class Project(BaseModel):
    """A git-backed project that groups sessions / issues / tasks.

    Each project binds to exactly one local git repository (MVP: single-repo).
    Tasks created under a project run inside per-task git worktrees branched
    off `default_branch`.
    """
    id: str
    name: str
    repo_path: str
    default_branch: str = "main"
    origin_url: str | None = None  # Set when project was created via `git clone`
    setup_script: str | None = None  # Optional shell snippet run after worktree creation (e.g. `npm install`)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Skill(BaseModel):
    """A reusable skill reference: pointer to an externally hosted markdown
    playbook (frontmatter + body) that an agent could later be configured to use.
    Body is intentionally NOT persisted — the right-side preview fetches `link`
    on demand via the backend proxy.
    """
    id: str
    name: str
    link: str
    description: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GitBranch(BaseModel):
    """A branch listing entry surfaced by the branches API."""
    name: str
    is_current: bool = False
    is_remote: bool = False
    last_commit_date: datetime | None = None
    last_commit_sha: str | None = None


class CodexSession(BaseModel):
    """Represents a local Codex CLI session managed by this console.

    In the per-turn model, a session is a chat history container.
    Each user message triggers one isolated `codex exec --json <prompt>` job.
    The session does not own a persistent process between turns.
    """
    id: str
    title: str
    cwd: str
    project_id: str | None = None  # Required for new sessions; nullable for back-compat with legacy rows
    # Status is request-oriented (not process-oriented):
    # "idle" = ready for input, "responding" = turn in progress,
    # "done" = turn completed, "failed" = turn errored
    status: str = "idle"
    created_at: datetime | None = None
    last_active_at: datetime | None = None
    log_path: str | None = None
    thread_id: str | None = None  # Codex app-server thread id, used for Codex resume
    claude_thread_id: str | None = None  # Claude session id, stored separately to avoid cross-executor pollution
    settings: dict[str, bool] = Field(default_factory=lambda: {"plan_first_pm": True})
    messages: list[CodexMessage] = []  # Persisted chat history


CodexWorkspace = CodexSession


class CodexIssue(BaseModel):
    id: str
    session_id: str
    project_id: str | None = None
    title: str
    description: str | None = None
    current_phase: str = "requirements"
    status: str = "open"
    review_comment: str | None = None
    is_pinned: bool = False
    milestone: str | None = None  # Milestone grouping (e.g., "v1.0", "sprint-1")
    # Git state — primary location. Tasks under this issue share the worktree below.
    git_branch: str | None = None
    git_base_branch: str | None = None
    git_worktree_path: str | None = None
    git_merge_status: str = "open"  # "open" | "merged" | "abandoned"
    git_last_commit_sha: str | None = None
    # GitHub PR loop (S2-PR). Populated by /api/codex/issues/{id}/pr/create
    # and refreshed by /pr/refresh.
    github_pr_url: str | None = None
    # Mirrors `gh pr view --json state,reviewDecision` — typical values:
    # `OPEN/MERGED/CLOSED` for state, `APPROVED/CHANGES_REQUESTED/REVIEW_REQUIRED` for decision.
    # Stored as "<state>:<reviewDecision?>" so a single column carries both.
    github_pr_state: str | None = None
    # Executor selection chosen at issue creation. When set, Conductor-dispatched
    # sub-agents use these instead of the agent catalog defaults (see dispatch_role).
    executor: str | None = None
    provider: str | None = None
    model: str | None = None
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
    project_id: str | None = None  # Git project this task runs against (None only for legacy rows)
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
    result_json: str | None = None
    parent_task_id: str | None = None  # Task this was continued from, if any
    task_kind: str = "normal"
    blocked_by_help_id: str | None = None
    workspace_path: str | None = None  # Dedicated workspace directory for this task (legacy ephemeral path)
    git_branch: str | None = None  # Per-task branch name (e.g. task/abc12345-add-foo)
    git_base_branch: str | None = None  # Branch this task was forked from
    git_worktree_path: str | None = None  # Absolute path to this task's git worktree (executor cwd)
    git_merge_status: str = "open"  # "open" | "merged" | "abandoned"
    git_last_commit_sha: str | None = None  # HEAD sha at the worktree, recorded on merge
    resume_session_id: str | None = None  # Agent-native conversation/thread id for follow-up (passed to agent)
    resume_message_id: str | None = None  # Optional last assistant message id for targeted resume
    last_execution_process_id: str | None = None  # FK → ExecutionProcess.id of most recent run
    sequence_index: int | None = None  # Position in development task sequence (0-based)
    sequence_group: str | None = None  # Group identifier for sequencing (typically issue_id)
    review_comment: str | None = None  # Architect's review feedback
    workflow_node_id: str | None = None  # FK → workflow_nodes.id (PR1+: DAG-aware tasks)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def workspace_id(self) -> str:
        return self.session_id


@dataclass
class SubAgentResult:
    """Structured envelope handed to Conductor after a workflow node finishes."""

    task_id: str
    node_key: str
    role: str
    agent_id: str
    status: str
    summary: str
    artifact_json: dict | None
    artifact_markdown: str | None
    artifact_paths: list[str]
    files_changed: list[str]
    qa_commands: list[dict] | None
    clarification_question: str | None
    critique: dict | None
    duration_s: float
    retry_count: int
    max_retries: int
    review_comment_in: str | None
    caller_node_key: str | None


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
    mentions: list[str] = Field(default_factory=list)  # @mentioned usernames
    issue_refs: list[str] = Field(default_factory=list)  # #123 style issue references
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
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    total_cost_usd: float | None = None
    # Run intent classification. Drives prompt building and post-run persistence:
    #   initial / rerun → role workflow prompt + persist artifact
    #   refine          → "current artifact + user changes" prompt + persist (merge)
    #   chat            → minimal prompt + CLI session resume; no artifact persist
    kind: Literal["initial", "rerun", "refine", "chat"] = "initial"
    # For chat / refine: pointer back to the CodexTaskMessage that triggered this run.
    triggering_message_id: str | None = None
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
    # HTTP wire protocol this executor's api_endpoint speaks. Used by the
    # Conductor's tool-use loop to pick the right request/response adapter.
    # "anthropic" -> POST /v1/messages; "openai" -> POST /v1/chat/completions.
    protocol: Literal["anthropic", "openai"] = "anthropic"
    providers: list[RuntimeProviderConfig] = Field(default_factory=list)
    default_provider_id: str | None = None  # ID of the default provider


class ConductorLLMConfig(BaseModel):
    """Dedicated LLM selection for the ProjectConductor's tool-use loop.

    Separate from the per-subagent executors so the orchestrating brain can run
    on a different model/provider than the agents it dispatches. `executor_id`
    references a RuntimeExecutorConfig in the same catalog (whose `protocol`
    decides the wire format); `model` overrides that executor's default model.
    """
    executor_id: str | None = None
    model: str | None = None
    max_tokens: int = 8192
    timeout_s: float = 120.0
    # Language for the conductor's user-facing output (reasoning narration, status
    # notes, user questions, finalize summary). "auto" matches the issue's own
    # language (legacy behavior); otherwise a UI locale code like "zh-CN" / "en-US"
    # synced from Settings → the server-side loop has no other way to know the UI
    # language, so it is persisted here.
    output_language: str = "auto"


class RuntimeCatalog(BaseModel):
    """Global runtime catalog containing all executor/provider/model configurations."""
    executors: list[RuntimeExecutorConfig] = Field(default_factory=list)
    conductor_llm: ConductorLLMConfig = Field(default_factory=ConductorLLMConfig)


# --- Template Models ---

class IssueTemplate(BaseModel):
    """Template for creating recurring issues."""
    id: str
    workspace_id: str | None = None  # None = global template
    title: str
    description: str | None = None
    phases: list[str] = Field(default_factory=list)  # Default phases to create
    created_at: datetime | None = None


# --- Workflow DAG Models (PR1) ---
# These replace the hardcoded 4-phase role pipeline with a first-class
# Agent registry + DAG-of-nodes execution model. Built-in agents preserve
# legacy behavior; the orchestrator/scheduler land in later PRs.

NodeStatus = Literal[
    "pending", "blocked", "ready", "running",
    "done", "failed", "skipped", "needs_rework",
]

EdgeType = Literal[
    "sequence", "parallel-fanout", "refine-loop",
    "retry-on-fail", "conditional", "critique-loop",
]


class Agent(BaseModel):
    """A pluggable agent definition.

    Replaces hardcoded role dispatch in role_workflow_service.py. Each Agent
    owns its system prompt template, input/output schema, and runtime defaults.
    """
    id: str
    workspace_id: str | None = None  # None = global agent
    name: str
    role_key: str  # Stable key for backward compat (product_manager/architect/...)
    description: str | None = None
    system_prompt_template: str
    # Declares which upstream artifacts to inject: list of {node_key|role_key, required, artifact_glob}
    input_schema: list[dict] = Field(default_factory=list)
    # Declares produced artifacts: {artifacts: [{name, kind, path_template}]}
    output_schema: dict = Field(default_factory=dict)
    default_executor: str | None = None
    default_provider: str | None = None
    default_model: str | None = None
    artifact_subdir: str | None = None  # legacy subdir (pm/architect/...) or "node_<key>" for custom
    persist_kind: str | None = None  # Hooks RoleWorkflowService.persist_result()
    agent_tier: Literal["managed", "specialist", "custom"] = "managed"
    triggers_replan_on_done: bool = False  # PM/architect set this true
    triggers_replan_on_fail: bool = False  # QA sets this true
    is_builtin: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WorkflowNode(BaseModel):
    """One node in a workflow graph (an agent invocation slot)."""
    id: str
    graph_id: str
    node_key: str  # Stable key within the graph (used by edges)
    agent_id: str
    title: str | None = None
    prompt_override: str | None = None  # Optional per-node override of agent.system_prompt_template
    status: NodeStatus = "pending"
    task_id: str | None = None
    artifact_dir: str | None = None
    retries: int = 0
    max_retries: int = 1
    instance_index: int = 0  # For multi-instance same-role nodes: engineer#0, engineer#1, etc.
    batch_key: str | None = None  # Shared key for nodes dispatched together via dispatch_batch (parallel swarm fan-out); None for serial dispatches
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WorkflowEdge(BaseModel):
    """An edge connecting two nodes within the same graph."""
    id: str
    graph_id: str
    from_node_key: str
    to_node_key: str
    edge_type: EdgeType = "sequence"
    condition_expr: str | None = None  # JSON-logic style mini-DSL (evaluated by scheduler)
    created_at: datetime | None = None


class WorkflowGraph(BaseModel):
    """A DAG describing how an issue is executed.

    `dag_json` is the editable source of truth. The nodes/edges lists are
    derived/materialized views that the scheduler queries directly.
    """
    id: str
    issue_id: str
    preset_id: str | None = None
    status: str = "draft"  # draft | running | done | failed | cancelled
    dag_json: str  # Serialized {nodes:[...], edges:[...], meta:{...}}
    created_by: str | None = None  # "orchestrator" | "user" | "preset"
    locked_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Convenience populated by store (not persisted directly on graphs table)
    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)


class WorkflowPreset(BaseModel):
    """A reusable graph template (e.g. legacy 4-phase, bug-fix, docs-only)."""
    id: str
    name: str
    description: str | None = None
    dag_template_json: str
    is_builtin: bool = False
    created_at: datetime | None = None


class GraphReplanPending(BaseModel):
    """A replan proposal awaiting user Confirm/Reject.

    Emitted by the scheduler when a node with triggers_replan_on_done/fail
    completes; suspends downstream dispatch until resolved.
    """
    id: str
    graph_id: str
    triggered_by_node_key: str
    trigger_reason: str  # "node_done" | "node_failed"
    diff_json: str  # {added_nodes, removed_node_keys, added_edges, removed_edge_ids}
    rationale: str | None = None
    status: Literal["pending", "confirmed", "rejected"] = "pending"
    created_at: datetime | None = None
    resolved_at: datetime | None = None


@dataclass
class ConductorState:
    """Issue-level rolling state for Conductor decisions and dispatch hints."""

    issue_id: str
    running_thread_json: str = "[]"
    pending_dispatches_json: str = "[]"
    scratchpad: str = ""
    decision_count: int = 0
    updated_at: datetime | None = None


@dataclass
class ProjectConductorState:
    """Project-level long-lived conductor context with tiered memory."""

    project_id: str
    hot_thread_json: str = "[]"
    warm_summaries_json: str = "[]"
    pinned_text: str = ""
    hot_tokens: int = 0
    warm_tokens: int = 0
    last_compaction_at: datetime | None = None
    total_tasks_handled: int = 0
    updated_at: datetime | None = None


ConductorTaskKind = Literal["issue", "qa_question", "scheduled_review", "ad_hoc"]
ConductorTurnKind = Literal["llm_request", "llm_response", "tool_use", "tool_result", "user_message", "error", "finalize"]


@dataclass
class ConductorTask:
    """A top-level ProjectConductor task; issues are one task kind among several."""

    id: str
    project_id: str
    task_kind: ConductorTaskKind
    payload: dict
    issue_id: str | None = None
    status: str = "pending"
    result_json: str | None = None
    lease_owner: str | None = None
    heartbeat_at: datetime | None = None
    lease_expires_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class ConductorTurn:
    """A persisted event within a single Conductor loop."""

    id: str
    conductor_task_id: str
    issue_id: str
    turn_index: int
    sub_index: int = 0
    kind: ConductorTurnKind = "llm_request"
    payload_json: str = "{}"
    created_at: datetime | None = None
    consumed_at: datetime | None = None


@dataclass
class ConductorStateLog:
    """A persisted phase transition within an issue conductor loop."""

    id: str
    issue_id: str
    from_phase: str | None
    to_phase: str
    from_detail: str | None = None
    to_detail: str | None = None
    transition_at: datetime | None = None
    duration_ms: int | None = None
    is_legal: bool = True


@dataclass
class ProjectMemoryEmbedding:
    """Cold-memory placeholder row; vector storage can be upgraded later."""

    id: str
    project_id: str
    source_kind: str
    source_id: str
    summary_text: str
    vector_json: str = "[]"
    created_at: datetime | None = None


AgentMessageType = Literal["handoff", "critique", "clarification", "answer", "specialist_call", "specialist_result"]


class AgentMessage(BaseModel):
    """A structured message passed between two workflow agents (e.g. Engineer → Architect critique).

    Persisted so the Collab Feed tab can replay the full inter-agent conversation.
    """
    id: str
    issue_id: str
    graph_id: str
    from_node_key: str
    to_node_key: str
    message_type: AgentMessageType = "handoff"
    body: str
    created_at: datetime | None = None


class ConductorDecision(BaseModel):
    """A decision record emitted by the ConductorSupervisor for each task completion.

    Persisted so the conductor-log endpoint can replay the full decision history.
    """
    id: str
    issue_id: str
    task_id: str
    action: str  # proceed|note|escalate|reroute|insert_node|request_clarification
    reason: str | None = None
    diff_json: str | None = None  # JSON-serialized diff when action mutates graph
    applied_at: datetime | None = None
    created_at: datetime | None = None
