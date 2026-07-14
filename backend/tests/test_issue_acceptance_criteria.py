from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest
from pydantic import ValidationError

import app.interfaces.api as api_module
from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.adapters.sqlite_store import SQLiteStore
from app.domain.models import CodexIssue, CodexSession, Project
from app.interfaces.api import ConfirmIssueAcceptanceCriteriaRequest, CreateIssueRequest


def _issue(*, issue_id: str = "issue-criteria") -> CodexIssue:
    now = datetime.now()
    return CodexIssue(
        id=issue_id,
        session_id="workspace-criteria",
        project_id="project-criteria",
        title="Persist acceptance criteria",
        description="Keep the completion contract with the issue.",
        acceptance_criteria=[
            "REST returns 401 without a token",
            "The list view round-trips criteria",
        ],
        acceptance_criteria_confirmed=True,
        created_at=now,
        updated_at=now,
    )


def test_codex_issue_acceptance_criteria_defaults_are_unconfirmed() -> None:
    issue = CodexIssue(id="legacy", session_id="workspace", title="Legacy issue")

    assert issue.acceptance_criteria == []
    assert issue.acceptance_criteria_confirmed is False


def test_sync_store_round_trips_issue_acceptance_criteria(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "criteria-sync.db")
    issue = _issue()

    store.save_codex_issue(issue)

    loaded = store.load_codex_issue(issue.id)
    assert loaded is not None
    assert loaded.acceptance_criteria == issue.acceptance_criteria
    assert loaded.acceptance_criteria_confirmed is True

    listed = store.list_codex_issues(session_id=issue.session_id)
    assert listed[0]["acceptance_criteria"] == issue.acceptance_criteria
    assert listed[0]["acceptance_criteria_confirmed"] is True


@pytest.mark.asyncio
async def test_async_store_round_trips_issue_acceptance_criteria(tmp_path) -> None:
    store = AsyncSQLiteStore(tmp_path / "criteria-async.db")
    issue = _issue()
    try:
        await store.save_codex_issue(issue)

        loaded = await store.load_codex_issue(issue.id)
        assert loaded is not None
        assert loaded.acceptance_criteria == issue.acceptance_criteria
        assert loaded.acceptance_criteria_confirmed is True

        listed = await store.list_codex_issues(session_id=issue.session_id)
        assert listed[0]["acceptance_criteria"] == issue.acceptance_criteria
        assert listed[0]["acceptance_criteria_confirmed"] is True
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_async_store_migrates_legacy_issue_to_unconfirmed_defaults(tmp_path) -> None:
    db_path = tmp_path / "criteria-legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE schema_version (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            version INTEGER NOT NULL
        );
        INSERT INTO schema_version (id, version) VALUES (1, 3);
        CREATE TABLE codex_issues (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            current_phase TEXT NOT NULL DEFAULT 'requirements',
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT,
            updated_at TEXT
        );
        INSERT INTO codex_issues (
            id, session_id, title, description, current_phase, status, created_at, updated_at
        ) VALUES (
            'legacy-issue', 'legacy-workspace', 'Legacy issue', NULL,
            'requirements', 'open', '2026-07-11T00:00:00', '2026-07-11T00:00:00'
        );
        """
    )
    conn.commit()
    conn.close()

    store = AsyncSQLiteStore(db_path)
    try:
        loaded = await store.load_codex_issue("legacy-issue")
        assert loaded is not None
        assert loaded.acceptance_criteria == []
        assert loaded.acceptance_criteria_confirmed is False

        listed = await store.list_codex_issues(session_id="legacy-workspace")
        assert listed[0]["acceptance_criteria"] == []
        assert listed[0]["acceptance_criteria_confirmed"] is False

        connection = await store._get_conn()
        cursor = await connection.execute("SELECT version FROM schema_version WHERE id = 1")
        version = await cursor.fetchone()
        assert version is not None
        assert version[0] == 12
    finally:
        await store.close()


class _IssueCreateStore:
    def __init__(self) -> None:
        self.workspace = CodexSession(
            id="workspace-api",
            title="Workspace",
            cwd="/tmp/project",
            project_id="project-api",
        )
        self.project = Project(id="project-api", name="Project", repo_path="/tmp/project")
        self.saved_issue: CodexIssue | None = None
        self.audit_events: list[str] = []

    async def load_codex_workspace(self, workspace_id: str) -> CodexSession | None:
        return self.workspace if workspace_id == self.workspace.id else None

    async def load_project(self, project_id: str) -> Project | None:
        return self.project if project_id == self.project.id else None

    async def save_codex_issue(self, issue: CodexIssue) -> None:
        self.saved_issue = issue

    async def load_codex_issue(self, issue_id: str) -> CodexIssue | None:
        if self.saved_issue is not None and self.saved_issue.id == issue_id:
            return self.saved_issue
        return None

    async def append_project_audit(self, **kwargs: object) -> None:
        event = kwargs.get("event")
        if isinstance(event, str):
            self.audit_events.append(event)


class _IssueWorktreeManager:
    async def prepare_issue_worktree(
        self, project: Project, issue: CodexIssue, *, base_branch: str | None = None
    ) -> tuple[str, str, str]:
        assert project.id == "project-api"
        assert issue.session_id == "workspace-api"
        return "issue/criteria", "/tmp/project-worktree", base_branch or "main"


@pytest.mark.asyncio
async def test_create_issue_request_persists_confirmed_acceptance_criteria(monkeypatch) -> None:
    store = _IssueCreateStore()
    monkeypatch.setattr(api_module, "codex_store", store)
    monkeypatch.setattr(api_module, "worktree_manager", _IssueWorktreeManager())

    request = CreateIssueRequest(
        session_id="workspace-api",
        title="Acceptance contract",
        acceptance_criteria=["  Returns 401 without a token  ", "", "Keeps legacy rows readable"],
        acceptance_criteria_confirmed=True,
    )
    created = await api_module.create_codex_issue(request)

    assert created.acceptance_criteria == [
        "Returns 401 without a token",
        "Keeps legacy rows readable",
    ]
    assert created.acceptance_criteria_confirmed is True
    assert store.saved_issue == created


def test_create_issue_request_rejects_confirmation_without_criteria() -> None:
    with pytest.raises(ValidationError, match="must include at least one item"):
        CreateIssueRequest(
            session_id="workspace-api",
            title="Missing criteria",
            acceptance_criteria_confirmed=True,
        )


@pytest.mark.asyncio
async def test_unconfirmed_issue_can_confirm_immutable_acceptance_contract(monkeypatch) -> None:
    store = _IssueCreateStore()
    issue = _issue()
    issue.acceptance_criteria = []
    issue.acceptance_criteria_confirmed = False
    store.saved_issue = issue

    class EventBus:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        async def append(self, event: dict[str, object]) -> None:
            self.events.append(event)

    event_bus = EventBus()
    monkeypatch.setattr(api_module, "codex_store", store)
    monkeypatch.setattr(api_module, "event_bus", event_bus)

    updated = await api_module.confirm_issue_acceptance_criteria(
        issue.id,
        ConfirmIssueAcceptanceCriteriaRequest(
            acceptance_criteria=["  Returns 401  ", "Returns 401", "Persists evidence"]
        ),
    )

    assert updated.acceptance_criteria == ["Returns 401", "Persists evidence"]
    assert updated.acceptance_criteria_confirmed is True
    assert store.audit_events == ["acceptance_criteria_confirmed:2"]
    assert event_bus.events[-1]["type"] == "issue_updated"


@pytest.mark.asyncio
async def test_confirmed_acceptance_contract_cannot_be_changed(monkeypatch) -> None:
    store = _IssueCreateStore()
    store.saved_issue = _issue()
    monkeypatch.setattr(api_module, "codex_store", store)

    with pytest.raises(api_module.HTTPException) as caught:
        await api_module.confirm_issue_acceptance_criteria(
            store.saved_issue.id,
            ConfirmIssueAcceptanceCriteriaRequest(acceptance_criteria=["Different target"]),
        )

    assert caught.value.status_code == 409
    assert store.saved_issue.acceptance_criteria == [
        "REST returns 401 without a token",
        "The list view round-trips criteria",
    ]


def test_confirm_acceptance_request_rejects_blank_only_criteria() -> None:
    with pytest.raises(ValidationError, match="must include at least one item"):
        ConfirmIssueAcceptanceCriteriaRequest(acceptance_criteria=[" ", ""])
