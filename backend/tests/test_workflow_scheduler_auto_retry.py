from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.workflow_scheduler import WorkflowScheduler
from app.domain.models import CodexIssue, CodexTask, WorkflowGraph, WorkflowNode


def _issue() -> CodexIssue:
    return CodexIssue(
        id="issue-1",
        session_id="sess-1",
        project_id="project-1",
        title="Fix flaky executor",
        description="Executor can fail during handshake.",
        git_branch="issue/fix-flaky-executor",
        git_base_branch="main",
        git_worktree_path="/tmp/issue-worktree",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def _failed_task(**overrides) -> CodexTask:
    base = dict(
        id="task-failed",
        session_id="sess-1",
        project_id="project-1",
        issue_id="issue-1",
        phase="engineer",
        title="Fix flaky executor",
        prompt="Patch the executor startup path.",
        role="engineer",
        executor="codex",
        provider="openai",
        model="gpt-5-codex",
        status="failed",
        result="executor failed to start",
        review_comment="previous feedback",
        workflow_node_id="node-1",
        git_branch="issue/fix-flaky-executor",
        git_base_branch="main",
        git_worktree_path="/tmp/issue-worktree",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    base.update(overrides)
    return CodexTask(**base)


def _node(*, retries: int = 0, max_retries: int = 1) -> WorkflowNode:
    return WorkflowNode(
        id="node-1",
        graph_id="graph-1",
        node_key="engineer",
        agent_id="agent-engineer",
        status="running",
        task_id="task-failed",
        retries=retries,
        max_retries=max_retries,
        started_at=datetime.now(),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def _graph(node: WorkflowNode) -> WorkflowGraph:
    return WorkflowGraph(
        id="graph-1",
        issue_id="issue-1",
        status="running",
        dag_json="{}",
        nodes=[node],
        edges=[],
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def _store(node: WorkflowNode, graph: WorkflowGraph, issue: CodexIssue):
    store = MagicMock()
    store.find_node_by_task_id = AsyncMock(return_value=node)
    store.load_workflow_graph = AsyncMock(return_value=graph)
    store.load_codex_issue = AsyncMock(return_value=issue)
    store.save_codex_task = AsyncMock()
    store.update_workflow_node = AsyncMock()
    store.list_agents = AsyncMock(return_value=[])
    store.save_codex_issue = AsyncMock()
    return store


def _event_bus(events: list[dict]):
    event_bus = MagicMock()
    event_bus.append = AsyncMock(side_effect=lambda event: events.append(event))
    return event_bus


@pytest.mark.asyncio
async def test_failed_workflow_task_auto_retries_once_before_marking_node_failed():
    issue = _issue()
    node = _node(retries=0, max_retries=1)
    graph = _graph(node)
    store = _store(node, graph, issue)
    events: list[dict] = []
    dispatched: list[CodexTask] = []

    async def dispatcher(task: CodexTask) -> None:
        dispatched.append(task)

    scheduler = WorkflowScheduler(store, task_dispatcher=dispatcher, event_bus=_event_bus(events))
    await scheduler.on_task_completed(_failed_task())

    assert len(dispatched) == 1
    retry_task = dispatched[0]
    assert retry_task.id != "task-failed"
    assert retry_task.parent_task_id == "task-failed"
    assert retry_task.workflow_node_id == "node-1"
    assert retry_task.role == "engineer"
    assert retry_task.prompt == "Patch the executor startup path."
    assert retry_task.executor == "codex"
    assert retry_task.provider == "openai"
    assert retry_task.model == "gpt-5-codex"
    assert "AUTO RETRY 1/1" in (retry_task.review_comment or "")
    assert "executor failed to start" in (retry_task.review_comment or "")
    store.save_codex_task.assert_awaited_once()
    assert store.save_codex_task.await_args.args[0] == retry_task

    store.update_workflow_node.assert_awaited_once_with(
        "node-1",
        status="running",
        task_id=retry_task.id,
        retries=1,
        completed_at=None,
        started_at=retry_task.created_at,
    )
    assert any(
        event.get("type") == "workflow_node_retrying"
        and event.get("previous_task_id") == "task-failed"
        and event.get("retry_task_id") == retry_task.id
        and event.get("retry") == 1
        and event.get("max_retries") == 1
        for event in events
    )
    assert any(
        event.get("type") == "task_status"
        and event.get("task_id") == retry_task.id
        and event.get("status") == "pending"
        for event in events
    )


@pytest.mark.asyncio
async def test_failed_workflow_task_marks_node_failed_when_retry_budget_exhausted():
    issue = _issue()
    node = _node(retries=1, max_retries=1)
    graph = _graph(node)
    store = _store(node, graph, issue)

    scheduler = WorkflowScheduler(store, task_dispatcher=AsyncMock(), event_bus=_event_bus([]))
    await scheduler.on_task_completed(_failed_task())

    store.save_codex_task.assert_not_called()
    store.update_workflow_node.assert_awaited_once()
    assert store.update_workflow_node.await_args.kwargs["status"] == "failed"
    assert store.update_workflow_node.await_args.kwargs["completed_at"] is not None


@pytest.mark.asyncio
async def test_failed_workflow_task_marks_node_failed_when_retry_dispatch_fails():
    issue = _issue()
    node = _node(retries=0, max_retries=1)
    graph = _graph(node)
    store = _store(node, graph, issue)
    events: list[dict] = []

    async def dispatcher(task: CodexTask) -> None:
        raise RuntimeError("runner unavailable")

    scheduler = WorkflowScheduler(store, task_dispatcher=dispatcher, event_bus=_event_bus(events))
    await scheduler.on_task_completed(_failed_task())

    assert store.save_codex_task.await_count == 2
    failed_retry_task = store.save_codex_task.await_args_list[-1].args[0]
    assert failed_retry_task.status == "failed"
    assert "runner unavailable" in (failed_retry_task.result or "")
    assert store.update_workflow_node.await_count == 2
    first_update = store.update_workflow_node.await_args_list[0]
    final_update = store.update_workflow_node.await_args_list[-1]
    assert first_update.kwargs["status"] == "running"
    assert final_update.kwargs["status"] == "failed"
    assert final_update.kwargs["task_id"] == "task-failed"
    assert final_update.kwargs["completed_at"] is not None
    assert any(
        event.get("type") == "workflow_node_retry_failed"
        and event.get("node_id") == "node-1"
        and "runner unavailable" in str(event.get("error"))
        for event in events
    )
