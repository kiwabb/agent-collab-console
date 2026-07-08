from __future__ import annotations

from datetime import datetime

import pytest

from app.application.role_concurrency import RoleConcurrencyLimiter
from app.application.specialist_orchestrator import (
    _SPECIALIST_ROLE_SLOTS_BY_CHILD,
    SpecialistOrchestrator,
    SpecialistOrchestratorError,
)
from app.domain.models import CodexIssue, CodexTask


@pytest.fixture(autouse=True)
def _reset_specialist_state():
    RoleConcurrencyLimiter._instance = None
    _SPECIALIST_ROLE_SLOTS_BY_CHILD.clear()
    yield
    RoleConcurrencyLimiter._instance = None
    _SPECIALIST_ROLE_SLOTS_BY_CHILD.clear()


class _EventBus:
    def __init__(self):
        self.events: list[dict] = []

    async def append(self, event: dict) -> None:
        self.events.append(event)


class _Store:
    def __init__(self):
        self.tasks: dict[str, CodexTask] = {}
        self.execution_updates: list[dict] = []

    async def save_codex_task(self, task: CodexTask) -> None:
        self.tasks[task.id] = task

    async def load_codex_task(self, task_id: str):
        return self.tasks.get(task_id)

    async def load_codex_issue(self, issue_id: str):
        return CodexIssue(
            id=issue_id,
            session_id="workspace-1",
            project_id="project-1",
            title="Issue",
            budget_usd=0.0,
            status="open",
        )

    async def list_codex_tasks(self, parent_task_id: str | None = None, issue_id: str | None = None):
        tasks = list(self.tasks.values())
        if parent_task_id is not None:
            tasks = [task for task in tasks if task.parent_task_id == parent_task_id]
        if issue_id is not None:
            tasks = [task for task in tasks if task.issue_id == issue_id]
        return tasks

    async def list_execution_processes(
        self, session_id: str | None = None, task_id: str | None = None
    ):
        return []

    async def update_execution_process_status(
        self, proc_id: str, status: str, completed_at: datetime | None = None
    ) -> None:
        self.execution_updates.append(
            {"execution_process_id": proc_id, "status": status, "completed_at": completed_at}
        )

    async def load_workflow_graph_for_issue(self, issue_id: str):
        return None

    async def save_agent_message(self, message):
        return None


class _FailingRunner:
    async def start_task_run(self, task: CodexTask):
        raise RuntimeError("specialist runtime unavailable")


def _parent_task() -> CodexTask:
    now = datetime.now()
    return CodexTask(
        id="parent-1",
        session_id="workspace-1",
        project_id="project-1",
        issue_id="issue-1",
        phase="engineer",
        title="Implement feature",
        prompt="Implement feature",
        role="engineer",
        status="running",
        result=None,
        workspace_path="/tmp/repo",
        git_worktree_path="/tmp/repo",
        git_branch="issue/feature",
        git_base_branch="main",
        last_execution_process_id="ep-parent",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_specialist_child_start_failure_marks_child_failed_and_parent_ready():
    store = _Store()
    bus = _EventBus()
    parent = _parent_task()
    await store.save_codex_task(parent)
    orchestrator = SpecialistOrchestrator(store, bus, _FailingRunner())

    with pytest.raises(SpecialistOrchestratorError):
        await orchestrator.request_specialist(
            parent_task=parent,
            specialist_role_key="specialist:security_reviewer",
            specialist_prompt="Review security",
            why="Sensitive auth path",
        )

    children = [task for task in store.tasks.values() if task.parent_task_id == parent.id]
    assert len(children) == 1
    child = children[0]
    assert child.status == "failed"
    assert "specialist runtime unavailable" in (child.result or "")
    assert store.tasks[parent.id].status == "ready_to_resume"
    assert store.tasks[parent.id].blocked_by_help_id is None
    assert "specialist runtime unavailable" in (store.tasks[parent.id].result or "")
    assert store.execution_updates[0]["execution_process_id"] == "ep-parent"
    assert store.execution_updates[0]["status"] == "Completed"
    task_status_events = [event for event in bus.events if event.get("type") == "task_status"]
    assert [event["task_id"] for event in task_status_events[-2:]] == [child.id, parent.id]
    assert [event["status"] for event in task_status_events[-2:]] == ["failed", "ready_to_resume"]
    assert task_status_events[-1]["role"] == "engineer"
    assert task_status_events[-2]["task_kind"] == "specialist_child"
    assert any(event.get("type") == "specialist_failed" for event in bus.events)
