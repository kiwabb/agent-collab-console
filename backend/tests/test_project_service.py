from __future__ import annotations  # noqa: I001

from collections.abc import AsyncGenerator
import shutil
import subprocess
from pathlib import Path

import pytest

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.application.git_service import GitService
from app.application.project_service import ProjectError, ProjectService


pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary not available")


@pytest.fixture
async def store(tmp_path: Path) -> AsyncGenerator[AsyncSQLiteStore, None]:
    s = AsyncSQLiteStore(tmp_path / "test.db")
    await s._init_db()
    try:
        yield s
    finally:
        await s.close()


@pytest.fixture
def svc(store: AsyncSQLiteStore) -> ProjectService:
    return ProjectService(store=store, git=GitService())


def _make_git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@e"], cwd=path, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("hello")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)
    return path


@pytest.mark.asyncio
async def test_create_from_local_accepts_valid_repo(svc: ProjectService, tmp_path: Path):
    repo = _make_git_repo(tmp_path / "demo")
    project = await svc.create_from_local("demo", str(repo))
    assert project.name == "demo"
    assert project.repo_path == str(repo)
    assert project.default_branch == "main"


@pytest.mark.asyncio
async def test_create_from_local_rejects_non_git_dir(svc: ProjectService, tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(ProjectError):
        await svc.create_from_local("plain", str(plain))


@pytest.mark.asyncio
async def test_create_from_local_rejects_missing_path(svc: ProjectService, tmp_path: Path):
    with pytest.raises(ProjectError):
        await svc.create_from_local("ghost", str(tmp_path / "nope"))


@pytest.mark.asyncio
async def test_create_from_local_rejects_duplicate(svc: ProjectService, tmp_path: Path):
    repo = _make_git_repo(tmp_path / "dup")
    await svc.create_from_local("dup", str(repo))
    with pytest.raises(ProjectError):
        await svc.create_from_local("dup-again", str(repo))


@pytest.mark.asyncio
async def test_create_from_clone_fails_on_bogus_url(svc: ProjectService, tmp_path: Path):
    with pytest.raises(ProjectError):
        await svc.create_from_clone("bad", "file:///definitely/not/a/repo", str(tmp_path / "out"))
    # Clone target should be cleaned up so the user can retry.
    assert not (tmp_path / "out" / "bad").exists()
