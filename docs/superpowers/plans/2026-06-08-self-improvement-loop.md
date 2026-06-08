# Self Improvement Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a review-only self-improvement proposal ledger that captures evidence-backed learning opportunities after issue completion without automatically mutating memory, specs, policy, tooling, or code.

**Architecture:** Add a focused `SelfImprovementProposal` domain row, persist it in both async and sync SQLite stores, extract deterministic proposals in a new application service, and call that service best-effort from the existing Conductor terminal seal after `record_project_memory(...)`. Expose a read-only API for future review inboxes.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2 at the API boundary, dataclasses in `backend/app/domain/models.py`, hand-written SQLite/aiosqlite store methods, pytest with `asyncio_mode=auto`.

---

## File Structure

- `backend/app/domain/models.py`: add the dataclass that represents one proposal ledger row.
- `backend/app/adapters/async_sqlite_store.py`: add runtime table/index creation and async save/list methods.
- `backend/app/adapters/sqlite_store.py`: add sync table/index creation and save/list methods for tests and one-off scripts.
- `backend/app/application/self_improvement_service.py`: add deterministic extraction, evidence normalization, fingerprinting, and best-effort issue completion entrypoint.
- `backend/app/application/conductor_main_loop.py`: call the service from `_seal_graph_and_issue_status` after `record_project_memory(...)`.
- `backend/app/interfaces/api.py`: add the read-only project proposals endpoint.
- `backend/tests/test_self_improvement_store.py`: cover sync/async store parity, filtering, and idempotent duplicate saves.
- `backend/tests/test_self_improvement_service.py`: cover deterministic extraction, no-op clean issues, duplicate extraction, and best-effort failures.
- `backend/tests/test_self_improvement_api.py`: cover API response shape and query filters.
- `backend/tests/test_swarm_integration.py`: extend the existing seal-path test to assert proposal extraction is called without disturbing cleanup behavior.

## Task 1: Store Contract Tests

**Files:**
- Create: `backend/tests/test_self_improvement_store.py`
- Modify later: `backend/app/domain/models.py`
- Modify later: `backend/app/adapters/async_sqlite_store.py`
- Modify later: `backend/app/adapters/sqlite_store.py`

- [ ] **Step 1: Write failing async/sync store tests**

Add this file:

```python
from datetime import datetime

import pytest

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.adapters.sqlite_store import SQLiteStore
from app.domain.models import SelfImprovementProposal


def _proposal(
    proposal_id: str = "proposal-1",
    *,
    project_id: str = "project-1",
    issue_id: str = "issue-1",
    target_kind: str = "runtime_tooling",
    status: str = "proposed",
    fingerprint: str = "project-1|issue-1|runtime_tooling|qa-failure",
) -> SelfImprovementProposal:
    return SelfImprovementProposal(
        id=proposal_id,
        project_id=project_id,
        issue_id=issue_id,
        target_kind=target_kind,
        title="Capture QA command failure contract",
        recommendation="Record a backend contract when QA command execution fails.",
        evidence_json='[{"kind":"qa_report","path":"issues/issue-1/qa.json"}]',
        severity="medium",
        confidence=0.8,
        status=status,
        fingerprint=fingerprint,
        created_at=datetime(2026, 6, 8, 10, 0, 0),
        updated_at=datetime(2026, 6, 8, 10, 0, 0),
    )


@pytest.mark.asyncio
async def test_async_store_saves_lists_filters_and_dedupes(tmp_path):
    store = AsyncSQLiteStore(tmp_path / "console.db")
    await store.save_self_improvement_proposal(_proposal())
    await store.save_self_improvement_proposal(
        _proposal(
            "proposal-2",
            issue_id="issue-2",
            target_kind="code_spec",
            status="accepted",
            fingerprint="project-1|issue-2|code_spec|qa-failure",
        )
    )
    await store.save_self_improvement_proposal(
        _proposal(
            "proposal-1b",
            status="proposed",
            fingerprint="project-1|issue-1|runtime_tooling|qa-failure",
        )
    )

    project_rows = await store.list_self_improvement_proposals(project_id="project-1")
    issue_rows = await store.list_self_improvement_proposals(project_id="project-1", issue_id="issue-1")
    status_rows = await store.list_self_improvement_proposals(project_id="project-1", status="accepted")
    limited_rows = await store.list_self_improvement_proposals(project_id="project-1", limit=1)
    await store.close()

    assert len(project_rows) == 2
    assert len(issue_rows) == 1
    assert issue_rows[0].id == "proposal-1b"
    assert issue_rows[0].fingerprint == "project-1|issue-1|runtime_tooling|qa-failure"
    assert [row.status for row in status_rows] == ["accepted"]
    assert len(limited_rows) == 1


def test_sync_store_saves_lists_filters_and_dedupes(tmp_path):
    store = SQLiteStore(tmp_path / "console.db")
    store.save_self_improvement_proposal(_proposal())
    store.save_self_improvement_proposal(
        _proposal(
            "proposal-2",
            issue_id="issue-2",
            target_kind="code_spec",
            status="accepted",
            fingerprint="project-1|issue-2|code_spec|qa-failure",
        )
    )
    store.save_self_improvement_proposal(
        _proposal(
            "proposal-1b",
            status="proposed",
            fingerprint="project-1|issue-1|runtime_tooling|qa-failure",
        )
    )

    assert len(store.list_self_improvement_proposals(project_id="project-1")) == 2
    issue_rows = store.list_self_improvement_proposals(project_id="project-1", issue_id="issue-1")
    assert len(issue_rows) == 1
    assert issue_rows[0].id == "proposal-1b"
    assert [row.status for row in store.list_self_improvement_proposals(project_id="project-1", status="accepted")] == ["accepted"]
```

- [ ] **Step 2: Run store tests to verify the missing contract**

Run: `pytest backend/tests/test_self_improvement_store.py -v`

Expected: FAIL with an import or attribute error for `SelfImprovementProposal` / `save_self_improvement_proposal`.

## Task 2: Domain Model And Store Implementation

**Files:**
- Modify: `backend/app/domain/models.py`
- Modify: `backend/app/adapters/async_sqlite_store.py`
- Modify: `backend/app/adapters/sqlite_store.py`
- Test: `backend/tests/test_self_improvement_store.py`

- [ ] **Step 1: Add the domain dataclass**

In `backend/app/domain/models.py`, add the dataclass near `ProjectMemoryEmbedding`:

```python
@dataclass
class SelfImprovementProposal:
    """Review-only proposal row produced from issue completion evidence."""

    id: str
    project_id: str
    issue_id: str
    target_kind: str
    title: str
    recommendation: str
    evidence_json: str = "[]"
    severity: str = "info"
    confidence: float = 0.0
    status: str = "proposed"
    fingerprint: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
```

- [ ] **Step 2: Add async store schema and indexes**

In `backend/app/adapters/async_sqlite_store.py`, extend the domain import to include `SelfImprovementProposal`.

In `_init_db`, after `project_memory_embeddings`, add:

```python
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
```

Near the project memory index, add:

```python
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_self_improvement_project_created ON self_improvement_proposals(project_id, created_at)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_self_improvement_issue ON self_improvement_proposals(issue_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_self_improvement_status ON self_improvement_proposals(status)")
```

- [ ] **Step 3: Add async store methods**

In `backend/app/adapters/async_sqlite_store.py`, near `save_project_memory_embedding`, add:

```python
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
        sql = (
            "SELECT id, project_id, issue_id, target_kind, title, recommendation, evidence_json, "
            "severity, confidence, status, fingerprint, created_at, updated_at "
            f"FROM self_improvement_proposals{where} ORDER BY created_at DESC, id DESC"
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
```

- [ ] **Step 4: Add sync store schema, indexes, and methods**

Mirror Step 2 and Step 3 in `backend/app/adapters/sqlite_store.py`, using `conn.execute(...)`, `sqlite3.Row`, synchronous `fetchall()`, and `conn.commit()`. Add `SelfImprovementProposal` to the top-level model import.

Use this method signature exactly:

```python
    def save_self_improvement_proposal(self, proposal: "SelfImprovementProposal") -> None:
```

Use this list signature exactly:

```python
    def list_self_improvement_proposals(
        self,
        project_id: str | None = None,
        issue_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list["SelfImprovementProposal"]:
```

- [ ] **Step 5: Run store tests**

Run: `pytest backend/tests/test_self_improvement_store.py -v`

Expected: PASS.

- [ ] **Step 6: Commit store layer**

Run:

```bash
git add backend/app/domain/models.py backend/app/adapters/async_sqlite_store.py backend/app/adapters/sqlite_store.py backend/tests/test_self_improvement_store.py
git commit -m "feat: add self improvement proposal store"
```

## Task 3: Deterministic Extraction Service

**Files:**
- Create: `backend/app/application/self_improvement_service.py`
- Create: `backend/tests/test_self_improvement_service.py`

- [ ] **Step 1: Write failing service tests**

Create `backend/tests/test_self_improvement_service.py`:

```python
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.application.self_improvement_service import extract_self_improvement_proposals
from app.domain.models import CodexIssue, ConductorTask


class MemoryStore:
    def __init__(self, *, tasks=None, latest=None, save_error: Exception | None = None):
        self.tasks = tasks or []
        self.latest = latest
        self.save_error = save_error
        self.saved = []

    async def list_conductor_tasks(self, *, status=None):
        if status is None:
            return self.tasks
        return [task for task in self.tasks if task.status == status]

    async def load_latest_conductor_task_for_issue(self, issue_id):
        return self.latest

    async def save_self_improvement_proposal(self, proposal):
        if self.save_error is not None:
            raise self.save_error
        self.saved.append(proposal)


def _issue(**overrides):
    data = {
        "id": "issue-1",
        "session_id": "session-1",
        "title": "Fix flaky QA workflow",
        "description": "QA reported command failures and runtime tracebacks.",
        "status": "completed",
        "project_id": "project-1",
        "created_at": datetime(2026, 6, 8, 10, 0, 0),
    }
    data.update(overrides)
    return CodexIssue(**data)


def _task(task_id, *, status="failed", result_json=None, payload=None):
    return ConductorTask(
        id=task_id,
        project_id="project-1",
        issue_id="issue-1",
        task_kind="conductor",
        status=status,
        payload=payload or {"phase": "qa"},
        result_json=result_json or {"traceback": "RuntimeError: qa command failed"},
    )


@pytest.mark.asyncio
async def test_qa_failure_creates_code_spec_proposal_with_evidence():
    store = MemoryStore(
        tasks=[
            _task(
                "task-1",
                result_json={
                    "qa": {"verdict": "failed", "bugs_found": ["missing regression contract"]},
                    "commands": [{"cmd": "pytest backend/tests/test_qa_workflow.py", "exit_code": 1}],
                },
            )
        ]
    )

    proposals = await extract_self_improvement_proposals(_issue(), store)

    assert len(proposals) == 1
    assert proposals[0].target_kind == "code_spec"
    assert proposals[0].severity == "medium"
    assert proposals[0].fingerprint == "project-1|issue-1|code_spec|qa_failure_contract"
    assert '"conductor_task"' in proposals[0].evidence_json
    assert store.saved == proposals


@pytest.mark.asyncio
async def test_runtime_failure_creates_runtime_tooling_proposal():
    store = MemoryStore(tasks=[_task("task-1", result_json={"traceback": "RuntimeError: browser observed failure"})])

    proposals = await extract_self_improvement_proposals(_issue(title="Fix browser runtime failure"), store)

    assert len(proposals) == 1
    assert proposals[0].target_kind == "runtime_tooling"
    assert proposals[0].fingerprint == "project-1|issue-1|runtime_tooling|runtime_failure_contract"


@pytest.mark.asyncio
async def test_clean_issue_creates_no_proposals():
    store = MemoryStore(tasks=[_task("task-1", status="done", result_json={"summary": "all good"})])

    proposals = await extract_self_improvement_proposals(_issue(title="Rename label"), store)

    assert proposals == []
    assert store.saved == []


@pytest.mark.asyncio
async def test_duplicate_rules_save_once_per_rule():
    store = MemoryStore(
        tasks=[
            _task("task-1", result_json={"traceback": "RuntimeError: failed once"}),
            _task("task-2", result_json={"traceback": "RuntimeError: failed twice"}),
        ]
    )

    proposals = await extract_self_improvement_proposals(_issue(), store)

    assert len(proposals) == 1
    assert len(store.saved) == 1


@pytest.mark.asyncio
async def test_store_save_failure_is_best_effort():
    store = MemoryStore(tasks=[_task("task-1")], save_error=RuntimeError("db unavailable"))

    proposals = await extract_self_improvement_proposals(_issue(), store)

    assert proposals == []
```

- [ ] **Step 2: Run service tests to verify they fail**

Run: `pytest backend/tests/test_self_improvement_service.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.application.self_improvement_service'`.

- [ ] **Step 3: Implement the service**

Create `backend/app/application/self_improvement_service.py`:

```python
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.domain.models import CodexIssue, SelfImprovementProposal

logger = logging.getLogger(__name__)


def _json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


def _normalize_fingerprint_part(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return normalized or "proposal"


def _fingerprint(issue: CodexIssue, target_kind: str, rule_id: str) -> str:
    return "|".join([issue.project_id or "", issue.id, target_kind, _normalize_fingerprint_part(rule_id)])


def _proposal(
    issue: CodexIssue,
    *,
    target_kind: str,
    rule_id: str,
    title: str,
    recommendation: str,
    evidence: list[dict[str, Any]],
    severity: str = "medium",
    confidence: float = 0.75,
) -> SelfImprovementProposal:
    now = datetime.now()
    return SelfImprovementProposal(
        id=f"sip-{uuid4().hex}",
        project_id=issue.project_id or "",
        issue_id=issue.id,
        target_kind=target_kind,
        title=title,
        recommendation=recommendation,
        evidence_json=json.dumps(evidence, ensure_ascii=False, default=str),
        severity=severity,
        confidence=confidence,
        status="proposed",
        fingerprint=_fingerprint(issue, target_kind, rule_id),
        created_at=now,
        updated_at=now,
    )


def _task_matches_issue(task: Any, issue_id: str) -> bool:
    return getattr(task, "issue_id", None) == issue_id


async def _load_issue_tasks(issue: CodexIssue, store: Any) -> list[Any]:
    if not hasattr(store, "list_conductor_tasks"):
        return []
    try:
        tasks = await store.list_conductor_tasks()
    except TypeError:
        tasks = []
        for status in ("failed", "stalled", "done"):
            try:
                tasks.extend(await store.list_conductor_tasks(status=status))
            except Exception as exc:  # noqa: BLE001
                logger.debug("self_improvement task read failed for %s/%s: %s", issue.id, status, exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("self_improvement task read failed for %s: %s", issue.id, exc)
        return []
    return [task for task in tasks if _task_matches_issue(task, issue.id)]


def _task_evidence(task: Any, reason: str) -> dict[str, Any]:
    return {
        "kind": "conductor_task",
        "id": getattr(task, "id", None),
        "status": getattr(task, "status", None),
        "reason": reason,
        "payload": getattr(task, "payload", None),
        "result_json": getattr(task, "result_json", None),
    }


def _classify_tasks(issue: CodexIssue, tasks: list[Any]) -> list[SelfImprovementProposal]:
    proposals: dict[str, SelfImprovementProposal] = {}
    for task in tasks:
        text = _json_text(getattr(task, "result_json", None))
        status = str(getattr(task, "status", "") or "").lower()
        lowered = text.lower()
        if "qa" in lowered and ("failed" in lowered or "bugs_found" in lowered or "exit_code" in lowered):
            proposal = _proposal(
                issue,
                target_kind="code_spec",
                rule_id="qa_failure_contract",
                title="Capture QA failure as an executable contract",
                recommendation="Review the QA failure evidence and add or update the relevant code-spec contract before similar issues repeat.",
                evidence=[_task_evidence(task, "qa_failure")],
                severity="medium",
                confidence=0.8,
            )
            proposals[proposal.fingerprint] = proposal
        elif status in {"failed", "stalled"} or "traceback" in lowered or "runtimeerror" in lowered:
            proposal = _proposal(
                issue,
                target_kind="runtime_tooling",
                rule_id="runtime_failure_contract",
                title="Harden runtime failure handling from conductor evidence",
                recommendation="Review the runtime/conductor failure and add a durable guard, test, or recovery contract for this failure mode.",
                evidence=[_task_evidence(task, "runtime_failure")],
                severity="medium",
                confidence=0.75,
            )
            proposals[proposal.fingerprint] = proposal
    return list(proposals.values())


async def extract_self_improvement_proposals(issue: CodexIssue, store: Any) -> list[SelfImprovementProposal]:
    if not getattr(issue, "project_id", None):
        return []
    tasks = await _load_issue_tasks(issue, store)
    proposals = _classify_tasks(issue, tasks)
    saved: list[SelfImprovementProposal] = []
    for proposal in proposals:
        try:
            await store.save_self_improvement_proposal(proposal)
        except Exception as exc:  # noqa: BLE001
            logger.warning("self_improvement proposal save failed for issue %s: %s", issue.id, exc)
            return []
        saved.append(proposal)
    return saved


async def record_issue_self_improvement(issue: CodexIssue, store: Any) -> list[SelfImprovementProposal]:
    try:
        return await extract_self_improvement_proposals(issue, store)
    except Exception as exc:  # noqa: BLE001
        logger.warning("self_improvement extraction failed for issue %s: %s", issue.id, exc)
        return []
```

- [ ] **Step 4: Run service tests**

Run: `pytest backend/tests/test_self_improvement_service.py -v`

Expected: PASS.

- [ ] **Step 5: Commit service layer**

Run:

```bash
git add backend/app/application/self_improvement_service.py backend/tests/test_self_improvement_service.py
git commit -m "feat: extract self improvement proposals"
```

## Task 4: Conductor Terminal Seal Hook

**Files:**
- Modify: `backend/app/application/conductor_main_loop.py`
- Modify: `backend/tests/test_swarm_integration.py`
- Create: `backend/tests/test_self_improvement_seal.py`

- [ ] **Step 1: Write failing seal hook test**

Create `backend/tests/test_self_improvement_seal.py`:

```python
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.application import conductor_main_loop as cml
from app.domain.models import CodexIssue, WorkflowGraph


class SealStore:
    def __init__(self):
        self.graph = WorkflowGraph(
            id="graph-1",
            issue_id="issue-1",
            preset_id="preset-1",
            status="running",
            created_at=datetime(2026, 6, 8, 10, 0, 0),
            updated_at=datetime(2026, 6, 8, 10, 0, 0),
        )
        self.saved_issue = None
        self.saved_graph = None

    async def load_workflow_graph_for_issue(self, issue_id):
        return self.graph

    async def save_workflow_graph(self, graph):
        self.saved_graph = graph

    async def save_codex_issue(self, issue):
        self.saved_issue = issue

    async def load_project(self, project_id):
        return None


def _issue():
    return CodexIssue(
        id="issue-1",
        session_id="session-1",
        title="Done issue",
        description="Completed",
        status="open",
        project_id="project-1",
    )


@pytest.mark.asyncio
async def test_done_seal_records_memory_then_self_improvement():
    store = SealStore()
    with patch("app.application.conductor_main_loop.record_project_memory", new=AsyncMock()) as memory, patch(
        "app.application.conductor_main_loop.record_issue_self_improvement", new=AsyncMock()
    ) as improve:
        await cml._seal_graph_and_issue_status(store=store, issue=_issue(), event_bus=None, result_status="done")

    memory.assert_awaited_once_with("graph-1", store)
    improve.assert_awaited_once()
    assert improve.await_args.args[0].id == "issue-1"
    assert improve.await_args.args[1] is store
    assert store.saved_issue.status == "completed"


@pytest.mark.asyncio
async def test_self_improvement_failure_does_not_block_terminal_status():
    store = SealStore()
    with patch("app.application.conductor_main_loop.record_project_memory", new=AsyncMock()), patch(
        "app.application.conductor_main_loop.record_issue_self_improvement",
        new=AsyncMock(side_effect=RuntimeError("proposal store down")),
    ):
        await cml._seal_graph_and_issue_status(store=store, issue=_issue(), event_bus=None, result_status="done")

    assert store.saved_graph.status == "done"
    assert store.saved_issue.status == "completed"
```

- [ ] **Step 2: Run seal tests to verify the hook is missing**

Run: `pytest backend/tests/test_self_improvement_seal.py -v`

Expected: FAIL because `record_issue_self_improvement` is not imported or not called.

- [ ] **Step 3: Add the terminal hook**

In `backend/app/application/conductor_main_loop.py`, add this import:

```python
from app.application.self_improvement_service import record_issue_self_improvement
```

Inside `_seal_graph_and_issue_status`, immediately after `await record_project_memory(graph.id, store)`, add:

```python
                try:
                    await record_issue_self_improvement(issue, store)
                except Exception as exc:  # noqa: BLE001
                    logging.getLogger(__name__).warning("self_improvement extraction failed: %s", exc)
```

- [ ] **Step 4: Extend the existing swarm seal-path test**

In `backend/tests/test_swarm_integration.py::test_cleanup_issue_swarm_worktrees_seal_path_main_clean`, patch the new hook so the test stays focused on cleanup:

```python
    with patch("app.application.conductor_main_loop.record_issue_self_improvement", new_callable=AsyncMock):
        await cml._seal_graph_and_issue_status(
            store=store, issue=issue, event_bus=None, result_status="done"
        )
```

Add missing imports if needed:

```python
from unittest.mock import AsyncMock, patch
```

- [ ] **Step 5: Run seal-related tests**

Run:

```bash
pytest backend/tests/test_self_improvement_seal.py backend/tests/test_swarm_integration.py::test_cleanup_issue_swarm_worktrees_seal_path_main_clean -v
```

Expected: PASS.

- [ ] **Step 6: Commit seal hook**

Run:

```bash
git add backend/app/application/conductor_main_loop.py backend/tests/test_self_improvement_seal.py backend/tests/test_swarm_integration.py
git commit -m "feat: record self improvement on issue seal"
```

## Task 5: Read-Only API Endpoint

**Files:**
- Modify: `backend/app/interfaces/api.py`
- Create: `backend/tests/test_self_improvement_api.py`

- [ ] **Step 1: Write failing API tests**

Create `backend/tests/test_self_improvement_api.py`:

```python
from datetime import datetime

from app.domain.models import SelfImprovementProposal


def _proposal(proposal_id="proposal-1", *, issue_id="issue-1", status="proposed"):
    return SelfImprovementProposal(
        id=proposal_id,
        project_id="project-1",
        issue_id=issue_id,
        target_kind="runtime_tooling",
        title="Harden runtime failure handling",
        recommendation="Add a durable runtime guard.",
        evidence_json='[{"kind":"conductor_task","id":"task-1"}]',
        severity="medium",
        confidence=0.75,
        status=status,
        fingerprint=f"project-1|{issue_id}|runtime_tooling|runtime_failure_contract",
        created_at=datetime(2026, 6, 8, 10, 0, 0),
        updated_at=datetime(2026, 6, 8, 10, 1, 0),
    )


def test_project_self_improvement_proposals_endpoint_shape(client):
    from app.bootstrap import async_store

    import anyio

    anyio.run(async_store.save_self_improvement_proposal, _proposal())

    resp = client.get("/api/codex/projects/project-1/self-improvement-proposals")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert list(body.keys()) == ["proposals"]
    assert body["proposals"][0]["id"] == "proposal-1"
    assert body["proposals"][0]["evidence"] == [{"kind": "conductor_task", "id": "task-1"}]
    assert body["proposals"][0]["created_at"] == "2026-06-08T10:00:00"


def test_project_self_improvement_proposals_endpoint_filters(client):
    from app.bootstrap import async_store

    import anyio

    anyio.run(async_store.save_self_improvement_proposal, _proposal("proposal-1", issue_id="issue-1"))
    anyio.run(async_store.save_self_improvement_proposal, _proposal("proposal-2", issue_id="issue-2", status="accepted"))

    resp = client.get(
        "/api/codex/projects/project-1/self-improvement-proposals",
        params={"issue_id": "issue-2", "status": "accepted", "limit": 5},
    )

    assert resp.status_code == 200, resp.text
    proposals = resp.json()["proposals"]
    assert [proposal["id"] for proposal in proposals] == ["proposal-2"]
```

- [ ] **Step 2: Run API tests to verify endpoint is missing**

Run: `pytest backend/tests/test_self_improvement_api.py -v`

Expected: FAIL with HTTP 404 for `/api/codex/projects/project-1/self-improvement-proposals`.

- [ ] **Step 3: Add response serialization helper**

In `backend/app/interfaces/api.py`, near the project conductor state endpoint helpers, add:

```python
def _self_improvement_proposal_to_dict(proposal) -> dict:
    try:
        evidence = json.loads(proposal.evidence_json or "[]")
    except json.JSONDecodeError:
        evidence = []
    if not isinstance(evidence, list):
        evidence = []
    return {
        "id": proposal.id,
        "project_id": proposal.project_id,
        "issue_id": proposal.issue_id,
        "target_kind": proposal.target_kind,
        "title": proposal.title,
        "recommendation": proposal.recommendation,
        "evidence": evidence,
        "severity": proposal.severity,
        "confidence": proposal.confidence,
        "status": proposal.status,
        "fingerprint": proposal.fingerprint,
        "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
        "updated_at": proposal.updated_at.isoformat() if proposal.updated_at else None,
    }
```

- [ ] **Step 4: Add the endpoint**

In `backend/app/interfaces/api.py`, near `/codex/projects/{project_id}/conductor-state`, add:

```python
@router.get("/codex/projects/{project_id}/self-improvement-proposals")
async def codex_project_self_improvement_proposals(
    project_id: str,
    issue_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    project = await codex_store.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    proposals = await codex_store.list_self_improvement_proposals(
        project_id=project_id,
        issue_id=issue_id,
        status=status,
        limit=limit,
    )
    return {"proposals": [_self_improvement_proposal_to_dict(proposal) for proposal in proposals]}
```

- [ ] **Step 5: Update API test setup if project lookup returns 404**

If the endpoint returns 404 because the session-scoped store has no `project-1`, seed a project in the test before saving proposals:

```python
from app.domain.models import Project


def _project():
    return Project(id="project-1", name="Project 1", repo_path="/tmp/project-1", default_branch="main")
```

Then call:

```python
anyio.run(async_store.save_project, _project())
```

- [ ] **Step 6: Run API tests**

Run: `pytest backend/tests/test_self_improvement_api.py -v`

Expected: PASS.

- [ ] **Step 7: Commit API endpoint**

Run:

```bash
git add backend/app/interfaces/api.py backend/tests/test_self_improvement_api.py
git commit -m "feat: expose self improvement proposals api"
```

## Task 6: Integrated Verification And Regression Sweep

**Files:**
- No new files expected.
- Modify implementation files only if the verification exposes a defect.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
pytest \
  backend/tests/test_self_improvement_store.py \
  backend/tests/test_self_improvement_service.py \
  backend/tests/test_self_improvement_seal.py \
  backend/tests/test_self_improvement_api.py \
  backend/tests/test_project_conductor.py \
  backend/tests/test_conductor_main_loop.py \
  -v
```

Expected: PASS.

- [ ] **Step 2: Run API and conductor adjacent tests**

Run:

```bash
pytest \
  backend/tests/test_codex_api.py \
  backend/tests/test_run_issue_conductor_loop.py \
  backend/tests/test_swarm_integration.py::test_cleanup_issue_swarm_worktrees_seal_path_main_clean \
  -v
```

Expected: PASS.

- [ ] **Step 3: Run the backend default test command if focused tests are green**

Run:

```bash
pytest backend/tests -q
```

Expected: PASS or only known slow/environment-skipped tests. Any failure in touched behavior must be fixed before continuing.

- [ ] **Step 4: Inspect the final diff**

Run:

```bash
git diff --stat
git diff -- backend/app/domain/models.py backend/app/adapters/async_sqlite_store.py backend/app/adapters/sqlite_store.py backend/app/application/self_improvement_service.py backend/app/application/conductor_main_loop.py backend/app/interfaces/api.py
```

Expected: Diff only covers the proposal ledger, extraction hook, API, and tests.

## Task 7: Trellis Quality And Finish Preparation

**Files:**
- Modify: `.trellis/spec/` only if verification reveals a reusable backend contract worth preserving.
- Modify: `.trellis/tasks/06-08-self-improvement-loop/prd.md` only if implementation reveals a requirement correction.

- [ ] **Step 1: Run Trellis check**

Load `trellis-check` and verify spec compliance, lint/type-check expectations, tests, cross-layer consistency, and code reuse.

Expected: No unresolved findings.

- [ ] **Step 2: Run spec update judgment**

Load `trellis-update-spec` and decide whether to record new reusable contracts. At minimum evaluate these candidates:

- self-improvement extraction is best-effort and must not block terminal issue status;
- review-only proposals must be durable and idempotent by fingerprint;
- API reads parse malformed `evidence_json` as an empty list rather than failing the endpoint.

Expected: Either a focused `.trellis/spec/` update is committed, or the journal records why no spec update was needed.

- [ ] **Step 3: Commit any final fixes or spec docs**

Run:

```bash
git status --short
git log --oneline -5
```

If dirty files remain from implementation or spec updates, group them into coherent commits using the existing commit style. Do not include unrelated user changes.

- [ ] **Step 4: Leave the task ready for `/finish-work`**

Run:

```bash
git status --short --branch
```

Expected: Working tree clean, branch ahead by the new implementation commits. Tell the user they can run `/finish-work` after reviewing the result.

## Plan Self-Review

- Spec coverage: The tasks cover durable proposals, evidence pointers, target kinds, idempotent fingerprints, best-effort terminal extraction, no-op clean issues, existing project memory preservation, read API, and backend tests.
- Placeholder scan: The plan contains no implementation placeholders. Every code-changing task has concrete paths, snippets, commands, and expected results.
- Type consistency: `SelfImprovementProposal`, `save_self_improvement_proposal`, `list_self_improvement_proposals`, `extract_self_improvement_proposals`, and `record_issue_self_improvement` are named consistently across tasks.
