"""Tests for the deterministic Architect Review diff guard (PR2).

Covers the three guard states plus key boundaries:
  1. hard_mismatch (claimed impl + zero diff) -> deterministic reject, no LLM.
  2. legal empty diff (honest changed_files=[] + zero diff) -> NOT hard reject.
  3. plan_drift (real changes diverge from expected_files) -> soft, not short-circuit.
  4. path normalization (./a/b.py == a/b.py).
  5. expected_files empty -> soft layer skipped, hard layer still applies.
"""

import json
import subprocess
from pathlib import Path

import pytest

from app.application.issue_artifact_documents import IssueArtifactDocuments
from app.application.review_guard import (
    GuardResult,  # noqa: F401
    compute_review_guard,
    render_guard_context,
)

ISSUE_ID = "issue-guard"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _init_repo(repo: Path) -> None:
    """Init a repo on `main` with a base commit, then check out a feature branch.

    Mirrors the real worktree topology: the Engineer runs on a branch forked
    from `main`, so `git diff main..HEAD` reflects only the agent's work.
    """
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-q", "-b", "main")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feature")


def _write_engineer_report(
    repo: Path,
    *,
    status: str,
    changed_files: list[str],
    completed_tasks: list[str] | None = None,
) -> None:
    docs = IssueArtifactDocuments()
    path = docs.engineer_implementation_md_path(str(repo), ISSUE_ID, task_id="eng-1")
    lines = [
        f"# Implementation Report: demo",  # noqa: F541
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


def _write_plan(repo: Path, tasks: list[dict]) -> None:
    docs = IssueArtifactDocuments()
    path = docs.architect_implementation_plan_path(str(repo), ISSUE_ID)
    path.write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")


def _make_real_change(repo: Path, rel: str) -> None:
    """Create + commit a real file change so git diff vs main is non-empty."""
    fp = repo / rel
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text("changed\n", encoding="utf-8")
    _git(repo, "add", rel)
    _git(repo, "commit", "-q", "-m", f"change {rel}")


def test_hard_mismatch_claimed_impl_zero_diff(tmp_path):
    """status=completed + claimed files but zero git diff -> hard_mismatch."""
    repo = tmp_path
    _init_repo(repo)
    _write_engineer_report(repo, status="completed", changed_files=["app/foo.py"])
    # No real change committed -> git diff vs main is empty.

    guard = compute_review_guard(str(repo), ISSUE_ID)
    assert guard.verdict == "hard_mismatch"
    assert guard.is_hard_mismatch is True
    assert guard.actual_files == []
    assert "app/foo.py" in guard.claimed_files


def test_legal_empty_diff_not_hard_reject(tmp_path):
    """Honest changed_files=[] + status=completed + zero diff -> NOT hard reject.

    Even with an implementation status, when the report honestly claims no files
    AND there is genuinely no change, there is no claim-vs-reality contradiction
    that the *files* assert; but status alone still implies implementation. The
    legal-empty-diff contract is specifically: blocked / already-implemented.
    """
    repo = tmp_path
    _init_repo(repo)
    # status=blocked is the canonical legal empty-diff state.
    _write_engineer_report(repo, status="blocked", changed_files=[])

    guard = compute_review_guard(str(repo), ISSUE_ID)
    assert guard.verdict != "hard_mismatch"
    assert guard.is_hard_mismatch is False


def test_completed_but_no_files_no_completed_tasks_not_hard_reject(tmp_path):
    """AC4: honest 'already implemented' (no changed_files, no completed_tasks) passes.

    A report that does not assert any changed files and lists no completed tasks
    is not claiming implementation, so an empty diff is legal even if the status
    string is 'completed'.
    """
    repo = tmp_path
    _init_repo(repo)
    _write_engineer_report(repo, status="completed", changed_files=[])

    guard = compute_review_guard(str(repo), ISSUE_ID)
    assert guard.verdict != "hard_mismatch"


def test_already_implemented_with_completed_tasks_not_hard_reject(tmp_path):
    """AC4 (the critical 误杀 case): honest 'already implemented' report.

    status=completed + changed_files=[] + LISTS completed_tasks (the task was
    genuinely addressed, just without new code) + zero diff must NOT be
    hard-rejected. completed_tasks is not a code-landing claim; only an explicit
    non-empty changed_files contradicting a zero diff is a hard fact. This is a
    real, common scenario the Engineer prompt explicitly sanctions, so the guard
    must defer to the LLM here instead of deterministically rejecting.
    """
    repo = tmp_path
    _init_repo(repo)
    _write_engineer_report(
        repo,
        status="completed",
        changed_files=[],
        completed_tasks=["Verified login flow already exists"],
    )

    guard = compute_review_guard(str(repo), ISSUE_ID)
    assert guard.verdict != "hard_mismatch"
    assert guard.is_hard_mismatch is False
    assert guard.claims_implementation is False


def test_plan_drift_soft_signal(tmp_path):
    """Real changes diverge from expected_files -> plan_drift (soft), not short-circuit."""
    repo = tmp_path
    _init_repo(repo)
    _make_real_change(repo, "app/actual.py")
    _write_engineer_report(repo, status="completed", changed_files=["app/actual.py"])
    _write_plan(
        repo,
        [
            {
                "title": "t1",
                "description": "d",
                "priority": "P1",
                "expected_files": ["app/expected.py"],
            }
        ],
    )

    guard = compute_review_guard(str(repo), ISSUE_ID)
    assert guard.verdict == "plan_drift"
    assert guard.is_hard_mismatch is False
    assert "app/expected.py" in guard.missing
    assert "app/actual.py" in guard.extra
    assert "app/actual.py" in guard.actual_files
    # Real diff is surfaced for the reviewer as ground truth.
    assert guard.diff_summary
    ctx = render_guard_context(guard)
    assert "missing_vs_expected" in ctx
    assert "SOFT signal" in ctx


def test_path_normalization_dot_slash(tmp_path):
    """./a/b.py and a/b.py are treated as the same file (no false drift)."""
    repo = tmp_path
    _init_repo(repo)
    _make_real_change(repo, "a/b.py")
    _write_engineer_report(repo, status="completed", changed_files=["./a/b.py"])
    _write_plan(
        repo,
        [
            {
                "title": "t1",
                "description": "d",
                "priority": "P1",
                "expected_files": ["./a/b.py"],
            }
        ],
    )

    guard = compute_review_guard(str(repo), ISSUE_ID)
    # expected matches actual after normalization -> no drift.
    assert guard.verdict == "ok"
    assert guard.missing == []
    assert guard.extra == []


def test_empty_expected_files_skips_soft_layer(tmp_path):
    """No expected_files predicted -> soft layer skipped; hard layer still active."""
    repo = tmp_path
    _init_repo(repo)
    _make_real_change(repo, "app/x.py")
    _write_engineer_report(repo, status="completed", changed_files=["app/x.py"])
    _write_plan(repo, [{"title": "t1", "description": "d", "priority": "P1", "expected_files": []}])

    guard = compute_review_guard(str(repo), ISSUE_ID)
    # Real change exists + no expected prediction -> ok (no drift judged).
    assert guard.verdict == "ok"
    assert guard.missing == []
    assert guard.extra == []

    # Hard layer still fires when the same report claims impl but diff is empty.
    repo2 = tmp_path / "repo2"
    repo2.mkdir()
    _init_repo(repo2)
    _write_engineer_report(repo2, status="completed", changed_files=["app/y.py"])
    _write_plan(
        repo2, [{"title": "t1", "description": "d", "priority": "P1", "expected_files": []}]
    )
    guard2 = compute_review_guard(str(repo2), ISSUE_ID)
    assert guard2.verdict == "hard_mismatch"


def test_no_workspace_path_returns_ok():
    guard = compute_review_guard(None, ISSUE_ID)
    assert guard.verdict == "ok"
    assert guard.is_hard_mismatch is False


def test_to_artifact_is_json_serializable(tmp_path):
    repo = tmp_path
    _init_repo(repo)
    _write_engineer_report(repo, status="completed", changed_files=["app/foo.py"])
    guard = compute_review_guard(str(repo), ISSUE_ID)
    payload = guard.to_artifact()
    json.dumps(payload)  # must not raise
    assert payload["verdict"] == "hard_mismatch"


# ---------------------------------------------------------------------------
# Endpoint-level: hard short-circuit must NOT dispatch the LLM (AC3),
# and the normal path MUST dispatch it (no regression).
# ---------------------------------------------------------------------------

import shutil  # noqa: E402

import pytest_asyncio  # noqa: E402

_HAS_GIT = shutil.which("git") is not None


@pytest_asyncio.fixture
async def store(client):  # client fixture initializes the app + sqlite store
    import app.interfaces.api as api_module

    assert api_module.codex_store is not None
    return api_module.codex_store


async def _make_parent_task(store, repo: Path):
    from datetime import datetime

    from app.domain.models import CodexTask

    task = CodexTask(
        id=f"parent-{repo.name}",
        session_id="ws-guard",
        issue_id=ISSUE_ID,
        phase="development",
        title="impl demo",
        prompt="implement",
        role="engineer",
        executor="codex",
        status="done",
        workspace_path=str(repo),
    )
    task.created_at = datetime.now()
    task.updated_at = datetime.now()
    await store.save_codex_task(task)
    return task


@pytest.mark.skipif(not _HAS_GIT, reason="git binary not available")
@pytest.mark.asyncio
async def test_submit_hard_mismatch_skips_llm_and_reworks_parent(store, tmp_path, monkeypatch):
    """Claimed impl + zero diff -> deterministic reject, run_codex_task NOT called."""
    import app.interfaces.api as api_module

    repo = tmp_path / "hardrepo"
    repo.mkdir()
    _init_repo(repo)
    _write_engineer_report(repo, status="completed", changed_files=["app/foo.py"])

    parent = await _make_parent_task(store, repo)

    called = {"n": 0}

    async def _fake_run(task_id):  # pragma: no cover - must NOT be hit
        called["n"] += 1
        return None

    monkeypatch.setattr(api_module, "run_codex_task", _fake_run)

    await api_module.submit_codex_task_for_review(parent.id)

    # LLM review must not have been dispatched.
    assert called["n"] == 0

    reloaded = await store.load_codex_task(parent.id)
    assert reloaded.status == "rework"
    assert reloaded.review_comment and "[FRAMEWORK]" in reloaded.review_comment


@pytest.mark.skipif(not _HAS_GIT, reason="git binary not available")
@pytest.mark.asyncio
async def test_submit_real_change_dispatches_llm(store, tmp_path, monkeypatch):
    """Real diff present -> normal path runs run_codex_task (no short-circuit)."""
    import app.interfaces.api as api_module

    repo = tmp_path / "okrepo"
    repo.mkdir()
    _init_repo(repo)
    _make_real_change(repo, "app/real.py")
    _write_engineer_report(repo, status="completed", changed_files=["app/real.py"])

    parent = await _make_parent_task(store, repo)

    called = {"n": 0}

    async def _fake_run(task_id):
        called["n"] += 1
        return None

    monkeypatch.setattr(api_module, "run_codex_task", _fake_run)

    await api_module.submit_codex_task_for_review(parent.id)

    assert called["n"] == 1
