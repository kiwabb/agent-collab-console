from __future__ import annotations

from datetime import datetime

import pytest

from app.application.specialist_orchestrator import (
    SpecialistOrchestrator,
    SpecialistOrchestratorError,
)
from app.domain.models import CodexTask


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

    async def update_execution_process_status(self, execution_process_id: str, status: str, **kwargs):
        self.execution_updates.append(
            {"execution_process_id": execution_process_id, "status": status, **kwargs}
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
