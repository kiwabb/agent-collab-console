"""Tests for /api/codex/tasks/{id}/rerun endpoint (P4)."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.domain.models import CodexSession, CodexTask, ExecutionProcess
import app.interfaces.api as api_module
from app.main import app


@pytest.fixture
def isolated_client():
    return TestClient(app)


def _make_session(tmp_path):
    now = datetime.now()
    return CodexSession(id="ws-1", title="W", cwd=str(tmp_path), created_at=now, last_active_at=now)


def _make_task(*, status="done", phase="requirements", sequence_index=None, sequence_group=None, tmp_path=None):
    now = datetime.now()
    return CodexTask(
        id="task-1",
        session_id="ws-1",
        issue_id="issue-1",
        phase=phase,
        title="任务",
        prompt="原始 prompt",
        role="product_manager",
        executor="codex",
        status=status,
        result=None,
        workspace_path=str(tmp_path) if tmp_path else "/tmp",
        sequence_index=sequence_index,
        sequence_group=sequence_group,
        created_at=now,
        updated_at=now,
    )


class RerunStoreStub:
    def __init__(self, *, session, tasks):
        self.session = session
        self.tasks = {t.id: t for t in tasks}
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
        return [
            {"id": t.id, "session_id": t.session_id, "issue_id": t.issue_id, "status": t.status,
             "phase": t.phase, "role": t.role, "executor": t.executor,
             "sequence_index": t.sequence_index, "sequence_group": t.sequence_group}
            for t in self.tasks.values()
        ]

    async def save_codex_task_message(self, msg):
        self.messages.append(msg)

    async def list_codex_task_messages(self, task_id, execution_process_id=None):
        return []

    async def save_execution_process(self, ep):
        self.execution_processes[ep.id] = ep

    async def load_execution_process(self, ep_id):
        return self.execution_processes.get(ep_id)

    async def update_execution_process_status(self, *a, **kw):
        pass

    async def load_runtime_catalog(self):
        return None

    async def save_runtime_catalog(self, catalog):
        pass


def _install_runner_stub(monkeypatch, store):
    captured = {}

    class _RunnerStub:
        async def start_task_run(self, task, *, kind="initial", triggering_message_id=None,
                                  prompt_override=None, **_):
            captured.update({"kind": kind, "prompt_override": prompt_override, "task_prompt": task.prompt})
            ep = ExecutionProcess(
                id=f"ep-rerun-{len(store.execution_processes) + 1}",
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
            return ep

    monkeypatch.setattr(api_module, "_get_task_runner", lambda: _RunnerStub())
    return captured


def test_rerun_creates_ep_kind_rerun(isolated_client, monkeypatch, tmp_path):
    session = _make_session(tmp_path)
    task = _make_task(tmp_path=tmp_path)
    store = RerunStoreStub(session=session, tasks=[task])
    monkeypatch.setattr(api_module, "codex_store", store)
    captured = _install_runner_stub(monkeypatch, store)

    response = isolated_client.post("/api/codex/tasks/task-1/rerun")
    assert response.status_code == 201, response.text
    assert captured["kind"] == "rerun"


def test_rerun_uses_task_prompt_not_user_content(isolated_client, monkeypatch, tmp_path):
    """Rerun has no request body content; runner gets prompt_override=None so it
    falls back to task.prompt + role workflow build_prompt."""
    session = _make_session(tmp_path)
    task = _make_task(tmp_path=tmp_path)
    store = RerunStoreStub(session=session, tasks=[task])
    monkeypatch.setattr(api_module, "codex_store", store)
    captured = _install_runner_stub(monkeypatch, store)

    response = isolated_client.post("/api/codex/tasks/task-1/rerun")
    assert response.status_code == 201
    assert captured["prompt_override"] is None
    assert captured["task_prompt"] == "原始 prompt"


def test_rerun_rejects_running_task(isolated_client, monkeypatch, tmp_path):
    session = _make_session(tmp_path)
    task = _make_task(status="running", tmp_path=tmp_path)
    store = RerunStoreStub(session=session, tasks=[task])
    monkeypatch.setattr(api_module, "codex_store", store)

    class _RunnerStub:
        async def start_task_run(self, *a, **kw):
            raise ValueError("Task already running")

    monkeypatch.setattr(api_module, "_get_task_runner", lambda: _RunnerStub())

    response = isolated_client.post("/api/codex/tasks/task-1/rerun")
    assert response.status_code == 409


def test_rerun_blocked_by_development_sequencing(isolated_client, monkeypatch, tmp_path):
    """Rerun for development task with sequence_index>0 must check prev task done."""
    session = _make_session(tmp_path)
    prev = _make_task(tmp_path=tmp_path, phase="development", sequence_index=0, sequence_group="issue-1")
    prev.id = "task-prev"
    prev.status = "pending"  # NOT done
    me = _make_task(tmp_path=tmp_path, phase="development", sequence_index=1, sequence_group="issue-1")
    store = RerunStoreStub(session=session, tasks=[prev, me])
    monkeypatch.setattr(api_module, "codex_store", store)
    _install_runner_stub(monkeypatch, store)

    response = isolated_client.post("/api/codex/tasks/task-1/rerun")
    assert response.status_code == 409
    assert "上一个" in response.json()["detail"] or "previous" in response.json()["detail"].lower()


def test_rerun_unknown_task_404(isolated_client, monkeypatch, tmp_path):
    session = _make_session(tmp_path)
    task = _make_task(tmp_path=tmp_path)
    store = RerunStoreStub(session=session, tasks=[task])
    monkeypatch.setattr(api_module, "codex_store", store)
    _install_runner_stub(monkeypatch, store)

    response = isolated_client.post("/api/codex/tasks/missing/rerun")
    assert response.status_code == 404
