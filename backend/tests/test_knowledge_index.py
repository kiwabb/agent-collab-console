"""Tests for FTS5-backed knowledge index + RRF hybrid search."""
from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.application import knowledge_index_service as kidx
from app.domain.models import CodexIssue


def _make_issue(*, id: str, title: str, description: str, project_id: str = "proj-1") -> CodexIssue:
    now = datetime.now()
    return CodexIssue(
        id=id,
        session_id="ws-1",
        project_id=project_id,
        title=title,
        description=description,
        current_phase="requirements",
        status="open",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
async def store():
    with tempfile.TemporaryDirectory() as td:
        s = AsyncSQLiteStore(Path(td) / "test.db")
        await s._init_db()
        yield s
        try:
            conn = await s._get_conn()
            await conn.close()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_index_and_search_issue_by_title(store):
    issue = _make_issue(id="i1", title="Add /api/echo endpoint", description="Return body")
    await store.save_codex_issue(issue)  # save_codex_issue now also indexes
    out = await kidx.search(store, "echo", scope="issues", mode="fts")
    assert any(r["issue_id"] == "i1" for r in out["issues"])


@pytest.mark.asyncio
async def test_search_artifact_content(store, tmp_path):
    issue = _make_issue(id="i2", title="Refactor", description="-")
    await store.save_codex_issue(issue)
    p = tmp_path / "prd.md"
    p.write_text("# PRD\nWe will refactor the websocket reconnection logic.", encoding="utf-8")
    artifact = {
        "id": "i2:prd.md",
        "issue_id": "i2",
        "task_id": "t1",
        "name": "prd.md",
        "path": str(p),
        "kind": "pm",
        "created_at": datetime.now().isoformat(),
    }
    await kidx.index_artifact(store, artifact)
    out = await kidx.search(store, "reconnection", scope="artifacts", mode="fts")
    assert any(r["artifact_id"] == "i2:prd.md" for r in out["artifacts"])
    # Snippet should contain the marked hit
    matches = [r for r in out["artifacts"] if r["artifact_id"] == "i2:prd.md"]
    assert "<mark>" in (matches[0]["snippet"] or "")


@pytest.mark.asyncio
async def test_search_snippet_escapes_indexed_html_but_keeps_mark_tags(store, tmp_path):
    issue = _make_issue(id="xss-issue", title="Security", description="-")
    await store.save_codex_issue(issue)
    p = tmp_path / "xss.md"
    p.write_text('<img src=x onerror=alert(1)> vulnerable-token', encoding="utf-8")
    await kidx.index_artifact(
        store,
        {
            "id": "xss-artifact",
            "issue_id": issue.id,
            "task_id": "t",
            "name": "xss.md",
            "path": str(p),
            "kind": "pm",
            "created_at": datetime.now().isoformat(),
        },
    )

    out = await kidx.search(store, "vulnerable-token", scope="artifacts", mode="fts")
    hit = next(r for r in out["artifacts"] if r["artifact_id"] == "xss-artifact")
    snippet = hit["snippet"]
    assert "<mark>vulnerable-token</mark>" in snippet
    assert "<img" not in snippet
    assert "onerror" in snippet
    assert "&lt;img" in snippet


@pytest.mark.asyncio
async def test_search_scope_all_combines(store, tmp_path):
    issue = _make_issue(id="i3", title="Tarantula deploy", description="-")
    await store.save_codex_issue(issue)
    p = tmp_path / "design.md"
    p.write_text("Tarantula traffic should be queued.", encoding="utf-8")
    await kidx.index_artifact(
        store,
        {
            "id": "i3:design.md",
            "issue_id": "i3",
            "task_id": "t",
            "name": "design.md",
            "path": str(p),
            "kind": "architect",
            "created_at": datetime.now().isoformat(),
        },
    )
    out = await kidx.search(store, "tarantula", scope="all", mode="fts")
    assert out["issues"]
    assert out["artifacts"]


@pytest.mark.asyncio
async def test_delete_artifact_index_removes_from_search(store, tmp_path):
    p = tmp_path / "x.md"
    p.write_text("unique-token-zzz", encoding="utf-8")
    await kidx.index_artifact(
        store,
        {
            "id": "a-del",
            "issue_id": "i-x",
            "task_id": "t",
            "name": "x.md",
            "path": str(p),
            "kind": "pm",
            "created_at": datetime.now().isoformat(),
        },
    )
    out = await kidx.search(store, "unique-token-zzz", scope="artifacts", mode="fts")
    assert any(r["artifact_id"] == "a-del" for r in out["artifacts"])
    await kidx.delete_artifact_index(store, "a-del")
    out2 = await kidx.search(store, "unique-token-zzz", scope="artifacts", mode="fts")
    assert not any(r["artifact_id"] == "a-del" for r in out2["artifacts"])


@pytest.mark.asyncio
async def test_find_similar_issues_fts_fallback(store):
    a = _make_issue(id="ia", title="Add login OAuth", description="google + github")
    b = _make_issue(id="ib", title="Login OAuth provider expansion", description="add gitlab")
    c = _make_issue(id="ic", title="Unrelated thing", description="zzz")
    for issue in (a, b, c):
        await store.save_codex_issue(issue)
    sims = await kidx.find_similar_issues(store, "ia", k=2)
    ids = [s["issue_id"] for s in sims]
    assert "ib" in ids
    assert "ia" not in ids


@pytest.mark.asyncio
async def test_search_returns_empty_for_empty_query(store):
    out = await kidx.search(store, "   ", scope="all", mode="fts")
    assert out["issues"] == []
    assert out["artifacts"] == []


@pytest.mark.asyncio
async def test_reindex_walks_existing_issues(store, tmp_path):
    a = _make_issue(id="rk-1", title="Bake the cake", description="-")
    await store.save_codex_issue(a)
    # First delete the FTS row to simulate "missing index"
    conn = await store._get_conn()
    await conn.execute("DELETE FROM issues_fts WHERE issue_id = ?", (a.id,))
    await conn.commit()
    # Reindex
    stats = await kidx.reindex_all(store)
    assert stats["indexed_issues"] >= 1
    out = await kidx.search(store, "cake", scope="issues", mode="fts")
    assert any(r["issue_id"] == a.id for r in out["issues"])


def test_rrf_merge_ranks_overlap_first():
    a = [{"issue_id": "x", "source": "fts"}, {"issue_id": "y", "source": "fts"}]
    b = [{"issue_id": "y", "source": "semantic"}, {"issue_id": "z", "source": "semantic"}]
    merged = kidx._merge_rrf(a, b, limit=10)
    # 'y' appears in both — it should rank ahead of 'x' and 'z'.
    assert merged[0]["issue_id"] == "y"
    assert {m["issue_id"] for m in merged} == {"x", "y", "z"}


def test_pack_unpack_vector_roundtrip():
    v = [0.1, -0.5, 3.14159, 1e-3]
    blob = kidx.pack_vector(v)
    out = kidx.unpack_vector(blob)
    assert len(out) == len(v)
    for a, b in zip(v, out):
        assert abs(a - b) < 1e-5


def test_cosine_basic():
    assert kidx.cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert kidx.cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert kidx.cosine([], []) == 0.0
    assert kidx.cosine([0.0, 0.0], [1.0, 1.0]) == 0.0
