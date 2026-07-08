from __future__ import annotations

from datetime import datetime

import pytest

from app.application.task_completion_registry import TaskCompletionRegistry
from app.application.task_dispatcher import dispatch_role
from app.domain.models import Agent, CodexIssue, CodexTask, WorkflowGraph, WorkflowNode


@pytest.fixture(autouse=True)
def _reset_registry():
    TaskCompletionRegistry._instance = None
    yield
    TaskCompletionRegistry._instance = None


class _EventBus:
    def __init__(self):
        self.events: list[dict] = []

    async def append(self, event: dict) -> None:
        self.events.append(event)


class _Store:
    def __init__(self):
        self.agent = Agent(
            id="agent-engineer",
            name="Engineer",
            role_key="engineer",
            system_prompt_template="Fix it",
        )
        self.graph = WorkflowGraph(
            id="graph-1",
            issue_id="issue-1",
            dag_json="{}",
            status="running",
            nodes=[],
            edges=[],
        )
        self.saved_tasks: dict[str, CodexTask] = {}
        self.nodes: dict[str, WorkflowNode] = {}
        self.node_updates: list[dict] = []

    async def list_agents(self, workspace_id=None):
        return [self.agent]

    async def load_workflow_graph_for_issue(self, issue_id: str):
        return self.graph if issue_id == self.graph.issue_id else None

    async def save_codex_task(self, task: CodexTask):
        self.saved_tasks[task.id] = task

    async def add_workflow_node(self, node: WorkflowNode):
        self.nodes[node.id] = node
        self.graph.nodes.append(node)

    async def add_workflow_edge(self, edge):
        self.graph.edges.append(edge)

    async def save_agent_message(self, message):
        return None

    async def update_workflow_node(self, node_id: str, **fields):
        self.node_updates.append({"node_id": node_id, **fields})
        node = self.nodes[node_id]
        for key, value in fields.items():
            setattr(node, key, value)


@pytest.mark.asyncio
async def test_dispatch_role_runner_start_failure_signals_completion_and_marks_failed():
    store = _Store()
    bus = _EventBus()
    issue = CodexIssue(
        id="issue-1",
        session_id="workspace-1",
        project_id="project-1",
        title="Fix bug",
        git_branch="issue/fix-bug",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    async def failing_runner(task: CodexTask):
        raise RuntimeError("runner unavailable")

    task_id, node_id = await dispatch_role(
        issue=issue,
        role="engineer",
        prompt_override="Fix bug",
        store=store,
        task_dispatcher_fn=failing_runner,
        event_bus=bus,
        register_completion=True,
    )

    task = store.saved_tasks[task_id]
    result = await TaskCompletionRegistry.get().wait_for(task_id, timeout=0.1)

    assert isinstance(result, dict)
    assert node_id in store.nodes
    assert task.status == "failed"
    assert "runner unavailable" in (task.result or "")
    assert store.nodes[node_id].status == "failed"
    assert store.node_updates[-1]["status"] == "failed"
    assert result["status"] == "failed"
    assert result["task_id"] == task_id
    assert result["node_id"] == node_id
    task_status_events = [event for event in bus.events if event.get("type") == "task_status"]
    assert task_status_events[-1]["role"] == "engineer"
    assert task_status_events[-1]["task_kind"] == "normal"
    assert task_status_events[-1]["issue_id"] == issue.id
