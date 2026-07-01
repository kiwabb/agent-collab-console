"""Tests for /api/codex/tasks/{id}/send endpoint (P3) — auto chat/refine routing."""

import json  # noqa: I001
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.application.issue_artifact_documents import IssueArtifactDocuments
from app.domain.models import CodexSession, CodexTask, ExecutionProcess
import app.interfaces.api as api_module
from app.main import app


def _make_session(tmp_path):
    now = datetime.now()
    return CodexSession(id="ws-1", title="W", cwd=str(tmp_path), created_at=now, last_active_at=now)


def _make_task(*, role="product_manager", tmp_path, status="done"):
    now = datetime.now()
    return CodexTask(
        id="task-1",
        session_id="ws-1",
        issue_id="issue-1",
        phase="requirements",
        title="t",
        prompt="p",
        role=role,
        executor="codex",
        status=status,
        result="canonical-summary",
        workspace_path=str(tmp_path),
        resume_session_id="cli-1",
        created_at=now,
        updated_at=now,
    )


class SendStoreStub:
    def __init__(self, *, session, task):
        self.session = session
        self.task = task
        self.tasks = {task.id: task}
        self.execution_processes = {}
        self.messages = []

    async def load_codex_session(self, session_id):
        return self.session if session_id == self.session.id else None

    async def load_codex_workspace(self, session_id):
        return self.session if session_id == self.session.id else None

    async def load_codex_task(self, task_id):
        return self.tasks.get(task_id)

    async def save_codex_task(self, task):
        self.tasks[task.id] = task

    async def list_codex_tasks(self, session_id=None, issue_id=None):
        return []

    async def save_codex_task_message(self, msg):
        self.messages.append(msg)

    async def list_codex_task_messages(self, task_id, execution_process_id=None):
        return [m for m in self.messages if m.task_id == task_id]

    async def save_execution_process(self, ep):
        self.execution_processes[ep.id] = ep

    async def load_execution_process(self, ep_id):
        return self.execution_processes.get(ep_id)

    async def update_execution_process_status(self, *a, **kw):
        pass

    async def load_log_events(self, *a, **kw):
        return []

    async def load_runtime_catalog(self):
        return None

    async def save_runtime_catalog(self, catalog):
        pass


def _install_runner_stub(monkeypatch, store):
    captured = {}

    class _RunnerStub:
        async def start_task_run(
            self, task, *, kind="initial", triggering_message_id=None, prompt_override=None, **_
        ):
            captured.update({"kind": kind, "content": prompt_override})
            ep = ExecutionProcess(
                id=f"ep-send-{len(store.execution_processes) + 1}",
                task_id=task.id,
                session_id=task.session_id,
                status="Running",
                kind=kind,
                triggering_message_id=triggering_message_id,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            await store.save_execution_process(ep)
            task.last_execution_process_id = ep.id
            task.result = None  # avoid mock-mode persist
            return ep

    monkeypatch.setattr(api_module, "_get_task_runner", lambda: _RunnerStub())
    return captured


def _write_pm_artifact(tmp_path, issue_id):
    docs = IssueArtifactDocuments()
    docs.pm_prd_json_path(str(tmp_path), issue_id).write_text(
        json.dumps(
            {
                "language": "zh-CN",
                "project_name": "p",
                "issue_id": issue_id,
                "issue_title": "t",
                "original_requirements": "...",
                "product_goals": ["g"],
                "user_stories": [],
                "requirement_analysis": "x",
                "requirement_pool": [],
                "acceptance_criteria": [],
                "constraints": [],
                "open_questions": [],
                "risks": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


@pytest.fixture
def isolated_client():
    return TestClient(app)


def test_send_auto_routes_chat_input_to_chat(isolated_client, monkeypatch, tmp_path):
    session = _make_session(tmp_path)
    task = _make_task(tmp_path=tmp_path)
    store = SendStoreStub(session=session, task=task)
    monkeypatch.setattr(api_module, "codex_store", store)
    captured = _install_runner_stub(monkeypatch, store)

    response = isolated_client.post("/api/codex/tasks/task-1/send", json={"content": "你好"})
    assert response.status_code == 201, response.text
    payload = response.json()
    assert captured["kind"] == "chat"
    assert payload["resolved_mode"] == "chat"
    assert payload["execution_process"]["kind"] == "chat"


def test_send_auto_routes_refine_input_to_refine(isolated_client, monkeypatch, tmp_path):
    session = _make_session(tmp_path)
    task = _make_task(tmp_path=tmp_path)
    _write_pm_artifact(tmp_path, task.issue_id)
    store = SendStoreStub(session=session, task=task)
    monkeypatch.setattr(api_module, "codex_store", store)
    captured = _install_runner_stub(monkeypatch, store)

    response = isolated_client.post(
        "/api/codex/tasks/task-1/send",
        json={"content": "把 product_goals 加一条 X"},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert captured["kind"] == "refine"
    assert payload["resolved_mode"] == "refine"


def test_send_auto_refine_without_artifact_degrades_to_chat(isolated_client, monkeypatch, tmp_path):
    """Auto-detected refine but no canonical artifact exists yet → degrade to chat
    so the user is not blocked. The endpoint returns resolved_mode="chat" so the
    frontend can show a hint."""
    session = _make_session(tmp_path)
    task = _make_task(tmp_path=tmp_path)
    # No PM artifact written
    store = SendStoreStub(session=session, task=task)
    monkeypatch.setattr(api_module, "codex_store", store)
    captured = _install_runner_stub(monkeypatch, store)

    response = isolated_client.post(
        "/api/codex/tasks/task-1/send",
        json={"content": "加一条 risk"},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert captured["kind"] == "chat"
    assert payload["resolved_mode"] == "chat"


def test_send_force_mode_chat_ignores_refine_keyword(isolated_client, monkeypatch, tmp_path):
    session = _make_session(tmp_path)
    task = _make_task(tmp_path=tmp_path)
    _write_pm_artifact(tmp_path, task.issue_id)
    store = SendStoreStub(session=session, task=task)
    monkeypatch.setattr(api_module, "codex_store", store)
    captured = _install_runner_stub(monkeypatch, store)

    response = isolated_client.post(
        "/api/codex/tasks/task-1/send",
        json={"content": "改一下第3条", "force_mode": "chat"},
    )
    assert response.status_code == 201
    assert captured["kind"] == "chat"
    assert response.json()["resolved_mode"] == "chat"


def test_send_force_mode_refine_strict_rejects_when_no_artifact(
    isolated_client, monkeypatch, tmp_path
):
    """force_mode=refine is strict: 409 if no canonical artifact, unlike auto mode."""
    session = _make_session(tmp_path)
    task = _make_task(tmp_path=tmp_path)
    store = SendStoreStub(session=session, task=task)
    monkeypatch.setattr(api_module, "codex_store", store)
    _install_runner_stub(monkeypatch, store)

    response = isolated_client.post(
        "/api/codex/tasks/task-1/send",
        json={"content": "x", "force_mode": "refine"},
    )
    assert response.status_code == 409


def test_send_unknown_task_404(isolated_client, monkeypatch, tmp_path):
    session = _make_session(tmp_path)
    task = _make_task(tmp_path=tmp_path)
    store = SendStoreStub(session=session, task=task)
    monkeypatch.setattr(api_module, "codex_store", store)
    _install_runner_stub(monkeypatch, store)

    response = isolated_client.post(
        "/api/codex/tasks/missing/send",
        json={"content": "hi"},
    )
    assert response.status_code == 404
