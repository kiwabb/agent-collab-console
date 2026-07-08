"""Tests for the parallel-swarm dispatch_batch conductor tool (PR2).

These exercise dispatch_batch in isolation: the worktree manager, dispatch_role,
and the completion registry are all stubbed, so no real git / subprocess work
runs. We verify:
  - concurrent fan-out with one isolated worktree per agent (distinct paths),
  - the batch-level concurrency cap is respected,
  - partial join: one agent failing/timing out does not abort the batch,
  - the extracted single-dispatch helper still drives dispatch_subagent (regression).
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

import app.application.conductor_tools as ct
from app.application import task_dispatcher
from app.application.role_concurrency import RoleConcurrencyLimiter
from app.application.task_completion_registry import TaskCompletionRegistry
from app.domain.models import CodexIssue, Project


@pytest.fixture(autouse=True)
def _reset_singletons():
    # The completion registry + role limiter are process singletons; isolate
    # per test so a cached concurrency limit / stale events don't leak across.
    TaskCompletionRegistry._instance = None
    RoleConcurrencyLimiter._instance = None
    yield
    TaskCompletionRegistry._instance = None
    RoleConcurrencyLimiter._instance = None


def _issue() -> CodexIssue:
    return CodexIssue(
        id="issue-deadbeef",
        session_id="s1",
        project_id="p1",
        title="t",
        git_branch="issue/deadbeef-t",
    )


def _project() -> Project:
    return Project(
        id="p1",
        name="demo",
        repo_path="/tmp/repo",
        default_branch="main",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


class _Store:
    """Minimal store stub for dispatch_batch / dispatch_subagent."""

    def __init__(self, issue: CodexIssue, project: Project):
        self._issue = issue
        self._project = project

    async def load_codex_issue(self, issue_id):
        return self._issue if issue_id == self._issue.id else None

    async def load_project(self, project_id):
        return self._project if project_id == self._project.id else None

    async def load_workflow_graph_for_issue(self, issue_id):
        return None  # never exhaust the re-dispatch budget


class _WorktreeManagerStub:
    """Hands out a unique worktree path per agent_key and records cleanups.

    Also stubs the PR3 join surface: commit_issue_worktree (upstream flush) and
    merge_agent_worktrees (sequential merge-back). By default every candidate
    merges cleanly; set `conflict_on` to a list of agent_keys to simulate a
    conflict on the first matching candidate.
    """

    def __init__(self, conflict_on: list[str] | None = None):
        self.prepared: list[str] = []
        self.cleaned: list[str] = []
        self.merged_candidates: list[list[dict]] = []
        self.flushed = 0
        self._conflict_on = set(conflict_on or [])

    async def prepare_agent_worktree(self, project, issue, agent_key):
        path = f"/tmp/wt/{issue.id}-{agent_key}"
        self.prepared.append(agent_key)
        branch = f"swarm/{issue.id[:8]}-{agent_key}"
        return branch, path, issue.git_branch

    async def cleanup_agent_worktree(self, project, issue, agent_key):
        self.cleaned.append(agent_key)

    async def commit_issue_worktree(self, issue, message=None):
        self.flushed += 1
        return None

    async def merge_agent_worktrees(self, project, issue, agents):
        self.merged_candidates.append(agents)
        merged: list[dict] = []
        conflict = None
        skipped: list[dict] = []
        for spec in agents:
            if conflict is not None:
                skipped.append(spec)
                continue
            if spec["agent_key"] in self._conflict_on:
                conflict = {
                    "agent_key": spec["agent_key"],
                    "role": spec.get("role"),
                    "branch": spec.get("branch"),
                    "worktree_path": spec.get("worktree_path"),
                    "files": ["shared.txt"],
                    "diff": "diff --git a/shared.txt b/shared.txt",
                }
            else:
                merged.append({**spec, "sha": f"sha-{spec['agent_key']}"})
                self.cleaned.append(spec.get("worktree_key") or spec["agent_key"])
        return {"merged": merged, "conflict": conflict, "skipped": skipped}


def _build(store, wm, *, dispatcher_fn=lambda task: None):
    return ct.build_conductor_tools(
        project_id="p1",
        store=store,
        event_bus=None,
        task_dispatcher_fn=dispatcher_fn,
        issue_id="issue-deadbeef",
        worktree_manager=wm,
    )


def _patch_dispatch(monkeypatch, *, run, register_only=True):
    """Patch dispatch_role + registry.wait_for_active.

    `run(role, agent_worktree_path) -> result_dict` is invoked inside the
    stubbed completion wait, simulating the subagent running to completion.
    """
    counter = {"n": 0}
    paths: dict[str, str | None] = {}
    batch_keys: dict[str, str | None] = {}

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
        counter["n"] += 1
        task_id = f"task-{counter['n']}"
        paths[task_id] = agent_worktree_path
        batch_keys[task_id] = batch_key
        return task_id, f"node-{counter['n']}"

    monkeypatch.setattr(task_dispatcher, "dispatch_role", fake_dispatch_role)

    async def fake_wait(self, task_id, *, idle_timeout, hard_timeout, activity_age):
        wt = paths.get(task_id)
        return await run(task_id, wt)

    monkeypatch.setattr(TaskCompletionRegistry, "wait_for_active", fake_wait)
    return paths, batch_keys


@pytest.mark.asyncio
async def test_dispatch_batch_fans_out_with_isolated_worktrees(monkeypatch):
    wm = _WorktreeManagerStub()
    store = _Store(_issue(), _project())
    reg = _build(store, wm)

    seen_paths: list[str] = []

    async def run(task_id, wt):
        seen_paths.append(wt)
        return {"status": "done", "task_id": task_id}

    _patch_dispatch(monkeypatch, run=run)

    out = await reg.tools["dispatch_batch"](
        {
            "agents": [
                {"role": "engineer", "prompt": "a"},
                {"role": "engineer", "prompt": "b"},
                {"role": "qa", "prompt": "c"},
            ]
        }
    )

    assert out["status"] == "batch_complete"
    assert out["agent_count"] == 3
    assert out["succeeded_count"] == 3
    assert out["failed_count"] == 0
    # Each agent got an isolated, distinct worktree path.
    wt_paths = [r["worktree_path"] for r in out["results"]]
    assert len(set(wt_paths)) == 3
    assert all(p is not None for p in wt_paths)
    # Two engineers in one batch get distinct agent keys (no worktree collision).
    keys = sorted(r["agent_key"] for r in out["results"])
    assert keys == ["engineer", "engineer-2", "qa"]
    # Upstream artifacts were flushed once before fan-out.
    assert wm.flushed == 1
    # PR3 join: all succeeded agents were handed to merge-back, then cleaned.
    assert out["merge_status"] == "merged"
    assert len(out["merged"]) == 3
    assert sorted(wm.cleaned) == sorted(wm.prepared)
    # Branch lineage is carried in-memory to the merge step.
    assert all("branch" in c for c in wm.merged_candidates[0])


@pytest.mark.asyncio
async def test_dispatch_batch_tags_all_nodes_with_one_batch_key(monkeypatch):
    """Every agent fanned out in one dispatch_batch call must carry the SAME,
    non-null batch_key so the UI can group them into a parallel swimlane."""
    wm = _WorktreeManagerStub()
    store = _Store(_issue(), _project())
    reg = _build(store, wm)

    async def run(task_id, wt):
        return {"status": "done", "task_id": task_id}

    _paths, batch_keys = _patch_dispatch(monkeypatch, run=run)

    await reg.tools["dispatch_batch"](
        {
            "agents": [
                {"role": "engineer"},
                {"role": "engineer"},
                {"role": "qa"},
            ]
        }
    )

    keys = [batch_keys[f"task-{i}"] for i in (1, 2, 3)]
    assert all(k is not None for k in keys), keys
    assert len(set(keys)) == 1, f"all batch nodes must share one batch_key, got {keys}"
    assert keys[0].startswith("batch-")


@pytest.mark.asyncio
async def test_dispatch_subagent_carries_no_batch_key(monkeypatch):
    """The serial path must leave batch_key None so its node is not grouped."""
    wm = _WorktreeManagerStub()
    store = _Store(_issue(), _project())
    reg = _build(store, wm)

    async def run(task_id, wt):
        return {"status": "done", "task_id": task_id}

    _paths, batch_keys = _patch_dispatch(monkeypatch, run=run)

    await reg.tools["dispatch_subagent"]({"role": "engineer"})
    assert batch_keys["task-1"] is None


@pytest.mark.asyncio
async def test_dispatch_batch_respects_concurrency_cap(monkeypatch):
    monkeypatch.setenv("MAX_PARALLEL_DISPATCH_PER_BATCH", "2")
    wm = _WorktreeManagerStub()
    store = _Store(_issue(), _project())
    reg = _build(store, wm)

    live = {"now": 0, "max": 0}
    gate = asyncio.Event()  # noqa: F841

    async def run(task_id, wt):
        live["now"] += 1
        live["max"] = max(live["max"], live["now"])
        # Hold all in-flight agents until everyone that can run has started,
        # so the peak concurrency reflects the cap.
        await asyncio.sleep(0.02)
        live["now"] -= 1
        return {"status": "done", "task_id": task_id}

    _patch_dispatch(monkeypatch, run=run)

    out = await reg.tools["dispatch_batch"]({"agents": [{"role": "engineer"} for _ in range(5)]})

    assert out["succeeded_count"] == 5
    assert live["max"] <= 2, f"peak concurrency {live['max']} exceeded cap 2"


@pytest.mark.asyncio
async def test_dispatch_batch_partial_join_on_failure(monkeypatch):
    wm = _WorktreeManagerStub()
    store = _Store(_issue(), _project())
    reg = _build(store, wm)

    async def run(task_id, wt):
        if task_id == "task-2":
            raise TimeoutError("boom")
        return {"status": "done", "task_id": task_id}

    _patch_dispatch(monkeypatch, run=run)

    out = await reg.tools["dispatch_batch"](
        {
            "agents": [
                {"role": "engineer"},
                {"role": "qa"},
                {"role": "architect"},
            ]
        }
    )

    # Whole batch does not raise; failures are isolated as result items.
    assert out["status"] == "batch_complete"
    assert out["agent_count"] == 3
    assert out["succeeded_count"] == 2
    assert out["failed_count"] == 1
    failed = [r for r in out["results"] if "error" in r]
    assert len(failed) == 1
    assert "agent_key" in failed[0] and "role" in failed[0]
    # The failed agent's worktree is cleaned up immediately (no leak); the two
    # succeeded agents are merged back then cleaned by merge_agent_worktrees.
    assert failed[0]["agent_key"] not in wm.cleaned
    assert failed[0]["worktree_key"] in wm.cleaned
    assert out["merge_status"] == "merged"
    assert len(out["merged"]) == 2
    # Only the two succeeded agents were merge candidates.
    assert {c["agent_key"] for c in wm.merged_candidates[0]} == {"engineer", "architect"}


@pytest.mark.asyncio
async def test_dispatch_batch_does_not_merge_partial_agent(monkeypatch):
    """A subagent result with status=partial is not a successful implementation.

    The Engineer workflow can downgrade claimed work to partial when the real
    git diff is empty; dispatch_batch must not count that as a success or hand
    it to merge-back.
    """
    wm = _WorktreeManagerStub()
    store = _Store(_issue(), _project())
    reg = _build(store, wm)

    async def run(task_id, wt):
        if task_id == "task-2":
            return {"status": "partial", "task_id": task_id, "files_changed": []}
        return {"status": "done", "task_id": task_id}

    _patch_dispatch(monkeypatch, run=run)

    out = await reg.tools["dispatch_batch"](
        {
            "agents": [
                {"role": "engineer"},
                {"role": "engineer"},
                {"role": "architect"},
            ]
        }
    )

    assert out["succeeded_count"] == 2
    assert out["failed_count"] == 1
    failed = [r for r in out["results"] if r.get("status") == "partial"]
    assert len(failed) == 1
    assert failed[0]["agent_key"] not in wm.cleaned
    assert failed[0]["worktree_key"] in wm.cleaned
    assert {c["agent_key"] for c in wm.merged_candidates[0]} == {"engineer", "architect"}


@pytest.mark.asyncio
async def test_dispatch_batch_empty_agents_errors(monkeypatch):
    wm = _WorktreeManagerStub()
    store = _Store(_issue(), _project())
    reg = _build(store, wm)
    out = await reg.tools["dispatch_batch"]({"agents": []})
    assert "error" in out


@pytest.mark.asyncio
async def test_dispatch_batch_merge_conflict_surfaces_structured(monkeypatch):
    """When merge-back hits a conflict, the tool returns merge_status=conflict
    with a structured `conflicts` list so the Conductor can reconcile it."""
    wm = _WorktreeManagerStub(conflict_on=["qa"])
    store = _Store(_issue(), _project())
    reg = _build(store, wm)

    async def run(task_id, wt):
        return {"status": "done", "task_id": task_id}

    _patch_dispatch(monkeypatch, run=run)

    out = await reg.tools["dispatch_batch"](
        {
            "agents": [
                {"role": "engineer"},
                {"role": "qa"},
            ]
        }
    )

    assert out["merge_status"] == "conflict"
    assert len(out["conflicts"]) == 1
    conflict = out["conflicts"][0]
    assert conflict["agent_key"] == "qa"
    assert conflict["files"] == ["shared.txt"]
    assert conflict["diff"]
    # The clean engineer was merged before the conflict (not rolled back).
    assert len(out["merged"]) == 1
    assert out["merged"][0]["agent_key"] == "engineer"
    assert "conflicting files" in out["note"].lower() or "conflict" in out["note"].lower()


@pytest.mark.asyncio
async def test_dispatch_subagent_regression_uses_shared_worktree(monkeypatch):
    """The extracted helper must not change serial dispatch: agent_worktree_path
    is None so the task runs in the shared issue worktree as before."""
    wm = _WorktreeManagerStub()
    store = _Store(_issue(), _project())
    reg = _build(store, wm)

    captured = {"wt": "sentinel"}

    async def run(task_id, wt):
        captured["wt"] = wt
        return {"status": "done", "task_id": task_id}

    _patch_dispatch(monkeypatch, run=run)

    out = await reg.tools["dispatch_subagent"]({"role": "engineer"})
    assert out["status"] == "done"
    assert captured["wt"] is None  # serial path: shared issue worktree
    # dispatch_subagent must never touch per-agent worktrees.
    assert wm.prepared == [] and wm.cleaned == []
