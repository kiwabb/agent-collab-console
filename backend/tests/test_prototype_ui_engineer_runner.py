from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.application.codex_task_runner import (
    CodexTaskExecutionTerminalEvidence,
    CodexTaskWireInputEvidence,
    ExecutionTerminalCallback,
    WireInputReadyCallback,
)
from app.application.prototype_ui_engineer_runner import (
    PrototypeUiEngineerActivity,
    PrototypeUiEngineerInstrumentationEvidence,
    PrototypeUiEngineerRunner,
    PrototypeUiEngineerRunnerError,
    PrototypeUiEngineerTaskCreatedEvidence,
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
from app.domain.structured_prototype_generation import PrototypeGenerationSourceSnapshot


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
        source_snapshot: PrototypeGenerationSourceSnapshot | None = None,
    ) -> tuple[str, str, str]:
        del project, scope_id, source_paths, source_snapshot
        return "prototype/test", str(self.root), "base-1"

    async def cleanup_prototype_ui_engineer_worktree(
        self,
        project: Project,
        scope_id: str,
    ) -> None:
        del project, scope_id
        self.cleaned = True


class _TaskRunner:
    def __init__(
        self,
        store: _Store,
        *,
        modify_source: bool = False,
        assistant_result: str | None = "submitted",
    ) -> None:
        self.store = store
        self.modify_source = modify_source
        self.assistant_result = assistant_result
        self.command_args: list[str] | None = None
        self.started = asyncio.Event()
        self.release_run: asyncio.Event | None = None

    async def start_task_run(
        self,
        task: CodexTask,
        *,
        wait_for_completion: bool = False,
        execution_started_callback: Callable[[CodexTask, ExecutionProcess], Awaitable[None]]
        | None = None,
        wire_input_ready_callback: WireInputReadyCallback | None = None,
        execution_terminal_callback: ExecutionTerminalCallback | None = None,
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
        assert wire_input_ready_callback is not None
        await wire_input_ready_callback(
            CodexTaskWireInputEvidence(
                task_id=task.id,
                execution_process_id=process.id,
                wire_input_hash="sha256:" + "a" * 64,
                wire_input_size=128,
                framing="claude-stream-json/user-message/v1",
                executor="claude",
                executor_type="claude",
                provider=None,
                model="test-model",
                runtime_config_hash="sha256:" + "b" * 64,
            )
        )
        self.started.set()
        if self.release_run is not None:
            await self.release_run.wait()
        if self.modify_source:
            (Path(task.workspace_path or "") / "src/page.tsx").write_text(
                "export const changed = true;\n",
                encoding="utf-8",
            )
        task.result = self.assistant_result
        task.status = "done"
        await self.store.save_codex_task(task)
        process.status = "Completed"
        process.exit_code = 0
        process.completed_at = datetime.now()
        assert execution_terminal_callback is not None
        await execution_terminal_callback(
            CodexTaskExecutionTerminalEvidence(
                task=task,
                process=process,
                task_status=task.status,
                result_hash="sha256:" + "c" * 64,
                result_size=len(self.assistant_result or ""),
            )
        )
        return process


def _fixture(
    tmp_path: Path,
    *,
    modify_source: bool = False,
    assistant_result: str | None = "submitted",
) -> tuple[PrototypeUiEngineerRunner, _Store, _TaskRunner, _WorktreeManager, Project]:
    worktree = tmp_path / "worktree"
    (worktree / "src").mkdir(parents=True)
    (worktree / "src/page.tsx").write_text("export const Page = 1;\n", encoding="utf-8")
    store = _Store()
    task_runner = _TaskRunner(
        store,
        modify_source=modify_source,
        assistant_result=assistant_result,
    )
    manager = _WorktreeManager(worktree)
    runner = PrototypeUiEngineerRunner(
        store=store,
        task_runner=task_runner,
        worktree_manager=manager,
        claude_availability_probe=lambda: True,
    )
    project = Project(id="project-1", name="Demo", repo_path=str(tmp_path / "project"))
    return runner, store, task_runner, manager, project


async def _accept_prepared(worktree: Path, task_id: str) -> None:
    del worktree, task_id


async def _accept_release() -> None:
    return None


async def _accept_instrumentation(
    evidence: PrototypeUiEngineerInstrumentationEvidence,
) -> None:
    del evidence


@pytest.mark.parametrize(
    ("task_kind", "built_in_tools", "allowed_tools"),
    [
        (
            "generation_blueprint",
            ("",),
            ("mcp__structured-prototype-generation__*",),
        ),
        (
            "generation_foundation",
            ("",),
            ("mcp__structured-prototype-generation__*",),
        ),
        (
            "generation_page",
            ("",),
            ("mcp__structured-prototype-generation__*",),
        ),
        ("conversation_edit", ("",), ("mcp__structured-prototype-ai__*",)),
    ],
)
def test_runner_builds_restricted_claude_tool_profile(
    task_kind: str,
    built_in_tools: tuple[str, ...],
    allowed_tools: tuple[str, ...],
) -> None:
    mcp_config = '{"mcpServers":{}}'

    assert PrototypeUiEngineerRunner._restricted_claude_args(task_kind, mcp_config) == [
        "--bare",
        "--setting-sources",
        "",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--no-chrome",
        "--tools",
        *built_in_tools,
        "--allowedTools",
        *allowed_tools,
        "--mcp-config",
        mcp_config,
        "--strict-mcp-config",
    ]


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
    activities: list[PrototypeUiEngineerActivity] = []

    async def record_activity(activity: PrototypeUiEngineerActivity) -> None:
        activities.append(activity)

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
        activity_callback=record_activity,
    )

    assert result.task_id == "prototype-ai-task-1"
    assert result.execution_process_id == "process-1"
    assert result.assistant_result == "submitted"
    task = store.tasks[result.task_id]
    assert task.role == "prototype_ui_engineer"
    assert task.executor == "claude"
    assert task.task_kind == "conversation_edit"
    assert task_runner.command_args == [
        "--bare",
        "--setting-sources",
        "",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--no-chrome",
        "--tools",
        "",
        "--allowedTools",
        "mcp__structured-prototype-ai__*",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--strict-mcp-config",
    ]
    assert activities
    assert all(activity.occurred_at.utcoffset() == UTC.utcoffset(None) for activity in activities)
    assert manager.cleaned is True


@pytest.mark.asyncio
async def test_task_created_callback_runs_after_task_save_and_before_process_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "true")
    runner, store, task_runner, manager, project = _fixture(tmp_path)
    seen: list[PrototypeUiEngineerTaskCreatedEvidence] = []

    async def reject_after_capture(
        evidence: PrototypeUiEngineerTaskCreatedEvidence,
    ) -> None:
        assert store.tasks[evidence.task_id] is evidence.task
        assert task_runner.started.is_set() is False
        seen.append(evidence)
        raise RuntimeError("operation step unavailable")

    with pytest.raises(
        PrototypeUiEngineerRunnerError,
        match="task-created persistence failed",
    ):
        await runner.execute_scoped_task(
            project=project,
            scope_id="generation-before-process",
            prompt="Submit one structured generation payload.",
            source_paths=(),
            phase="structured_prototype_generation",
            task_kind="generation_page",
            task_title="Generate structured prototype page",
            task_id="generation-before-process-task",
            mcp_config='{"mcpServers":{"token":"secret"}}',
            prepared_callback=_accept_prepared,
            release_callback=_accept_release,
            task_created_callback=reject_after_capture,
        )

    assert len(seen) == 1
    evidence = seen[0]
    assert evidence.task_id == "generation-before-process-task"
    assert evidence.worktree_path_contained is True
    assert evidence.worktree_base_commit == "base-1"
    assert evidence.runtime_profile.executor == "claude"
    assert evidence.runtime_profile.runtime_profile_hash.startswith("sha256:")
    assert evidence.runtime_profile.adapter_config_hash.startswith("sha256:")
    assert "secret" not in evidence.runtime_profile.adapter_config_hash
    assert task_runner.command_args is None
    assert manager.cleaned is True


@pytest.mark.asyncio
async def test_runner_accepts_empty_result_when_completion_callback_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "true")
    runner, _, task_runner, manager, project = _fixture(tmp_path, assistant_result=None)
    completions: list[tuple[Path, str, str]] = []
    prepared: list[tuple[Path, str]] = []
    releases: list[str] = []

    async def bind_prepared(worktree: Path, task_id: str) -> None:
        assert task_runner.command_args is None
        prepared.append((worktree, task_id))

    async def release_scope() -> None:
        assert manager.cleaned is False
        releases.append("released")

    async def accept_completion(worktree: Path, task_id: str, process_id: str) -> None:
        completions.append((worktree, task_id, process_id))

    result = await runner.execute_scoped_task(
        project=project,
        scope_id="generation-item-empty-result",
        prompt="Submit one structured generation payload.",
        source_paths=(),
        phase="structured_prototype_generation",
        task_kind="generation_page",
        task_title="Generate structured prototype page",
        task_id="prototype-generation-task-empty-result",
        mcp_config='{"mcpServers":{}}',
        prepared_callback=bind_prepared,
        release_callback=release_scope,
        completion_callback=accept_completion,
        instrumentation_callback=_accept_instrumentation,
    )

    assert result.assistant_result == ""
    assert completions == [
        (
            manager.root,
            "prototype-generation-task-empty-result",
            "process-1",
        )
    ]
    assert prepared == [(manager.root, "prototype-generation-task-empty-result")]
    assert releases == ["released"]
    assert task_runner.command_args == [
        "--bare",
        "--setting-sources",
        "",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--no-chrome",
        "--tools",
        "",
        "--allowedTools",
        "mcp__structured-prototype-generation__*",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--strict-mcp-config",
    ]
    assert manager.cleaned is True


@pytest.mark.asyncio
async def test_runner_fails_when_empty_result_completion_callback_rejects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "true")
    runner, _, _, manager, project = _fixture(tmp_path, assistant_result=None)

    async def reject_completion(worktree: Path, task_id: str, process_id: str) -> None:
        del worktree, task_id, process_id
        raise PrototypeUiEngineerRunnerError("structured submission is missing")

    with pytest.raises(PrototypeUiEngineerRunnerError, match="submission is missing"):
        await runner.execute_scoped_task(
            project=project,
            scope_id="generation-item-missing-submission",
            prompt="Submit one structured generation payload.",
            source_paths=(),
            phase="structured_prototype_generation",
            task_kind="generation_page",
            task_title="Generate structured prototype page",
            task_id="prototype-generation-task-missing-submission",
            mcp_config='{"mcpServers":{}}',
            prepared_callback=_accept_prepared,
            release_callback=_accept_release,
            completion_callback=reject_completion,
            instrumentation_callback=_accept_instrumentation,
        )

    assert manager.cleaned is True


@pytest.mark.asyncio
@pytest.mark.parametrize("task_kind", ["unknown", "prototype_generation"])
async def test_runner_rejects_unknown_task_kind_before_creating_workspace(
    tmp_path: Path,
    task_kind: str,
) -> None:
    runner, store, _, manager, project = _fixture(tmp_path)

    with pytest.raises(PrototypeUiEngineerRunnerError, match="no restricted runtime profile"):
        await runner.execute_scoped_task(
            project=project,
            scope_id="unsupported-task",
            prompt="Do something unsupported.",
            source_paths=(),
            phase="unsupported",
            task_kind=task_kind,
            task_title="Unsupported",
            task_id="unsupported-task-1",
            mcp_config='{"mcpServers":{}}',
        )

    assert store.workspaces == {}
    assert store.tasks == {}
    assert manager.cleaned is False


@pytest.mark.asyncio
async def test_runner_requires_scoped_mcp_before_creating_workspace(tmp_path: Path) -> None:
    runner, store, _, manager, project = _fixture(tmp_path)

    with pytest.raises(PrototypeUiEngineerRunnerError, match="scoped MCP configuration"):
        await runner.execute_scoped_task(
            project=project,
            scope_id="missing-mcp",
            prompt="Generate a page.",
            source_paths=(),
            phase="structured_prototype_generation",
            task_kind="generation_page",
            task_title="Generate page",
            task_id="missing-mcp-task",
            prepared_callback=_accept_prepared,
            release_callback=_accept_release,
            instrumentation_callback=_accept_instrumentation,
        )

    assert store.workspaces == {}
    assert store.tasks == {}
    assert manager.cleaned is False


@pytest.mark.asyncio
async def test_runner_requires_generation_repository_binding_before_workspace(
    tmp_path: Path,
) -> None:
    runner, store, task_runner, manager, project = _fixture(tmp_path)

    with pytest.raises(PrototypeUiEngineerRunnerError, match="prepared repository scope"):
        await runner.execute_scoped_task(
            project=project,
            scope_id="missing-repository-binding",
            prompt="Generate a page.",
            source_paths=(),
            phase="structured_prototype_generation",
            task_kind="generation_page",
            task_title="Generate page",
            task_id="missing-repository-binding-task",
            mcp_config='{"mcpServers":{}}',
        )

    assert store.workspaces == {}
    assert store.tasks == {}
    assert task_runner.command_args is None
    assert manager.cleaned is False


@pytest.mark.asyncio
async def test_runner_requires_generation_repository_release_before_workspace(
    tmp_path: Path,
) -> None:
    runner, store, task_runner, manager, project = _fixture(tmp_path)

    with pytest.raises(PrototypeUiEngineerRunnerError, match="scope release callback"):
        await runner.execute_scoped_task(
            project=project,
            scope_id="missing-repository-release",
            prompt="Generate a page.",
            source_paths=(),
            phase="structured_prototype_generation",
            task_kind="generation_page",
            task_title="Generate page",
            task_id="missing-repository-release-task",
            mcp_config='{"mcpServers":{}}',
            prepared_callback=_accept_prepared,
            instrumentation_callback=_accept_instrumentation,
        )

    assert store.workspaces == {}
    assert store.tasks == {}
    assert task_runner.command_args is None
    assert manager.cleaned is False


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
            mcp_config='{"mcpServers":{}}',
            prepared_callback=_accept_prepared,
            release_callback=_accept_release,
            instrumentation_callback=_accept_instrumentation,
        )

    assert manager.cleaned is True


@pytest.mark.asyncio
async def test_runner_cleans_worktree_when_repository_release_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "true")
    runner, _, _, manager, project = _fixture(tmp_path)

    async def fail_release() -> None:
        assert manager.cleaned is False
        raise RuntimeError("release failed")

    with pytest.raises(RuntimeError, match="release failed"):
        await runner.execute_scoped_task(
            project=project,
            scope_id="release-failure",
            prompt="Generate a page.",
            source_paths=(),
            phase="structured_prototype_generation",
            task_kind="generation_page",
            task_title="Generate page",
            task_id="release-failure-task",
            mcp_config='{"mcpServers":{}}',
            prepared_callback=_accept_prepared,
            release_callback=fail_release,
            instrumentation_callback=_accept_instrumentation,
        )

    assert manager.cleaned is True


@pytest.mark.asyncio
async def test_runner_drains_release_before_cleanup_during_repeated_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "true")
    runner, _, task_runner, manager, project = _fixture(tmp_path)
    task_runner.release_run = asyncio.Event()
    release_started = asyncio.Event()
    release_finished = asyncio.Event()

    async def release_scope() -> None:
        release_started.set()
        await release_finished.wait()
        assert manager.cleaned is False

    execution = asyncio.create_task(
        runner.execute_scoped_task(
            project=project,
            scope_id="cancelled-release",
            prompt="Generate a page.",
            source_paths=(),
            phase="structured_prototype_generation",
            task_kind="generation_page",
            task_title="Generate page",
            task_id="cancelled-release-task",
            mcp_config='{"mcpServers":{}}',
            prepared_callback=_accept_prepared,
            release_callback=release_scope,
            instrumentation_callback=_accept_instrumentation,
        )
    )
    await task_runner.started.wait()
    execution.cancel()
    task_runner.release_run.set()
    await release_started.wait()
    execution.cancel()
    await asyncio.sleep(0)
    assert manager.cleaned is False

    release_finished.set()
    with pytest.raises(asyncio.CancelledError):
        await execution
    assert manager.cleaned is True
