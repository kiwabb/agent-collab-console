from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from app.domain.models import SelfImprovementProposal


pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(shutil.which("git") is None, reason="git binary not available"),
]


def _make_git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)
    return path


def _create_project(client, tmp_path: Path, name: str = "self-improvement-api") -> dict:
    repo = _make_git_repo(tmp_path / name)
    resp = client.post(
        "/api/projects",
        json={"name": name, "source": "local", "repo_path": str(repo)},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _proposal(
    project_id: str,
    proposal_id="proposal-1",
    *,
    issue_id="issue-1",
    target_kind="runtime_tooling",
    status="proposed",
):
    return SelfImprovementProposal(
        id=proposal_id,
        project_id=project_id,
        issue_id=issue_id,
        target_kind=target_kind,
        title="Harden runtime failure handling",
        recommendation="Add a durable runtime guard.",
        evidence_json='[{"kind":"conductor_task","id":"task-1"}]',
        severity="medium",
        confidence=0.75,
        status=status,
        fingerprint=f"{project_id}|{issue_id}|{target_kind}|runtime_failure_contract",
        created_at=datetime(2026, 6, 8, 10, 0, 0),
        updated_at=datetime(2026, 6, 8, 10, 1, 0),
    )


def _seed_proposal(proposal: SelfImprovementProposal) -> None:
    import app.bootstrap as bootstrap_module

    assert bootstrap_module.store is not None
    bootstrap_module.store.save_self_improvement_proposal(proposal)


def test_project_self_improvement_proposals_endpoint_shape(client, tmp_path):
    project = _create_project(client, tmp_path, name="self-improvement-shape")
    _seed_proposal(_proposal(project["id"]))

    resp = client.get(f"/api/codex/projects/{project['id']}/self-improvement-proposals")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert list(body.keys()) == ["proposals"]
    assert body["proposals"][0]["id"] == "proposal-1"
    assert body["proposals"][0]["evidence"] == [{"kind": "conductor_task", "id": "task-1"}]
    assert body["proposals"][0]["created_at"] == "2026-06-08T10:00:00"


def test_project_self_improvement_proposals_endpoint_filters(client, tmp_path):
    project = _create_project(client, tmp_path, name="self-improvement-filters")
    _seed_proposal(_proposal(project["id"], "proposal-1", issue_id="issue-1"))
    _seed_proposal(_proposal(project["id"], "proposal-2", issue_id="issue-2", status="accepted"))

    resp = client.get(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals",
        params={"issue_id": "issue-2", "status": "accepted", "limit": 5},
    )

    assert resp.status_code == 200, resp.text
    proposals = resp.json()["proposals"]
    assert [proposal["id"] for proposal in proposals] == ["proposal-2"]


def test_project_self_improvement_proposal_patch_accepts_proposed(client, tmp_path):
    project = _create_project(client, tmp_path, name="self-improvement-accept")
    _seed_proposal(_proposal(project["id"]))

    resp = client.patch(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1",
        json={"status": "accepted"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == "proposal-1"
    assert body["status"] == "accepted"
    assert body["evidence"] == [{"kind": "conductor_task", "id": "task-1"}]
    assert body["updated_at"] != "2026-06-08T10:01:00"


def test_project_self_improvement_proposal_patch_rejects_proposed(client, tmp_path):
    project = _create_project(client, tmp_path, name="self-improvement-reject")
    _seed_proposal(_proposal(project["id"]))

    resp = client.patch(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1",
        json={"status": "rejected"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rejected"


def test_project_self_improvement_proposal_patch_applies_accepted(client, tmp_path):
    project = _create_project(client, tmp_path, name="self-improvement-apply")
    _seed_proposal(_proposal(project["id"], status="accepted"))

    resp = client.patch(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1",
        json={"status": "applied"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "applied"


def test_project_self_improvement_proposal_patch_is_idempotent(client, tmp_path):
    project = _create_project(client, tmp_path, name="self-improvement-idempotent")
    _seed_proposal(_proposal(project["id"], status="accepted"))

    resp = client.patch(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1",
        json={"status": "accepted"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "accepted"


def test_project_self_improvement_proposal_patch_rejects_invalid_transition(client, tmp_path):
    project = _create_project(client, tmp_path, name="self-improvement-conflict")
    _seed_proposal(_proposal(project["id"], status="rejected"))

    resp = client.patch(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1",
        json={"status": "accepted"},
    )

    assert resp.status_code == 409
    assert "Invalid self-improvement proposal status transition" in resp.json()["detail"]


def test_project_self_improvement_proposal_patch_returns_404_for_unknown_project_or_proposal(client, tmp_path):
    project = _create_project(client, tmp_path, name="self-improvement-missing")

    missing_project_resp = client.patch(
        "/api/codex/projects/missing-project/self-improvement-proposals/proposal-1",
        json={"status": "accepted"},
    )
    missing_proposal_resp = client.patch(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/missing-proposal",
        json={"status": "accepted"},
    )

    assert missing_project_resp.status_code == 404
    assert missing_project_resp.json()["detail"] == "Project not found"
    assert missing_proposal_resp.status_code == 404
    assert missing_proposal_resp.json()["detail"] == "Self-improvement proposal not found"


def test_project_self_improvement_proposal_patch_hides_cross_project_proposal(client, tmp_path):
    source_project = _create_project(client, tmp_path, name="self-improvement-source")
    other_project = _create_project(client, tmp_path, name="self-improvement-other")
    _seed_proposal(_proposal(source_project["id"]))

    resp = client.patch(
        f"/api/codex/projects/{other_project['id']}/self-improvement-proposals/proposal-1",
        json={"status": "accepted"},
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Self-improvement proposal not found"


def test_project_self_improvement_proposal_patch_returns_503_when_store_unavailable(client, monkeypatch):
    from app.interfaces import api as api_module

    monkeypatch.setattr(api_module, "codex_store", None)

    resp = client.patch(
        "/api/codex/projects/project-1/self-improvement-proposals/proposal-1",
        json={"status": "accepted"},
    )

    assert resp.status_code == 503
    assert resp.json()["detail"] == "SQLite store not available"


def test_project_self_improvement_proposal_apply_plan_for_accepted_project_memory(client, tmp_path):
    project = _create_project(client, tmp_path, name="self-improvement-apply-plan-memory")
    _seed_proposal(_proposal(project["id"], target_kind="project_memory", status="accepted"))

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/apply-plan"
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["proposal"]["id"] == "proposal-1"
    assert body["proposal"]["status"] == "accepted"
    assert body["plan"]["mode"] == "dry_run"
    assert body["plan"]["target_kind"] == "project_memory"
    assert body["plan"]["candidate_changes"][0]["kind"] == "append_markdown"
    assert body["plan"]["candidate_changes"][0]["path"] == ".agent-collab/team_notes.md"
    assert "Harden runtime failure handling" in body["plan"]["candidate_changes"][0]["content"]

    proposals = client.get(f"/api/codex/projects/{project['id']}/self-improvement-proposals").json()["proposals"]
    assert proposals[0]["status"] == "accepted"


def test_project_self_improvement_proposal_apply_plan_for_accepted_non_memory(client, tmp_path):
    project = _create_project(client, tmp_path, name="self-improvement-apply-plan-spec")
    _seed_proposal(_proposal(project["id"], target_kind="code_spec", status="accepted"))

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/apply-plan"
    )

    assert resp.status_code == 200, resp.text
    plan = resp.json()["plan"]
    assert plan["target_kind"] == "code_spec"
    assert plan["candidate_changes"][0]["kind"] == "open_pr_task"
    assert "Add a durable runtime guard" in plan["candidate_changes"][0]["body"]
    assert all(change["kind"] != "patch_file" for change in plan["candidate_changes"])


@pytest.mark.parametrize("status", ["proposed", "rejected", "applied"])
def test_project_self_improvement_proposal_apply_plan_requires_accepted_status(client, tmp_path, status):
    project = _create_project(client, tmp_path, name=f"self-improvement-apply-plan-{status}")
    _seed_proposal(_proposal(project["id"], status=status))

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/apply-plan"
    )

    assert resp.status_code == 409
    assert "accepted" in resp.json()["detail"]


def test_project_self_improvement_proposal_apply_plan_returns_404_for_unknown_or_cross_project(client, tmp_path):
    source_project = _create_project(client, tmp_path, name="self-improvement-apply-plan-source")
    other_project = _create_project(client, tmp_path, name="self-improvement-apply-plan-other")
    _seed_proposal(_proposal(source_project["id"], status="accepted"))

    missing_project_resp = client.post(
        "/api/codex/projects/missing-project/self-improvement-proposals/proposal-1/apply-plan"
    )
    missing_proposal_resp = client.post(
        f"/api/codex/projects/{source_project['id']}/self-improvement-proposals/missing/apply-plan"
    )
    cross_project_resp = client.post(
        f"/api/codex/projects/{other_project['id']}/self-improvement-proposals/proposal-1/apply-plan"
    )

    assert missing_project_resp.status_code == 404
    assert missing_project_resp.json()["detail"] == "Project not found"
    assert missing_proposal_resp.status_code == 404
    assert missing_proposal_resp.json()["detail"] == "Self-improvement proposal not found"
    assert cross_project_resp.status_code == 404
    assert cross_project_resp.json()["detail"] == "Self-improvement proposal not found"


def test_project_self_improvement_proposal_apply_plan_returns_503_when_store_unavailable(client, monkeypatch):
    from app.interfaces import api as api_module

    monkeypatch.setattr(api_module, "codex_store", None)

    resp = client.post(
        "/api/codex/projects/project-1/self-improvement-proposals/proposal-1/apply-plan"
    )

    assert resp.status_code == 503
    assert resp.json()["detail"] == "SQLite store not available"
