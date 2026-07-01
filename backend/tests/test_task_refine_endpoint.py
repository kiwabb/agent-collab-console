"""Tests for /api/codex/tasks/{id}/refine endpoint (P3) — generic across 4 roles."""

import json  # noqa: I001
from datetime import datetime
from pathlib import Path  # noqa: F401

import pytest
from fastapi.testclient import TestClient

from app.application.issue_artifact_documents import IssueArtifactDocuments
from app.domain.models import CodexSession, CodexTask, ExecutionProcess
import app.interfaces.api as api_module
from app.main import app


def _make_session(tmp_path):
    now = datetime.now()
    return CodexSession(id="ws-1", title="W", cwd=str(tmp_path), created_at=now, last_active_at=now)


def _make_task(*, role: str, tmp_path, status="done"):
    now = datetime.now()
    return CodexTask(
        id="task-1",
        session_id="ws-1",
        issue_id="issue-1",
        phase=role,  # not strictly required
        title=f"{role} task",
        prompt=f"original {role} prompt",
        role=role,
        executor="codex",
        status=status,
        result="canonical-result-summary",
        workspace_path=str(tmp_path),
        resume_session_id="cli-1",
        resume_message_id=None,
        created_at=now,
        updated_at=now,
    )


class RefineStoreStub:
    def __init__(self, *, session, task):
        self.session = session
        self.task = task
        self.tasks = {task.id: task}
        self.execution_processes = {}
        self.messages = []

    async def load_codex_session(self, session_id: str):
        return self.session if session_id == self.session.id else None

    async def load_codex_workspace(self, session_id: str):
        return self.session if session_id == self.session.id else None

    async def load_codex_task(self, task_id: str):
        return self.tasks.get(task_id)

    async def save_codex_task(self, task):
        self.tasks[task.id] = task

    async def list_codex_tasks(self, session_id=None, issue_id=None):
        return []

    async def save_codex_task_message(self, msg):
        self.messages.append(msg)

    async def list_codex_task_messages(self, task_id, execution_process_id=None):
        result = [m for m in self.messages if m.task_id == task_id]
        if execution_process_id is not None:
            result = [m for m in result if m.execution_process_id == execution_process_id]
        return result

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


def _write_pm_artifact(tmp_path, issue_id):
    docs = IssueArtifactDocuments()
    p = docs.pm_prd_json_path(str(tmp_path), issue_id)
    p.write_text(
        json.dumps(
            {
                "language": "zh-CN",
                "project_name": "p",
                "issue_id": issue_id,
                "issue_title": "t",
                "original_requirements": "...",
                "product_goals": ["goal A"],
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


def _write_architect_artifact(tmp_path, issue_id):
    docs = IssueArtifactDocuments()
    docs.architect_system_design_json_path(str(tmp_path), issue_id).write_text(
        json.dumps({"modules": ["existing-A"]}), encoding="utf-8"
    )


def _write_engineer_artifact(tmp_path, issue_id, task_id):
    docs = IssueArtifactDocuments()
    docs.engineer_implementation_md_path(str(tmp_path), issue_id, task_id=task_id).write_text(
        "# Implementation report\nDone X.\n", encoding="utf-8"
    )


def _write_qa_artifact(tmp_path, issue_id):
    docs = IssueArtifactDocuments()
    docs.qa_plan_json_path(str(tmp_path), issue_id).write_text(
        json.dumps({"status": "passed", "test_scope": "scoped"}), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Endpoint shape: refine creates EP with kind=refine
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_client():
    return TestClient(app)


def _install_runner_stub(monkeypatch, store):
    captured = {}

    class _RunnerStub:
        async def start_task_run(
            self,
            task,
            *,
            kind="initial",
            triggering_message_id=None,
            prompt_override=None,
            resume_session_id=None,
            resume_message_id=None,
            **_,
        ):
            captured.update(
                {
                    "kind": kind,
                    "triggering_message_id": triggering_message_id,
                    "prompt_override": prompt_override,
                }
            )
            ep = ExecutionProcess(
                id="ep-refine-1",
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
            # In a real run the agent would write a new JSON artifact here;
            # for endpoint-shape tests we clear result so the mock-mode finalize
            # skips persist_result (which would otherwise reject our placeholder
            # task.result string as invalid PRD JSON).
            task.result = None
            return ep

    monkeypatch.setattr(api_module, "_get_task_runner", lambda: _RunnerStub())
    return captured


def test_refine_endpoint_creates_ep_kind_refine(isolated_client, monkeypatch, tmp_path):
    session = _make_session(tmp_path)
    task = _make_task(role="product_manager", tmp_path=tmp_path)
    _write_pm_artifact(tmp_path, task.issue_id)
    store = RefineStoreStub(session=session, task=task)
    monkeypatch.setattr(api_module, "codex_store", store)
    captured = _install_runner_stub(monkeypatch, store)

    response = isolated_client.post(
        "/api/codex/tasks/task-1/refine",
        json={"content": "把 product_goals 加一条「目标 B」"},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["execution_process"]["kind"] == "refine"
    assert captured["kind"] == "refine"
    assert captured["prompt_override"] == "把 product_goals 加一条「目标 B」"


def test_refine_rejects_when_no_canonical_artifact(isolated_client, monkeypatch, tmp_path):
    session = _make_session(tmp_path)
    task = _make_task(role="product_manager", tmp_path=tmp_path)
    # NO artifact written
    store = RefineStoreStub(session=session, task=task)
    monkeypatch.setattr(api_module, "codex_store", store)
    _install_runner_stub(monkeypatch, store)

    response = isolated_client.post(
        "/api/codex/tasks/task-1/refine",
        json={"content": "change X"},
    )
    assert response.status_code == 409
    assert "initial" in response.json()["detail"].lower() or "产物" in response.json()["detail"]


def test_refine_rejects_unknown_task(isolated_client, monkeypatch, tmp_path):
    session = _make_session(tmp_path)
    task = _make_task(role="product_manager", tmp_path=tmp_path)
    store = RefineStoreStub(session=session, task=task)
    monkeypatch.setattr(api_module, "codex_store", store)
    _install_runner_stub(monkeypatch, store)

    response = isolated_client.post(
        "/api/codex/tasks/does-not-exist/refine",
        json={"content": "x"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Prompt builder: refine branch includes existing artifact for each role
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_prompt_text_refine_includes_existing_pm_artifact(tmp_path):
    from app.application.codex_task_runner import CodexTaskRunner

    _write_pm_artifact(tmp_path, "issue-1")
    runner = CodexTaskRunner.__new__(CodexTaskRunner)
    runner._role_workflow_service = type(
        "S", (), {"is_managed_role": staticmethod(lambda r: True)}
    )()
    runner._CODEX_COLLABORATION_HINT = "(hint)"
    runner.codex_store = None

    task = _make_task(role="product_manager", tmp_path=tmp_path)
    out = await runner._build_prompt_text(
        task,
        prompt_text="加一条 goal B",
        prompt_override="加一条 goal B",
        resume_session_id="cli-1",
        resume_message_id=None,
        kind="refine",
    )
    assert "goal A" in out  # existing artifact embedded
    assert "加一条 goal B" in out
    assert "json" in out.lower()  # schema reminder


@pytest.mark.asyncio
async def test_build_prompt_text_refine_includes_existing_architect_artifact(tmp_path):
    from app.application.codex_task_runner import CodexTaskRunner

    _write_architect_artifact(tmp_path, "issue-1")
    runner = CodexTaskRunner.__new__(CodexTaskRunner)
    runner._role_workflow_service = type(
        "S", (), {"is_managed_role": staticmethod(lambda r: True)}
    )()
    runner._CODEX_COLLABORATION_HINT = "(hint)"
    runner.codex_store = None

    task = _make_task(role="architect", tmp_path=tmp_path)
    out = await runner._build_prompt_text(
        task,
        prompt_text="加模块 B",
        prompt_override="加模块 B",
        resume_session_id="cli-1",
        resume_message_id=None,
        kind="refine",
    )
    assert "existing-A" in out
    assert "加模块 B" in out


@pytest.mark.asyncio
async def test_build_prompt_text_refine_includes_existing_engineer_artifact(tmp_path):
    from app.application.codex_task_runner import CodexTaskRunner

    _write_engineer_artifact(tmp_path, "issue-1", task_id="task-1")
    runner = CodexTaskRunner.__new__(CodexTaskRunner)
    runner._role_workflow_service = type(
        "S", (), {"is_managed_role": staticmethod(lambda r: True)}
    )()
    runner._CODEX_COLLABORATION_HINT = "(hint)"
    runner.codex_store = None

    task = _make_task(role="engineer", tmp_path=tmp_path)
    out = await runner._build_prompt_text(
        task,
        prompt_text="加测试 X",
        prompt_override="加测试 X",
        resume_session_id="cli-1",
        resume_message_id=None,
        kind="refine",
    )
    assert "Done X" in out  # markdown content embedded
    assert "加测试 X" in out


@pytest.mark.asyncio
async def test_build_prompt_text_refine_includes_existing_qa_artifact(tmp_path):
    from app.application.codex_task_runner import CodexTaskRunner

    _write_qa_artifact(tmp_path, "issue-1")
    runner = CodexTaskRunner.__new__(CodexTaskRunner)
    runner._role_workflow_service = type(
        "S", (), {"is_managed_role": staticmethod(lambda r: True)}
    )()
    runner._CODEX_COLLABORATION_HINT = "(hint)"
    runner.codex_store = None

    task = _make_task(role="qa", tmp_path=tmp_path)
    out = await runner._build_prompt_text(
        task,
        prompt_text="改成 failed",
        prompt_override="改成 failed",
        resume_session_id="cli-1",
        resume_message_id=None,
        kind="refine",
    )
    assert "passed" in out  # existing status
    assert "改成 failed" in out


@pytest.mark.asyncio
async def test_build_prompt_text_refine_raises_when_no_artifact(tmp_path):
    """If no canonical artifact exists, refine prompt building must raise — the
    endpoint should have rejected before reaching this; defense in depth."""
    from app.application.codex_task_runner import CodexTaskRunner

    runner = CodexTaskRunner.__new__(CodexTaskRunner)
    runner._role_workflow_service = type(
        "S", (), {"is_managed_role": staticmethod(lambda r: True)}
    )()
    runner._CODEX_COLLABORATION_HINT = "(hint)"
    runner.codex_store = None

    task = _make_task(role="product_manager", tmp_path=tmp_path)
    with pytest.raises(Exception):  # noqa: B017
        await runner._build_prompt_text(
            task,
            prompt_text="x",
            prompt_override="x",
            resume_session_id=None,
            resume_message_id=None,
            kind="refine",
        )
