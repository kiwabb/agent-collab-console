"""Critical-path tests from test_codex_tasks.py, ported to the project+worktree model.

Each session in the new model needs a project_id, and every issue automatically
gets a git worktree. These tests use a fresh temp git repo per test so they
don't share state across runs.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary not available")


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@e"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("seed")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)
    return path


@pytest.fixture
def project_ctx(client, tmp_path):
    """Build a fresh project + workspace and yield their primary IDs."""
    repo = _init_repo(tmp_path / "repo")
    project = client.post(
        "/api/projects",
        json={"name": tmp_path.name, "source": "local", "repo_path": str(repo)},
    ).json()
    workspace = client.post(
        "/api/codex/workspaces",
        json={"title": "WS", "project_id": project["id"]},
    ).json()
    return {"project_id": project["id"], "session_id": workspace["id"], "repo": repo}


def test_create_and_list_issues_for_workspace(client, project_ctx):
    create_resp = client.post(
        "/api/codex/issues",
        json={
            "session_id": project_ctx["session_id"],
            "title": "Issue-first flow",
            "description": "Wire issues into the system",
        },
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["session_id"] == project_ctx["session_id"]
    assert created["project_id"] == project_ctx["project_id"]
    assert created["current_phase"] == "requirements"
    assert created["status"] == "open"
    # Worktree is materialised on the issue.
    assert created["git_branch"] and created["git_worktree_path"]

    listing = client.get(f"/api/codex/issues?session_id={project_ctx['session_id']}").json()
    assert any(i["id"] == created["id"] for i in listing)


def test_create_task_linked_to_issue_inherits_worktree(client, project_ctx):
    issue = client.post(
        "/api/codex/issues",
        json={"session_id": project_ctx["session_id"], "title": "PM issue"},
    ).json()
    task_resp = client.post(
        "/api/codex/tasks",
        json={
            "session_id": project_ctx["session_id"],
            "issue_id": issue["id"],
            "title": "Write PRD",
            "prompt": "...",
            "role": "product_manager",
        },
    )
    assert task_resp.status_code == 201, task_resp.text
    task = task_resp.json()
    assert task["issue_id"] == issue["id"]
    # Task inherits the issue's worktree path, not an ephemeral one.
    assert task["git_worktree_path"] == issue["git_worktree_path"]
    assert task["workspace_path"] == issue["git_worktree_path"]


def test_create_task_can_set_phase(client, project_ctx):
    issue = client.post(
        "/api/codex/issues",
        json={"session_id": project_ctx["session_id"], "title": "Architecture issue"},
    ).json()
    task_resp = client.post(
        "/api/codex/tasks",
        json={
            "session_id": project_ctx["session_id"],
            "issue_id": issue["id"],
            "title": "Design",
            "prompt": "...",
            "role": "architect",
            "phase": "architecture",
        },
    )
    assert task_resp.status_code == 201, task_resp.text
    assert task_resp.json()["phase"] == "architecture"


@pytest.mark.parametrize(
    "role,expected_phase",
    [
        ("product_manager", "requirements"),
        ("architect", "architecture"),
        ("engineer", "development"),
        ("qa", "testing"),
    ],
)
def test_create_task_defaults_phase_for_each_role(client, project_ctx, role, expected_phase):
    """Phase is now a free-form tag — the test still passes a role and gets
    back *a* phase, but the precise phase value is no longer constrained to
    the legacy 4-phase enum. We just verify the task was created with the
    supplied role."""
    issue = client.post(
        "/api/codex/issues",
        json={"session_id": project_ctx["session_id"], "title": "role default"},
    ).json()
    task_resp = client.post(
        "/api/codex/tasks",
        json={
            "session_id": project_ctx["session_id"],
            "issue_id": issue["id"],
            "title": "T",
            "prompt": "...",
            "role": role,
        },
    )
    assert task_resp.status_code == 201
    assert task_resp.json()["role"] == role


def test_create_task_allows_any_role_phase_combination(client, project_ctx):
    """PR5: role and phase are decoupled. An engineer-role task with
    phase='requirements' is now allowed (and useful for custom DAGs)."""
    issue = client.post(
        "/api/codex/issues",
        json={"session_id": project_ctx["session_id"], "title": "mismatch"},
    ).json()
    resp = client.post(
        "/api/codex/tasks",
        json={
            "session_id": project_ctx["session_id"],
            "issue_id": issue["id"],
            "title": "T",
            "prompt": "...",
            "role": "engineer",
            "phase": "requirements",
        },
    )
    assert resp.status_code == 201


def test_update_issue_phase(client, project_ctx):
    issue = client.post(
        "/api/codex/issues",
        json={"session_id": project_ctx["session_id"], "title": "phase update"},
    ).json()
    resp = client.post(
        f"/api/codex/issues/{issue['id']}/phase",
        json={"current_phase": "development"},
    )
    assert resp.status_code == 200
    assert resp.json()["current_phase"] == "development"


def test_update_issue_phase_accepts_freeform_value(client, project_ctx):
    """PR5: issue phase is no longer enum-validated. Any string sticks."""
    issue = client.post(
        "/api/codex/issues",
        json={"session_id": project_ctx["session_id"], "title": "freeform"},
    ).json()
    resp = client.post(
        f"/api/codex/issues/{issue['id']}/phase",
        json={"current_phase": "frob"},
    )
    assert resp.status_code == 200
    assert resp.json()["current_phase"] == "frob"


def test_chat_task_creates_own_worktree(client, project_ctx):
    """Tasks without an issue_id get a per-task worktree under chat/<id>-..."""
    resp = client.post(
        "/api/codex/tasks",
        json={
            "session_id": project_ctx["session_id"],
            "title": "ad-hoc chat",
            "prompt": "...",
            "role": "general",
        },
    )
    assert resp.status_code == 201, resp.text
    task = resp.json()
    assert task["git_branch"].startswith("chat/")
    assert task["git_worktree_path"]
    assert Path(task["git_worktree_path"]).exists()


def test_delete_issue_cleans_up_worktree(client, project_ctx):
    issue = client.post(
        "/api/codex/issues",
        json={"session_id": project_ctx["session_id"], "title": "doomed"},
    ).json()
    worktree = Path(issue["git_worktree_path"])
    assert worktree.exists()
    resp = client.delete(f"/api/codex/issues/{issue['id']}")
    assert resp.status_code == 200
    assert not worktree.exists()


def test_list_tasks_filtered_by_session(client, project_ctx):
    issue = client.post(
        "/api/codex/issues",
        json={"session_id": project_ctx["session_id"], "title": "filter"},
    ).json()
    client.post(
        "/api/codex/tasks",
        json={
            "session_id": project_ctx["session_id"],
            "issue_id": issue["id"],
            "title": "T1",
            "prompt": "...",
            "role": "product_manager",
        },
    )
    resp = client.get(f"/api/codex/tasks?session_id={project_ctx['session_id']}")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1
