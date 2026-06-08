"""End-to-end integration tests for the parallel-swarm orchestration pipeline.

Unlike ``test_conductor_dispatch_batch.py`` (which stubs the WorktreeManager and
runs zero real git) and ``test_worktree_manager.py`` (which drives the
WorktreeManager primitives directly but bypasses the conductor tool), these
tests drive the **real** ``dispatch_batch`` conductor tool through the **real**
WorktreeManager + GitService against a **real git temp repo** and a **real**
AsyncSQLiteStore (tmp db). Only the subagent *execution layer* is mocked:
``task_dispatcher.dispatch_role`` (which would otherwise spawn a CLI runtime) and
``TaskCompletionRegistry.wait_for_active`` (which awaits that runtime). The mock
execution writes **real files into each agent's real worktree**, so the merge
back into the issue branch is a genuine `git` operation exercising the
swarm-safe primitive (`squash_merge_into_branch`).

This fills the gap called out by the E2E swarm validation task: the full
dispatch_batch -> fan-out -> per-agent worktree -> sequential merge-back ->
main-pollution-guard chain has never been exercised end-to-end against real git
+ real sqlite; every prior test mocked one of those layers.

Marked ``slow`` (real git subprocesses + real sqlite). Runs under ``--runslow``
or when targeted explicitly (``pytest tests/test_swarm_integration.py``).
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest

import app.application.conductor_tools as ct
from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.application import task_dispatcher, timeouts
from app.application.git_service import GitService
from app.application.role_concurrency import RoleConcurrencyLimiter
from app.application.task_completion_registry import TaskCompletionRegistry
from app.application.worktree_manager import WorktreeManager
from app.domain.models import CodexIssue, CodexTask, ExecutionProcess, Project


pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(shutil.which("git") is None, reason="git binary not available"),
]


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    ).stdout


# --------------------------------------------------------------------------- #
# Fixtures: real git repo, real sqlite store, real worktree manager.
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _reset_singletons():
    """The completion registry + role limiter are process singletons; isolate
    per test so a cached concurrency limit / stale events don't leak across."""
    TaskCompletionRegistry._instance = None
    RoleConcurrencyLimiter._instance = None
    yield
    TaskCompletionRegistry._instance = None
    RoleConcurrencyLimiter._instance = None


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real git repo with one initial commit on `main`."""
    r = tmp_path / "repo"
    r.mkdir()
    _git("init", "-b", "main", cwd=r)
    _git("config", "user.email", "test@example.com", cwd=r)
    _git("config", "user.name", "Test", cwd=r)
    (r / "README.md").write_text("hello\n")
    _git("add", "README.md", cwd=r)
    _git("commit", "-m", "init", cwd=r)
    return r


@pytest.fixture
def manager() -> WorktreeManager:
    return WorktreeManager(GitService())


@pytest.fixture
async def store():
    """A real AsyncSQLiteStore backed by a throwaway tmp database (never the real
    console.db)."""
    with tempfile.TemporaryDirectory() as td:
        s = AsyncSQLiteStore(Path(td) / "swarm-int.db")
        await s._init_db()
        yield s
        try:
            conn = await s._get_conn()
            await conn.close()
        except Exception:
            pass


async def _seed_project_and_issue(
    store: AsyncSQLiteStore,
    manager: WorktreeManager,
    repo: Path,
    *,
    budget_usd: float | None = None,
) -> tuple[Project, CodexIssue]:
    """Persist a real Project + Issue and prepare the shared issue worktree."""
    now = datetime.now()
    project = Project(
        id=f"p-{uuid4().hex[:8]}",
        name="demo",
        repo_path=str(repo),
        default_branch="main",
        created_at=now,
        updated_at=now,
    )
    await store.save_project(project)

    issue = CodexIssue(
        id=f"issue-{uuid4().hex[:8]}",
        session_id="s1",
        project_id=project.id,
        title="parallel swarm work",
        budget_usd=budget_usd,
        created_at=now,
        updated_at=now,
    )
    branch, path, base = await manager.prepare_issue_worktree(project, issue)
    issue.git_branch = branch
    issue.git_worktree_path = path
    issue.git_base_branch = base
    await store.save_codex_issue(issue)
    return project, issue


def _build_tools(store, manager, project, issue):
    return ct.build_conductor_tools(
        project_id=project.id,
        store=store,
        event_bus=None,
        task_dispatcher_fn=lambda task: None,  # truthy so dispatch_batch is live
        issue_id=issue.id,
        worktree_manager=manager,
    )


def _patch_subagent_execution(monkeypatch, *, write_plan):
    """Mock ONLY the subagent execution layer.

    `write_plan` maps an agent's worktree path -> a callable(Path) that performs
    the agent's "work" (writes real files into that worktree). dispatch_role is
    replaced with a no-op that returns a fake task_id; wait_for_active is
    replaced with a coroutine that runs the write_plan against the agent's real
    worktree then returns a `done` result. Everything downstream (commit, merge,
    main-pollution guard) is REAL git.

    Returns a dict mapping task_id -> agent_worktree_path for assertions.
    """
    counter = {"n": 0}
    paths: dict[str, str | None] = {}

    async def fake_dispatch_role(*, issue, role, prompt_override, store,
                                 task_dispatcher_fn, event_bus, prev_node_key,
                                 agent_worktree_path=None, batch_key=None,
                                 register_completion=False):
        counter["n"] += 1
        task_id = f"task-{counter['n']}"
        paths[task_id] = agent_worktree_path
        return task_id, f"node-{counter['n']}"

    monkeypatch.setattr(task_dispatcher, "dispatch_role", fake_dispatch_role)

    async def fake_wait(self, task_id, *, idle_timeout, hard_timeout, activity_age):
        wt = paths.get(task_id)
        if wt is not None:
            do_write = write_plan(wt)
            if do_write is not None:
                do_write(Path(wt))
        return {"status": "done", "task_id": task_id}

    monkeypatch.setattr(TaskCompletionRegistry, "wait_for_active", fake_wait)
    return paths


# --------------------------------------------------------------------------- #
# Scenario 1: parallel fan-out + real merge-back + main NOT polluted (core).
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_dispatch_batch_real_fanout_merges_and_keeps_main_clean(
    monkeypatch, store, manager, repo
):
    """Two agents write DIFFERENT files in isolated real worktrees; dispatch_batch
    fans them out, then sequentially squash-merges both back into the issue
    branch via REAL git. Asserts:
      - both files land on the issue branch,
      - main's ref AND tree are byte-for-byte unchanged (PR3 regression),
      - both agent worktrees are cleaned up (no leaks).
    """
    project, issue = await _seed_project_and_issue(store, manager, repo)
    reg = _build_tools(store, manager, project, issue)

    main_before = _git("rev-parse", "main", cwd=repo).strip()
    main_tree_before = _git("ls-tree", "-r", "--name-only", "main", cwd=repo)

    # Each agent writes a distinct file into its own worktree.
    file_for = {}

    def write_plan(wt: str):
        # Derive a per-agent file name from the worktree path so the two agents
        # never touch the same file.
        name = "a.txt" if wt.endswith("engineer") else "b.txt"
        file_for[wt] = name

        def _do(p: Path):
            (p / name).write_text(f"content of {name}\n")
        return _do

    _patch_subagent_execution(monkeypatch, write_plan=write_plan)

    out = await reg.tools["dispatch_batch"]({"agents": [
        {"role": "engineer", "prompt": "write a.txt"},
        {"role": "qa", "prompt": "write b.txt"},
    ]})

    assert out["status"] == "batch_complete"
    assert out["succeeded_count"] == 2
    assert out["failed_count"] == 0
    assert out["merge_status"] == "merged"
    assert len(out["merged"]) == 2

    # Both files landed on the issue branch (verify via real git tree listing).
    issue_tree = _git("ls-tree", "-r", "--name-only", issue.git_branch, cwd=repo)
    assert "a.txt" in issue_tree
    assert "b.txt" in issue_tree

    # PR3 REGRESSION (the critical one): main's ref AND tree are unchanged and
    # contain none of the agent files.
    main_after = _git("rev-parse", "main", cwd=repo).strip()
    assert main_after == main_before, "dispatch_batch merge-back polluted main's ref"
    main_tree_after = _git("ls-tree", "-r", "--name-only", "main", cwd=repo)
    assert main_tree_after == main_tree_before
    assert "a.txt" not in main_tree_after
    assert "b.txt" not in main_tree_after

    # Both agent worktrees cleaned up after a successful merge (no leak).
    leaked = [
        p for p in await manager.git.list_worktree_paths(str(repo))
        if "swarm-" in Path(p).name
    ]
    assert leaked == [], f"agent worktrees leaked: {leaked}"

    # The shared issue worktree is consistent with the moved ref (no stale index
    # reporting phantom deletions) and has both files on disk.
    status = _git("status", "--porcelain", cwd=Path(issue.git_worktree_path))
    assert status.strip() == ""
    assert (Path(issue.git_worktree_path) / "a.txt").exists()
    assert (Path(issue.git_worktree_path) / "b.txt").exists()


@pytest.mark.asyncio
async def test_dispatch_batch_three_same_role_engineers_merge_modules(
    monkeypatch, store, manager, repo
):
    """REAL-run regression: three independent engineer agents writing
    module_a.py/module_b.py/module_c.py must merge back into the issue worktree.

    This mirrors the browser-observed issue "REAL run: three tiny independent
    modules in parallel" where agents reported success but the issue ended with
    no mergeable diff.
    """
    project, issue = await _seed_project_and_issue(store, manager, repo)
    reg = _build_tools(store, manager, project, issue)
    main_before = _git("rev-parse", "main", cwd=repo).strip()

    def write_plan(wt: str):
        module_by_suffix = {
            "engineer": ("module_a.py", "def add(a, b):\n    return a + b\n"),
            "engineer-2": ("module_b.py", "def mul(a, b):\n    return a * b\n"),
            "engineer-3": ("module_c.py", "def sub(a, b):\n    return a - b\n"),
        }
        agent_key = next(key for key in module_by_suffix if Path(wt).name.endswith(f"-{key}"))
        name, content = module_by_suffix[agent_key]

        def _do(p: Path):
            (p / name).write_text(content)
        return _do

    _patch_subagent_execution(monkeypatch, write_plan=write_plan)

    out = await reg.tools["dispatch_batch"]({"agents": [
        {"role": "engineer", "prompt": "create module_a.py with add"},
        {"role": "engineer", "prompt": "create module_b.py with mul"},
        {"role": "engineer", "prompt": "create module_c.py with sub"},
    ]})

    assert out["status"] == "batch_complete"
    assert out["succeeded_count"] == 3
    assert out["failed_count"] == 0
    assert out["merge_status"] == "merged"
    assert len(out["merged"]) == 3

    issue_tree = _git("ls-tree", "-r", "--name-only", issue.git_branch, cwd=repo)
    assert "module_a.py" in issue_tree
    assert "module_b.py" in issue_tree
    assert "module_c.py" in issue_tree
    issue_wt = Path(issue.git_worktree_path)
    assert (issue_wt / "module_a.py").read_text() == "def add(a, b):\n    return a + b\n"
    assert (issue_wt / "module_b.py").read_text() == "def mul(a, b):\n    return a * b\n"
    assert (issue_wt / "module_c.py").read_text() == "def sub(a, b):\n    return a - b\n"

    assert _git("rev-parse", "main", cwd=repo).strip() == main_before
    main_tree = _git("ls-tree", "-r", "--name-only", "main", cwd=repo)
    assert "module_a.py" not in main_tree
    assert "module_b.py" not in main_tree
    assert "module_c.py" not in main_tree


# --------------------------------------------------------------------------- #
# Scenario 2: real conflict -> structured surfacing, no rollback.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_dispatch_batch_real_conflict_surfaces_structured(
    monkeypatch, store, manager, repo
):
    """Two agents edit the SAME file with conflicting content via REAL git. The
    merge-back stops at the first conflict; asserts:
      - exactly one agent merged cleanly (not rolled back),
      - merge_status == 'conflict' with the conflicting file enumerated,
      - the conflicting agent's worktree is KEPT for reconcile.
    """
    project, issue = await _seed_project_and_issue(store, manager, repo)
    reg = _build_tools(store, manager, project, issue)

    def write_plan(wt: str):
        # Both agents write DIFFERENT content to the SAME file -> real conflict
        # on the second merge.
        tag = "A" if wt.endswith("engineer") else "B"

        def _do(p: Path):
            (p / "shared.txt").write_text(f"from {tag}\n")
        return _do

    _patch_subagent_execution(monkeypatch, write_plan=write_plan)

    out = await reg.tools["dispatch_batch"]({"agents": [
        {"role": "engineer", "prompt": "edit shared.txt"},
        {"role": "qa", "prompt": "edit shared.txt"},
    ]})

    assert out["merge_status"] == "conflict"
    # First agent merged cleanly; second conflicts (stop-on-first-conflict).
    assert len(out["merged"]) == 1
    assert len(out["conflicts"]) == 1
    conflict = out["conflicts"][0]
    assert "shared.txt" in conflict["files"]
    assert conflict["diff"], "conflict diff must be captured for the reconcile turn"

    merged_key = out["merged"][0]["agent_key"]
    conflict_key = conflict["agent_key"]
    assert merged_key != conflict_key

    # The already-merged agent's commit was NOT rolled back.
    issue_log = _git("log", "--oneline", issue.git_branch, cwd=repo)
    assert f"merge swarm agent {merged_key}" in issue_log
    assert f"merge swarm agent {conflict_key}" not in issue_log

    # The conflicting agent's worktree is KEPT for reconcile; the merged one is
    # cleaned. Probe the live worktree list.
    live = await manager.git.list_worktree_paths(str(repo))
    kept = [p for p in live if f"-{conflict_key}" in Path(p).name and "swarm-" in Path(p).name]
    assert kept, "conflicting agent worktree must be kept for reconcile"

    # main stays clean even on the conflict path.
    main_tree = _git("ls-tree", "-r", "--name-only", "main", cwd=repo)
    assert "shared.txt" not in main_tree


# --------------------------------------------------------------------------- #
# Scenario 2b: no-op agent (no produced changes) -> clean no-op, not a conflict.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_dispatch_batch_noop_agent_is_clean_not_conflict(
    monkeypatch, store, manager, repo
):
    """Regression: an agent that produces NO files (pure-analysis role / chose not
    to edit anything) must NOT be reported as a conflict. Its branch has nothing
    ahead of the issue branch, so the squash-merge would fail at the empty commit
    — that must be a clean no-op (worktree cleaned, no conflict, others not
    stopped). Drives the full dispatch_batch path through real git.
    """
    project, issue = await _seed_project_and_issue(store, manager, repo)
    reg = _build_tools(store, manager, project, issue)

    def write_plan(wt: str):
        # First agent writes a real file; second agent writes nothing (no-op).
        if wt.endswith("engineer"):
            def _do(p: Path):
                (p / "a.txt").write_text("content of a.txt\n")
            return _do
        return None  # no-op agent: no files produced

    _patch_subagent_execution(monkeypatch, write_plan=write_plan)

    out = await reg.tools["dispatch_batch"]({"agents": [
        {"role": "engineer", "prompt": "write a.txt"},
        {"role": "qa", "prompt": "analyze only, write nothing"},
    ]})

    assert out["status"] == "batch_complete"
    assert out["succeeded_count"] == 2
    # No phantom conflict; the no-op agent is recorded as a no-op merge.
    assert out["merge_status"] == "merged"
    assert "conflicts" not in out
    assert len(out["merged"]) == 1
    assert len(out["noop_merges"]) == 1

    # The real agent's file landed; the no-op agent contributed nothing.
    issue_tree = _git("ls-tree", "-r", "--name-only", issue.git_branch, cwd=repo)
    assert "a.txt" in issue_tree

    # No swarm worktrees leaked (neither the merged nor the no-op agent).
    leaked = [
        p for p in await manager.git.list_worktree_paths(str(repo))
        if "swarm-" in Path(p).name
    ]
    assert leaked == [], f"agent worktrees leaked: {leaked}"

    # main untouched.
    main_tree = _git("ls-tree", "-r", "--name-only", "main", cwd=repo)
    assert "a.txt" not in main_tree


# --------------------------------------------------------------------------- #
# Scenario 3: upstream visibility (flush-then-fork) through dispatch_batch.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_dispatch_batch_flushes_upstream_so_agents_see_it(
    monkeypatch, store, manager, repo
):
    """An uncommitted upstream artifact in the shared issue worktree must be
    flushed onto the issue branch BEFORE per-agent worktrees fork, so each agent
    forks a tree that includes it (PR1 finding). Driven through the real
    dispatch_batch path."""
    project, issue = await _seed_project_and_issue(store, manager, repo)
    reg = _build_tools(store, manager, project, issue)

    # Upstream (PM/architect) leaves an artifact UNCOMMITTED in the issue worktree.
    (Path(issue.git_worktree_path) / "prd.md").write_text("upstream PM output\n")

    seen_upstream: dict[str, bool] = {}

    def write_plan(wt: str):
        def _do(p: Path):
            # Agent records whether it could see the flushed upstream artifact.
            prd = p / "prd.md"
            seen_upstream[wt] = prd.exists() and prd.read_text() == "upstream PM output\n"
            # Also do real work so the merge is non-trivial.
            (p / f"{Path(wt).name}.txt").write_text("agent work\n")
        return _do

    _patch_subagent_execution(monkeypatch, write_plan=write_plan)

    out = await reg.tools["dispatch_batch"]({"agents": [
        {"role": "engineer"},
        {"role": "qa"},
    ]})

    assert out["succeeded_count"] == 2
    # Every agent forked a worktree that already contained the flushed upstream
    # artifact.
    assert seen_upstream and all(seen_upstream.values()), seen_upstream


# --------------------------------------------------------------------------- #
# Scenario 4: budget-driven concurrency downscale (real store aggregation).
# --------------------------------------------------------------------------- #


async def _record_spend(store, issue, project, usd: float) -> None:
    """Persist a COMPLETED execution process so budget aggregation sees real
    accrued spend (only terminal-status processes are summed)."""
    now = datetime.now()
    task = CodexTask(
        id=f"task-{uuid4().hex[:8]}",
        session_id=issue.session_id,
        project_id=project.id,
        issue_id=issue.id,
        title="prior run",
        prompt="...",
        status="done",
        created_at=now,
        updated_at=now,
    )
    await store.save_codex_task(task)
    proc = ExecutionProcess(
        id=f"ep-{uuid4().hex[:8]}",
        task_id=task.id,
        session_id=issue.session_id,
        status="Completed",
        total_cost_usd=usd,
        created_at=now,
        updated_at=now,
        completed_at=now,
    )
    await store.save_execution_process(proc)


@pytest.mark.asyncio
async def test_dispatch_batch_tight_budget_downscales_concurrency(
    monkeypatch, store, manager, repo
):
    """A tight remaining budget must shrink the EFFECTIVE dispatch_batch fan-out
    below the configured cap. Uses the real store's spend aggregation. We assert
    on the emitted concurrency_cap (the actual semaphore size) and on observed
    peak concurrency."""
    monkeypatch.setenv("MAX_PARALLEL_DISPATCH_PER_BATCH", "4")
    monkeypatch.setenv("EST_COST_PER_AGENT_USD", "0.50")
    # Budget 5.0, already spent 4.0 -> remaining 1.0 -> floor(1.0/0.5)=2 agents.
    project, issue = await _seed_project_and_issue(store, manager, repo, budget_usd=5.0)
    await _record_spend(store, issue, project, 4.0)

    reg = _build_tools(store, manager, project, issue)

    # Capture the batch_started event so we can read the chosen concurrency cap.
    events: list[dict] = []

    import app.application.conductor_tools as ctmod

    orig_emit = ctmod._emit

    async def capture_emit(bus, etype, payload):
        if etype == "conductor_tool":
            events.append(payload)
        return await orig_emit(bus, etype, payload)

    monkeypatch.setattr(ctmod, "_emit", capture_emit)

    import asyncio as _asyncio
    live = {"now": 0, "max": 0}

    # Wrap wait so we can measure real peak concurrency through the semaphore.
    counter = {"n": 0}
    paths: dict[str, str | None] = {}

    async def fake_dispatch_role(*, issue, role, prompt_override, store,
                                 task_dispatcher_fn, event_bus, prev_node_key,
                                 agent_worktree_path=None, batch_key=None,
                                 register_completion=False):
        counter["n"] += 1
        task_id = f"task-{counter['n']}"
        paths[task_id] = agent_worktree_path
        return task_id, f"node-{counter['n']}"

    monkeypatch.setattr(task_dispatcher, "dispatch_role", fake_dispatch_role)

    async def fake_wait(self, task_id, *, idle_timeout, hard_timeout, activity_age):
        live["now"] += 1
        live["max"] = max(live["max"], live["now"])
        await _asyncio.sleep(0.02)
        wt = paths.get(task_id)
        if wt is not None:
            (Path(wt) / f"{Path(wt).name}.txt").write_text("x\n")
        live["now"] -= 1
        return {"status": "done", "task_id": task_id}

    monkeypatch.setattr(TaskCompletionRegistry, "wait_for_active", fake_wait)

    out = await reg.tools["dispatch_batch"]({"agents": [
        {"role": "engineer"} for _ in range(4)
    ]})

    assert out["succeeded_count"] == 4
    started = next(e for e in events if e.get("status") == "batch_started")
    assert started["configured_cap"] == 4
    assert started["concurrency_cap"] == 2, started
    # Observed peak concurrency respected the downscaled cap.
    assert live["max"] <= 2, f"peak concurrency {live['max']} exceeded budget cap 2"


@pytest.mark.asyncio
async def test_dispatch_batch_unlimited_budget_keeps_full_concurrency(
    monkeypatch, store, manager, repo
):
    """budget_usd == 0 means unlimited: no downscale; the configured cap stands."""
    monkeypatch.setenv("MAX_PARALLEL_DISPATCH_PER_BATCH", "3")
    # 0 == no ceiling (unlimited).
    project, issue = await _seed_project_and_issue(store, manager, repo, budget_usd=0.0)
    reg = _build_tools(store, manager, project, issue)

    events: list[dict] = []
    import app.application.conductor_tools as ctmod
    orig_emit = ctmod._emit

    async def capture_emit(bus, etype, payload):
        if etype == "conductor_tool":
            events.append(payload)
        return await orig_emit(bus, etype, payload)

    monkeypatch.setattr(ctmod, "_emit", capture_emit)

    def write_plan(wt: str):
        def _do(p: Path):
            (p / f"{Path(wt).name}.txt").write_text("x\n")
        return _do

    _patch_subagent_execution(monkeypatch, write_plan=write_plan)

    out = await reg.tools["dispatch_batch"]({"agents": [
        {"role": "engineer"},
        {"role": "qa"},
        {"role": "architect"},
    ]})

    assert out["succeeded_count"] == 3
    started = next(e for e in events if e.get("status") == "batch_started")
    assert started["configured_cap"] == 3
    assert started["concurrency_cap"] == 3, "unlimited budget must not downscale"


# --------------------------------------------------------------------------- #
# Scenario 5: soft budget semantics — over-budget does NOT hard-kill the batch.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_dispatch_batch_over_budget_is_soft_not_killed(
    monkeypatch, store, manager, repo
):
    """Over-budget must NOT abort/raise in dispatch_batch: it squeezes concurrency
    to 1 (soft) but still runs the agents and merges their work. (Soft-semantics
    contract from the budget spec.)"""
    monkeypatch.setenv("MAX_PARALLEL_DISPATCH_PER_BATCH", "3")
    monkeypatch.setenv("EST_COST_PER_AGENT_USD", "0.50")
    project, issue = await _seed_project_and_issue(store, manager, repo, budget_usd=1.0)
    # Spent 2.0 against a 1.0 budget -> over budget.
    await _record_spend(store, issue, project, 2.0)
    reg = _build_tools(store, manager, project, issue)

    events: list[dict] = []
    import app.application.conductor_tools as ctmod
    orig_emit = ctmod._emit

    async def capture_emit(bus, etype, payload):
        if etype == "conductor_tool":
            events.append(payload)
        return await orig_emit(bus, etype, payload)

    monkeypatch.setattr(ctmod, "_emit", capture_emit)

    def write_plan(wt: str):
        def _do(p: Path):
            (p / f"{Path(wt).name}.txt").write_text("x\n")
        return _do

    _patch_subagent_execution(monkeypatch, write_plan=write_plan)

    out = await reg.tools["dispatch_batch"]({"agents": [
        {"role": "engineer"},
        {"role": "qa"},
    ]})

    # NOT hard-killed: the batch ran to completion and merged.
    assert out["status"] == "batch_complete"
    assert out["succeeded_count"] == 2
    assert out["merge_status"] == "merged"
    # Over budget squeezed concurrency to the floor of 1 (soft, not 0).
    started = next(e for e in events if e.get("status") == "batch_started")
    assert started["concurrency_cap"] == 1, started


# --------------------------------------------------------------------------- #
# Scenario 7: terminal-state swarm worktree cleanup (PR1 — the one real gap).
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_cleanup_issue_swarm_worktrees_removes_residue_main_clean(
    store, manager, repo
):
    """Conductor terminal-state sweep: residual per-agent swarm worktrees +
    `swarm/*` branch refs (left when a batch is kept for reconcile / a loop ends
    mid-flight) are removed by ``cleanup_issue_swarm_worktrees``. Asserts:
      1. the swarm worktree directories are gone,
      2. the `swarm/*` branch refs are gone,
      3. main is byte-for-byte unchanged (zero pollution),
      4. idempotent: a second call is a no-op (no raise).
    """
    project, issue = await _seed_project_and_issue(store, manager, repo)
    main_before = _git("rev-parse", "main", cwd=repo).strip()

    # Create two residual per-agent worktrees (simulating a kept-for-reconcile
    # batch that the conductor finalized without cleaning up).
    br_a, wt_a, _ = await manager.prepare_agent_worktree(project, issue, "engineer")
    br_b, wt_b, _ = await manager.prepare_agent_worktree(project, issue, "qa")
    # Each agent writes + commits a file on its own branch (real divergence).
    (Path(wt_a) / "a.txt").write_text("from engineer\n")
    await manager.git.commit_all(wt_a, "engineer change")
    (Path(wt_b) / "b.txt").write_text("from qa\n")
    await manager.git.commit_all(wt_b, "qa change")

    # Sanity: the worktrees + branches really exist before cleanup.
    live_before = await manager.git.list_worktree_paths(str(repo))
    assert any(Path(p).name.startswith(f"swarm-{issue.id}-") for p in live_before)
    branches_before = await manager.git.list_branch_names(str(repo), f"swarm/{issue.id[:8]}-")
    assert br_a in branches_before and br_b in branches_before

    # --- The terminal sweep. ---
    await manager.cleanup_issue_swarm_worktrees(project, issue)

    # 1) swarm worktree directories gone.
    assert not Path(wt_a).exists()
    assert not Path(wt_b).exists()
    live_after = await manager.git.list_worktree_paths(str(repo))
    assert not any(Path(p).name.startswith(f"swarm-{issue.id}-") for p in live_after)

    # 2) swarm branch refs gone.
    branches_after = await manager.git.list_branch_names(str(repo), f"swarm/{issue.id[:8]}-")
    assert branches_after == [], branches_after
    assert not await manager.git.branch_exists(str(repo), br_a)
    assert not await manager.git.branch_exists(str(repo), br_b)

    # 3) main untouched (byte-for-byte: same ref, none of the agent files).
    assert _git("rev-parse", "main", cwd=repo).strip() == main_before
    main_tree = _git("ls-tree", "-r", "--name-only", "main", cwd=repo)
    assert "a.txt" not in main_tree and "b.txt" not in main_tree

    # The issue branch is also untouched (no merge happened — cleanup never merges).
    assert "a.txt" not in _git("ls-tree", "-r", "--name-only", issue.git_branch, cwd=repo)

    # 4) idempotent: second call is a no-op, no raise.
    await manager.cleanup_issue_swarm_worktrees(project, issue)
    assert _git("rev-parse", "main", cwd=repo).strip() == main_before


@pytest.mark.asyncio
async def test_cleanup_issue_swarm_worktrees_seal_path_main_clean(
    monkeypatch, store, manager, repo
):
    """Wired through the conductor terminal seal: ``_seal_graph_and_issue_status``
    must invoke the swarm cleanup (best-effort) so a conductor-finalized issue
    leaves no residual swarm worktrees/branches and never pollutes main."""
    import app.application.conductor_main_loop as cml
    import app.bootstrap as bootstrap

    project, issue = await _seed_project_and_issue(store, manager, repo)
    main_before = _git("rev-parse", "main", cwd=repo).strip()

    br_a, wt_a, _ = await manager.prepare_agent_worktree(project, issue, "engineer")
    (Path(wt_a) / "a.txt").write_text("from engineer\n")
    await manager.git.commit_all(wt_a, "engineer change")

    # The seal resolves the worktree manager from the bootstrap singleton.
    monkeypatch.setattr(bootstrap, "worktree_manager", manager)

    await cml._seal_graph_and_issue_status(
        store=store, issue=issue, event_bus=None, result_status="done"
    )

    # Residual swarm worktree + branch cleaned by the seal.
    assert not Path(wt_a).exists()
    assert not await manager.git.branch_exists(str(repo), br_a)
    # main untouched.
    assert _git("rev-parse", "main", cwd=repo).strip() == main_before
    assert "a.txt" not in _git("ls-tree", "-r", "--name-only", "main", cwd=repo)
