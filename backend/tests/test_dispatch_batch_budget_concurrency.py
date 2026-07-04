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
    ct._DISPATCH_START_LOCKS_BY_ISSUE.clear()
    yield
    TaskCompletionRegistry._instance = None
    RoleConcurrencyLimiter._instance = None
    ct._DISPATCH_START_LOCKS_BY_ISSUE.clear()


def _issue(budget_usd):
    return CodexIssue(
        id="issue-deadbeef",
        session_id="s1",
        project_id="p1",
        title="t",
        git_branch="issue/deadbeef-t",
        budget_usd=budget_usd,
    )


def _project():
    return Project(
        id="p1",
        name="demo",
        repo_path="/tmp/repo",
        default_branch="main",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def _ep(cost):
    now = datetime.now()
    return ExecutionProcess(
        id="ep",
        task_id="task-1",
        session_id="s1",
        status="Completed",
        total_cost_usd=cost,
        created_at=now,
        updated_at=now,
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


class _ChangingBudgetStore(_Store):
    def __init__(self, issue, project):
        super().__init__(issue, project, spent_cost=0.0)
        self.execution_process_calls = 0

    async def list_execution_processes(self, task_id=None):
        self.execution_process_calls += 1
        # Initial batch preflight is healthy; per-agent gates after that see
        # over-budget spend and must stop before worktree preparation.
        cost = 0.0 if self.execution_process_calls == 1 else 12.0
        return [_ep(cost)]


class _SecondGateOverBudgetStore(_Store):
    def __init__(self, issue, project):
        super().__init__(issue, project, spent_cost=0.0)
        self.execution_process_calls = 0

    async def list_execution_processes(self, task_id=None):
        self.execution_process_calls += 1
        # Batch preflight and the first per-agent gate are healthy; the second
        # per-agent gate sees over-budget spend. A serial dispatch gate must
        # stop the second agent before it prepares a worktree.
        cost = 0.0 if self.execution_process_calls <= 2 else 12.0
        return [_ep(cost)]


class _WorktreeManagerStub:
    def __init__(self):
        self.prepared: list[str] = []
        self.cleaned: list[str] = []

    async def prepare_agent_worktree(self, project, issue, agent_key):
        self.prepared.append(agent_key)
        return f"swarm/{agent_key}", f"/tmp/wt/{agent_key}", issue.git_branch

    async def cleanup_agent_worktree(self, project, issue, agent_key):
        self.cleaned.append(agent_key)

    async def commit_issue_worktree(self, issue, message=None):
        return None

    async def merge_agent_worktrees(self, project, issue, agents):
        return {"merged": [{**a, "sha": "x"} for a in agents], "conflict": None, "skipped": []}


class _FailingMergeWorktreeManagerStub(_WorktreeManagerStub):
    async def merge_agent_worktrees(self, project, issue, agents):
        raise RuntimeError("merge infrastructure unavailable")


def _build(store, wm):
    return ct.build_conductor_tools(
        project_id="p1",
        store=store,
        event_bus=None,
        task_dispatcher_fn=lambda task: None,
        issue_id="issue-deadbeef",
        worktree_manager=wm,
    )


async def _measure_peak_concurrency(reg, n_agents):
    """Run a batch of n_agents and return the peak simultaneous in-flight count."""
    state = {"current": 0, "peak": 0}

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

    import app.application.task_completion_registry as tcr_mod  # noqa: F401

    orig_dispatch = task_dispatcher.dispatch_role
    orig_wait = TaskCompletionRegistry.wait_for_active
    task_dispatcher.dispatch_role = fake_dispatch_role
    TaskCompletionRegistry.wait_for_active = fake_wait
    try:
        agents = [{"role": f"engineer", "prompt": str(i)} for i in range(n_agents)]  # noqa: F541
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
async def test_healthy_small_budget_downscales_to_affordable_cap(monkeypatch):
    monkeypatch.setenv("MAX_PARALLEL_DISPATCH_PER_BATCH", "3")
    monkeypatch.setenv("EST_COST_PER_AGENT_USD", "0.50")
    # Budget 1, spent 0 -> healthy, but only two 0.50 agents fit inside the
    # remaining budget at once. The configured cap is still an upper bound.
    store = _Store(_issue(budget_usd=1.0), _project(), spent_cost=0.0)
    reg = _build(store, _WorktreeManagerStub())

    out, peak = await _measure_peak_concurrency(reg, n_agents=4)

    assert out["status"] == "batch_complete"
    assert peak == 2


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
async def test_over_budget_rejects_batch_without_dispatch(monkeypatch):
    monkeypatch.setenv("MAX_PARALLEL_DISPATCH_PER_BATCH", "3")
    monkeypatch.setenv("EST_COST_PER_AGENT_USD", "0.50")
    # spent 12 > budget 10 -> hard gate rejects new dispatches.
    store = _Store(_issue(budget_usd=10.0), _project(), spent_cost=12.0)
    wm = _WorktreeManagerStub()
    reg = _build(store, wm)

    out = await reg.tools["dispatch_batch"](
        {"agents": [{"role": "role0", "prompt": "0"}, {"role": "role1", "prompt": "1"}]}
    )

    assert out["status"] == "budget_exceeded"
    assert "budget" in out
    assert out["budget"]["budget_usd"] == 10.0
    assert wm.prepared == []


@pytest.mark.asyncio
async def test_batch_per_agent_budget_gate_stops_before_worktree_when_budget_changes(monkeypatch):
    monkeypatch.setenv("MAX_PARALLEL_DISPATCH_PER_BATCH", "1")
    monkeypatch.setenv("EST_COST_PER_AGENT_USD", "0.50")
    store = _ChangingBudgetStore(_issue(budget_usd=10.0), _project())
    wm = _WorktreeManagerStub()
    reg = _build(store, wm)

    out = await reg.tools["dispatch_batch"](
        {"agents": [{"role": "role0", "prompt": "0"}, {"role": "role1", "prompt": "1"}]}
    )

    assert out["status"] == "batch_complete"
    assert out["succeeded_count"] == 0
    assert out["failed_count"] == 2
    assert all(result["status"] == "budget_exceeded" for result in out["results"])
    assert wm.prepared == []
    assert wm.cleaned == []


@pytest.mark.asyncio
async def test_batch_budget_gate_serializes_before_each_worktree(monkeypatch):
    monkeypatch.setenv("MAX_PARALLEL_DISPATCH_PER_BATCH", "2")
    monkeypatch.setenv("EST_COST_PER_AGENT_USD", "0.50")
    store = _SecondGateOverBudgetStore(_issue(budget_usd=10.0), _project())
    wm = _WorktreeManagerStub()
    reg = _build(store, wm)

    out = await reg.tools["dispatch_batch"](
        {"agents": [{"role": "role0", "prompt": "0"}, {"role": "role1", "prompt": "1"}]}
    )

    assert out["status"] == "batch_complete"
    assert out["succeeded_count"] == 1
    assert out["failed_count"] == 1
    assert len(wm.prepared) == 1
    assert wm.prepared[0].startswith("role0-batch-")
    assert out["results"][0]["status"] == "done"
    assert out["results"][1]["status"] == "budget_exceeded"
    assert wm.cleaned == []


@pytest.mark.asyncio
async def test_over_budget_rejects_dispatch_subagent(monkeypatch):
    monkeypatch.setenv("EST_COST_PER_AGENT_USD", "0.50")
    store = _Store(_issue(budget_usd=10.0), _project(), spent_cost=12.0)
    reg = _build(store, _WorktreeManagerStub())

    out = await reg.tools["dispatch_subagent"]({"role": "engineer", "prompt": "fix it"})

    assert out["status"] == "budget_exceeded"
    assert out["budget"]["budget_usd"] == 10.0


@pytest.mark.asyncio
async def test_unlimited_budget_does_not_downscale(monkeypatch):
    monkeypatch.setenv("MAX_PARALLEL_DISPATCH_PER_BATCH", "3")
    monkeypatch.setenv("EST_COST_PER_AGENT_USD", "0.50")
    # budget_usd=0 -> unlimited -> cap untouched even with huge spend.
    store = _Store(_issue(budget_usd=0.0), _project(), spent_cost=999.0)
    reg = _build(store, _WorktreeManagerStub())

    out, peak = await _measure_peak_concurrency(reg, n_agents=4)  # noqa: RUF059

    assert peak == 3  # configured cap, not compressed


@pytest.mark.asyncio
async def test_merge_failure_reports_error_not_noop(monkeypatch):
    monkeypatch.setenv("MAX_PARALLEL_DISPATCH_PER_BATCH", "2")
    monkeypatch.setenv("EST_COST_PER_AGENT_USD", "0.50")
    store = _Store(_issue(budget_usd=10.0), _project(), spent_cost=0.0)
    reg = _build(store, _FailingMergeWorktreeManagerStub())

    out, peak = await _measure_peak_concurrency(reg, n_agents=2)  # noqa: RUF059

    assert out["status"] == "batch_complete"
    assert out["succeeded_count"] == 2
    assert out["merge_status"] == "error"
    assert "merge infrastructure unavailable" in out["merge_error"]
    assert "MERGE ERROR" in out["note"]
