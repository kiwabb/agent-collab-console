from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.application.issue_artifact_documents import IssueArtifactDocuments
from app.domain.models import CodexIssue, CodexSession, CodexTask
import app.interfaces.api as api_module
from app.main import app


class TransitionStoreStub:
    def __init__(self, *, issue, session, tasks):
        self.issue = issue
        self.session = session
        self.tasks = {task.id: task for task in tasks}
        self.saved_issue = None
        self.saved_tasks = []

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
                "sequence_index": task.sequence_index,
                "sequence_group": task.sequence_group,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            })
        return result

    async def save_codex_task(self, task):
        self.tasks[task.id] = task
        self.saved_tasks.append(task)

    async def load_codex_task(self, task_id: str):
        return self.tasks.get(task_id)

    async def load_runtime_catalog(self):
        return None

    async def save_runtime_catalog(self, catalog):
        pass


@pytest.fixture
def client():
    return TestClient(app)


def _build_development_issue_bundle(tmp_path, *, engineer_statuses):
    """Build session, issue (in development phase), and engineer tasks with given statuses."""
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
        current_phase="development",
        status="open",
        created_at=now,
        updated_at=now,
    )
    engineer_tasks = []
    for idx, status in enumerate(engineer_statuses):
        engineer_tasks.append(
            CodexTask(
                id=f"task-eng-{idx}",
                session_id=session.id,
                issue_id=issue.id,
                phase="development",
                title=f"开发 - {issue.title} - Step {idx}",
                prompt=f"Implement step {idx}",
                role="engineer",
                executor="codex",
                status=status,
                workspace_path=str(tmp_path),
                sequence_index=idx,
                sequence_group=issue.id,
                created_at=now,
                updated_at=now,
            )
        )
    return session, issue, engineer_tasks


def _write_engineer_artifacts(tmp_path, issue_id: str, task_ids: list[str]):
    """Write implementation-<task_id>.md files via real IssueArtifactDocuments."""
    docs = IssueArtifactDocuments()
    for task_id in task_ids:
        path = docs.engineer_implementation_md_path(str(tmp_path), issue_id, task_id=task_id)
        path.write_text(f"# Implementation report for {task_id}\n", encoding="utf-8")


def test_transition_to_testing_creates_qa_task_when_all_engineer_tasks_done(client, monkeypatch, tmp_path):
    session, issue, engineer_tasks = _build_development_issue_bundle(tmp_path, engineer_statuses=["done", "done"])
    _write_engineer_artifacts(tmp_path, issue.id, [t.id for t in engineer_tasks])
    store = TransitionStoreStub(issue=issue, session=session, tasks=engineer_tasks)
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-testing")

    assert response.status_code == 200
    payload = response.json()
    assert payload["issue"]["current_phase"] == "testing"
    assert payload["created"] is True
    assert payload["task"] is not None
    assert payload["task"]["role"] == "qa"
    assert payload["task"]["phase"] == "testing"
    assert payload["task"]["title"].startswith("测试 - ")
    assert payload["task"]["issue_id"] == issue.id
    qa_tasks = [t for t in store.tasks.values() if t.role == "qa" and t.issue_id == issue.id]
    assert len(qa_tasks) == 1


def test_transition_to_testing_rejects_wrong_phase_requirements(client, monkeypatch, tmp_path):
    session, issue, engineer_tasks = _build_development_issue_bundle(tmp_path, engineer_statuses=["done"])
    issue.current_phase = "requirements"
    store = TransitionStoreStub(issue=issue, session=session, tasks=engineer_tasks)
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-testing")

    assert response.status_code == 409
    assert "开发或测试" in response.json()["detail"]


def test_transition_to_testing_rejects_wrong_phase_architecture(client, monkeypatch, tmp_path):
    session, issue, engineer_tasks = _build_development_issue_bundle(tmp_path, engineer_statuses=["done"])
    issue.current_phase = "architecture"
    store = TransitionStoreStub(issue=issue, session=session, tasks=engineer_tasks)
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-testing")

    assert response.status_code == 409
    assert "开发或测试" in response.json()["detail"]


def test_transition_to_testing_rejects_running_tasks(client, monkeypatch, tmp_path):
    session, issue, engineer_tasks = _build_development_issue_bundle(tmp_path, engineer_statuses=["done", "running"])
    _write_engineer_artifacts(tmp_path, issue.id, [t.id for t in engineer_tasks])
    store = TransitionStoreStub(issue=issue, session=session, tasks=engineer_tasks)
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-testing")

    assert response.status_code == 409
    assert "运行" in response.json()["detail"]


def test_transition_to_testing_rejects_unfinished_engineer_tasks(client, monkeypatch, tmp_path):
    session, issue, engineer_tasks = _build_development_issue_bundle(tmp_path, engineer_statuses=["done", "pending"])
    _write_engineer_artifacts(tmp_path, issue.id, [t.id for t in engineer_tasks])
    store = TransitionStoreStub(issue=issue, session=session, tasks=engineer_tasks)
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-testing")

    assert response.status_code == 409
    detail = response.json()["detail"]
    # Should mention the unfinished task title or the general unfinished signal
    assert "开发任务" in detail or "Step 1" in detail


def test_transition_to_testing_rejects_when_no_engineer_tasks(client, monkeypatch, tmp_path):
    session, issue, _ = _build_development_issue_bundle(tmp_path, engineer_statuses=[])
    store = TransitionStoreStub(issue=issue, session=session, tasks=[])
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-testing")

    assert response.status_code == 409
    assert "开发任务" in response.json()["detail"]


def test_transition_to_testing_rejects_missing_implementation_artifacts(client, monkeypatch, tmp_path):
    session, issue, engineer_tasks = _build_development_issue_bundle(tmp_path, engineer_statuses=["done"])
    # Note: NO implementation*.md written
    store = TransitionStoreStub(issue=issue, session=session, tasks=engineer_tasks)
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-testing")

    assert response.status_code == 409
    assert "implementation" in response.json()["detail"] or "开发产物" in response.json()["detail"]


def test_transition_to_testing_reuses_existing_qa_task(client, monkeypatch, tmp_path):
    session, issue, engineer_tasks = _build_development_issue_bundle(tmp_path, engineer_statuses=["done"])
    _write_engineer_artifacts(tmp_path, issue.id, [t.id for t in engineer_tasks])
    now = datetime.now()
    existing_qa = CodexTask(
        id="task-qa-existing",
        session_id=session.id,
        issue_id=issue.id,
        phase="testing",
        title=f"测试 - {issue.title}",
        prompt="请基于当前开发产物对该需求进行 QA 验收。",
        role="qa",
        executor="codex",
        status="pending",
        workspace_path=str(tmp_path),
        created_at=now,
        updated_at=now,
    )
    store = TransitionStoreStub(issue=issue, session=session, tasks=[*engineer_tasks, existing_qa])
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-testing")

    assert response.status_code == 200
    payload = response.json()
    assert payload["created"] is False
    assert payload["task"]["id"] == "task-qa-existing"
    qa_tasks = [t for t in store.tasks.values() if t.role == "qa" and t.issue_id == issue.id]
    assert len(qa_tasks) == 1


def test_transition_to_testing_idempotent_when_already_testing(client, monkeypatch, tmp_path):
    session, issue, engineer_tasks = _build_development_issue_bundle(tmp_path, engineer_statuses=["done"])
    issue.current_phase = "testing"
    _write_engineer_artifacts(tmp_path, issue.id, [t.id for t in engineer_tasks])
    now = datetime.now()
    existing_qa = CodexTask(
        id="task-qa-existing",
        session_id=session.id,
        issue_id=issue.id,
        phase="testing",
        title=f"测试 - {issue.title}",
        prompt="请基于当前开发产物对该需求进行 QA 验收。",
        role="qa",
        executor="codex",
        status="pending",
        workspace_path=str(tmp_path),
        created_at=now,
        updated_at=now,
    )
    store = TransitionStoreStub(issue=issue, session=session, tasks=[*engineer_tasks, existing_qa])
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-testing")

    assert response.status_code == 200
    payload = response.json()
    assert payload["issue"]["current_phase"] == "testing"
    assert payload["created"] is False
    assert payload["task"]["id"] == "task-qa-existing"


def test_transition_to_testing_returns_404_for_unknown_issue(client, monkeypatch, tmp_path):
    session, issue, engineer_tasks = _build_development_issue_bundle(tmp_path, engineer_statuses=["done"])
    store = TransitionStoreStub(issue=issue, session=session, tasks=engineer_tasks)
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post("/api/codex/issues/does-not-exist/transition-to-testing")

    assert response.status_code == 404
