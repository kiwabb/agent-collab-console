"""Phase 2 — executor result closed loop.

GAP E: a schema-invalid artifact must be signaled to the Conductor as
`artifact_invalid` (not `done`) and emit a structured event.
GAP G: the Conductor must not re-dispatch the same role past its budget.
"""

from __future__ import annotations  # noqa: I001

from datetime import datetime

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.application.task_completion_registry import TaskCompletionRegistry
from app.application.workflow_scheduler import WorkflowScheduler
from app.domain.models import CodexTask, WorkflowGraph, WorkflowNode


def _task(**kw) -> CodexTask:
    base = dict(
        id="task-e",
        session_id="sess-1",
        issue_id="issue-1",
        title="Issue",
        prompt="Do work",
        role="engineer",
        status="done",
        result='{"wrong":"schema"}',
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    base.update(kw)
    t = CodexTask(**base)
    return t


def _node() -> WorkflowNode:
    return WorkflowNode(id="node-1", graph_id="graph-1", node_key="engineer", agent_id="agent-eng")


def _graph() -> WorkflowGraph:
    return WorkflowGraph(
        id="graph-1",
        issue_id="issue-1",
        dag_json="{}",
        status="running",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        nodes=[],
        edges=[],
    )


def _scheduler_store(node, graph):
    store = MagicMock()
    store.find_node_by_task_id = AsyncMock(return_value=node)
    store.update_workflow_node = AsyncMock()
    store.load_workflow_graph = AsyncMock(return_value=graph)
    store.load_codex_issue = AsyncMock(return_value=MagicMock(id="issue-1", session_id="sess-1"))
    # _maybe_advance_phase runs after the signal; stub its store calls.
    store.list_agents = AsyncMock(return_value=[])
    return store


@pytest.mark.asyncio
async def test_validation_failure_signals_artifact_invalid_and_emits_event():
    TaskCompletionRegistry._instance = None
    reg = TaskCompletionRegistry.get()

    task = _task(workflow_node_id="node-1")
    # Simulate api._refresh_task_result attaching the marker on schema failure.
    task._validation_error = {
        "type": "ValidationError",
        "message": "missing changed_files",
        "role": "engineer",
    }
    node = _node()
    graph = _graph()
    store = _scheduler_store(node, graph)

    events: list[dict] = []
    event_bus = MagicMock()
    event_bus.append = AsyncMock(side_effect=lambda e: events.append(e))

    reg.register(task.id)
    sched = WorkflowScheduler(store, event_bus=event_bus)
    await sched.on_task_completed(task)

    # Conductor is signaled with artifact_invalid + the validation_error detail.
    signaled = reg._results[task.id]
    assert signaled["status"] == "artifact_invalid"
    assert signaled["validation_error"]["type"] == "ValidationError"
    # Structured observability event emitted.
    assert any(
        e.get("type") == "artifact_validation_failed" and e.get("role") == "engineer"
        for e in events
    )


@pytest.mark.asyncio
async def test_valid_artifact_signals_done():
    TaskCompletionRegistry._instance = None
    reg = TaskCompletionRegistry.get()

    task = _task(workflow_node_id="node-1", result="ok")  # no _validation_error
    node = _node()
    graph = _graph()
    store = _scheduler_store(node, graph)

    event_bus = MagicMock()
    event_bus.append = AsyncMock()

    reg.register(task.id)
    sched = WorkflowScheduler(store, event_bus=event_bus)
    await sched.on_task_completed(task)

    assert reg._results[task.id]["status"] == "done"


# --- GAP G: per-role dispatch cap ---------------------------------------


@pytest.mark.asyncio
async def test_dispatch_subagent_returns_retries_exhausted_at_cap(monkeypatch):
    monkeypatch.setenv("CONDUCTOR_MAX_DISPATCHES_PER_ROLE", "3")
    from app.application.conductor_tools import build_conductor_tools

    # Graph already has 3 engineer nodes (engineer, engineer#1, engineer#2).
    graph = _graph()
    graph.nodes = [
        WorkflowNode(id="n0", graph_id="graph-1", node_key="engineer", agent_id="a"),
        WorkflowNode(id="n1", graph_id="graph-1", node_key="engineer#1", agent_id="a"),
        WorkflowNode(id="n2", graph_id="graph-1", node_key="engineer#2", agent_id="a"),
    ]
    store = MagicMock()
    store.load_codex_issue = AsyncMock(return_value=MagicMock(id="issue-1"))
    store.load_workflow_graph_for_issue = AsyncMock(return_value=graph)

    dispatched = {"called": False}

    async def fake_dispatcher(*a, **k):
        dispatched["called"] = True
        return ("task-new", "node-new")

    registry = build_conductor_tools(
        project_id="proj-1",
        store=store,
        event_bus=None,
        task_dispatcher_fn=fake_dispatcher,
        issue_id="issue-1",
    )
    result = await registry.tools["dispatch_subagent"]({"role": "engineer"})

    assert result["status"] == "retries_exhausted"
    assert result["dispatches"] == 3
    assert result["max_dispatches"] == 3


@pytest.mark.asyncio
async def test_dispatch_subagent_proceeds_under_cap(monkeypatch):
    monkeypatch.setenv("CONDUCTOR_MAX_DISPATCHES_PER_ROLE", "4")
    from app.application.conductor_tools import build_conductor_tools

    graph = _graph()
    graph.nodes = [WorkflowNode(id="n0", graph_id="graph-1", node_key="engineer", agent_id="a")]
    store = MagicMock()
    store.load_codex_issue = AsyncMock(return_value=MagicMock(id="issue-1"))
    store.load_workflow_graph_for_issue = AsyncMock(return_value=graph)

    # Patch dispatch_role + registry so we don't actually run a task runner.
    import app.application.conductor_tools as ct  # noqa: F401

    monkeypatch.setattr(
        "app.application.task_dispatcher.dispatch_role",
        AsyncMock(return_value=("task-new", "node-new")),
    )
    from app.application.task_completion_registry import TaskCompletionRegistry

    TaskCompletionRegistry._instance = None

    registry = build_conductor_tools(
        project_id="proj-1",
        store=store,
        event_bus=None,
        task_dispatcher_fn=AsyncMock(),
        issue_id="issue-1",
    )
    # Signal the task immediately so wait_for_active returns without blocking.
    reg = TaskCompletionRegistry.get()
    orig_register = reg.register

    def _register_and_signal(tid):
        orig_register(tid)
        reg.signal(tid, {"task_id": tid, "role": "engineer", "status": "done"})

    monkeypatch.setattr(reg, "register", _register_and_signal)

    result = await registry.tools["dispatch_subagent"]({"role": "engineer"})
    assert result.get("status") != "retries_exhausted"
