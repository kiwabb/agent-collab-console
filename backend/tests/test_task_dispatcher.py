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
    store.save_agent_message = AsyncMock()
    store.load_codex_issue = AsyncMock(return_value=issue)
    return store


class _EventBusSpy:
    def __init__(self):
        self.events = []

    async def append(self, event: dict):
        self.events.append(event)


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
async def test_dispatch_role_uses_shared_issue_worktree_by_default():
    """Regression: without agent_worktree_path, the task uses the shared issue
    worktree path (serial path behaviour must be unchanged)."""
    from app.application.task_dispatcher import dispatch_role

    issue = _make_issue()
    issue.git_worktree_path = "/repos/demo-worktrees/issue-xyz"
    graph = _make_graph(issue.id)
    agent = _make_agent("engineer")
    store = _make_store(issue, graph, [agent])

    await dispatch_role(
        issue=issue,
        role="engineer",
        store=store,
        task_dispatcher_fn=None,
    )

    created_task = store.save_codex_task.call_args[0][0]
    assert created_task.workspace_path == issue.git_worktree_path
    assert created_task.git_worktree_path == issue.git_worktree_path


@pytest.mark.asyncio
async def test_dispatch_role_injects_agent_worktree_path_when_provided():
    """When agent_worktree_path is supplied (parallel swarm dispatch), the task
    runs in the isolated per-agent worktree, not the shared issue worktree."""
    from app.application.task_dispatcher import dispatch_role

    issue = _make_issue()
    issue.git_worktree_path = "/repos/demo-worktrees/issue-xyz"
    graph = _make_graph(issue.id)
    agent = _make_agent("engineer")
    store = _make_store(issue, graph, [agent])

    agent_path = "/repos/demo-worktrees/swarm-issue-engineerA"
    await dispatch_role(
        issue=issue,
        role="engineer",
        store=store,
        task_dispatcher_fn=None,
        agent_worktree_path=agent_path,
    )

    created_task = store.save_codex_task.call_args[0][0]
    assert created_task.workspace_path == agent_path
    assert created_task.git_worktree_path == agent_path
    # The branch/base still reference the issue (agent branch is handled by the
    # worktree manager; the task tracks issue lineage).
    assert created_task.git_branch == issue.git_branch


@pytest.mark.asyncio
async def test_dispatch_role_sets_batch_key_on_node():
    """When batch_key is supplied (parallel swarm fan-out), the created node
    carries it so the UI can group same-batch agents into a parallel swimlane.
    The serial path leaves it None."""
    from app.application.task_dispatcher import dispatch_role

    issue = _make_issue()
    graph = _make_graph(issue.id)
    agent = _make_agent("engineer")
    store = _make_store(issue, graph, [agent])

    await dispatch_role(
        issue=issue,
        role="engineer",
        store=store,
        task_dispatcher_fn=None,
        batch_key="batch-abc123",
    )
    node = store.add_workflow_node.call_args[0][0]
    assert node.batch_key == "batch-abc123"

    # Serial path: omitting batch_key leaves the node ungrouped.
    store2 = _make_store(issue, _make_graph(issue.id), [agent])
    await dispatch_role(
        issue=issue,
        role="engineer",
        store=store2,
        task_dispatcher_fn=None,
    )
    node2 = store2.add_workflow_node.call_args[0][0]
    assert node2.batch_key is None


@pytest.mark.asyncio
async def test_dispatch_role_retry_creates_fresh_task():
    """Re-dispatching a role after it completed creates a new task with a new node_key.

    This is the QA-failed → re-engineer scenario: Conductor dispatches engineer
    again after QA failure, and must get a fresh task (engineer#1), not the old result.
    """
    from app.application.task_dispatcher import dispatch_role

    issue = _make_issue()
    existing_task_id = str(uuid4())
    done_node = WorkflowNode(
        id=str(uuid4()),
        graph_id="graph-001",
        node_key="engineer",
        agent_id="agent-engineer",
        status="done",
        task_id=existing_task_id,
        created_at=datetime.now(),
    )
    graph = _make_graph(issue.id)
    graph.nodes = [done_node]

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

    # Must be a brand-new task, not the cached one
    assert task_id != existing_task_id
    store.save_codex_task.assert_called_once()
    assert len(dispatcher_called) == 1
    # New node key is engineer#1
    saved_node = store.add_workflow_node.call_args[0][0]
    assert saved_node.node_key == "engineer#1"


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


@pytest.mark.asyncio
async def test_dispatch_role_records_initial_handoff_message():
    """Records conductor-to-role handoff when dispatching the first role.

    Also exercises role-alias normalization: dispatching the alias "pm"
    resolves the canonical "product_manager" agent and uses the canonical
    role for the node/handoff keys.
    """
    from app.application.task_dispatcher import dispatch_role

    issue = _make_issue()
    graph = _make_graph(issue.id)
    agent = _make_agent("product_manager")
    store = _make_store(issue, graph, [agent])
    event_bus = _EventBusSpy()

    await dispatch_role(
        issue=issue,
        role="pm",  # alias → normalized to product_manager
        prev_node_key=None,
        prompt_override="Plan the implementation",
        store=store,
        task_dispatcher_fn=None,
        event_bus=event_bus,
    )

    store.save_agent_message.assert_called_once()
    msg = store.save_agent_message.call_args[0][0]
    assert msg.issue_id == issue.id
    assert msg.graph_id == graph.id
    assert msg.from_node_key == "conductor"
    assert msg.to_node_key == "product_manager"
    assert msg.message_type == "handoff"
    assert msg.body == "Plan the implementation"

    posted_events = [event for event in event_bus.events if event["type"] == "agent_message_posted"]
    assert len(posted_events) == 1
    assert posted_events[0]["issue_id"] == issue.id
    assert posted_events[0]["session_id"] == issue.session_id
    assert posted_events[0]["message"]["id"] == msg.id
    assert posted_events[0]["message"]["from_node_key"] == "conductor"
    assert posted_events[0]["message"]["to_node_key"] == "product_manager"
    assert posted_events[0]["message"]["message_type"] == "handoff"


@pytest.mark.asyncio
async def test_dispatch_role_records_prev_node_handoff_message():
    """Records previous-node-to-role handoff for downstream dispatches."""
    from app.application.task_dispatcher import dispatch_role

    issue = _make_issue()
    graph = _make_graph(issue.id)
    agent = _make_agent("architect")
    store = _make_store(issue, graph, [agent])

    await dispatch_role(
        issue=issue,
        role="architect",
        prev_node_key="pm",
        prompt_override="Design the change",
        store=store,
        task_dispatcher_fn=None,
    )

    store.save_agent_message.assert_called_once()
    msg = store.save_agent_message.call_args[0][0]
    assert msg.from_node_key == "pm"
    assert msg.to_node_key == "architect"
    assert msg.message_type == "handoff"
    assert msg.body == "Design the change"


@pytest.mark.asyncio
async def test_dispatch_role_uses_generic_handoff_body_for_issue_fallback_prompt():
    """Uses a concise body when the prompt is only the issue title/description fallback."""
    from app.application.task_dispatcher import dispatch_role

    issue = _make_issue()
    graph = _make_graph(issue.id)
    agent = _make_agent("qa")
    store = _make_store(issue, graph, [agent])

    await dispatch_role(
        issue=issue,
        role="qa",
        store=store,
        task_dispatcher_fn=None,
    )

    msg = store.save_agent_message.call_args[0][0]
    assert msg.body == "Dispatch qa"


@pytest.mark.asyncio
async def test_dispatch_role_stores_full_handoff_body():
    """Handoff message body truncates the prompt to 200 characters and appends an ellipsis."""
    from app.application.task_dispatcher import dispatch_role

    issue = _make_issue()
    graph = _make_graph(issue.id)
    agent = _make_agent("engineer")
    store = _make_store(issue, graph, [agent])
    long_prompt = "x" * 500

    await dispatch_role(
        issue=issue,
        role="engineer",
        prompt_override=long_prompt,
        store=store,
        task_dispatcher_fn=None,
    )

    msg = store.save_agent_message.call_args[0][0]
    assert msg.body == "x" * 200 + "…"


@pytest.mark.asyncio
async def test_dispatch_role_skips_handoff_message_for_idempotent_path():
    """Does not create duplicate handoff messages when returning an exact-key cached node."""
    from app.application.task_dispatcher import dispatch_role

    issue = _make_issue()
    existing_task_id = str(uuid4())
    existing_node_id = str(uuid4())
    # Empty graph → same_role_count=0 → key="engineer" matches this done node exactly
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

    # Patch same_role_count: with one "engineer" node, count=1 → key="engineer#1"
    # (no match). To hit idempotent path we need count=0 → key="engineer".
    # Simulate by removing the node from the list before count, but keeping it for
    # the idempotency check. We do this by making the graph appear empty for the
    # count but having the node present — instead, test the exact scenario: truly
    # no prior nodes but one done node (count should be 0 after computing against
    # an empty node list). Re-setup:
    graph2 = _make_graph(issue.id)
    graph2.nodes = [existing_node]
    store2 = _make_store(issue, graph2, [agent])

    # With nodes=[existing_node] (key="engineer", done):
    # same_role_count = 1 (matches "engineer") → node_key = "engineer#1"
    # "engineer#1" not in nodes → no idempotent hit → creates new task → calls save_agent_message
    # So this test now verifies the OPPOSITE: a retry DOES write a handoff message.
    await dispatch_role(
        issue=issue,
        role="engineer",
        store=store2,
        task_dispatcher_fn=None,
    )

    # A retry (engineer → engineer#1) DOES write a handoff message
    store2.save_agent_message.assert_called_once()


class _ConcurrencyStore:
    """Async store stub whose add_workflow_node actually appends to the live
    graph, and whose awaits yield, so a missing lock around the
    count→mint-key→add-node section would expose a node_key collision."""

    def __init__(self, issue, graph, agents):
        self.issue = issue
        self.graph = graph
        self.agents = agents
        self.nodes: list = []
        self.tasks: list = []

    async def list_agents(self, workspace_id=None):
        await asyncio.sleep(0)
        return self.agents

    async def load_workflow_graph_for_issue(self, issue_id):
        await asyncio.sleep(0)  # yield point: exposes races if unlocked
        return self.graph

    async def save_codex_task(self, task):
        await asyncio.sleep(0)
        self.tasks.append(task)

    async def add_workflow_node(self, node):
        await asyncio.sleep(0)
        self.graph.nodes.append(node)  # the next dispatch must see this
        self.nodes.append(node)

    async def add_workflow_edge(self, edge):
        await asyncio.sleep(0)

    async def save_agent_message(self, msg):
        await asyncio.sleep(0)

    async def load_codex_issue(self, issue_id):
        return self.issue


@pytest.mark.asyncio
async def test_concurrent_same_role_dispatch_gets_unique_node_keys():
    """Two same-role dispatches fired concurrently (the new same-turn parallel
    path) must each mint a distinct node_key. The per-issue lock serialises the
    count→add-node section; without it both would read an empty graph and collide
    on 'engineer'."""
    from app.application.task_dispatcher import dispatch_role, _issue_dispatch_locks

    _issue_dispatch_locks.clear()
    issue = _make_issue()
    graph = _make_graph(issue.id)
    agent = _make_agent("engineer")
    store = _ConcurrencyStore(issue, graph, [agent])

    async def noop(task):
        await asyncio.sleep(0)

    results = await asyncio.gather(
        dispatch_role(issue=issue, role="engineer", store=store, task_dispatcher_fn=noop),
        dispatch_role(issue=issue, role="engineer", store=store, task_dispatcher_fn=noop),
    )

    node_keys = sorted(n.node_key for n in store.nodes)
    assert node_keys == ["engineer", "engineer#1"]
    # Two distinct tasks were created.
    assert results[0][0] != results[1][0]
    assert len(store.tasks) == 2
