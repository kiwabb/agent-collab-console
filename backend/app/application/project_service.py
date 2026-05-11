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
        if dest.exists():
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
    ) -> Project:
        project = await self.get(project_id)
        if name is not None:
            project.name = name
        if default_branch is not None:
            project.default_branch = default_branch
        if setup_script is not None:
            project.setup_script = setup_script
        project.updated_at = datetime.now()
        await self.store.save_project(project)
        return project

    async def delete(self, project_id: str) -> None:
        await self.store.delete_project(project_id)

    async def list_branches(self, project_id: str):
        project = await self.get(project_id)
        return await self.git.list_branches(project.repo_path)


def _slug_from_url(url: str) -> str:
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    if tail.endswith(".git"):
        tail = tail[:-4]
    return tail or "project"
