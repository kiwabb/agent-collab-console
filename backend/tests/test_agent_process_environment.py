from __future__ import annotations

from datetime import datetime

import pytest

from app.application.claude_process_runtime import ClaudeProcessRuntime
from app.application.codex_app_server_runtime import CodexAppServerRuntime
from app.domain.models import CodexSession, CodexTask


class _Store:
    def __init__(self, workspace: CodexSession, task: CodexTask):
        self.workspace = workspace
        self.task = task

    async def load_codex_workspace(self, workspace_id: str):
        return self.workspace if workspace_id == self.workspace.id else None

    async def save_codex_workspace(self, workspace: CodexSession):
        self.workspace = workspace

    async def load_codex_task(self, task_id: str):
        return self.task if task_id == self.task.id else None

    async def save_codex_task(self, task: CodexTask):
        self.task = task


class _FakeProcess:
    pid = 12345
    stdin = None
    stdout = None
    stderr = None
    returncode = None


@pytest.mark.asyncio
async def test_claude_process_disables_python_bytecode_by_default(monkeypatch, tmp_path):
    now = datetime.now()
    workspace = CodexSession(
        id="workspace-1",
        title="Workspace",
        cwd=str(tmp_path),
        created_at=now,
        last_active_at=now,
    )
    task = CodexTask(
        id="task-1",
        session_id=workspace.id,
        project_id="project-1",
        issue_id="issue-1",
        title="QA",
        prompt="verify",
        role="qa",
        executor="claude",
        workspace_path=str(tmp_path),
        git_worktree_path=str(tmp_path),
        status="pending",
        created_at=now,
        updated_at=now,
    )
    captured_env: dict[str, str] = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured_env.update(kwargs["env"])
        return _FakeProcess()

    async def fake_reader_loop(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.application.claude_process_runtime.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(ClaudeProcessRuntime, "_reader_loop", fake_reader_loop)

    runtime = ClaudeProcessRuntime(codex_store=_Store(workspace, task), log_store=None)

    await runtime._spawn_process_async(
        workspace_id=workspace.id,
        resume_session_id=None,
        resume_message_id=None,
        task_id=task.id,
        waiter=None,
        cwd=str(tmp_path),
    )

    assert captured_env["PYTHONDONTWRITEBYTECODE"] == "1"


@pytest.mark.asyncio
async def test_codex_app_server_disables_python_bytecode_by_default(monkeypatch, tmp_path):
    now = datetime.now()
    workspace = CodexSession(
        id="workspace-1",
        title="Workspace",
        cwd=str(tmp_path),
        created_at=now,
        last_active_at=now,
    )
    task = CodexTask(
        id="task-1",
        session_id=workspace.id,
        project_id="project-1",
        issue_id="issue-1",
        title="QA",
        prompt="verify",
        role="qa",
        executor="codex",
        workspace_path=str(tmp_path),
        git_worktree_path=str(tmp_path),
        status="pending",
        created_at=now,
        updated_at=now,
    )
    captured_env: dict[str, str] = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured_env.update(kwargs["env"])
        return _FakeProcess()

    async def fake_handshake(*args, **kwargs):
        return None

    async def fake_thread_start(*args, **kwargs):
        return {"thread_id": "thread-1"}

    monkeypatch.setattr(
        "app.application.codex_app_server_runtime.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(
        "app.application.json_rpc_client.AsyncJsonRpcPeer.start",
        fake_handshake,
    )
    monkeypatch.setattr(
        "app.application.codex_app_server_runtime.CodexAppServerRuntime._initialize_or_fail_fast",
        fake_handshake,
    )
    monkeypatch.setattr(
        "app.application.codex_app_server_runtime.CodexAppServerRuntime._append_log",
        fake_handshake,
    )
    monkeypatch.setattr(
        "app.application.json_rpc_client.AppServerClient.thread_start",
        fake_thread_start,
    )
    monkeypatch.setattr(
        "app.application.json_rpc_client.AppServerClient.turn_start",
        fake_handshake,
    )

    runtime = CodexAppServerRuntime(codex_store=_Store(workspace, task), log_store=None)

    await runtime._spawn_process_async(
        workspace_id=workspace.id,
        resume_session_id=None,
        task_id=task.id,
        prompt_text="verify",
        waiter=None,
        cwd=str(tmp_path),
    )
    await runtime._processes[task.id].output_task

    assert captured_env["PYTHONDONTWRITEBYTECODE"] == "1"
