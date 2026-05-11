from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from app.application.git_service import GitService
from app.application.worktree_manager import WorktreeManager
from app.domain.models import CodexIssue, CodexTask, Project


pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary not available")


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    r = tmp_path / "repo"
    r.mkdir()
    _git("init", "-b", "main", cwd=r)
    _git("config", "user.email", "test@example.com", cwd=r)
    _git("config", "user.name", "Test", cwd=r)
    (r / "README.md").write_text("hello")
    _git("add", "README.md", cwd=r)
    _git("commit", "-m", "init", cwd=r)
    return Project(
        id="p1",
        name="demo",
        repo_path=str(r),
        default_branch="main",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


@pytest.fixture
def manager() -> WorktreeManager:
    return WorktreeManager(GitService())


@pytest.mark.asyncio
async def test_prepare_issue_worktree_creates_branch_and_path(project: Project, manager: WorktreeManager):
    issue = CodexIssue(id="issue-deadbeef", session_id="s1", project_id=project.id, title="Add foo feature")
    branch, path, base = await manager.prepare_issue_worktree(project, issue)
    assert branch.startswith(f"issue/{issue.id[:8]}-")
    assert "add-foo" in branch
    assert Path(path).exists()
    assert base == "main"


@pytest.mark.asyncio
async def test_prepare_issue_worktree_is_idempotent(project: Project, manager: WorktreeManager):
    issue = CodexIssue(id="issue-aaaa1111", session_id="s1", project_id=project.id, title="t")
    b1, p1, _ = await manager.prepare_issue_worktree(project, issue)
    issue.git_branch = b1
    issue.git_worktree_path = p1
    b2, p2, _ = await manager.prepare_issue_worktree(project, issue)
    assert (b1, p1) == (b2, p2)


@pytest.mark.asyncio
async def test_merge_issue_squashes_changes_back_to_base(project: Project, manager: WorktreeManager):
    issue = CodexIssue(id="issue-bbbb2222", session_id="s1", project_id=project.id, title="feat")
    _, path, _ = await manager.prepare_issue_worktree(project, issue)
    issue.git_branch = f"issue/{issue.id[:8]}-feat"
    issue.git_worktree_path = path
    issue.git_base_branch = "main"
    (Path(path) / "newfile.txt").write_text("data")
    _git("add", "newfile.txt", cwd=Path(path))
    _git("-c", "user.email=t@e", "-c", "user.name=T", "commit", "-m", "work", cwd=Path(path))
    result = await manager.merge_issue(project, issue, message="merge feat")
    log = subprocess.run(
        ["git", "log", "--oneline", "main"], cwd=project.repo_path, capture_output=True, text=True, check=True
    ).stdout
    assert "merge feat" in log
    assert issue.git_merge_status == "merged"
    assert issue.git_last_commit_sha == result["sha"]


@pytest.mark.asyncio
async def test_cleanup_issue_worktree_removes_directory(project: Project, manager: WorktreeManager):
    issue = CodexIssue(id="issue-cccc3333", session_id="s1", project_id=project.id, title="x")
    _, path, _ = await manager.prepare_issue_worktree(project, issue)
    issue.git_worktree_path = path
    await manager.cleanup_issue_worktree(project, issue)
    assert not Path(path).exists()


@pytest.mark.asyncio
async def test_prepare_chat_task_worktree(project: Project, manager: WorktreeManager):
    task = CodexTask(id="task-dddd4444", session_id="s1", project_id=project.id, title="quick fix", prompt="...")
    branch, path, base = await manager.prepare_chat_task_worktree(project, task)
    assert branch.startswith("chat/task-ddd")
    assert Path(path).exists()
    assert base == "main"
