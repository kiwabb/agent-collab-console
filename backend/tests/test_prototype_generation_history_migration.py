from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.adapters.async_sqlite_store import AsyncSQLiteStore

_HTML_SENTINEL = "<!doctype html><html><body>HISTORY-PRESERVE-SENTINEL-9F1C7A</body></html>"
_HTML_RESULT_JSON = json.dumps({"result": _HTML_SENTINEL}, separators=(",", ":"))


def _runtime_history_snapshot(
    connection: sqlite3.Connection,
) -> dict[str, list[tuple[object, ...]]]:
    table_queries = {
        "codex_tasks": "SELECT * FROM codex_tasks ORDER BY id",
        "codex_task_messages": "SELECT * FROM codex_task_messages ORDER BY id",
        "log_events": "SELECT * FROM log_events ORDER BY id",
        "audit_log": "SELECT * FROM audit_log ORDER BY id",
        "agent_call_traces": "SELECT * FROM agent_call_traces ORDER BY id",
    }
    snapshots: dict[str, list[tuple[object, ...]]] = {}
    for table, query in table_queries.items():
        rows = connection.execute(query).fetchall()
        snapshots[table] = [tuple(row) for row in rows]
    return snapshots


@pytest.mark.asyncio
async def test_v8_preserves_complete_prototype_generation_runtime_history(tmp_path: Path) -> None:
    db_path = tmp_path / "prototype-history.db"
    initial_store = AsyncSQLiteStore(db_path)
    try:
        await initial_store._init_db()
    finally:
        await initial_store.close()

    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "INSERT INTO codex_sessions (id, title, cwd) VALUES (?, ?, ?)",
            ("workspace", "Workspace", str(tmp_path)),
        )
        connection.executemany(
            """
            INSERT INTO codex_tasks (
                id, session_id, title, prompt, task_kind, result, result_json,
                trace_id, span_id, created_at, updated_at
            ) VALUES (?, 'workspace', ?, ?, ?, ?, ?, ?, ?, '2026-07-12', '2026-07-12')
            """,
            [
                (
                    "generation-task",
                    "Generation title remains",
                    "Generation prompt remains",
                    "prototype_generation",
                    f"result:{_HTML_SENTINEL}",
                    _HTML_RESULT_JSON,
                    "generation-process",
                    "generation-task",
                ),
                (
                    "planning-task",
                    "Planning title",
                    "Planning prompt",
                    "prototype_planning",
                    f"planning-result:{_HTML_SENTINEL}",
                    _HTML_RESULT_JSON,
                    "planning-process",
                    "planning-task",
                ),
                (
                    "normal-task",
                    "Normal title",
                    "Normal prompt",
                    "normal",
                    f"normal-result:{_HTML_SENTINEL}",
                    _HTML_RESULT_JSON,
                    "normal-process",
                    "normal-task",
                ),
            ],
        )
        connection.executemany(
            """
            INSERT INTO execution_processes (id, task_id, session_id, status, created_at)
            VALUES (?, ?, 'workspace', 'Completed', '2026-07-12')
            """,
            [
                ("generation-process", "generation-task"),
                ("planning-process", "planning-task"),
                ("normal-process", "normal-task"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO codex_task_messages (id, task_id, execution_process_id, role, content)
            VALUES (?, ?, ?, 'assistant', ?)
            """,
            [
                ("generation-message", "generation-task", "generation-process", _HTML_SENTINEL),
                ("planning-message", "planning-task", "planning-process", _HTML_SENTINEL),
                ("normal-message", "normal-task", "normal-process", _HTML_SENTINEL),
            ],
        )
        connection.executemany(
            """
            INSERT INTO log_events (
                id, session_id, stream, content, task_id, execution_process_id,
                trace_id, span_id, parent_span_id, created_at
            ) VALUES (?, 'workspace', 'stdout', ?, ?, ?, ?, ?, ?, '2026-07-12')
            """,
            [
                (
                    "generation-log",
                    _HTML_SENTINEL,
                    "generation-task",
                    "generation-process",
                    "generation-process",
                    "generation-task",
                    None,
                ),
                (
                    "generation-process-log",
                    _HTML_SENTINEL,
                    None,
                    "generation-process",
                    None,
                    None,
                    None,
                ),
                (
                    "planning-log",
                    _HTML_SENTINEL,
                    "planning-task",
                    "planning-process",
                    "generation-process",
                    "planning-task",
                    "generation-task",
                ),
                (
                    "normal-log",
                    _HTML_SENTINEL,
                    "normal-task",
                    "normal-process",
                    "normal-process",
                    "normal-task",
                    None,
                ),
            ],
        )
        connection.executemany(
            """
            INSERT INTO audit_log (
                id, created_at, category, actor, task_id, execution_process_id,
                correlation_id, trace_id, span_id, payload_json, status, error
            ) VALUES (?, '2026-07-12', 'agent_finalize', 'prototype_ui_engineer',
                      ?, ?, ?, ?, ?, ?, 'done', ?)
            """,
            [
                (
                    "generation-audit",
                    "generation-task",
                    "generation-process",
                    "generation-process",
                    "generation-process",
                    "generation-task",
                    _HTML_RESULT_JSON,
                    "preserved generation error metadata",
                ),
                (
                    "generation-trace-linked-audit",
                    None,
                    None,
                    None,
                    None,
                    None,
                    json.dumps({"response_preview": _HTML_SENTINEL}, separators=(",", ":")),
                    None,
                ),
                (
                    "planning-audit",
                    "planning-task",
                    "planning-process",
                    "generation-process",
                    "planning-process",
                    "planning-task",
                    _HTML_RESULT_JSON,
                    "planning error",
                ),
                (
                    "normal-audit",
                    "normal-task",
                    "normal-process",
                    "normal-process",
                    "normal-process",
                    "normal-task",
                    _HTML_RESULT_JSON,
                    "normal error",
                ),
            ],
        )
        trace_values = (
            json.dumps({"request": _HTML_SENTINEL}, separators=(",", ":")),
            json.dumps({"response": _HTML_SENTINEL}, separators=(",", ":")),
            f"request-preview:{_HTML_SENTINEL}",
            f"response-preview:{_HTML_SENTINEL}",
        )
        connection.executemany(
            """
            INSERT INTO agent_call_traces (
                id, audit_log_id, trace_id, span_id, task_id, execution_process_id,
                kind, title, request_json, response_json, request_preview,
                response_preview, metadata_json, is_truncated, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'runtime_agent', ?, ?, ?, ?, ?, ?, 0, '2026-07-12')
            """,
            [
                (
                    "generation-trace",
                    "generation-audit",
                    "generation-process",
                    "generation-task",
                    "generation-task",
                    "generation-process",
                    "Generation trace title remains",
                    *trace_values,
                    '{"metadata":"remains"}',
                ),
                (
                    "generation-audit-linked-trace",
                    "generation-audit",
                    None,
                    None,
                    None,
                    None,
                    "Audit-linked trace title remains",
                    *trace_values,
                    '{"metadata":"remains"}',
                ),
                (
                    "generation-trace-linked-audit-trace",
                    "generation-trace-linked-audit",
                    "generation-process",
                    "generation-task",
                    "generation-task",
                    "generation-process",
                    "Trace-linked audit title remains",
                    *trace_values,
                    '{"metadata":"remains"}',
                ),
                (
                    "planning-trace",
                    "planning-audit",
                    "generation-process",
                    "planning-task",
                    "planning-task",
                    "planning-process",
                    "Planning trace",
                    *trace_values,
                    '{"metadata":"planning"}',
                ),
                (
                    "normal-trace",
                    "normal-audit",
                    "normal-process",
                    "normal-task",
                    "normal-task",
                    "normal-process",
                    "Normal trace",
                    *trace_values,
                    '{"metadata":"normal"}',
                ),
            ],
        )
        connection.execute("UPDATE schema_version SET version = 7 WHERE id = 1")
        connection.commit()
        before_history = _runtime_history_snapshot(connection)
    finally:
        connection.close()

    migrated_store = AsyncSQLiteStore(db_path)
    try:
        await migrated_store._init_db()
    finally:
        await migrated_store.close()

    connection = sqlite3.connect(db_path)
    try:
        assert _runtime_history_snapshot(connection) == before_history
        version = connection.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
        assert version == (11,)
    finally:
        connection.close()

    reopened_store = AsyncSQLiteStore(db_path)
    try:
        await reopened_store._init_db()
    finally:
        await reopened_store.close()
    reopened = sqlite3.connect(db_path)
    try:
        assert _runtime_history_snapshot(reopened) == before_history
    finally:
        reopened.close()
