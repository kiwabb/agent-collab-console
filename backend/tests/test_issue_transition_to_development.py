from datetime import datetime
import json

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
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            })
        return result

    async def save_codex_task(self, task):
        self.tasks[task.id] = task
        self.saved_tasks.append(task)

    async def load_codex_task(self, task_id: str):
        return self.tasks.get(task_id)


@pytest.fixture
def client():
    return TestClient(app)


def build_architecture_issue_bundle(tmp_path):
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
        current_phase="architecture",
        status="open",
        created_at=now,
        updated_at=now,
    )
    architect_task = CodexTask(
        id="task-arch-1",
        session_id=session.id,
        issue_id=issue.id,
        phase="architecture",
        title=f"架构 - {issue.title}",
        prompt="请基于当前需求产物进行架构设计。",
        role="architect",
        executor="codex",
        status="done",
        workspace_path=str(tmp_path),
        created_at=now,
        updated_at=now,
    )
    return session, issue, architect_task


def create_architecture_artifacts(tmp_path, issue_id: str, implementation_tasks: list[dict] | None = None):
    issue_root = tmp_path / "issues" / issue_id
    issue_root.mkdir(parents=True, exist_ok=True)
    (issue_root / "system_design.json").write_text("{}" if not implementation_tasks else json.dumps({"tasks": []}), encoding="utf-8")
    if implementation_tasks is not None:
        (issue_root / "implementation_plan.json").write_text(json.dumps(implementation_tasks), encoding="utf-8")
        # Also create development_task_list.json with same order
        task_titles = [task["title"] for task in implementation_tasks]
        (issue_root / "development_task_list.json").write_text(json.dumps(task_titles), encoding="utf-8")


def test_transition_to_development_updates_issue_and_creates_engineer_tasks(client, monkeypatch, tmp_path):
    session, issue, architect_task = build_architecture_issue_bundle(tmp_path)
    create_architecture_artifacts(
        tmp_path,
        issue.id,
        implementation_tasks=[
            {"title": "Build UI shell", "description": "Implement page layout", "priority": "P1"},
            {"title": "Wire API client", "description": "Connect fetch layer", "priority": "P1"},
        ],
    )
    store = TransitionStoreStub(issue=issue, session=session, tasks=[architect_task])
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-development")

    assert response.status_code == 200
    payload = response.json()
    assert payload["issue"]["current_phase"] == "development"
    assert payload["created"] is True
    assert len(payload["tasks"]) == 2
    assert payload["tasks"][0]["role"] == "engineer"
    assert payload["tasks"][0]["phase"] == "development"


def test_transition_to_development_rejects_missing_system_design_json(client, monkeypatch, tmp_path):
    session, issue, architect_task = build_architecture_issue_bundle(tmp_path)
    issue_root = tmp_path / "issues" / issue.id
    issue_root.mkdir(parents=True, exist_ok=True)
    (issue_root / "implementation_plan.json").write_text(
        json.dumps([{"title": "Build UI shell", "description": "Implement layout", "priority": "P1"}]),
        encoding="utf-8",
    )
    store = TransitionStoreStub(issue=issue, session=session, tasks=[architect_task])
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-development")

    assert response.status_code == 409
    assert "架构产物" in response.json()["detail"]


def test_transition_to_development_rejects_missing_implementation_plan_json(client, monkeypatch, tmp_path):
    session, issue, architect_task = build_architecture_issue_bundle(tmp_path)
    issue_root = tmp_path / "issues" / issue.id
    issue_root.mkdir(parents=True, exist_ok=True)
    (issue_root / "system_design.json").write_text("{}", encoding="utf-8")
    store = TransitionStoreStub(issue=issue, session=session, tasks=[architect_task])
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-development")

    assert response.status_code == 409
    assert "架构产物" in response.json()["detail"]


def test_transition_to_development_rejects_empty_implementation_plan(client, monkeypatch, tmp_path):
    session, issue, architect_task = build_architecture_issue_bundle(tmp_path)
    issue_root = tmp_path / "issues" / issue.id
    issue_root.mkdir(parents=True, exist_ok=True)
    (issue_root / "system_design.json").write_text("{}", encoding="utf-8")
    (issue_root / "implementation_plan.json").write_text("[]", encoding="utf-8")
    store = TransitionStoreStub(issue=issue, session=session, tasks=[architect_task])
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-development")

    assert response.status_code == 409
    assert "拆分" in response.json()["detail"]


def test_transition_to_development_reuses_existing_engineer_tasks(client, monkeypatch, tmp_path):
    session, issue, architect_task = build_architecture_issue_bundle(tmp_path)
    create_architecture_artifacts(
        tmp_path,
        issue.id,
        implementation_tasks=[{"title": "Build UI shell", "description": "Implement page layout", "priority": "P1"}],
    )
    existing = architect_task.model_copy(
        update={
            "id": "task-eng-1",
            "phase": "development",
            "role": "engineer",
            "title": f"开发 - {issue.title} - Build UI shell",
            "prompt": "Implement Build UI shell",
            "status": "pending",
        }
    )
    store = TransitionStoreStub(issue=issue, session=session, tasks=[architect_task, existing])
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-development")

    assert response.status_code == 200
    payload = response.json()
    assert payload["created"] is False
    assert len(payload["tasks"]) == 1
    assert payload["tasks"][0]["id"] == "task-eng-1"


def test_transition_to_development_rejects_missing_development_task_list_json(client, monkeypatch, tmp_path):
    """Verify transition fails when development_task_list.json is missing."""
    session, issue, architect_task = build_architecture_issue_bundle(tmp_path)
    issue_root = tmp_path / "issues" / issue.id
    issue_root.mkdir(parents=True, exist_ok=True)
    (issue_root / "system_design.json").write_text("{}", encoding="utf-8")
    (issue_root / "implementation_plan.json").write_text(
        json.dumps([{"title": "Build UI shell", "description": "Implement layout", "priority": "P1"}]),
        encoding="utf-8",
    )
    # Missing development_task_list.json
    store = TransitionStoreStub(issue=issue, session=session, tasks=[architect_task])
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-development")

    assert response.status_code == 409
    assert "development_task_list" in response.json()["detail"]


def test_transition_to_development_returns_tasks_with_sequence_fields(client, monkeypatch, tmp_path):
    """Verify transition returns tasks with correct sequence_index and sequence_group."""
    session, issue, architect_task = build_architecture_issue_bundle(tmp_path)
    issue_root = tmp_path / "issues" / issue.id
    issue_root.mkdir(parents=True, exist_ok=True)
    (issue_root / "system_design.json").write_text("{}", encoding="utf-8")
    (issue_root / "implementation_plan.json").write_text(
        json.dumps([
            {"title": "Build UI shell", "description": "Implement page layout", "priority": "P1"},
            {"title": "Wire API client", "description": "Connect fetch layer", "priority": "P1"},
            {"title": "Add error handling", "description": "Handle edge cases", "priority": "P2"},
        ]),
        encoding="utf-8",
    )
    (issue_root / "development_task_list.json").write_text(
        json.dumps(["Build UI shell", "Wire API client", "Add error handling"]),
        encoding="utf-8",
    )
    store = TransitionStoreStub(issue=issue, session=session, tasks=[architect_task])
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-development")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["tasks"]) == 3

    # Verify sequence fields
    for idx, task in enumerate(payload["tasks"]):
        assert task["sequence_index"] == idx, f"Task {idx} should have sequence_index={idx}"
        assert task["sequence_group"] == issue.id, f"Task {idx} should have sequence_group={issue.id}"

    # Verify order matches development_task_list.json
    assert payload["tasks"][0]["title"] == f"开发 - {issue.title} - Build UI shell"
    assert payload["tasks"][1]["title"] == f"开发 - {issue.title} - Wire API client"
    assert payload["tasks"][2]["title"] == f"开发 - {issue.title} - Add error handling"


def test_transition_to_development_respects_development_task_list_order(client, monkeypatch, tmp_path):
    """Verify transition respects development_task_list.json order, not implementation_plan.json order."""
    session, issue, architect_task = build_architecture_issue_bundle(tmp_path)
    issue_root = tmp_path / "issues" / issue.id
    issue_root.mkdir(parents=True, exist_ok=True)
    (issue_root / "system_design.json").write_text("{}", encoding="utf-8")
    # implementation_plan.json has one order
    (issue_root / "implementation_plan.json").write_text(
        json.dumps([
            {"title": "Task A", "description": "First in plan", "priority": "P1"},
            {"title": "Task B", "description": "Second in plan", "priority": "P1"},
            {"title": "Task C", "description": "Third in plan", "priority": "P1"},
        ]),
        encoding="utf-8",
    )
    # development_task_list.json has different order
    (issue_root / "development_task_list.json").write_text(
        json.dumps(["Task C", "Task A", "Task B"]),  # Different order
        encoding="utf-8",
    )
    store = TransitionStoreStub(issue=issue, session=session, tasks=[architect_task])
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-development")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["tasks"]) == 3

    # Verify order matches development_task_list.json, NOT implementation_plan.json
    assert payload["tasks"][0]["title"] == f"开发 - {issue.title} - Task C"
    assert payload["tasks"][0]["sequence_index"] == 0
    assert payload["tasks"][1]["title"] == f"开发 - {issue.title} - Task A"
    assert payload["tasks"][1]["sequence_index"] == 1
    assert payload["tasks"][2]["title"] == f"开发 - {issue.title} - Task B"
    assert payload["tasks"][2]["sequence_index"] == 2


def test_transition_to_development_rejects_duplicate_titles_in_development_task_list(client, monkeypatch, tmp_path):
    """Verify transition fails when development_task_list.json has duplicate titles."""
    session, issue, architect_task = build_architecture_issue_bundle(tmp_path)
    issue_root = tmp_path / "issues" / issue.id
    issue_root.mkdir(parents=True, exist_ok=True)
    (issue_root / "system_design.json").write_text("{}", encoding="utf-8")
    (issue_root / "implementation_plan.json").write_text(
        json.dumps([
            {"title": "Build UI shell", "description": "Implement layout", "priority": "P1"},
            {"title": "Wire API client", "description": "Connect fetch", "priority": "P1"},
        ]),
        encoding="utf-8",
    )
    # development_task_list.json has duplicate
    (issue_root / "development_task_list.json").write_text(
        json.dumps(["Build UI shell", "Build UI shell"]),  # Duplicate
        encoding="utf-8",
    )
    store = TransitionStoreStub(issue=issue, session=session, tasks=[architect_task])
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-development")

    assert response.status_code == 409
    assert "重复" in response.json()["detail"] or "duplicate" in response.json()["detail"].lower()


def test_transition_to_development_rejects_mismatched_development_task_list(client, monkeypatch, tmp_path):
    """Verify transition fails when development_task_list.json doesn't match implementation_plan.json."""
    session, issue, architect_task = build_architecture_issue_bundle(tmp_path)
    issue_root = tmp_path / "issues" / issue.id
    issue_root.mkdir(parents=True, exist_ok=True)
    (issue_root / "system_design.json").write_text("{}", encoding="utf-8")
    (issue_root / "implementation_plan.json").write_text(
        json.dumps([
            {"title": "Build UI shell", "description": "Implement layout", "priority": "P1"},
            {"title": "Wire API client", "description": "Connect fetch", "priority": "P1"},
        ]),
        encoding="utf-8",
    )
    # development_task_list.json has unknown title
    (issue_root / "development_task_list.json").write_text(
        json.dumps(["Build UI shell", "Unknown Task"]),  # "Unknown Task" not in implementation_plan
        encoding="utf-8",
    )
    store = TransitionStoreStub(issue=issue, session=session, tasks=[architect_task])
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-development")

    assert response.status_code == 409
    assert "不匹配" in response.json()["detail"] or "mismatch" in response.json()["detail"].lower() or "match" in response.json()["detail"].lower()

def test_transition_to_development_rejects_duplicate_titles_in_implementation_plan(client, monkeypatch, tmp_path):
    """Verify transition fails when implementation_plan.json has duplicate titles."""
    session, issue, architect_task = build_architecture_issue_bundle(tmp_path)
    issue_root = tmp_path / "issues" / issue.id
    issue_root.mkdir(parents=True, exist_ok=True)
    (issue_root / "system_design.json").write_text("{}", encoding="utf-8")
    (issue_root / "implementation_plan.json").write_text(
        json.dumps([
            {"title": "Build UI shell", "description": "Implement layout", "priority": "P1"},
            {"title": "Build UI shell", "description": "Duplicate title", "priority": "P1"},  # Duplicate
        ]),
        encoding="utf-8",
    )
    (issue_root / "development_task_list.json").write_text(
        json.dumps(["Build UI shell"]),
        encoding="utf-8",
    )
    store = TransitionStoreStub(issue=issue, session=session, tasks=[architect_task])
    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.post(f"/api/codex/issues/{issue.id}/transition-to-development")

    assert response.status_code == 409
    assert "重复" in response.json()["detail"] or "duplicate" in response.json()["detail"].lower()
