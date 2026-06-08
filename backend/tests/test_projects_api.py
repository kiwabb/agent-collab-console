"""FastAPI integration tests for the project + worktree flow."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(shutil.which("git") is None, reason="git binary not available"),
]


def _make_git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@e"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("hello")
    (path / ".gitignore").write_text(".claude\n")
    subprocess.run(["git", "add", "README.md", ".gitignore"], cwd=path, check=True, capture_output=True)
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
        json={"title": "Workspace", "project_id": project["id"]},
    )
    assert resp.status_code == 201, resp.text
    workspace = resp.json()
    assert workspace["project_id"] == project["id"]
    assert workspace["cwd"] == project["repo_path"]


def test_issue_creation_builds_worktree(client, tmp_path):
    project = _create_project(client, tmp_path, name="issue-host")
    ws = client.post(
        "/api/codex/workspaces",
        json={"title": "Workspace", "project_id": project["id"]},
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
        "/api/codex/workspaces", json={"title": "Workspace", "project_id": project["id"]}
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
        "/api/codex/workspaces", json={"title": "Workspace", "project_id": project["id"]}
    )
    resp = client.delete(f"/api/projects/{project['id']}")
    assert resp.status_code == 409


def test_delete_project_force_cascades_sessions(client, tmp_path):
    project = _create_project(client, tmp_path, name="bulk")
    ws = client.post(
        "/api/codex/workspaces", json={"title": "Workspace", "project_id": project["id"]}
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
        "/api/codex/workspaces", json={"title": "Workspace", "project_id": project["id"]}
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
        "/api/codex/workspaces", json={"title": "Workspace", "project_id": project["id"]}
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


def test_merge_refuses_when_base_diverged(client, tmp_path):
    project = _create_project(client, tmp_path, name="diverged-base")
    repo = Path(project["repo_path"])
    ws = client.post(
        "/api/codex/workspaces", json={"title": "Workspace", "project_id": project["id"]}
    ).json()
    issue = client.post(
        "/api/codex/issues", json={"session_id": ws["id"], "title": "behind"}
    ).json()
    # Move main forward _after_ the worktree was branched, so base has a
    # commit the worktree lacks.
    (repo / "main-progress.txt").write_text("ahead")
    subprocess.run(["git", "add", "main-progress.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e", "-c", "user.name=T", "commit", "-m", "main progress"],
        cwd=repo, check=True, capture_output=True,
    )
    # And add a real commit on the worktree side so the squash has something to land.
    wt = Path(issue["git_worktree_path"])
    (wt / "feat.txt").write_text("work")
    subprocess.run(["git", "add", "feat.txt"], cwd=wt, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e", "-c", "user.name=T", "commit", "-m", "feat"],
        cwd=wt, check=True, capture_output=True,
    )

    # Default merge is refused with 409.
    refused = client.post(f"/api/codex/issues/{issue['id']}/merge", json={"message": None})
    assert refused.status_code == 409
    assert "diverged" in refused.json()["detail"].lower() or "ahead" in refused.json()["detail"].lower()

    # Override gets through.
    allowed = client.post(
        f"/api/codex/issues/{issue['id']}/merge",
        json={"message": None, "allow_diverged_base": True},
    )
    assert allowed.status_code == 200


def test_merge_auto_commits_dirty_worktree(client, tmp_path):
    project = _create_project(client, tmp_path, name="dirty-merge")
    ws = client.post(
        "/api/codex/workspaces", json={"title": "Workspace", "project_id": project["id"]}
    ).json()
    issue = client.post(
        "/api/codex/issues", json={"session_id": ws["id"], "title": "dirty"}
    ).json()
    # Drop an uncommitted file in the worktree.
    (Path(issue["git_worktree_path"]) / "tmp.txt").write_text("staging")
    resp = client.post(f"/api/codex/issues/{issue['id']}/merge", json={"message": None})
    assert resp.status_code == 200, resp.text
    refreshed = client.get(f"/api/codex/issues/{issue['id']}").json()
    assert refreshed["git_merge_status"] == "merged"


def test_abandon_issue_marks_status_and_keeps_worktree_for_undo(client, tmp_path):
    project = _create_project(client, tmp_path, name="abandon-host")
    ws = client.post(
        "/api/codex/workspaces", json={"title": "Workspace", "project_id": project["id"]}
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
    assert body["git_worktree_path"] == str(worktree)
    assert worktree.exists()
    # Issue record still exists.
    listed = client.get(f"/api/codex/issues/{issue['id']}").json()
    assert listed["git_merge_status"] == "abandoned"
    finalize = client.post(f"/api/codex/issues/{issue['id']}/abandon/finalize")
    assert finalize.status_code == 200, finalize.text
    assert finalize.json()["git_worktree_path"] is None
    assert not worktree.exists()


def test_abandon_refuses_when_already_merged(client, tmp_path):
    project = _create_project(client, tmp_path, name="abandon-block")
    ws = client.post(
        "/api/codex/workspaces", json={"title": "Workspace", "project_id": project["id"]}
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


def test_repair_resets_issue_state_when_branch_was_deleted_externally(client, tmp_path):
    project = _create_project(client, tmp_path, name="ghost-branch")
    ws = client.post(
        "/api/codex/workspaces", json={"title": "Workspace", "project_id": project["id"]}
    ).json()
    issue = client.post(
        "/api/codex/issues", json={"session_id": ws["id"], "title": "ghost-branch"}
    ).json()
    # Tear down the worktree from the git side AND delete the branch ref by
    # hand — simulates `git worktree remove && git branch -D` outside the app.
    repo = Path(project["repo_path"])
    subprocess.run(
        ["git", "worktree", "remove", "--force", issue["git_worktree_path"]],
        cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(["git", "branch", "-D", issue["git_branch"]], cwd=repo, check=True, capture_output=True)
    resp = client.post(f"/api/projects/{project['id']}/repair")
    assert resp.status_code == 200, resp.text
    assert resp.json()["issues_reset"] == 1
    refreshed = client.get(f"/api/codex/issues/{issue['id']}").json()
    assert refreshed["git_branch"] is None


def test_repair_removes_orphan_worktree_dirs(client, tmp_path):
    project = _create_project(client, tmp_path, name="orphan-gc")
    ws = client.post(
        "/api/codex/workspaces", json={"title": "Workspace", "project_id": project["id"]}
    ).json()
    # Create one live issue (=> one legit worktree).
    live = client.post(
        "/api/codex/issues", json={"session_id": ws["id"], "title": "live"}
    ).json()
    worktree_parent = Path(live["git_worktree_path"]).parent
    # Drop a stray issue-* dir simulating a crashed delete.
    orphan = worktree_parent / "issue-ghost1234"
    orphan.mkdir(parents=True)
    (orphan / "stale.txt").write_text("leftover")

    resp = client.post(f"/api/projects/{project['id']}/repair")
    assert resp.status_code == 200
    body = resp.json()
    assert body["orphan_dirs_removed"] == 1
    assert not orphan.exists()
    # The live worktree must remain.
    assert Path(live["git_worktree_path"]).exists()


def test_repair_resets_issue_state_when_worktree_dir_is_missing(client, tmp_path):
    project = _create_project(client, tmp_path, name="repair-host")
    ws = client.post(
        "/api/codex/workspaces", json={"title": "Workspace", "project_id": project["id"]}
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


def test_audit_log_supports_since_filter(client, tmp_path):
    project = _create_project(client, tmp_path, name="audit-since")
    ws = client.post(
        "/api/codex/workspaces", json={"title": "Workspace", "project_id": project["id"]}
    ).json()
    issue_a = client.post(
        "/api/codex/issues", json={"session_id": ws["id"], "title": "early"}
    ).json()
    # All entries to this point.
    earlier = client.get(f"/api/projects/{project['id']}/audit").json()
    assert len(earlier) >= 1
    cutoff = earlier[0]["created_at"]
    # Trigger one more event AFTER the cutoff.
    client.post(f"/api/codex/issues/{issue_a['id']}/abandon")
    filtered = client.get(
        f"/api/projects/{project['id']}/audit?since={cutoff}"
    ).json()
    events = {row["event"] for row in filtered}
    assert "abandoned" in events
    # The earlier creation entry shouldn't be returned again — strictly newer.
    assert all(row["created_at"] >= cutoff for row in filtered)


def test_audit_log_records_merge_and_abandon(client, tmp_path):
    project = _create_project(client, tmp_path, name="audit-host")
    ws = client.post(
        "/api/codex/workspaces", json={"title": "Workspace", "project_id": project["id"]}
    ).json()
    # Merge one issue
    merged = client.post(
        "/api/codex/issues", json={"session_id": ws["id"], "title": "m"}
    ).json()
    wt = Path(merged["git_worktree_path"])
    (wt / "f.txt").write_text("x")
    subprocess.run(["git", "add", "f.txt"], cwd=wt, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e", "-c", "user.name=T", "commit", "-m", "x"],
        cwd=wt, check=True, capture_output=True,
    )
    client.post(f"/api/codex/issues/{merged['id']}/merge", json={"message": None})
    # Abandon another
    abandoned = client.post(
        "/api/codex/issues", json={"session_id": ws["id"], "title": "a"}
    ).json()
    client.post(f"/api/codex/issues/{abandoned['id']}/abandon")

    audit = client.get(f"/api/projects/{project['id']}/audit").json()
    events = [(row["issue_id"], row["event"]) for row in audit]
    # Most recent first
    assert events[0] == (abandoned["id"], "abandoned")
    assert (merged["id"], "merged") in events


def test_full_create_to_merge_round_trip(client, tmp_path):
    """End-to-end: project → workspace → issue → edit → diff → merge → stats."""
    # 1. Create project
    project = _create_project(client, tmp_path, name="e2e")
    repo = Path(project["repo_path"])

    # 2. Create workspace bound to project
    ws = client.post(
        "/api/codex/workspaces",
        json={"title": "E2E session", "project_id": project["id"]},
    ).json()
    assert ws["project_id"] == project["id"]
    assert ws["cwd"] == project["repo_path"]

    # 3. Create issue (auto-builds worktree)
    issue = client.post(
        "/api/codex/issues",
        json={"session_id": ws["id"], "title": "wire up X"},
    ).json()
    assert issue["git_branch"] and issue["git_worktree_path"]
    worktree = Path(issue["git_worktree_path"])

    # 4. Make a change inside the worktree (simulate the agent doing work)
    (worktree / "feature.txt").write_text("payload\n")
    subprocess.run(["git", "add", "feature.txt"], cwd=worktree, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e", "-c", "user.name=T", "commit", "-m", "feat: x"],
        cwd=worktree, check=True, capture_output=True,
    )

    # 5. Diffstat surfaces the change
    diff = client.get(f"/api/codex/issues/{issue['id']}/diff?stat_only=true").json()
    assert diff["stat"] == {"files": 1, "insertions": 1, "deletions": 0}

    # 6. Squash merge
    merge = client.post(
        f"/api/codex/issues/{issue['id']}/merge", json={"message": "ship it"}
    )
    assert merge.status_code == 200, merge.text
    sha = merge.json()["sha"]

    # 7. Squash commit lands on main with our message
    log = subprocess.run(
        ["git", "log", "--oneline", "main"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout
    assert "ship it" in log

    # 8. Issue reflects merged state with the new sha
    refreshed = client.get(f"/api/codex/issues/{issue['id']}").json()
    assert refreshed["git_merge_status"] == "merged"
    assert refreshed["git_last_commit_sha"] == sha

    # 9. Stats roll up: 1 workspace, 1 merged issue, no open/abandoned
    stats = client.get(f"/api/projects/{project['id']}/stats").json()
    assert stats == {
        "workspaces": 1,
        "issues_total": 1,
        "issues_open": 0,
        "issues_merged": 1,
        "issues_abandoned": 0,
    }


def test_get_issue_diff_returns_empty_when_no_changes(client, tmp_path):
    project = _create_project(client, tmp_path, name="diff-empty")
    ws = client.post(
        "/api/codex/workspaces", json={"title": "Workspace", "project_id": project["id"]}
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


def test_get_issue_diff_resets_missing_worktree(client, tmp_path):
    project = _create_project(client, tmp_path, name="diff-missing")
    ws = client.post(
        "/api/codex/workspaces", json={"title": "Workspace", "project_id": project["id"]}
    ).json()
    issue = client.post(
        "/api/codex/issues",
        json={"session_id": ws["id"], "title": "Missing worktree"},
    ).json()
    shutil.rmtree(issue["git_worktree_path"])

    resp = client.get(f"/api/codex/issues/{issue['id']}/diff")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "diff": "",
        "base_branch": None,
        "branch": None,
        "stat": None,
        "commits_ahead": 0,
        "worktree_missing": True,
    }
    refreshed = client.get(f"/api/codex/issues/{issue['id']}").json()
    assert refreshed["git_worktree_path"] is None
    assert refreshed["git_branch"] is None


def test_issue_reset_rejects_missing_project_repo_without_mutating_state(client, tmp_path):
    project = _create_project(client, tmp_path, name="reset-missing-repo")
    ws = client.post(
        "/api/codex/workspaces", json={"title": "Workspace", "project_id": project["id"]}
    ).json()
    issue = client.post(
        "/api/codex/issues",
        json={"session_id": ws["id"], "title": "Reset should be atomic"},
    ).json()
    task = client.post(
        "/api/codex/tasks",
        json={
            "session_id": ws["id"],
            "issue_id": issue["id"],
            "title": "Existing task",
            "prompt": "keep me",
            "role": "engineer",
        },
    ).json()

    shutil.rmtree(project["repo_path"])

    resp = client.post(f"/api/codex/issues/{issue['id']}/reset")

    assert resp.status_code == 409, resp.text
    assert "repo path is missing" in resp.json()["detail"].lower()
    refreshed = client.get(f"/api/codex/issues/{issue['id']}").json()
    assert refreshed["status"] == issue["status"]
    assert refreshed["current_phase"] == issue["current_phase"]
    assert refreshed["git_worktree_path"] == issue["git_worktree_path"]
    assert refreshed["git_branch"] == issue["git_branch"]
    assert refreshed["git_base_branch"] == issue["git_base_branch"]
    assert refreshed["git_merge_status"] == issue["git_merge_status"]
    tasks = client.get(f"/api/codex/tasks?issue_id={issue['id']}").json()
    assert [t["id"] for t in tasks] == [task["id"]]


def test_issue_reset_recreates_existing_issue_branch(client, tmp_path):
    project = _create_project(client, tmp_path, name="reset-existing-branch")
    ws = client.post(
        "/api/codex/workspaces", json={"title": "Workspace", "project_id": project["id"]}
    ).json()
    issue = client.post(
        "/api/codex/issues",
        json={"session_id": ws["id"], "title": "Reset existing branch"},
    ).json()
    original_branch = issue["git_branch"]
    original_worktree = Path(issue["git_worktree_path"])
    (original_worktree / "generated.txt").write_text("old run\n")
    subprocess.run(["git", "add", "generated.txt"], cwd=original_worktree, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e", "-c", "user.name=T", "commit", "-m", "old run"],
        cwd=original_worktree,
        check=True,
        capture_output=True,
    )

    resp = client.post(f"/api/codex/issues/{issue['id']}/reset")

    assert resp.status_code == 201, resp.text
    refreshed = client.get(f"/api/codex/issues/{issue['id']}").json()
    assert refreshed["git_branch"] == original_branch
    assert Path(refreshed["git_worktree_path"]).exists()
    assert Path(refreshed["git_worktree_path"]) != original_worktree or original_worktree.exists()
    assert not (Path(refreshed["git_worktree_path"]) / "generated.txt").exists()
    assert refreshed["git_base_branch"] == "main"
    assert refreshed["git_merge_status"] == "open"


def test_conductor_restart_rejects_missing_project_repo_without_creating_graph(client, tmp_path):
    project = _create_project(client, tmp_path, name="restart-missing-repo")
    ws = client.post(
        "/api/codex/workspaces", json={"title": "Workspace", "project_id": project["id"]}
    ).json()
    issue = client.post(
        "/api/codex/issues",
        json={"session_id": ws["id"], "title": "Restart should not run without repo"},
    ).json()

    shutil.rmtree(project["repo_path"])

    resp = client.post(f"/api/codex/issues/{issue['id']}/conductor/restart")

    assert resp.status_code == 409, resp.text
    assert "repo path is missing" in resp.json()["detail"].lower()
    refreshed = client.get(f"/api/codex/issues/{issue['id']}").json()
    assert refreshed["git_worktree_path"] == issue["git_worktree_path"]
    assert refreshed["git_branch"] == issue["git_branch"]
    graph = client.get(f"/api/codex/issues/{issue['id']}/graph")
    assert graph.status_code == 404
