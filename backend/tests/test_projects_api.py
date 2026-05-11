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
    ws = client.post(
        "/api/codex/workspaces", json={"title": "W", "project_id": project["id"]}
    ).json()
    # Spawn an issue so a real worktree dir exists.
    issue = client.post(
        "/api/codex/issues", json={"session_id": ws["id"], "title": "I"}
    ).json()
    worktree_parent = Path(issue["git_worktree_path"]).parent
    assert worktree_parent.exists()
    resp = client.delete(f"/api/projects/{project['id']}?force=true")
    assert resp.status_code == 200
    assert resp.json()["cascaded_sessions"] >= 1
    # Project should no longer be in the listing.
    listing = client.get("/api/projects").json()
    assert all(p["id"] != project["id"] for p in listing)
    # Worktree parent should be cleaned up.
    assert not worktree_parent.exists()


def test_issue_creation_with_base_branch_override_forks_from_feature(client, tmp_path):
    project = _create_project(client, tmp_path, name="basefork")
    # Create a feature branch on the repo so we can fork from it.
    repo = Path(project["repo_path"])
    subprocess.run(["git", "checkout", "-b", "feature/seed"], cwd=repo, check=True, capture_output=True)
    (repo / "feat.txt").write_text("seed")
    subprocess.run(["git", "add", "feat.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e", "-c", "user.name=T", "commit", "-m", "seed"],
        cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)

    ws = client.post(
        "/api/codex/workspaces", json={"title": "W", "project_id": project["id"]}
    ).json()
    resp = client.post(
        "/api/codex/issues",
        json={"session_id": ws["id"], "title": "from feature", "base_branch": "feature/seed"},
    )
    assert resp.status_code == 201, resp.text
    issue = resp.json()
    assert issue["git_base_branch"] == "feature/seed"
    # The seeded file from the feature branch must be present in the worktree.
    assert (Path(issue["git_worktree_path"]) / "feat.txt").exists()


def test_project_stats_counts_workspaces_and_issue_buckets(client, tmp_path):
    project = _create_project(client, tmp_path, name="stats-host")
    ws = client.post(
        "/api/codex/workspaces", json={"title": "W", "project_id": project["id"]}
    ).json()
    # Three issues: leave one open, merge one, abandon one.
    open_issue = client.post(
        "/api/codex/issues", json={"session_id": ws["id"], "title": "open"}
    ).json()
    merged_issue = client.post(
        "/api/codex/issues", json={"session_id": ws["id"], "title": "merged"}
    ).json()
    abandoned_issue = client.post(
        "/api/codex/issues", json={"session_id": ws["id"], "title": "abandoned"}
    ).json()

    # Materialise a real change so the squash merge has something to commit.
    worktree = Path(merged_issue["git_worktree_path"])
    (worktree / "x.txt").write_text("hi")
    subprocess.run(["git", "add", "x.txt"], cwd=worktree, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e", "-c", "user.name=T", "commit", "-m", "x"],
        cwd=worktree, check=True, capture_output=True,
    )
    client.post(f"/api/codex/issues/{merged_issue['id']}/merge", json={"message": None})
    client.post(f"/api/codex/issues/{abandoned_issue['id']}/abandon")

    resp = client.get(f"/api/projects/{project['id']}/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "workspaces": 1,
        "issues_total": 3,
        "issues_open": 1,
        "issues_merged": 1,
        "issues_abandoned": 1,
    }
    # Sanity: open_issue still listed as open.
    full = client.get(f"/api/codex/issues/{open_issue['id']}").json()
    assert full["git_merge_status"] == "open"


def test_merge_refuses_dirty_worktree(client, tmp_path):
    project = _create_project(client, tmp_path, name="dirty-merge")
    ws = client.post(
        "/api/codex/workspaces", json={"title": "W", "project_id": project["id"]}
    ).json()
    issue = client.post(
        "/api/codex/issues", json={"session_id": ws["id"], "title": "dirty"}
    ).json()
    # Drop an uncommitted file in the worktree.
    (Path(issue["git_worktree_path"]) / "tmp.txt").write_text("staging")
    resp = client.post(f"/api/codex/issues/{issue['id']}/merge", json={"message": None})
    assert resp.status_code == 400
    assert "uncommitted" in resp.json()["detail"].lower()


def test_abandon_issue_clears_worktree_and_marks_status(client, tmp_path):
    project = _create_project(client, tmp_path, name="abandon-host")
    ws = client.post(
        "/api/codex/workspaces", json={"title": "W", "project_id": project["id"]}
    ).json()
    issue = client.post(
        "/api/codex/issues", json={"session_id": ws["id"], "title": "throwaway"}
    ).json()
    worktree = Path(issue["git_worktree_path"])
    assert worktree.exists()
    resp = client.post(f"/api/codex/issues/{issue['id']}/abandon")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["git_merge_status"] == "abandoned"
    assert body["git_worktree_path"] is None
    assert not worktree.exists()
    # Issue record still exists.
    listed = client.get(f"/api/codex/issues/{issue['id']}").json()
    assert listed["git_merge_status"] == "abandoned"


def test_abandon_refuses_when_already_merged(client, tmp_path):
    project = _create_project(client, tmp_path, name="abandon-block")
    ws = client.post(
        "/api/codex/workspaces", json={"title": "W", "project_id": project["id"]}
    ).json()
    issue = client.post(
        "/api/codex/issues", json={"session_id": ws["id"], "title": "block"}
    ).json()
    # Materialise a real change so the squash merge has something to commit.
    worktree = Path(issue["git_worktree_path"])
    (worktree / "x.txt").write_text("hi")
    subprocess.run(["git", "add", "x.txt"], cwd=worktree, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e", "-c", "user.name=T", "commit", "-m", "x"],
        cwd=worktree, check=True, capture_output=True,
    )
    client.post(f"/api/codex/issues/{issue['id']}/merge", json={"message": None})
    resp = client.post(f"/api/codex/issues/{issue['id']}/abandon")
    assert resp.status_code == 409


def test_repair_resets_issue_state_when_worktree_dir_is_missing(client, tmp_path):
    project = _create_project(client, tmp_path, name="repair-host")
    ws = client.post(
        "/api/codex/workspaces", json={"title": "W", "project_id": project["id"]}
    ).json()
    issue = client.post(
        "/api/codex/issues", json={"session_id": ws["id"], "title": "ghost"}
    ).json()
    # Simulate disk drift: nuke the worktree directory behind git's back.
    shutil.rmtree(issue["git_worktree_path"])
    resp = client.post(f"/api/projects/{project['id']}/repair")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["issues_reset"] == 1
    refreshed = client.get(f"/api/codex/issues/{issue['id']}").json()
    assert refreshed["git_worktree_path"] is None
    assert refreshed["git_branch"] is None


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
