"""Tests for the team_notes_service (block parsing + soft-delete state)."""
from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.application.team_notes_service import TeamNotesService


SAMPLE_MARKDOWN = """\
<!-- issue:abc-123 -->
## 2026-05-15 10:00 — Add login OAuth
_intent: feature · graph status: done_

**Product goals:**
- Support github + google sign-in

**QA verdict:** `passed`

<!-- issue:def-456 -->
## 2026-05-16 11:00 — Fix websocket flake
_intent: bugfix · graph status: done_

**Bugs / lessons:**
- Reconnect storms when token expires
"""


@pytest.fixture
async def store():
    with tempfile.TemporaryDirectory() as td:
        s = AsyncSQLiteStore(Path(td) / "test.db")
        await s._init_db()
        yield s


@pytest.fixture
def project_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    notes_dir = repo / ".agent-collab"
    notes_dir.mkdir()
    (notes_dir / "team_notes.md").write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    return repo


def test_parse_blocks_returns_two_blocks():
    svc = TeamNotesService()
    blocks = svc.parse_blocks(SAMPLE_MARKDOWN)
    assert len(blocks) == 2
    assert blocks[0].issue_id == "abc-123"
    assert blocks[0].heading == "Add login OAuth"
    assert blocks[0].timestamp == "2026-05-15 10:00"
    assert blocks[1].issue_id == "def-456"
    assert blocks[1].block_id == "issue:def-456"


def test_parse_blocks_empty_returns_empty_list():
    svc = TeamNotesService()
    assert svc.parse_blocks("") == []
    assert svc.parse_blocks("   ") == []


@pytest.mark.asyncio
async def test_soft_delete_and_restore(store, project_repo):
    svc = TeamNotesService()
    blocks = await svc.list_blocks(store, "proj-1", str(project_repo))
    assert len(blocks) == 2

    await svc.soft_delete(store, "proj-1", "issue:abc-123")
    blocks_after = await svc.list_blocks(store, "proj-1", str(project_repo))
    assert {b.block_id for b in blocks_after} == {"issue:def-456"}

    with_deleted = await svc.list_blocks(
        store, "proj-1", str(project_repo), include_deleted=True
    )
    assert len(with_deleted) == 2
    deleted = [b for b in with_deleted if b.block_id == "issue:abc-123"][0]
    assert deleted.deleted_at is not None

    await svc.restore(store, "proj-1", "issue:abc-123")
    after_restore = await svc.list_blocks(store, "proj-1", str(project_repo))
    assert len(after_restore) == 2


@pytest.mark.asyncio
async def test_pin_affects_prompt_order(store, project_repo):
    svc = TeamNotesService()
    # Pin the OLDER block — by default it would sort newer-first, so pinning
    # the older one should push it to the top.
    await svc.set_pinned(store, "proj-1", "issue:abc-123", True)
    rendered = await svc.format_for_prompt(store, "proj-1", str(project_repo))
    assert rendered is not None
    # OAuth (pinned, older) appears before websocket (newer, unpinned)
    oauth_idx = rendered.find("Add login OAuth")
    ws_idx = rendered.find("Fix websocket flake")
    assert oauth_idx != -1 and ws_idx != -1
    assert oauth_idx < ws_idx


@pytest.mark.asyncio
async def test_format_for_prompt_drops_soft_deleted_blocks(store, project_repo):
    svc = TeamNotesService()
    await svc.soft_delete(store, "proj-1", "issue:abc-123")
    rendered = await svc.format_for_prompt(store, "proj-1", str(project_repo))
    assert rendered is not None
    assert "Add login OAuth" not in rendered
    assert "Fix websocket flake" in rendered


@pytest.mark.asyncio
async def test_format_for_prompt_returns_none_when_all_deleted(store, project_repo):
    svc = TeamNotesService()
    await svc.soft_delete(store, "proj-1", "issue:abc-123")
    await svc.soft_delete(store, "proj-1", "issue:def-456")
    rendered = await svc.format_for_prompt(store, "proj-1", str(project_repo))
    assert rendered is None


def test_parse_blocks_handles_distilled_section():
    md = """\
## ⚙️ Distilled lessons (auto-curated)
- Use X over Y

<!-- issue:i1 -->
## 2026-01-01 — Hello
body
"""
    svc = TeamNotesService()
    blocks = svc.parse_blocks(md)
    assert len(blocks) == 2
    assert any(b.distilled for b in blocks)
