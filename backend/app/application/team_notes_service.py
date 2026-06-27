from __future__ import annotations

"""Block-aware view + soft-delete state for team_notes.md.

The markdown file on disk (managed by `ProjectMemoryService`) remains the
source of truth. This service adds:

  * `parse_blocks(md)`        — split file into per-issue blocks.
  * `list_blocks(...)`        — reconcile parsed blocks with soft-delete state.
  * `soft_delete / restore`   — flip the `deleted_at` flag in
                                 `team_notes_state`. The markdown is not
                                 touched, so a human editor can resurrect
                                 anything by just re-saving the file.
  * `pin / unpin`             — pinned blocks bubble to the top of the
                                 TEAM CONTEXT injection.
  * `format_for_prompt(...)`  — what `role_workflow_service` should call
                                 instead of `ProjectMemoryService.read_for_prompt`
                                 (drops soft-deleted blocks, orders pinned-first).

Block IDs are deterministic: prefer the `<!-- issue:<id> -->` marker; if
absent (legacy / hand-written blocks) the SHA-1 of the heading line is used.
"""
import hashlib  # noqa: E402
import logging  # noqa: E402
import re  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Iterable  # noqa: E402, F401, UP035

from app.application.project_memory_service import (  # noqa: E402
    MEMORY_BYTES_CAP,
    MEMORY_DIR_NAME,  # noqa: F401
    MEMORY_FILE_NAME,  # noqa: F401
    ProjectMemoryService,
    project_memory,
)

logger = logging.getLogger(__name__)

ISSUE_MARKER_RE = re.compile(r"<!--\s*issue:([A-Za-z0-9_\-]+)\s*-->")
DISTILLED_HEADER_PREFIX = "## ⚙️ Distilled lessons"
HEADING_DATE_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)\s+[—\-]\s+(.+?)\s*$")


@dataclass
class NoteBlock:
    block_id: str
    issue_id: str | None
    heading: str
    body: str
    timestamp: str | None
    pinned: bool = False
    deleted_at: str | None = None
    distilled: bool = False

    def to_dict(self) -> dict:
        return {
            "block_id": self.block_id,
            "issue_id": self.issue_id,
            "heading": self.heading,
            "body": self.body,
            "timestamp": self.timestamp,
            "pinned": self.pinned,
            "deleted_at": self.deleted_at,
            "distilled": self.distilled,
        }


class TeamNotesService:
    def __init__(self, memory: ProjectMemoryService | None = None) -> None:
        self.memory = memory or project_memory

    # ------------------------------------------------------------------
    # Pure parsing
    # ------------------------------------------------------------------

    def parse_blocks(self, markdown: str) -> list[NoteBlock]:
        if not markdown or not markdown.strip():
            return []
        chunks = self.memory._split_into_blocks(markdown)  # type: ignore[attr-defined]
        out: list[NoteBlock] = []
        for raw in chunks:
            block = self._parse_one(raw)
            if block is None:
                continue
            out.append(block)
        return out

    @staticmethod
    def _parse_one(raw: str) -> NoteBlock | None:
        if not raw.strip():
            return None
        is_distilled = raw.lstrip().startswith(DISTILLED_HEADER_PREFIX)
        # extract issue marker
        m = ISSUE_MARKER_RE.search(raw)
        issue_id = m.group(1) if m else None
        # heading: first line starting with "## "
        heading = ""
        timestamp = None
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                heading = stripped[3:].strip()
                hm = HEADING_DATE_RE.match(stripped)
                if hm:
                    timestamp = hm.group(1)
                    heading = hm.group(2).strip()
                break
        if not heading and is_distilled:
            heading = "Distilled lessons"
        if not heading:
            return None
        block_id = (
            f"issue:{issue_id}"
            if issue_id
            else "h:" + hashlib.sha1(heading.encode("utf-8")).hexdigest()[:16]
        )
        return NoteBlock(
            block_id=block_id,
            issue_id=issue_id,
            heading=heading,
            body=raw,
            timestamp=timestamp,
            distilled=is_distilled,
        )

    # ------------------------------------------------------------------
    # File-system & DB integration
    # ------------------------------------------------------------------

    def memory_path(self, project_repo_path: str | None) -> Path | None:
        return self.memory._memory_path(project_repo_path)  # type: ignore[attr-defined]

    def read_markdown(self, project_repo_path: str | None) -> str:
        path = self.memory_path(project_repo_path)
        if path is None or not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    async def list_blocks(
        self,
        store,
        project_id: str,
        project_repo_path: str | None,
        include_deleted: bool = False,
    ) -> list[NoteBlock]:
        md = self.read_markdown(project_repo_path)
        blocks = self.parse_blocks(md)
        state = await self._load_state(store, project_id)
        for b in blocks:
            st = state.get(b.block_id)
            if st:
                b.pinned = bool(st.get("pinned"))
                b.deleted_at = st.get("deleted_at")
        if not include_deleted:
            blocks = [b for b in blocks if not b.deleted_at]
        return blocks

    async def soft_delete(self, store, project_id: str, block_id: str) -> None:
        await self._upsert_state(
            store,
            project_id,
            block_id,
            deleted_at=datetime.now(timezone.utc).isoformat(),  # noqa: UP017
        )

    async def restore(self, store, project_id: str, block_id: str) -> None:
        await self._upsert_state(store, project_id, block_id, deleted_at=None)

    async def set_pinned(self, store, project_id: str, block_id: str, pinned: bool) -> None:
        await self._upsert_state(store, project_id, block_id, pinned=pinned)

    async def format_for_prompt(
        self,
        store,
        project_id: str | None,
        project_repo_path: str | None,
    ) -> str | None:
        """Drop-in replacement for `ProjectMemoryService.read_for_prompt`.

        Honors soft-deletes + pin order. If project_id is unknown (legacy
        callers), falls back to plain `read_for_prompt`.
        """
        if not project_id:
            text = self.memory.read_for_prompt(project_repo_path)
            return text
        blocks = await self.list_blocks(store, project_id, project_repo_path, include_deleted=False)
        if not blocks:
            return None
        # Sort: pinned (preserve discovery order), then by timestamp desc.
        pinned = [b for b in blocks if b.pinned]
        others = [b for b in blocks if not b.pinned]
        others.sort(key=lambda b: b.timestamp or "", reverse=True)
        ordered: list[NoteBlock] = pinned + others
        rebuilt = "\n\n".join(b.body for b in ordered).strip()
        if not rebuilt:
            return None
        # Reuse the cap from project_memory.
        if len(rebuilt.encode("utf-8")) > MEMORY_BYTES_CAP:
            rebuilt = self.memory._trim_to_cap(rebuilt + "\n")  # type: ignore[attr-defined]
        return rebuilt

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _upsert_state(
        self,
        store,
        project_id: str,
        block_id: str,
        *,
        deleted_at: str | None = ...,
        pinned: bool | None = None,
    ) -> None:
        conn = await store._get_conn()
        # Fetch current row first to preserve un-touched fields.
        cur = await conn.execute(
            "SELECT deleted_at, pinned FROM team_notes_state WHERE project_id = ? AND block_id = ?",
            (project_id, block_id),
        )
        row = await cur.fetchone()
        cur_deleted = row[0] if row else None
        cur_pinned = bool(row[1]) if row else False
        new_deleted = cur_deleted if deleted_at is ... else deleted_at
        new_pinned = cur_pinned if pinned is None else bool(pinned)
        await conn.execute(
            "INSERT OR REPLACE INTO team_notes_state (project_id, block_id, deleted_at, pinned) "
            "VALUES (?, ?, ?, ?)",
            (project_id, block_id, new_deleted, 1 if new_pinned else 0),
        )
        await conn.commit()

    async def _load_state(self, store, project_id: str) -> dict[str, dict]:
        try:
            conn = await store._get_conn()
            cur = await conn.execute(
                "SELECT block_id, deleted_at, pinned FROM team_notes_state WHERE project_id = ?",
                (project_id,),
            )
            rows = await cur.fetchall()
        except Exception as exc:  # noqa: BLE001, RUF100
            logger.debug("team_notes_service._load_state failed: %s", exc)
            return {}
        out: dict[str, dict] = {}
        for r in rows:
            out[r[0]] = {"deleted_at": r[1], "pinned": bool(r[2])}
        return out


# Module-level singleton
team_notes = TeamNotesService()
