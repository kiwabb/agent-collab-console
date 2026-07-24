import asyncio
import json
import logging
import re
from collections.abc import Sequence
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import aiosqlite
from pydantic import ValidationError

from app.adapters.audit_log_query import build_audit_log_query as _build_audit_log_query
from app.adapters.structured_prototype_store import (
    STRUCTURED_PROTOTYPE_GENERATION_SNAPSHOT_COLUMNS,
    STRUCTURED_PROTOTYPE_RUNTIME_SESSION_COLUMNS,
    STRUCTURED_PROTOTYPE_RUNTIME_SESSION_REPLACEMENT_INDEX_SQL,
    STRUCTURED_PROTOTYPE_SCHEMA_SQL,
)
from app.domain.models import (
    Agent,
    AgentCallTrace,
    AgentMessage,
    AgentRun,
    Approval,
    ApprovalEvent,
    Artifact,
    AuditLog,
    CodexIssue,
    CodexMessage,
    CodexSession,
    CodexTask,
    CodexTaskMessage,
    ConductorDecision,
    ConductorState,
    ConductorStateLog,
    ConductorTask,
    ConductorTurn,
    ExecutionProcess,
    GraphReplanPending,
    HelpRequest,
    LogEvent,
    Message,
    PlanDetails,
    Project,
    ProjectConductorState,
    ProjectEnvVar,
    ProjectMemoryEmbedding,
    ProjectReadinessProbe,
    ProjectStartupEvidence,
    ProjectStartupService,
    RuntimeCatalog,
    SelfImprovementApplicationEvent,
    SelfImprovementProposal,
    Session,
    Skill,
    Task,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)
from app.json_safety import object_dict_list, object_dict_or_none, parse_json_value

logger = logging.getLogger(__name__)


class RowWithKeys(Protocol):
    def keys(self) -> Sequence[str]: ...


SQLITE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _row_has_key(row: RowWithKeys, key: str) -> bool:
    """Return whether a sqlite row exposes a column name."""
    return key in row.keys()  # noqa: SIM118 - sqlite Row membership checks values, not column names.


def _quote_sqlite_identifier(name: object) -> str:
    if not isinstance(name, str) or SQLITE_IDENTIFIER_RE.fullmatch(name) is None:
        raise ValueError(f"unsafe sqlite identifier: {name!r}")
    return f'"{name}"'


def _project_readiness_probe(raw: object) -> ProjectReadinessProbe | None:
    if not isinstance(raw, str) or not raw:
        return None
    parsed = parse_json_value(raw)
    try:
        return ProjectReadinessProbe.model_validate(parsed)
    except ValidationError:
        return None


def _project_startup_evidence(raw: object) -> list[ProjectStartupEvidence]:
    if not isinstance(raw, str) or not raw:
        return []
    parsed = parse_json_value(raw, default=[])
    if not isinstance(parsed, list):
        return []
    evidence: list[ProjectStartupEvidence] = []
    for item in parsed:
        if isinstance(item, str) and item.strip():
            evidence.append(ProjectStartupEvidence(path=item.strip()))
            continue
        try:
            evidence.append(ProjectStartupEvidence.model_validate(item))
        except ValidationError:
            continue
    return evidence


def _log_events_query(*, has_task_id: bool, has_execution_process_id: bool, reverse: bool) -> str:
    if has_task_id and has_execution_process_id:
        if reverse:
            return "SELECT * FROM log_events WHERE session_id = ? AND task_id = ? AND execution_process_id = ? ORDER BY created_at DESC LIMIT ?"
        return "SELECT * FROM log_events WHERE session_id = ? AND task_id = ? AND execution_process_id = ? ORDER BY created_at ASC LIMIT ?"
    if has_execution_process_id:
        if reverse:
            return "SELECT * FROM log_events WHERE session_id = ? AND execution_process_id = ? ORDER BY created_at DESC LIMIT ?"
        return "SELECT * FROM log_events WHERE session_id = ? AND execution_process_id = ? ORDER BY created_at ASC LIMIT ?"
    if has_task_id:
        if reverse:
            return "SELECT * FROM log_events WHERE session_id = ? AND task_id = ? ORDER BY created_at DESC LIMIT ?"
        return "SELECT * FROM log_events WHERE session_id = ? AND task_id = ? ORDER BY created_at ASC LIMIT ?"
    if reverse:
        return "SELECT * FROM log_events WHERE session_id = ? ORDER BY created_at DESC LIMIT ?"
    return "SELECT * FROM log_events WHERE session_id = ? ORDER BY created_at ASC LIMIT ?"


def _json_object(value: str | None) -> dict[str, object] | None:
    if not value:
        return None
    parsed: object = json.loads(value)
    return object_dict_or_none(parsed)


def _json_string_list(value: str | None) -> list[str] | None:
    if not value:
        return None
    parsed: object = json.loads(value)
    if not isinstance(parsed, list):
        return None
    return [item for item in parsed if isinstance(item, str)]


def _issue_acceptance_criteria(value: object) -> list[str]:
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed: object = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        return []
    return [item.strip() for item in parsed if item.strip()]


def _json_object_list(value: str | None) -> list[dict[str, object]]:
    if not value:
        return []
    parsed: object = json.loads(value)
    return object_dict_list(parsed)


def _codex_settings(value: str | None) -> dict[str, bool]:
    parsed = _json_object(value)
    if parsed is None:
        return {"plan_first_pm": True}
    settings = {key: item for key, item in parsed.items() if isinstance(item, bool)}
    return settings or {"plan_first_pm": True}


def _plan_details(value: str | None) -> PlanDetails | None:
    parsed = _json_object(value)
    if parsed is None:
        return None
    summary = parsed.get("summary")
    next_steps = parsed.get("next_steps")
    task_title = parsed.get("task_title")
    if not isinstance(summary, str) or not isinstance(task_title, str):
        return None
    if not isinstance(next_steps, list) or not all(isinstance(item, str) for item in next_steps):
        return None
    return PlanDetails(summary=summary, next_steps=next_steps, task_title=task_title)


def _preserved_json_array_items(raw: str) -> list[tuple[object, str]]:
    """Decode array values while preserving each retained element's exact JSON bytes."""
    decoder = json.JSONDecoder()
    index = 0
    length = len(raw)

    while index < length and raw[index].isspace():
        index += 1
    if index >= length or raw[index] != "[":
        raise ValueError("expected a JSON array")
    index += 1

    items: list[tuple[object, str]] = []
    while True:
        while index < length and raw[index].isspace():
            index += 1
        if index < length and raw[index] == "]":
            index += 1
            break
        start = index
        value, index = decoder.raw_decode(raw, index)
        items.append((value, raw[start:index]))
        while index < length and raw[index].isspace():
            index += 1
        if index < length and raw[index] == ",":
            index += 1
            continue
        if index < length and raw[index] == "]":
            index += 1
            break
        raise ValueError("malformed JSON array separator")

    if raw[index:].strip():
        raise ValueError("unexpected data after JSON array")
    return items


def _project_conductor_memory_text(value: object) -> str:
    return str(value.get("summary", "")) if isinstance(value, dict) else str(value)


def _contains_legacy_recursive_compaction_signature(summary: str, signature: str) -> bool:
    """Match a legacy review pair only at a summarizer fragment boundary."""
    return summary.startswith(signature) or f" | {signature}" in summary


class AsyncSQLiteStore:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._conn_lock = asyncio.Lock()
        self._init_lock = asyncio.Lock()
        self._initialized_connection: aiosqlite.Connection | None = None

    async def close(self) -> None:
        """Close the connection. Call this on app shutdown."""
        async with self._conn_lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None
                self._initialized_connection = None

    async def _get_conn(self) -> aiosqlite.Connection:
        async with self._conn_lock:
            if self._conn is None:
                self._conn = await aiosqlite.connect(self.db_path, timeout=30.0)
                await self._conn.execute("PRAGMA journal_mode=WAL")
                await self._conn.execute("PRAGMA synchronous=NORMAL")
                await self._conn.execute("PRAGMA busy_timeout=30000")
            return self._conn

    @staticmethod
    async def _apply_project_conductor_v16_migration(
        conn: aiosqlite.Connection,
    ) -> None:
        """Repair the legacy scheduled-review feedback loop inside one transaction."""
        invalid_state = await (
            await conn.execute(
                """SELECT project_id
                   FROM project_conductor_states
                   WHERE json_type(
                             CASE WHEN json_valid(hot_thread_json)
                                  THEN hot_thread_json ELSE 'null' END
                         ) <> 'array'
                      OR json_type(
                             CASE WHEN json_valid(warm_summaries_json)
                                  THEN warm_summaries_json ELSE 'null' END
                         ) <> 'array'
                   LIMIT 1"""
            )
        ).fetchone()
        if invalid_state is not None:
            raise ValueError(
                f"project conductor state JSON is invalid for project {invalid_state[0]}"
            )
        invalid_task = await (
            await conn.execute(
                """SELECT id
                   FROM conductor_tasks
                   WHERE task_kind = 'scheduled_review'
                     AND result_json IS NOT NULL
                     AND instr(result_json, 'ProjectConductor context answer.') > 0
                     AND instr(result_json, 'Run a scheduled project health review.') > 0
                     AND NOT json_valid(result_json)
                   LIMIT 1"""
            )
        ).fetchone()
        if invalid_task is not None:
            raise ValueError(
                f"scheduled project review result JSON is invalid for task {invalid_task[0]}"
            )

        recursive_task_rows = await (
            await conn.execute(
                """SELECT id, project_id, json_extract(result_json, '$.answer')
                   FROM conductor_tasks
                   WHERE task_kind = 'scheduled_review'
                     AND status = 'done'
                     AND json_valid(result_json)
                     AND instr(
                         COALESCE(json_extract(result_json, '$.answer'), ''),
                         'ProjectConductor context answer.'
                     ) > 0
                     AND instr(
                         COALESCE(json_extract(result_json, '$.answer'), ''),
                         'Run a scheduled project health review.'
                     ) > 0"""
            )
        ).fetchall()
        recursive_task_ids_by_project: dict[str, set[str]] = {}
        recursive_compaction_signatures_by_project: dict[str, set[str]] = {}
        for task_id, project_id, answer in recursive_task_rows:
            project_key = str(project_id)
            answer_prefix = str(answer)[:240]
            recursive_task_ids_by_project.setdefault(project_key, set()).add(str(task_id))
            recursive_compaction_signatures_by_project.setdefault(project_key, set()).add(
                f"user: Run a scheduled project health review. | project_conductor: {answer_prefix}"
            )

        removed_warm_source_ids: dict[str, set[str]] = {}
        state_rows = await (
            await conn.execute(
                """SELECT project_id, hot_thread_json, warm_summaries_json
                   FROM project_conductor_states"""
            )
        ).fetchall()
        for project_id_value, hot_json_value, warm_json_value in state_rows:
            project_id = str(project_id_value)
            recursive_task_ids = recursive_task_ids_by_project.get(project_id)
            if not recursive_task_ids:
                continue

            hot_items = _preserved_json_array_items(str(hot_json_value))
            retained_hot = [
                raw_item
                for value, raw_item in hot_items
                if not (
                    isinstance(value, dict) and str(value.get("task_id", "")) in recursive_task_ids
                )
            ]
            warm_items = _preserved_json_array_items(str(warm_json_value))
            retained_warm: list[str] = []
            removed_ids = removed_warm_source_ids.setdefault(project_id, set())
            recursive_signatures = recursive_compaction_signatures_by_project[project_id]
            for value, raw_item in warm_items:
                summary = _project_conductor_memory_text(value)
                if any(
                    _contains_legacy_recursive_compaction_signature(summary, signature)
                    for signature in recursive_signatures
                ):
                    if isinstance(value, dict) and value.get("id"):
                        removed_ids.add(str(value["id"]))
                    continue
                retained_warm.append(raw_item)

            if len(retained_hot) == len(hot_items) and len(retained_warm) == len(warm_items):
                continue
            repaired_hot_json = f"[{','.join(retained_hot)}]"
            repaired_warm_json = f"[{','.join(retained_warm)}]"
            await conn.execute(
                """UPDATE project_conductor_states
                   SET hot_thread_json = ?, warm_summaries_json = ?,
                       hot_tokens = ?, warm_tokens = ?
                   WHERE project_id = ?""",
                (
                    repaired_hot_json,
                    repaired_warm_json,
                    0 if not retained_hot else max(1, len(repaired_hot_json) // 4),
                    0 if not retained_warm else max(1, len(repaired_warm_json) // 4),
                    project_id,
                ),
            )

        for project_id in recursive_task_ids_by_project:
            await conn.execute(
                """INSERT INTO project_audit (project_id, issue_id, event, created_at)
                   SELECT ?, NULL, 'project_conductor_recursive_memory_repaired', datetime('now')
                   WHERE NOT EXISTS (
                       SELECT 1 FROM project_audit
                       WHERE project_id = ?
                         AND event = 'project_conductor_recursive_memory_repaired'
                   )""",
                (project_id, project_id),
            )
            for source_id in removed_warm_source_ids.get(project_id, set()):
                await conn.execute(
                    """DELETE FROM project_memory_embeddings
                       WHERE project_id = ? AND source_kind = 'warm_summary' AND source_id = ?""",
                    (project_id, source_id),
                )
            cold_rows = await (
                await conn.execute(
                    """SELECT id, source_id, summary_text
                       FROM project_memory_embeddings
                       WHERE project_id = ? AND source_kind = 'warm_summary'""",
                    (project_id,),
                )
            ).fetchall()
            recursive_signatures = recursive_compaction_signatures_by_project[project_id]
            for memory_id, source_id, summary_text in cold_rows:
                summary = str(summary_text)
                if not any(
                    _contains_legacy_recursive_compaction_signature(summary, signature)
                    for signature in recursive_signatures
                ):
                    continue
                await conn.execute(
                    """DELETE FROM project_memory_embeddings
                       WHERE id = ? AND project_id = ? AND source_kind = 'warm_summary'
                         AND source_id = ? AND summary_text = ?""",
                    (str(memory_id), project_id, str(source_id), summary),
                )
        await conn.execute(
            """UPDATE conductor_tasks
               SET result_json = json_set(
                   result_json,
                   '$.answer',
                   'Scheduled project review completed. '
                   || 'Historical recursive context was removed.'
               )
               WHERE task_kind = 'scheduled_review'
                 AND status = 'done'
                 AND json_valid(result_json)
                 AND instr(
                     COALESCE(json_extract(result_json, '$.answer'), ''),
                     'ProjectConductor context answer.'
                 ) > 0
                 AND instr(
                     COALESCE(json_extract(result_json, '$.answer'), ''),
                     'Run a scheduled project health review.'
                 ) > 0"""
        )
        await conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_conductor_tasks_project_review_due
               ON conductor_tasks(project_id, task_kind, status, updated_at DESC)"""
        )
        await conn.execute(
            "INSERT OR REPLACE INTO schema_version (id, version) VALUES (1, ?)",
            (16,),
        )

    async def _init_db(self) -> None:
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
                acceptance_criteria TEXT NOT NULL DEFAULT '[]',
                acceptance_criteria_confirmed INTEGER NOT NULL DEFAULT 0,
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
                trace_id TEXT,
                span_id TEXT,
                parent_span_id TEXT,
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
                trace_id TEXT,
                span_id TEXT,
                parent_span_id TEXT,
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
        for table in ["tasks", "runs", "artifacts", "messages", "approvals", "approval_events"]:
            with suppress(aiosqlite.OperationalError):
                await conn.execute(f"ALTER TABLE {table} ADD COLUMN created_at TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_sessions ADD COLUMN thread_id TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_sessions ADD COLUMN claude_thread_id TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_sessions ADD COLUMN project_id TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_sessions ADD COLUMN settings_json TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE log_events ADD COLUMN task_id TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute(
                "ALTER TABLE codex_task_messages ADD COLUMN execution_process_id TEXT"
            )
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE log_events ADD COLUMN execution_process_id TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute(
                "ALTER TABLE codex_tasks ADD COLUMN phase TEXT DEFAULT 'requirements'"
            )
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN issue_id TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN role TEXT DEFAULT 'general'")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN executor TEXT DEFAULT 'codex'")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN resume_session_id TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN resume_message_id TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN workspace_path TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN last_execution_process_id TEXT")
        # Distributed-tracing identity (approach C) on tasks, log_events, audit_log.
        for _trace_col in ("trace_id", "span_id", "parent_span_id"):
            with suppress(aiosqlite.OperationalError):
                await conn.execute(f"ALTER TABLE codex_tasks ADD COLUMN {_trace_col} TEXT")
            with suppress(aiosqlite.OperationalError):
                await conn.execute(f"ALTER TABLE log_events ADD COLUMN {_trace_col} TEXT")
            with suppress(aiosqlite.OperationalError):
                await conn.execute(f"ALTER TABLE audit_log ADD COLUMN {_trace_col} TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN task_kind TEXT DEFAULT 'normal'")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN blocked_by_help_id TEXT")
        # Add provider and model columns to codex_tasks
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN provider TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN model TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN result_json TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE agents ADD COLUMN agent_tier TEXT DEFAULT 'managed'")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_issues ADD COLUMN project_id TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute(
                "ALTER TABLE codex_issues ADD COLUMN acceptance_criteria TEXT NOT NULL DEFAULT '[]'"
            )
        with suppress(aiosqlite.OperationalError):
            await conn.execute(
                "ALTER TABLE codex_issues ADD COLUMN acceptance_criteria_confirmed INTEGER NOT NULL DEFAULT 0"
            )
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_issues ADD COLUMN review_comment TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_issues ADD COLUMN milestone TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_issues ADD COLUMN git_branch TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_issues ADD COLUMN git_base_branch TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_issues ADD COLUMN git_worktree_path TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute(
                "ALTER TABLE codex_issues ADD COLUMN git_merge_status TEXT DEFAULT 'open'"
            )
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_issues ADD COLUMN git_last_commit_sha TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_issues ADD COLUMN github_pr_url TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_issues ADD COLUMN github_pr_state TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute(
                "ALTER TABLE codex_issues ADD COLUMN is_pinned INTEGER NOT NULL DEFAULT 0"
            )
        # Issue-level executor selection (propagated to Conductor sub-agents)
        for _issue_exec_col in ("executor", "provider", "model"):
            with suppress(aiosqlite.OperationalError):
                await conn.execute(f"ALTER TABLE codex_issues ADD COLUMN {_issue_exec_col} TEXT")
        # Per-issue cost budget (cost-aware conductor scheduling, PR2)
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_issues ADD COLUMN budget_usd REAL")
        # Add executor/provider/model snapshot columns to execution_processes
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE execution_processes ADD COLUMN executor TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE execution_processes ADD COLUMN provider TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE execution_processes ADD COLUMN model TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute(
                "ALTER TABLE execution_processes ADD COLUMN kind TEXT NOT NULL DEFAULT 'initial'"
            )
        with suppress(aiosqlite.OperationalError):
            await conn.execute(
                "ALTER TABLE execution_processes ADD COLUMN triggering_message_id TEXT"
            )
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN sequence_index INTEGER")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN sequence_group TEXT")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN review_comment TEXT")
        # Add token usage and cost columns to execution_processes
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE execution_processes ADD COLUMN input_tokens INTEGER")
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE execution_processes ADD COLUMN output_tokens INTEGER")
        with suppress(aiosqlite.OperationalError):
            await conn.execute(
                "ALTER TABLE execution_processes ADD COLUMN cache_read_tokens INTEGER"
            )
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE execution_processes ADD COLUMN total_cost_usd REAL")
        # --- Project / git worktree feature additions ---
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                repo_path TEXT NOT NULL,
                default_branch TEXT NOT NULL DEFAULT 'main',
                origin_url TEXT,
                setup_script TEXT,
                run_command TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        for stmt in ("ALTER TABLE projects ADD COLUMN run_command TEXT",):
            with suppress(aiosqlite.OperationalError):
                await conn.execute(stmt)
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_repo_path ON projects(repo_path)"
        )
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS project_startup_configs (
                project_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                notes_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES codex_tasks(id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS project_startup_services (
                project_id TEXT NOT NULL,
                service_id TEXT NOT NULL,
                name TEXT NOT NULL,
                working_directory TEXT NOT NULL,
                setup_command TEXT NOT NULL DEFAULT '',
                run_command TEXT NOT NULL,
                access_url TEXT,
                readiness_probe_json TEXT,
                depends_on_json TEXT NOT NULL DEFAULT '[]',
                evidence_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT,
                updated_at TEXT,
                PRIMARY KEY (project_id, service_id),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
        """)
        with suppress(aiosqlite.OperationalError):
            await conn.execute(
                "ALTER TABLE project_startup_services ADD COLUMN readiness_probe_json TEXT"
            )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_project_startup_services_project_id "
            "ON project_startup_services(project_id)"
        )
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
            with suppress(aiosqlite.OperationalError):
                await conn.execute(stmt)
        # One-time wipe of legacy codex data so all rows have project_id.
        # The decision to clear was made explicitly (dev-stage data).
        version_row = await (
            await conn.execute("SELECT version FROM schema_version WHERE id = 1")
        ).fetchone()
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
            current_version = 2
        if current_version < 3:
            await conn.execute(
                "INSERT OR REPLACE INTO schema_version (id, version) VALUES (1, ?)",
                (3,),
            )
            current_version = 3
        if current_version < 4:
            await conn.execute(
                "INSERT OR REPLACE INTO schema_version (id, version) VALUES (1, ?)",
                (4,),
            )
            current_version = 4
        # Create runtime_catalog_settings table if not exists
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS runtime_catalog_settings (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            )
        """)
        # Skills library — references to externally hosted markdown playbooks.
        # Body is not stored locally; UI fetches `link` via proxy on demand.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS skills (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                link TEXT NOT NULL,
                description TEXT,
                category TEXT,
                tags TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_skills_category ON skills(category)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(name)")
        # User-defined skill categories (allows pre-creating empty groups so
        # the user can drag skills into them).
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS skill_categories (
                name TEXT PRIMARY KEY
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
        with suppress(Exception):
            await conn.execute("ALTER TABLE codex_tasks ADD COLUMN workflow_node_id TEXT")
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
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS project_conductor_states (
                project_id TEXT PRIMARY KEY,
                hot_thread_json TEXT NOT NULL DEFAULT '[]',
                warm_summaries_json TEXT NOT NULL DEFAULT '[]',
                pinned_text TEXT NOT NULL DEFAULT '',
                hot_tokens INTEGER NOT NULL DEFAULT 0,
                warm_tokens INTEGER NOT NULL DEFAULT 0,
                last_compaction_at TEXT,
                total_tasks_handled INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT,
                revision INTEGER NOT NULL DEFAULT 1
            )
        """)
        await conn.execute("""
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
        await conn.execute("""
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
        await conn.execute("""
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
        await conn.execute("""
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
        await conn.execute("""
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
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS self_improvement_application_events (
                id TEXT PRIMARY KEY,
                proposal_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                issue_id TEXT NOT NULL,
                target_kind TEXT NOT NULL,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                path TEXT,
                content_sha256 TEXT,
                result_json TEXT NOT NULL DEFAULT '{}',
                error TEXT,
                created_at TEXT
            )
        """)
        # Unified audit trail (PR1). One row per LLM call/return, tool use/result,
        # command exec, git command, CLI spawn, generic event, or agent finalize.
        # Line-level stdout/stderr stays in log_events (joined via
        # execution_process_id), not mirrored here.
        await conn.execute("""
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
                trace_id TEXT,
                span_id TEXT,
                parent_span_id TEXT,
                status TEXT,
                duration_ms INTEGER,
                payload_json TEXT NOT NULL DEFAULT '{}',
                error TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_call_traces (
                id TEXT PRIMARY KEY,
                audit_log_id TEXT,
                trace_id TEXT,
                span_id TEXT,
                parent_span_id TEXT,
                issue_id TEXT,
                task_id TEXT,
                execution_process_id TEXT,
                kind TEXT NOT NULL,
                title TEXT,
                request_json TEXT,
                response_json TEXT,
                request_preview TEXT,
                response_preview TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                is_truncated INTEGER NOT NULL DEFAULT 0,
                created_at TEXT
            )
        """)
        if current_version < 8:
            await conn.execute(
                "INSERT OR REPLACE INTO schema_version (id, version) VALUES (1, ?)",
                (8,),
            )
            current_version = 8
        if current_version < 9:
            await conn.execute(
                "INSERT OR REPLACE INTO schema_version (id, version) VALUES (1, ?)",
                (9,),
            )
            current_version = 9
        if current_version < 11:
            await conn.executescript(STRUCTURED_PROTOTYPE_SCHEMA_SQL)
            await conn.execute(
                "INSERT OR REPLACE INTO schema_version (id, version) VALUES (1, ?)",
                (11,),
            )
            current_version = 11
        if current_version < 12:
            await conn.executescript(
                """
                DROP TABLE IF EXISTS prototype_generation_run_items;
                DROP TABLE IF EXISTS prototype_generation_runs;
                DROP TABLE IF EXISTS prototype_plan_items;
                DROP TABLE IF EXISTS prototype_plans;
                DROP TABLE IF EXISTS prototype_versions;
                DROP TABLE IF EXISTS prototypes;
                """
            )
            await conn.execute(
                "INSERT OR REPLACE INTO schema_version (id, version) VALUES (1, ?)",
                (12,),
            )
            current_version = 12
        if current_version < 13:
            await conn.execute(
                "INSERT OR REPLACE INTO schema_version (id, version) VALUES (1, ?)",
                (13,),
            )
            current_version = 13
        if current_version < 14:
            for name, declaration in STRUCTURED_PROTOTYPE_GENERATION_SNAPSHOT_COLUMNS:
                with suppress(aiosqlite.OperationalError):
                    await conn.execute(
                        "ALTER TABLE prototype_document_generation_jobs "
                        f"ADD COLUMN {name} {declaration}"
                    )
            await conn.execute(
                "INSERT OR REPLACE INTO schema_version (id, version) VALUES (1, ?)",
                (14,),
            )
            current_version = 14
        if current_version < 15:
            await conn.executescript(STRUCTURED_PROTOTYPE_SCHEMA_SQL)
            for name, declaration in STRUCTURED_PROTOTYPE_RUNTIME_SESSION_COLUMNS:
                with suppress(aiosqlite.OperationalError):
                    await conn.execute(
                        f"ALTER TABLE prototype_runtime_sessions ADD COLUMN {name} {declaration}"
                    )
            await conn.execute(STRUCTURED_PROTOTYPE_RUNTIME_SESSION_REPLACEMENT_INDEX_SQL)
            await conn.execute(
                "INSERT OR REPLACE INTO schema_version (id, version) VALUES (1, ?)",
                (15,),
            )
            current_version = 15
        if current_version < 16:
            # Keep the repair isolated from the broader boot schema work. A
            # typed failure or cancellation must never leave a half-repaired
            # ledger that a later executescript() could commit implicitly.
            await conn.commit()
            await conn.execute("BEGIN IMMEDIATE")
            try:
                await self._apply_project_conductor_v16_migration(conn)
                await conn.commit()
            except BaseException:
                # Transaction boundary: startup cancellation is also rollback-worthy.
                await conn.rollback()
                raise
            current_version = 16
        if current_version < 17:
            # Project Conductor state is an optimistic-concurrency aggregate.
            # Add its compare-and-swap revision in one startup transaction.
            await conn.commit()
            await conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = await conn.execute("PRAGMA table_info(project_conductor_states)")
                columns = {str(row[1]) for row in await cursor.fetchall()}
                if "revision" not in columns:
                    await conn.execute(
                        "ALTER TABLE project_conductor_states "
                        "ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"
                    )
                await conn.execute(
                    "UPDATE project_conductor_states SET revision = 1 WHERE revision = 0"
                )
                await conn.execute(
                    "INSERT OR REPLACE INTO schema_version (id, version) VALUES (1, ?)",
                    (17,),
                )
                await conn.commit()
            except BaseException:
                # Transaction boundary: startup cancellation is also rollback-worthy.
                await conn.rollback()
                raise
            current_version = 17
        # Also repairs databases opened by a prerelease v17 build that used
        # zero as the persisted default; zero is reserved for unsaved objects.
        await conn.execute("UPDATE project_conductor_states SET revision = 1 WHERE revision = 0")
        # Create indexes for frequently queried columns
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_codex_tasks_session_id ON codex_tasks(session_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_codex_tasks_project_id ON codex_tasks(project_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_codex_sessions_project_id ON codex_sessions(project_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_codex_issues_project_id ON codex_issues(project_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_codex_tasks_issue_id ON codex_tasks(issue_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_codex_tasks_parent_task_id ON codex_tasks(parent_task_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_codex_tasks_status ON codex_tasks(status)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_codex_tasks_task_kind ON codex_tasks(task_kind)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_codex_issues_session_id ON codex_issues(session_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_codex_task_messages_task_id ON codex_task_messages(task_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_codex_task_messages_execution_process_id ON codex_task_messages(execution_process_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_log_events_session_id ON log_events(session_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_log_events_task_id ON log_events(task_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_log_events_execution_process_id ON log_events(execution_process_id)"
        )
        # Trace lookups: fetch one trace's spans/steps across both tables. Guarded
        # by suppress because on an existing DB the ALTER above adds the column in
        # the same _init_db pass, but an index build racing a failed ALTER would
        # otherwise crash init.
        with suppress(aiosqlite.OperationalError):
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_log_events_trace_id ON log_events(trace_id)"
            )
        with suppress(aiosqlite.OperationalError):
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_log_trace_id ON audit_log(trace_id)"
            )
        # Must run BEFORE idx_conductor_turns_inbox below; the index
        # references consumed_at, and on an existing DB without the column
        # the CREATE INDEX otherwise raises and crashes _init_db().
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE conductor_turns ADD COLUMN consumed_at TEXT")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conductor_turns_task_turn ON conductor_turns(conductor_task_id, turn_index, sub_index)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conductor_turns_issue_created ON conductor_turns(issue_id, created_at)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conductor_turns_inbox ON conductor_turns(conductor_task_id, kind, consumed_at, created_at)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conductor_state_log_issue_transition ON conductor_state_log(issue_id, transition_at)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_execution_processes_session_id ON execution_processes(session_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_execution_processes_task_id ON execution_processes(task_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_help_requests_parent_task_id ON help_requests(parent_task_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_help_requests_child_task_id ON help_requests(child_task_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_help_requests_workspace_id ON help_requests(workspace_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_artifact_paths_issue_id ON artifact_paths(issue_id)"
        )
        # Workflow DAG indexes
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_role_key ON agents(role_key)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agents_workspace_id ON agents(workspace_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_workflow_graphs_issue_id ON workflow_graphs(issue_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_workflow_nodes_graph_id ON workflow_nodes(graph_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_workflow_nodes_status ON workflow_nodes(status)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_workflow_nodes_task_id ON workflow_nodes(task_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_workflow_edges_graph_id ON workflow_edges(graph_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_graph_replan_pending_graph_id ON graph_replan_pending(graph_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_graph_replan_pending_status ON graph_replan_pending(status)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_codex_tasks_workflow_node_id ON codex_tasks(workflow_node_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_messages_issue_id ON agent_messages(issue_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_messages_graph_id ON agent_messages(graph_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conductor_decisions_issue_id ON conductor_decisions(issue_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conductor_decisions_task_id ON conductor_decisions(task_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conductor_tasks_project_id ON conductor_tasks(project_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conductor_tasks_status ON conductor_tasks(status)"
        )
        for stmt in (
            "ALTER TABLE conductor_tasks ADD COLUMN lease_owner TEXT",
            "ALTER TABLE conductor_tasks ADD COLUMN heartbeat_at TEXT",
            "ALTER TABLE conductor_tasks ADD COLUMN lease_expires_at TEXT",
        ):
            with suppress(aiosqlite.OperationalError):
                await conn.execute(stmt)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conductor_tasks_lease ON conductor_tasks(status, lease_expires_at)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_project_memory_embeddings_project_id ON project_memory_embeddings(project_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_self_improvement_project_created ON self_improvement_proposals(project_id, created_at)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_self_improvement_issue ON self_improvement_proposals(issue_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_self_improvement_status ON self_improvement_proposals(status)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_self_improvement_events_project_created ON self_improvement_application_events(project_id, created_at)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_self_improvement_events_proposal_created ON self_improvement_application_events(proposal_id, created_at)"
        )
        # --- Project env vars ---
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS project_env_vars (
                project_id TEXT NOT NULL,
                name TEXT NOT NULL,
                value TEXT NOT NULL,
                secret INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT '',
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(project_id, name),
                FOREIGN KEY (project_id) REFERENCES projects(id)
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_project_env_vars_project_id ON project_env_vars(project_id)"
        )
        # Audit log filter/pagination indexes (PR3 read API will lean on these).
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_log_issue_created ON audit_log(issue_id, created_at)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_log_category_created ON audit_log(category, created_at)"
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_task_id ON audit_log(task_id)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_call_traces_audit_log_id ON agent_call_traces(audit_log_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_call_traces_trace_id ON agent_call_traces(trace_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_call_traces_task_id ON agent_call_traces(task_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_call_traces_execution_process_id ON agent_call_traces(execution_process_id)"
        )
        # Phase 4: add instance_index to workflow_nodes for existing DBs
        with suppress(aiosqlite.OperationalError):
            await conn.execute(
                "ALTER TABLE workflow_nodes ADD COLUMN instance_index INTEGER NOT NULL DEFAULT 0"
            )
        # Parallel swarm: add batch_key to group nodes from one dispatch_batch call
        with suppress(aiosqlite.OperationalError):
            await conn.execute("ALTER TABLE workflow_nodes ADD COLUMN batch_key TEXT")
        await conn.commit()
        self._initialized_connection = conn

    async def _ensure_db(self) -> None:
        conn = await self._get_conn()
        if self._initialized_connection is conn:
            return
        async with self._init_lock:
            conn = await self._get_conn()
            if self._initialized_connection is conn:
                return
            await self._init_db()

    def _format_datetime(self, dt: datetime | None) -> str | None:
        return dt.isoformat() if dt else None

    def _parse_datetime(self, s: str | None) -> datetime | None:
        return datetime.fromisoformat(s) if s else None

    async def save_session(self, session: Session) -> None:
        conn = await self._get_conn()
        await conn.execute(
            "INSERT OR REPLACE INTO sessions (id, title, state) VALUES (?, ?, ?)",
            (session.id, session.title, session.state.value),
        )
        for task in session.tasks:
            await conn.execute(
                "INSERT OR REPLACE INTO tasks (id, session_id, title, assignee, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    task.id,
                    session.id,
                    task.title,
                    task.assignee,
                    task.status,
                    self._format_datetime(task.created_at),
                ),
            )
        for run in session.runs:
            await conn.execute(
                "INSERT OR REPLACE INTO runs (id, task_id, agent_id, role, status, summary, payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.id,
                    run.task_id,
                    run.agent_id,
                    run.role,
                    run.status,
                    run.summary,
                    json.dumps(run.payload) if run.payload else None,
                    self._format_datetime(run.created_at),
                ),
            )
        for artifact in session.artifacts:
            content = artifact.content
            if hasattr(content, "model_dump"):
                content = json.dumps(content.model_dump())
            elif not isinstance(content, str):
                content = json.dumps(content)
            await conn.execute(
                "INSERT OR REPLACE INTO artifacts (id, task_id, kind, content, steps, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    artifact.id,
                    artifact.task_id,
                    artifact.kind,
                    content,
                    json.dumps(artifact.steps) if artifact.steps else None,
                    self._format_datetime(artifact.created_at),
                ),
            )
        for message in session.messages:
            await conn.execute(
                "INSERT OR REPLACE INTO messages (id, task_id, agent_id, role, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    message.id,
                    message.task_id,
                    message.agent_id,
                    message.role,
                    message.content,
                    self._format_datetime(message.created_at),
                ),
            )
        for approval in session.approvals:
            await conn.execute(
                "INSERT OR REPLACE INTO approvals (id, session_id, task_id, action, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    approval.id,
                    approval.session_id,
                    approval.task_id,
                    approval.action,
                    approval.status,
                    self._format_datetime(approval.created_at),
                ),
            )
        for event in session.approval_events:
            await conn.execute(
                "INSERT OR REPLACE INTO approval_events (id, session_id, task_id, approval_id, event_type, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    event.id,
                    event.session_id,
                    event.task_id,
                    event.approval_id,
                    event.event_type,
                    self._format_datetime(event.created_at),
                ),
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

        async def load_tasks() -> None:
            async with conn.execute(
                "SELECT * FROM tasks WHERE session_id = ?", (session_id,)
            ) as cur:
                async for t_row in cur:
                    session.tasks.append(
                        Task(
                            id=t_row["id"],
                            session_id=t_row["session_id"],
                            title=t_row["title"],
                            assignee=t_row["assignee"],
                            status=t_row["status"],
                            created_at=self._parse_datetime(t_row["created_at"]),
                        )
                    )

        async def load_runs() -> None:
            async with conn.execute(
                "SELECT * FROM runs WHERE task_id IN (SELECT id FROM tasks WHERE session_id = ?)",
                (session_id,),
            ) as cur:
                async for r_row in cur:
                    session.runs.append(
                        AgentRun(
                            id=r_row["id"],
                            task_id=r_row["task_id"],
                            agent_id=r_row["agent_id"],
                            role=r_row["role"],
                            status=r_row["status"],
                            summary=r_row["summary"],
                            payload=_json_object(r_row["payload"]),
                            created_at=self._parse_datetime(r_row["created_at"]),
                        )
                    )

        async def load_artifacts() -> None:
            async with conn.execute(
                "SELECT * FROM artifacts WHERE task_id IN (SELECT id FROM tasks WHERE session_id = ?)",
                (session_id,),
            ) as cur:
                async for a_row in cur:
                    content = a_row["content"]
                    try:
                        parsed_plan = _plan_details(content)
                        if parsed_plan is not None:
                            content = parsed_plan
                    except (json.JSONDecodeError, TypeError):
                        pass
                    session.artifacts.append(
                        Artifact(
                            id=a_row["id"],
                            task_id=a_row["task_id"],
                            kind=a_row["kind"],
                            content=content,
                            steps=_json_string_list(a_row["steps"]),
                            created_at=self._parse_datetime(a_row["created_at"]),
                        )
                    )

        async def load_messages() -> None:
            async with conn.execute(
                "SELECT * FROM messages WHERE task_id IN (SELECT id FROM tasks WHERE session_id = ?)",
                (session_id,),
            ) as cur:
                async for m_row in cur:
                    session.messages.append(
                        Message(
                            id=m_row["id"],
                            task_id=m_row["task_id"],
                            agent_id=m_row["agent_id"],
                            role=m_row["role"],
                            content=m_row["content"],
                            created_at=self._parse_datetime(m_row["created_at"]),
                        )
                    )

        async def load_approvals() -> None:
            async with conn.execute(
                "SELECT * FROM approvals WHERE session_id = ?", (session_id,)
            ) as cur:
                async for ap_row in cur:
                    session.approvals.append(
                        Approval(
                            id=ap_row["id"],
                            session_id=ap_row["session_id"],
                            task_id=ap_row["task_id"],
                            action=ap_row["action"],
                            status=ap_row["status"],
                            created_at=self._parse_datetime(ap_row["created_at"]),
                        )
                    )

        async def load_approval_events() -> None:
            async with conn.execute(
                "SELECT * FROM approval_events WHERE session_id = ?", (session_id,)
            ) as cur:
                async for ev_row in cur:
                    session.approval_events.append(
                        ApprovalEvent(
                            id=ev_row["id"],
                            session_id=ev_row["session_id"],
                            task_id=ev_row["task_id"],
                            approval_id=ev_row["approval_id"],
                            event_type=ev_row["event_type"],
                            created_at=self._parse_datetime(ev_row["created_at"]),
                        )
                    )

        await load_tasks()
        await load_runs()
        await load_artifacts()
        await load_messages()
        await load_approvals()
        await load_approval_events()
        return session

    async def list_sessions(self) -> list[dict[str, object]]:
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT id, title, state FROM sessions") as cur:
            rows = await cur.fetchall()
        return [{"id": r["id"], "title": r["title"], "state": r["state"]} for r in rows]

    async def save_codex_session(self, session: CodexSession) -> None:
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            "INSERT OR REPLACE INTO codex_sessions (id, title, cwd, project_id, status, created_at, last_active_at, log_path, thread_id, claude_thread_id, settings_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session.id,
                session.title,
                session.cwd,
                session.project_id,
                session.status,
                self._format_datetime(session.created_at),
                self._format_datetime(session.last_active_at),
                session.log_path,
                session.thread_id,
                session.claude_thread_id,
                json.dumps(session.settings, ensure_ascii=False)
                if getattr(session, "settings", None) is not None
                else None,
            ),
        )
        await conn.execute("DELETE FROM codex_messages WHERE session_id = ?", (session.id,))
        for msg in session.messages:
            await conn.execute(
                "INSERT INTO codex_messages (id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    msg.id,
                    msg.session_id,
                    msg.role,
                    msg.content,
                    self._format_datetime(msg.created_at),
                ),
            )
        await conn.commit()

    async def save_codex_workspace(self, workspace: CodexSession) -> None:
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
            project_id=row["project_id"] if _row_has_key(row, "project_id") else None,
            status=row["status"],
            created_at=self._parse_datetime(row["created_at"]),
            last_active_at=self._parse_datetime(row["last_active_at"]),
            log_path=row["log_path"],
            thread_id=row["thread_id"] if _row_has_key(row, "thread_id") else None,
            claude_thread_id=row["claude_thread_id"]
            if _row_has_key(row, "claude_thread_id")
            else None,
            settings=_codex_settings(
                row["settings_json"] if _row_has_key(row, "settings_json") else None
            ),
            messages=messages,
        )

    async def load_codex_workspace(self, workspace_id: str) -> CodexSession | None:
        return await self.load_codex_session(workspace_id)

    async def list_codex_sessions(self, project_id: str | None = None) -> list[dict[str, object]]:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        base = "SELECT id, title, project_id, status, created_at, last_active_at, settings_json FROM codex_sessions"
        if project_id:
            async with conn.execute(
                f"{base} WHERE project_id = ? ORDER BY last_active_at DESC", (project_id,)
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with conn.execute(f"{base} ORDER BY last_active_at DESC") as cur:
                rows = await cur.fetchall()
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "project_id": r["project_id"],
                "status": r["status"],
                "created_at": r["created_at"],
                "last_active_at": r["last_active_at"],
                "settings": _codex_settings(
                    r["settings_json"] if _row_has_key(r, "settings_json") else None
                ),
            }
            for r in rows
        ]

    async def list_codex_workspaces(self, project_id: str | None = None) -> list[dict[str, object]]:
        return await self.list_codex_sessions(project_id=project_id)

    async def delete_codex_session(self, session_id: str) -> None:
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

    async def delete_codex_issue(self, issue_id: str) -> None:
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute("DELETE FROM codex_issues WHERE id = ?", (issue_id,))
        await conn.commit()

    async def delete_codex_workspace(self, workspace_id: str) -> None:
        await self.delete_codex_session(workspace_id)

    async def save_codex_issue(self, issue: CodexIssue) -> None:
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            """INSERT OR REPLACE INTO codex_issues (
                id, session_id, project_id, title, description,
                acceptance_criteria, acceptance_criteria_confirmed,
                current_phase, status, review_comment,
                is_pinned, milestone,
                git_branch, git_base_branch, git_worktree_path, git_merge_status, git_last_commit_sha,
                github_pr_url, github_pr_state,
                executor, provider, model,
                budget_usd,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                issue.id,
                issue.session_id,
                issue.project_id,
                issue.title,
                issue.description,
                json.dumps(issue.acceptance_criteria, ensure_ascii=False),
                1 if issue.acceptance_criteria_confirmed else 0,
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
                issue.github_pr_url,
                issue.github_pr_state,
                issue.executor,
                issue.provider,
                issue.model,
                issue.budget_usd,
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
        except Exception:
            logger.debug("issue fts sync failed: issue_id=%s", issue.id, exc_info=True)
        await conn.commit()

    async def load_codex_issue(self, issue_id: str) -> CodexIssue | None:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM codex_issues WHERE id = ?", (issue_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        acceptance_criteria = _issue_acceptance_criteria(
            row["acceptance_criteria"] if _row_has_key(row, "acceptance_criteria") else None
        )
        return CodexIssue(
            id=row["id"],
            session_id=row["session_id"],
            project_id=row["project_id"] if _row_has_key(row, "project_id") else None,
            title=row["title"],
            description=row["description"],
            acceptance_criteria=acceptance_criteria,
            acceptance_criteria_confirmed=(
                bool(row["acceptance_criteria_confirmed"])
                if _row_has_key(row, "acceptance_criteria_confirmed") and acceptance_criteria
                else False
            ),
            current_phase=row["current_phase"],
            status=row["status"],
            review_comment=row["review_comment"] if _row_has_key(row, "review_comment") else None,
            is_pinned=bool(row["is_pinned"]) if _row_has_key(row, "is_pinned") else False,
            milestone=row["milestone"]
            if _row_has_key(row, "milestone") and row["milestone"]
            else None,
            git_branch=row["git_branch"]
            if _row_has_key(row, "git_branch") and row["git_branch"]
            else None,
            git_base_branch=row["git_base_branch"]
            if _row_has_key(row, "git_base_branch") and row["git_base_branch"]
            else None,
            git_worktree_path=row["git_worktree_path"]
            if _row_has_key(row, "git_worktree_path") and row["git_worktree_path"]
            else None,
            git_merge_status=row["git_merge_status"]
            if _row_has_key(row, "git_merge_status") and row["git_merge_status"]
            else "open",
            git_last_commit_sha=row["git_last_commit_sha"]
            if _row_has_key(row, "git_last_commit_sha") and row["git_last_commit_sha"]
            else None,
            github_pr_url=row["github_pr_url"]
            if _row_has_key(row, "github_pr_url") and row["github_pr_url"]
            else None,
            github_pr_state=row["github_pr_state"]
            if _row_has_key(row, "github_pr_state") and row["github_pr_state"]
            else None,
            executor=row["executor"] if _row_has_key(row, "executor") and row["executor"] else None,
            provider=row["provider"] if _row_has_key(row, "provider") and row["provider"] else None,
            model=row["model"] if _row_has_key(row, "model") and row["model"] else None,
            budget_usd=row["budget_usd"]
            if _row_has_key(row, "budget_usd") and row["budget_usd"] is not None
            else None,
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    async def list_codex_issues(
        self, session_id: str | None = None, project_id: str | None = None
    ) -> list[dict[str, object]]:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        select_sql = "SELECT id, session_id, project_id, title, description, acceptance_criteria, acceptance_criteria_confirmed, current_phase, status, review_comment, is_pinned, milestone, git_branch, git_base_branch, git_worktree_path, git_merge_status, git_last_commit_sha, github_pr_url, github_pr_state, budget_usd, created_at, updated_at FROM codex_issues"
        clauses: list[str] = []
        params: list[object] = []
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
        items: list[dict[str, object]] = []
        for row in rows:
            item = dict(row)
            acceptance_criteria = _issue_acceptance_criteria(item["acceptance_criteria"])
            item["acceptance_criteria"] = acceptance_criteria
            item["acceptance_criteria_confirmed"] = bool(
                item["acceptance_criteria_confirmed"]
            ) and bool(acceptance_criteria)
            items.append(item)
        return items

    async def save_codex_task(self, task: CodexTask) -> None:
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            """INSERT OR REPLACE INTO codex_tasks (
                id, session_id, project_id, issue_id, phase, title, prompt, role, executor, provider, model,
                status, result, result_json, parent_task_id, task_kind, blocked_by_help_id, workspace_path,
                git_branch, git_base_branch, git_worktree_path, git_merge_status, git_last_commit_sha,
                resume_session_id, resume_message_id, last_execution_process_id,
                trace_id, span_id, parent_span_id,
                sequence_index, sequence_group, review_comment, workflow_node_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task.id,
                task.session_id,
                task.project_id,
                task.issue_id,
                task.phase,
                task.title,
                task.prompt,
                task.role,
                task.executor,
                task.provider,
                task.model,
                task.status,
                task.result,
                task.result_json,
                task.parent_task_id,
                task.task_kind,
                task.blocked_by_help_id,
                task.workspace_path,
                task.git_branch,
                task.git_base_branch,
                task.git_worktree_path,
                task.git_merge_status,
                task.git_last_commit_sha,
                task.resume_session_id,
                task.resume_message_id,
                task.last_execution_process_id,
                task.trace_id,
                task.span_id,
                task.parent_span_id,
                task.sequence_index,
                task.sequence_group,
                task.review_comment,
                task.workflow_node_id,
                self._format_datetime(task.created_at),
                self._format_datetime(task.updated_at),
            ),
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
            project_id=row["project_id"]
            if _row_has_key(row, "project_id") and row["project_id"]
            else None,
            issue_id=row["issue_id"] if _row_has_key(row, "issue_id") and row["issue_id"] else None,
            phase=row["phase"] if _row_has_key(row, "phase") and row["phase"] else "requirements",
            title=row["title"],
            prompt=row["prompt"],
            role=row["role"] if _row_has_key(row, "role") and row["role"] else "general",
            executor=row["executor"] if row["executor"] else "codex",
            provider=row["provider"] if _row_has_key(row, "provider") and row["provider"] else None,
            model=row["model"] if _row_has_key(row, "model") and row["model"] else None,
            status=row["status"],
            result=row["result"],
            result_json=row["result_json"]
            if _row_has_key(row, "result_json") and row["result_json"]
            else None,
            parent_task_id=row["parent_task_id"] if row["parent_task_id"] else None,
            task_kind=row["task_kind"]
            if _row_has_key(row, "task_kind") and row["task_kind"]
            else "normal",
            blocked_by_help_id=row["blocked_by_help_id"]
            if _row_has_key(row, "blocked_by_help_id") and row["blocked_by_help_id"]
            else None,
            workspace_path=row["workspace_path"]
            if _row_has_key(row, "workspace_path") and row["workspace_path"]
            else None,
            git_branch=row["git_branch"]
            if _row_has_key(row, "git_branch") and row["git_branch"]
            else None,
            git_base_branch=row["git_base_branch"]
            if _row_has_key(row, "git_base_branch") and row["git_base_branch"]
            else None,
            git_worktree_path=row["git_worktree_path"]
            if _row_has_key(row, "git_worktree_path") and row["git_worktree_path"]
            else None,
            git_merge_status=row["git_merge_status"]
            if _row_has_key(row, "git_merge_status") and row["git_merge_status"]
            else "open",
            git_last_commit_sha=row["git_last_commit_sha"]
            if _row_has_key(row, "git_last_commit_sha") and row["git_last_commit_sha"]
            else None,
            resume_session_id=row["resume_session_id"]
            if _row_has_key(row, "resume_session_id") and row["resume_session_id"]
            else None,
            resume_message_id=row["resume_message_id"]
            if _row_has_key(row, "resume_message_id") and row["resume_message_id"]
            else None,
            last_execution_process_id=row["last_execution_process_id"]
            if _row_has_key(row, "last_execution_process_id") and row["last_execution_process_id"]
            else None,
            trace_id=row["trace_id"] if _row_has_key(row, "trace_id") and row["trace_id"] else None,
            span_id=row["span_id"] if _row_has_key(row, "span_id") and row["span_id"] else None,
            parent_span_id=row["parent_span_id"]
            if _row_has_key(row, "parent_span_id") and row["parent_span_id"]
            else None,
            sequence_index=row["sequence_index"] if _row_has_key(row, "sequence_index") else None,
            sequence_group=row["sequence_group"] if _row_has_key(row, "sequence_group") else None,
            review_comment=row["review_comment"] if _row_has_key(row, "review_comment") else None,
            workflow_node_id=row["workflow_node_id"]
            if _row_has_key(row, "workflow_node_id") and row["workflow_node_id"]
            else None,
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    async def list_codex_tasks(
        self,
        session_id: str | None = None,
        issue_id: str | None = None,
        project_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, object]]:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        select_sql = (
            "SELECT id, session_id, project_id, issue_id, phase, title, prompt, role, executor, provider, model, status, result, result_json, "
            "parent_task_id, task_kind, blocked_by_help_id, workspace_path, "
            "git_branch, git_base_branch, git_worktree_path, git_merge_status, git_last_commit_sha, "
            "resume_session_id, resume_message_id, last_execution_process_id, "
            "trace_id, span_id, parent_span_id, "
            "sequence_index, sequence_group, review_comment, workflow_node_id, created_at, updated_at FROM codex_tasks"
        )
        clauses: list[str] = []
        params: list[object] = []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if issue_id:
            clauses.append("issue_id = ?")
            params.append(issue_id)
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        async with conn.execute(
            f"{select_sql}{where} ORDER BY created_at ASC", tuple(params)
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # --- Project CRUD ---

    async def save_project(self, project: Project) -> None:
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            "INSERT OR REPLACE INTO projects (id, name, repo_path, default_branch, origin_url, setup_script, run_command, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project.id,
                project.name,
                project.repo_path,
                project.default_branch,
                project.origin_url,
                project.setup_script,
                project.run_command,
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
            run_command=row["run_command"],
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
            run_command=row["run_command"],
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
                run_command=r["run_command"],
                created_at=self._parse_datetime(r["created_at"]),
                updated_at=self._parse_datetime(r["updated_at"]),
            )
            for r in rows
        ]

    async def delete_project(self, project_id: str) -> None:
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        await conn.commit()

    async def replace_project_startup_services(
        self,
        project_id: str,
        task_id: str,
        services: list[ProjectStartupService],
        notes: list[str],
    ) -> None:
        await self._ensure_db()
        conn = await self._get_conn()
        now = datetime.now()
        await conn.execute("BEGIN")
        try:
            await conn.execute(
                "DELETE FROM project_startup_services WHERE project_id = ?",
                (project_id,),
            )
            for service in services:
                await conn.execute(
                    """
                    INSERT INTO project_startup_services (
                        project_id, service_id, name, working_directory,
                        setup_command, run_command, access_url, readiness_probe_json,
                        depends_on_json, evidence_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        service.service_id,
                        service.name,
                        service.working_directory,
                        service.setup_command,
                        service.run_command,
                        service.access_url,
                        (
                            json.dumps(
                                service.readiness_probe.model_dump(mode="json"),
                                ensure_ascii=False,
                            )
                            if service.readiness_probe is not None
                            else None
                        ),
                        json.dumps(service.depends_on, ensure_ascii=False),
                        json.dumps(
                            [item.model_dump(mode="json") for item in service.evidence],
                            ensure_ascii=False,
                        ),
                        self._format_datetime(service.created_at or now),
                        self._format_datetime(now),
                    ),
                )
            await conn.execute(
                """
                INSERT INTO project_startup_configs (
                    project_id, task_id, notes_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    task_id = excluded.task_id,
                    notes_json = excluded.notes_json,
                    updated_at = excluded.updated_at
                """,
                (
                    project_id,
                    task_id,
                    json.dumps(notes, ensure_ascii=False),
                    self._format_datetime(now),
                    self._format_datetime(now),
                ),
            )
        except Exception:
            await conn.rollback()
            raise
        await conn.commit()

    async def list_project_startup_services(self, project_id: str) -> list[ProjectStartupService]:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """
            SELECT project_id, service_id, name, working_directory,
                   setup_command, run_command, access_url, readiness_probe_json,
                   depends_on_json, evidence_json, created_at, updated_at
            FROM project_startup_services
            WHERE project_id = ?
            ORDER BY service_id
            """,
            (project_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [
            ProjectStartupService(
                project_id=row["project_id"],
                service_id=row["service_id"],
                name=row["name"],
                working_directory=row["working_directory"],
                setup_command=row["setup_command"],
                run_command=row["run_command"],
                access_url=row["access_url"],
                readiness_probe=_project_readiness_probe(row["readiness_probe_json"]),
                depends_on=json.loads(row["depends_on_json"]),
                evidence=_project_startup_evidence(row["evidence_json"]),
                created_at=self._parse_datetime(row["created_at"]),
                updated_at=self._parse_datetime(row["updated_at"]),
            )
            for row in rows
        ]

    async def load_project_startup_config_meta(self, project_id: str) -> dict[str, object] | None:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """
            SELECT project_id, task_id, notes_json, created_at, updated_at
            FROM project_startup_configs WHERE project_id = ?
            """,
            (project_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return {
            "project_id": row["project_id"],
            "task_id": row["task_id"],
            "notes": json.loads(row["notes_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # --- Project env vars CRUD ---

    async def save_project_env_var(
        self,
        project_id: str,
        name: str,
        value: str,
        *,
        secret: bool = False,
        source: str = "",
    ) -> None:
        """Insert or replace a single environment variable for a project.

        Callers MUST encrypt `value` before calling this method when ``secret=True``.
        This method does NOT perform encryption — it stores the value as given.
        """
        await self._ensure_db()
        conn = await self._get_conn()
        now = self._format_datetime(datetime.now())
        await conn.execute(
            "INSERT OR REPLACE INTO project_env_vars "
            "(project_id, name, value, secret, source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM project_env_vars WHERE project_id=? AND name=?), ?), ?)",
            (
                project_id,
                name,
                value,
                1 if secret else 0,
                source,
                project_id,
                name,
                now,
                now,
            ),
        )
        await conn.commit()

    async def load_project_env_vars(self, project_id: str) -> list[ProjectEnvVar]:
        """Return all stored env vars for a project."""
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM project_env_vars WHERE project_id = ? ORDER BY name",
            (project_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [
            ProjectEnvVar(
                project_id=r["project_id"],
                name=r["name"],
                value=r["value"],
                secret=bool(r["secret"]),
                source=r["source"] or "",
                created_at=self._parse_datetime(r["created_at"]),
                updated_at=self._parse_datetime(r["updated_at"]),
            )
            for r in rows
        ]

    async def load_project_env_var(self, project_id: str, name: str) -> ProjectEnvVar | None:
        """Return a single stored env var, or None."""
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM project_env_vars WHERE project_id = ? AND name = ?",
            (project_id, name),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return ProjectEnvVar(
            project_id=row["project_id"],
            name=row["name"],
            value=row["value"],
            secret=bool(row["secret"]),
            source=row["source"] or "",
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    async def delete_project_env_var(self, project_id: str, name: str) -> None:
        """Remove a single env var from the store."""
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            "DELETE FROM project_env_vars WHERE project_id = ? AND name = ?",
            (project_id, name),
        )
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
    ) -> list[dict[str, object]]:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        if since:
            query = (
                "SELECT id, project_id, issue_id, event, sha, base_branch, created_at "
                "FROM project_audit WHERE project_id = ? AND created_at >= ? "
                "ORDER BY id DESC LIMIT ?"
            )
            params: tuple[object, ...] = (project_id, since, limit)
        else:
            query = (
                "SELECT id, project_id, issue_id, event, sha, base_branch, created_at "
                "FROM project_audit WHERE project_id = ? ORDER BY id DESC LIMIT ?"
            )
            params = (project_id, limit)
        async with conn.execute(query, params) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def save_help_request(self, help_request: HelpRequest) -> None:
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
                json.dumps(help_request.continuation_payload)
                if help_request.continuation_payload is not None
                else None,
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
        async with conn.execute(
            "SELECT * FROM help_requests WHERE id = ?", (help_request_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
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
            continuation_payload=_json_object(row["continuation_payload"]),
            created_at=self._parse_datetime(row["created_at"]),
            started_at=self._parse_datetime(row["started_at"]),
            completed_at=self._parse_datetime(row["completed_at"]),
            timeout_at=self._parse_datetime(row["timeout_at"]),
            consumed_at=self._parse_datetime(row["consumed_at"]),
        )

    async def list_help_requests(
        self, *, parent_task_id: str | None = None, child_task_id: str | None = None
    ) -> list[HelpRequest]:
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
                continuation_payload=_json_object(row["continuation_payload"]),
                created_at=self._parse_datetime(row["created_at"]),
                started_at=self._parse_datetime(row["started_at"]),
                completed_at=self._parse_datetime(row["completed_at"]),
                timeout_at=self._parse_datetime(row["timeout_at"]),
                consumed_at=self._parse_datetime(row["consumed_at"]),
            )
            for row in rows
        ]

    async def delete_codex_task(self, task_id: str) -> None:
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            "DELETE FROM help_requests WHERE parent_task_id = ? OR child_task_id = ?",
            (task_id, task_id),
        )
        await conn.execute("DELETE FROM codex_task_messages WHERE task_id = ?", (task_id,))
        await conn.execute("DELETE FROM execution_processes WHERE task_id = ?", (task_id,))
        await conn.execute("DELETE FROM log_events WHERE task_id = ?", (task_id,))
        await conn.execute("DELETE FROM agent_call_traces WHERE task_id = ?", (task_id,))
        await conn.execute("DELETE FROM codex_tasks WHERE id = ?", (task_id,))
        await conn.commit()

    async def save_codex_task_message(self, message: CodexTaskMessage) -> None:
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
                execution_process_id=r["execution_process_id"]
                if _row_has_key(r, "execution_process_id")
                else None,
                role=r["role"],
                content=r["content"],
                created_at=self._parse_datetime(r["created_at"]),
            )
            for r in rows
        ]

    async def reset(self) -> None:
        conn = await self._get_conn()
        async with conn.execute("SELECT name FROM sqlite_master WHERE type='table'") as cur:
            async for table in cur:
                name = table[0]
                if name == "sqlite_sequence":
                    continue
                # Skip FTS5 virtual table shadow tables to prevent corruption
                if name.startswith(("issues_fts_", "artifacts_fts_")):
                    continue
                quoted_name = _quote_sqlite_identifier(name)
                # Identifier is validated by _quote_sqlite_identifier.
                await conn.execute(f"DELETE FROM {quoted_name}")  # nosec B608
        await conn.commit()

    async def append_log_event(self, event: LogEvent) -> None:
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            "INSERT INTO log_events (id, session_id, stream, content, task_id, execution_process_id, trace_id, span_id, parent_span_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.id,
                event.session_id,
                event.stream,
                event.content,
                event.task_id,
                event.execution_process_id,
                event.trace_id,
                event.span_id,
                event.parent_span_id,
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
        if execution_process_id and task_id:
            async with conn.execute(
                _log_events_query(has_task_id=True, has_execution_process_id=True, reverse=reverse),
                (session_id, task_id, execution_process_id, limit),
            ) as cur:
                rows = await cur.fetchall()
        elif execution_process_id:
            async with conn.execute(
                _log_events_query(
                    has_task_id=False, has_execution_process_id=True, reverse=reverse
                ),
                (session_id, execution_process_id, limit),
            ) as cur:
                rows = await cur.fetchall()
        elif task_id:
            async with conn.execute(
                _log_events_query(
                    has_task_id=True, has_execution_process_id=False, reverse=reverse
                ),
                (session_id, task_id, limit),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with conn.execute(
                _log_events_query(
                    has_task_id=False, has_execution_process_id=False, reverse=reverse
                ),
                (session_id, limit),
            ) as cur:
                rows = await cur.fetchall()
        return [
            LogEvent(
                id=r["id"],
                session_id=r["session_id"],
                stream=r["stream"],
                content=r["content"],
                task_id=r["task_id"] if _row_has_key(r, "task_id") else None,
                execution_process_id=r["execution_process_id"]
                if _row_has_key(r, "execution_process_id")
                else None,
                trace_id=r["trace_id"] if _row_has_key(r, "trace_id") else None,
                span_id=r["span_id"] if _row_has_key(r, "span_id") else None,
                parent_span_id=r["parent_span_id"] if _row_has_key(r, "parent_span_id") else None,
                created_at=self._parse_datetime(r["created_at"]),
            )
            for r in rows
        ]

    async def save_execution_process(self, process: ExecutionProcess) -> None:
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            "INSERT OR REPLACE INTO execution_processes (id, task_id, session_id, status, exit_code, executor, provider, model, kind, triggering_message_id, input_tokens, output_tokens, cache_read_tokens, total_cost_usd, started_at, completed_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                process.id,
                process.task_id,
                process.session_id,
                process.status,
                process.exit_code,
                process.executor,
                process.provider,
                process.model,
                process.kind,
                process.triggering_message_id,
                process.input_tokens,
                process.output_tokens,
                process.cache_read_tokens,
                process.total_cost_usd,
                self._format_datetime(process.started_at),
                self._format_datetime(process.completed_at),
                self._format_datetime(process.created_at),
                self._format_datetime(process.updated_at),
            ),
        )
        await conn.commit()

    async def load_execution_process(self, process_id: str) -> ExecutionProcess | None:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM execution_processes WHERE id = ?", (process_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return ExecutionProcess(
            id=row["id"],
            task_id=row["task_id"],
            session_id=row["session_id"],
            status=row["status"],
            exit_code=row["exit_code"],
            executor=row["executor"] if _row_has_key(row, "executor") and row["executor"] else None,
            provider=row["provider"] if _row_has_key(row, "provider") and row["provider"] else None,
            model=row["model"] if _row_has_key(row, "model") and row["model"] else None,
            input_tokens=row["input_tokens"] if _row_has_key(row, "input_tokens") else None,
            output_tokens=row["output_tokens"] if _row_has_key(row, "output_tokens") else None,
            cache_read_tokens=row["cache_read_tokens"]
            if _row_has_key(row, "cache_read_tokens")
            else None,
            total_cost_usd=row["total_cost_usd"] if _row_has_key(row, "total_cost_usd") else None,
            kind=row["kind"] if _row_has_key(row, "kind") and row["kind"] else "initial",
            triggering_message_id=row["triggering_message_id"]
            if _row_has_key(row, "triggering_message_id")
            else None,
            started_at=self._parse_datetime(row["started_at"]),
            completed_at=self._parse_datetime(row["completed_at"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    async def list_execution_processes(
        self, session_id: str | None = None, task_id: str | None = None
    ) -> list[ExecutionProcess]:
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
            async with conn.execute(
                "SELECT * FROM execution_processes ORDER BY created_at DESC"
            ) as cur:
                rows = await cur.fetchall()
        return [
            ExecutionProcess(
                id=r["id"],
                task_id=r["task_id"],
                session_id=r["session_id"],
                status=r["status"],
                exit_code=r["exit_code"],
                executor=r["executor"] if _row_has_key(r, "executor") and r["executor"] else None,
                provider=r["provider"] if _row_has_key(r, "provider") and r["provider"] else None,
                model=r["model"] if _row_has_key(r, "model") and r["model"] else None,
                input_tokens=r["input_tokens"] if _row_has_key(r, "input_tokens") else None,
                output_tokens=r["output_tokens"] if _row_has_key(r, "output_tokens") else None,
                cache_read_tokens=r["cache_read_tokens"]
                if _row_has_key(r, "cache_read_tokens")
                else None,
                total_cost_usd=r["total_cost_usd"] if _row_has_key(r, "total_cost_usd") else None,
                kind=r["kind"] if _row_has_key(r, "kind") and r["kind"] else "initial",
                triggering_message_id=r["triggering_message_id"]
                if _row_has_key(r, "triggering_message_id")
                else None,
                started_at=self._parse_datetime(r["started_at"]),
                completed_at=self._parse_datetime(r["completed_at"]),
                created_at=self._parse_datetime(r["created_at"]),
                updated_at=self._parse_datetime(r["updated_at"]),
            )
            for r in rows
        ]

    async def list_execution_process_runtime_rows(
        self,
        session_id: str,
        *,
        log_limit: int = 10000,
    ) -> list[tuple[ExecutionProcess, CodexTask | None, list[CodexTaskMessage], list[LogEvent]]]:
        processes = await self.list_execution_processes(session_id=session_id)
        rows: list[
            tuple[ExecutionProcess, CodexTask | None, list[CodexTaskMessage], list[LogEvent]]
        ] = []
        for process in processes:
            task = await self.load_codex_task(process.task_id)
            messages = await self.list_codex_task_messages(
                process.task_id, execution_process_id=process.id
            )
            logs = await self.load_log_events(
                session_id,
                task_id=process.task_id,
                execution_process_id=process.id,
                limit=log_limit,
            )
            rows.append((process, task, messages, logs))
        return rows

    async def update_execution_process_status(
        self,
        process_id: str,
        status: str,
        exit_code: int | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        await self._ensure_db()
        conn = await self._get_conn()
        from datetime import datetime as dt

        now = dt.now()
        completed_at_value = (
            self._format_datetime(completed_at) if completed_at is not None else None
        )
        await conn.execute(
            "UPDATE execution_processes SET status = ?, exit_code = ?, completed_at = ?, updated_at = ? WHERE id = ?",
            (status, exit_code, completed_at_value, self._format_datetime(now), process_id),
        )
        await conn.commit()

    async def update_execution_process_usage(
        self,
        process_id: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_tokens: int | None = None,
        total_cost_usd: float | None = None,
    ) -> None:
        await self._ensure_db()
        conn = await self._get_conn()
        from datetime import datetime as dt

        now = dt.now()
        await conn.execute(
            "UPDATE execution_processes SET input_tokens = ?, output_tokens = ?, cache_read_tokens = ?, total_cost_usd = ?, updated_at = ? WHERE id = ?",
            (
                input_tokens,
                output_tokens,
                cache_read_tokens,
                total_cost_usd,
                self._format_datetime(now),
                process_id,
            ),
        )
        await conn.commit()

    # --- Runtime Catalog ---

    async def save_runtime_catalog(self, catalog: "RuntimeCatalog") -> None:
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
        async with conn.execute(
            "SELECT data FROM runtime_catalog_settings WHERE id = ?", ("runtime_catalog",)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        try:
            data = _json_object(row["data"])
            if data is None:
                return None
            return RuntimeCatalog.model_validate(data)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

    # --- Artifact Paths ---

    async def save_artifact(self, artifact: dict[str, object]) -> None:
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

    async def list_artifacts(self, issue_id: str) -> list[dict[str, object]]:
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

    def _row_to_agent(self, row: aiosqlite.Row) -> "Agent":
        from app.domain.models import Agent

        return Agent(
            id=row["id"],
            workspace_id=row["workspace_id"],
            name=row["name"],
            role_key=row["role_key"],
            description=row["description"],
            system_prompt_template=row["system_prompt_template"],
            input_schema=_json_object_list(row["input_schema"]),
            output_schema=_json_object(row["output_schema"]) or {},
            default_executor=row["default_executor"],
            default_provider=row["default_provider"],
            default_model=row["default_model"],
            artifact_subdir=row["artifact_subdir"],
            persist_kind=row["persist_kind"],
            agent_tier=row["agent_tier"]
            if _row_has_key(row, "agent_tier") and row["agent_tier"]
            else "managed",
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

    async def list_agents(
        self, workspace_id: str | None = None, role_key: str | None = None
    ) -> list["Agent"]:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        sql = "SELECT * FROM agents WHERE 1=1"
        params: list[object] = []
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

    def _row_to_workflow_graph(self, row: aiosqlite.Row) -> "WorkflowGraph":
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

    def _row_to_workflow_node(self, row: aiosqlite.Row) -> "WorkflowNode":
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
            instance_index=row["instance_index"] if _row_has_key(row, "instance_index") else 0,
            batch_key=row["batch_key"] if _row_has_key(row, "batch_key") else None,
            started_at=self._parse_datetime(row["started_at"]),
            completed_at=self._parse_datetime(row["completed_at"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def _row_to_workflow_edge(self, row: aiosqlite.Row) -> "WorkflowEdge":
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
                        instance_index, batch_key, started_at, completed_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        n.batch_key,
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
        params: list[object] = []
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if task_id is not None:
            sets.append("task_id = ?")
            params.append(task_id)
        if artifact_dir is not None:
            sets.append("artifact_dir = ?")
            params.append(artifact_dir)
        if prompt_override is not None:
            sets.append("prompt_override = ?")
            params.append(prompt_override)
        if retries is not None:
            sets.append("retries = ?")
            params.append(retries)
        if started_at is not None:
            sets.append("started_at = ?")
            params.append(self._format_datetime(started_at))
        if completed_at is not self._UNSET:
            # Explicit None clears the column to NULL; a datetime value formats it.
            if completed_at is not None and not isinstance(completed_at, datetime):
                raise TypeError("completed_at must be a datetime or None")
            db_val = self._format_datetime(completed_at)
            sets.append("completed_at = ?")
            params.append(db_val)
        sets.append("updated_at = ?")
        params.append(self._format_datetime(datetime.now()))
        params.append(node_id)
        # SET fragments are built only from fixed column names above; values stay parameterized.
        await conn.execute(
            f"UPDATE workflow_nodes SET {', '.join(sets)} WHERE id = ?",  # nosec B608
            tuple(params),
        )
        await conn.commit()

    async def add_workflow_node(self, node: "WorkflowNode") -> None:
        """Insert a single new node (used by Conductor-driven dynamic dispatch)."""
        await self._ensure_db()
        conn = await self._get_conn()
        now_iso = self._format_datetime(datetime.now())
        await conn.execute(
            """
            INSERT OR IGNORE INTO workflow_nodes (
                id, graph_id, node_key, agent_id, title, prompt_override,
                status, task_id, artifact_dir, retries, max_retries,
                instance_index, batch_key, started_at, completed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node.id,
                node.graph_id,
                node.node_key,
                node.agent_id,
                node.title,
                node.prompt_override,
                node.status,
                node.task_id,
                node.artifact_dir,
                node.retries,
                node.max_retries,
                node.instance_index,
                node.batch_key,
                self._format_datetime(node.started_at),
                self._format_datetime(node.completed_at),
                self._format_datetime(node.created_at) or now_iso,
                now_iso,
            ),
        )
        await conn.commit()

    async def add_workflow_edge(self, edge: "WorkflowEdge") -> None:
        """Insert a single new edge (used by Conductor-driven dynamic dispatch)."""
        await self._ensure_db()
        conn = await self._get_conn()
        now_iso = self._format_datetime(datetime.now())
        await conn.execute(
            """
            INSERT OR IGNORE INTO workflow_edges (
                id, graph_id, from_node_key, to_node_key, edge_type,
                condition_expr, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                edge.id,
                edge.graph_id,
                edge.from_node_key,
                edge.to_node_key,
                edge.edge_type,
                edge.condition_expr,
                self._format_datetime(edge.created_at) or now_iso,
            ),
        )
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
            out.append(
                GraphReplanPending(
                    id=r["id"],
                    graph_id=r["graph_id"],
                    triggered_by_node_key=r["triggered_by_node_key"],
                    trigger_reason=r["trigger_reason"],
                    diff_json=r["diff_json"],
                    rationale=r["rationale"],
                    status=r["status"],
                    created_at=self._parse_datetime(r["created_at"]),
                    resolved_at=self._parse_datetime(r["resolved_at"]),
                )
            )
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

    async def clear_issue_execution_history(self, issue_id: str) -> None:
        """Delete all execution history for an issue (used by reset).

        Clears every table whose data would make the UI show stale state
        after a hard reset: conductor phase/timeline, mesh messages, and
        any cached conductor decisions.
        """
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute("DELETE FROM conductor_turns WHERE issue_id = ?", (issue_id,))
        await conn.execute("DELETE FROM agent_messages WHERE issue_id = ?", (issue_id,))
        await conn.execute("DELETE FROM conductor_decisions WHERE issue_id = ?", (issue_id,))
        await conn.execute("DELETE FROM conductor_states WHERE issue_id = ?", (issue_id,))
        await conn.execute("DELETE FROM conductor_state_log WHERE issue_id = ?", (issue_id,))
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
            out.append(
                AgentMessage(
                    id=r["id"],
                    issue_id=r["issue_id"],
                    graph_id=r["graph_id"],
                    from_node_key=r["from_node_key"],
                    to_node_key=r["to_node_key"],
                    message_type=r["message_type"],
                    body=r["body"],
                    created_at=self._parse_datetime(r["created_at"]),
                )
            )
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

    async def save_project_conductor_state(self, state: "ProjectConductorState") -> bool:
        from app.domain.models import ProjectConductorState  # noqa: F401

        await self._ensure_db()
        conn = await self._get_conn()
        values = (
            state.hot_thread_json,
            state.warm_summaries_json,
            state.pinned_text,
            state.hot_tokens,
            state.warm_tokens,
            self._format_datetime(state.last_compaction_at),
            state.total_tasks_handled,
            self._format_datetime(state.updated_at),
        )
        if state.revision == 0:
            cursor = await conn.execute(
                """INSERT INTO project_conductor_states
                   (project_id, hot_thread_json, warm_summaries_json, pinned_text,
                    hot_tokens, warm_tokens, last_compaction_at, total_tasks_handled,
                    updated_at, revision)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                   ON CONFLICT(project_id) DO NOTHING""",
                (state.project_id, *values),
            )
        else:
            cursor = await conn.execute(
                """UPDATE project_conductor_states
                   SET hot_thread_json = ?, warm_summaries_json = ?, pinned_text = ?,
                       hot_tokens = ?, warm_tokens = ?, last_compaction_at = ?,
                       total_tasks_handled = ?, updated_at = ?, revision = revision + 1
                   WHERE project_id = ? AND revision = ?""",
                (*values, state.project_id, state.revision),
            )
        saved = cursor.rowcount == 1
        await conn.commit()
        if saved:
            state.revision += 1
        return saved

    async def load_project_conductor_state(self, project_id: str) -> "ProjectConductorState | None":
        from app.domain.models import ProjectConductorState

        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM project_conductor_states WHERE project_id = ?",
            (project_id,),
        ) as cur:
            row = await cur.fetchone()
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
            revision=int(row["revision"] or 0),
        )

    def _row_to_conductor_task(self, row: aiosqlite.Row) -> "ConductorTask":
        from app.domain.models import ConductorTask

        try:
            payload = _json_object(row["payload_json"]) or {}
        except json.JSONDecodeError:
            payload = {}
        return ConductorTask(
            id=row["id"],
            project_id=row["project_id"],
            task_kind=row["task_kind"],
            payload=payload,
            issue_id=row["issue_id"],
            status=row["status"],
            result_json=row["result_json"],
            lease_owner=row["lease_owner"]
            if _row_has_key(row, "lease_owner") and row["lease_owner"]
            else None,
            heartbeat_at=self._parse_datetime(
                row["heartbeat_at"] if _row_has_key(row, "heartbeat_at") else None
            ),
            lease_expires_at=self._parse_datetime(
                row["lease_expires_at"] if _row_has_key(row, "lease_expires_at") else None
            ),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    async def save_conductor_task(self, task: "ConductorTask") -> None:
        from app.domain.models import ConductorTask  # noqa: F401

        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
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
        await conn.commit()

    async def create_conductor_task_if_absent(self, task: "ConductorTask") -> bool:
        from app.domain.models import ConductorTask  # noqa: F401

        await self._ensure_db()
        conn = await self._get_conn()
        cur = await conn.execute(
            """INSERT OR IGNORE INTO conductor_tasks
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
        await conn.commit()
        return (cur.rowcount or 0) > 0

    async def load_latest_completed_project_review_at(
        self,
        project_id: str,
    ) -> datetime | None:
        await self._ensure_db()
        conn = await self._get_conn()
        async with conn.execute(
            """SELECT COALESCE(updated_at, created_at)
               FROM conductor_tasks
               WHERE project_id = ? AND task_kind = 'scheduled_review' AND status = 'done'
               ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
               LIMIT 1""",
            (project_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return self._parse_datetime(row[0])

    async def load_conductor_task(self, task_id: str) -> "ConductorTask | None":
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM conductor_tasks WHERE id = ?", (task_id,)) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return self._row_to_conductor_task(row)

    async def load_latest_conductor_task_for_issue(self, issue_id: str) -> "ConductorTask | None":
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """SELECT * FROM conductor_tasks
               WHERE issue_id = ?
               ORDER BY created_at DESC, updated_at DESC, id DESC
               LIMIT 1""",
            (issue_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return self._row_to_conductor_task(row)

    async def list_conductor_tasks(
        self,
        *,
        status: str | None = None,
        issue_id: str | None = None,
    ) -> list["ConductorTask"]:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        if status is not None and issue_id is not None:
            async with conn.execute(
                """SELECT * FROM conductor_tasks
                   WHERE status = ? AND issue_id = ?
                   ORDER BY created_at ASC, updated_at ASC, id ASC""",
                (status, issue_id),
            ) as cur:
                rows = await cur.fetchall()
        elif status is not None:
            async with conn.execute(
                """SELECT * FROM conductor_tasks
                   WHERE status = ?
                   ORDER BY created_at ASC, updated_at ASC, id ASC""",
                (status,),
            ) as cur:
                rows = await cur.fetchall()
        elif issue_id is not None:
            async with conn.execute(
                """SELECT * FROM conductor_tasks
                   WHERE issue_id = ?
                   ORDER BY created_at ASC, updated_at ASC, id ASC""",
                (issue_id,),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with conn.execute(
                "SELECT * FROM conductor_tasks ORDER BY created_at ASC, updated_at ASC, id ASC"
            ) as cur:
                rows = await cur.fetchall()
        return [self._row_to_conductor_task(row) for row in rows]

    async def save_conductor_turn(self, turn: "ConductorTurn") -> None:
        from app.domain.models import ConductorTurn  # noqa: F401

        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
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
        await conn.commit()

    async def enqueue_conductor_user_message(
        self, conductor_task_id: str, issue_id: str, text: str
    ) -> "ConductorTurn":
        from app.domain.models import ConductorTurn

        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT COALESCE(MAX(turn_index), -1) AS max_turn_index FROM conductor_turns WHERE conductor_task_id = ?",
            (conductor_task_id,),
        ) as cur:
            row = await cur.fetchone()
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
        await self.save_conductor_turn(turn)
        return turn

    async def drain_conductor_inbox(self, conductor_task_id: str) -> list["ConductorTurn"]:
        from app.domain.models import ConductorTurn

        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """SELECT * FROM conductor_turns
               WHERE conductor_task_id = ? AND kind = 'user_message' AND consumed_at IS NULL
               ORDER BY created_at ASC, id ASC""",
            (conductor_task_id,),
        ) as cur:
            rows = await cur.fetchall()
        if not rows:
            return []
        consumed_at = datetime.now()
        await conn.executemany(
            "UPDATE conductor_turns SET consumed_at = ? WHERE id = ?",
            [(self._format_datetime(consumed_at), row["id"]) for row in rows],
        )
        await conn.commit()
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

    async def list_conductor_turns(
        self,
        issue_id: str,
        *,
        conductor_task_id: str | None = None,
        limit: int = 200,
    ) -> list["ConductorTurn"]:
        from app.domain.models import ConductorTurn

        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        sql = """SELECT * FROM conductor_turns
                 WHERE issue_id = ?"""
        params: list[object] = [issue_id]
        if conductor_task_id:
            sql += " AND conductor_task_id = ?"
            params.append(conductor_task_id)
        sql += " ORDER BY created_at ASC, turn_index ASC, sub_index ASC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        async with conn.execute(sql, tuple(params)) as cur:
            rows = await cur.fetchall()
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
                consumed_at=self._parse_datetime(row["consumed_at"])
                if _row_has_key(row, "consumed_at")
                else None,
            )
            for row in rows
        ]

    async def save_conductor_state_log(self, entry: "ConductorStateLog") -> None:
        from app.domain.models import ConductorStateLog  # noqa: F401

        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
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
        await conn.commit()

    async def list_conductor_state_logs(
        self,
        issue_id: str | None = None,
        *,
        limit: int = 200,
        descending: bool = False,
    ) -> list["ConductorStateLog"]:
        from app.domain.models import ConductorStateLog

        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
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
        async with conn.execute(sql, tuple(params)) as cur:
            rows = await cur.fetchall()
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

    async def save_audit_log(self, entry: "AuditLog") -> None:
        from app.domain.models import AuditLog  # noqa: F401

        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            """INSERT OR REPLACE INTO audit_log
               (id, created_at, category, actor, issue_id, task_id, conductor_task_id,
                execution_process_id, correlation_id, trace_id, span_id, parent_span_id,
                status, duration_ms, payload_json, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                entry.trace_id,
                entry.span_id,
                entry.parent_span_id,
                entry.status,
                entry.duration_ms,
                entry.payload_json,
                entry.error,
            ),
        )
        await conn.commit()

    async def load_audit_log(self, audit_log_id: str) -> "AuditLog | None":
        from app.domain.models import AuditLog

        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM audit_log WHERE id = ?", (audit_log_id,)) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return AuditLog(
            id=row["id"],
            created_at=self._parse_datetime(row["created_at"]),
            category=row["category"],
            actor=row["actor"],
            issue_id=row["issue_id"],
            task_id=row["task_id"],
            conductor_task_id=row["conductor_task_id"],
            execution_process_id=row["execution_process_id"],
            correlation_id=row["correlation_id"],
            trace_id=row["trace_id"] if _row_has_key(row, "trace_id") else None,
            span_id=row["span_id"] if _row_has_key(row, "span_id") else None,
            parent_span_id=row["parent_span_id"] if _row_has_key(row, "parent_span_id") else None,
            status=row["status"],
            duration_ms=int(row["duration_ms"]) if row["duration_ms"] is not None else None,
            payload_json=row["payload_json"],
            error=row["error"],
        )

    async def save_agent_call_trace(self, trace: AgentCallTrace) -> None:
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            """INSERT OR REPLACE INTO agent_call_traces
               (id, audit_log_id, trace_id, span_id, parent_span_id, issue_id, task_id,
                execution_process_id, kind, title, request_json, response_json,
                request_preview, response_preview, metadata_json, is_truncated, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trace.id,
                trace.audit_log_id,
                trace.trace_id,
                trace.span_id,
                trace.parent_span_id,
                trace.issue_id,
                trace.task_id,
                trace.execution_process_id,
                trace.kind,
                trace.title,
                trace.request_json,
                trace.response_json,
                trace.request_preview,
                trace.response_preview,
                trace.metadata_json,
                1 if trace.is_truncated else 0,
                self._format_datetime(trace.created_at or datetime.now()),
            ),
        )
        await conn.commit()

    def _agent_call_trace_from_row(self, row: aiosqlite.Row) -> AgentCallTrace:
        return AgentCallTrace(
            id=row["id"],
            audit_log_id=row["audit_log_id"],
            trace_id=row["trace_id"],
            span_id=row["span_id"],
            parent_span_id=row["parent_span_id"],
            issue_id=row["issue_id"],
            task_id=row["task_id"],
            execution_process_id=row["execution_process_id"],
            kind=row["kind"],
            title=row["title"],
            request_json=row["request_json"],
            response_json=row["response_json"],
            request_preview=row["request_preview"],
            response_preview=row["response_preview"],
            metadata_json=row["metadata_json"] or "{}",
            is_truncated=bool(row["is_truncated"]),
            created_at=self._parse_datetime(row["created_at"]),
        )

    async def load_agent_call_trace(self, audit_log_id: str) -> AgentCallTrace | None:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM agent_call_traces WHERE audit_log_id = ? ORDER BY created_at DESC LIMIT 1",
            (audit_log_id,),
        ) as cur:
            row = await cur.fetchone()
        return self._agent_call_trace_from_row(row) if row is not None else None

    async def list_agent_call_traces(
        self,
        *,
        trace_id: str | None = None,
        task_id: str | None = None,
        execution_process_id: str | None = None,
        limit: int = 100,
    ) -> list[AgentCallTrace]:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        clauses: list[str] = []
        params: list[object] = []
        if trace_id:
            clauses.append("trace_id = ?")
            params.append(trace_id)
        if task_id:
            clauses.append("task_id = ?")
            params.append(task_id)
        if execution_process_id:
            clauses.append("execution_process_id = ?")
            params.append(execution_process_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 500)))
        async with conn.execute(
            f"SELECT * FROM agent_call_traces {where} ORDER BY created_at ASC LIMIT ?",  # nosec B608
            tuple(params),
        ) as cur:
            rows = await cur.fetchall()
        return [self._agent_call_trace_from_row(row) for row in rows]

    async def list_audit_logs(
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
        from app.domain.models import AuditLog

        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        sql, params = _build_audit_log_query(
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
        async with conn.execute(sql, tuple(params)) as cur:
            rows = await cur.fetchall()
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
                trace_id=row["trace_id"] if _row_has_key(row, "trace_id") else None,
                span_id=row["span_id"] if _row_has_key(row, "span_id") else None,
                parent_span_id=row["parent_span_id"]
                if _row_has_key(row, "parent_span_id")
                else None,
                status=row["status"],
                duration_ms=int(row["duration_ms"]) if row["duration_ms"] is not None else None,
                payload_json=row["payload_json"],
                error=row["error"],
            )
            for row in rows
        ]

    async def save_project_memory_embedding(self, memory: "ProjectMemoryEmbedding") -> None:
        from app.domain.models import ProjectMemoryEmbedding  # noqa: F401

        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
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
        await conn.commit()

    async def list_project_memory_embeddings(
        self,
        project_id: str,
        limit: int | None = None,
        *,
        descending: bool = False,
    ) -> list["ProjectMemoryEmbedding"]:
        from app.domain.models import ProjectMemoryEmbedding

        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        if descending:
            sql = (
                "SELECT * FROM project_memory_embeddings WHERE project_id = ? "
                "ORDER BY created_at DESC, id DESC"
            )
        else:
            sql = (
                "SELECT * FROM project_memory_embeddings WHERE project_id = ? "
                "ORDER BY created_at ASC, id ASC"
            )
        args: list[object] = [project_id]
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)
        async with conn.execute(sql, tuple(args)) as cur:
            rows = await cur.fetchall()
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

    async def count_project_memory_embeddings(self, project_id: str) -> int:
        await self._ensure_db()
        conn = await self._get_conn()
        async with conn.execute(
            "SELECT COUNT(*) FROM project_memory_embeddings WHERE project_id = ?",
            (project_id,),
        ) as cur:
            row = await cur.fetchone()
        return int(row[0]) if row is not None else 0

    async def save_self_improvement_proposal(self, proposal: "SelfImprovementProposal") -> None:
        from app.domain.models import SelfImprovementProposal  # noqa: F401

        await self._ensure_db()
        conn = await self._get_conn()
        now = datetime.now()
        created_at = proposal.created_at or now
        updated_at = proposal.updated_at or now
        await conn.execute(
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
        await conn.commit()

    async def list_self_improvement_proposals(
        self,
        project_id: str | None = None,
        issue_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list["SelfImprovementProposal"]:
        from app.domain.models import SelfImprovementProposal

        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
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
        # WHERE fragments are built only from fixed column predicates above; values stay parameterized.
        sql = (
            "SELECT id, project_id, issue_id, target_kind, title, recommendation, evidence_json, "
            "severity, confidence, status, fingerprint, created_at, updated_at "
            f"FROM self_improvement_proposals{where} ORDER BY created_at DESC, id DESC"  # nosec B608
        )
        if limit is not None:
            sql += " LIMIT ?"
            args.append(max(1, min(int(limit), 100)))
        async with conn.execute(sql, tuple(args)) as cur:
            rows = await cur.fetchall()
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

    async def load_self_improvement_proposal(
        self, proposal_id: str
    ) -> "SelfImprovementProposal | None":
        from app.domain.models import SelfImprovementProposal

        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT id, project_id, issue_id, target_kind, title, recommendation, evidence_json, "
            "severity, confidence, status, fingerprint, created_at, updated_at "
            "FROM self_improvement_proposals WHERE id = ?",
            (proposal_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return SelfImprovementProposal(
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

    async def update_self_improvement_proposal_status(
        self, proposal_id: str, status: str
    ) -> "SelfImprovementProposal | None":
        await self._ensure_db()
        conn = await self._get_conn()
        updated_at = datetime.now()
        cur = await conn.execute(
            "UPDATE self_improvement_proposals SET status = ?, updated_at = ? WHERE id = ?",
            (status, self._format_datetime(updated_at), proposal_id),
        )
        await conn.commit()
        if cur.rowcount == 0:
            return None
        return await self.load_self_improvement_proposal(proposal_id)

    async def save_self_improvement_application_event(
        self, event: "SelfImprovementApplicationEvent"
    ) -> None:
        from app.domain.models import SelfImprovementApplicationEvent  # noqa: F401

        await self._ensure_db()
        conn = await self._get_conn()
        created_at = event.created_at or datetime.now()
        await conn.execute(
            """INSERT OR REPLACE INTO self_improvement_application_events
               (id, proposal_id, project_id, issue_id, target_kind, action, status,
                path, content_sha256, result_json, error, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.id,
                event.proposal_id,
                event.project_id,
                event.issue_id,
                event.target_kind,
                event.action,
                event.status,
                event.path,
                event.content_sha256,
                event.result_json or "{}",
                event.error,
                self._format_datetime(created_at),
            ),
        )
        await conn.commit()

    async def list_self_improvement_application_events(
        self,
        project_id: str | None = None,
        proposal_id: str | None = None,
        limit: int | None = None,
    ) -> list["SelfImprovementApplicationEvent"]:
        from app.domain.models import SelfImprovementApplicationEvent

        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        clauses: list[str] = []
        args: list[object] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            args.append(project_id)
        if proposal_id is not None:
            clauses.append("proposal_id = ?")
            args.append(proposal_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        # WHERE fragments are built only from fixed column predicates above; values stay parameterized.
        sql = (
            "SELECT id, proposal_id, project_id, issue_id, target_kind, action, status, "
            "path, content_sha256, result_json, error, created_at "
            f"FROM self_improvement_application_events{where} "  # nosec B608
            "ORDER BY created_at DESC, id DESC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            args.append(max(1, min(int(limit), 100)))
        async with conn.execute(sql, tuple(args)) as cur:
            rows = await cur.fetchall()
        return [
            SelfImprovementApplicationEvent(
                id=row["id"],
                proposal_id=row["proposal_id"],
                project_id=row["project_id"],
                issue_id=row["issue_id"],
                target_kind=row["target_kind"],
                action=row["action"],
                status=row["status"],
                path=row["path"],
                content_sha256=row["content_sha256"],
                result_json=row["result_json"] or "{}",
                error=row["error"],
                created_at=self._parse_datetime(row["created_at"]),
            )
            for row in rows
        ]

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
            out.append(
                ConductorDecision(
                    id=r["id"],
                    issue_id=r["issue_id"],
                    task_id=r["task_id"],
                    action=r["action"],
                    reason=r["reason"],
                    diff_json=r["diff_json"],
                    applied_at=self._parse_datetime(r["applied_at"]),
                    created_at=self._parse_datetime(r["created_at"]),
                )
            )
        return out

    # --- Skill CRUD ---

    def _row_to_skill(self, r: aiosqlite.Row) -> Skill:
        tags_raw = r["tags"]
        try:
            tags = _json_string_list(tags_raw) or []
        except (ValueError, TypeError):
            tags = []
        return Skill(
            id=r["id"],
            name=r["name"],
            link=r["link"],
            description=r["description"],
            category=r["category"],
            tags=tags,
            created_at=self._parse_datetime(r["created_at"]),
            updated_at=self._parse_datetime(r["updated_at"]),
        )

    async def save_skill(self, skill: Skill) -> None:
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            "INSERT OR REPLACE INTO skills (id, name, link, description, category, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                skill.id,
                skill.name,
                skill.link,
                skill.description,
                skill.category,
                json.dumps(skill.tags or []),
                self._format_datetime(skill.created_at),
                self._format_datetime(skill.updated_at),
            ),
        )
        await conn.commit()

    async def load_skill(self, skill_id: str) -> Skill | None:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)) as cur:
            row = await cur.fetchone()
        return self._row_to_skill(row) if row else None

    async def list_skills(
        self,
        *,
        search: str | None = None,
        category: str | None = None,
    ) -> list[Skill]:
        await self._ensure_db()
        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row
        clauses: list[str] = []
        params: list[object] = []
        if search:
            clauses.append("(name LIKE ? OR description LIKE ? OR tags LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like, like])
        if category:
            clauses.append("category = ?")
            params.append(category)
        sql = "SELECT * FROM skills"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC"
        async with conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [self._row_to_skill(r) for r in rows]

    async def list_skill_categories(self) -> list[str]:
        """Union of categories observed on skills and user-pre-created empty
        categories). Returned sorted alphabetically.
        """
        await self._ensure_db()
        conn = await self._get_conn()
        async with conn.execute(
            "SELECT DISTINCT category FROM skills WHERE category IS NOT NULL AND category != ''"
        ) as cur:
            in_use = {r[0] for r in await cur.fetchall()}
        async with conn.execute("SELECT name FROM skill_categories") as cur:
            user_defined = {r[0] for r in await cur.fetchall()}
        return sorted(in_use | user_defined)

    async def add_skill_category(self, name: str) -> None:
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute(
            "INSERT OR IGNORE INTO skill_categories (name) VALUES (?)",
            (name,),
        )
        await conn.commit()

    async def delete_skill_category(self, name: str) -> int:
        """Remove a user-defined empty category. Returns the number of skills
        that still reference this category — caller decides whether to refuse
        the delete or to cascade.
        """
        await self._ensure_db()
        conn = await self._get_conn()
        async with conn.execute(
            "SELECT COUNT(*) FROM skills WHERE category = ?",
            (name,),
        ) as cur:
            row = await cur.fetchone()
            in_use = int(row[0]) if row else 0
        await conn.execute("DELETE FROM skill_categories WHERE name = ?", (name,))
        await conn.commit()
        return in_use

    async def delete_skill(self, skill_id: str) -> None:
        await self._ensure_db()
        conn = await self._get_conn()
        await conn.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
        await conn.commit()
