from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import cast

import pytest

from app.application.codex_task_runner import CodexTaskRunner, TaskRunnerStore
from app.application.role_workflow_service import RoleWorkflowService
from app.domain.models import (
    CodexIssue,
    CodexSession,
    CodexTask,
    ExecutionProcess,
    HelpRequest,
    Project,
)


class _Store:
    def __init__(self, help_request: HelpRequest) -> None:
        self.help_request = help_request

    async def load_help_request(self, help_request_id: str) -> HelpRequest | None:
        if help_request_id == self.help_request.id:
            return self.help_request
        return None


class _HelpOrchestrator:
    def __init__(self) -> None:
        self.completed: list[tuple[str, str, str | None]] = []

    async def complete_help_request(
        self, help_request_id: str, *, child_status: str, child_result: str | None
    ) -> None:
        self.completed.append((help_request_id, child_status, child_result))


@pytest.mark.asyncio
async def test_help_child_completion_skips_resume_failed_request_with_case_and_spaces() -> None:
    now = datetime.now()
    task = CodexTask(
        id="child-1",
        session_id="workspace-1",
        title="Help child",
        prompt="Help",
        role="engineer",
        executor="codex",
        status="done",
        task_kind="help_child",
        blocked_by_help_id="help-1",
        result="child result",
        created_at=now,
        updated_at=now,
    )
    help_request = HelpRequest(
        id="help-1",
        workspace_id="workspace-1",
        parent_task_id="parent-1",
        child_task_id="child-1",
        source_executor="codex",
        target_executor="claude",
        title="Need help",
        prompt="Please investigate",
        status=" Resume_Failed ",
        created_at=now,
    )
    orchestrator = _HelpOrchestrator()
    runner = CodexTaskRunner.__new__(CodexTaskRunner)
    runner.codex_store = cast(TaskRunnerStore, _Store(help_request))
    runner._help_orchestrator_factory = lambda: orchestrator

    await runner._complete_help_child_if_needed(task)

    assert orchestrator.completed == []


@pytest.mark.asyncio
async def test_start_task_run_rejects_responding_task_with_case_and_spaces() -> None:
    task = CodexTask(
        id="task-1",
        session_id="workspace-1",
        title="Already active",
        prompt="Work",
        role="engineer",
        executor="codex",
        status=" Responding ",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    runner = CodexTaskRunner.__new__(CodexTaskRunner)

    with pytest.raises(ValueError, match="already running"):
        await runner.start_task_run(task)


class _RunStore:
    def __init__(self, task: CodexTask) -> None:
        self.task = task
        self.processes: dict[str, ExecutionProcess] = {}

    async def save_execution_process(self, process: ExecutionProcess) -> None:
        self.processes[process.id] = process

    async def save_codex_task(self, task: CodexTask) -> None:
        self.task = task

    async def load_codex_task(self, task_id: str) -> CodexTask | None:
        return self.task if self.task.id == task_id else None

    async def update_execution_process_status(
        self,
        process_id: str,
        status: str,
        exit_code: int | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        process = self.processes[process_id]
        process.status = status
        process.exit_code = exit_code
        process.completed_at = completed_at

    async def load_codex_workspace(self, workspace_id: str) -> CodexSession | None:
        return None

    async def load_help_request(self, help_request_id: str) -> HelpRequest | None:
        return None

    async def load_codex_issue(self, issue_id: str) -> CodexIssue | None:
        return None

    async def save_codex_issue(self, issue: CodexIssue) -> None:
        return None


class _RunEventBus:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def append(self, event: dict[str, object]) -> None:
        self.events.append(event)


class _RealManager:
    def __init__(self) -> None:
        self.wait: bool | None = None
        self.input_text: str | None = None

    async def write_input_async(
        self,
        session_id: str | None = None,
        input_text: str = "",
        **kwargs: object,
    ) -> str:
        del session_id
        self.input_text = input_text
        wait = kwargs.get("wait")
        self.wait = wait if isinstance(wait, bool) else None
        return "done"


class _UnrelatedMockManager:
    pass


class _ManagedPromptWorkflowService(RoleWorkflowService):
    def __init__(self, managed_prompt: str) -> None:
        self.managed_prompt = managed_prompt

    def is_managed_role(self, role: str | None) -> bool:
        return role == "product_manager"

    async def build_prompt(
        self,
        task: CodexTask,
        workspace_title: str | None = None,
        project_repo_path: str | None = None,
    ) -> str:
        del task, workspace_title, project_repo_path
        return self.managed_prompt


@pytest.mark.asyncio
async def test_start_task_run_can_explicitly_wait_for_real_runtime(monkeypatch) -> None:
    task = CodexTask(
        id="task-wait",
        session_id="workspace-1",
        project_id="project-1",
        title="Generate artifact",
        prompt="Write the staged artifact",
        role="prototype_ui_engineer",
        executor="claude",
        status="pending",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    store = _RunStore(task)
    event_bus = _RunEventBus()
    manager = _RealManager()

    async def refresh(_: CodexTask) -> object:
        return None

    runner = CodexTaskRunner(
        codex_store=cast(TaskRunnerStore, store),
        event_bus=event_bus,
        process_manager_factory=lambda: manager,
        mock_manager_cls=_UnrelatedMockManager,
        refresh_task_result=refresh,
    )

    async def resolve_config(
        _: CodexTask,
        run_executor: str | None = None,
        run_provider: str | None = None,
        run_model: str | None = None,
    ) -> tuple[str, str | None, str | None, dict[str, str] | None, list[str] | None, str]:
        del run_executor, run_provider, run_model
        return "claude", None, "MiniMax-M3", None, None, "claude"

    monkeypatch.setattr(runner, "_resolve_effective_config", resolve_config)
    started: list[tuple[str, str]] = []

    async def execution_started(
        started_task: CodexTask,
        process: ExecutionProcess,
    ) -> None:
        started.append((started_task.id, process.id))

    process = await runner.start_task_run(
        task,
        wait_for_completion=True,
        execution_started_callback=execution_started,
    )

    assert manager.wait is True
    assert started == [(task.id, process.id)]
    assert process.status == "Completed"
    assert store.task.status == "done"


class _ContextRunStore(_RunStore):
    def __init__(self, task: CodexTask, workspace: CodexSession, project: Project) -> None:
        super().__init__(task)
        self.workspace = workspace
        self.project = project
        self.workspace_load_count = 0
        self.project_load_count = 0

    async def load_codex_workspace(self, workspace_id: str) -> CodexSession | None:
        self.workspace_load_count += 1
        return self.workspace if self.workspace.id == workspace_id else None

    async def load_project(self, project_id: str) -> Project | None:
        self.project_load_count += 1
        return self.project if self.project.id == project_id else None


@pytest.mark.asyncio
async def test_start_task_run_sends_unmanaged_prototype_prompt_verbatim_with_team_notes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_path = tmp_path / "repo"
    notes_path = repo_path / ".agent-collab" / "team_notes.md"
    notes_path.parent.mkdir(parents=True)
    notes_path.write_text(
        "## Prior project memory\nTEAM_NOTES_MUST_NOT_REACH_PROTOTYPE_RUNTIME\n",
        encoding="utf-8",
    )
    prompt = (
        "Generate the prototype from the repository.\n"
        "Target route: /settings/feishu\n"
        "Artifact path: .agent-collab/prototype-staging/item-1/index.html"
    )
    task = CodexTask(
        id="prototype-task-wire-prompt",
        session_id="prototype-workspace",
        project_id="project-with-memory",
        title="Feishu settings",
        prompt=prompt,
        role="prototype_ui_engineer",
        executor="claude",
        status="pending",
        workspace_path=str(repo_path),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    workspace = CodexSession(
        id=task.session_id,
        project_id=task.project_id,
        title="WORKSPACE_CONTEXT_MUST_NOT_REACH_PROTOTYPE_RUNTIME",
        cwd=str(repo_path),
    )
    project = Project(
        id="project-with-memory",
        name="Project with memory",
        repo_path=str(repo_path),
    )
    store = _ContextRunStore(task, workspace, project)
    event_bus = _RunEventBus()
    manager = _RealManager()

    async def refresh(_: CodexTask) -> object:
        return None

    runner = CodexTaskRunner(
        codex_store=cast(TaskRunnerStore, store),
        event_bus=event_bus,
        process_manager_factory=lambda: manager,
        mock_manager_cls=_UnrelatedMockManager,
        refresh_task_result=refresh,
    )

    async def resolve_config(
        _: CodexTask,
        run_executor: str | None = None,
        run_provider: str | None = None,
        run_model: str | None = None,
    ) -> tuple[str, str | None, str | None, dict[str, str] | None, list[str] | None, str]:
        del run_executor, run_provider, run_model
        return "claude", "minimax", "MiniMax-M3", None, None, "claude"

    monkeypatch.setattr(runner, "_resolve_effective_config", resolve_config)

    await runner.start_task_run(task, wait_for_completion=True)

    assert manager.input_text == task.prompt
    assert manager.input_text == prompt
    assert store.workspace_load_count == 0
    assert store.project_load_count == 0


@pytest.mark.asyncio
async def test_start_task_run_sends_managed_role_prompt_without_transport_reframing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = CodexTask(
        id="managed-task-wire-prompt",
        session_id="managed-workspace",
        title="Define requirements",
        prompt="Original product request",
        role="product_manager",
        executor="codex",
        status="pending",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    store = _RunStore(task)
    manager = _RealManager()
    managed_prompt = "MANAGED ROLE PROMPT\nPreserve this exact final line."

    async def refresh(_: CodexTask) -> object:
        return None

    runner = CodexTaskRunner(
        codex_store=cast(TaskRunnerStore, store),
        event_bus=_RunEventBus(),
        process_manager_factory=lambda: manager,
        mock_manager_cls=_UnrelatedMockManager,
        refresh_task_result=refresh,
        role_workflow_service=_ManagedPromptWorkflowService(managed_prompt),
    )

    async def resolve_config(
        _: CodexTask,
        run_executor: str | None = None,
        run_provider: str | None = None,
        run_model: str | None = None,
    ) -> tuple[str, str | None, str | None, dict[str, str] | None, list[str] | None, str]:
        del run_executor, run_provider, run_model
        return "codex", None, "gpt-5", None, None, "codex"

    monkeypatch.setattr(runner, "_resolve_effective_config", resolve_config)

    await runner.start_task_run(task, wait_for_completion=True)

    assert manager.input_text == managed_prompt
