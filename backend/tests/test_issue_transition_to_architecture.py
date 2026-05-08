from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.domain.models import CodexIssue, CodexSession, CodexTask
import app.interfaces.api as api_module
from app.main import app


class TransitionStoreStub:
    def __init__(self, *, issue, session, tasks):
        self.issue = issue
        self.session = session
        self.tasks = {task.id: task for task in tasks}
        self.saved_issue = None
        self.saved_task = None

    async def load_codex_issue(self, issue_id: str):
        return self.issue if issue_id == self.issue.id else None

    async def load_codex_session(self, session_id: str):
        return self.session if session_id == self.session.id else None

    async def load_codex_workspace(self, session_id: str):
        return self.session if session_id == self.session.id else None

    async def save_codex_issue(self, issue):
        self.issue = issue
        self.saved_issue = issue

    async def list_codex_tasks(self, session_id: str | None = None, issue_id: str | None = None):
        result = []
        for task in self.tasks.values():
            if session_id is not None and task.session_id != session_id:
                continue
            if issue_id is not None and task.issue_id != issue_id:
                continue
            result.append({
                "id": task.id,
                "session_id": task.session_id,
                "issue_id": task.issue_id,
                "phase": task.phase,
                "title": task.title,
                "prompt": task.prompt,
                "role": task.role,
                "executor": task.executor,
                "status": task.status,
                "workspace_path": task.workspace_path,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            })
        return result

    async def save_codex_task(self, task):
        self.tasks[task.id] = task
        self.saved_task = task

    async def load_codex_task(self, task_id: str):
        return self.tasks.get(task_id)


@pytest.fixture
def client():
    return TestClient(app)


def build_issue_bundle(tmp_path):
    now = datetime.now()
    session = CodexSession(
        id="ws-1",
        title="Workspace",
        cwd=str(tmp_path),
        created_at=now,
        last_active_at=now,
    )
    issue = CodexIssue(
        id="issue-1",
        session_id=session.id,
        title="需求 - 购物车",
        current_phase="requirements",
        status="open",
        created_at=now,
        updated_at=now,
    )
    pm_task = CodexTask(
        id="task-pm-1",
        session_id=session.id,
        issue_id=issue.id,
        phase="requirements",
        title="需求 - 购物车",
        prompt="请整理需求",
        role="product_manager",
        executor="codex",
        status="done",
        workspace_path=str(tmp_path),
        created_at=now,
        updated_at=now,
    )
    return session, issue, pm_task


def create_issue_artifacts(tmp_path, issue_id: str, names: set[str]):
    issue_root = tmp_path / "issues" / issue_id
    issue_root.mkdir(parents=True, exist_ok=True)
    for name in names:
        (issue_root / name).write_text(f"{name} content", encoding="utf-8")


def test_transition_to_architecture_updates_issue_and_creates_task(client, monkeypatch, tmp_path):
    session, issue, pm_task = build_issue_bundle(tmp_path)
    create_issue_artifacts(tmp_path, issue.id, {"requirement.md", "prd.json", "prd.md"})
    store = TransitionStoreStub(issue=issue, session=session, tasks=[pm_task])
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-architecture")

    assert response.status_code == 200
    payload = response.json()
    assert payload["created"] is True
    assert payload["issue"]["current_phase"] == "architecture"
    assert payload["task"]["role"] == "architect"
    assert payload["task"]["phase"] == "architecture"
    assert payload["task"]["title"] == f"架构 - {issue.title}"


def test_transition_to_architecture_returns_existing_architect_task(client, monkeypatch, tmp_path):
    session, issue, pm_task = build_issue_bundle(tmp_path)
    create_issue_artifacts(tmp_path, issue.id, {"requirement.md"})
    architect_task = CodexTask(
        id="task-arch-1",
        session_id=session.id,
        issue_id=issue.id,
        phase="architecture",
        title=f"架构 - {issue.title}",
        prompt="请基于当前需求产物进行架构设计。",
        role="architect",
        executor="codex",
        status="pending",
        workspace_path=str(tmp_path),
        created_at=pm_task.created_at,
        updated_at=pm_task.updated_at,
    )
    store = TransitionStoreStub(issue=issue, session=session, tasks=[pm_task, architect_task])
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-architecture")

    assert response.status_code == 200
    payload = response.json()
    assert payload["created"] is False
    assert payload["task"]["id"] == architect_task.id


def test_transition_to_architecture_rejects_running_issue_task(client, monkeypatch, tmp_path):
    session, issue, pm_task = build_issue_bundle(tmp_path)
    create_issue_artifacts(tmp_path, issue.id, {"requirement.md"})
    running_task = pm_task.model_copy(update={"id": "task-live-1", "status": "running"})
    store = TransitionStoreStub(issue=issue, session=session, tasks=[pm_task, running_task])
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-architecture")

    assert response.status_code == 409
    assert "运行" in response.json()["detail"]


def test_transition_to_architecture_rejects_missing_requirement_artifacts(client, monkeypatch, tmp_path):
    session, issue, pm_task = build_issue_bundle(tmp_path)
    store = TransitionStoreStub(issue=issue, session=session, tasks=[pm_task])
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-architecture")

    assert response.status_code == 409
    assert "需求产物" in response.json()["detail"]
