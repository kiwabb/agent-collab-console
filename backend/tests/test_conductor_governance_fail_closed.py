"""Fail-closed governance regressions for conductor dispatch gates."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime

import pytest

import app.application.conductor_tools as ct
from app.application.budget_service import IssueBudgetStatus
from app.domain.models import CodexIssue, Project

ISSUE_ID = "issue-governance"


@pytest.fixture(autouse=True)
def _reset_dispatch_locks() -> Generator[None, None, None]:
    ct._DISPATCH_START_LOCKS_BY_ISSUE.clear()
    yield
    ct._DISPATCH_START_LOCKS_BY_ISSUE.clear()


def _issue() -> CodexIssue:
    return CodexIssue(
        id=ISSUE_ID,
        session_id="session-1",
        project_id="project-1",
        title="Governance test",
        git_branch="issue/governance-test",
        budget_usd=5.0,
        status="open",
    )




def _budget_status(issue: CodexIssue) -> IssueBudgetStatus:
    return IssueBudgetStatus(
        issue_id=issue.id,
        spent_usd=0.0,
        budget_usd=0.0,
        budget_source="issue",
        soft_warn_ratio=0.8,
    )

def _project() -> Project:
    now = datetime.now()
    return Project(
        id="project-1",
        name="demo",
        repo_path="/tmp/repo",
        default_branch="main",
        created_at=now,
        updated_at=now,
    )


class _Store:
    def __init__(self, *, graph_error: Exception | None = None, project: Project | None = None):
        self.issue = _issue()
        self.project = project or _project()
        self.graph_error = graph_error

    async def load_codex_issue(self, issue_id: str):
        return self.issue if issue_id == ISSUE_ID else None

    async def load_project(self, project_id: str):
        return self.project if project_id == self.project.id else None

    async def load_workflow_graph_for_issue(self, issue_id: str):
        if self.graph_error is not None:
            raise self.graph_error
        return None


class _WorktreeManager:
    def __init__(self) -> None:
        self.prepared: list[str] = []

    async def prepare_agent_worktree(self, project, issue, agent_key: str):
        self.prepared.append(agent_key)
        return f"branch/{agent_key}", f"/tmp/{agent_key}", issue.git_branch

    async def commit_issue_worktree(self, issue, message=None):
        return None

    async def cleanup_agent_worktree(self, project, issue, agent_key: str):
        return None

    async def merge_agent_worktrees(self, project, issue, agents):
        return {"merged": [], "conflict": None, "skipped": []}


def _registry(store, *, worktree_manager=None):
    return ct.build_conductor_tools(
        project_id="project-1",
        store=store,
        event_bus=None,
        task_dispatcher_fn=lambda *a, **k: None,
        issue_id=ISSUE_ID,
        worktree_manager=worktree_manager,
    )


@pytest.mark.asyncio
async def test_dispatch_subagent_fails_closed_when_budget_status_errors(monkeypatch):
    async def _boom(store, issue):
        raise RuntimeError("budget store unavailable")

    monkeypatch.setattr(
        "app.application.budget_service.compute_issue_budget_status",
        _boom,
    )
    reg = _registry(_Store())

    result = await reg.tools["dispatch_subagent"]({"role": "engineer", "prompt": "fix it"})

    assert result["status"] == "failed"
    assert result["gate"] == "budget"
    assert "refusing to dispatch" in result["error"]
    assert "budget store unavailable" in result["details"]


@pytest.mark.asyncio
async def test_dispatch_batch_fails_closed_when_budget_status_errors(monkeypatch):
    async def _boom(store, issue):
        raise RuntimeError("budget store unavailable")

    monkeypatch.setattr(
        "app.application.budget_service.compute_issue_budget_status",
        _boom,
    )
    wm = _WorktreeManager()
    reg = _registry(_Store(), worktree_manager=wm)

    result = await reg.tools["dispatch_batch"]({"agents": [{"role": "engineer"}]})

    assert result["status"] == "failed"
    assert result["gate"] == "budget"
    assert wm.prepared == []


@pytest.mark.asyncio
async def test_dispatch_subagent_fails_closed_when_graph_load_errors(monkeypatch):
    async def _ok(store, issue):
        return _budget_status(issue)

    monkeypatch.setattr(
        "app.application.budget_service.compute_issue_budget_status",
        _ok,
    )
    reg = _registry(_Store(graph_error=RuntimeError("graph read failed")))

    result = await reg.tools["dispatch_subagent"]({"role": "engineer", "prompt": "fix it"})

    assert result["status"] == "failed"
    assert result["gate"] == "redispatch_budget"
    assert "graph read failed" in result["details"]


@pytest.mark.asyncio
async def test_dispatch_batch_fails_closed_when_graph_load_errors_before_worktrees(monkeypatch):
    async def _ok(store, issue):
        return _budget_status(issue)

    monkeypatch.setattr(
        "app.application.budget_service.compute_issue_budget_status",
        _ok,
    )
    wm = _WorktreeManager()
    reg = _registry(_Store(graph_error=RuntimeError("graph read failed")), worktree_manager=wm)

    result = await reg.tools["dispatch_batch"]({"agents": [{"role": "engineer"}]})

    assert result["status"] == "failed"
    assert result["gate"] == "redispatch_budget"
    assert wm.prepared == []
