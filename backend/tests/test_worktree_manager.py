from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from app.application.git_service import GitService
from app.application.worktree_manager import WorktreeError, WorktreeManager
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


# ---- Per-agent (swarm) worktree ----


async def _issue_with_worktree(project: Project, manager: WorktreeManager, issue_id: str) -> CodexIssue:
    issue = CodexIssue(id=issue_id, session_id="s1", project_id=project.id, title="swarm work")
    branch, path, base = await manager.prepare_issue_worktree(project, issue)
    issue.git_branch = branch
    issue.git_worktree_path = path
    issue.git_base_branch = base
    return issue


@pytest.mark.asyncio
async def test_prepare_agent_worktree_forks_from_issue_branch(project: Project, manager: WorktreeManager):
    issue = await _issue_with_worktree(project, manager, "issue-swrm0001")
    branch, path, base = await manager.prepare_agent_worktree(project, issue, "engineerA")
    assert branch == f"swarm/{issue.id[:8]}-engineera"
    assert Path(path).exists()
    # base is the issue integration branch, not the project default
    assert base == issue.git_branch
    assert base != project.default_branch


@pytest.mark.asyncio
async def test_prepare_agent_worktree_requires_issue_branch(project: Project, manager: WorktreeManager):
    issue = CodexIssue(id="issue-swrm0002", session_id="s1", project_id=project.id, title="no branch yet")
    with pytest.raises(WorktreeError):
        await manager.prepare_agent_worktree(project, issue, "engineerA")


@pytest.mark.asyncio
async def test_agent_worktrees_are_isolated(project: Project, manager: WorktreeManager):
    issue = await _issue_with_worktree(project, manager, "issue-swrm0003")
    _, path_a, _ = await manager.prepare_agent_worktree(project, issue, "engineerA")
    _, path_b, _ = await manager.prepare_agent_worktree(project, issue, "engineerB")
    assert path_a != path_b
    # Writes in one agent worktree are not visible in the other.
    (Path(path_a) / "a_only.txt").write_text("from A")
    (Path(path_b) / "b_only.txt").write_text("from B")
    assert not (Path(path_b) / "a_only.txt").exists()
    assert not (Path(path_a) / "b_only.txt").exists()


@pytest.mark.asyncio
async def test_prepare_agent_worktree_is_idempotent(project: Project, manager: WorktreeManager):
    issue = await _issue_with_worktree(project, manager, "issue-swrm0004")
    b1, p1, _ = await manager.prepare_agent_worktree(project, issue, "engineerA")
    b2, p2, _ = await manager.prepare_agent_worktree(project, issue, "engineerA")
    assert (b1, p1) == (b2, p2)


@pytest.mark.asyncio
async def test_cleanup_agent_worktree_removes_and_is_idempotent(project: Project, manager: WorktreeManager):
    issue = await _issue_with_worktree(project, manager, "issue-swrm0005")
    _, path, _ = await manager.prepare_agent_worktree(project, issue, "engineerA")
    assert Path(path).exists()
    await manager.cleanup_agent_worktree(project, issue, "engineerA")
    assert not Path(path).exists()
    # Calling again on a now-missing worktree must not raise.
    await manager.cleanup_agent_worktree(project, issue, "engineerA")
