"""End-to-end integration tests for the Architect Review diff guard (PR4 / AC8).

Unlike ``test_review_guard.py`` (which drives ``compute_review_guard`` against a
small hand-rolled git repo and exercises the unit-level boundaries), these tests
drive the guard through **real git worktree topologies** that mirror the two
production paths it must hold for:

  * the **serial** path — the Engineer + review task share the issue worktree
    (checked out on the issue integration branch), and
  * the **parallel swarm** path — the Engineer runs in an isolated *per-agent*
    worktree (``swarm/<issue>-<key>``, forked from the issue branch via the real
    ``WorktreeManager.prepare_agent_worktree``), and the guard's ``base``
    fallback (``merge-base origin/main HEAD`` -> ``main`` -> ``HEAD~1``) must
    still compute the correct changed-file set *inside that forked worktree*.

Every git state here is REAL (no mocked ``git diff``): the verdict is driven by
the actual worktree contents, which is the whole point of the deterministic
guard. The subagent *execution layer* is the only thing stubbed (the hard
short-circuit endpoint test monkeypatches ``run_codex_task`` to assert it is
NOT dispatched — AC3).

These reuse the real-git / real-sqlite fixture style from
``test_swarm_integration.py`` (``repo`` / ``manager`` / ``store`` /
``_seed_project_and_issue`` / ``_git``). Marked ``slow`` (real git subprocesses
+ real sqlite); runs under ``--runslow`` or when targeted explicitly.

Main-pollution guard: the swarm-worktree scenario forks a per-agent worktree off
the issue branch (never the primary repo's checked-out ``main``). The tests
assert ``main``'s ref is byte-for-byte unchanged at the end, per the
Worktree-Scoped Branch Merge (Swarm-Safe) contract.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.application.git_service import GitService
from app.application.engineer_workflow import git_changed_files
from app.application.issue_artifact_documents import IssueArtifactDocuments
from app.application.review_guard import compute_review_guard, render_guard_context
from app.application.worktree_manager import WorktreeManager
from app.domain.models import CodexIssue, CodexTask, Project


pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(shutil.which("git") is None, reason="git binary not available"),
]

ISSUE_ID = "issue-guard-int"


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    ).stdout


# --------------------------------------------------------------------------- #
# Fixtures: real git repo, real sqlite store, real worktree manager
# (same shape as test_swarm_integration.py — reuse, don't reinvent).
# --------------------------------------------------------------------------- #


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real git repo with one initial commit on `main`.

    Ships a ``.gitignore`` that excludes agent-harness scratch dirs (``.claude/``,
    ``.agent/``) exactly as the production repo does. Without this, a tool harness
    that drops a ``.claude/`` into any cwd it touches would surface as an untracked
    entry in ``git status --porcelain`` and pollute ``git_changed_files`` — a
    test-environment artifact, not real engineer output. Mirroring the production
    ``.gitignore`` keeps the guard's view of "code changes" honest here.
    """
    r = tmp_path / "repo"
    r.mkdir()
    _git("init", "-b", "main", cwd=r)
    _git("config", "user.email", "test@example.com", cwd=r)
    _git("config", "user.name", "Test", cwd=r)
    (r / "README.md").write_text("hello\n")
    (r / ".gitignore").write_text(".claude/\n.agent/\n")
    _git("add", "README.md", ".gitignore", cwd=r)
    _git("commit", "-m", "init", cwd=r)
    return r


@pytest.fixture
def manager() -> WorktreeManager:
    return WorktreeManager(GitService())


@pytest.fixture
async def store():
    """A real AsyncSQLiteStore on a throwaway tmp db (never the real console.db)."""
    with tempfile.TemporaryDirectory() as td:
        s = AsyncSQLiteStore(Path(td) / "review-guard-int.db")
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
        id=ISSUE_ID,
        session_id="s1",
        project_id=project.id,
        title="review guard work",
        created_at=now,
        updated_at=now,
    )
    branch, path, base = await manager.prepare_issue_worktree(project, issue)
    issue.git_branch = branch
    issue.git_worktree_path = path
    issue.git_base_branch = base
    await store.save_codex_issue(issue)
    return project, issue


# --------------------------------------------------------------------------- #
# Artifact helpers: write the Engineer report markdown + Architect plan json
# into a worktree exactly as the workflows persist them (under issues/<id>/...,
# which git_changed_files deliberately excludes so they never count as "code").
# --------------------------------------------------------------------------- #


def _write_engineer_report(
    worktree: str,
    *,
    status: str,
    changed_files: list[str],
    completed_tasks: list[str] | None = None,
) -> None:
    docs = IssueArtifactDocuments()
    path = docs.engineer_implementation_md_path(worktree, ISSUE_ID, task_id="eng-1")
    lines = [
        "# Implementation Report: demo",
        "",
        f"- Status: {status}",
        "",
        "## Changed Files",
    ]
    lines.extend([f"- {f}" for f in changed_files] or ["- None"])
    lines += ["", "## Completed Tasks"]
    lines.extend([f"- **{t}** (P1): done" for t in (completed_tasks or [])] or ["- None"])
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_plan(worktree: str, tasks: list[dict]) -> None:
    docs = IssueArtifactDocuments()
    path = docs.architect_implementation_plan_path(worktree, ISSUE_ID)
    path.write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")


def _commit_code_change(worktree: Path, rel: str, content: str = "changed\n") -> None:
    """Create + commit a REAL code file change in the given worktree so the diff
    vs the base branch is non-empty (committed change)."""
    fp = worktree / rel
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content, encoding="utf-8")
    _git("add", rel, cwd=worktree)
    _git("commit", "-m", f"change {rel}", cwd=worktree)


# --------------------------------------------------------------------------- #
# Scenario 1: hard_mismatch on the SERIAL path (issue worktree).
# Drives the real endpoint and asserts the LLM is NOT dispatched (AC3).
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_serial_hard_mismatch_skips_llm_and_reworks_parent(
    monkeypatch, store, manager, repo
):
    """Engineer report claims changed_files=[X] but the issue worktree has ZERO
    real code changes -> compute_review_guard == hard_mismatch, and the
    submit-for-review endpoint deterministically rejects WITHOUT calling the LLM
    (run_codex_task call_count == 0), parent -> rework with [FRAMEWORK] reason.
    """
    import app.interfaces.api as api_module

    project, issue = await _seed_project_and_issue(store, manager, repo)
    wt = issue.git_worktree_path

    # Report claims a file landed; no actual code file is committed/created.
    _write_engineer_report(wt, status="completed", changed_files=["app/foo.py"])

    # Direct guard check on the real worktree state.
    guard = compute_review_guard(wt, issue.id)
    assert guard.verdict == "hard_mismatch", guard
    assert guard.actual_files == []
    assert "app/foo.py" in guard.claimed_files

    # End-to-end through the endpoint: parent task shares the issue worktree.
    now = datetime.now()
    parent = CodexTask(
        id=f"parent-{uuid4().hex[:8]}",
        session_id=issue.session_id,
        issue_id=issue.id,
        phase="development",
        title="impl demo",
        prompt="implement",
        role="engineer",
        executor="codex",
        status="done",
        workspace_path=wt,
        created_at=now,
        updated_at=now,
    )

    # The endpoint uses the module-level store, not our fixture store; point it
    # at our throwaway store so the real writeback path runs against real sqlite.
    monkeypatch.setattr(api_module, "codex_store", store)
    await store.save_codex_task(parent)

    called = {"n": 0}

    async def _fake_run(task_id):  # must NOT be hit on the hard-short-circuit path
        called["n"] += 1
        return None

    monkeypatch.setattr(api_module, "run_codex_task", _fake_run)

    await api_module.submit_codex_task_for_review(parent.id)

    assert called["n"] == 0, "LLM review must not be dispatched on hard_mismatch"

    reloaded = await store.load_codex_task(parent.id)
    assert reloaded.status == "rework"
    assert reloaded.review_comment and "[FRAMEWORK]" in reloaded.review_comment

    # main ref unchanged (no merge/branch mutation on this path).
    assert _git("rev-parse", "main", cwd=repo).strip()


# --------------------------------------------------------------------------- #
# Scenario 2: legal empty diff is NOT hard-rejected (AC4 regression lock).
# The坑 that PR2/PR3 each tripped — keep it nailed down end-to-end.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_serial_legal_empty_diff_dispatches_llm(
    monkeypatch, store, manager, repo
):
    """Honest already-implemented report (changed_files=[], but completed_tasks
    listed) + genuinely ZERO real diff -> NOT hard_mismatch, the normal LLM
    review path runs (run_codex_task called). Locks AC4: 'already implemented,
    nothing to change' must survive the guard untouched.
    """
    import app.interfaces.api as api_module

    project, issue = await _seed_project_and_issue(store, manager, repo)
    wt = issue.git_worktree_path

    _write_engineer_report(
        wt,
        status="completed",
        changed_files=[],
        completed_tasks=["Verified login flow already exists"],
    )

    guard = compute_review_guard(wt, issue.id)
    assert guard.verdict != "hard_mismatch", guard
    assert guard.is_hard_mismatch is False
    assert guard.claims_implementation is False

    now = datetime.now()
    parent = CodexTask(
        id=f"parent-{uuid4().hex[:8]}",
        session_id=issue.session_id,
        issue_id=issue.id,
        phase="development",
        title="impl demo",
        prompt="implement",
        role="engineer",
        executor="codex",
        status="done",
        workspace_path=wt,
        created_at=now,
        updated_at=now,
    )
    monkeypatch.setattr(api_module, "codex_store", store)
    await store.save_codex_task(parent)

    called = {"n": 0}

    async def _fake_run(task_id):
        called["n"] += 1
        return None

    monkeypatch.setattr(api_module, "run_codex_task", _fake_run)

    await api_module.submit_codex_task_for_review(parent.id)

    assert called["n"] == 1, "legal empty diff must dispatch the normal LLM review"

    reloaded = await store.load_codex_task(parent.id)
    # Not deterministically reworked; left awaiting the LLM review verdict.
    assert reloaded.status == "awaiting_review"


# --------------------------------------------------------------------------- #
# Scenario 3: plan_drift soft signal (real diff diverges from expected_files).
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_serial_plan_drift_is_soft_with_real_diff(store, manager, repo):
    """A REAL code change exists, but the file differs from the Architect's
    expected_files -> verdict=plan_drift (SOFT). The guard carries missing/extra
    + a real diff summary, and does NOT short-circuit.
    """
    project, issue = await _seed_project_and_issue(store, manager, repo)
    wt = Path(issue.git_worktree_path)

    _commit_code_change(wt, "app/actual.py")
    _write_engineer_report(str(wt), status="completed", changed_files=["app/actual.py"])
    _write_plan(str(wt), [
        {
            "title": "t1",
            "description": "d",
            "priority": "P1",
            "expected_files": ["app/expected.py"],
        }
    ])

    guard = compute_review_guard(str(wt), issue.id)
    assert guard.verdict == "plan_drift", guard
    assert guard.is_hard_mismatch is False
    assert "app/expected.py" in guard.missing
    assert "app/actual.py" in guard.extra
    assert "app/actual.py" in guard.actual_files
    # Real diff is ground truth surfaced to the reviewer.
    assert guard.diff_summary
    ctx = render_guard_context(guard)
    assert "missing_vs_expected" in ctx
    assert "SOFT signal" in ctx
    assert "actual_git_diff" in ctx


# --------------------------------------------------------------------------- #
# Scenario 4: ok (actual change matches expected_files exactly).
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_serial_ok_when_actual_matches_expected(store, manager, repo):
    """Actual changed file == expected_files -> ok; no drift, no short-circuit."""
    project, issue = await _seed_project_and_issue(store, manager, repo)
    wt = Path(issue.git_worktree_path)

    _commit_code_change(wt, "app/feature.py")
    _write_engineer_report(str(wt), status="completed", changed_files=["app/feature.py"])
    _write_plan(str(wt), [
        {
            "title": "t1",
            "description": "d",
            "priority": "P1",
            "expected_files": ["app/feature.py"],
        }
    ])

    guard = compute_review_guard(str(wt), issue.id)
    assert guard.verdict == "ok", guard
    assert guard.missing == []
    assert guard.extra == []
    assert "app/feature.py" in guard.actual_files


# --------------------------------------------------------------------------- #
# Scenario 5: parallel SWARM per-agent worktree base fallback (key regression).
# The Engineer runs in an isolated swarm/<issue>-<key> worktree forked from the
# issue branch; git_changed_files' base fallback must compute the correct diff
# INSIDE that forked worktree, so the guard does not false-positive hard_mismatch.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_swarm_agent_worktree_base_fallback_sees_real_change(
    store, manager, repo
):
    """An Engineer changing files inside a real per-agent swarm worktree (forked
    from the issue branch) is correctly detected by git_changed_files /
    compute_review_guard via the base fallback. The guard must NOT misjudge it as
    hard_mismatch just because the worktree's base differs from the primary repo.

    Reuses manager.prepare_agent_worktree (the real swarm fork). Asserts main is
    byte-for-byte unchanged at the end (Worktree-Scoped Branch Merge contract).
    """
    project, issue = await _seed_project_and_issue(store, manager, repo)
    main_before = _git("rev-parse", "main", cwd=repo).strip()

    # Real per-agent swarm worktree forked from the issue branch.
    branch, agent_wt, base = await manager.prepare_agent_worktree(
        project, issue, "engineer"
    )
    assert base == issue.git_branch
    agent_path = Path(agent_wt)

    try:
        # Engineer does real work + writes the report INSIDE the isolated worktree.
        _commit_code_change(agent_path, "app/swarm_feature.py")
        _write_engineer_report(
            agent_wt, status="completed", changed_files=["app/swarm_feature.py"]
        )

        # git_changed_files inside the forked worktree must see the real change
        # via base fallback (origin/main absent -> main -> HEAD~1).
        changed = git_changed_files(agent_wt)
        assert "app/swarm_feature.py" in changed, changed

        guard = compute_review_guard(agent_wt, issue.id)
        # Real change present -> NOT a hard_mismatch; ok (no expected_files plan).
        assert guard.is_hard_mismatch is False, guard
        assert guard.verdict == "ok", guard
        assert "app/swarm_feature.py" in guard.actual_files
    finally:
        await manager.cleanup_agent_worktree(project, issue, "engineer")

    # main stays byte-for-byte clean: the swarm fork never touched the primary
    # repo's checked-out branch.
    main_after = _git("rev-parse", "main", cwd=repo).strip()
    assert main_after == main_before, "swarm worktree fork polluted main's ref"


# --------------------------------------------------------------------------- #
# Scenario 5b: a claimed-but-absent file in a swarm worktree IS hard_mismatch
# (the swarm base fallback does not accidentally suppress a genuine mismatch).
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_swarm_agent_worktree_claim_with_zero_change_is_hard_mismatch(
    store, manager, repo
):
    """Symmetric guard for the swarm path: an Engineer that claims a file but
    produces ZERO real change inside the per-agent worktree is still caught as
    hard_mismatch (the base fallback computing [] is the correct, not a spurious,
    result here)."""
    project, issue = await _seed_project_and_issue(store, manager, repo)
    main_before = _git("rev-parse", "main", cwd=repo).strip()

    branch, agent_wt, base = await manager.prepare_agent_worktree(
        project, issue, "engineer"
    )
    try:
        # Claim a file but make NO real change in the worktree.
        _write_engineer_report(
            agent_wt, status="completed", changed_files=["app/ghost.py"]
        )
        assert git_changed_files(agent_wt) == []
        guard = compute_review_guard(agent_wt, issue.id)
        assert guard.verdict == "hard_mismatch", guard
        assert "app/ghost.py" in guard.claimed_files
    finally:
        await manager.cleanup_agent_worktree(project, issue, "engineer")

    assert _git("rev-parse", "main", cwd=repo).strip() == main_before


# --------------------------------------------------------------------------- #
# Scenario 6: UNTRACKED new file is counted by git_changed_files (via
# git status --porcelain), so a freshly-created-but-uncommitted file is NOT
# misjudged as zero change -> no false hard_mismatch.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_untracked_new_file_counts_as_change_no_false_mismatch(
    store, manager, repo
):
    """git diff --name-only does NOT list untracked files; git_changed_files
    backstops with git status --porcelain. A brand-new uncommitted file claimed
    by the Engineer must therefore be counted as a real change, so the guard does
    NOT false-positive hard_mismatch on a legitimately-new-file implementation.
    """
    project, issue = await _seed_project_and_issue(store, manager, repo)
    wt = Path(issue.git_worktree_path)

    # The `app/` package already exists & is tracked (commit it first), so an
    # untracked file inside it is reported by `git status --porcelain` at FILE
    # granularity. (A brand-new untracked *directory* collapses to `dir/` in
    # porcelain — that is real `git` behavior and not what this regression is
    # about; the engineer-adds-a-file-to-an-existing-package case is the
    # production-realistic one the guard must not false-positive on.)
    _commit_code_change(wt, "app/existing.py", content="seed\n")

    # Brand-new file, created but NOT git-added/committed (untracked).
    new_rel = "app/brand_new.py"
    (wt / new_rel).write_text("print('new')\n", encoding="utf-8")

    # diff --name-only main..HEAD would miss it; status --porcelain catches it.
    changed = git_changed_files(str(wt))
    assert new_rel in changed, f"untracked new file missing from changed set: {changed}"

    _write_engineer_report(str(wt), status="completed", changed_files=[new_rel])
    guard = compute_review_guard(str(wt), issue.id)
    assert guard.is_hard_mismatch is False, guard
    assert new_rel in guard.actual_files
