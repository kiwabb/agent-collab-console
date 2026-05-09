import asyncio
import json
from datetime import datetime
from pathlib import Path

import aiosqlite

from app.domain.models import Session, Task, AgentRun, Artifact, Message, Approval, ApprovalEvent, PlanDetails, CodexSession, CodexMessage, CodexIssue, CodexTask, CodexTaskMessage, LogEvent, ExecutionProcess, HelpRequest, RuntimeCatalog


class AsyncSQLiteStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._conn_lock = asyncio.Lock()

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
                status TEXT DEFAULT 'idle',
                created_at TEXT,
                last_active_at TEXT,
                log_path TEXT,
                thread_id TEXT,
                claude_thread_id TEXT
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
                title TEXT NOT NULL,
                description TEXT,
                current_phase TEXT NOT NULL DEFAULT 'requirements',
                status TEXT NOT NULL DEFAULT 'open',
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
        # Create runtime_catalog_settings table if not exists
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS runtime_catalog_settings (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            )
        """)
        # Create indexes for frequently queried columns
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_codex_tasks_session_id ON codex_tasks(session_id)")
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
            "INSERT OR REPLACE INTO codex_sessions (id, title, cwd, status, created_at, last_active_at, log_path, thread_id, claude_thread_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session.id, session.title, session.cwd, session.status,
             self._format_datetime(session.created_at),
             self._format_datetime(session.last_active_at),
             session.log_path,
             session.thread_id,
             session.claude_thread_id),
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
            status=row["status"],
            created_at=self._parse_datetime(row["created_at"]),
            last_active_at=self._parse_datetime(row["last_active_at"]),
            log_path=row["log_path"],
            thread_id=row["thread_id"] if "thread_id" in row.keys() else None,
            claude_thread_id=row["claude_thread_id"] if "claude_thread_id" in row.keys() else None,
            messages=messages,
        )

    async def load_codex_workspace(self, workspace_id: str) -> CodexSession | None:
        return await self.load_codex_session(workspace_id)

    async def list_codex_sessions(self) -> list[dict]:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT id, title, status, created_at, last_active_at FROM codex_sessions ORDER BY last_active_at DESC") as cur:
            rows = await cur.fetchall()
        return [{"id": r["id"], "title": r["title"], "status": r["status"],
                 "created_at": r["created_at"], "last_active_at": r["last_active_at"]} for r in rows]

    async def list_codex_workspaces(self) -> list[dict]:
        return await self.list_codex_sessions()

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
            "INSERT OR REPLACE INTO codex_issues (id, session_id, title, description, current_phase, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                issue.id,
                issue.session_id,
                issue.title,
                issue.description,
                issue.current_phase,
                issue.status,
                self._format_datetime(issue.created_at),
                self._format_datetime(issue.updated_at),
            ),
        )
        await conn.commit()

    async def load_codex_issue(self, issue_id: str) -> CodexIssue | None:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM codex_issues WHERE id = ?", (issue_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return CodexIssue(
            id=row["id"],
            session_id=row["session_id"],
            title=row["title"],
            description=row["description"],
            current_phase=row["current_phase"],
            status=row["status"],
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    async def list_codex_issues(self, session_id: str | None = None) -> list[dict]:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        select_sql = "SELECT id, session_id, title, description, current_phase, status, created_at, updated_at FROM codex_issues"
        if session_id:
            async with conn.execute(f"{select_sql} WHERE session_id = ? ORDER BY updated_at DESC, created_at DESC", (session_id,)) as cur:
                rows = await cur.fetchall()
        else:
            async with conn.execute(f"{select_sql} ORDER BY updated_at DESC, created_at DESC") as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def save_codex_task(self, task: CodexTask):
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            "INSERT OR REPLACE INTO codex_tasks (id, session_id, issue_id, phase, title, prompt, role, executor, provider, model, status, result, parent_task_id, task_kind, blocked_by_help_id, workspace_path, resume_session_id, resume_message_id, last_execution_process_id, sequence_index, sequence_group, review_comment, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (task.id, task.session_id, task.issue_id, task.phase, task.title, task.prompt, task.role, task.executor,
             task.provider, task.model, task.status, task.result, task.parent_task_id, task.task_kind, task.blocked_by_help_id,
             task.workspace_path, task.resume_session_id, task.resume_message_id, task.last_execution_process_id,
             task.sequence_index, task.sequence_group, task.review_comment,
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
            parent_task_id=row["parent_task_id"] if row["parent_task_id"] else None,
            task_kind=row["task_kind"] if "task_kind" in row.keys() and row["task_kind"] else "normal",
            blocked_by_help_id=row["blocked_by_help_id"] if "blocked_by_help_id" in row.keys() and row["blocked_by_help_id"] else None,
            workspace_path=row["workspace_path"] if "workspace_path" in row.keys() and row["workspace_path"] else None,
            resume_session_id=row["resume_session_id"] if "resume_session_id" in row.keys() and row["resume_session_id"] else None,
            resume_message_id=row["resume_message_id"] if "resume_message_id" in row.keys() and row["resume_message_id"] else None,
            last_execution_process_id=row["last_execution_process_id"] if "last_execution_process_id" in row.keys() and row["last_execution_process_id"] else None,
            sequence_index=row["sequence_index"] if "sequence_index" in row.keys() else None,
            sequence_group=row["sequence_group"] if "sequence_group" in row.keys() else None,
            review_comment=row["review_comment"] if "review_comment" in row.keys() else None,
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    async def list_codex_tasks(self, session_id: str | None = None, issue_id: str | None = None) -> list[dict]:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        select_sql = "SELECT id, session_id, issue_id, phase, title, prompt, role, executor, status, result, parent_task_id, task_kind, blocked_by_help_id, workspace_path, resume_session_id, resume_message_id, last_execution_process_id, sequence_index, sequence_group, review_comment, created_at, updated_at FROM codex_tasks"
        if session_id and issue_id:
            async with conn.execute(
                f"{select_sql} WHERE session_id = ? AND issue_id = ? ORDER BY created_at ASC",
                (session_id, issue_id),
            ) as cur:
                rows = await cur.fetchall()
        elif session_id:
            async with conn.execute(
                f"{select_sql} WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ) as cur:
                rows = await cur.fetchall()
        elif issue_id:
            async with conn.execute(
                f"{select_sql} WHERE issue_id = ? ORDER BY created_at ASC",
                (issue_id,),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with conn.execute(f"{select_sql} ORDER BY created_at ASC") as cur:
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
            "INSERT OR REPLACE INTO execution_processes (id, task_id, session_id, status, exit_code, executor, provider, model, started_at, completed_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (process.id, process.task_id, process.session_id, process.status, process.exit_code,
             process.executor, process.provider, process.model,
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
        await conn.execute(
            "UPDATE execution_processes SET status = ?, exit_code = ?, completed_at = ?, updated_at = ? WHERE id = ?",
            (status, exit_code, self._format_datetime(completed_at or now), self._format_datetime(now), process_id),
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
