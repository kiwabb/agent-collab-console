"""Project lifecycle: create from local path or clone, list/get/update/delete."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.application.git_service import GitError, GitService
from app.domain.models import Project


class ProjectError(RuntimeError):
    pass


class ProjectService:
    def __init__(self, store: AsyncSQLiteStore, git: GitService):
        self.store = store
        self.git = git

    async def create_from_local(self, name: str, repo_path: str) -> Project:
        path = Path(repo_path).expanduser()
        if not path.is_absolute():
            path = path.resolve()
        if not path.exists():
            raise ProjectError(f"path does not exist: {path}")
        if not path.is_dir():
            raise ProjectError(f"path is not a directory: {path}")
        if not await self.git.is_git_repo(path):
            raise ProjectError(f"not a git repository: {path}")
        existing = await self.store.load_project_by_repo_path(str(path))
        if existing is not None:
            raise ProjectError(f"a project already references this repo: {existing.id}")
        default_branch = await self.git.default_branch(path)
        now = datetime.now()
        project = Project(
            id=str(uuid4()),
            name=name.strip() or path.name,
            repo_path=str(path),
            default_branch=default_branch,
            origin_url=None,
            setup_script=None,
            created_at=now,
            updated_at=now,
        )
        await self.store.save_project(project)
        return project

    async def create_from_clone(self, name: str, origin_url: str, dest_parent: str) -> Project:
        parent = Path(dest_parent).expanduser().resolve()
        parent.mkdir(parents=True, exist_ok=True)
        slug = (name.strip() or _slug_from_url(origin_url)).replace(" ", "-")
        dest = parent / slug
        if dest.exists():  # noqa: SIM102
            if any(dest.iterdir()):
                raise ProjectError(f"destination already exists and is not empty: {dest}")
        try:
            await self.git.clone(origin_url, dest)
        except GitError as exc:
            # Clean partial clone so the user can retry.
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            raise ProjectError(f"clone failed: {exc}") from exc
        default_branch = await self.git.default_branch(dest)
        now = datetime.now()
        project = Project(
            id=str(uuid4()),
            name=name.strip() or slug,
            repo_path=str(dest),
            default_branch=default_branch,
            origin_url=origin_url,
            setup_script=None,
            created_at=now,
            updated_at=now,
        )
        await self.store.save_project(project)
        return project

    async def list(self) -> list[Project]:
        return await self.store.list_projects()

    async def get(self, project_id: str) -> Project:
        project = await self.store.load_project(project_id)
        if project is None:
            raise ProjectError(f"project not found: {project_id}")
        return project

    async def update(
        self,
        project_id: str,
        *,
        name: str | None = None,
        default_branch: str | None = None,
        setup_script: str | None = None,
        run_command: str | None = None,
    ) -> Project:
        project = await self.get(project_id)
        if name is not None:
            project.name = name
        if default_branch is not None:
            project.default_branch = default_branch
        if setup_script is not None:
            project.setup_script = setup_script
        if run_command is not None:
            project.run_command = run_command
        project.updated_at = datetime.now()
        await self.store.save_project(project)
        return project

    async def delete(self, project_id: str) -> None:
        await self.store.delete_project(project_id)

    async def list_branches(self, project_id: str):
        project = await self.get(project_id)
        return await self.git.list_branches(project.repo_path)

    async def remote_status(self, project_id: str, *, do_fetch: bool = True) -> dict:
        """How the project's default branch relates to its remote.

        Thin wrapper over GitService.remote_status that resolves the project's
        repo_path/default_branch. Never raises for common degraded states (no
        origin / offline / not a git repo) — those surface in the `error` field.
        """
        project = await self.get(project_id)
        return await self.git.remote_status(
            project.repo_path,
            branch=project.default_branch,
            do_fetch=do_fetch,
        )

    async def fast_forward_pull(self, project_id: str) -> dict:
        """Fast-forward the project's default branch to its remote.

        Re-checks the safety preconditions server-side (never trusts a prior
        status the client may have cached) and refuses unless the pull is a
        clean fast-forward. Returns either:
          {"success": True, "new_sha", "behind_before", "branch"}
        or, when it cannot fast-forward:
          {"success": False, "reason", "branch"}  with reason in
          no_origin / fetch_failed / no_remote_branch / not_on_default /
          dirty / diverged / already_up_to_date.
        The repository is never modified in the failure cases.
        """
        project = await self.get(project_id)
        status = await self.git.remote_status(
            project.repo_path,
            branch=project.default_branch,
            do_fetch=True,
        )
        branch = status["branch"]
        reason: str | None = None
        if not status["has_origin"]:
            reason = "no_origin"
        elif status["error"] in {"fetch_failed", "no_remote_branch"}:
            reason = status["error"]
        elif status["current_branch"] != branch:
            reason = "not_on_default"
        elif status["dirty"]:
            reason = "dirty"
        elif status["ahead"] > 0:
            reason = "diverged"
        elif status["behind"] == 0:
            reason = "already_up_to_date"
        if reason is not None:
            return {"success": False, "reason": reason, "branch": branch}
        behind_before = status["behind"]
        new_sha = await self.git.fast_forward(project.repo_path, branch)
        return {
            "success": True,
            "new_sha": new_sha,
            "behind_before": behind_before,
            "branch": branch,
        }


def _slug_from_url(url: str) -> str:
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    if tail.endswith(".git"):
        tail = tail[:-4]
    return tail or "project"
