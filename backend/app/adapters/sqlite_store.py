import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

from app.domain.models import Session, Task, AgentRun, Artifact, Message, Approval, ApprovalEvent, PlanDetails, CodexSession, CodexMessage, CodexIssue, CodexTask, CodexTaskMessage, LogEvent, ExecutionProcess, HelpRequest, RuntimeCatalog, SelfImprovementProposal


class SQLiteStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _execute(self, conn: sqlite3.Connection, query: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a query with error handling and rollback on failure."""
        try:
            return conn.execute(query, params)
        except sqlite3.Error as e:
            logger.error("Database error: %s | query: %s | params: %s", e, query, params)
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            raise

    def _execute_with_commit(self, conn: sqlite3.Connection, query: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a query with commit, rolling back on failure."""
        try:
            cur = conn.execute(query, params)
            conn.commit()
            return cur
        except sqlite3.Error as e:
            logger.error("Database error: %s | query: %s | params: %s", e, query, params)
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            raise

    def _init_db(self):
        conn = self._get_conn()
        try:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'draft'
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    assignee TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    status TEXT DEFAULT 'running',
                    summary TEXT,
                    payload TEXT,
                    created_at TEXT,
                    FOREIGN KEY (task_id) REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    steps TEXT,
                    created_at TEXT,
                    FOREIGN KEY (task_id) REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT,
                    FOREIGN KEY (task_id) REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS approval_events (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    approval_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at TEXT,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS codex_sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    cwd TEXT NOT NULL,
                    project_id TEXT,
                    status TEXT DEFAULT 'idle',
                    created_at TEXT,
                    last_active_at TEXT,
                    log_path TEXT,
                    thread_id TEXT,
                    claude_thread_id TEXT,
                    settings_json TEXT
                );
                CREATE TABLE IF NOT EXISTS codex_messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT,
                    FOREIGN KEY (session_id) REFERENCES codex_sessions(id)
                );
                CREATE TABLE IF NOT EXISTS codex_issues (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    project_id TEXT,
                    title TEXT NOT NULL,
                    description TEXT,
                    current_phase TEXT NOT NULL DEFAULT 'requirements',
                    status TEXT NOT NULL DEFAULT 'open',
                    review_comment TEXT,
                    is_pinned INTEGER NOT NULL DEFAULT 0,
                    milestone TEXT,
                    git_branch TEXT,
                    git_base_branch TEXT,
                    git_worktree_path TEXT,
                    git_merge_status TEXT DEFAULT 'open',
                    git_last_commit_sha TEXT,
                    github_pr_url TEXT,
                    github_pr_state TEXT,
                    executor TEXT,
                    provider TEXT,
                    model TEXT,
                    budget_usd REAL,
                    created_at TEXT,
                    updated_at TEXT,
                    FOREIGN KEY (session_id) REFERENCES codex_sessions(id)
                );
                CREATE TABLE IF NOT EXISTS codex_tasks (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    issue_id TEXT,
                    phase TEXT DEFAULT 'requirements',
                    title TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    role TEXT DEFAULT 'general',
                    executor TEXT DEFAULT 'codex',
                    provider TEXT,
                    model TEXT,
                    status TEXT DEFAULT 'pending',
                    result TEXT,
                    result_json TEXT,
                    parent_task_id TEXT,
                    task_kind TEXT DEFAULT 'normal',
                    blocked_by_help_id TEXT,
                    workspace_path TEXT,
                    resume_session_id TEXT,
                    resume_message_id TEXT,
                    last_execution_process_id TEXT,
                    sequence_index INTEGER,
                    sequence_group TEXT,
                    review_comment TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    FOREIGN KEY (session_id) REFERENCES codex_sessions(id)
                );
                CREATE TABLE IF NOT EXISTS codex_task_messages (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    execution_process_id TEXT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT,
                    FOREIGN KEY (task_id) REFERENCES codex_tasks(id)
                );
                CREATE TABLE IF NOT EXISTS log_events (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    stream TEXT NOT NULL DEFAULT 'stdout',
                    content TEXT NOT NULL,
                    task_id TEXT,
                    execution_process_id TEXT,
                    created_at TEXT,
                    FOREIGN KEY (session_id) REFERENCES codex_sessions(id)
                );
                CREATE TABLE IF NOT EXISTS execution_processes (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Running',
                    exit_code INTEGER,
                    started_at TEXT,
                    completed_at TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    kind TEXT NOT NULL DEFAULT 'initial',
                    triggering_message_id TEXT,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    cache_read_tokens INTEGER,
                    total_cost_usd REAL,
                    FOREIGN KEY (task_id) REFERENCES codex_tasks(id),
                    FOREIGN KEY (session_id) REFERENCES codex_sessions(id)
                );
                CREATE TABLE IF NOT EXISTS help_requests (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    parent_task_id TEXT NOT NULL,
                    child_task_id TEXT NOT NULL,
                    source_executor TEXT NOT NULL,
                    target_executor TEXT NOT NULL,
                    title TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    context_summary TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    continuation_payload TEXT,
                    created_at TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    timeout_at TEXT,
                    consumed_at TEXT
                );
            """)
            # Add created_at column to existing tables if not present (backward compatibility)
            for table in ["tasks", "runs", "artifacts", "messages", "approvals", "approval_events"]:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN created_at TEXT")
                except sqlite3.OperationalError:
                    pass  # Column already exists
            # Add thread_id column to codex_sessions for session resume support
            try:
                conn.execute("ALTER TABLE codex_sessions ADD COLUMN thread_id TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE codex_sessions ADD COLUMN claude_thread_id TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE codex_sessions ADD COLUMN project_id TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE codex_sessions ADD COLUMN settings_json TEXT")
            except sqlite3.OperationalError:
                pass
            # Add task_id column to log_events for task-scoped log attribution
            try:
                conn.execute("ALTER TABLE log_events ADD COLUMN task_id TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE codex_task_messages ADD COLUMN execution_process_id TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE log_events ADD COLUMN execution_process_id TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            # Add executor column to codex_tasks for dual-executor support
            try:
                conn.execute("ALTER TABLE codex_tasks ADD COLUMN phase TEXT DEFAULT 'requirements'")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE codex_tasks ADD COLUMN issue_id TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE codex_tasks ADD COLUMN role TEXT DEFAULT 'general'")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE codex_tasks ADD COLUMN executor TEXT DEFAULT 'codex'")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE codex_tasks ADD COLUMN resume_session_id TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE codex_tasks ADD COLUMN resume_message_id TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE codex_tasks ADD COLUMN workspace_path TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE codex_tasks ADD COLUMN last_execution_process_id TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE codex_tasks ADD COLUMN task_kind TEXT DEFAULT 'normal'")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE codex_tasks ADD COLUMN blocked_by_help_id TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            # Add provider and model columns to codex_tasks
            try:
                conn.execute("ALTER TABLE codex_tasks ADD COLUMN provider TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE codex_tasks ADD COLUMN model TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE codex_tasks ADD COLUMN result_json TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE agents ADD COLUMN agent_tier TEXT DEFAULT 'managed'")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE codex_issues ADD COLUMN project_id TEXT")
            except sqlite3.OperationalError:
                pass
            for _issue_exec_col in ("executor", "provider", "model"):
                try:
                    conn.execute(f"ALTER TABLE codex_issues ADD COLUMN {_issue_exec_col} TEXT")
                except sqlite3.OperationalError:
                    pass
            # Per-issue cost budget (cost-aware conductor scheduling, PR2)
            try:
                conn.execute("ALTER TABLE codex_issues ADD COLUMN budget_usd REAL")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE codex_issues ADD COLUMN review_comment TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE codex_issues ADD COLUMN milestone TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE codex_issues ADD COLUMN git_branch TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE codex_issues ADD COLUMN git_base_branch TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE codex_issues ADD COLUMN git_worktree_path TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE codex_issues ADD COLUMN git_merge_status TEXT DEFAULT 'open'")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE codex_issues ADD COLUMN git_last_commit_sha TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE codex_issues ADD COLUMN github_pr_url TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE codex_issues ADD COLUMN github_pr_state TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE codex_issues ADD COLUMN is_pinned INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            # Add executor/provider/model snapshot columns to execution_processes
            try:
                conn.execute("ALTER TABLE execution_processes ADD COLUMN executor TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE execution_processes ADD COLUMN provider TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE execution_processes ADD COLUMN model TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE execution_processes ADD COLUMN kind TEXT NOT NULL DEFAULT 'initial'")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE execution_processes ADD COLUMN triggering_message_id TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE codex_tasks ADD COLUMN sequence_index INTEGER")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE codex_tasks ADD COLUMN sequence_group TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE codex_tasks ADD COLUMN review_comment TEXT")
            except sqlite3.OperationalError:
                pass
            # Add token usage and cost columns to execution_processes
            try:
                conn.execute("ALTER TABLE execution_processes ADD COLUMN input_tokens INTEGER")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE execution_processes ADD COLUMN output_tokens INTEGER")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE execution_processes ADD COLUMN cache_read_tokens INTEGER")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE execution_processes ADD COLUMN total_cost_usd REAL")
            except sqlite3.OperationalError:
                pass
            # Create runtime_catalog_settings table if not exists
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runtime_catalog_settings (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                )
            """)
            # Create artifact_paths table for tracking written artifacts
            conn.execute("""
                CREATE TABLE IF NOT EXISTS artifact_paths (
                    id TEXT PRIMARY KEY,
                    issue_id TEXT NOT NULL,
                    task_id TEXT,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    created_at TEXT,
                    UNIQUE(issue_id, name)
                )
            """)
            # --- Workflow DAG tables (PR1) ---
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT,
                    name TEXT NOT NULL,
                    role_key TEXT NOT NULL,
                    description TEXT,
                    system_prompt_template TEXT NOT NULL,
                    input_schema TEXT,
                    output_schema TEXT,
                    default_executor TEXT,
                    default_provider TEXT,
                    default_model TEXT,
                    artifact_subdir TEXT,
                    persist_kind TEXT,
                    agent_tier TEXT DEFAULT 'managed',
                    triggers_replan_on_done INTEGER NOT NULL DEFAULT 0,
                    triggers_replan_on_fail INTEGER NOT NULL DEFAULT 0,
                    is_builtin INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT,
                    updated_at TEXT,
                    UNIQUE(workspace_id, role_key)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS workflow_graphs (
                    id TEXT PRIMARY KEY,
                    issue_id TEXT NOT NULL,
                    preset_id TEXT,
                    status TEXT NOT NULL DEFAULT 'draft',
                    dag_json TEXT NOT NULL,
                    created_by TEXT,
                    locked_at TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    FOREIGN KEY (issue_id) REFERENCES codex_issues(id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS workflow_nodes (
                    id TEXT PRIMARY KEY,
                    graph_id TEXT NOT NULL,
                    node_key TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    title TEXT,
                    prompt_override TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    task_id TEXT,
                    artifact_dir TEXT,
                    retries INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 1,
                    instance_index INTEGER NOT NULL DEFAULT 0,
                    batch_key TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    UNIQUE(graph_id, node_key),
                    FOREIGN KEY (graph_id) REFERENCES workflow_graphs(id),
                    FOREIGN KEY (agent_id) REFERENCES agents(id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS workflow_edges (
                    id TEXT PRIMARY KEY,
                    graph_id TEXT NOT NULL,
                    from_node_key TEXT NOT NULL,
                    to_node_key TEXT NOT NULL,
                    edge_type TEXT NOT NULL DEFAULT 'sequence',
                    condition_expr TEXT,
                    created_at TEXT,
                    UNIQUE(graph_id, from_node_key, to_node_key, edge_type),
                    FOREIGN KEY (graph_id) REFERENCES workflow_graphs(id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS workflow_presets (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    dag_template_json TEXT NOT NULL,
                    is_builtin INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS graph_replan_pending (
                    id TEXT PRIMARY KEY,
                    graph_id TEXT NOT NULL,
                    triggered_by_node_key TEXT NOT NULL,
                    trigger_reason TEXT NOT NULL,
                    diff_json TEXT NOT NULL,
                    rationale TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT,
                    resolved_at TEXT,
                    FOREIGN KEY (graph_id) REFERENCES workflow_graphs(id)
                )
            """)
            try:
                conn.execute("ALTER TABLE codex_tasks ADD COLUMN workflow_node_id TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            # Knowledge stack: FTS5 virtual tables + embedding stores + team-notes state
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS issues_fts USING fts5(
                    issue_id UNINDEXED,
                    project_id UNINDEXED,
                    title,
                    description,
                    tokenize='porter unicode61'
                )
            """)
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS artifacts_fts USING fts5(
                    artifact_id UNINDEXED,
                    issue_id UNINDEXED,
                    project_id UNINDEXED,
                    role UNINDEXED,
                    name,
                    content,
                    tokenize='porter unicode61'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS artifact_embeddings (
                    artifact_id TEXT PRIMARY KEY,
                    vector BLOB NOT NULL,
                    model TEXT NOT NULL,
                    dim INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS issue_embeddings (
                    issue_id TEXT PRIMARY KEY,
                    vector BLOB NOT NULL,
                    model TEXT NOT NULL,
                    dim INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS team_notes_state (
                    project_id TEXT NOT NULL,
                    block_id TEXT NOT NULL,
                    deleted_at TEXT,
                    pinned INTEGER DEFAULT 0,
                    PRIMARY KEY (project_id, block_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_messages (
                    id TEXT PRIMARY KEY,
                    issue_id TEXT NOT NULL,
                    graph_id TEXT NOT NULL,
                    from_node_key TEXT NOT NULL,
                    to_node_key TEXT NOT NULL,
                    message_type TEXT NOT NULL DEFAULT 'handoff',
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conductor_decisions (
                    id TEXT PRIMARY KEY,
                    issue_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    reason TEXT,
                    diff_json TEXT,
                    applied_at TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conductor_states (
                    issue_id TEXT PRIMARY KEY,
                    running_thread_json TEXT NOT NULL DEFAULT '[]',
                    pending_dispatches_json TEXT NOT NULL DEFAULT '[]',
                    scratchpad TEXT NOT NULL DEFAULT '',
                    decision_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS project_conductor_states (
                    project_id TEXT PRIMARY KEY,
                    hot_thread_json TEXT NOT NULL DEFAULT '[]',
                    warm_summaries_json TEXT NOT NULL DEFAULT '[]',
                    pinned_text TEXT NOT NULL DEFAULT '',
                    hot_tokens INTEGER NOT NULL DEFAULT 0,
                    warm_tokens INTEGER NOT NULL DEFAULT 0,
                    last_compaction_at TEXT,
                    total_tasks_handled INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conductor_tasks (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    task_kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    issue_id TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    result_json TEXT,
                    lease_owner TEXT,
                    heartbeat_at TEXT,
                    lease_expires_at TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conductor_turns (
                    id TEXT PRIMARY KEY,
                    conductor_task_id TEXT NOT NULL,
                    issue_id TEXT NOT NULL,
                    turn_index INTEGER NOT NULL,
                    sub_index INTEGER NOT NULL DEFAULT 0,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    consumed_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conductor_state_log (
                    id TEXT PRIMARY KEY,
                    issue_id TEXT NOT NULL,
                    from_phase TEXT,
                    to_phase TEXT NOT NULL,
                    from_detail TEXT,
                    to_detail TEXT,
                    transition_at TEXT NOT NULL,
                    duration_ms INTEGER,
                    is_legal INTEGER NOT NULL DEFAULT 1
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS project_memory_embeddings (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    summary_text TEXT NOT NULL,
                    vector_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS self_improvement_proposals (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    issue_id TEXT NOT NULL,
                    target_kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    recommendation TEXT NOT NULL,
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    severity TEXT NOT NULL DEFAULT 'info',
                    confidence REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'proposed',
                    fingerprint TEXT NOT NULL UNIQUE,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            # Unified audit trail (PR1). One row per LLM call/return, tool use/result,
            # command exec, git command, CLI spawn, generic event, or agent finalize.
            # Line-level stdout/stderr stays in log_events (joined via
            # execution_process_id), not mirrored here.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    category TEXT NOT NULL,
                    actor TEXT,
                    issue_id TEXT,
                    task_id TEXT,
                    conductor_task_id TEXT,
                    execution_process_id TEXT,
                    correlation_id TEXT,
                    status TEXT,
                    duration_ms INTEGER,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT
                )
            """)
            # Create indexes for frequently queried columns
            conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_tasks_session_id ON codex_tasks(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_tasks_issue_id ON codex_tasks(issue_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_tasks_parent_task_id ON codex_tasks(parent_task_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_tasks_status ON codex_tasks(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_tasks_task_kind ON codex_tasks(task_kind)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_issues_session_id ON codex_issues(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_task_messages_task_id ON codex_task_messages(task_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_task_messages_execution_process_id ON codex_task_messages(execution_process_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_log_events_session_id ON log_events(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_log_events_task_id ON log_events(task_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_log_events_execution_process_id ON log_events(execution_process_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_execution_processes_session_id ON execution_processes(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_execution_processes_task_id ON execution_processes(task_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_help_requests_parent_task_id ON help_requests(parent_task_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_help_requests_child_task_id ON help_requests(child_task_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_help_requests_workspace_id ON help_requests(workspace_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_artifact_paths_issue_id ON artifact_paths(issue_id)")
            # Workflow DAG indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_role_key ON agents(role_key)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_workspace_id ON agents(workspace_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_graphs_issue_id ON workflow_graphs(issue_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_nodes_graph_id ON workflow_nodes(graph_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_nodes_status ON workflow_nodes(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_nodes_task_id ON workflow_nodes(task_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_edges_graph_id ON workflow_edges(graph_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_graph_replan_pending_graph_id ON graph_replan_pending(graph_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_graph_replan_pending_status ON graph_replan_pending(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_tasks_workflow_node_id ON codex_tasks(workflow_node_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_messages_issue_id ON agent_messages(issue_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_messages_graph_id ON agent_messages(graph_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conductor_decisions_issue_id ON conductor_decisions(issue_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conductor_decisions_task_id ON conductor_decisions(task_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conductor_tasks_project_id ON conductor_tasks(project_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conductor_tasks_status ON conductor_tasks(status)")
            for stmt in (
                "ALTER TABLE conductor_tasks ADD COLUMN lease_owner TEXT",
                "ALTER TABLE conductor_tasks ADD COLUMN heartbeat_at TEXT",
                "ALTER TABLE conductor_tasks ADD COLUMN lease_expires_at TEXT",
            ):
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError:
                    pass
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conductor_tasks_lease ON conductor_tasks(status, lease_expires_at)")
            # Phase 4: add instance_index to workflow_nodes for existing DBs
            try:
                conn.execute(
                    "ALTER TABLE workflow_nodes ADD COLUMN instance_index INTEGER NOT NULL DEFAULT 0"
                )
            except sqlite3.OperationalError:
                pass
            # Parallel swarm: add batch_key to group nodes from one dispatch_batch call
            try:
                conn.execute(
                    "ALTER TABLE workflow_nodes ADD COLUMN batch_key TEXT"
                )
            except sqlite3.OperationalError:
                pass
            # Must run BEFORE idx_conductor_turns_inbox below; the index
            # references consumed_at, and on an existing DB without the column
            # the CREATE INDEX otherwise raises sqlite3.OperationalError and
            # tanks the whole _init_db().
            try:
                conn.execute("ALTER TABLE conductor_turns ADD COLUMN consumed_at TEXT")
            except sqlite3.OperationalError:
                pass
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conductor_turns_task_turn ON conductor_turns(conductor_task_id, turn_index, sub_index)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conductor_turns_issue_created ON conductor_turns(issue_id, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conductor_turns_inbox ON conductor_turns(conductor_task_id, kind, consumed_at, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conductor_state_log_issue_transition ON conductor_state_log(issue_id, transition_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_project_memory_embeddings_project_id ON project_memory_embeddings(project_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_self_improvement_project_created ON self_improvement_proposals(project_id, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_self_improvement_issue ON self_improvement_proposals(issue_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_self_improvement_status ON self_improvement_proposals(status)")
            # Audit log filter/pagination indexes (PR3 read API will lean on these).
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_issue_created ON audit_log(issue_id, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_category_created ON audit_log(category, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_task_id ON audit_log(task_id)")
            conn.commit()
        except sqlite3.Error as e:
            logger.error("Database initialization error: %s", e)
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def _ensure_db(self):
        """Re-run schema creation so callers never hit a missing-table error."""
        self._init_db()

    def _format_datetime(self, dt: datetime | None) -> str | None:
        """Format datetime for SQLite storage."""
        return dt.isoformat() if dt else None

    def _parse_datetime(self, s: str | None) -> datetime | None:
        """Parse datetime from SQLite storage."""
        return datetime.fromisoformat(s) if s else None

    def save_session(self, session: Session):
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO sessions (id, title, state) VALUES (?, ?, ?)",
                (session.id, session.title, session.state.value),
            )
            for task in session.tasks:
                conn.execute(
                    "INSERT OR REPLACE INTO tasks (id, session_id, title, assignee, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (task.id, session.id, task.title, task.assignee, task.status, self._format_datetime(task.created_at)),
                )
            for run in session.runs:
                conn.execute(
                    "INSERT OR REPLACE INTO runs (id, task_id, agent_id, role, status, summary, payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (run.id, run.task_id, run.agent_id, run.role, run.status, run.summary, json.dumps(run.payload) if run.payload else None, self._format_datetime(run.created_at)),
                )
            for artifact in session.artifacts:
                content = artifact.content
                if hasattr(content, "model_dump"):
                    content = json.dumps(content.model_dump())
                elif not isinstance(content, str):
                    content = json.dumps(content)
                conn.execute(
                    "INSERT OR REPLACE INTO artifacts (id, task_id, kind, content, steps, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (artifact.id, artifact.task_id, artifact.kind, content, json.dumps(artifact.steps) if artifact.steps else None, self._format_datetime(artifact.created_at)),
                )
            for message in session.messages:
                conn.execute(
                    "INSERT OR REPLACE INTO messages (id, task_id, agent_id, role, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (message.id, message.task_id, message.agent_id, message.role, message.content, self._format_datetime(message.created_at)),
                )
            for approval in session.approvals:
                conn.execute(
                    "INSERT OR REPLACE INTO approvals (id, session_id, task_id, action, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (approval.id, approval.session_id, approval.task_id, approval.action, approval.status, self._format_datetime(approval.created_at)),
                )
            for event in session.approval_events:
                conn.execute(
                    "INSERT OR REPLACE INTO approval_events (id, session_id, task_id, approval_id, event_type, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (event.id, event.session_id, event.task_id, event.approval_id, event.event_type, self._format_datetime(event.created_at)),
                )
            conn.commit()
        except sqlite3.Error as e:
            logger.error("Database error saving session %s: %s", session.id, e)
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def load_session(self, session_id: str) -> Session | None:
        conn = self._get_conn()
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            row = cur.fetchone()
            if not row:
                conn.close()
                return None

            session = Session(
                id=row["id"],
                title=row["title"],
                state=row["state"],
            )

            # Load tasks
            for t_row in conn.execute("SELECT * FROM tasks WHERE session_id = ?", (session_id,)):
                session.tasks.append(Task(
                    id=t_row["id"],
                    session_id=t_row["session_id"],
                    title=t_row["title"],
                    assignee=t_row["assignee"],
                    status=t_row["status"],
                    created_at=self._parse_datetime(t_row["created_at"]),
                ))

            # Load runs
            for r_row in conn.execute("SELECT * FROM runs WHERE task_id IN (SELECT id FROM tasks WHERE session_id = ?)", (session_id,)):
                session.runs.append(AgentRun(
                    id=r_row["id"],
                    task_id=r_row["task_id"],
                    agent_id=r_row["agent_id"],
                    role=r_row["role"],
                    status=r_row["status"],
                    summary=r_row["summary"],
                    payload=json.loads(r_row["payload"]) if r_row["payload"] else None,
                    created_at=self._parse_datetime(r_row["created_at"]),
                ))

            # Load artifacts
            for a_row in conn.execute("SELECT * FROM artifacts WHERE task_id IN (SELECT id FROM tasks WHERE session_id = ?)", (session_id,)):
                content = a_row["content"]
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict):
                        content = PlanDetails(**parsed)
                    else:
                        content = parsed
                except (json.JSONDecodeError, TypeError):
                    pass
                session.artifacts.append(Artifact(
                    id=a_row["id"],
                    task_id=a_row["task_id"],
                    kind=a_row["kind"],
                    content=content,
                    steps=json.loads(a_row["steps"]) if a_row["steps"] else None,
                    created_at=self._parse_datetime(a_row["created_at"]),
                ))

            # Load messages
            for m_row in conn.execute("SELECT * FROM messages WHERE task_id IN (SELECT id FROM tasks WHERE session_id = ?)", (session_id,)):
                session.messages.append(Message(
                    id=m_row["id"],
                    task_id=m_row["task_id"],
                    agent_id=m_row["agent_id"],
                    role=m_row["role"],
                    content=m_row["content"],
                    created_at=self._parse_datetime(m_row["created_at"]),
                ))

            # Load approvals
            for ap_row in conn.execute("SELECT * FROM approvals WHERE session_id = ?", (session_id,)):
                session.approvals.append(Approval(
                    id=ap_row["id"],
                    session_id=ap_row["session_id"],
                    task_id=ap_row["task_id"],
                    action=ap_row["action"],
                    status=ap_row["status"],
                    created_at=self._parse_datetime(ap_row["created_at"]),
                ))

            # Load approval events
            for ev_row in conn.execute("SELECT * FROM approval_events WHERE session_id = ?", (session_id,)):
                session.approval_events.append(ApprovalEvent(
                    id=ev_row["id"],
                    session_id=ev_row["session_id"],
                    task_id=ev_row["task_id"],
                    approval_id=ev_row["approval_id"],
                    event_type=ev_row["event_type"],
                    created_at=self._parse_datetime(ev_row["created_at"]),
                ))

            conn.close()
            return session
        except sqlite3.Error as e:
            logger.error("Database error loading session %s: %s", session_id, e)
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            raise

    def list_sessions(self) -> list[dict]:
        """List all sessions with id, title, state."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, title, state FROM sessions").fetchall()
        conn.close()
        return [{"id": r["id"], "title": r["title"], "state": r["state"]} for r in rows]

    # --- Codex Session persistence ---

    def save_codex_session(self, session: CodexSession):
        self._ensure_db()
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO codex_sessions (id, title, cwd, project_id, status, created_at, last_active_at, log_path, thread_id, claude_thread_id, settings_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session.id, session.title, session.cwd, session.project_id, session.status,
                 self._format_datetime(session.created_at),
                 self._format_datetime(session.last_active_at),
                 session.log_path,
                 session.thread_id,
                 session.claude_thread_id,
                 json.dumps(session.settings, ensure_ascii=False) if getattr(session, "settings", None) is not None else None),
            )
            # Persist messages
            conn.execute("DELETE FROM codex_messages WHERE session_id = ?", (session.id,))
            for msg in session.messages:
                conn.execute(
                    "INSERT INTO codex_messages (id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                    (msg.id, msg.session_id, msg.role, msg.content, self._format_datetime(msg.created_at)),
                )
            conn.commit()
        except sqlite3.Error as e:
            logger.error("Database error saving codex session %s: %s", session.id, e)
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def save_codex_workspace(self, workspace: CodexSession):
        self.save_codex_session(workspace)

    def load_codex_session(self, session_id: str) -> CodexSession | None:
        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM codex_sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            conn.close()
            return None
        # Load messages for this session
        msg_rows = conn.execute(
            "SELECT * FROM codex_messages WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
        messages = [
            CodexMessage(
                id=r["id"],
                session_id=r["session_id"],
                role=r["role"],
                content=r["content"],
                created_at=self._parse_datetime(r["created_at"]),
            )
            for r in msg_rows
        ]
        conn.close()
        return CodexSession(
            id=row["id"],
            title=row["title"],
            cwd=row["cwd"],
            project_id=row["project_id"] if "project_id" in row.keys() else None,
            status=row["status"],
            created_at=self._parse_datetime(row["created_at"]),
            last_active_at=self._parse_datetime(row["last_active_at"]),
            log_path=row["log_path"],
            thread_id=row["thread_id"] if "thread_id" in row.keys() else None,
            claude_thread_id=row["claude_thread_id"] if "claude_thread_id" in row.keys() else None,
            settings=json.loads(row["settings_json"]) if "settings_json" in row.keys() and row["settings_json"] else {"plan_first_pm": True},
            messages=messages,
        )

    def load_codex_workspace(self, workspace_id: str) -> CodexSession | None:
        return self.load_codex_session(workspace_id)

    def list_codex_sessions(self) -> list[dict]:
        """List all codex sessions with id, title, status, created_at, last_active_at."""
        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, title, project_id, status, created_at, last_active_at, settings_json FROM codex_sessions ORDER BY last_active_at DESC").fetchall()
        conn.close()
        return [{"id": r["id"], "title": r["title"], "project_id": r["project_id"], "status": r["status"],
                 "created_at": r["created_at"], "last_active_at": r["last_active_at"],
                 "settings": json.loads(r["settings_json"]) if r["settings_json"] else {"plan_first_pm": True}}
                for r in rows]

    def list_codex_workspaces(self) -> list[dict]:
        return self.list_codex_sessions()

    def delete_codex_session(self, session_id: str):
        """Delete a codex session and all its related records in proper cascade order."""
        self._ensure_db()
        conn = self._get_conn()
        # Delete help_requests for this workspace first (references tasks)
        conn.execute("DELETE FROM help_requests WHERE workspace_id = ?", (session_id,))
        # Delete task messages for all tasks in this session (FK to tasks)
        conn.execute(
            "DELETE FROM codex_task_messages WHERE task_id IN (SELECT id FROM codex_tasks WHERE session_id = ?)",
            (session_id,),
        )
        # Delete execution processes for tasks in this session (FK to tasks)
        conn.execute(
            "DELETE FROM execution_processes WHERE task_id IN (SELECT id FROM codex_tasks WHERE session_id = ?)",
            (session_id,),
        )
        # Delete log events for tasks in this session (FK to tasks, not just session_id)
        conn.execute(
            "DELETE FROM log_events WHERE task_id IN (SELECT id FROM codex_tasks WHERE session_id = ?)",
            (session_id,),
        )
        # Delete issues (session-level, no task dependencies)
        conn.execute("DELETE FROM codex_issues WHERE session_id = ?", (session_id,))
        # Delete tasks (now no task-level dependents remain)
        conn.execute("DELETE FROM codex_tasks WHERE session_id = ?", (session_id,))
        # Delete session-level records (no FK dependencies remain)
        conn.execute("DELETE FROM codex_messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM log_events WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM codex_sessions WHERE id = ?", (session_id,))
        conn.commit()
        conn.close()

    def delete_codex_issue(self, issue_id: str):
        """Delete a codex issue record."""
        self._ensure_db()
        conn = self._get_conn()
        conn.execute("DELETE FROM codex_issues WHERE id = ?", (issue_id,))
        conn.commit()
        conn.close()

    def delete_codex_workspace(self, workspace_id: str):
        self.delete_codex_session(workspace_id)

    def save_codex_issue(self, issue: CodexIssue):
        self._ensure_db()
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO codex_issues (id, session_id, project_id, title, description, current_phase, status, review_comment, is_pinned, milestone, git_branch, git_base_branch, git_worktree_path, git_merge_status, git_last_commit_sha, github_pr_url, github_pr_state, executor, provider, model, budget_usd, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                issue.id,
                issue.session_id,
                issue.project_id,
                issue.title,
                issue.description,
                issue.current_phase,
                issue.status,
                issue.review_comment,
                1 if issue.is_pinned else 0,
                issue.milestone,
                issue.git_branch,
                issue.git_base_branch,
                issue.git_worktree_path,
                issue.git_merge_status,
                issue.git_last_commit_sha,
                getattr(issue, "github_pr_url", None),
                getattr(issue, "github_pr_state", None),
                getattr(issue, "executor", None),
                getattr(issue, "provider", None),
                getattr(issue, "model", None),
                getattr(issue, "budget_usd", None),
                self._format_datetime(issue.created_at),
                self._format_datetime(issue.updated_at),
            ),
        )
        conn.commit()
        conn.close()

    def load_codex_issue(self, issue_id: str) -> CodexIssue | None:
        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM codex_issues WHERE id = ?", (issue_id,)).fetchone()
        conn.close()
        if not row:
            return None
        return CodexIssue(
            id=row["id"],
            session_id=row["session_id"],
            project_id=row["project_id"] if "project_id" in row.keys() else None,
            title=row["title"],
            description=row["description"],
            current_phase=row["current_phase"],
            status=row["status"],
            review_comment=row["review_comment"] if "review_comment" in row.keys() else None,
            is_pinned=bool(row["is_pinned"]),
            milestone=row["milestone"] if "milestone" in row.keys() and row["milestone"] else None,
            git_branch=row["git_branch"] if "git_branch" in row.keys() and row["git_branch"] else None,
            git_base_branch=row["git_base_branch"] if "git_base_branch" in row.keys() and row["git_base_branch"] else None,
            git_worktree_path=row["git_worktree_path"] if "git_worktree_path" in row.keys() and row["git_worktree_path"] else None,
            git_merge_status=row["git_merge_status"] if "git_merge_status" in row.keys() and row["git_merge_status"] else "open",
            git_last_commit_sha=row["git_last_commit_sha"] if "git_last_commit_sha" in row.keys() and row["git_last_commit_sha"] else None,
            github_pr_url=row["github_pr_url"] if "github_pr_url" in row.keys() and row["github_pr_url"] else None,
            github_pr_state=row["github_pr_state"] if "github_pr_state" in row.keys() and row["github_pr_state"] else None,
            executor=row["executor"] if "executor" in row.keys() and row["executor"] else None,
            provider=row["provider"] if "provider" in row.keys() and row["provider"] else None,
            model=row["model"] if "model" in row.keys() and row["model"] else None,
            budget_usd=row["budget_usd"] if "budget_usd" in row.keys() and row["budget_usd"] is not None else None,
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def list_codex_issues(self, session_id: str | None = None) -> list[dict]:
        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        select_sql = "SELECT id, session_id, project_id, title, description, current_phase, status, review_comment, is_pinned, milestone, git_branch, git_base_branch, git_worktree_path, git_merge_status, git_last_commit_sha, github_pr_url, github_pr_state, budget_usd, created_at, updated_at FROM codex_issues"
        if session_id:
            rows = conn.execute(f"{select_sql} WHERE session_id = ? ORDER BY is_pinned DESC, updated_at DESC, created_at DESC", (session_id,)).fetchall()
        else:
            rows = conn.execute(f"{select_sql} ORDER BY is_pinned DESC, updated_at DESC, created_at DESC").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # --- Codex Tasks ---

    def save_codex_task(self, task: CodexTask):
        self._ensure_db()
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO codex_tasks (id, session_id, issue_id, phase, title, prompt, role, executor, provider, model, status, result, result_json, parent_task_id, task_kind, blocked_by_help_id, workspace_path, resume_session_id, resume_message_id, last_execution_process_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (task.id, task.session_id, task.issue_id, task.phase, task.title, task.prompt, task.role, task.executor,
             task.provider, task.model, task.status, task.result, task.result_json, task.parent_task_id, task.task_kind, task.blocked_by_help_id,
             task.workspace_path, task.resume_session_id, task.resume_message_id, task.last_execution_process_id,
             self._format_datetime(task.created_at),
             self._format_datetime(task.updated_at)),
        )
        conn.commit()
        conn.close()

    def load_codex_task(self, task_id: str) -> CodexTask | None:
        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM codex_tasks WHERE id = ?", (task_id,)).fetchone()
        conn.close()
        if not row:
            return None
        return CodexTask(
            id=row["id"],
            session_id=row["session_id"],
            issue_id=row["issue_id"] if "issue_id" in row.keys() and row["issue_id"] else None,
            phase=row["phase"] if "phase" in row.keys() and row["phase"] else "requirements",
            title=row["title"],
            prompt=row["prompt"],
            role=row["role"] if "role" in row.keys() and row["role"] else "general",
            executor=row["executor"] if row["executor"] else "codex",
            provider=row["provider"] if "provider" in row.keys() and row["provider"] else None,
            model=row["model"] if "model" in row.keys() and row["model"] else None,
            status=row["status"],
            result=row["result"],
            result_json=row["result_json"] if "result_json" in row.keys() and row["result_json"] else None,
            parent_task_id=row["parent_task_id"] if row["parent_task_id"] else None,
            task_kind=row["task_kind"] if "task_kind" in row.keys() and row["task_kind"] else "normal",
            blocked_by_help_id=row["blocked_by_help_id"] if "blocked_by_help_id" in row.keys() and row["blocked_by_help_id"] else None,
            workspace_path=row["workspace_path"] if "workspace_path" in row.keys() and row["workspace_path"] else None,
            resume_session_id=row["resume_session_id"] if "resume_session_id" in row.keys() and row["resume_session_id"] else None,
            resume_message_id=row["resume_message_id"] if "resume_message_id" in row.keys() and row["resume_message_id"] else None,
            last_execution_process_id=row["last_execution_process_id"] if "last_execution_process_id" in row.keys() and row["last_execution_process_id"] else None,
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def list_codex_tasks(self, session_id: str | None = None, issue_id: str | None = None) -> list[dict]:
        """List tasks, optionally filtered by session_id."""
        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        select_sql = "SELECT id, session_id, issue_id, phase, title, prompt, role, executor, provider, model, status, result, result_json, parent_task_id, task_kind, blocked_by_help_id, workspace_path, resume_session_id, resume_message_id, last_execution_process_id, created_at, updated_at FROM codex_tasks"
        if session_id and issue_id:
            rows = conn.execute(
                f"{select_sql} WHERE session_id = ? AND issue_id = ? ORDER BY created_at ASC",
                (session_id, issue_id),
            ).fetchall()
        elif session_id:
            rows = conn.execute(
                f"{select_sql} WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
        elif issue_id:
            rows = conn.execute(
                f"{select_sql} WHERE issue_id = ? ORDER BY created_at ASC",
                (issue_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                f"{select_sql} ORDER BY created_at ASC",
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def save_help_request(self, help_request: HelpRequest):
        self._ensure_db()
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO help_requests (
                id, workspace_id, parent_task_id, child_task_id, source_executor, target_executor,
                title, prompt, context_summary, status, error_message, continuation_payload,
                created_at, started_at, completed_at, timeout_at, consumed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                help_request.id,
                help_request.workspace_id,
                help_request.parent_task_id,
                help_request.child_task_id,
                help_request.source_executor,
                help_request.target_executor,
                help_request.title,
                help_request.prompt,
                help_request.context_summary,
                help_request.status,
                help_request.error_message,
                json.dumps(help_request.continuation_payload) if help_request.continuation_payload is not None else None,
                self._format_datetime(help_request.created_at),
                self._format_datetime(help_request.started_at),
                self._format_datetime(help_request.completed_at),
                self._format_datetime(help_request.timeout_at),
                self._format_datetime(help_request.consumed_at),
            ),
        )
        conn.commit()
        conn.close()

    def load_help_request(self, help_request_id: str) -> HelpRequest | None:
        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM help_requests WHERE id = ?", (help_request_id,)).fetchone()
        conn.close()
        if not row:
            return None
        continuation_payload = json.loads(row["continuation_payload"]) if row["continuation_payload"] else None
        return HelpRequest(
            id=row["id"],
            workspace_id=row["workspace_id"],
            parent_task_id=row["parent_task_id"],
            child_task_id=row["child_task_id"],
            source_executor=row["source_executor"],
            target_executor=row["target_executor"],
            title=row["title"],
            prompt=row["prompt"],
            context_summary=row["context_summary"],
            status=row["status"],
            error_message=row["error_message"],
            continuation_payload=continuation_payload,
            created_at=self._parse_datetime(row["created_at"]),
            started_at=self._parse_datetime(row["started_at"]),
            completed_at=self._parse_datetime(row["completed_at"]),
            timeout_at=self._parse_datetime(row["timeout_at"]),
            consumed_at=self._parse_datetime(row["consumed_at"]),
        )

    def list_help_requests(self, *, parent_task_id: str | None = None, child_task_id: str | None = None) -> list[HelpRequest]:
        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        if parent_task_id:
            rows = conn.execute(
                "SELECT * FROM help_requests WHERE parent_task_id = ? ORDER BY created_at ASC",
                (parent_task_id,),
            ).fetchall()
        elif child_task_id:
            rows = conn.execute(
                "SELECT * FROM help_requests WHERE child_task_id = ? ORDER BY created_at ASC",
                (child_task_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM help_requests ORDER BY created_at ASC").fetchall()
        conn.close()
        return [
            HelpRequest(
                id=row["id"],
                workspace_id=row["workspace_id"],
                parent_task_id=row["parent_task_id"],
                child_task_id=row["child_task_id"],
                source_executor=row["source_executor"],
                target_executor=row["target_executor"],
                title=row["title"],
                prompt=row["prompt"],
                context_summary=row["context_summary"],
                status=row["status"],
                error_message=row["error_message"],
                continuation_payload=json.loads(row["continuation_payload"]) if row["continuation_payload"] else None,
                created_at=self._parse_datetime(row["created_at"]),
                started_at=self._parse_datetime(row["started_at"]),
                completed_at=self._parse_datetime(row["completed_at"]),
                timeout_at=self._parse_datetime(row["timeout_at"]),
                consumed_at=self._parse_datetime(row["consumed_at"]),
            )
            for row in rows
        ]

    def delete_codex_task(self, task_id: str):
        self._ensure_db()
        conn = self._get_conn()
        conn.execute(
            "DELETE FROM help_requests WHERE parent_task_id = ? OR child_task_id = ?",
            (task_id, task_id),
        )
        conn.execute("DELETE FROM codex_task_messages WHERE task_id = ?", (task_id,))
        conn.execute("DELETE FROM execution_processes WHERE task_id = ?", (task_id,))
        conn.execute("DELETE FROM log_events WHERE task_id = ?", (task_id,))
        conn.execute("DELETE FROM codex_tasks WHERE id = ?", (task_id,))
        conn.commit()
        conn.close()

    def save_codex_task_message(self, message: CodexTaskMessage):
        self._ensure_db()
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO codex_task_messages (id, task_id, execution_process_id, role, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                message.id,
                message.task_id,
                message.execution_process_id,
                message.role,
                message.content,
                self._format_datetime(message.created_at),
            ),
        )
        conn.commit()
        conn.close()

    def list_codex_task_messages(
        self,
        task_id: str,
        execution_process_id: str | None = None,
    ) -> list[CodexTaskMessage]:
        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        if execution_process_id:
            rows = conn.execute(
                "SELECT * FROM codex_task_messages WHERE task_id = ? AND execution_process_id = ? ORDER BY created_at ASC",
                (task_id, execution_process_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM codex_task_messages WHERE task_id = ? ORDER BY created_at ASC",
                (task_id,),
            ).fetchall()
        conn.close()
        return [
            CodexTaskMessage(
                id=r["id"],
                task_id=r["task_id"],
                execution_process_id=r["execution_process_id"] if "execution_process_id" in r.keys() else None,
                role=r["role"],
                content=r["content"],
                created_at=self._parse_datetime(r["created_at"]),
            )
            for r in rows
        ]

    def reset(self):
        """Delete all data from all tables. Used by tests to isolate each test case."""
        conn = self._get_conn()
        for table in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            name = table[0]
            if name == "sqlite_sequence":
                continue
            # Skip FTS5 virtual table shadow tables to prevent corruption
            if name.startswith(("issues_fts_", "artifacts_fts_")):
                continue
            conn.execute(f"DELETE FROM {name}")
        conn.commit()
        conn.close()

    def append_log_event(self, event: LogEvent):
        self._ensure_db()
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO log_events (id, session_id, stream, content, task_id, execution_process_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                event.id,
                event.session_id,
                event.stream,
                event.content,
                event.task_id,
                event.execution_process_id,
                self._format_datetime(event.created_at),
            ),
        )
        conn.commit()
        conn.close()

    def load_log_events(
        self,
        session_id: str,
        task_id: str | None = None,
        execution_process_id: str | None = None,
        limit: int = 1000,
        reverse: bool = False,
    ) -> list[LogEvent]:
        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        order = "DESC" if reverse else "ASC"
        if execution_process_id and task_id:
            rows = conn.execute(
                f"SELECT * FROM log_events WHERE session_id = ? AND task_id = ? AND execution_process_id = ? ORDER BY created_at {order} LIMIT ?",
                (session_id, task_id, execution_process_id, limit),
            ).fetchall()
        elif execution_process_id:
            rows = conn.execute(
                f"SELECT * FROM log_events WHERE session_id = ? AND execution_process_id = ? ORDER BY created_at {order} LIMIT ?",
                (session_id, execution_process_id, limit),
            ).fetchall()
        elif task_id:
            rows = conn.execute(
                f"SELECT * FROM log_events WHERE session_id = ? AND task_id = ? ORDER BY created_at {order} LIMIT ?",
                (session_id, task_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM log_events WHERE session_id = ? ORDER BY created_at {order} LIMIT ?",
                (session_id, limit),
            ).fetchall()
        conn.close()
        return [
            LogEvent(
                id=r["id"],
                session_id=r["session_id"],
                stream=r["stream"],
                content=r["content"],
                task_id=r["task_id"] if "task_id" in r.keys() else None,
                execution_process_id=r["execution_process_id"] if "execution_process_id" in r.keys() else None,
                created_at=self._parse_datetime(r["created_at"]),
            )
            for r in rows
        ]

    # --- ExecutionProcess ---

    def save_execution_process(self, process: ExecutionProcess):
        """Create or update an ExecutionProcess record."""
        self._ensure_db()
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO execution_processes (id, task_id, session_id, status, exit_code, executor, provider, model, kind, triggering_message_id, input_tokens, output_tokens, cache_read_tokens, total_cost_usd, started_at, completed_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (process.id, process.task_id, process.session_id, process.status, process.exit_code,
             process.executor, process.provider, process.model,
             process.kind, process.triggering_message_id,
             process.input_tokens, process.output_tokens, process.cache_read_tokens, process.total_cost_usd,
             self._format_datetime(process.started_at),
             self._format_datetime(process.completed_at),
             self._format_datetime(process.created_at),
             self._format_datetime(process.updated_at)),
        )
        conn.commit()
        conn.close()

    def load_execution_process(self, process_id: str) -> ExecutionProcess | None:
        """Load an ExecutionProcess by id."""
        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM execution_processes WHERE id = ?", (process_id,)).fetchone()
        conn.close()
        if not row:
            return None
        return ExecutionProcess(
            id=row["id"],
            task_id=row["task_id"],
            session_id=row["session_id"],
            status=row["status"],
            exit_code=row["exit_code"],
            executor=row["executor"] if "executor" in row.keys() and row["executor"] else None,
            provider=row["provider"] if "provider" in row.keys() and row["provider"] else None,
            model=row["model"] if "model" in row.keys() and row["model"] else None,
            input_tokens=row["input_tokens"] if "input_tokens" in row.keys() else None,
            output_tokens=row["output_tokens"] if "output_tokens" in row.keys() else None,
            cache_read_tokens=row["cache_read_tokens"] if "cache_read_tokens" in row.keys() else None,
            total_cost_usd=row["total_cost_usd"] if "total_cost_usd" in row.keys() else None,
            kind=row["kind"] if "kind" in row.keys() and row["kind"] else "initial",
            triggering_message_id=row["triggering_message_id"] if "triggering_message_id" in row.keys() else None,
            started_at=self._parse_datetime(row["started_at"]),
            completed_at=self._parse_datetime(row["completed_at"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def list_execution_processes(self, session_id: str | None = None, task_id: str | None = None) -> list[ExecutionProcess]:
        """List execution processes, optionally filtered by session_id and/or task_id."""
        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        if session_id and task_id:
            rows = conn.execute(
                "SELECT * FROM execution_processes WHERE session_id = ? AND task_id = ? ORDER BY created_at DESC",
                (session_id, task_id),
            ).fetchall()
        elif session_id:
            rows = conn.execute(
                "SELECT * FROM execution_processes WHERE session_id = ? ORDER BY created_at DESC",
                (session_id,),
            ).fetchall()
        elif task_id:
            rows = conn.execute(
                "SELECT * FROM execution_processes WHERE task_id = ? ORDER BY created_at DESC",
                (task_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM execution_processes ORDER BY created_at DESC",
            ).fetchall()
        conn.close()
        return [
            ExecutionProcess(
                id=r["id"],
                task_id=r["task_id"],
                session_id=r["session_id"],
                status=r["status"],
                exit_code=r["exit_code"],
                executor=r["executor"] if "executor" in r.keys() and r["executor"] else None,
                provider=r["provider"] if "provider" in r.keys() and r["provider"] else None,
                model=r["model"] if "model" in r.keys() and r["model"] else None,
                input_tokens=r["input_tokens"] if "input_tokens" in r.keys() else None,
                output_tokens=r["output_tokens"] if "output_tokens" in r.keys() else None,
                cache_read_tokens=r["cache_read_tokens"] if "cache_read_tokens" in r.keys() else None,
                total_cost_usd=r["total_cost_usd"] if "total_cost_usd" in r.keys() else None,
                kind=r["kind"] if "kind" in r.keys() and r["kind"] else "initial",
                triggering_message_id=r["triggering_message_id"] if "triggering_message_id" in r.keys() else None,
                started_at=self._parse_datetime(r["started_at"]),
                completed_at=self._parse_datetime(r["completed_at"]),
                created_at=self._parse_datetime(r["created_at"]),
                updated_at=self._parse_datetime(r["updated_at"]),
            )
            for r in rows
        ]

    def list_execution_process_runtime_rows(self, session_id: str) -> list[tuple[ExecutionProcess, CodexTask | None, list[CodexTaskMessage], list[LogEvent]]]:
        processes = self.list_execution_processes(session_id=session_id)
        rows = []
        for process in processes:
            task = self.load_codex_task(process.task_id)
            messages = self.list_codex_task_messages(process.task_id, execution_process_id=process.id)
            logs = self.load_log_events(session_id, task_id=process.task_id, execution_process_id=process.id, limit=10000)
            rows.append((process, task, messages, logs))
        return rows

    def update_execution_process_status(self, process_id: str, status: str, exit_code: int | None = None, completed_at: datetime | None = None):
        """Update the status of an ExecutionProcess."""
        self._ensure_db()
        conn = self._get_conn()
        from datetime import datetime as dt
        now = dt.now()
        completed_at_value = self._format_datetime(completed_at) if completed_at is not None else None
        conn.execute(
            "UPDATE execution_processes SET status = ?, exit_code = ?, completed_at = ?, updated_at = ? WHERE id = ?",
            (status, exit_code, completed_at_value, self._format_datetime(now), process_id),
        )
        conn.commit()
        conn.close()

    def update_execution_process_usage(self, process_id: str, input_tokens: int | None = None, output_tokens: int | None = None, cache_read_tokens: int | None = None, total_cost_usd: float | None = None):
        """Update the token usage and cost of an ExecutionProcess."""
        self._ensure_db()
        conn = self._get_conn()
        from datetime import datetime as dt
        now = dt.now()
        conn.execute(
            "UPDATE execution_processes SET input_tokens = ?, output_tokens = ?, cache_read_tokens = ?, total_cost_usd = ?, updated_at = ? WHERE id = ?",
            (input_tokens, output_tokens, cache_read_tokens, total_cost_usd, self._format_datetime(now), process_id),
        )
        conn.commit()
        conn.close()

    # --- Conductor State ---

    def save_conductor_state(self, state: "ConductorState") -> None:
        from app.domain.models import ConductorState  # noqa: F401 (type hint import)
        self._ensure_db()
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO conductor_states
               (issue_id, running_thread_json, pending_dispatches_json, scratchpad, decision_count, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                state.issue_id,
                state.running_thread_json,
                state.pending_dispatches_json,
                state.scratchpad,
                state.decision_count,
                self._format_datetime(state.updated_at or datetime.now()),
            ),
        )
        conn.commit()
        conn.close()

    def load_conductor_state(self, issue_id: str) -> "ConductorState | None":
        from app.domain.models import ConductorState
        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM conductor_states WHERE issue_id = ?",
            (issue_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        return ConductorState(
            issue_id=row["issue_id"],
            running_thread_json=row["running_thread_json"] or "[]",
            pending_dispatches_json=row["pending_dispatches_json"] or "[]",
            scratchpad=row["scratchpad"] or "",
            decision_count=int(row["decision_count"] or 0),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def save_project_conductor_state(self, state: "ProjectConductorState") -> None:
        from app.domain.models import ProjectConductorState  # noqa: F401
        self._ensure_db()
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO project_conductor_states
               (project_id, hot_thread_json, warm_summaries_json, pinned_text,
                hot_tokens, warm_tokens, last_compaction_at, total_tasks_handled, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                state.project_id,
                state.hot_thread_json,
                state.warm_summaries_json,
                state.pinned_text,
                state.hot_tokens,
                state.warm_tokens,
                self._format_datetime(state.last_compaction_at),
                state.total_tasks_handled,
                self._format_datetime(state.updated_at),
            ),
        )
        conn.commit()
        conn.close()

    def load_project_conductor_state(self, project_id: str) -> "ProjectConductorState | None":
        from app.domain.models import ProjectConductorState
        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM project_conductor_states WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        return ProjectConductorState(
            project_id=row["project_id"],
            hot_thread_json=row["hot_thread_json"] or "[]",
            warm_summaries_json=row["warm_summaries_json"] or "[]",
            pinned_text=row["pinned_text"] or "",
            hot_tokens=int(row["hot_tokens"] or 0),
            warm_tokens=int(row["warm_tokens"] or 0),
            last_compaction_at=self._parse_datetime(row["last_compaction_at"]),
            total_tasks_handled=int(row["total_tasks_handled"] or 0),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def _row_to_conductor_task(self, row) -> "ConductorTask":
        from app.domain.models import ConductorTask

        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        keys = row.keys()
        return ConductorTask(
            id=row["id"],
            project_id=row["project_id"],
            task_kind=row["task_kind"],
            payload=payload if isinstance(payload, dict) else {},
            issue_id=row["issue_id"],
            status=row["status"],
            result_json=row["result_json"],
            lease_owner=row["lease_owner"] if "lease_owner" in keys and row["lease_owner"] else None,
            heartbeat_at=self._parse_datetime(row["heartbeat_at"] if "heartbeat_at" in keys else None),
            lease_expires_at=self._parse_datetime(row["lease_expires_at"] if "lease_expires_at" in keys else None),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def save_conductor_task(self, task: "ConductorTask") -> None:
        from app.domain.models import ConductorTask  # noqa: F401
        self._ensure_db()
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO conductor_tasks
               (id, project_id, task_kind, payload_json, issue_id, status, result_json,
                lease_owner, heartbeat_at, lease_expires_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task.id,
                task.project_id,
                task.task_kind,
                json.dumps(task.payload, ensure_ascii=False, default=str),
                task.issue_id,
                task.status,
                task.result_json,
                task.lease_owner,
                self._format_datetime(task.heartbeat_at),
                self._format_datetime(task.lease_expires_at),
                self._format_datetime(task.created_at),
                self._format_datetime(task.updated_at or datetime.now()),
            ),
        )
        conn.commit()
        conn.close()

    def load_conductor_task(self, task_id: str) -> "ConductorTask | None":
        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM conductor_tasks WHERE id = ?", (task_id,)).fetchone()
        conn.close()
        if row is None:
            return None
        return self._row_to_conductor_task(row)

    def load_latest_conductor_task_for_issue(self, issue_id: str) -> "ConductorTask | None":
        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT * FROM conductor_tasks
               WHERE issue_id = ?
               ORDER BY created_at DESC, updated_at DESC, id DESC
               LIMIT 1""",
            (issue_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        return self._row_to_conductor_task(row)

    def list_conductor_tasks(self, *, status: str | None = None) -> list["ConductorTask"]:
        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        if status:
            rows = conn.execute(
                """SELECT * FROM conductor_tasks
                   WHERE status = ?
                   ORDER BY created_at ASC, updated_at ASC, id ASC""",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM conductor_tasks ORDER BY created_at ASC, updated_at ASC, id ASC"
            ).fetchall()
        conn.close()
        return [self._row_to_conductor_task(row) for row in rows]

    def save_conductor_turn(self, turn: "ConductorTurn") -> None:
        from app.domain.models import ConductorTurn  # noqa: F401
        self._ensure_db()
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO conductor_turns
               (id, conductor_task_id, issue_id, turn_index, sub_index, kind, payload_json, created_at, consumed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                turn.id,
                turn.conductor_task_id,
                turn.issue_id,
                turn.turn_index,
                turn.sub_index,
                turn.kind,
                turn.payload_json,
                self._format_datetime(turn.created_at or datetime.now()),
                self._format_datetime(turn.consumed_at),
            ),
        )
        conn.commit()
        conn.close()

    def enqueue_conductor_user_message(self, conductor_task_id: str, issue_id: str, text: str) -> "ConductorTurn":
        from app.domain.models import ConductorTurn

        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT COALESCE(MAX(turn_index), -1) AS max_turn_index FROM conductor_turns WHERE conductor_task_id = ?",
            (conductor_task_id,),
        ).fetchone()
        next_turn_index = int((row["max_turn_index"] if row is not None else -1) or -1) + 1
        turn = ConductorTurn(
            id=str(uuid4()),
            conductor_task_id=conductor_task_id,
            issue_id=issue_id,
            turn_index=next_turn_index,
            sub_index=0,
            kind="user_message",
            payload_json=json.dumps({"text": text}, ensure_ascii=False),
            created_at=datetime.now(),
            consumed_at=None,
        )
        conn.execute(
            """INSERT OR REPLACE INTO conductor_turns
               (id, conductor_task_id, issue_id, turn_index, sub_index, kind, payload_json, created_at, consumed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                turn.id,
                turn.conductor_task_id,
                turn.issue_id,
                turn.turn_index,
                turn.sub_index,
                turn.kind,
                turn.payload_json,
                self._format_datetime(turn.created_at or datetime.now()),
                None,
            ),
        )
        conn.commit()
        conn.close()
        return turn

    def drain_conductor_inbox(self, conductor_task_id: str) -> list["ConductorTurn"]:
        from app.domain.models import ConductorTurn

        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT * FROM conductor_turns
               WHERE conductor_task_id = ? AND kind = 'user_message' AND consumed_at IS NULL
               ORDER BY created_at ASC, id ASC""",
            (conductor_task_id,),
        ).fetchall()
        if not rows:
            conn.close()
            return []
        consumed_at = datetime.now()
        conn.executemany(
            "UPDATE conductor_turns SET consumed_at = ? WHERE id = ?",
            [(self._format_datetime(consumed_at), row["id"]) for row in rows],
        )
        conn.commit()
        conn.close()
        return [
            ConductorTurn(
                id=row["id"],
                conductor_task_id=row["conductor_task_id"],
                issue_id=row["issue_id"],
                turn_index=int(row["turn_index"] or 0),
                sub_index=int(row["sub_index"] or 0),
                kind=row["kind"],
                payload_json=row["payload_json"] or "{}",
                created_at=self._parse_datetime(row["created_at"]),
                consumed_at=consumed_at,
            )
            for row in rows
        ]

    def list_conductor_turns(
        self,
        issue_id: str,
        *,
        conductor_task_id: str | None = None,
        limit: int = 200,
    ) -> list["ConductorTurn"]:
        from app.domain.models import ConductorTurn
        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        sql = """SELECT * FROM conductor_turns
                 WHERE issue_id = ?"""
        params: list[object] = [issue_id]
        if conductor_task_id:
            sql += " AND conductor_task_id = ?"
            params.append(conductor_task_id)
        sql += " ORDER BY created_at ASC, turn_index ASC, sub_index ASC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        rows = conn.execute(sql, tuple(params)).fetchall()
        conn.close()
        return [
            ConductorTurn(
                id=row["id"],
                conductor_task_id=row["conductor_task_id"],
                issue_id=row["issue_id"],
                turn_index=int(row["turn_index"] or 0),
                sub_index=int(row["sub_index"] or 0),
                kind=row["kind"],
                payload_json=row["payload_json"] or "{}",
                created_at=self._parse_datetime(row["created_at"]),
                consumed_at=self._parse_datetime(row["consumed_at"]) if "consumed_at" in row.keys() else None,
            )
            for row in rows
        ]

    def save_conductor_state_log(self, entry: "ConductorStateLog") -> None:
        from app.domain.models import ConductorStateLog  # noqa: F401

        self._ensure_db()
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO conductor_state_log
               (id, issue_id, from_phase, to_phase, from_detail, to_detail, transition_at, duration_ms, is_legal)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.id,
                entry.issue_id,
                entry.from_phase,
                entry.to_phase,
                entry.from_detail,
                entry.to_detail,
                self._format_datetime(entry.transition_at or datetime.now()),
                entry.duration_ms,
                1 if entry.is_legal else 0,
            ),
        )
        conn.commit()
        conn.close()

    def list_conductor_state_logs(
        self,
        issue_id: str | None = None,
        *,
        limit: int = 200,
        descending: bool = False,
    ) -> list["ConductorStateLog"]:
        from app.domain.models import ConductorStateLog

        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM conductor_state_log"
        params: list[object] = []
        if issue_id is not None:
            sql += " WHERE issue_id = ?"
            params.append(issue_id)
        order = "DESC" if descending else "ASC"
        sql += f" ORDER BY transition_at {order}, id {order}"
        if limit > 0:
            sql += " LIMIT ?"
            params.append(max(1, min(limit, 5000)))
        rows = conn.execute(sql, tuple(params)).fetchall()
        conn.close()
        return [
            ConductorStateLog(
                id=row["id"],
                issue_id=row["issue_id"],
                from_phase=row["from_phase"],
                to_phase=row["to_phase"],
                from_detail=row["from_detail"],
                to_detail=row["to_detail"],
                transition_at=self._parse_datetime(row["transition_at"]),
                duration_ms=int(row["duration_ms"]) if row["duration_ms"] is not None else None,
                is_legal=bool(row["is_legal"]),
            )
            for row in rows
        ]

    def save_audit_log(self, entry: "AuditLog") -> None:
        from app.domain.models import AuditLog  # noqa: F401

        self._ensure_db()
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO audit_log
               (id, created_at, category, actor, issue_id, task_id, conductor_task_id,
                execution_process_id, correlation_id, status, duration_ms, payload_json, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.id,
                self._format_datetime(entry.created_at or datetime.now()),
                entry.category,
                entry.actor,
                entry.issue_id,
                entry.task_id,
                entry.conductor_task_id,
                entry.execution_process_id,
                entry.correlation_id,
                entry.status,
                entry.duration_ms,
                entry.payload_json,
                entry.error,
            ),
        )
        conn.commit()
        conn.close()

    def list_audit_logs(
        self,
        *,
        category: str | None = None,
        categories: list[str] | None = None,
        issue_id: str | None = None,
        task_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        q: str | None = None,
        cursor_created_at: str | None = None,
        cursor_id: str | None = None,
        limit: int = 200,
        descending: bool = True,
    ) -> list["AuditLog"]:
        from app.adapters.audit_log_query import build_audit_log_query
        from app.domain.models import AuditLog

        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        sql, params = build_audit_log_query(
            category=category,
            categories=categories,
            issue_id=issue_id,
            task_id=task_id,
            since=since,
            until=until,
            q=q,
            cursor_created_at=cursor_created_at,
            cursor_id=cursor_id,
            limit=limit,
            descending=descending,
        )
        rows = conn.execute(sql, tuple(params)).fetchall()
        conn.close()
        return [
            AuditLog(
                id=row["id"],
                created_at=self._parse_datetime(row["created_at"]),
                category=row["category"],
                actor=row["actor"],
                issue_id=row["issue_id"],
                task_id=row["task_id"],
                conductor_task_id=row["conductor_task_id"],
                execution_process_id=row["execution_process_id"],
                correlation_id=row["correlation_id"],
                status=row["status"],
                duration_ms=int(row["duration_ms"]) if row["duration_ms"] is not None else None,
                payload_json=row["payload_json"],
                error=row["error"],
            )
            for row in rows
        ]

    def save_project_memory_embedding(self, memory: "ProjectMemoryEmbedding") -> None:
        from app.domain.models import ProjectMemoryEmbedding  # noqa: F401
        self._ensure_db()
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO project_memory_embeddings
               (id, project_id, source_kind, source_id, summary_text, vector_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                memory.id,
                memory.project_id,
                memory.source_kind,
                memory.source_id,
                memory.summary_text,
                memory.vector_json,
                self._format_datetime(memory.created_at or datetime.now()),
            ),
        )
        conn.commit()
        conn.close()

    def list_project_memory_embeddings(self, project_id: str, limit: int | None = None) -> list["ProjectMemoryEmbedding"]:
        from app.domain.models import ProjectMemoryEmbedding
        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM project_memory_embeddings WHERE project_id = ? ORDER BY created_at ASC"
        args: list = [project_id]
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)
        rows = conn.execute(sql, tuple(args)).fetchall()
        conn.close()
        return [
            ProjectMemoryEmbedding(
                id=row["id"],
                project_id=row["project_id"],
                source_kind=row["source_kind"],
                source_id=row["source_id"],
                summary_text=row["summary_text"],
                vector_json=row["vector_json"] or "[]",
                created_at=self._parse_datetime(row["created_at"]),
            )
            for row in rows
        ]

    def save_self_improvement_proposal(self, proposal: "SelfImprovementProposal") -> None:
        from app.domain.models import SelfImprovementProposal  # noqa: F401

        self._ensure_db()
        conn = self._get_conn()
        now = datetime.now()
        created_at = proposal.created_at or now
        updated_at = proposal.updated_at or now
        conn.execute(
            """INSERT INTO self_improvement_proposals
               (id, project_id, issue_id, target_kind, title, recommendation, evidence_json,
                severity, confidence, status, fingerprint, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(fingerprint) DO UPDATE SET
                   id = excluded.id,
                   title = excluded.title,
                   recommendation = excluded.recommendation,
                   evidence_json = excluded.evidence_json,
                   severity = excluded.severity,
                   confidence = excluded.confidence,
                   status = excluded.status,
                   updated_at = excluded.updated_at""",
            (
                proposal.id,
                proposal.project_id,
                proposal.issue_id,
                proposal.target_kind,
                proposal.title,
                proposal.recommendation,
                proposal.evidence_json or "[]",
                proposal.severity,
                float(proposal.confidence),
                proposal.status,
                proposal.fingerprint,
                self._format_datetime(created_at),
                self._format_datetime(updated_at),
            ),
        )
        conn.commit()
        conn.close()

    def list_self_improvement_proposals(
        self,
        project_id: str | None = None,
        issue_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list["SelfImprovementProposal"]:
        from app.domain.models import SelfImprovementProposal

        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        clauses: list[str] = []
        args: list[object] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            args.append(project_id)
        if issue_id is not None:
            clauses.append("issue_id = ?")
            args.append(issue_id)
        if status is not None:
            clauses.append("status = ?")
            args.append(status)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT id, project_id, issue_id, target_kind, title, recommendation, evidence_json, "
            "severity, confidence, status, fingerprint, created_at, updated_at "
            f"FROM self_improvement_proposals{where} ORDER BY created_at DESC, id DESC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            args.append(max(1, min(int(limit), 100)))
        rows = conn.execute(sql, tuple(args)).fetchall()
        conn.close()
        return [
            SelfImprovementProposal(
                id=row["id"],
                project_id=row["project_id"],
                issue_id=row["issue_id"],
                target_kind=row["target_kind"],
                title=row["title"],
                recommendation=row["recommendation"],
                evidence_json=row["evidence_json"] or "[]",
                severity=row["severity"] or "info",
                confidence=float(row["confidence"] or 0),
                status=row["status"] or "proposed",
                fingerprint=row["fingerprint"],
                created_at=self._parse_datetime(row["created_at"]),
                updated_at=self._parse_datetime(row["updated_at"]),
            )
            for row in rows
        ]

    # --- Runtime Catalog ---

    def save_runtime_catalog(self, catalog: "RuntimeCatalog"):
        """Save the runtime catalog to the database."""
        self._ensure_db()
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO runtime_catalog_settings (id, data) VALUES (?, ?)",
            ("runtime_catalog", json.dumps(catalog.model_dump())),
        )
        conn.commit()
        conn.close()

    def load_runtime_catalog(self) -> "RuntimeCatalog | None":
        """Load the runtime catalog from the database."""
        self._ensure_db()
        from app.domain.models import RuntimeCatalog
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT data FROM runtime_catalog_settings WHERE id = ?", ("runtime_catalog",)).fetchone()
        conn.close()
        if not row:
            return None
        try:
            data = json.loads(row["data"])
            return RuntimeCatalog(**data)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

    # --- Artifact Paths ---

    def save_artifact(self, artifact: dict) -> None:
        """Save artifact path to database. Fields: id, issue_id, task_id, name, path, kind, created_at."""
        self._ensure_db()
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO artifact_paths (id, issue_id, task_id, name, path, kind, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    artifact.get("id"),
                    artifact.get("issue_id"),
                    artifact.get("task_id"),
                    artifact.get("name"),
                    artifact.get("path"),
                    artifact.get("kind"),
                    artifact.get("created_at"),
                ),
            )
            conn.commit()
        except sqlite3.Error as e:
            logger.error("Database error saving artifact: %s", e)
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def list_artifacts(self, issue_id: str) -> list[dict]:
        """List all artifacts for an issue, ordered by created_at."""
        self._ensure_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM artifact_paths WHERE issue_id = ? ORDER BY created_at ASC",
            (issue_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
