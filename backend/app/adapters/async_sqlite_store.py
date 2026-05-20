import asyncio
import json
from datetime import datetime
from pathlib import Path

import aiosqlite

from app.domain.models import Session, Task, AgentRun, Artifact, Message, Approval, ApprovalEvent, PlanDetails, CodexSession, CodexMessage, CodexIssue, CodexTask, CodexTaskMessage, LogEvent, ExecutionProcess, HelpRequest, RuntimeCatalog, Project


class AsyncSQLiteStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._conn_lock = asyncio.Lock()

    async def close(self) -> None:
        """Close the connection. Call this on app shutdown."""
        async with self._conn_lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None

    async def _get_conn(self) -> aiosqlite.Connection:
        async with self._conn_lock:
            if self._conn is None:
                self._conn = await aiosqlite.connect(self.db_path, timeout=30.0)
                await self._conn.execute("PRAGMA journal_mode=WAL")
                await self._conn.execute("PRAGMA synchronous=NORMAL")
            return self._conn

    async def _init_db(self):
        conn = await self._get_conn()
        await conn.executescript("""
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
                milestone TEXT,
                git_branch TEXT,
                git_base_branch TEXT,
                git_worktree_path TEXT,
                git_merge_status TEXT DEFAULT 'open',
                git_last_commit_sha TEXT,
                github_pr_url TEXT,
                github_pr_state TEXT,
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
        for table in ["tasks", "runs", "artifacts", "messages", "approvals", "approval_events"]:
            try:
                await conn.execute(f"ALTER TABLE {table} ADD COLUMN created_at TEXT")
            except aiosqlite.OperationalError:
                pass
        try:
            await conn.execute("ALTER TABLE codex_sessions ADD COLUMN thread_id TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_sessions ADD COLUMN claude_thread_id TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_sessions ADD COLUMN project_id TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_sessions ADD COLUMN settings_json TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE log_events ADD COLUMN task_id TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_task_messages ADD COLUMN execution_process_id TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE log_events ADD COLUMN execution_process_id TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN phase TEXT DEFAULT 'requirements'")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN issue_id TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN role TEXT DEFAULT 'general'")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN executor TEXT DEFAULT 'codex'")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN resume_session_id TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN resume_message_id TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN workspace_path TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN last_execution_process_id TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN task_kind TEXT DEFAULT 'normal'")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN blocked_by_help_id TEXT")
        except aiosqlite.OperationalError:
            pass
        # Add provider and model columns to codex_tasks
        try:
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN provider TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN model TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN result_json TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE agents ADD COLUMN agent_tier TEXT DEFAULT 'managed'")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_issues ADD COLUMN project_id TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_issues ADD COLUMN review_comment TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_issues ADD COLUMN milestone TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_issues ADD COLUMN git_branch TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_issues ADD COLUMN git_base_branch TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_issues ADD COLUMN git_worktree_path TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_issues ADD COLUMN git_merge_status TEXT DEFAULT 'open'")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_issues ADD COLUMN git_last_commit_sha TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_issues ADD COLUMN github_pr_url TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_issues ADD COLUMN github_pr_state TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_issues ADD COLUMN is_pinned INTEGER NOT NULL DEFAULT 0")
        except aiosqlite.OperationalError:
            pass
        # Add executor/provider/model snapshot columns to execution_processes
        try:
            await conn.execute("ALTER TABLE execution_processes ADD COLUMN executor TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE execution_processes ADD COLUMN provider TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE execution_processes ADD COLUMN model TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE execution_processes ADD COLUMN kind TEXT NOT NULL DEFAULT 'initial'")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE execution_processes ADD COLUMN triggering_message_id TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN sequence_index INTEGER")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN sequence_group TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN review_comment TEXT")
        except aiosqlite.OperationalError:
            pass
        # --- Project / git worktree feature additions ---
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                repo_path TEXT NOT NULL,
                default_branch TEXT NOT NULL DEFAULT 'main',
                origin_url TEXT,
                setup_script TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_repo_path ON projects(repo_path)")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                version INTEGER NOT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS project_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT,
                issue_id TEXT,
                event TEXT NOT NULL,
                sha TEXT,
                base_branch TEXT,
                created_at TEXT NOT NULL
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_project_audit_project_id ON project_audit(project_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_project_audit_issue_id ON project_audit(issue_id)"
        )
        for stmt in (
            "ALTER TABLE codex_tasks ADD COLUMN project_id TEXT",
            "ALTER TABLE codex_tasks ADD COLUMN git_branch TEXT",
            "ALTER TABLE codex_tasks ADD COLUMN git_base_branch TEXT",
            "ALTER TABLE codex_tasks ADD COLUMN git_worktree_path TEXT",
            "ALTER TABLE codex_tasks ADD COLUMN git_merge_status TEXT DEFAULT 'open'",
            "ALTER TABLE codex_tasks ADD COLUMN git_last_commit_sha TEXT",
            "ALTER TABLE codex_sessions ADD COLUMN project_id TEXT",
            "ALTER TABLE codex_issues ADD COLUMN project_id TEXT",
            "ALTER TABLE codex_issues ADD COLUMN git_branch TEXT",
            "ALTER TABLE codex_issues ADD COLUMN git_base_branch TEXT",
            "ALTER TABLE codex_issues ADD COLUMN git_worktree_path TEXT",
            "ALTER TABLE codex_issues ADD COLUMN git_merge_status TEXT DEFAULT 'open'",
            "ALTER TABLE codex_issues ADD COLUMN git_last_commit_sha TEXT",
            # S2-PR: GitHub PR loop. Stores `gh pr create` output URL +
            # last-observed review state for the issue's branch.
            "ALTER TABLE codex_issues ADD COLUMN github_pr_url TEXT",
            "ALTER TABLE codex_issues ADD COLUMN github_pr_state TEXT",
        ):
            try:
                await conn.execute(stmt)
            except aiosqlite.OperationalError:
                pass
        # One-time wipe of legacy codex data so all rows have project_id.
        # The decision to clear was made explicitly (dev-stage data).
        version_row = await (await conn.execute("SELECT version FROM schema_version WHERE id = 1")).fetchone()
        current_version = version_row[0] if version_row else 0
        if current_version < 2:
            await conn.executescript(
                """
                DELETE FROM codex_task_messages;
                DELETE FROM execution_processes;
                DELETE FROM codex_tasks;
                DELETE FROM codex_issues;
                DELETE FROM codex_sessions;
                DELETE FROM log_events;
                DELETE FROM help_requests;
                """
            )
            await conn.execute(
                "INSERT OR REPLACE INTO schema_version (id, version) VALUES (1, ?)",
                (2,),
            )
        # Create runtime_catalog_settings table if not exists
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS runtime_catalog_settings (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            )
        """)
        # Create artifact_paths table for tracking written artifacts
        await conn.execute("""
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
        # Agent = first-class replacement for hardcoded roles.
        await conn.execute("""
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
        await conn.execute("""
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
        await conn.execute("""
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
                started_at TEXT,
                completed_at TEXT,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(graph_id, node_key),
                FOREIGN KEY (graph_id) REFERENCES workflow_graphs(id),
                FOREIGN KEY (agent_id) REFERENCES agents(id)
            )
        """)
        await conn.execute("""
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
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS workflow_presets (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                dag_template_json TEXT NOT NULL,
                is_builtin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT
            )
        """)
        await conn.execute("""
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
        # Add workflow_node_id FK to codex_tasks for DAG-aware runtime routing.
        try:
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN workflow_node_id TEXT")
        except Exception:
            pass  # Column already exists
        # Knowledge stack: FTS5 virtual tables + embedding stores + team-notes state
        await conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS issues_fts USING fts5(
                issue_id UNINDEXED,
                project_id UNINDEXED,
                title,
                description,
                tokenize='porter unicode61'
            )
        """)
        await conn.execute("""
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
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS artifact_embeddings (
                artifact_id TEXT PRIMARY KEY,
                vector BLOB NOT NULL,
                model TEXT NOT NULL,
                dim INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS issue_embeddings (
                issue_id TEXT PRIMARY KEY,
                vector BLOB NOT NULL,
                model TEXT NOT NULL,
                dim INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS team_notes_state (
                project_id TEXT NOT NULL,
                block_id TEXT NOT NULL,
                deleted_at TEXT,
                pinned INTEGER DEFAULT 0,
                PRIMARY KEY (project_id, block_id)
            )
        """)
        await conn.execute("""
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
        await conn.execute("""
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
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS conductor_states (
                issue_id TEXT PRIMARY KEY,
                running_thread_json TEXT NOT NULL DEFAULT '[]',
                pending_dispatches_json TEXT NOT NULL DEFAULT '[]',
                scratchpad TEXT NOT NULL DEFAULT '',
                decision_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT
            )
        """)
        # Create indexes for frequently queried columns
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_tasks_session_id ON codex_tasks(session_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_tasks_project_id ON codex_tasks(project_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_sessions_project_id ON codex_sessions(project_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_issues_project_id ON codex_issues(project_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_tasks_issue_id ON codex_tasks(issue_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_tasks_parent_task_id ON codex_tasks(parent_task_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_tasks_status ON codex_tasks(status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_tasks_task_kind ON codex_tasks(task_kind)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_issues_session_id ON codex_issues(session_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_task_messages_task_id ON codex_task_messages(task_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_task_messages_execution_process_id ON codex_task_messages(execution_process_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_log_events_session_id ON log_events(session_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_log_events_task_id ON log_events(task_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_log_events_execution_process_id ON log_events(execution_process_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_execution_processes_session_id ON execution_processes(session_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_execution_processes_task_id ON execution_processes(task_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_help_requests_parent_task_id ON help_requests(parent_task_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_help_requests_child_task_id ON help_requests(child_task_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_help_requests_workspace_id ON help_requests(workspace_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_artifact_paths_issue_id ON artifact_paths(issue_id)")
        # Workflow DAG indexes
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_role_key ON agents(role_key)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_workspace_id ON agents(workspace_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_graphs_issue_id ON workflow_graphs(issue_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_nodes_graph_id ON workflow_nodes(graph_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_nodes_status ON workflow_nodes(status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_nodes_task_id ON workflow_nodes(task_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_edges_graph_id ON workflow_edges(graph_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_graph_replan_pending_graph_id ON graph_replan_pending(graph_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_graph_replan_pending_status ON graph_replan_pending(status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_tasks_workflow_node_id ON codex_tasks(workflow_node_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_messages_issue_id ON agent_messages(issue_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_messages_graph_id ON agent_messages(graph_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_conductor_decisions_issue_id ON conductor_decisions(issue_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_conductor_decisions_task_id ON conductor_decisions(task_id)")
        # Phase 4: add instance_index to workflow_nodes for existing DBs
        try:
            await conn.execute(
                "ALTER TABLE workflow_nodes ADD COLUMN instance_index INTEGER NOT NULL DEFAULT 0"
            )
        except aiosqlite.OperationalError:
            pass
        await conn.commit()

    async def _ensure_db(self):
        await self._init_db()

    def _format_datetime(self, dt: datetime | None) -> str | None:
        return dt.isoformat() if dt else None

    def _parse_datetime(self, s: str | None) -> datetime | None:
        return datetime.fromisoformat(s) if s else None

    async def save_session(self, session: Session):
        conn = await self._get_conn()
        await conn.execute(
            "INSERT OR REPLACE INTO sessions (id, title, state) VALUES (?, ?, ?)",
            (session.id, session.title, session.state.value),
        )
        for task in session.tasks:
            await conn.execute(
                "INSERT OR REPLACE INTO tasks (id, session_id, title, assignee, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (task.id, session.id, task.title, task.assignee, task.status, self._format_datetime(task.created_at)),
            )
        for run in session.runs:
            await conn.execute(
                "INSERT OR REPLACE INTO runs (id, task_id, agent_id, role, status, summary, payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (run.id, run.task_id, run.agent_id, run.role, run.status, run.summary, json.dumps(run.payload) if run.payload else None, self._format_datetime(run.created_at)),
            )
        for artifact in session.artifacts:
            content = artifact.content
            if hasattr(content, "model_dump"):
                content = json.dumps(content.model_dump())
            elif not isinstance(content, str):
                content = json.dumps(content)
            await conn.execute(
                "INSERT OR REPLACE INTO artifacts (id, task_id, kind, content, steps, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (artifact.id, artifact.task_id, artifact.kind, content, json.dumps(artifact.steps) if artifact.steps else None, self._format_datetime(artifact.created_at)),
            )
        for message in session.messages:
            await conn.execute(
                "INSERT OR REPLACE INTO messages (id, task_id, agent_id, role, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (message.id, message.task_id, message.agent_id, message.role, message.content, self._format_datetime(message.created_at)),
            )
        for approval in session.approvals:
            await conn.execute(
                "INSERT OR REPLACE INTO approvals (id, session_id, task_id, action, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (approval.id, approval.session_id, approval.task_id, approval.action, approval.status, self._format_datetime(approval.created_at)),
            )
        for event in session.approval_events:
            await conn.execute(
                "INSERT OR REPLACE INTO approval_events (id, session_id, task_id, approval_id, event_type, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (event.id, event.session_id, event.task_id, event.approval_id, event.event_type, self._format_datetime(event.created_at)),
            )
        await conn.commit()

    async def load_session(self, session_id: str) -> Session | None:
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        row = await cur.fetchone()
        if not row:
            return None

        session = Session(
            id=row["id"],
            title=row["title"],
            state=row["state"],
        )

        async def load_tasks():
            async with conn.execute("SELECT * FROM tasks WHERE session_id = ?", (session_id,)) as cur:
                async for t_row in cur:
                    session.tasks.append(Task(
                        id=t_row["id"],
                        session_id=t_row["session_id"],
                        title=t_row["title"],
                        assignee=t_row["assignee"],
                        status=t_row["status"],
                        created_at=self._parse_datetime(t_row["created_at"]),
                    ))

        async def load_runs():
            async with conn.execute("SELECT * FROM runs WHERE task_id IN (SELECT id FROM tasks WHERE session_id = ?)", (session_id,)) as cur:
                async for r_row in cur:
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

        async def load_artifacts():
            async with conn.execute("SELECT * FROM artifacts WHERE task_id IN (SELECT id FROM tasks WHERE session_id = ?)", (session_id,)) as cur:
                async for a_row in cur:
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

        async def load_messages():
            async with conn.execute("SELECT * FROM messages WHERE task_id IN (SELECT id FROM tasks WHERE session_id = ?)", (session_id,)) as cur:
                async for m_row in cur:
                    session.messages.append(Message(
                        id=m_row["id"],
                        task_id=m_row["task_id"],
                        agent_id=m_row["agent_id"],
                        role=m_row["role"],
                        content=m_row["content"],
                        created_at=self._parse_datetime(m_row["created_at"]),
                    ))

        async def load_approvals():
            async with conn.execute("SELECT * FROM approvals WHERE session_id = ?", (session_id,)) as cur:
                async for ap_row in cur:
                    session.approvals.append(Approval(
                        id=ap_row["id"],
                        session_id=ap_row["session_id"],
                        task_id=ap_row["task_id"],
                        action=ap_row["action"],
                        status=ap_row["status"],
                        created_at=self._parse_datetime(ap_row["created_at"]),
                    ))

        async def load_approval_events():
            async with conn.execute("SELECT * FROM approval_events WHERE session_id = ?", (session_id,)) as cur:
                async for ev_row in cur:
                    session.approval_events.append(ApprovalEvent(
                        id=ev_row["id"],
                        session_id=ev_row["session_id"],
                        task_id=ev_row["task_id"],
                        approval_id=ev_row["approval_id"],
                        event_type=ev_row["event_type"],
                        created_at=self._parse_datetime(ev_row["created_at"]),
                    ))

        await load_tasks()
        await load_runs()
        await load_artifacts()
        await load_messages()
        await load_approvals()
        await load_approval_events()
        return session

    async def list_sessions(self) -> list[dict]:
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT id, title, state FROM sessions") as cur:
            rows = await cur.fetchall()
        return [{"id": r["id"], "title": r["title"], "state": r["state"]} for r in rows]

    async def save_codex_session(self, session: CodexSession):
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            "INSERT OR REPLACE INTO codex_sessions (id, title, cwd, project_id, status, created_at, last_active_at, log_path, thread_id, claude_thread_id, settings_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session.id, session.title, session.cwd, session.project_id, session.status,
             self._format_datetime(session.created_at),
             self._format_datetime(session.last_active_at),
             session.log_path,
             session.thread_id,
             session.claude_thread_id,
             json.dumps(session.settings, ensure_ascii=False) if getattr(session, "settings", None) is not None else None),
        )
        await conn.execute("DELETE FROM codex_messages WHERE session_id = ?", (session.id,))
        for msg in session.messages:
            await conn.execute(
                "INSERT INTO codex_messages (id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (msg.id, msg.session_id, msg.role, msg.content, self._format_datetime(msg.created_at)),
            )
        await conn.commit()

    async def save_codex_workspace(self, workspace: CodexSession):
        await self.save_codex_session(workspace)

    async def load_codex_session(self, session_id: str) -> CodexSession | None:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM codex_sessions WHERE id = ?", (session_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        async with conn.execute(
            "SELECT * FROM codex_messages WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        ) as cur:
            msg_rows = await cur.fetchall()
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

    async def load_codex_workspace(self, workspace_id: str) -> CodexSession | None:
        return await self.load_codex_session(workspace_id)

    async def list_codex_sessions(self, project_id: str | None = None) -> list[dict]:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        base = "SELECT id, title, project_id, status, created_at, last_active_at, settings_json FROM codex_sessions"
        if project_id:
            async with conn.execute(f"{base} WHERE project_id = ? ORDER BY last_active_at DESC", (project_id,)) as cur:
                rows = await cur.fetchall()
        else:
            async with conn.execute(f"{base} ORDER BY last_active_at DESC") as cur:
                rows = await cur.fetchall()
        return [{"id": r["id"], "title": r["title"], "project_id": r["project_id"], "status": r["status"],
                 "created_at": r["created_at"], "last_active_at": r["last_active_at"],
                 "settings": json.loads(r["settings_json"]) if "settings_json" in r.keys() and r["settings_json"] else {"plan_first_pm": True}}
                for r in rows]

    async def list_codex_workspaces(self, project_id: str | None = None) -> list[dict]:
        return await self.list_codex_sessions(project_id=project_id)

    async def delete_codex_session(self, session_id: str):
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            "DELETE FROM codex_task_messages WHERE task_id IN (SELECT id FROM codex_tasks WHERE session_id = ?)",
            (session_id,),
        )
        await conn.execute("DELETE FROM codex_issues WHERE session_id = ?", (session_id,))
        await conn.execute("DELETE FROM codex_messages WHERE session_id = ?", (session_id,))
        await conn.execute("DELETE FROM codex_tasks WHERE session_id = ?", (session_id,))
        await conn.execute("DELETE FROM log_events WHERE session_id = ?", (session_id,))
        await conn.execute("DELETE FROM codex_sessions WHERE id = ?", (session_id,))
        await conn.commit()

    async def delete_codex_issue(self, issue_id: str):
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute("DELETE FROM codex_issues WHERE id = ?", (issue_id,))
        await conn.commit()

    async def delete_codex_workspace(self, workspace_id: str):
        await self.delete_codex_session(workspace_id)

    async def save_codex_issue(self, issue: CodexIssue):
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            """INSERT OR REPLACE INTO codex_issues (
                id, session_id, project_id, title, description, current_phase, status, review_comment,
                is_pinned, milestone,
                git_branch, git_base_branch, git_worktree_path, git_merge_status, git_last_commit_sha,
                github_pr_url, github_pr_state,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                self._format_datetime(issue.created_at),
                self._format_datetime(issue.updated_at),
            ),
        )
        # Knowledge index: keep FTS in sync. Best-effort.
        try:
            await conn.execute("DELETE FROM issues_fts WHERE issue_id = ?", (issue.id,))
            await conn.execute(
                "INSERT INTO issues_fts (issue_id, project_id, title, description) VALUES (?, ?, ?, ?)",
                (issue.id, issue.project_id or "", issue.title or "", issue.description or ""),
            )
        except Exception:  # noqa: BLE001
            pass
        await conn.commit()

    async def load_codex_issue(self, issue_id: str) -> CodexIssue | None:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM codex_issues WHERE id = ?", (issue_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        keys = row.keys()
        return CodexIssue(
            id=row["id"],
            session_id=row["session_id"],
            project_id=row["project_id"] if "project_id" in keys else None,
            title=row["title"],
            description=row["description"],
            current_phase=row["current_phase"],
            status=row["status"],
            review_comment=row["review_comment"] if "review_comment" in keys else None,
            is_pinned=bool(row["is_pinned"]) if "is_pinned" in keys else False,
            milestone=row["milestone"] if "milestone" in keys and row["milestone"] else None,
            git_branch=row["git_branch"] if "git_branch" in keys and row["git_branch"] else None,
            git_base_branch=row["git_base_branch"] if "git_base_branch" in keys and row["git_base_branch"] else None,
            git_worktree_path=row["git_worktree_path"] if "git_worktree_path" in keys and row["git_worktree_path"] else None,
            git_merge_status=row["git_merge_status"] if "git_merge_status" in keys and row["git_merge_status"] else "open",
            git_last_commit_sha=row["git_last_commit_sha"] if "git_last_commit_sha" in keys and row["git_last_commit_sha"] else None,
            github_pr_url=row["github_pr_url"] if "github_pr_url" in keys and row["github_pr_url"] else None,
            github_pr_state=row["github_pr_state"] if "github_pr_state" in keys and row["github_pr_state"] else None,
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    async def list_codex_issues(self, session_id: str | None = None, project_id: str | None = None) -> list[dict]:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        select_sql = "SELECT id, session_id, project_id, title, description, current_phase, status, review_comment, is_pinned, milestone, git_branch, git_base_branch, git_worktree_path, git_merge_status, git_last_commit_sha, github_pr_url, github_pr_state, created_at, updated_at FROM codex_issues"
        clauses, params = [], []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        order = " ORDER BY updated_at DESC, created_at DESC"
        async with conn.execute(f"{select_sql}{where}{order}", tuple(params)) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def save_codex_task(self, task: CodexTask):
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            """INSERT OR REPLACE INTO codex_tasks (
                id, session_id, project_id, issue_id, phase, title, prompt, role, executor, provider, model,
                status, result, result_json, parent_task_id, task_kind, blocked_by_help_id, workspace_path,
                git_branch, git_base_branch, git_worktree_path, git_merge_status, git_last_commit_sha,
                resume_session_id, resume_message_id, last_execution_process_id,
                sequence_index, sequence_group, review_comment, workflow_node_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task.id, task.session_id, task.project_id, task.issue_id, task.phase, task.title, task.prompt, task.role, task.executor,
             task.provider, task.model, task.status, task.result, task.result_json, task.parent_task_id, task.task_kind, task.blocked_by_help_id,
             task.workspace_path,
             task.git_branch, task.git_base_branch, task.git_worktree_path, task.git_merge_status, task.git_last_commit_sha,
             task.resume_session_id, task.resume_message_id, task.last_execution_process_id,
             task.sequence_index, task.sequence_group, task.review_comment,
             getattr(task, "workflow_node_id", None),
             self._format_datetime(task.created_at),
             self._format_datetime(task.updated_at)),
        )
        await conn.commit()

    async def load_codex_task(self, task_id: str) -> CodexTask | None:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM codex_tasks WHERE id = ?", (task_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        keys = row.keys()
        return CodexTask(
            id=row["id"],
            session_id=row["session_id"],
            project_id=row["project_id"] if "project_id" in keys and row["project_id"] else None,
            issue_id=row["issue_id"] if "issue_id" in keys and row["issue_id"] else None,
            phase=row["phase"] if "phase" in keys and row["phase"] else "requirements",
            title=row["title"],
            prompt=row["prompt"],
            role=row["role"] if "role" in keys and row["role"] else "general",
            executor=row["executor"] if row["executor"] else "codex",
            provider=row["provider"] if "provider" in keys and row["provider"] else None,
            model=row["model"] if "model" in keys and row["model"] else None,
            status=row["status"],
            result=row["result"],
            result_json=row["result_json"] if "result_json" in keys and row["result_json"] else None,
            parent_task_id=row["parent_task_id"] if row["parent_task_id"] else None,
            task_kind=row["task_kind"] if "task_kind" in keys and row["task_kind"] else "normal",
            blocked_by_help_id=row["blocked_by_help_id"] if "blocked_by_help_id" in keys and row["blocked_by_help_id"] else None,
            workspace_path=row["workspace_path"] if "workspace_path" in keys and row["workspace_path"] else None,
            git_branch=row["git_branch"] if "git_branch" in keys and row["git_branch"] else None,
            git_base_branch=row["git_base_branch"] if "git_base_branch" in keys and row["git_base_branch"] else None,
            git_worktree_path=row["git_worktree_path"] if "git_worktree_path" in keys and row["git_worktree_path"] else None,
            git_merge_status=row["git_merge_status"] if "git_merge_status" in keys and row["git_merge_status"] else "open",
            git_last_commit_sha=row["git_last_commit_sha"] if "git_last_commit_sha" in keys and row["git_last_commit_sha"] else None,
            resume_session_id=row["resume_session_id"] if "resume_session_id" in keys and row["resume_session_id"] else None,
            resume_message_id=row["resume_message_id"] if "resume_message_id" in keys and row["resume_message_id"] else None,
            last_execution_process_id=row["last_execution_process_id"] if "last_execution_process_id" in keys and row["last_execution_process_id"] else None,
            sequence_index=row["sequence_index"] if "sequence_index" in keys else None,
            sequence_group=row["sequence_group"] if "sequence_group" in keys else None,
            review_comment=row["review_comment"] if "review_comment" in keys else None,
            workflow_node_id=row["workflow_node_id"] if "workflow_node_id" in keys and row["workflow_node_id"] else None,
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    async def list_codex_tasks(
        self,
        session_id: str | None = None,
        issue_id: str | None = None,
        project_id: str | None = None,
    ) -> list[dict]:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        select_sql = (
            "SELECT id, session_id, project_id, issue_id, phase, title, prompt, role, executor, status, result, result_json, "
            "parent_task_id, task_kind, blocked_by_help_id, workspace_path, "
            "git_branch, git_base_branch, git_worktree_path, git_merge_status, git_last_commit_sha, "
            "resume_session_id, resume_message_id, last_execution_process_id, "
            "sequence_index, sequence_group, review_comment, created_at, updated_at FROM codex_tasks"
        )
        clauses, params = [], []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if issue_id:
            clauses.append("issue_id = ?")
            params.append(issue_id)
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        async with conn.execute(f"{select_sql}{where} ORDER BY created_at ASC", tuple(params)) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # --- Project CRUD ---

    async def save_project(self, project: Project):
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            "INSERT OR REPLACE INTO projects (id, name, repo_path, default_branch, origin_url, setup_script, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project.id,
                project.name,
                project.repo_path,
                project.default_branch,
                project.origin_url,
                project.setup_script,
                self._format_datetime(project.created_at),
                self._format_datetime(project.updated_at),
            ),
        )
        await conn.commit()

    async def load_project(self, project_id: str) -> Project | None:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return Project(
            id=row["id"],
            name=row["name"],
            repo_path=row["repo_path"],
            default_branch=row["default_branch"] or "main",
            origin_url=row["origin_url"],
            setup_script=row["setup_script"],
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    async def load_project_by_repo_path(self, repo_path: str) -> Project | None:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM projects WHERE repo_path = ?", (repo_path,)) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return Project(
            id=row["id"],
            name=row["name"],
            repo_path=row["repo_path"],
            default_branch=row["default_branch"] or "main",
            origin_url=row["origin_url"],
            setup_script=row["setup_script"],
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    async def list_projects(self) -> list[Project]:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM projects ORDER BY created_at ASC") as cur:
            rows = await cur.fetchall()
        return [
            Project(
                id=r["id"],
                name=r["name"],
                repo_path=r["repo_path"],
                default_branch=r["default_branch"] or "main",
                origin_url=r["origin_url"],
                setup_script=r["setup_script"],
                created_at=self._parse_datetime(r["created_at"]),
                updated_at=self._parse_datetime(r["updated_at"]),
            )
            for r in rows
        ]

    async def delete_project(self, project_id: str):
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        await conn.commit()

    async def append_project_audit(
        self,
        *,
        project_id: str | None,
        issue_id: str | None,
        event: str,
        sha: str | None = None,
        base_branch: str | None = None,
    ) -> None:
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            "INSERT INTO project_audit (project_id, issue_id, event, sha, base_branch, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, issue_id, event, sha, base_branch, datetime.now().isoformat()),
        )
        await conn.commit()

    async def list_project_audit(
        self,
        project_id: str,
        *,
        limit: int = 50,
        since: str | None = None,
    ) -> list[dict]:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        if since:
            query = (
                "SELECT id, project_id, issue_id, event, sha, base_branch, created_at "
                "FROM project_audit WHERE project_id = ? AND created_at >= ? "
                "ORDER BY id DESC LIMIT ?"
            )
            params = (project_id, since, limit)
        else:
            query = (
                "SELECT id, project_id, issue_id, event, sha, base_branch, created_at "
                "FROM project_audit WHERE project_id = ? ORDER BY id DESC LIMIT ?"
            )
            params = (project_id, limit)
        async with conn.execute(query, params) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def save_help_request(self, help_request: HelpRequest):
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
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
        await conn.commit()

    async def load_help_request(self, help_request_id: str) -> HelpRequest | None:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM help_requests WHERE id = ?", (help_request_id,)) as cur:
            row = await cur.fetchone()
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

    async def list_help_requests(self, *, parent_task_id: str | None = None, child_task_id: str | None = None) -> list[HelpRequest]:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        if parent_task_id:
            async with conn.execute(
                "SELECT * FROM help_requests WHERE parent_task_id = ? ORDER BY created_at ASC",
                (parent_task_id,),
            ) as cur:
                rows = await cur.fetchall()
        elif child_task_id:
            async with conn.execute(
                "SELECT * FROM help_requests WHERE child_task_id = ? ORDER BY created_at ASC",
                (child_task_id,),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with conn.execute("SELECT * FROM help_requests ORDER BY created_at ASC") as cur:
                rows = await cur.fetchall()
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

    async def delete_codex_task(self, task_id: str):
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            "DELETE FROM help_requests WHERE parent_task_id = ? OR child_task_id = ?",
            (task_id, task_id),
        )
        await conn.execute("DELETE FROM codex_task_messages WHERE task_id = ?", (task_id,))
        await conn.execute("DELETE FROM execution_processes WHERE task_id = ?", (task_id,))
        await conn.execute("DELETE FROM log_events WHERE task_id = ?", (task_id,))
        await conn.execute("DELETE FROM codex_tasks WHERE id = ?", (task_id,))
        await conn.commit()

    async def save_codex_task_message(self, message: CodexTaskMessage):
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
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
        await conn.commit()

    async def list_codex_task_messages(
        self,
        task_id: str,
        execution_process_id: str | None = None,
    ) -> list[CodexTaskMessage]:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        if execution_process_id:
            async with conn.execute(
                "SELECT * FROM codex_task_messages WHERE task_id = ? AND execution_process_id = ? ORDER BY created_at ASC",
                (task_id, execution_process_id),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with conn.execute(
                "SELECT * FROM codex_task_messages WHERE task_id = ? ORDER BY created_at ASC",
                (task_id,),
            ) as cur:
                rows = await cur.fetchall()
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

    async def reset(self):
        conn = await self._get_conn()
        async with conn.execute("SELECT name FROM sqlite_master WHERE type='table'") as cur:
            async for table in cur:
                name = table[0]
                if name != "sqlite_sequence":
                    await conn.execute(f"DELETE FROM {name}")
        await conn.commit()

    async def append_log_event(self, event: LogEvent):
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
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
        await conn.commit()

    async def load_log_events(
        self,
        session_id: str,
        task_id: str | None = None,
        execution_process_id: str | None = None,
        limit: int = 1000,
        reverse: bool = False,
    ) -> list[LogEvent]:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        order = "DESC" if reverse else "ASC"
        if execution_process_id and task_id:
            async with conn.execute(
                f"SELECT * FROM log_events WHERE session_id = ? AND task_id = ? AND execution_process_id = ? ORDER BY created_at {order} LIMIT ?",
                (session_id, task_id, execution_process_id, limit),
            ) as cur:
                rows = await cur.fetchall()
        elif execution_process_id:
            async with conn.execute(
                f"SELECT * FROM log_events WHERE session_id = ? AND execution_process_id = ? ORDER BY created_at {order} LIMIT ?",
                (session_id, execution_process_id, limit),
            ) as cur:
                rows = await cur.fetchall()
        elif task_id:
            async with conn.execute(
                f"SELECT * FROM log_events WHERE session_id = ? AND task_id = ? ORDER BY created_at {order} LIMIT ?",
                (session_id, task_id, limit),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with conn.execute(
                f"SELECT * FROM log_events WHERE session_id = ? ORDER BY created_at {order} LIMIT ?",
                (session_id, limit),
            ) as cur:
                rows = await cur.fetchall()
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

    async def save_execution_process(self, process: ExecutionProcess):
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            "INSERT OR REPLACE INTO execution_processes (id, task_id, session_id, status, exit_code, executor, provider, model, kind, triggering_message_id, started_at, completed_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (process.id, process.task_id, process.session_id, process.status, process.exit_code,
             process.executor, process.provider, process.model,
             process.kind, process.triggering_message_id,
             self._format_datetime(process.started_at),
             self._format_datetime(process.completed_at),
             self._format_datetime(process.created_at),
             self._format_datetime(process.updated_at)),
        )
        await conn.commit()

    async def load_execution_process(self, process_id: str) -> ExecutionProcess | None:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM execution_processes WHERE id = ?", (process_id,)) as cur:
            row = await cur.fetchone()
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
            kind=row["kind"] if "kind" in row.keys() and row["kind"] else "initial",
            triggering_message_id=row["triggering_message_id"] if "triggering_message_id" in row.keys() else None,
            started_at=self._parse_datetime(row["started_at"]),
            completed_at=self._parse_datetime(row["completed_at"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    async def list_execution_processes(self, session_id: str | None = None, task_id: str | None = None) -> list[ExecutionProcess]:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        if session_id and task_id:
            async with conn.execute(
                "SELECT * FROM execution_processes WHERE session_id = ? AND task_id = ? ORDER BY created_at DESC",
                (session_id, task_id),
            ) as cur:
                rows = await cur.fetchall()
        elif session_id:
            async with conn.execute(
                "SELECT * FROM execution_processes WHERE session_id = ? ORDER BY created_at DESC",
                (session_id,),
            ) as cur:
                rows = await cur.fetchall()
        elif task_id:
            async with conn.execute(
                "SELECT * FROM execution_processes WHERE task_id = ? ORDER BY created_at DESC",
                (task_id,),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with conn.execute("SELECT * FROM execution_processes ORDER BY created_at DESC") as cur:
                rows = await cur.fetchall()
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
                kind=r["kind"] if "kind" in r.keys() and r["kind"] else "initial",
                triggering_message_id=r["triggering_message_id"] if "triggering_message_id" in r.keys() else None,
                started_at=self._parse_datetime(r["started_at"]),
                completed_at=self._parse_datetime(r["completed_at"]),
                created_at=self._parse_datetime(r["created_at"]),
                updated_at=self._parse_datetime(r["updated_at"]),
            )
            for r in rows
        ]

    async def list_execution_process_runtime_rows(self, session_id: str) -> list[tuple[ExecutionProcess, CodexTask | None, list[CodexTaskMessage], list[LogEvent]]]:
        processes = await self.list_execution_processes(session_id=session_id)
        rows = []
        for process in processes:
            task = await self.load_codex_task(process.task_id)
            messages = await self.list_codex_task_messages(process.task_id, execution_process_id=process.id)
            logs = await self.load_log_events(session_id, task_id=process.task_id, execution_process_id=process.id, limit=10000)
            rows.append((process, task, messages, logs))
        return rows

    async def update_execution_process_status(self, process_id: str, status: str, exit_code: int | None = None, completed_at: datetime | None = None):
        await self._ensure_db()
        conn = await self._get_conn()
        from datetime import datetime as dt
        now = dt.now()
        completed_at_value = self._format_datetime(completed_at) if completed_at is not None else None
        await conn.execute(
            "UPDATE execution_processes SET status = ?, exit_code = ?, completed_at = ?, updated_at = ? WHERE id = ?",
            (status, exit_code, completed_at_value, self._format_datetime(now), process_id),
        )
        await conn.commit()

    # --- Runtime Catalog ---

    async def save_runtime_catalog(self, catalog: "RuntimeCatalog"):
        """Save the runtime catalog to the database."""
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            "INSERT OR REPLACE INTO runtime_catalog_settings (id, data) VALUES (?, ?)",
            ("runtime_catalog", json.dumps(catalog.model_dump())),
        )
        await conn.commit()

    async def load_runtime_catalog(self) -> "RuntimeCatalog | None":
        """Load the runtime catalog from the database."""
        await self._ensure_db()
        from app.domain.models import RuntimeCatalog
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT data FROM runtime_catalog_settings WHERE id = ?", ("runtime_catalog",)) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        try:
            data = json.loads(row["data"])
            return RuntimeCatalog(**data)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

    # --- Artifact Paths ---

    async def save_artifact(self, artifact: dict) -> None:
        """Save artifact path to database. Fields: id, issue_id, task_id, name, path, kind, created_at."""
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
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
        await conn.commit()

    async def list_artifacts(self, issue_id: str) -> list[dict]:
        """List all artifacts for an issue, ordered by created_at."""
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM artifact_paths WHERE issue_id = ? ORDER BY created_at ASC",
            (issue_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # --- Agents (PR1: Workflow DAG) ---

    def _row_to_agent(self, row) -> "Agent":
        from app.domain.models import Agent
        return Agent(
            id=row["id"],
            workspace_id=row["workspace_id"],
            name=row["name"],
            role_key=row["role_key"],
            description=row["description"],
            system_prompt_template=row["system_prompt_template"],
            input_schema=json.loads(row["input_schema"]) if row["input_schema"] else [],
            output_schema=json.loads(row["output_schema"]) if row["output_schema"] else {},
            default_executor=row["default_executor"],
            default_provider=row["default_provider"],
            default_model=row["default_model"],
            artifact_subdir=row["artifact_subdir"],
            persist_kind=row["persist_kind"],
            agent_tier=row["agent_tier"] if "agent_tier" in row.keys() and row["agent_tier"] else "managed",
            triggers_replan_on_done=bool(row["triggers_replan_on_done"]),
            triggers_replan_on_fail=bool(row["triggers_replan_on_fail"]),
            is_builtin=bool(row["is_builtin"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    async def save_agent(self, agent: "Agent") -> None:
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            """
            INSERT OR REPLACE INTO agents (
                id, workspace_id, name, role_key, description, system_prompt_template,
                input_schema, output_schema, default_executor, default_provider, default_model,
                artifact_subdir, persist_kind, agent_tier, triggers_replan_on_done, triggers_replan_on_fail,
                is_builtin, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent.id,
                agent.workspace_id,
                agent.name,
                agent.role_key,
                agent.description,
                agent.system_prompt_template,
                json.dumps(agent.input_schema) if agent.input_schema else None,
                json.dumps(agent.output_schema) if agent.output_schema else None,
                agent.default_executor,
                agent.default_provider,
                agent.default_model,
                agent.artifact_subdir,
                agent.persist_kind,
                agent.agent_tier,
                1 if agent.triggers_replan_on_done else 0,
                1 if agent.triggers_replan_on_fail else 0,
                1 if agent.is_builtin else 0,
                self._format_datetime(agent.created_at),
                self._format_datetime(agent.updated_at),
            ),
        )
        await conn.commit()

    async def load_agent(self, agent_id: str) -> "Agent | None":
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)) as cur:
            row = await cur.fetchone()
        return self._row_to_agent(row) if row else None

    async def list_agents(self, workspace_id: str | None = None, role_key: str | None = None) -> list["Agent"]:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        sql = "SELECT * FROM agents WHERE 1=1"
        params: list = []
        # Workspace scoping: when workspace_id is provided, return both global (NULL) and workspace-specific.
        if workspace_id is not None:
            sql += " AND (workspace_id IS NULL OR workspace_id = ?)"
            params.append(workspace_id)
        else:
            sql += " AND workspace_id IS NULL"
        if role_key is not None:
            sql += " AND role_key = ?"
            params.append(role_key)
        sql += " ORDER BY is_builtin DESC, created_at ASC"
        async with conn.execute(sql, tuple(params)) as cur:
            rows = await cur.fetchall()
        return [self._row_to_agent(r) for r in rows]

    async def delete_agent(self, agent_id: str) -> bool:
        await self._ensure_db()
        conn = await self._get_conn()
        cur = await conn.execute("DELETE FROM agents WHERE id = ? AND is_builtin = 0", (agent_id,))
        await conn.commit()
        return (cur.rowcount or 0) > 0

    # --- Workflow Graphs / Nodes / Edges / Replan (PR3) ---

    def _row_to_workflow_graph(self, row) -> "WorkflowGraph":
        from app.domain.models import WorkflowGraph
        return WorkflowGraph(
            id=row["id"],
            issue_id=row["issue_id"],
            preset_id=row["preset_id"],
            status=row["status"],
            dag_json=row["dag_json"],
            created_by=row["created_by"],
            locked_at=self._parse_datetime(row["locked_at"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def _row_to_workflow_node(self, row) -> "WorkflowNode":
        from app.domain.models import WorkflowNode
        return WorkflowNode(
            id=row["id"],
            graph_id=row["graph_id"],
            node_key=row["node_key"],
            agent_id=row["agent_id"],
            title=row["title"],
            prompt_override=row["prompt_override"],
            status=row["status"],
            task_id=row["task_id"],
            artifact_dir=row["artifact_dir"],
            retries=row["retries"] or 0,
            max_retries=row["max_retries"] or 1,
            instance_index=row["instance_index"] if "instance_index" in row.keys() else 0,
            started_at=self._parse_datetime(row["started_at"]),
            completed_at=self._parse_datetime(row["completed_at"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def _row_to_workflow_edge(self, row) -> "WorkflowEdge":
        from app.domain.models import WorkflowEdge
        return WorkflowEdge(
            id=row["id"],
            graph_id=row["graph_id"],
            from_node_key=row["from_node_key"],
            to_node_key=row["to_node_key"],
            edge_type=row["edge_type"],
            condition_expr=row["condition_expr"],
            created_at=self._parse_datetime(row["created_at"]),
        )

    async def save_workflow_graph(
        self,
        graph: "WorkflowGraph",
        nodes: list["WorkflowNode"] | None = None,
        edges: list["WorkflowEdge"] | None = None,
    ) -> None:
        """Persist graph + rebuild derived nodes/edges atomically."""
        await self._ensure_db()
        conn = await self._get_conn()
        now_iso = self._format_datetime(datetime.now())
        await conn.execute(
            """
            INSERT OR REPLACE INTO workflow_graphs (
                id, issue_id, preset_id, status, dag_json, created_by,
                locked_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                graph.id,
                graph.issue_id,
                graph.preset_id,
                graph.status,
                graph.dag_json,
                graph.created_by,
                self._format_datetime(graph.locked_at),
                self._format_datetime(graph.created_at) or now_iso,
                now_iso,
            ),
        )
        if nodes is not None:
            await conn.execute("DELETE FROM workflow_nodes WHERE graph_id = ?", (graph.id,))
            for n in nodes:
                await conn.execute(
                    """
                    INSERT INTO workflow_nodes (
                        id, graph_id, node_key, agent_id, title, prompt_override,
                        status, task_id, artifact_dir, retries, max_retries,
                        instance_index, started_at, completed_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        n.id,
                        n.graph_id,
                        n.node_key,
                        n.agent_id,
                        n.title,
                        n.prompt_override,
                        n.status,
                        n.task_id,
                        n.artifact_dir,
                        n.retries,
                        n.max_retries,
                        n.instance_index,
                        self._format_datetime(n.started_at),
                        self._format_datetime(n.completed_at),
                        self._format_datetime(n.created_at) or now_iso,
                        now_iso,
                    ),
                )
        if edges is not None:
            await conn.execute("DELETE FROM workflow_edges WHERE graph_id = ?", (graph.id,))
            for e in edges:
                await conn.execute(
                    """
                    INSERT INTO workflow_edges (
                        id, graph_id, from_node_key, to_node_key, edge_type,
                        condition_expr, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        e.id,
                        e.graph_id,
                        e.from_node_key,
                        e.to_node_key,
                        e.edge_type,
                        e.condition_expr,
                        self._format_datetime(e.created_at) or now_iso,
                    ),
                )
        await conn.commit()

    async def load_workflow_graph(self, graph_id: str) -> "WorkflowGraph | None":
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM workflow_graphs WHERE id = ?", (graph_id,)) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        graph = self._row_to_workflow_graph(row)
        async with conn.execute(
            "SELECT * FROM workflow_nodes WHERE graph_id = ? ORDER BY created_at ASC",
            (graph_id,),
        ) as cur:
            node_rows = await cur.fetchall()
        async with conn.execute(
            "SELECT * FROM workflow_edges WHERE graph_id = ? ORDER BY created_at ASC",
            (graph_id,),
        ) as cur:
            edge_rows = await cur.fetchall()
        graph.nodes = [self._row_to_workflow_node(r) for r in node_rows]
        graph.edges = [self._row_to_workflow_edge(r) for r in edge_rows]
        return graph

    async def load_workflow_graph_for_issue(self, issue_id: str) -> "WorkflowGraph | None":
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT id FROM workflow_graphs WHERE issue_id = ? ORDER BY created_at DESC LIMIT 1",
            (issue_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return await self.load_workflow_graph(row["id"])

    _UNSET = object()  # sentinel: caller did not pass this kwarg

    async def update_workflow_node(
        self,
        node_id: str,
        *,
        status: str | None = None,
        task_id: str | None = None,
        artifact_dir: str | None = None,
        prompt_override: str | None = None,
        retries: int | None = None,
        started_at: datetime | None = None,
        completed_at: object = _UNSET,  # use sentinel so None means "clear to NULL"
    ) -> None:
        await self._ensure_db()
        conn = await self._get_conn()
        sets: list[str] = []
        params: list = []
        if status is not None:
            sets.append("status = ?"); params.append(status)
        if task_id is not None:
            sets.append("task_id = ?"); params.append(task_id)
        if artifact_dir is not None:
            sets.append("artifact_dir = ?"); params.append(artifact_dir)
        if prompt_override is not None:
            sets.append("prompt_override = ?"); params.append(prompt_override)
        if retries is not None:
            sets.append("retries = ?"); params.append(retries)
        if started_at is not None:
            sets.append("started_at = ?"); params.append(self._format_datetime(started_at))
        if completed_at is not self._UNSET:
            # Explicit None clears the column to NULL; a datetime value formats it.
            db_val = self._format_datetime(completed_at) if completed_at is not None else None
            sets.append("completed_at = ?"); params.append(db_val)
        sets.append("updated_at = ?"); params.append(self._format_datetime(datetime.now()))
        params.append(node_id)
        await conn.execute(f"UPDATE workflow_nodes SET {', '.join(sets)} WHERE id = ?", tuple(params))
        await conn.commit()

    async def find_node_by_task_id(self, task_id: str) -> "WorkflowNode | None":
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM workflow_nodes WHERE task_id = ? ORDER BY updated_at DESC LIMIT 1",
            (task_id,),
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_workflow_node(row) if row else None

    async def save_replan_pending(self, replan: "GraphReplanPending") -> None:
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            """
            INSERT OR REPLACE INTO graph_replan_pending (
                id, graph_id, triggered_by_node_key, trigger_reason,
                diff_json, rationale, status, created_at, resolved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                replan.id,
                replan.graph_id,
                replan.triggered_by_node_key,
                replan.trigger_reason,
                replan.diff_json,
                replan.rationale,
                replan.status,
                self._format_datetime(replan.created_at),
                self._format_datetime(replan.resolved_at),
            ),
        )
        await conn.commit()

    async def list_pending_replans(self, graph_id: str) -> list["GraphReplanPending"]:
        from app.domain.models import GraphReplanPending
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM graph_replan_pending WHERE graph_id = ? AND status = 'pending' ORDER BY created_at ASC",
            (graph_id,),
        ) as cur:
            rows = await cur.fetchall()
        out: list[GraphReplanPending] = []
        for r in rows:
            out.append(GraphReplanPending(
                id=r["id"],
                graph_id=r["graph_id"],
                triggered_by_node_key=r["triggered_by_node_key"],
                trigger_reason=r["trigger_reason"],
                diff_json=r["diff_json"],
                rationale=r["rationale"],
                status=r["status"],
                created_at=self._parse_datetime(r["created_at"]),
                resolved_at=self._parse_datetime(r["resolved_at"]),
            ))
        return out

    async def resolve_replan(self, replan_id: str, status: str) -> bool:
        await self._ensure_db()
        conn = await self._get_conn()
        cur = await conn.execute(
            "UPDATE graph_replan_pending SET status = ?, resolved_at = ? WHERE id = ? AND status = 'pending'",
            (status, self._format_datetime(datetime.now()), replan_id),
        )
        await conn.commit()
        return (cur.rowcount or 0) > 0

    async def save_agent_message(self, msg: "AgentMessage") -> None:
        from app.domain.models import AgentMessage  # noqa: F401 (type hint import)
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            """INSERT OR REPLACE INTO agent_messages
               (id, issue_id, graph_id, from_node_key, to_node_key, message_type, body, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                msg.id,
                msg.issue_id,
                msg.graph_id,
                msg.from_node_key,
                msg.to_node_key,
                msg.message_type,
                msg.body,
                self._format_datetime(msg.created_at or datetime.now()),
            ),
        )
        await conn.commit()

    async def list_agent_messages(self, issue_id: str) -> list["AgentMessage"]:
        from app.domain.models import AgentMessage
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM agent_messages WHERE issue_id = ? ORDER BY created_at ASC",
            (issue_id,),
        ) as cur:
            rows = await cur.fetchall()
        out: list[AgentMessage] = []
        for r in rows:
            out.append(AgentMessage(
                id=r["id"],
                issue_id=r["issue_id"],
                graph_id=r["graph_id"],
                from_node_key=r["from_node_key"],
                to_node_key=r["to_node_key"],
                message_type=r["message_type"],
                body=r["body"],
                created_at=self._parse_datetime(r["created_at"]),
            ))
        return out

    async def save_conductor_state(self, state: "ConductorState") -> None:
        from app.domain.models import ConductorState  # noqa: F401 (type hint import)
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
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
        await conn.commit()

    async def load_conductor_state(self, issue_id: str) -> "ConductorState | None":
        from app.domain.models import ConductorState
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM conductor_states WHERE issue_id = ?",
            (issue_id,),
        ) as cur:
            row = await cur.fetchone()
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

    async def save_conductor_decision(self, d: "ConductorDecision") -> None:
        from app.domain.models import ConductorDecision  # noqa: F401 (type hint import)
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            """INSERT OR REPLACE INTO conductor_decisions
               (id, issue_id, task_id, action, reason, diff_json, applied_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                d.id,
                d.issue_id,
                d.task_id,
                d.action,
                d.reason,
                d.diff_json,
                self._format_datetime(d.applied_at),
                self._format_datetime(d.created_at or datetime.now()),
            ),
        )
        await conn.commit()

    async def list_conductor_decisions(self, issue_id: str) -> list["ConductorDecision"]:
        from app.domain.models import ConductorDecision
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM conductor_decisions WHERE issue_id = ? ORDER BY created_at ASC",
            (issue_id,),
        ) as cur:
            rows = await cur.fetchall()
        out: list[ConductorDecision] = []
        for r in rows:
            out.append(ConductorDecision(
                id=r["id"],
                issue_id=r["issue_id"],
                task_id=r["task_id"],
                action=r["action"],
                reason=r["reason"],
                diff_json=r["diff_json"],
                applied_at=self._parse_datetime(r["applied_at"]),
                created_at=self._parse_datetime(r["created_at"]),
            ))
        return out
