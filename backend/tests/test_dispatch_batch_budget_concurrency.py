"""dispatch_batch effective concurrency is downscaled by a tight budget (PR3).

The configured cap (MAX_PARALLEL_DISPATCH_PER_BATCH) is the upper bound, but a
small remaining budget shrinks the EFFECTIVE concurrency. We measure the peak
number of agents running at once and assert it is bounded by the budget-allowed
value — and unchanged (= configured cap) when the budget is comfortable.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

import app.application.conductor_tools as ct
from app.application import task_dispatcher
from app.application.role_concurrency import RoleConcurrencyLimiter
from app.application.task_completion_registry import TaskCompletionRegistry
from app.domain.models import CodexIssue, ExecutionProcess, Project


@pytest.fixture(autouse=True)
def _reset_singletons():
    TaskCompletionRegistry._instance = None
    RoleConcurrencyLimiter._instance = None
    yield
    TaskCompletionRegistry._instance = None
    RoleConcurrencyLimiter._instance = None


def _issue(budget_usd):
    return CodexIssue(
        id="issue-deadbeef", session_id="s1", project_id="p1", title="t",
        git_branch="issue/deadbeef-t", budget_usd=budget_usd,
    )


def _project():
    return Project(
        id="p1", name="demo", repo_path="/tmp/repo", default_branch="main",
        created_at=datetime.now(), updated_at=datetime.now(),
    )


def _ep(cost):
    now = datetime.now()
    return ExecutionProcess(
        id="ep", task_id="task-1", session_id="s1", status="Completed",
        total_cost_usd=cost, created_at=now, updated_at=now,
    )


class _Store:
    """Store stub that also serves the budget-aggregation chain."""

    def __init__(self, issue, project, *, spent_cost):
        self._issue = issue
        self._project = project
        self._spent_cost = spent_cost

    async def load_codex_issue(self, issue_id):
        return self._issue if issue_id == self._issue.id else None

    async def load_project(self, project_id):
        return self._project if project_id == self._project.id else None

    async def load_workflow_graph_for_issue(self, issue_id):
        return None

    async def list_codex_tasks(self, issue_id=None):
        return [{"id": "task-1"}]

    async def list_execution_processes(self, task_id=None):
        return [_ep(self._spent_cost)]


class _WorktreeManagerStub:
    async def prepare_agent_worktree(self, project, issue, agent_key):
        return f"swarm/{agent_key}", f"/tmp/wt/{agent_key}", issue.git_branch

    async def cleanup_agent_worktree(self, project, issue, agent_key):
        pass

    async def commit_issue_worktree(self, issue, message=None):
        return None

    async def merge_agent_worktrees(self, project, issue, agents):
        return {"merged": [{**a, "sha": "x"} for a in agents], "conflict": None, "skipped": []}


def _build(store, wm):
    return ct.build_conductor_tools(
        project_id="p1", store=store, event_bus=None,
        task_dispatcher_fn=lambda task: None,
        issue_id="issue-deadbeef", worktree_manager=wm,
    )


async def _measure_peak_concurrency(reg, n_agents):
    """Run a batch of n_agents and return the peak simultaneous in-flight count."""
    state = {"current": 0, "peak": 0}

    async def fake_dispatch_role(*, issue, role, prompt_override, store, task_dispatcher_fn,
                                 event_bus, prev_node_key, agent_worktree_path=None, batch_key=None,
                                 register_completion=False):
        fake_dispatch_role.n += 1
        return f"task-{fake_dispatch_role.n}", f"node-{fake_dispatch_role.n}"

    fake_dispatch_role.n = 0

    async def fake_wait(self, task_id, *, idle_timeout, hard_timeout, activity_age):
        state["current"] += 1
        state["peak"] = max(state["peak"], state["current"])
        # Hold the "slot" briefly so siblings overlap if concurrency allows.
        await asyncio.sleep(0.02)
        state["current"] -= 1
        return {"status": "done", "task_id": task_id}

    import app.application.task_completion_registry as tcr_mod
    orig_dispatch = task_dispatcher.dispatch_role
    orig_wait = TaskCompletionRegistry.wait_for_active
    task_dispatcher.dispatch_role = fake_dispatch_role
    TaskCompletionRegistry.wait_for_active = fake_wait
    try:
        agents = [{"role": f"engineer", "prompt": str(i)} for i in range(n_agents)]
        # Distinct roles so the per-role limiter (default 3) never masks the
        # budget downscale we are measuring.
        agents = [{"role": f"role{i}", "prompt": str(i)} for i in range(n_agents)]
        out = await reg.tools["dispatch_batch"]({"agents": agents})
    finally:
        task_dispatcher.dispatch_role = orig_dispatch
        TaskCompletionRegistry.wait_for_active = orig_wait
    return out, state["peak"]


@pytest.mark.asyncio
async def test_comfortable_budget_keeps_configured_cap(monkeypatch):
    monkeypatch.setenv("MAX_PARALLEL_DISPATCH_PER_BATCH", "3")
    monkeypatch.setenv("EST_COST_PER_AGENT_USD", "0.50")
    # Budget 10, spent 0 -> remaining 10 / 0.5 = 20 supported, clamped to cap 3.
    store = _Store(_issue(budget_usd=10.0), _project(), spent_cost=0.0)
    reg = _build(store, _WorktreeManagerStub())

    out, peak = await _measure_peak_concurrency(reg, n_agents=4)

    assert out["status"] == "batch_complete"
    assert peak == 3  # full configured cap, not downscaled


@pytest.mark.asyncio
async def test_tight_budget_downscales_effective_concurrency(monkeypatch):
    monkeypatch.setenv("MAX_PARALLEL_DISPATCH_PER_BATCH", "3")
    monkeypatch.setenv("EST_COST_PER_AGENT_USD", "0.50")
    # Budget 10, spent 9.4 -> remaining 0.6 / 0.5 = floor(1.2) = 1 supported.
    store = _Store(_issue(budget_usd=10.0), _project(), spent_cost=9.4)
    reg = _build(store, _WorktreeManagerStub())

    out, peak = await _measure_peak_concurrency(reg, n_agents=4)

    assert out["status"] == "batch_complete"
    # Effective concurrency squeezed to the budget-allowed 1, well under cap 3.
    assert peak == 1
    # Still at least 1 -> the batch made progress, not zeroed out.
    assert out["agent_count"] == 4


@pytest.mark.asyncio
async def test_over_budget_squeezes_concurrency_to_one(monkeypatch):
    monkeypatch.setenv("MAX_PARALLEL_DISPATCH_PER_BATCH", "3")
    monkeypatch.setenv("EST_COST_PER_AGENT_USD", "0.50")
    # spent 12 > budget 10 -> over budget -> concurrency floor 1 (no batch=0).
    store = _Store(_issue(budget_usd=10.0), _project(), spent_cost=12.0)
    reg = _build(store, _WorktreeManagerStub())

    out, peak = await _measure_peak_concurrency(reg, n_agents=3)

    assert peak == 1
    assert out["agent_count"] == 3


@pytest.mark.asyncio
async def test_unlimited_budget_does_not_downscale(monkeypatch):
    monkeypatch.setenv("MAX_PARALLEL_DISPATCH_PER_BATCH", "3")
    monkeypatch.setenv("EST_COST_PER_AGENT_USD", "0.50")
    # budget_usd=0 -> unlimited -> cap untouched even with huge spend.
    store = _Store(_issue(budget_usd=0.0), _project(), spent_cost=999.0)
    reg = _build(store, _WorktreeManagerStub())

    out, peak = await _measure_peak_concurrency(reg, n_agents=4)

    assert peak == 3  # configured cap, not compressed
