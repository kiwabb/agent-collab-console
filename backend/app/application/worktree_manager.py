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
from app.application.worktree_claude_hooks import inject_worktree_claude_hooks
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


def _agent_branch_name(issue: CodexIssue, agent_key: str) -> str:
    return f"swarm/{issue.id[:8]}-{_slugify(agent_key)}"


def _worktree_path(project: Project, kind: str, item_id: str) -> Path:
    """`{repo}/../{name}-worktrees/{kind}-{id}/`."""
    repo = Path(project.repo_path)
    parent = repo.parent / f"{project.name}-worktrees"
    return parent / f"{kind}-{item_id}"


class WorktreeManager:
    def __init__(self, git: GitService):
        self.git = git
        # Per-issue + per-chat-task locks. Two concurrent creates of the same
        # issue worktree would race `git worktree add` and clobber each other;
        # the lock serialises all mutating ops keyed by the entity id.
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def _lock_for(self, key: str) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock

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
        lock = await self._lock_for(f"issue:{issue.id}")
        async with lock:
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
            await inject_worktree_claude_hooks(worktree)
            if project.setup_script:
                await self._run_setup(project.setup_script, worktree)
            return branch, str(worktree), base

    async def cleanup_issue_worktree(self, project: Project, issue: CodexIssue) -> None:
        if not issue.git_worktree_path:
            return
        lock = await self._lock_for(f"issue:{issue.id}")
        async with lock:
            await self._cleanup_path(project.repo_path, issue.git_worktree_path)

    async def merge_issue(
        self,
        project: Project,
        issue: CodexIssue,
        message: str | None = None,
    ) -> dict:
        if not issue.git_branch:
            raise WorktreeError("issue has no git branch to merge")
        lock = await self._lock_for(f"issue:{issue.id}")
        async with lock:
            base = issue.git_base_branch or project.default_branch
            # Auto-commit any uncommitted changes in the worktree so they are
            # included in the squash merge. Engineer intentionally doesn't
            # auto-commit during task execution, so this is the expected path.
            if issue.git_worktree_path:
                status = await self.git.status_porcelain(issue.git_worktree_path)
                if status.strip():
                    await self.git.commit_all(
                        issue.git_worktree_path,
                        f"chore: commit engineer changes before merge ({issue.id[:8]})",
                    )
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

    # ---- Per-agent (swarm / parallel) ----

    async def commit_issue_worktree(
        self,
        issue: CodexIssue,
        message: str | None = None,
    ) -> str | None:
        """Commit any uncommitted changes in the shared issue worktree.

        Per-agent worktrees fork from the issue *branch*, so they only see what
        has been committed to that branch at fork time. Upstream agents (PM /
        architect) intentionally don't auto-commit during execution, so their
        artifacts can sit uncommitted in the shared issue worktree. Before a
        fan-out we must flush those to the issue branch, otherwise the isolated
        agents start from a stale tree and can't see upstream artifacts (PR1
        check finding). Mirrors the pre-merge commit in `merge_issue`.

        Returns the new HEAD sha, or None if there was nothing to commit.
        """
        if not issue.git_worktree_path or not issue.git_branch:
            return None
        lock = await self._lock_for(f"issue:{issue.id}")
        async with lock:
            status = await self.git.status_porcelain(issue.git_worktree_path)
            if not status.strip():
                return None
            commit_message = (
                message
                or f"chore: flush upstream artifacts before swarm fan-out ({issue.id[:8]})"
            )
            return await self.git.commit_all(issue.git_worktree_path, commit_message)

    async def prepare_agent_worktree(
        self,
        project: Project,
        issue: CodexIssue,
        agent_key: str,
    ) -> tuple[str, str, str]:
        """Create an isolated per-agent worktree forked from the issue branch.

        For parallel swarm dispatch: each concurrent agent gets its own worktree
        + branch (`swarm/<issue>-<agent_key>`) so file edits never clobber each
        other. The fork point is the issue integration branch (not the project
        default), so each agent starts from the issue's accumulated state and its
        changes can later be squash-merged back into the issue branch (PR3).

        Returns (branch, worktree_path, base_branch). Safe to call repeatedly for
        the same agent_key (idempotent on an existing worktree).
        """
        if not issue.git_branch:
            raise WorktreeError(
                "issue has no git branch; prepare_issue_worktree must run first"
            )
        lock = await self._lock_for(f"swarm:{issue.id}:{agent_key}")
        async with lock:
            branch = _agent_branch_name(issue, agent_key)
            base = issue.git_branch
            worktree = _worktree_path(project, "swarm", f"{issue.id}-{agent_key}")
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
            await inject_worktree_claude_hooks(worktree)
            if project.setup_script:
                await self._run_setup(project.setup_script, worktree)
            return branch, str(worktree), base

    async def cleanup_agent_worktree(
        self,
        project: Project,
        issue: CodexIssue,
        agent_key: str,
    ) -> None:
        """Remove a per-agent swarm worktree. Idempotent: a missing worktree is a
        no-op, so this is safe to call on failed/aborted batches for cleanup."""
        lock = await self._lock_for(f"swarm:{issue.id}:{agent_key}")
        async with lock:
            worktree = _worktree_path(project, "swarm", f"{issue.id}-{agent_key}")
            await self._cleanup_path(project.repo_path, str(worktree))

    async def _collect_conflict(
        self,
        project: Project,
        issue: CodexIssue,
        agent_branch: str,
        agent_worktree_path: str | None,
    ) -> dict:
        """Probe a failed squash-merge to enumerate the conflicting files + diff.

        `git_service.squash_merge` does its merge in a throwaway detached
        worktree and `reset --hard`s on conflict, so by the time it raises there
        is no conflict state left to inspect. We re-run the merge in a temporary
        detached worktree of the issue branch with `--no-commit --no-ff`, list
        the unmerged paths, then abort — this gives the reconcile turn the
        structured conflict info without leaving the repo dirty.
        """
        repo_p = Path(project.repo_path)
        probe = repo_p.parent / f".jm-conflict-{agent_branch[:24].replace('/', '-')}"
        files: list[str] = []
        try:
            await self.git.prune_worktrees(project.repo_path)
            if probe.exists():
                await self._cleanup_path(project.repo_path, str(probe))
            # Detached worktree at the issue branch tip, then merge the agent
            # branch into it without committing so conflicts surface as unmerged
            # paths we can read.
            await self.git._run(
                ["worktree", "add", "--detach", str(probe), issue.git_branch],
                cwd=repo_p,
                check=False,
            )
            await self.git._run(
                ["merge", "--no-commit", "--no-ff", "--", agent_branch],
                cwd=probe,
                check=False,
            )
            files = await self.git.conflicted_files(probe)
            await self.git._run(["merge", "--abort"], cwd=probe, check=False)
        except GitError:
            pass
        finally:
            await self._cleanup_path(project.repo_path, str(probe))
        diff = ""
        if agent_worktree_path:
            try:
                diff = await self.git.worktree_diff(agent_worktree_path, issue.git_branch)
            except GitError:
                diff = ""
        return {"files": files, "diff": diff}

    async def merge_agent_worktrees(
        self,
        project: Project,
        issue: CodexIssue,
        agents: list[dict],
    ) -> dict:
        """Sequentially squash-merge successful per-agent branches back into the
        issue integration branch.

        `agents` is a list of `{agent_key, branch, worktree_path, role?}` for the
        agents that produced mergeable output (the succeeded items from
        `dispatch_batch`). Merges run strictly serially inside the issue lock so
        each merge sees the previous one's commits (no octopus, no parallel
        merge).

        Conflict semantics: `git_service.squash_merge` does a three-way merge and
        on conflict resets + raises `GitError` (no half-merged state). On the
        FIRST conflict we STOP merging the rest — continuing would stack more
        agents onto an already-contentious issue branch and muddy the reconcile.
        Already-merged agents are NOT rolled back (their worktrees are cleaned).
        The conflicting agent's worktree is KEPT for the reconcile turn, and we
        return structured conflict info (agent_key, role, files, diff) so the
        Conductor LLM can decide (re-dispatch a resolver / escalate to the user).

        Returns:
            {
              "merged": [{agent_key, role, branch, sha}],
              "conflict": {agent_key, role, branch, worktree_path, files, diff} | None,
              "skipped": [{agent_key, role, branch}],   # not attempted after a conflict
            }
        """
        if not issue.git_branch:
            raise WorktreeError("issue has no git branch to merge agent worktrees into")

        merged: list[dict] = []
        conflict: dict | None = None
        skipped: list[dict] = []

        lock = await self._lock_for(f"issue:{issue.id}")
        async with lock:
            for spec in agents:
                agent_key = spec.get("agent_key")
                branch = spec.get("branch")
                worktree_path = spec.get("worktree_path")
                role = spec.get("role")
                if not agent_key or not branch:
                    continue

                # Once a conflict has occurred, do not attempt further merges.
                if conflict is not None:
                    skipped.append({"agent_key": agent_key, "role": role, "branch": branch})
                    continue

                # Flush the agent's uncommitted edits onto its branch so the
                # squash merge picks them up (engineer doesn't auto-commit).
                if worktree_path:
                    try:
                        status = await self.git.status_porcelain(worktree_path)
                        if status.strip():
                            await self.git.commit_all(
                                worktree_path,
                                f"chore: commit {agent_key} changes before merge ({issue.id[:8]})",
                            )
                    except GitError:
                        pass

                # Divergence detection: the issue branch may have advanced from
                # an earlier merge in this loop. We don't rebase (squash_merge
                # does a three-way merge that handles a moved base; non-overlapping
                # changes auto-merge, overlapping ones surface as a conflict).
                behind = 0
                if worktree_path:
                    try:
                        behind = await self.git.commits_behind(worktree_path, issue.git_branch)
                    except GitError:
                        behind = 0

                try:
                    # Use the swarm-safe primitive: it squash-merges into the
                    # issue branch via a detached temp worktree and advances ONLY
                    # the issue branch ref (plus syncs the issue worktree). It
                    # never fast-forwards the primary repo, so the project default
                    # branch can't be polluted with unreviewed agent changes.
                    # (Plain `squash_merge` would ff the default branch because it
                    # is an ancestor of the squash commit — see git_service docs.)
                    sha = await self.git.squash_merge_into_branch(
                        repo_path=project.repo_path,
                        source_branch=branch,
                        target_branch=issue.git_branch,
                        message=f"merge swarm agent {agent_key}: {issue.title}",
                        target_worktree_path=issue.git_worktree_path,
                    )
                    merged.append({
                        "agent_key": agent_key,
                        "role": role,
                        "branch": branch,
                        "sha": sha,
                        "behind_at_merge": behind,
                    })
                    # Merged successfully → its worktree+branch are no longer needed.
                    await self.cleanup_agent_worktree(project, issue, agent_key)
                except GitError:
                    # Conflict (or other merge failure). Keep this agent's worktree
                    # so the reconcile turn can inspect it; collect conflict detail.
                    detail = await self._collect_conflict(
                        project, issue, branch, worktree_path
                    )
                    conflict = {
                        "agent_key": agent_key,
                        "role": role,
                        "branch": branch,
                        "worktree_path": worktree_path,
                        "files": detail["files"],
                        "diff": detail["diff"],
                    }

        if merged:
            issue.git_last_commit_sha = merged[-1]["sha"]
            issue.updated_at = datetime.now()

        return {"merged": merged, "conflict": conflict, "skipped": skipped}

    # ---- Chat-task-level (standalone, no issue) ----

    async def prepare_chat_task_worktree(
        self,
        project: Project,
        task: CodexTask,
    ) -> tuple[str, str, str]:
        lock = await self._lock_for(f"chat:{task.id}")
        async with lock:
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
            await inject_worktree_claude_hooks(worktree)
            if project.setup_script:
                await self._run_setup(project.setup_script, worktree)
            return branch, str(worktree), base

    async def cleanup_chat_task_worktree(self, project: Project, task: CodexTask) -> None:
        if not task.git_worktree_path:
            return
        lock = await self._lock_for(f"chat:{task.id}")
        async with lock:
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
        import os
        # Inherit a curated slice of the parent process env so commands like
        # `npm install` (needs PATH, HOME, possibly NPM_TOKEN, etc.) can find
        # their tools. The intentional drop list keeps Python/codex internals
        # from leaking into the user's setup shell.
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in {"CODEX_LAUNCH_ENABLED", "CODEX_WORKSPACE_ROOT", "SQLITE_DB_PATH"}
        }
        proc = await asyncio.create_subprocess_shell(
            script,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600.0)
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise WorktreeError("setup_script timed out after 600s") from exc
        if proc.returncode != 0:
            # Show the tail of stderr (then stdout) so the toast has the actual
            # error rather than the first lines of an autoreloader banner.
            combined = stderr.decode("utf-8", errors="replace").strip() or stdout.decode("utf-8", errors="replace").strip()
            tail = "\n".join(combined.splitlines()[-30:])
            raise WorktreeError(
                f"setup_script failed (rc={proc.returncode}):\n{tail}"
            )
