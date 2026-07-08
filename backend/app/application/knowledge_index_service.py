from __future__ import annotations

"""Cross-issue knowledge index: FTS5 + optional semantic embeddings.

Indexes:
  - issues_fts(title, description) — keyed by issue_id
  - artifacts_fts(role, name, content) — keyed by artifact_id (artifact_paths.id)
  - issue_embeddings(issue_id, vector BLOB)
  - artifact_embeddings(artifact_id, vector BLOB)

Public API:
  await index_issue(store, issue)
  await index_artifact(store, artifact_row)
  await delete_artifact_index(store, artifact_id)
  await search(store, query, scope, project_id, mode, limit)
  await find_similar_issues(store, issue_id, k)
  await reindex_all(store, project_id=None)

Failure model:
  - FTS writes must succeed (in main txn).
  - Embedding writes are best-effort: caller wraps in asyncio.create_task.
  - Search is robust to missing tables: returns empty results.
"""
import html  # noqa: E402
import logging  # noqa: E402
import math  # noqa: E402
import struct  # noqa: E402
from collections.abc import Mapping, Sequence  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Literal, Protocol, TypedDict, runtime_checkable  # noqa: E402

from app.json_safety import parse_json_value  # noqa: E402

logger = logging.getLogger(__name__)

CONTENT_BYTES_CAP = 16_000
SNIPPET_MAX_TOKENS = 24
FTS_SNIPPET_ELLIPSIS = "…"
MARK_OPEN_SENTINEL = "\u0000KIDX_MARK_OPEN\u0000"
MARK_CLOSE_SENTINEL = "\u0000KIDX_MARK_CLOSE\u0000"
_JSON_PARSE_FAILED = object()

SearchMode = Literal["fts", "semantic", "hybrid"]
SearchScope = Literal["issues", "artifacts", "all"]
SearchHit = dict[str, object]


class SearchResponse(TypedDict):
    issues: list[SearchHit]
    artifacts: list[SearchHit]
    mode: SearchMode
    query: str


class ReindexStats(TypedDict):
    indexed_issues: int
    indexed_artifacts: int
    embedded_issues: int
    embedded_artifacts: int


class ArtifactRow(TypedDict, total=False):
    id: object
    issue_id: object
    task_id: object
    name: object
    path: object
    kind: object
    created_at: object


class DbCursor(Protocol):
    async def fetchone(self) -> Sequence[object] | None: ...

    async def fetchall(self) -> list[Sequence[object]]: ...


class DbConnection(Protocol):
    async def execute(
        self, sql: str, parameters: Sequence[object] = ()
    ) -> DbCursor: ...

    async def commit(self) -> None: ...


@runtime_checkable
class IssueLike(Protocol):
    id: object
    project_id: object
    title: object
    description: object


IssueInput = Mapping[str, object] | IssueLike


class KnowledgeStore(Protocol):
    async def _get_conn(self) -> DbConnection: ...

    async def list_codex_issues(
        self, session_id: str | None = None, project_id: str | None = None
    ) -> list[IssueInput]: ...

    async def list_artifacts(self, issue_id: str) -> list[ArtifactRow]: ...


class EmbeddingService(Protocol):
    enabled: bool
    model_label: str

    async def embed_one(self, text: str) -> list[float] | None: ...


# ---------------------------------------------------------------------------
# Vector helpers (float32 little-endian BLOB)
# ---------------------------------------------------------------------------


def pack_vector(vec: Sequence[float]) -> bytes:
    floats = [float(x) for x in vec]
    return struct.pack(f"<{len(floats)}f", *floats)


def unpack_vector(blob: bytes) -> list[float]:
    if not blob:
        return []
    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob[: count * 4]))


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):  # noqa: B905
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _truncate_bytes(text: str, cap: int = CONTENT_BYTES_CAP) -> str:
    if not text:
        return ""
    data = text.encode("utf-8")
    if len(data) <= cap:
        return text
    return data[:cap].decode("utf-8", errors="ignore")


def _read_artifact_text(path_str: str | None) -> str:
    if not path_str:
        return ""
    try:
        p = Path(path_str)
    except (TypeError, ValueError):
        return ""
    if not p.exists() or not p.is_file():
        return ""
    try:
        raw = p.read_bytes()
    except OSError:
        return ""
    # Skip likely binary blobs (heuristic: NUL byte in first 4KB).
    if b"\x00" in raw[:4096]:
        return ""
    text = raw.decode("utf-8", errors="ignore")
    # If JSON, flatten to text for better FTS tokenization.
    if p.suffix.lower() == ".json":
        obj = parse_json_value(text, default=_JSON_PARSE_FAILED)
        if obj is _JSON_PARSE_FAILED:
            logger.debug("knowledge index json flatten failed: path=%s", p)
        else:
            text = _json_to_text(obj)
    return _truncate_bytes(text)


def _json_to_text(obj: object, depth: int = 0) -> str:
    if depth > 6:
        return ""
    if obj is None or isinstance(obj, bool):
        return ""
    if isinstance(obj, (int, float)):
        return str(obj)
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return "\n".join(_json_to_text(x, depth + 1) for x in obj if x is not None)
    if isinstance(obj, Mapping):
        parts: list[str] = []
        for k, v in obj.items():
            piece = _json_to_text(v, depth + 1)
            if piece:
                parts.append(f"{k}: {piece}")
        return "\n".join(parts)
    return str(obj)


def _escape_fts_query(q: str) -> str:
    """FTS5 MATCH expects a specific grammar. We quote each whitespace-split
    token and OR them together, so user-typed strings can't blow up.
    """
    if not q:
        return ""
    tokens = [t for t in q.replace('"', " ").split() if t]
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"' for t in tokens)


def _sanitize_fts_snippet(snippet: str | None) -> str:
    """Escape indexed content while preserving FTS-generated mark tags."""
    if not snippet:
        return ""
    protected = snippet.replace("<mark>", MARK_OPEN_SENTINEL).replace(
        "</mark>", MARK_CLOSE_SENTINEL
    )
    escaped = html.escape(protected, quote=True)
    return escaped.replace(MARK_OPEN_SENTINEL, "<mark>").replace(MARK_CLOSE_SENTINEL, "</mark>")


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------


async def index_issue(store: KnowledgeStore, issue: IssueInput) -> None:
    """Upsert an issue row into issues_fts.

    `issue` can be a CodexIssue domain object or a dict.
    """
    issue_id = _issue_str(issue, "id")
    if not issue_id:
        return
    project_id = _issue_str(issue, "project_id")
    title = _issue_str(issue, "title")
    description = _issue_str(issue, "description")
    try:
        conn = await store._get_conn()
        await conn.execute("DELETE FROM issues_fts WHERE issue_id = ?", (issue_id,))
        await conn.execute(
            "INSERT INTO issues_fts (issue_id, project_id, title, description) VALUES (?, ?, ?, ?)",
            (issue_id, project_id, title, _truncate_bytes(description)),
        )
        await conn.commit()
    except Exception as exc:  # noqa: BLE001, RUF100
        logger.debug("knowledge_index.index_issue failed for %s: %s", issue_id, exc)


async def index_artifact(store: KnowledgeStore, artifact_row: ArtifactRow) -> None:
    """Upsert an artifact_paths row into artifacts_fts.

    The on-disk file is read; large/binary files are skipped or truncated.
    """
    artifact_id = _artifact_str(artifact_row, "id")
    if not artifact_id:
        return
    role = _derive_role(artifact_row)
    name = _artifact_str(artifact_row, "name")
    path_str = _artifact_str(artifact_row, "path")
    issue_id = _artifact_str(artifact_row, "issue_id")
    project_id = await _lookup_project_id(store, issue_id)
    content = _read_artifact_text(path_str)
    try:
        conn = await store._get_conn()
        await conn.execute("DELETE FROM artifacts_fts WHERE artifact_id = ?", (artifact_id,))
        await conn.execute(
            "INSERT INTO artifacts_fts (artifact_id, issue_id, project_id, role, name, content) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (artifact_id, issue_id, project_id or "", role, name, content),
        )
        await conn.commit()
    except Exception as exc:  # noqa: BLE001, RUF100
        logger.debug("knowledge_index.index_artifact failed for %s: %s", artifact_id, exc)


async def delete_artifact_index(store: KnowledgeStore, artifact_id: str) -> None:
    try:
        conn = await store._get_conn()
        await conn.execute("DELETE FROM artifacts_fts WHERE artifact_id = ?", (artifact_id,))
        await conn.execute("DELETE FROM artifact_embeddings WHERE artifact_id = ?", (artifact_id,))
        await conn.commit()
    except Exception as exc:  # noqa: BLE001, RUF100
        logger.debug("knowledge_index.delete_artifact_index failed for %s: %s", artifact_id, exc)


async def store_issue_embedding(
    store: KnowledgeStore, issue_id: str, vector: list[float], model: str
) -> None:
    if not issue_id or not vector:
        return
    try:
        conn = await store._get_conn()
        await conn.execute(
            "INSERT OR REPLACE INTO issue_embeddings (issue_id, vector, model, dim, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                issue_id,
                pack_vector(vector),
                model,
                len(vector),
                datetime.now(timezone.utc).isoformat(),  # noqa: UP017
            ),  # noqa: RUF100, UP017
        )
        await conn.commit()
    except Exception as exc:  # noqa: BLE001, RUF100
        logger.debug("knowledge_index.store_issue_embedding failed: %s", exc)


async def store_artifact_embedding(
    store: KnowledgeStore, artifact_id: str, vector: list[float], model: str
) -> None:
    if not artifact_id or not vector:
        return
    try:
        conn = await store._get_conn()
        await conn.execute(
            "INSERT OR REPLACE INTO artifact_embeddings (artifact_id, vector, model, dim, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                artifact_id,
                pack_vector(vector),
                model,
                len(vector),
                datetime.now(timezone.utc).isoformat(),  # noqa: UP017
            ),  # noqa: RUF100, UP017
        )
        await conn.commit()
    except Exception as exc:  # noqa: BLE001, RUF100
        logger.debug("knowledge_index.store_artifact_embedding failed: %s", exc)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


async def search(
    store: KnowledgeStore,
    query: str,
    scope: SearchScope = "all",
    project_id: str | None = None,
    mode: SearchMode = "hybrid",
    limit: int = 20,
    embedding_service: EmbeddingService | None = None,
) -> SearchResponse:
    """Run a knowledge search.

    Returns: { "issues": [...], "artifacts": [...], "mode": <effective>, "query": <str> }
    """
    query = (query or "").strip()
    if not query:
        return {"issues": [], "artifacts": [], "mode": mode, "query": ""}

    fts_issues: list[SearchHit] = []
    fts_artifacts: list[SearchHit] = []
    if mode in ("fts", "hybrid") or mode == "semantic" and embedding_service is None:  # noqa: RUF021
        if scope in ("issues", "all"):
            fts_issues = await _fts_search_issues(store, query, project_id, limit)
        if scope in ("artifacts", "all"):
            fts_artifacts = await _fts_search_artifacts(store, query, project_id, limit)

    sem_issues: list[SearchHit] = []
    sem_artifacts: list[SearchHit] = []
    effective_mode = mode
    if (
        mode in ("semantic", "hybrid")
        and embedding_service is not None
        and embedding_service.enabled
    ):
        try:
            qvec = await embedding_service.embed_one(query)
        except Exception as exc:  # noqa: BLE001, RUF100
            logger.info("knowledge_index.search semantic embed failed: %s — falling back", exc)
            qvec = None
        if qvec:
            if scope in ("issues", "all"):
                sem_issues = await _semantic_search_issues(store, qvec, project_id, limit)
            if scope in ("artifacts", "all"):
                sem_artifacts = await _semantic_search_artifacts(store, qvec, project_id, limit)
        else:
            effective_mode = "fts"
    elif mode == "semantic" and (embedding_service is None or not embedding_service.enabled):
        effective_mode = "fts"  # graceful downgrade

    # Merge
    issues = (
        _merge_rrf(fts_issues, sem_issues, limit)
        if mode == "hybrid"
        else (sem_issues if mode == "semantic" and sem_issues else fts_issues)
    )
    artifacts = (
        _merge_rrf(fts_artifacts, sem_artifacts, limit)
        if mode == "hybrid"
        else (sem_artifacts if mode == "semantic" and sem_artifacts else fts_artifacts)
    )
    return {
        "issues": issues,
        "artifacts": artifacts,
        "mode": effective_mode,
        "query": query,
    }


async def find_similar_issues(
    store: KnowledgeStore,
    issue_id: str,
    k: int = 5,
    embedding_service: EmbeddingService | None = None,
) -> list[SearchHit]:
    """Find issues similar to `issue_id`.

    Strategy:
      1) If embedding for this issue exists, do cosine vs all peers.
      2) Else fall back to FTS using the issue's title as the query.
    """
    if k <= 0:
        return []

    # Semantic path
    if embedding_service is not None and embedding_service.enabled:
        anchor = await _load_issue_embedding(store, issue_id)
        if anchor is not None:
            return await _semantic_similar_issues(store, issue_id, anchor, k)

    # FTS fallback: use title as the query
    try:
        conn = await store._get_conn()
        cur = await conn.execute(
            "SELECT title, description, project_id FROM codex_issues WHERE id = ?", (issue_id,)
        )
        row = await cur.fetchone()
    except Exception:  # noqa: BLE001, RUF100
        return []
    if not row:
        return []
    title = _row_text(row[0]) or ""
    description = _row_text(row[1]) or ""
    project_id = _row_text(row[2])
    bag = " ".join((title.split() + description.split()[:30])[:30])
    if not bag.strip():
        return []
    hits = await _fts_search_issues(store, bag, project_id, k + 1)
    return [h for h in hits if h.get("issue_id") != issue_id][:k]


# ---------------------------------------------------------------------------
# Reindex (admin / migration)
# ---------------------------------------------------------------------------


async def reindex_all(
    store: KnowledgeStore,
    project_id: str | None = None,
    embedding_service: EmbeddingService | None = None,
) -> ReindexStats:
    """Walk codex_issues + artifact_paths and (re)index everything.

    Embeddings are scheduled but not awaited.
    """
    indexed_issues = 0
    indexed_artifacts = 0
    embedded_issues = 0
    embedded_artifacts = 0

    try:
        issues = await store.list_codex_issues(None, project_id)
    except Exception:  # noqa: BLE001, RUF100
        issues = []
    for issue in issues or []:
        await index_issue(store, issue)
        indexed_issues += 1
        if embedding_service is not None and embedding_service.enabled:
            title = _issue_str(issue, "title")
            desc = _issue_str(issue, "description")
            text = f"{title}\n\n{desc}".strip()
            if text:
                try:
                    vec = await embedding_service.embed_one(text)
                    if vec:
                        await store_issue_embedding(
                            store, _issue_str(issue, "id"), vec, embedding_service.model_label
                        )
                        embedded_issues += 1
                except Exception as exc:  # noqa: BLE001, RUF100
                    logger.debug("reindex issue embed failed: %s", exc)

    # Artifacts — pull via per-issue list to reuse existing helper
    for issue in issues or []:
        issue_id = _issue_str(issue, "id")
        if not issue_id:
            continue
        try:
            arts = await store.list_artifacts(issue_id)
        except Exception:  # noqa: BLE001, RUF100
            arts = []
        for art in arts:
            await index_artifact(store, art)
            indexed_artifacts += 1
            if embedding_service is not None and embedding_service.enabled:
                text = _read_artifact_text(_artifact_str(art, "path"))
                if text:
                    try:
                        vec = await embedding_service.embed_one(text[:8000])
                        if vec:
                            await store_artifact_embedding(
                                store,
                                _artifact_str(art, "id"),
                                vec,
                                embedding_service.model_label,
                            )
                            embedded_artifacts += 1
                    except Exception as exc:  # noqa: BLE001, RUF100
                        logger.debug("reindex artifact embed failed: %s", exc)

    return {
        "indexed_issues": indexed_issues,
        "indexed_artifacts": indexed_artifacts,
        "embedded_issues": embedded_issues,
        "embedded_artifacts": embedded_artifacts,
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _issue_value(issue: IssueInput, name: str) -> object | None:
    if isinstance(issue, Mapping):
        return issue.get(name)
    if name == "id":
        return issue.id
    if name == "project_id":
        return issue.project_id
    if name == "title":
        return issue.title
    if name == "description":
        return issue.description
    return None


def _issue_str(issue: IssueInput, name: str) -> str:
    value = _issue_value(issue, name)
    return value if isinstance(value, str) else ""


def _artifact_str(artifact_row: Mapping[str, object], name: str) -> str:
    value = artifact_row.get(name)
    return value if isinstance(value, str) else ""


def _score(hit: Mapping[str, object], field: str = "score") -> float:
    value = hit.get(field)
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _row_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _row_score(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _row_vector(value: object) -> list[float]:
    return unpack_vector(value) if isinstance(value, bytes) else []


def _derive_role(artifact_row: Mapping[str, object]) -> str:
    name = _artifact_str(artifact_row, "name").lower()
    path = _artifact_str(artifact_row, "path").lower()
    for role in ("pm", "architect", "engineer", "qa"):
        if (
            f"/{role}/" in path
            or path.endswith(f"/{role}")
            or name.startswith(f"{role}_")
            or f"/{role}/" in name
        ):
            return role
    # fall back to artifact kind if present
    kind = _artifact_str(artifact_row, "kind").lower()
    if kind in ("pm", "architect", "engineer", "qa"):
        return kind
    return ""


async def _lookup_project_id(store: KnowledgeStore, issue_id: str) -> str | None:
    if not issue_id:
        return None
    try:
        conn = await store._get_conn()
        cur = await conn.execute("SELECT project_id FROM codex_issues WHERE id = ?", (issue_id,))
        row = await cur.fetchone()
    except Exception:  # noqa: BLE001, RUF100
        return None
    if not row:
        return None
    value = row[0]
    return str(value) if value is not None else None


async def _fts_search_issues(
    store: KnowledgeStore, query: str, project_id: str | None, limit: int
) -> list[SearchHit]:
    match = _escape_fts_query(query)
    if not match:
        return []
    sql = (
        "SELECT issue_id, project_id, title, "
        "snippet(issues_fts, 3, '<mark>', '</mark>', ?, ?) AS snippet, "
        "bm25(issues_fts) AS score "
        "FROM issues_fts WHERE issues_fts MATCH ?"
    )
    params: list[object] = [FTS_SNIPPET_ELLIPSIS, SNIPPET_MAX_TOKENS, match]
    if project_id:
        sql += " AND project_id = ?"
        params.append(project_id)
    sql += " ORDER BY score LIMIT ?"
    params.append(limit)
    try:
        conn = await store._get_conn()
        cur = await conn.execute(sql, params)
        rows = await cur.fetchall()
    except Exception as exc:  # noqa: BLE001, RUF100
        logger.debug("knowledge_index._fts_search_issues failed: %s", exc)
        return []
    out: list[SearchHit] = []
    for r in rows:
        out.append(
            {
                "kind": "issue",
                "issue_id": r[0],
                "project_id": r[1],
                "title": r[2],
                "snippet": _sanitize_fts_snippet(_row_text(r[3])),
                "score": _row_score(r[4]),
                "source": "fts",
            }
        )
    return out


async def _fts_search_artifacts(
    store: KnowledgeStore, query: str, project_id: str | None, limit: int
) -> list[SearchHit]:
    match = _escape_fts_query(query)
    if not match:
        return []
    sql = (
        "SELECT artifact_id, issue_id, project_id, role, name, "
        "snippet(artifacts_fts, 5, '<mark>', '</mark>', ?, ?) AS snippet, "
        "bm25(artifacts_fts) AS score "
        "FROM artifacts_fts WHERE artifacts_fts MATCH ?"
    )
    params: list[object] = [FTS_SNIPPET_ELLIPSIS, SNIPPET_MAX_TOKENS, match]
    if project_id:
        sql += " AND project_id = ?"
        params.append(project_id)
    sql += " ORDER BY score LIMIT ?"
    params.append(limit)
    try:
        conn = await store._get_conn()
        cur = await conn.execute(sql, params)
        rows = await cur.fetchall()
    except Exception as exc:  # noqa: BLE001, RUF100
        logger.debug("knowledge_index._fts_search_artifacts failed: %s", exc)
        return []
    out: list[SearchHit] = []
    for r in rows:
        out.append(
            {
                "kind": "artifact",
                "artifact_id": r[0],
                "issue_id": r[1],
                "project_id": r[2],
                "role": r[3],
                "name": r[4],
                "snippet": _sanitize_fts_snippet(_row_text(r[5])),
                "score": _row_score(r[6]),
                "source": "fts",
            }
        )
    return out


async def _semantic_search_issues(
    store: KnowledgeStore, qvec: list[float], project_id: str | None, limit: int
) -> list[SearchHit]:
    sql = (
        "SELECT e.issue_id, e.vector, i.title, i.project_id "
        "FROM issue_embeddings e JOIN codex_issues i ON i.id = e.issue_id"
    )
    params: list[object] = []
    if project_id:
        sql += " WHERE i.project_id = ?"
        params.append(project_id)
    try:
        conn = await store._get_conn()
        cur = await conn.execute(sql, params)
        rows = await cur.fetchall()
    except Exception as exc:  # noqa: BLE001, RUF100
        logger.debug("knowledge_index._semantic_search_issues failed: %s", exc)
        return []
    scored: list[SearchHit] = []
    for r in rows:
        vec = _row_vector(r[1])
        if not vec:
            continue
        score = cosine(qvec, vec)
        scored.append(
            {
                "kind": "issue",
                "issue_id": r[0],
                "project_id": r[3],
                "title": r[2],
                "snippet": "",
                "score": score,
                "source": "semantic",
            }
        )
    scored.sort(key=_score, reverse=True)
    return scored[:limit]


async def _semantic_search_artifacts(
    store: KnowledgeStore, qvec: list[float], project_id: str | None, limit: int
) -> list[SearchHit]:
    sql = (
        "SELECT e.artifact_id, e.vector, ap.issue_id, ap.name, ci.project_id "
        "FROM artifact_embeddings e "
        "JOIN artifact_paths ap ON ap.id = e.artifact_id "
        "LEFT JOIN codex_issues ci ON ci.id = ap.issue_id"
    )
    params: list[object] = []
    if project_id:
        sql += " WHERE ci.project_id = ?"
        params.append(project_id)
    try:
        conn = await store._get_conn()
        cur = await conn.execute(sql, params)
        rows = await cur.fetchall()
    except Exception as exc:  # noqa: BLE001, RUF100
        logger.debug("knowledge_index._semantic_search_artifacts failed: %s", exc)
        return []
    scored: list[SearchHit] = []
    for r in rows:
        vec = _row_vector(r[1])
        if not vec:
            continue
        score = cosine(qvec, vec)
        scored.append(
            {
                "kind": "artifact",
                "artifact_id": r[0],
                "issue_id": r[2],
                "project_id": r[4],
                "role": "",
                "name": r[3],
                "snippet": "",
                "score": score,
                "source": "semantic",
            }
        )
    scored.sort(key=_score, reverse=True)
    return scored[:limit]


async def _load_issue_embedding(store: KnowledgeStore, issue_id: str) -> list[float] | None:
    try:
        conn = await store._get_conn()
        cur = await conn.execute(
            "SELECT vector FROM issue_embeddings WHERE issue_id = ?", (issue_id,)
        )
        row = await cur.fetchone()
    except Exception:  # noqa: BLE001, RUF100
        return None
    if not row:
        return None
    return _row_vector(row[0])


async def _semantic_similar_issues(
    store: KnowledgeStore, self_issue_id: str, anchor: list[float], k: int
) -> list[SearchHit]:
    try:
        conn = await store._get_conn()
        cur = await conn.execute(
            "SELECT e.issue_id, e.vector, i.title, i.project_id "
            "FROM issue_embeddings e JOIN codex_issues i ON i.id = e.issue_id "
            "WHERE e.issue_id != ?",
            (self_issue_id,),
        )
        rows = await cur.fetchall()
    except Exception as exc:  # noqa: BLE001, RUF100
        logger.debug("knowledge_index._semantic_similar_issues failed: %s", exc)
        return []
    out: list[SearchHit] = []
    for r in rows:
        vec = _row_vector(r[1])
        if not vec:
            continue
        score = cosine(anchor, vec)
        out.append(
            {
                "issue_id": r[0],
                "title": r[2],
                "project_id": r[3],
                "score": score,
                "source": "semantic",
            }
        )
    out.sort(key=_score, reverse=True)
    return out[:k]


def _merge_rrf(a: list[SearchHit], b: list[SearchHit], limit: int, k: int = 60) -> list[SearchHit]:
    """Reciprocal rank fusion: score = sum(1 / (k + rank_i)) across lists.

    Keys items by their identity (issue_id or artifact_id).
    """
    bucket: dict[str, SearchHit] = {}
    for lst in (a, b):
        for rank, item in enumerate(lst):
            key_raw = item.get("artifact_id") or item.get("issue_id")
            if not key_raw:
                continue
            key = str(key_raw)
            cur = bucket.get(key)
            rrf = 1.0 / (k + rank + 1)
            if cur is None:
                merged = dict(item)
                merged["rrf"] = rrf
                merged["sources"] = [item.get("source")]
                bucket[key] = merged
            else:
                cur["rrf"] = _score(cur, "rrf") + rrf
                source = item.get("source")
                sources_raw = cur.get("sources")
                sources = list(sources_raw) if isinstance(sources_raw, list) else []
                if source and source not in sources:
                    sources.append(source)
                    cur["sources"] = sources
                # Prefer FTS snippet if we got one.
                if not cur.get("snippet") and item.get("snippet"):
                    cur["snippet"] = item.get("snippet")
    merged_items = list(bucket.values())
    merged_items.sort(key=lambda x: _score(x, "rrf"), reverse=True)
    return merged_items[:limit]
