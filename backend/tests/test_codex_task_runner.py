from __future__ import annotations

from datetime import datetime

import pytest

from app.application.codex_task_runner import CodexTaskRunner
from app.domain.models import CodexTask, HelpRequest


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
        updated_at=now,
    )
    orchestrator = _HelpOrchestrator()
    runner = CodexTaskRunner.__new__(CodexTaskRunner)
    runner.codex_store = _Store(help_request)
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
