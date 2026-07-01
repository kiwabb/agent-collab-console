"""FastAPI integration tests for Codex global endpoints."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary not available")


def _make_git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@e"], cwd=path, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("hello")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)
    return path


def _create_project(client, tmp_path: Path, name: str = "demo"):
    repo = _make_git_repo(tmp_path / name)
    resp = client.post(
        "/api/projects",
        json={"name": name, "source": "local", "repo_path": str(repo)},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_codex_stats_returns_basic_counts_across_projects(client, tmp_path):
    """Two separate projects each get a workspace; stats must aggregate workspace/session counts."""
    proj_a = _create_project(client, tmp_path, name="stats-proj-a")
    proj_b = _create_project(client, tmp_path, name="stats-proj-b")

    ws_a = client.post(  # noqa: F841
        "/api/codex/workspaces",
        json={"title": "WA", "project_id": proj_a["id"]},
    ).json()
    ws_b = client.post(  # noqa: F841
        "/api/codex/workspaces",
        json={"title": "WB", "project_id": proj_b["id"]},
    ).json()

    resp = client.get("/api/codex/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["workspaces_total"] == 2, f"expected 2 workspaces, got {body}"
    assert body["sessions_total"] == 2
    assert "tasks_total" in body
    assert "executor_codex_available" in body
    assert "executor_claude_available" in body
    assert "last_activity_at" in body


def test_codex_stats_returns_503_when_store_unavailable(client, monkeypatch):
    """When codex_store is None the endpoint must return 503."""
    from app.interfaces import api as api_module

    original = api_module.codex_store

    api_module.codex_store = None
    try:
        resp = client.get("/api/codex/stats")
        assert resp.status_code == 503
        assert "not available" in resp.json()["detail"]
    finally:
        api_module.codex_store = original