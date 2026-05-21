"""Tests for task_dispatcher.dispatch_role."""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domain.models import Agent, CodexIssue, WorkflowGraph, WorkflowNode


def _make_agent(role_key="engineer") -> Agent:
    return Agent(
        id=f"agent-{role_key}",
        workspace_id=None,
        name=role_key.title(),
        role_key=role_key,
        system_prompt_template=f"[builtin:{role_key}]",
        default_executor="claude",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def _make_issue() -> CodexIssue:
    return CodexIssue(
        id=str(uuid4()),
        session_id="sess-001",
        project_id="proj-001",
        title="Fix the bug",
        description="There is a bug",
        status="open",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def _make_graph(issue_id: str) -> WorkflowGraph:
    return WorkflowGraph(
        id=str(uuid4()),
        issue_id=issue_id,
        dag_json="{}",
        status="running",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        nodes=[],
        edges=[],
    )


def _make_store(issue: CodexIssue, graph: WorkflowGraph, agents: list) -> MagicMock:
    store = MagicMock()
    store.list_agents = AsyncMock(return_value=agents)
    store.load_workflow_graph_for_issue = AsyncMock(return_value=graph)
    store.save_codex_task = AsyncMock()
    store.add_workflow_node = AsyncMock()
    store.add_workflow_edge = AsyncMock()
    store.load_codex_issue = AsyncMock(return_value=issue)
    return store


@pytest.mark.asyncio
async def test_dispatch_role_creates_task():
    """test_dispatch_role_creates_task: verify CodexTask created with correct role."""
    from app.application.task_dispatcher import dispatch_role

    issue = _make_issue()
    graph = _make_graph(issue.id)
    agent = _make_agent("engineer")
    store = _make_store(issue, graph, [agent])

    dispatched_tasks = []

    async def fake_dispatcher(task):
        dispatched_tasks.append(task)

    task_id, node_id = await dispatch_role(
        issue=issue,
        role="engineer",
        store=store,
        task_dispatcher_fn=fake_dispatcher,
    )

    # Task was saved
    store.save_codex_task.assert_called_once()
    created_task = store.save_codex_task.call_args[0][0]
    assert created_task.role == "engineer"
    assert created_task.issue_id == issue.id
    assert created_task.title == issue.title
    assert created_task.workflow_node_id == node_id

    # Graph was updated with new node
    store.add_workflow_node.assert_called_once()
    created_node = store.add_workflow_node.call_args[0][0]
    assert created_node.node_key == "engineer"
    assert created_node.task_id == task_id

    # Dispatcher was called
    assert len(dispatched_tasks) == 1
    assert dispatched_tasks[0].id == task_id


@pytest.mark.asyncio
async def test_dispatch_role_idempotent():
    """test_dispatch_role_idempotent: if existing done node found, returns existing task_id."""
    from app.application.task_dispatcher import dispatch_role

    issue = _make_issue()
    existing_task_id = str(uuid4())
    existing_node_id = str(uuid4())
    existing_node = WorkflowNode(
        id=existing_node_id,
        graph_id="graph-001",
        node_key="engineer",
        agent_id="agent-engineer",
        status="done",
        task_id=existing_task_id,
        created_at=datetime.now(),
    )
    graph = _make_graph(issue.id)
    graph.nodes = [existing_node]

    agent = _make_agent("engineer")
    store = _make_store(issue, graph, [agent])

    dispatcher_called = []

    async def fake_dispatcher(task):
        dispatcher_called.append(task)

    task_id, node_id = await dispatch_role(
        issue=issue,
        role="engineer",
        store=store,
        task_dispatcher_fn=fake_dispatcher,
    )

    # Returns existing task_id
    assert task_id == existing_task_id
    assert node_id == existing_node_id
    # No new task created
    store.save_codex_task.assert_not_called()
    # Dispatcher NOT called for idempotent path
    assert len(dispatcher_called) == 0


@pytest.mark.asyncio
async def test_dispatch_role_raises_without_agent():
    """Raises ValueError when no agent matches the requested role."""
    from app.application.task_dispatcher import dispatch_role

    issue = _make_issue()
    graph = _make_graph(issue.id)
    store = _make_store(issue, graph, agents=[])  # No agents

    with pytest.raises(ValueError, match="No agent found for role"):
        await dispatch_role(
            issue=issue,
            role="nonexistent_role",
            store=store,
            task_dispatcher_fn=None,
        )


@pytest.mark.asyncio
async def test_dispatch_role_adds_edge_for_prev_node():
    """Adds a sequence edge from prev_node_key to the new node."""
    from app.application.task_dispatcher import dispatch_role

    issue = _make_issue()
    graph = _make_graph(issue.id)
    agent = _make_agent("engineer")
    store = _make_store(issue, graph, [agent])

    await dispatch_role(
        issue=issue,
        role="engineer",
        prev_node_key="pm",
        store=store,
        task_dispatcher_fn=None,
    )

    store.add_workflow_edge.assert_called_once()
    edge = store.add_workflow_edge.call_args[0][0]
    assert edge.from_node_key == "pm"
    assert edge.to_node_key == "engineer"
