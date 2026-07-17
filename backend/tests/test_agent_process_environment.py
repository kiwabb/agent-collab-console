from __future__ import annotations

from datetime import datetime

import pytest

from app.application.claude_process_runtime import ClaudeProcessRuntime
from app.application.codex_app_server_runtime import CodexAppServerRuntime
from app.domain.models import (
    CodexSession,
    CodexTask,
    CodexTaskMessage,
    ExecutionProcess,
    HelpRequest,
    LogEvent,
)


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

    async def update_execution_process_status(
        self,
        process_id: str,
        status: str,
        exit_code: int | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        return None

    async def load_execution_process(self, process_id: str) -> ExecutionProcess | None:
        return None

    async def list_codex_task_messages(
        self, task_id: str, execution_process_id: str | None = None
    ) -> list[CodexTaskMessage]:
        return []

    async def update_execution_process_usage(
        self,
        process_id: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_tokens: int | None = None,
        total_cost_usd: float | None = None,
    ) -> None:
        return None

    async def save_codex_task_message(self, message: CodexTaskMessage) -> None:
        return None

    async def load_help_request(self, help_request_id: str) -> HelpRequest | None:
        return None


class _LogStore:
    async def append_log_event(self, event: LogEvent) -> None:
        return None


class _FakeProcess:
    pid = 12345
    stdin = object()
    stdout = object()
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
    captured_args: tuple[object, ...] = ()

    async def fake_create_subprocess_exec(*args, **kwargs):
        nonlocal captured_args
        captured_args = args
        captured_env.update(kwargs["env"])
        return _FakeProcess()

    async def fake_reader_loop(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.application.claude_process_runtime.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(ClaudeProcessRuntime, "_reader_loop", fake_reader_loop)

    runtime = ClaudeProcessRuntime(codex_store=_Store(workspace, task), log_store=_LogStore())

    await runtime._spawn_process_async(
        workspace_id=workspace.id,
        resume_session_id=None,
        resume_message_id=None,
        task_id=task.id,
        waiter=None,
        cwd=str(tmp_path),
    )

    assert captured_env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert "--permission-mode=bypassPermissions" in captured_args
    assert "--permission-mode=dontAsk" not in captured_args


@pytest.mark.asyncio
async def test_claude_process_applies_restricted_prototype_permission_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    now = datetime.now()
    workspace = CodexSession(
        id="prototype-workspace",
        title="Prototype workspace",
        cwd=str(tmp_path),
        created_at=now,
        last_active_at=now,
    )
    task = CodexTask(
        id="prototype-task",
        session_id=workspace.id,
        project_id="project-1",
        title="Generate page",
        prompt="generate",
        role="prototype_ui_engineer",
        executor="claude",
        workspace_path=str(tmp_path),
        git_worktree_path=str(tmp_path),
        status="pending",
        created_at=now,
        updated_at=now,
    )
    captured_args: tuple[object, ...] = ()

    async def fake_create_subprocess_exec(*args, **kwargs):
        nonlocal captured_args
        del kwargs
        captured_args = args
        return _FakeProcess()

    async def fake_reader_loop(*args, **kwargs):
        del args, kwargs

    monkeypatch.setattr(
        "app.application.claude_process_runtime.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(ClaudeProcessRuntime, "_reader_loop", fake_reader_loop)

    runtime = ClaudeProcessRuntime(codex_store=_Store(workspace, task), log_store=_LogStore())
    restricted_args = [
        "--bare",
        "--setting-sources",
        "",
        "--tools",
        "Read,Glob,Grep",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--strict-mcp-config",
    ]

    await runtime._spawn_process_async(
        workspace_id=workspace.id,
        resume_session_id=None,
        resume_message_id=None,
        task_id=task.id,
        waiter=None,
        cwd=str(tmp_path),
        env_overrides={"ANTHROPIC_API_KEY": "test-only"},
        command_args=restricted_args,
    )

    assert captured_args.count("--permission-mode=dontAsk") == 1
    assert "--permission-mode=bypassPermissions" not in captured_args
    assert "project,local" not in captured_args
    for arg in restricted_args:
        assert arg in captured_args


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

    runtime = CodexAppServerRuntime(codex_store=_Store(workspace, task), log_store=_LogStore())

    await runtime._spawn_process_async(
        workspace_id=workspace.id,
        resume_session_id=None,
        task_id=task.id,
        prompt_text="verify",
        waiter=None,
        cwd=str(tmp_path),
    )
    output_task = runtime._processes[task.id].output_task
    assert output_task is not None
    await output_task

    assert captured_env["PYTHONDONTWRITEBYTECODE"] == "1"
