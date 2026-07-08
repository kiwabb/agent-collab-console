"""PR3 tests for the audit_log read API + store query extensions.

Covers `GET /api/codex/audit-log` (filters / search / cursor pagination) and
the underlying `list_audit_logs` store extensions (categories IN, since/until,
q LIKE, keyset cursor) on BOTH stores. Frontend (PR4) is out of scope.
"""

from __future__ import annotations  # noqa: I001

import asyncio
from datetime import datetime, timedelta

import pytest

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.adapters.sqlite_store import SQLiteStore
from app.domain.models import AgentCallTrace, AuditLog, CodexTask, CodexTaskMessage, LogEvent


# --- store-level seeding helper ------------------------------------------------


def _seed_via_bootstrap_sync_store(rows: list[AuditLog]) -> None:
    """Insert rows through the bootstrap sync store (same DB file the API reads).

    The API endpoint reads through the async `codex_store`, but both stores point
    at the same SQLite file, so seeding synchronously is the simplest path inside
    a sync TestClient test.
    """
    import app.bootstrap as bootstrap_module

    store = bootstrap_module.store
    assert store is not None
    for row in rows:
        store.save_audit_log(row)


def _seed_task_for_api(task: CodexTask) -> None:
    import app.bootstrap as bootstrap_module
    from app.interfaces import api as api_module

    assert bootstrap_module.store is not None
    bootstrap_module.store.save_codex_task(task)
    assert api_module.codex_store is not None
    asyncio.run(api_module.codex_store.save_codex_task(task))


def _seed_task_message_for_api(message: CodexTaskMessage) -> None:
    import app.bootstrap as bootstrap_module
    from app.interfaces import api as api_module

    assert bootstrap_module.store is not None
    bootstrap_module.store.save_codex_task_message(message)
    assert api_module.codex_store is not None
    asyncio.run(api_module.codex_store.save_codex_task_message(message))


def _seed_log_event_for_api(event: LogEvent) -> None:
    from app.interfaces import api as api_module

    assert api_module.codex_store is not None
    append_log_event = getattr(api_module.codex_store, "append_log_event")
    asyncio.run(append_log_event(event))


def _row(
    idx: int,
    *,
    category: str = "git_command",
    issue_id: str | None = "issue-1",
    task_id: str | None = "task-1",
    actor: str | None = "tester",
    payload_json: str = "{}",
    error: str | None = None,
    created_at: datetime | None = None,
) -> AuditLog:
    base = datetime(2026, 5, 31, 12, 0, 0)
    return AuditLog(
        id=f"audit-{idx:04d}",
        category=category,
        created_at=created_at or (base + timedelta(seconds=idx)),
        actor=actor,
        issue_id=issue_id,
        task_id=task_id,
        conductor_task_id=None,
        execution_process_id=None,
        correlation_id=None,
        status="ok",
        duration_ms=idx,
        payload_json=payload_json,
        error=error,
    )


# =============================================================================
# Store-level unit tests (async + sync parity)
# =============================================================================


@pytest.fixture
async def audit_store(tmp_path):
    store = AsyncSQLiteStore(tmp_path / "console.db")
    await store._ensure_db()
    try:
        yield store
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_store_categories_in_filter(audit_store):
    await audit_store.save_audit_log(_row(1, category="git_command"))
    await audit_store.save_audit_log(_row(2, category="llm_call"))
    await audit_store.save_audit_log(_row(3, category="tool_use"))

    rows = await audit_store.list_audit_logs(categories=["git_command", "llm_call"])
    cats = {r.category for r in rows}
    assert cats == {"git_command", "llm_call"}


@pytest.mark.asyncio
async def test_store_since_until_range(audit_store):
    for i in range(1, 6):
        await audit_store.save_audit_log(_row(i))

    base = datetime(2026, 5, 31, 12, 0, 0)
    since = (base + timedelta(seconds=2)).isoformat()
    until = (base + timedelta(seconds=4)).isoformat()
    rows = await audit_store.list_audit_logs(since=since, until=until)
    durations = [r.duration_ms for r in rows]
    assert all(duration is not None for duration in durations)
    secs = sorted(duration for duration in durations if duration is not None)
    assert secs == [2, 3, 4]  # inclusive both ends


@pytest.mark.asyncio
async def test_store_q_search_case_insensitive(audit_store):
    await audit_store.save_audit_log(_row(1, payload_json='{"cmd": "git STATUS --porcelain"}'))
    await audit_store.save_audit_log(_row(2, payload_json='{"cmd": "ls -la"}'))

    hit = await audit_store.list_audit_logs(q="status")
    assert len(hit) == 1
    assert hit[0].id == "audit-0001"

    hit_upper = await audit_store.list_audit_logs(q="STATUS")
    assert len(hit_upper) == 1

    miss = await audit_store.list_audit_logs(q="no-such-token-xyz")
    assert miss == []


@pytest.mark.asyncio
async def test_store_q_search_is_injection_safe(audit_store):
    await audit_store.save_audit_log(_row(1, payload_json='{"x": 1}'))
    await audit_store.save_audit_log(_row(2, payload_json="{}"))

    # A `q` full of SQL metacharacters / LIKE wildcards must not error, must not
    # match everything via injection, and must not drop/alter rows.
    for malicious in ["%", "'", "' OR '1'='1", "%' --", "_;DROP TABLE audit_log;"]:
        rows = await audit_store.list_audit_logs(q=malicious)
        assert isinstance(rows, list)

    # The table is intact and untouched after the injection attempts.
    remaining = await audit_store.list_audit_logs(limit=100)
    assert len(remaining) == 2


@pytest.mark.asyncio
async def test_store_cursor_keyset_pagination(audit_store):
    for i in range(1, 11):
        await audit_store.save_audit_log(_row(i))

    # Page 1 (newest first): ids 10..6
    page1 = await audit_store.list_audit_logs(limit=5, descending=True)
    assert [r.duration_ms for r in page1] == [10, 9, 8, 7, 6]

    last = page1[-1]
    assert last.created_at is not None
    page2 = await audit_store.list_audit_logs(
        limit=5,
        descending=True,
        cursor_created_at=last.created_at.isoformat(),
        cursor_id=last.id,
    )
    assert [r.duration_ms for r in page2] == [5, 4, 3, 2, 1]

    # No overlap, full coverage.
    all_ids = {r.id for r in page1} | {r.id for r in page2}
    assert len(all_ids) == 10


def test_sync_store_query_parity(tmp_path):
    store = SQLiteStore(tmp_path / "console.db")
    store._init_db()
    store.save_audit_log(_row(1, category="git_command"))
    store.save_audit_log(_row(2, category="llm_call"))

    rows = store.list_audit_logs(categories=["llm_call"], q="tester")
    assert len(rows) == 1
    assert rows[0].category == "llm_call"


def test_store_legacy_single_category_still_works(tmp_path):
    """Backward compat: the singular `category` kwarg (PR1/PR2 callers) still filters."""
    store = SQLiteStore(tmp_path / "console.db")
    store._init_db()
    store.save_audit_log(_row(1, category="git_command"))
    store.save_audit_log(_row(2, category="llm_call"))

    rows = store.list_audit_logs(category="git_command")
    assert len(rows) == 1
    assert rows[0].category == "git_command"


# =============================================================================
# API-level tests (GET /api/codex/audit-log)
# =============================================================================


def test_api_returns_items_and_shape(client):
    _seed_via_bootstrap_sync_store([_row(1), _row(2)])
    resp = client.get("/api/codex/audit-log")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body and "next_cursor" in body
    assert len(body["items"]) == 2
    item = body["items"][0]
    for key in ("id", "created_at", "category", "payload_json", "actor"):
        assert key in item
    # newest first (duration_ms 2 then 1 in our seed ordering)
    assert [i["duration_ms"] for i in body["items"]] == [2, 1]


def test_api_returns_role_chain_metadata_for_task_and_command_rows(client):
    _seed_task_for_api(
        CodexTask(
            id="task-engineer",
            session_id="workspace-1",
            issue_id="issue-1",
            title="Engineer task",
            prompt="Implement",
            role="engineer",
        )
    )
    _seed_via_bootstrap_sync_store(
        [
            _row(
                1,
                category="command_exec",
                task_id="task-engineer",
                payload_json='{"command": "pytest", "exit_code": 0, "stdout": "ok", "stderr": ""}',
            ),
            _row(
                2,
                category="git_command",
                task_id=None,
                actor="git",
                payload_json='{"argv": ["git", "status", "--short"], "cwd": "/repo", "exit_code": 0, "stdout": "ok", "stderr": ""}',
            ),
        ]
    )

    resp = client.get("/api/codex/audit-log")
    assert resp.status_code == 200, resp.text
    items = {item["id"]: item for item in resp.json()["items"]}
    command = items["audit-0001"]
    assert command["role"] == "engineer"
    assert command["role_label"] == "Engineer"
    assert command["task_title"] == "Engineer task"
    assert command["call_input"] == {"command": "pytest", "cwd": None}
    assert command["call_output"]["exit_code"] == 0
    assert command["call_output"]["stdout"] == "ok"

    git = items["audit-0002"]
    assert git["role"] == "system"
    assert git["role_label"] == "System"
    assert git["call_input"] == {"argv": ["git", "status", "--short"], "cwd": "/repo"}
    assert git["call_output"]["exit_code"] == 0
    assert git["call_summary"] == "git status --short"


def test_api_returns_role_chain_metadata_for_conductor_dispatch(client):
    _seed_via_bootstrap_sync_store(
        [
            AuditLog(
                id="audit-tool-use",
                category="tool_use",
                created_at=datetime(2026, 5, 31, 12, 0, 1),
                actor="dispatch_subagent",
                issue_id="issue-1",
                conductor_task_id="conductor-1",
                payload_json='{"name": "dispatch_subagent", "turn_index": 2, "sub_index": 1, "input": {"role": "architect", "task": "design"}}',
            ),
            AuditLog(
                id="audit-tool-result",
                category="tool_result",
                created_at=datetime(2026, 5, 31, 12, 0, 2),
                actor="dispatch_subagent",
                issue_id="issue-1",
                conductor_task_id="conductor-1",
                payload_json='{"name": "dispatch_subagent", "turn_index": 2, "sub_index": 2, "result": {"role": "architect", "summary": "done"}}',
            ),
        ]
    )

    resp = client.get("/api/codex/audit-log")
    assert resp.status_code == 200, resp.text
    items = {item["id"]: item for item in resp.json()["items"]}
    use = items["audit-tool-use"]
    assert use["role"] == "architect"
    assert use["role_label"] == "Architect"
    assert use["turn_index"] == 2
    assert use["sub_index"] == 1
    assert use["call_name"] == "dispatch_subagent"
    assert use["call_input"] == {"role": "architect", "task": "design"}

    result = items["audit-tool-result"]
    assert result["role"] == "architect"
    assert result["turn_index"] == 2
    assert result["sub_index"] == 2
    assert result["call_output"] == {"role": "architect", "summary": "done"}


def test_api_audit_log_chains_groups_agent_operation_and_hides_system(client):
    _seed_task_for_api(
        CodexTask(
            id="task-engineer",
            session_id="workspace-1",
            issue_id="issue-1",
            title="Engineer task",
            prompt="Implement",
            role="engineer",
        )
    )
    _seed_via_bootstrap_sync_store(
        [
            AuditLog(
                id="audit-system",
                category="git_command",
                created_at=datetime(2026, 5, 31, 12, 0, 3),
                actor="git",
                issue_id="issue-1",
                task_id=None,
                payload_json='{"argv": ["git", "status"], "exit_code": 0}',
            ),
            AuditLog(
                id="audit-result",
                category="tool_result",
                created_at=datetime(2026, 5, 31, 12, 0, 2),
                actor="dispatch_subagent",
                issue_id="issue-1",
                conductor_task_id="conductor-1",
                payload_json='{"name": "dispatch_subagent", "turn_index": 0, "sub_index": 2, "result": {"task_id": "task-engineer", "summary": "done"}}',
            ),
            AuditLog(
                id="audit-use",
                category="tool_use",
                created_at=datetime(2026, 5, 31, 12, 0, 1),
                actor="dispatch_subagent",
                issue_id="issue-1",
                conductor_task_id="conductor-1",
                payload_json='{"name": "dispatch_subagent", "turn_index": 0, "sub_index": 1, "input": {"task_id": "task-engineer", "task": "implement"}}',
            ),
        ]
    )

    resp = client.get("/api/codex/audit-log/chains")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    operation = body["items"][0]
    assert operation["role"] == "engineer"
    assert operation["role_label"] == "Engineer"
    assert operation["operation_task_id"] == "task-engineer"
    assert operation["task_title"] == "Engineer task"
    assert operation["entry_count"] == 2
    assert [entry["id"] for entry in operation["entries"]] == ["audit-use", "audit-result"]
    assert all(entry["role"] != "system" for entry in operation["entries"])


def test_api_audit_log_chains_paginates_past_system_only_rows(client):
    _seed_via_bootstrap_sync_store(
        [
            _row(
                5,
                category="git_command",
                task_id=None,
                actor="git",
                payload_json='{"argv": ["git", "status"], "exit_code": 0}',
            ),
            AuditLog(
                id="audit-tool-use",
                category="tool_use",
                created_at=datetime(2026, 5, 31, 12, 0, 1),
                actor="dispatch_subagent",
                issue_id="issue-1",
                conductor_task_id="conductor-1",
                payload_json='{"name": "dispatch_subagent", "turn_index": 0, "input": {"role": "architect", "task": "design"}}',
            ),
        ]
    )

    resp = client.get("/api/codex/audit-log/chains?limit=1")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["role"] == "architect"


def test_api_audit_log_trace_returns_saved_full_trace(client):
    import app.bootstrap as bootstrap_module

    assert bootstrap_module.store is not None
    _seed_via_bootstrap_sync_store(
        [
            AuditLog(
                id="audit-trace",
                category="llm_call",
                created_at=datetime(2026, 5, 31, 12, 0, 1),
                actor="auto_plan",
                payload_json='{"prompt_chars": 10}',
                trace_id="trace-1",
            )
        ]
    )
    bootstrap_module.store.save_agent_call_trace(
        AgentCallTrace(
            id="trace-row-1",
            audit_log_id="audit-trace",
            trace_id="trace-1",
            kind="llm",
            title="System Planner · model-1",
            request_json='{"messages":[{"role":"user","content":"full prompt"}]}',
            response_json='{"content":[{"type":"text","text":"full response"}]}',
            request_preview="full prompt",
            response_preview="full response",
            metadata_json='{"model":"model-1"}',
            is_truncated=False,
        )
    )

    resp = client.get("/api/codex/audit-log/audit-trace/trace")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["available"] is True
    assert body["id"] == "trace-row-1"
    assert body["request"]["messages"][0]["content"] == "full prompt"
    assert body["response"]["content"][0]["text"] == "full response"
    assert body["metadata"]["model"] == "model-1"

    trace_resp = client.get("/api/codex/traces/trace-1")
    assert trace_resp.status_code == 200, trace_resp.text
    trace_body = trace_resp.json()
    assert trace_body["available"] is True
    assert [item["id"] for item in trace_body["items"]] == ["trace-row-1"]


def test_api_audit_log_trace_falls_back_to_runtime_logs(client):
    _seed_task_for_api(
        CodexTask(
            id="task-runtime",
            session_id="workspace-1",
            issue_id="issue-1",
            title="Runtime task",
            prompt="full task prompt",
            role="engineer",
            executor="claude",
            provider="anthropic",
            model="model-1",
        )
    )
    _seed_task_message_for_api(
        CodexTaskMessage(
            id="message-1",
            task_id="task-runtime",
            execution_process_id="exec-1",
            role="assistant",
            content="assistant answer",
            created_at=datetime(2026, 5, 31, 12, 0, 2),
        )
    )
    _seed_log_event_for_api(
        LogEvent(
            id="log-1",
            session_id="workspace-1",
            stream="tool_use",
            content='{"kind":"tool_use","tool_name":"Read","input":{"file":"a.py"}}',
            task_id="task-runtime",
            execution_process_id="exec-1",
            created_at=datetime(2026, 5, 31, 12, 0, 3),
        )
    )
    _seed_via_bootstrap_sync_store(
        [
                AuditLog(
                    id="audit-runtime",
                    category="llm_call",
                    created_at=datetime(2026, 5, 31, 12, 0, 1),
                    actor="claude",
                    issue_id="issue-1",
                task_id="task-runtime",
                execution_process_id="exec-1",
                payload_json="{}",
            )
        ]
    )

    resp = client.get("/api/codex/audit-log/audit-runtime/trace")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["available"] is True
    assert body["kind"] == "runtime_logs"
    assert body["request"]["prompt"] == "full task prompt"
    assert body["response"]["messages"][0]["content"] == "assistant answer"
    assert body["response"]["logs"][0]["stream"] == "tool_use"
    assert body["metadata"]["source"] == "log_events"


def test_api_cli_spawn_trace_includes_runtime_process_logs(client):
    _seed_task_for_api(
        CodexTask(
            id="task-cli-runtime",
            session_id="workspace-1",
            issue_id="issue-1",
            title="Generate Startup Scripts",
            prompt="generate scripts",
            role="operations_engineer",
            executor="claude",
            provider="anthropic",
            model="MiniMax-M3",
        )
    )
    _seed_task_message_for_api(
        CodexTaskMessage(
            id="message-cli-1",
            task_id="task-cli-runtime",
            execution_process_id=None,
            role="assistant",
            content="I will inspect the project.",
            created_at=datetime(2026, 7, 8, 10, 52, 40),
        )
    )
    _seed_log_event_for_api(
        LogEvent(
            id="log-cli-1",
            session_id="workspace-1",
            stream="tool_use",
            content='{"kind":"tool_use","tool_name":"Read","input":{"file":"package.json"}}',
            task_id="task-cli-runtime",
            execution_process_id=None,
            created_at=datetime(2026, 7, 8, 10, 52, 45),
        )
    )
    _seed_via_bootstrap_sync_store(
        [
            AuditLog(
                id="audit-cli-runtime",
                category="cli_spawn",
                created_at=datetime(2026, 7, 8, 10, 52, 31),
                actor="claude",
                issue_id="issue-1",
                task_id="task-cli-runtime",
                payload_json='{"executor":"claude","model":"MiniMax-M3","pid":58816}',
            )
        ]
    )

    resp = client.get("/api/codex/audit-log/audit-cli-runtime/trace")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["available"] is True
    assert body["kind"] == "cli_spawn"
    assert body["request"]["task"]["title"] == "Generate Startup Scripts"
    assert body["response"]["messages"][0]["content"] == "I will inspect the project."
    assert body["response"]["logs"][0]["stream"] == "tool_use"
    assert body["metadata"]["source"] == "audit_log+runtime_logs"
    assert body["metadata"]["message_count"] == 1
    assert body["metadata"]["log_count"] == 1


def test_api_audit_log_trace_reports_unavailable_for_legacy_unlinked_rows(client):
    _seed_via_bootstrap_sync_store(
        [
            AuditLog(
                id="audit-legacy",
                category="llm_call",
                created_at=datetime(2026, 5, 31, 12, 0, 1),
                actor="auto_plan",
                payload_json='{"prompt_chars": 10}',
            )
        ]
    )

    resp = client.get("/api/codex/audit-log/audit-legacy/trace")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "available": False,
        "audit_log_id": "audit-legacy",
        "reason": "trace_not_recorded",
    }


def test_api_category_multi_value_repeated_and_csv(client):
    _seed_via_bootstrap_sync_store(
        [
            _row(1, category="git_command"),
            _row(2, category="llm_call"),
            _row(3, category="tool_use"),
        ]
    )

    # repeated param form
    resp = client.get("/api/codex/audit-log?category=git_command&category=llm_call")
    assert resp.status_code == 200
    cats = {i["category"] for i in resp.json()["items"]}
    assert cats == {"git_command", "llm_call"}

    # comma-separated form
    resp2 = client.get("/api/codex/audit-log?category=git_command,tool_use")
    cats2 = {i["category"] for i in resp2.json()["items"]}
    assert cats2 == {"git_command", "tool_use"}


def test_api_issue_and_task_filters(client):
    _seed_via_bootstrap_sync_store(
        [
            _row(1, issue_id="issue-A", task_id="task-A"),
            _row(2, issue_id="issue-B", task_id="task-B"),
        ]
    )
    resp = client.get("/api/codex/audit-log?issue_id=issue-A")
    items = resp.json()["items"]
    assert len(items) == 1 and items[0]["issue_id"] == "issue-A"

    resp2 = client.get("/api/codex/audit-log?task_id=task-B")
    items2 = resp2.json()["items"]
    assert len(items2) == 1 and items2[0]["task_id"] == "task-B"


def test_api_time_range_and_search(client):
    base = datetime(2026, 5, 31, 12, 0, 0)
    _seed_via_bootstrap_sync_store(
        [
            _row(1, payload_json='{"cmd": "git PUSH"}'),
            _row(2, payload_json='{"cmd": "git fetch"}'),
            _row(5, payload_json='{"cmd": "git merge"}'),
        ]
    )
    since = (base + timedelta(seconds=2)).isoformat()
    resp = client.get(f"/api/codex/audit-log?since={since}")
    secs = sorted(i["duration_ms"] for i in resp.json()["items"])
    assert secs == [2, 5]

    # case-insensitive q
    resp2 = client.get("/api/codex/audit-log?q=push")
    items2 = resp2.json()["items"]
    assert len(items2) == 1 and items2[0]["duration_ms"] == 1


def test_api_cursor_pagination_full_coverage(client):
    _seed_via_bootstrap_sync_store([_row(i) for i in range(1, 8)])  # 7 rows

    seen: list[int] = []
    cursor = None
    pages = 0
    while True:
        url = "/api/codex/audit-log?limit=3"
        if cursor:
            url += f"&cursor={cursor}"
        resp = client.get(url)
        assert resp.status_code == 200
        body = resp.json()
        seen.extend(i["duration_ms"] for i in body["items"])
        cursor = body["next_cursor"]
        pages += 1
        if cursor is None:
            break
        assert pages < 10, "pagination did not terminate"

    # All 7 seen exactly once, in strict descending order, no dupes/gaps.
    assert seen == [7, 6, 5, 4, 3, 2, 1]
    assert len(set(seen)) == 7


def test_api_limit_clamped_to_200(client):
    _seed_via_bootstrap_sync_store([_row(1)])
    resp = client.get("/api/codex/audit-log?limit=99999")
    assert resp.status_code == 200
    # Just assert it returns successfully with the single row (clamp doesn't error).
    assert len(resp.json()["items"]) == 1


def test_api_empty_result_and_invalid_cursor(client):
    resp = client.get("/api/codex/audit-log?issue_id=does-not-exist")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["next_cursor"] is None

    _seed_via_bootstrap_sync_store([_row(1)])
    # Garbage cursor degrades to page 1 rather than erroring.
    resp2 = client.get("/api/codex/audit-log?cursor=not-a-valid-base64-cursor!!!")
    assert resp2.status_code == 200
    assert len(resp2.json()["items"]) == 1


def test_api_q_injection_safe(client):
    _seed_via_bootstrap_sync_store([_row(1), _row(2)])
    for malicious in ["%", "'", "' OR '1'='1", "%25", "_;--"]:
        resp = client.get("/api/codex/audit-log", params={"q": malicious})
        assert resp.status_code == 200
        assert isinstance(resp.json()["items"], list)

    # Table still intact: an unfiltered read returns the two seeded rows.
    resp = client.get("/api/codex/audit-log")
    assert len(resp.json()["items"]) == 2


def test_api_503_when_store_unavailable(client, monkeypatch):
    from app.interfaces import api as api_module

    monkeypatch.setattr(api_module, "codex_store", None)
    resp = client.get("/api/codex/audit-log")
    assert resp.status_code == 503
    assert "not available" in resp.json()["detail"]


def test_agent_timeline_filters_status_events_and_projects_business_nodes(client):
    _seed_task_for_api(
        CodexTask(
            id="task-timeline",
            session_id="workspace-1",
            issue_id=None,
            project_id="project-1",
            title="Generate Startup Scripts",
            prompt="Generate startup scripts",
            role="operations_engineer",
            task_kind="project_script_suggestion",
            last_execution_process_id="ep-1",
            trace_id="ep-1",
            span_id="task-timeline",
        )
    )
    cli_row = _row(
        101,
        category="cli_spawn",
        issue_id=None,
        task_id="task-timeline",
        actor="claude",
        payload_json=(
            '{"argv":["claude","-p","<prompt redacted>"],'
            '"cwd":"/repo","workspace_id":"workspace-1",'
            '"execution_process_id":"ep-1","executor":"claude",'
            '"provider":"anthropic","model":"MiniMax-M3","pid":58816}'
        ),
        created_at=datetime(2026, 7, 8, 10, 52, 31),
    )
    cli_row.execution_process_id = "ep-1"
    cli_row.correlation_id = "ep-1"
    cli_row.trace_id = "ep-1"
    cli_row.span_id = "task-timeline"
    status_row = _row(
        102,
        category="event",
        issue_id=None,
        task_id="task-timeline",
        actor="task_status",
        payload_json=(
            '{"type":"task_status","task_id":"task-timeline",'
            '"project_id":"project-1","workspace_id":"workspace-1",'
            '"role":"operations_engineer",'
            '"task_kind":"project_script_suggestion",'
            '"status":"done","execution_process_id":"ep-1",'
            '"trace_id":"ep-1","span_id":"task-timeline"}'
        ),
        created_at=datetime(2026, 7, 8, 10, 55, 55),
    )
    status_row.execution_process_id = "ep-1"
    status_row.correlation_id = "ep-1"
    status_row.trace_id = "ep-1"
    status_row.span_id = "task-timeline"
    status_row.status = "done"
    script_row = _row(
        103,
        category="event",
        issue_id=None,
        task_id="task-timeline",
        actor="project_script_updated",
        payload_json=(
            '{"type":"project_script_updated","project_id":"project-1",'
            '"session_id":"workspace-1","task_id":"task-timeline",'
            '"setup_script":"npm install",'
            '"run_command":"npm run dev"}'
        ),
        created_at=datetime(2026, 7, 8, 10, 55, 56),
    )
    script_row.status = "ok"
    _seed_via_bootstrap_sync_store([cli_row, status_row, script_row])

    resp = client.get("/api/codex/agent-timeline?task_id=task-timeline")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["next_cursor"] is None
    assert len(body["items"]) == 1
    operation = body["items"][0]
    assert operation["title"] == "Generate Startup Scripts"
    assert operation["timeline_kind"] == "agent_execution"
    assert operation["event_type"] is None
    assert operation["execution_process_id"] == "ep-1"
    assert operation["trace_id"] == "ep-1"
    assert operation["span_id"] == "task-timeline"
    assert operation["status"] == "done"
    assert operation["status_source"] == "task_status"
    assert operation["result"]["run_command"] == "npm run dev"
    assert operation["summary"] == "run_command: npm run dev"
    assert operation["entry_count"] == 2
    assert [entry["actor"] for entry in operation["entries"]] == ["claude", "project_script_updated"]
    event_types = [entry["actor"] for item in body["items"] for entry in item["entries"]]
    assert "task_status" not in event_types

    trace_resp = client.get("/api/codex/audit-log/audit-0103/trace")
    assert trace_resp.status_code == 200, trace_resp.text
    trace_body = trace_resp.json()
    assert trace_body["kind"] == "project_script_updated"
    assert trace_body["metadata"]["source"] == "audit_log"
    assert trace_body["response"]["run_command"] == "npm run dev"


def test_sync_store_log_events_preserve_parent_span_id(tmp_path):
    store = SQLiteStore(tmp_path / "console.db")
    store._init_db()
    store.append_log_event(
        LogEvent(
            id="log-1",
            session_id="workspace-1",
            stream="stdout",
            content="hello",
            task_id="task-1",
            execution_process_id="ep-1",
            trace_id="ep-1",
            span_id="task-1",
            parent_span_id="parent-1",
            created_at=datetime(2026, 7, 8, 11, 0, 0),
        )
    )

    rows = store.load_log_events("workspace-1", task_id="task-1", reverse=False)

    assert len(rows) == 1
    assert rows[0].trace_id == "ep-1"
    assert rows[0].span_id == "task-1"
    assert rows[0].parent_span_id == "parent-1"


def test_agent_timeline_does_not_apply_task_status_across_execution_boundaries(client):
    _seed_task_for_api(
        CodexTask(
            id="task-boundary",
            session_id="workspace-1",
            issue_id=None,
            project_id="project-1",
            title="Generate Startup Scripts",
            prompt="Generate startup scripts",
            role="operations_engineer",
            task_kind="project_script_suggestion",
            last_execution_process_id="ep-current",
            trace_id="ep-current",
            span_id="task-boundary",
        )
    )
    cli_row = _row(
        201,
        category="cli_spawn",
        issue_id=None,
        task_id="task-boundary",
        actor="claude",
        payload_json=(
            '{"cwd":"/repo","workspace_id":"workspace-1",'
            '"execution_process_id":"ep-current","executor":"claude",'
            '"provider":"anthropic","model":"MiniMax-M3"}'
        ),
        created_at=datetime(2026, 7, 8, 11, 0, 0),
    )
    cli_row.execution_process_id = "ep-current"
    cli_row.correlation_id = "ep-current"
    cli_row.trace_id = "ep-current"
    cli_row.span_id = "task-boundary"
    cli_row.status = "ok"
    old_status_row = _row(
        202,
        category="event",
        issue_id=None,
        task_id="task-boundary",
        actor="task_status",
        payload_json=(
            '{"type":"task_status","task_id":"task-boundary",'
            '"status":"failed"}'
        ),
        created_at=datetime(2026, 7, 8, 11, 1, 0),
    )
    old_status_row.status = "failed"
    _seed_via_bootstrap_sync_store([cli_row, old_status_row])

    resp = client.get("/api/codex/agent-timeline?task_id=task-boundary")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["execution_process_id"] == "ep-current"
    assert body["items"][0]["status"] == "ok"
    assert body["items"][0]["status_source"] == "audit_row"
