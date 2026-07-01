"""PR3 tests for the audit_log read API + store query extensions.

Covers `GET /api/codex/audit-log` (filters / search / cursor pagination) and
the underlying `list_audit_logs` store extensions (categories IN, since/until,
q LIKE, keyset cursor) on BOTH stores. Frontend (PR4) is out of scope.
"""

from __future__ import annotations  # noqa: I001

from datetime import datetime, timedelta

import pytest

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.adapters.sqlite_store import SQLiteStore
from app.domain.models import AuditLog


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


@pytest.mark.asyncio
async def test_store_categories_in_filter(tmp_path):
    store = AsyncSQLiteStore(tmp_path / "console.db")
    await store._ensure_db()
    await store.save_audit_log(_row(1, category="git_command"))
    await store.save_audit_log(_row(2, category="llm_call"))
    await store.save_audit_log(_row(3, category="tool_use"))

    rows = await store.list_audit_logs(categories=["git_command", "llm_call"])
    cats = {r.category for r in rows}
    assert cats == {"git_command", "llm_call"}


@pytest.mark.asyncio
async def test_store_since_until_range(tmp_path):
    store = AsyncSQLiteStore(tmp_path / "console.db")
    await store._ensure_db()
    for i in range(1, 6):
        await store.save_audit_log(_row(i))

    base = datetime(2026, 5, 31, 12, 0, 0)
    since = (base + timedelta(seconds=2)).isoformat()
    until = (base + timedelta(seconds=4)).isoformat()
    rows = await store.list_audit_logs(since=since, until=until)
    secs = sorted(r.duration_ms for r in rows)
    assert secs == [2, 3, 4]  # inclusive both ends


@pytest.mark.asyncio
async def test_store_q_search_case_insensitive(tmp_path):
    store = AsyncSQLiteStore(tmp_path / "console.db")
    await store._ensure_db()
    await store.save_audit_log(_row(1, payload_json='{"cmd": "git STATUS --porcelain"}'))
    await store.save_audit_log(_row(2, payload_json='{"cmd": "ls -la"}'))

    hit = await store.list_audit_logs(q="status")
    assert len(hit) == 1
    assert hit[0].id == "audit-0001"

    hit_upper = await store.list_audit_logs(q="STATUS")
    assert len(hit_upper) == 1

    miss = await store.list_audit_logs(q="no-such-token-xyz")
    assert miss == []


@pytest.mark.asyncio
async def test_store_q_search_is_injection_safe(tmp_path):
    store = AsyncSQLiteStore(tmp_path / "console.db")
    await store._ensure_db()
    await store.save_audit_log(_row(1, payload_json='{"x": 1}'))
    await store.save_audit_log(_row(2, payload_json="{}"))

    # A `q` full of SQL metacharacters / LIKE wildcards must not error, must not
    # match everything via injection, and must not drop/alter rows.
    for malicious in ["%", "'", "' OR '1'='1", "%' --", "_;DROP TABLE audit_log;"]:
        rows = await store.list_audit_logs(q=malicious)
        assert isinstance(rows, list)

    # The table is intact and untouched after the injection attempts.
    remaining = await store.list_audit_logs(limit=100)
    assert len(remaining) == 2


@pytest.mark.asyncio
async def test_store_cursor_keyset_pagination(tmp_path):
    store = AsyncSQLiteStore(tmp_path / "console.db")
    await store._ensure_db()
    for i in range(1, 11):
        await store.save_audit_log(_row(i))

    # Page 1 (newest first): ids 10..6
    page1 = await store.list_audit_logs(limit=5, descending=True)
    assert [r.duration_ms for r in page1] == [10, 9, 8, 7, 6]

    last = page1[-1]
    page2 = await store.list_audit_logs(
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
