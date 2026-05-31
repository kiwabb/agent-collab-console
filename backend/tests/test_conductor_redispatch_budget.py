"""Regression pin: GAP G re-dispatch budget upper bound.

`_check_redispatch_budget` (conductor_tools.py) caps how many times the
Conductor may dispatch the SAME role for one issue. Each dispatch of a role
adds a graph node (role, role#1, role#2 ...). Once the count reaches
`CONDUCTOR_MAX_DISPATCHES_PER_ROLE` (default 4) the tool short-circuits with a
terminal `retries_exhausted` result and must NOT reach the real dispatcher —
otherwise the Conductor is stuck in an unbounded rework loop.

These tests lock that boundary deterministically:
  - below budget  -> control passes through to the dispatcher,
  - at/over budget -> `retries_exhausted`, dispatcher never invoked.

Pure tests (no real git / subprocess); the dispatcher is a sentinel.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

import app.application.conductor_tools as ct
from app.application import task_dispatcher
from app.application.role_concurrency import RoleConcurrencyLimiter
from app.application.task_completion_registry import TaskCompletionRegistry
from app.domain.models import CodexIssue, WorkflowGraph, WorkflowNode


ISSUE_ID = "issue-budget"
ROLE = "engineer"


class _SentinelDispatched(Exception):
    """Raised by the stub dispatcher to prove control passed the budget gate."""


@pytest.fixture(autouse=True)
def _reset_singletons():
    # dispatch_subagent acquires a per-role concurrency slot and registers in the
    # completion registry; both are process singletons. Isolate per test so a
    # pass-through dispatch never leaks a held slot / stale event across tests.
    TaskCompletionRegistry._instance = None
    RoleConcurrencyLimiter._instance = None
    yield
    TaskCompletionRegistry._instance = None
    RoleConcurrencyLimiter._instance = None


def _sentinel_dispatch_role(monkeypatch, message: str) -> None:
    """Make dispatch_role raise a sentinel so a pass-through dispatch fails fast
    right after the budget gate (no real git / runner work)."""
    async def _boom(*args, **kwargs):
        raise _SentinelDispatched(message)

    monkeypatch.setattr(task_dispatcher, "dispatch_role", _boom)


def _node(node_key: str) -> WorkflowNode:
    return WorkflowNode(
        id=str(uuid4()),
        graph_id="g1",
        node_key=node_key,
        agent_id="agent-1",
    )


def _graph_with_role_nodes(count: int) -> WorkflowGraph:
    """A graph holding `count` nodes for ROLE: engineer, engineer#1, ... ."""
    keys = [ROLE] + [f"{ROLE}#{i}" for i in range(1, count)]
    return WorkflowGraph(
        id="g1",
        issue_id=ISSUE_ID,
        dag_json="{}",
        nodes=[_node(k) for k in keys[:count]],
    )


class _Store:
    """Minimal store: serves one issue + a workflow graph of a chosen size."""

    def __init__(self, role_node_count: int):
        self._graph = _graph_with_role_nodes(role_node_count)
        self._issue = CodexIssue(
            id=ISSUE_ID,
            session_id="s1",
            project_id="p1",
            title="t",
            git_branch="issue/budget-t",
        )

    async def load_codex_issue(self, issue_id):
        return self._issue if issue_id == ISSUE_ID else None

    async def load_workflow_graph_for_issue(self, issue_id):
        return self._graph if issue_id == ISSUE_ID else None


def _build_registry(store):
    # A non-None task_dispatcher_fn + issue_id is required to reach the budget
    # gate (otherwise dispatch_subagent returns the no-context stub early).
    return ct.build_conductor_tools(
        project_id="p1",
        store=store,
        event_bus=None,
        task_dispatcher_fn=lambda *a, **k: None,
        issue_id=ISSUE_ID,
    )


@pytest.mark.asyncio
async def test_redispatch_default_budget_is_four():
    """The shipped default cap is 4 dispatches of the same role."""
    assert ct._max_dispatches_per_role() == 4


@pytest.mark.asyncio
async def test_fifth_redispatch_is_rejected_without_dispatching():
    """At the 4-node budget, the next dispatch_subagent is the 5th attempt and
    must return `retries_exhausted` WITHOUT reaching the dispatcher."""
    store = _Store(role_node_count=4)  # engineer, #1, #2, #3 already dispatched

    registry = _build_registry(store)
    # No dispatch_role monkeypatch: if the gate failed to short-circuit, the
    # real dispatch_role would run — but we assert a clean retries_exhausted
    # instead, proving control never reached it.
    result = await registry.tools["dispatch_subagent"]({"role": ROLE})

    assert result["status"] == "retries_exhausted"
    assert result["role"] == ROLE
    assert result["dispatches"] == 4
    assert result["max_dispatches"] == 4


@pytest.mark.asyncio
async def test_under_budget_passes_through_to_dispatch(monkeypatch):
    """Below the budget (3 of 4 used) the gate lets control through; we prove it
    by making dispatch_role raise a sentinel that the budget gate never would."""
    store = _Store(role_node_count=3)  # engineer, #1, #2 -> 4th attempt allowed
    _sentinel_dispatch_role(monkeypatch, "reached dispatch_role (budget gate passed)")

    registry = _build_registry(store)
    with pytest.raises(_SentinelDispatched):
        await registry.tools["dispatch_subagent"]({"role": ROLE})


@pytest.mark.asyncio
async def test_budget_counts_only_matching_role_nodes(monkeypatch):
    """Nodes for other roles do not consume this role's budget."""
    store = _Store(role_node_count=0)
    # Inject unrelated-role nodes; engineer budget should be untouched.
    store._graph.nodes = [_node("qa"), _node("architect"), _node("architect#1")]
    _sentinel_dispatch_role(monkeypatch, "engineer budget not consumed by other roles")

    registry = _build_registry(store)
    with pytest.raises(_SentinelDispatched):
        await registry.tools["dispatch_subagent"]({"role": ROLE})


@pytest.mark.asyncio
async def test_redispatch_budget_env_override(monkeypatch):
    """`CONDUCTOR_MAX_DISPATCHES_PER_ROLE` tunes the cap; at the override the
    next attempt is rejected without dispatching."""
    monkeypatch.setenv("CONDUCTOR_MAX_DISPATCHES_PER_ROLE", "2")
    assert ct._max_dispatches_per_role() == 2
    store = _Store(role_node_count=2)

    registry = _build_registry(store)
    result = await registry.tools["dispatch_subagent"]({"role": ROLE})
    assert result["status"] == "retries_exhausted"
    assert result["max_dispatches"] == 2
