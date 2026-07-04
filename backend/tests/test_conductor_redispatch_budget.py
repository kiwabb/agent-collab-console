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

from __future__ import annotations  # noqa: I001

import asyncio
from datetime import datetime  # noqa: F401
from uuid import uuid4

import pytest

import app.application.conductor_tools as ct
from app.application import task_dispatcher
from app.application.role_concurrency import RoleConcurrencyLimiter
from app.application.task_completion_registry import TaskCompletionRegistry
from app.domain.models import Agent, CodexIssue, WorkflowGraph, WorkflowNode


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
    ct._DISPATCH_START_LOCKS_BY_ISSUE.clear()
    yield
    TaskCompletionRegistry._instance = None
    RoleConcurrencyLimiter._instance = None
    ct._DISPATCH_START_LOCKS_BY_ISSUE.clear()


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


class _WorktreeManager:
    def __init__(self):
        self.prepared: list[str] = []

    async def prepare_agent_worktree(self, project, issue, agent_key):
        self.prepared.append(agent_key)
        return f"branch/{agent_key}", f"/tmp/{agent_key}", issue.git_branch

    async def commit_issue_worktree(self, issue, message=None):
        return None

    async def cleanup_agent_worktree(self, project, issue, agent_key):
        return None

    async def merge_agent_worktrees(self, project, issue, agents):
        return {"merged": [], "conflict": None, "skipped": []}


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
async def test_role_alias_counts_against_canonical_role_budget():
    """`eng` / `dev` must not bypass the engineer redispatch cap."""
    store = _Store(role_node_count=4)

    registry = _build_registry(store)
    result = await registry.tools["dispatch_subagent"]({"role": "dev"})

    assert result["status"] == "retries_exhausted"
    assert result["role"] == ROLE
    assert result["dispatches"] == 4


def test_normalize_role_canonicalizes_case_and_whitespace():
    assert task_dispatcher.normalize_role(" Engineer ") == "engineer"
    assert task_dispatcher.normalize_role(" DEV ") == "engineer"


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


@pytest.mark.asyncio
async def test_concurrent_dispatches_share_issue_start_lock(monkeypatch):
    monkeypatch.setenv("CONDUCTOR_MAX_DISPATCHES_PER_ROLE", "1")
    store = _Store(role_node_count=0)

    async def fake_dispatch_role(
        *,
        issue,
        role,
        prompt_override,
        store,
        task_dispatcher_fn,
        event_bus,
        prev_node_key,
        agent_worktree_path=None,
        batch_key=None,
        register_completion=False,
    ):
        store._graph.nodes.append(_node(role))
        return f"task-{len(store._graph.nodes)}", store._graph.nodes[-1].id

    async def fake_wait(self, task_id, *, idle_timeout, hard_timeout, activity_age):
        return {"status": "done", "task_id": task_id}

    monkeypatch.setattr(task_dispatcher, "dispatch_role", fake_dispatch_role)
    monkeypatch.setattr(TaskCompletionRegistry, "wait_for_active", fake_wait)

    registry = _build_registry(store)
    results = await asyncio.gather(
        registry.tools["dispatch_subagent"]({"role": ROLE}),
        registry.tools["dispatch_subagent"]({"role": ROLE}),
    )

    statuses = sorted(result.get("status") for result in results)
    assert statuses == ["done", "retries_exhausted"]
    assert sum(1 for node in store._graph.nodes if node.node_key == ROLE) == 1


@pytest.mark.asyncio
async def test_dispatch_role_prefers_exact_agent_match_before_prefix():
    issue = CodexIssue(
        id=ISSUE_ID,
        session_id="s1",
        project_id="p1",
        title="t",
        git_branch="issue/exact-agent",
    )

    class Store(_Store):
        async def list_agents(self, workspace_id=None):
            return [
                Agent(
                    id="agent-backend",
                    role_key="engineer_backend",
                    name="Backend Engineer",
                ),
                Agent(
                    id="agent-engineer",
                    role_key="engineer",
                    name="Engineer",
                ),
            ]

        async def save_codex_task(self, task):
            self.saved_task = task

        async def add_workflow_node(self, node):
            self.added_node = node

        async def add_workflow_edge(self, edge):
            self.added_edge = edge

        async def save_agent_message(self, message):
            self.saved_message = message

    store = Store(role_node_count=0)
    captured = {}

    async def runner(task):
        captured["role"] = task.role

    await task_dispatcher.dispatch_role(
        issue=issue,
        role="engineer",
        store=store,
        task_dispatcher_fn=runner,
    )

    assert store.added_node.agent_id == "agent-engineer"
    assert captured["role"] == "engineer"


@pytest.mark.asyncio
async def test_dispatch_batch_rejects_same_role_over_budget_before_worktrees():
    """Batch preflight counts existing + requested same-role dispatches together.

    With 3 engineer nodes already present and max=4, a batch requesting two more
    engineers would overshoot. It must fail before any per-agent worktree is
    prepared.
    """
    store = _Store(role_node_count=3)
    async def _load_project(project_id):
        return object()

    store.load_project = _load_project
    wm = _WorktreeManager()
    registry = ct.build_conductor_tools(
        project_id="p1",
        store=store,
        event_bus=None,
        task_dispatcher_fn=lambda *a, **k: None,
        issue_id=ISSUE_ID,
        worktree_manager=wm,
    )

    result = await registry.tools["dispatch_batch"](
        {
            "agents": [
                {"role": ROLE, "prompt": "first"},
                {"role": ROLE, "prompt": "second"},
            ]
        }
    )

    assert result["status"] == "retries_exhausted"
    assert result["roles"] == [
        {
            "role": ROLE,
            "dispatches": 3,
            "requested": 2,
            "max_dispatches": 4,
        }
    ]
    assert wm.prepared == []


@pytest.mark.asyncio
async def test_dispatch_batch_aliases_share_redispatch_budget_before_worktrees():
    """Batch preflight canonicalizes aliases before counting requested roles."""
    store = _Store(role_node_count=3)

    async def _load_project(project_id):
        return object()

    store.load_project = _load_project
    wm = _WorktreeManager()
    registry = ct.build_conductor_tools(
        project_id="p1",
        store=store,
        event_bus=None,
        task_dispatcher_fn=lambda *a, **k: None,
        issue_id=ISSUE_ID,
        worktree_manager=wm,
    )

    result = await registry.tools["dispatch_batch"](
        {
            "agents": [
                {"role": "eng", "prompt": "first"},
                {"role": "dev", "prompt": "second"},
            ]
        }
    )

    assert result["status"] == "retries_exhausted"
    assert result["roles"][0]["role"] == ROLE
    assert result["roles"][0]["dispatches"] == 3
    assert result["roles"][0]["requested"] == 2
    assert wm.prepared == []
