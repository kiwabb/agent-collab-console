from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

import pytest

from app.application.prototype_ui_engineer_runner import (
    PrototypeUiEngineerRunner,
    PrototypeUiEngineerRunnerError,
)
from app.domain.models import (
    CodexSession,
    CodexTask,
    ExecutionProcess,
    LogEvent,
    Project,
    RuntimeCatalog,
    RuntimeExecutorConfig,
)


class _Store:
    def __init__(self) -> None:
        self.tasks: dict[str, CodexTask] = {}
        self.workspaces: dict[str, CodexSession] = {}
        self.catalog = RuntimeCatalog(
            executors=[
                RuntimeExecutorConfig(
                    id="claude",
                    label="Claude Code",
                    enabled=True,
                    executor_type="claude",
                    api_endpoint="https://api.example.test/anthropic",
                    api_key="test-key",
                    default_model="test-model",
                )
            ]
        )

    async def load_runtime_catalog(self) -> RuntimeCatalog | None:
        return self.catalog

    async def save_runtime_catalog(self, catalog: RuntimeCatalog) -> None:
        self.catalog = catalog

    async def load_codex_workspace(self, workspace_id: str) -> CodexSession | None:
        return self.workspaces.get(workspace_id)

    async def save_codex_workspace(self, workspace: CodexSession) -> None:
        self.workspaces[workspace.id] = workspace

    async def list_codex_workspaces(
        self,
        project_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [
            {"id": workspace.id, "project_id": workspace.project_id}
            for workspace in self.workspaces.values()
            if project_id is None or workspace.project_id == project_id
        ]

    async def save_codex_task(self, task: CodexTask) -> None:
        self.tasks[task.id] = task

    async def load_codex_task(self, task_id: str) -> CodexTask | None:
        return self.tasks.get(task_id)

    async def load_log_events(
        self,
        session_id: str,
        task_id: str | None = None,
        execution_process_id: str | None = None,
        limit: int = 1000,
        reverse: bool = False,
    ) -> list[LogEvent]:
        del session_id, task_id, execution_process_id, limit, reverse
        return []


class _GitInspector:
    async def status_porcelain(self, worktree_path: str | Path) -> str:
        del worktree_path
        return ""

    async def worktree_diff(self, worktree_path: str | Path, base_branch: str) -> str:
        del worktree_path, base_branch
        return ""

    async def head_commit(self, worktree_path: str | Path) -> str:
        del worktree_path
        return "head-1"


class _WorktreeManager:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.git = _GitInspector()
        self.cleaned = False

    async def prepare_prototype_ui_engineer_worktree(
        self,
        project: Project,
        scope_id: str,
        *,
        source_paths: tuple[str, ...] = (),
    ) -> tuple[str, str, str]:
        del project, scope_id, source_paths
        return "prototype/test", str(self.root), "base-1"

    async def cleanup_prototype_ui_engineer_worktree(
        self,
        project: Project,
        scope_id: str,
    ) -> None:
        del project, scope_id
        self.cleaned = True


class _TaskRunner:
    def __init__(self, store: _Store, *, modify_source: bool = False) -> None:
        self.store = store
        self.modify_source = modify_source
        self.command_args: list[str] | None = None

    async def start_task_run(
        self,
        task: CodexTask,
        *,
        wait_for_completion: bool = False,
        execution_started_callback: Callable[[CodexTask, ExecutionProcess], Awaitable[None]]
        | None = None,
        command_args_override: list[str] | None = None,
    ) -> ExecutionProcess:
        assert wait_for_completion is True
        assert execution_started_callback is not None
        self.command_args = command_args_override
        now = datetime.now()
        process = ExecutionProcess(
            id="process-1",
            task_id=task.id,
            session_id=task.session_id,
            status="Running",
            executor="claude",
            started_at=now,
            created_at=now,
            updated_at=now,
        )
        task.last_execution_process_id = process.id
        task.status = "running"
        await self.store.save_codex_task(task)
        await execution_started_callback(task, process)
        if self.modify_source:
            (Path(task.workspace_path or "") / "src/page.tsx").write_text(
                "export const changed = true;\n",
                encoding="utf-8",
            )
        task.result = "submitted"
        task.status = "done"
        await self.store.save_codex_task(task)
        process.status = "Completed"
        process.exit_code = 0
        process.completed_at = datetime.now()
        return process


def _fixture(
    tmp_path: Path,
    *,
    modify_source: bool = False,
) -> tuple[PrototypeUiEngineerRunner, _Store, _TaskRunner, _WorktreeManager, Project]:
    worktree = tmp_path / "worktree"
    (worktree / "src").mkdir(parents=True)
    (worktree / "src/page.tsx").write_text("export const Page = 1;\n", encoding="utf-8")
    store = _Store()
    task_runner = _TaskRunner(store, modify_source=modify_source)
    manager = _WorktreeManager(worktree)
    runner = PrototypeUiEngineerRunner(
        store=store,
        task_runner=task_runner,
        worktree_manager=manager,
        claude_availability_probe=lambda: True,
    )
    project = Project(id="project-1", name="Demo", repo_path=str(tmp_path / "project"))
    return runner, store, task_runner, manager, project


@pytest.mark.asyncio
async def test_runner_fails_closed_when_runtime_launch_is_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "false")
    runner, _, _, _, _ = _fixture(tmp_path)

    with pytest.raises(PrototypeUiEngineerRunnerError, match="runtime launch is disabled"):
        await runner.ensure_available()


@pytest.mark.asyncio
async def test_runner_fails_closed_when_claude_cli_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "true")
    runner, _, _, _, _ = _fixture(tmp_path)
    runner.claude_availability_probe = lambda: False

    with pytest.raises(PrototypeUiEngineerRunnerError, match="available Claude CLI command"):
        await runner.ensure_available()


@pytest.mark.asyncio
async def test_runner_uses_scoped_identity_and_cleans_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "true")
    runner, store, task_runner, manager, project = _fixture(tmp_path)

    result = await runner.execute_scoped_task(
        project=project,
        scope_id="edit-run-1",
        prompt="Submit a structured prototype outcome.",
        source_paths=(),
        phase="prototype_ai_edit",
        task_kind="conversation_edit",
        task_title="Edit structured prototype",
        task_id="prototype-ai-task-1",
        mcp_config='{"mcpServers":{}}',
    )

    assert result.task_id == "prototype-ai-task-1"
    assert result.execution_process_id == "process-1"
    assert result.assistant_result == "submitted"
    task = store.tasks[result.task_id]
    assert task.role == "prototype_ui_engineer"
    assert task.executor == "claude"
    assert task.task_kind == "conversation_edit"
    assert task_runner.command_args == [
        "--mcp-config",
        '{"mcpServers":{}}',
        "--strict-mcp-config",
    ]
    assert manager.cleaned is True


@pytest.mark.asyncio
async def test_runner_rejects_project_source_edits_and_cleans_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "true")
    runner, _, _, manager, project = _fixture(tmp_path, modify_source=True)

    with pytest.raises(PrototypeUiEngineerRunnerError, match="modified project source"):
        await runner.execute_scoped_task(
            project=project,
            scope_id="generation-item-1",
            prompt="Submit one structured generation payload.",
            source_paths=("src/page.tsx",),
            phase="structured_prototype_generation",
            task_kind="generation_page",
            task_title="Generate structured prototype page",
            task_id="prototype-generation-task-1",
        )

    assert manager.cleaned is True
