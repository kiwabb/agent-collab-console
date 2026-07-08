from __future__ import annotations

from datetime import datetime

import pytest

import app.application.conductor_tools as ct
from app.application import task_dispatcher
from app.application.role_concurrency import RoleConcurrencyLimiter
from app.application.task_completion_registry import TaskCompletionRegistry
from app.domain.models import CodexIssue, CodexTask, WorkflowGraph, WorkflowNode
from app.json_safety import object_dict


@pytest.fixture(autouse=True)
def _reset_singletons():
    TaskCompletionRegistry._instance = None
    RoleConcurrencyLimiter._instance = None
    yield
    TaskCompletionRegistry._instance = None
    RoleConcurrencyLimiter._instance = None


class _EventBus:
    def __init__(self):
        self.events: list[dict] = []

    async def append(self, event: dict) -> None:
        self.events.append(event)


class _ProcessManager:
    def __init__(self):
        self.terminated: list[str] = []

    async def terminate_task(self, task_id: str):
        self.terminated.append(task_id)


class _Store:
    def __init__(self):
        now = datetime.now()
        self.issue = CodexIssue(
            id="issue-1",
            session_id="workspace-1",
            project_id="project-1",
            title="Fix timeout",
            git_branch="issue/fix-timeout",
            created_at=now,
            updated_at=now,
        )
        self.task = CodexTask(
            id="task-timeout",
            session_id="workspace-1",
            project_id="project-1",
            issue_id="issue-1",
            phase="engineer",
            title="Fix timeout",
            prompt="Fix timeout",
            role="engineer",
            status="running",
            result=None,
            task_kind="normal",
            created_at=now,
            updated_at=now,
        )
        self.saved_tasks: list[CodexTask] = []
        self.node_updates: list[dict] = []

    async def load_codex_issue(self, issue_id: str):
        return self.issue if issue_id == self.issue.id else None

    async def load_workflow_graph_for_issue(self, issue_id: str):
        return WorkflowGraph(
            id="graph-1",
            issue_id=issue_id,
            dag_json="{}",
            nodes=[
                WorkflowNode(
                    id="node-timeout",
                    graph_id="graph-1",
                    node_key="engineer#1",
                    agent_id="agent-1",
                    status="running",
                    task_id="task-timeout",
                )
            ],
        )

    async def list_codex_tasks(self, issue_id=None):
        return []

    async def list_execution_processes(self, task_id=None):
        return []

    async def load_codex_task(self, task_id: str):
        return self.task if task_id == self.task.id else None

    async def save_codex_task(self, task: CodexTask):
        self.task = task
        self.saved_tasks.append(task)

    async def update_workflow_node(self, node_id: str, **fields):
        self.node_updates.append({"node_id": node_id, **fields})


@pytest.mark.asyncio
async def test_dispatch_subagent_timeout_terminates_task_and_marks_node_failed(monkeypatch):
    store = _Store()
    bus = _EventBus()
    process_manager = _ProcessManager()

    async def fake_dispatch_role(**kwargs):
        return "task-timeout", "node-timeout"

    async def fake_wait_for_active(self, task_id, *, idle_timeout, hard_timeout, activity_age):
        raise TimeoutError("idle timeout")

    import app.bootstrap as bootstrap_module

    monkeypatch.setattr(task_dispatcher, "dispatch_role", fake_dispatch_role)
    monkeypatch.setattr(TaskCompletionRegistry, "wait_for_active", fake_wait_for_active)
    monkeypatch.setattr(bootstrap_module, "get_codex_process_manager", lambda: process_manager)

    registry = ct.build_conductor_tools(
        project_id="project-1",
        store=store,
        event_bus=bus,
        task_dispatcher_fn=lambda task: None,
        issue_id="issue-1",
    )

    result = object_dict(
        await registry.tools["dispatch_subagent"]({"role": "engineer", "prompt": "Fix timeout"})
    )

    assert result["task_id"] == "task-timeout"
    assert result["role"] == "engineer"
    assert "subagent timed out" in str(result.get("error") or "")
    assert process_manager.terminated == ["task-timeout"]
    assert store.saved_tasks[-1].status == "failed"
    assert "subagent timed out" in (store.saved_tasks[-1].result or "")
    assert store.node_updates[-1]["node_id"] == "node-timeout"
    assert store.node_updates[-1]["status"] == "failed"
    node_events = [event for event in bus.events if event.get("type") == "workflow_node_updated"]
    assert node_events[-1]["node_id"] == "node-timeout"
    assert node_events[-1]["node_key"] == "engineer#1"
    assert node_events[-1]["batch_key"] is None
    task_status_events = [event for event in bus.events if event.get("type") == "task_status"]
    assert task_status_events[-1]["task_id"] == "task-timeout"
    assert task_status_events[-1]["role"] == "engineer"
    assert task_status_events[-1]["task_kind"] == "normal"
    assert task_status_events[-1]["status"] == "failed"
