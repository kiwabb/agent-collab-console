"""Issue-scoped git worktree lifecycle.

All tasks under one issue share the issue's worktree (PM, architect, engineer,
qa run sequentially and need to see each other's artifacts). Standalone chat
tasks (no issue_id) also get a worktree, scoped to the task itself.
"""
from __future__ import annotations

import asyncio
import re
import shutil
from datetime import datetime
from pathlib import Path

from app.application.git_service import GitError, GitService
from app.domain.models import CodexIssue, CodexTask, Project


class WorktreeError(RuntimeError):
    pass


_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def _slugify(text: str, max_len: int = 24) -> str:
    cleaned = _SAFE_CHARS.sub("-", (text or "").strip().lower()).strip("-")
    if not cleaned:
        cleaned = "item"
    return cleaned[:max_len].rstrip("-") or "item"


def _issue_branch_name(issue: CodexIssue) -> str:
    return f"issue/{issue.id[:8]}-{_slugify(issue.title)}"


def _chat_branch_name(task: CodexTask) -> str:
    return f"chat/{task.id[:8]}-{_slugify(task.title)}"


def _worktree_path(project: Project, kind: str, item_id: str) -> Path:
    """`{repo}/../{name}-worktrees/{kind}-{id}/`."""
    repo = Path(project.repo_path)
    parent = repo.parent / f"{project.name}-worktrees"
    return parent / f"{kind}-{item_id}"


class WorktreeManager:
    def __init__(self, git: GitService):
        self.git = git

    # ---- Issue-level ----

    async def prepare_issue_worktree(
        self,
        project: Project,
        issue: CodexIssue,
        base_branch: str | None = None,
    ) -> tuple[str, str, str]:
        """Create a worktree for an issue if it doesn't already have one.

        `base_branch` overrides the fork point (defaults to project default).
        Returns (branch, worktree_path, base_branch). Safe to call repeatedly.
        """
        if issue.git_worktree_path and issue.git_branch:
            return issue.git_branch, issue.git_worktree_path, issue.git_base_branch or project.default_branch
        branch = _issue_branch_name(issue)
        base = base_branch or project.default_branch
        worktree = _worktree_path(project, "issue", issue.id)
        if worktree.exists() and await self.git.is_git_repo(worktree):
            return branch, str(worktree), base
        if worktree.exists():
            raise WorktreeError(f"worktree path exists but is not a git repo: {worktree}")
        await self.git.create_worktree(
            repo_path=project.repo_path,
            branch=branch,
            worktree_path=worktree,
            base_branch=base,
        )
        if project.setup_script:
            await self._run_setup(project.setup_script, worktree)
        return branch, str(worktree), base

    async def cleanup_issue_worktree(self, project: Project, issue: CodexIssue) -> None:
        if not issue.git_worktree_path:
            return
        await self._cleanup_path(project.repo_path, issue.git_worktree_path)

    async def merge_issue(
        self,
        project: Project,
        issue: CodexIssue,
        message: str | None = None,
    ) -> dict:
        if not issue.git_branch:
            raise WorktreeError("issue has no git branch to merge")
        base = issue.git_base_branch or project.default_branch
        commit_message = message or f"Squash merge issue {issue.id[:8]}: {issue.title}"
        sha = await self.git.squash_merge(
            repo_path=project.repo_path,
            source_branch=issue.git_branch,
            base_branch=base,
            message=commit_message,
        )
        issue.git_merge_status = "merged"
        issue.git_last_commit_sha = sha
        issue.updated_at = datetime.now()
        return {"sha": sha, "base_branch": base, "message": commit_message}

    async def issue_diff(self, project: Project, issue: CodexIssue) -> str:
        if not issue.git_worktree_path:
            return ""
        base = issue.git_base_branch or project.default_branch
        return await self.git.worktree_diff(issue.git_worktree_path, base)

    # ---- Chat-task-level (standalone, no issue) ----

    async def prepare_chat_task_worktree(
        self,
        project: Project,
        task: CodexTask,
    ) -> tuple[str, str, str]:
        if task.git_worktree_path and task.git_branch:
            return task.git_branch, task.git_worktree_path, task.git_base_branch or project.default_branch
        branch = _chat_branch_name(task)
        base = project.default_branch
        worktree = _worktree_path(project, "chat", task.id)
        if worktree.exists() and await self.git.is_git_repo(worktree):
            return branch, str(worktree), base
        if worktree.exists():
            raise WorktreeError(f"worktree path exists but is not a git repo: {worktree}")
        await self.git.create_worktree(
            repo_path=project.repo_path,
            branch=branch,
            worktree_path=worktree,
            base_branch=base,
        )
        if project.setup_script:
            await self._run_setup(project.setup_script, worktree)
        return branch, str(worktree), base

    async def cleanup_chat_task_worktree(self, project: Project, task: CodexTask) -> None:
        if not task.git_worktree_path:
            return
        await self._cleanup_path(project.repo_path, task.git_worktree_path)

    async def prune(self, project: Project) -> None:
        """Run `git worktree prune` on the primary repo to drop stale metadata."""
        await self.git.prune_worktrees(project.repo_path)

    # ---- Shared helpers ----

    async def _cleanup_path(self, repo_path: str, worktree_path: str) -> None:
        try:
            await self.git.remove_worktree(repo_path, worktree_path)
        except GitError:
            pass
        path = Path(worktree_path)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    async def _run_setup(self, script: str, cwd: Path) -> None:
        proc = await asyncio.create_subprocess_shell(
            script,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600.0)
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise WorktreeError("setup_script timed out after 600s") from exc
        if proc.returncode != 0:
            raise WorktreeError(
                f"setup_script failed (rc={proc.returncode}): "
                f"{stderr.decode('utf-8', errors='replace').strip() or stdout.decode('utf-8', errors='replace').strip()}"
            )
