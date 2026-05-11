"""FastAPI integration tests for the project + worktree flow."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary not available")


def _make_git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@e"], cwd=path, check=True, capture_output=True)
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


def test_create_project_from_local_succeeds(client, tmp_path):
    project = _create_project(client, tmp_path)
    assert project["repo_path"].endswith("demo")
    assert project["default_branch"] == "main"


def test_create_project_rejects_non_git_dir(client, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    resp = client.post(
        "/api/projects",
        json={"name": "plain", "source": "local", "repo_path": str(plain)},
    )
    assert resp.status_code == 400


def test_list_projects_returns_created_project(client, tmp_path):
    _create_project(client, tmp_path, name="listed")
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()]
    assert "listed" in names


def test_workspace_requires_project_id(client):
    resp = client.post("/api/codex/workspaces", json={"title": "no project"})
    assert resp.status_code == 422  # missing required field


def test_workspace_creation_inherits_repo_path_as_cwd(client, tmp_path):
    project = _create_project(client, tmp_path, name="ws-host")
    resp = client.post(
        "/api/codex/workspaces",
        json={"title": "WS", "project_id": project["id"]},
    )
    assert resp.status_code == 201, resp.text
    workspace = resp.json()
    assert workspace["project_id"] == project["id"]
    assert workspace["cwd"] == project["repo_path"]


def test_issue_creation_builds_worktree(client, tmp_path):
    project = _create_project(client, tmp_path, name="issue-host")
    ws = client.post(
        "/api/codex/workspaces",
        json={"title": "W", "project_id": project["id"]},
    ).json()
    resp = client.post(
        "/api/codex/issues",
        json={"session_id": ws["id"], "title": "Add login flow"},
    )
    assert resp.status_code == 201, resp.text
    issue = resp.json()
    assert issue["git_branch"].startswith("issue/")
    assert issue["git_base_branch"] == "main"
    assert issue["git_worktree_path"]
    assert Path(issue["git_worktree_path"]).exists()


def test_merge_issue_squash_lands_on_base(client, tmp_path):
    project = _create_project(client, tmp_path, name="merge-host")
    ws = client.post(
        "/api/codex/workspaces", json={"title": "W", "project_id": project["id"]}
    ).json()
    issue = client.post(
        "/api/codex/issues",
        json={"session_id": ws["id"], "title": "Add hello"},
    ).json()
    worktree = Path(issue["git_worktree_path"])
    (worktree / "hello.txt").write_text("world")
    subprocess.run(["git", "add", "hello.txt"], cwd=worktree, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e", "-c", "user.name=T", "commit", "-m", "add hello"],
        cwd=worktree,
        check=True,
        capture_output=True,
    )
    merge = client.post(f"/api/codex/issues/{issue['id']}/merge", json={"message": None})
    assert merge.status_code == 200, merge.text
    body = merge.json()
    assert body["base_branch"] == "main"
    # The squash commit is on main now.
    log = subprocess.run(
        ["git", "log", "--oneline", "main"], cwd=project["repo_path"], capture_output=True, text=True, check=True
    ).stdout
    assert "Squash merge issue" in log


def test_delete_project_refuses_without_force_when_session_attached(client, tmp_path):
    project = _create_project(client, tmp_path, name="protected")
    client.post(
        "/api/codex/workspaces", json={"title": "W", "project_id": project["id"]}
    )
    resp = client.delete(f"/api/projects/{project['id']}")
    assert resp.status_code == 409


def test_delete_project_force_cascades_sessions(client, tmp_path):
    project = _create_project(client, tmp_path, name="bulk")
    client.post(
        "/api/codex/workspaces", json={"title": "W", "project_id": project["id"]}
    )
    resp = client.delete(f"/api/projects/{project['id']}?force=true")
    assert resp.status_code == 200
    assert resp.json()["cascaded_sessions"] >= 1
    # Project should no longer be in the listing.
    listing = client.get("/api/projects").json()
    assert all(p["id"] != project["id"] for p in listing)


def test_get_issue_diff_returns_empty_when_no_changes(client, tmp_path):
    project = _create_project(client, tmp_path, name="diff-empty")
    ws = client.post(
        "/api/codex/workspaces", json={"title": "W", "project_id": project["id"]}
    ).json()
    issue = client.post(
        "/api/codex/issues",
        json={"session_id": ws["id"], "title": "Empty"},
    ).json()
    resp = client.get(f"/api/codex/issues/{issue['id']}/diff")
    assert resp.status_code == 200
    body = resp.json()
    assert body["branch"] == issue["git_branch"]
    assert body["base_branch"] == issue["git_base_branch"]
    assert body["diff"] == ""
