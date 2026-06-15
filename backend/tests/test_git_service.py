"""Integration tests for GitService against a real local git binary."""
from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from app.application.git_service import GitError, GitService

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary not available")


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git("init", "-b", "main", cwd=r)
    _git("config", "user.email", "test@example.com", cwd=r)
    _git("config", "user.name", "Test", cwd=r)
    (r / "README.md").write_text("hello")
    _git("add", "README.md", cwd=r)
    _git("commit", "-m", "init", cwd=r)
    return r


@pytest.mark.asyncio
async def test_is_git_repo_true_for_real_repo(repo: Path):
    svc = GitService()
    assert await svc.is_git_repo(repo) is True


@pytest.mark.asyncio
async def test_is_git_repo_false_for_plain_dir(tmp_path: Path):
    svc = GitService()
    assert await svc.is_git_repo(tmp_path) is False


@pytest.mark.asyncio
async def test_default_branch_falls_back_to_head(repo: Path):
    svc = GitService()
    assert await svc.default_branch(repo) == "main"


@pytest.mark.asyncio
async def test_list_branches_includes_main(repo: Path):
    svc = GitService()
    branches = await svc.list_branches(repo)
    names = [b.name for b in branches]
    assert "main" in names
    main = next(b for b in branches if b.name == "main")
    assert main.is_current is True


@pytest.mark.asyncio
async def test_create_worktree_branches_from_base(repo: Path, tmp_path: Path):
    svc = GitService()
    wt = tmp_path / "wt"
    await svc.create_worktree(repo, "feature/x", wt, "main")
    assert (wt / "README.md").exists()
    assert await svc.is_git_repo(wt) is True


@pytest.mark.asyncio
async def test_squash_merge_lands_on_base(repo: Path, tmp_path: Path):
    svc = GitService()
    wt = tmp_path / "wt"
    await svc.create_worktree(repo, "feature/y", wt, "main")
    (wt / "file.txt").write_text("payload")
    _git("add", "file.txt", cwd=wt)
    _git("-c", "user.email=t@e", "-c", "user.name=T", "commit", "-m", "add file", cwd=wt)
    sha = await svc.squash_merge(repo, "feature/y", "main", "merge feature/y")
    log = subprocess.run(
        ["git", "log", "--oneline", "main"], cwd=str(repo), capture_output=True, text=True, check=True
    ).stdout
    assert "merge feature/y" in log
    assert len(sha) >= 7


@pytest.mark.asyncio
async def test_remove_worktree_cleans_metadata(repo: Path, tmp_path: Path):
    svc = GitService()
    wt = tmp_path / "wt"
    await svc.create_worktree(repo, "feature/z", wt, "main")
    await svc.remove_worktree(repo, wt)
    listing = subprocess.run(
        ["git", "worktree", "list"], cwd=str(repo), capture_output=True, text=True, check=True
    ).stdout
    assert str(wt) not in listing


@pytest.mark.asyncio
async def test_conflicted_files_empty_on_clean_tree(repo: Path):
    svc = GitService()
    assert await svc.conflicted_files(repo) == []


@pytest.mark.asyncio
async def test_conflicted_files_lists_unmerged_paths(repo: Path):
    svc = GitService()
    # Two branches edit the same line so a merge produces a conflict.
    _git("checkout", "-b", "branch-a", cwd=repo)
    (repo / "shared.txt").write_text("from A\n")
    _git("add", "shared.txt", cwd=repo)
    _git("-c", "user.email=t@e", "-c", "user.name=T", "commit", "-m", "A edit", cwd=repo)

    _git("checkout", "main", cwd=repo)
    _git("checkout", "-b", "branch-b", cwd=repo)
    (repo / "shared.txt").write_text("from B\n")
    _git("add", "shared.txt", cwd=repo)
    _git("-c", "user.email=t@e", "-c", "user.name=T", "commit", "-m", "B edit", cwd=repo)

    # Merge A into B → conflict on shared.txt (merge leaves conflict state behind).
    subprocess.run(["git", "merge", "branch-a"], cwd=str(repo), capture_output=True)
    files = await svc.conflicted_files(repo)
    assert files == ["shared.txt"]
    subprocess.run(["git", "merge", "--abort"], cwd=str(repo), capture_output=True)


@pytest.mark.asyncio
async def test_create_worktree_rejects_branch_starting_with_dash(repo: Path, tmp_path: Path):
    svc = GitService()
    with pytest.raises(GitError):
        await svc.create_worktree(repo, "-rf", tmp_path / "wt2", "main")


@pytest.mark.asyncio
async def test_clone_rejects_url_starting_with_dash(tmp_path: Path):
    svc = GitService()
    with pytest.raises(GitError):
        await svc.clone("--upload-pack=evil", tmp_path / "dest")


# --- Remote sync (fetch / remote_status / fast_forward) ---


def _commit(cwd: Path, name: str, content: str, message: str) -> None:
    (cwd / name).write_text(content)
    _git("add", name, cwd=cwd)
    _git("-c", "user.email=t@e", "-c", "user.name=T", "commit", "-m", message, cwd=cwd)


@pytest.fixture
def clone_pair(tmp_path: Path) -> tuple[Path, Path]:
    """An `origin` bare repo and a working clone of it (origin remote set, on main)."""
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    seed.mkdir()
    _git("init", "-b", "main", cwd=seed)
    _git("config", "user.email", "test@example.com", cwd=seed)
    _git("config", "user.name", "Test", cwd=seed)
    _commit(seed, "README.md", "hello\n", "init")
    _git("clone", "--bare", str(seed), str(origin), cwd=tmp_path)

    work = tmp_path / "work"
    _git("clone", str(origin), str(work), cwd=tmp_path)
    _git("config", "user.email", "test@example.com", cwd=work)
    _git("config", "user.name", "Test", cwd=work)
    return origin, work


def _advance_origin(origin: Path, tmp_path: Path, *, message: str = "upstream") -> None:
    """Push a new commit into the bare origin so clones become 1 behind."""
    pusher = tmp_path / "pusher"
    if not pusher.exists():
        _git("clone", str(origin), str(pusher), cwd=tmp_path)
        _git("config", "user.email", "test@example.com", cwd=pusher)
        _git("config", "user.name", "Test", cwd=pusher)
    _commit(pusher, "upstream.txt", message + "\n", message)
    _git("push", "origin", "main", cwd=pusher)


@pytest.mark.asyncio
async def test_remote_status_up_to_date(clone_pair: tuple[Path, Path]):
    svc = GitService()
    _origin, work = clone_pair
    status = await svc.remote_status(work, branch="main")
    assert status["has_origin"] is True
    assert status["error"] is None
    assert status["behind"] == 0
    assert status["ahead"] == 0
    assert status["can_fast_forward"] is False
    assert status["fetched"] is True


@pytest.mark.asyncio
async def test_remote_status_detects_behind_and_can_ff(clone_pair, tmp_path):
    svc = GitService()
    origin, work = clone_pair
    _advance_origin(origin, tmp_path)
    status = await svc.remote_status(work, branch="main")
    assert status["behind"] == 1
    assert status["ahead"] == 0
    assert status["dirty"] is False
    assert status["can_fast_forward"] is True


@pytest.mark.asyncio
async def test_remote_status_dirty_blocks_ff(clone_pair, tmp_path):
    svc = GitService()
    origin, work = clone_pair
    _advance_origin(origin, tmp_path)
    (work / "README.md").write_text("locally edited\n")  # uncommitted change
    status = await svc.remote_status(work, branch="main")
    assert status["behind"] == 1
    assert status["dirty"] is True
    assert status["can_fast_forward"] is False


@pytest.mark.asyncio
async def test_remote_status_diverged_blocks_ff(clone_pair, tmp_path):
    svc = GitService()
    origin, work = clone_pair
    _advance_origin(origin, tmp_path)
    _commit(work, "local.txt", "local work\n", "local commit")  # diverge
    status = await svc.remote_status(work, branch="main")
    assert status["behind"] == 1
    assert status["ahead"] == 1
    assert status["can_fast_forward"] is False


@pytest.mark.asyncio
async def test_remote_status_no_origin(repo: Path):
    svc = GitService()
    status = await svc.remote_status(repo, branch="main")
    assert status["has_origin"] is False
    assert status["error"] == "no_origin"
    assert status["can_fast_forward"] is False


@pytest.mark.asyncio
async def test_remote_status_not_a_git_repo(tmp_path: Path):
    svc = GitService()
    status = await svc.remote_status(tmp_path, branch="main")
    assert status["error"] == "not_a_git_repo"
    assert status["can_fast_forward"] is False


@pytest.mark.asyncio
async def test_fast_forward_advances_head(clone_pair, tmp_path):
    svc = GitService()
    origin, work = clone_pair
    _advance_origin(origin, tmp_path)
    before = await svc.head_commit(work)
    await svc.fetch(work)
    new_sha = await svc.fast_forward(work, "main")
    assert new_sha != before
    assert (work / "upstream.txt").exists()
    # Now clean and up to date.
    status = await svc.remote_status(work, branch="main", do_fetch=False)
    assert status["behind"] == 0


@pytest.mark.asyncio
async def test_fast_forward_refuses_when_diverged(clone_pair, tmp_path):
    svc = GitService()
    origin, work = clone_pair
    _advance_origin(origin, tmp_path)
    _commit(work, "local.txt", "local work\n", "local commit")
    await svc.fetch(work)
    head_before = await svc.head_commit(work)
    with pytest.raises(GitError):
        await svc.fast_forward(work, "main")
    # Working tree / HEAD untouched on failure.
    assert await svc.head_commit(work) == head_before


@pytest.mark.asyncio
async def test_fetch_rejects_remote_starting_with_dash(repo: Path):
    svc = GitService()
    with pytest.raises(GitError):
        await svc.fetch(repo, remote="-rf")
