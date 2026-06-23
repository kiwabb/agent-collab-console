from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.application.conductor_session_registry import ConductorSessionRegistry
from app.application.self_improvement_apply_service import build_self_improvement_apply_plan, hash_apply_candidate_content
from app.domain.models import CodexIssue, Project, SelfImprovementApplicationEvent, SelfImprovementProposal


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


def _source_issue(
    project_id: str,
    issue_id: str = "issue-1",
    *,
    session_id: str = "workspace-1",
) -> CodexIssue:
    return CodexIssue(
        id=issue_id,
        session_id=session_id,
        project_id=project_id,
        title="Original runtime failure",
        description="The source issue that produced the proposal.",
        current_phase="done",
        status="completed",
        executor="codex",
        provider="openai",
        model="gpt-5",
        created_at=datetime(2026, 6, 8, 9, 0, 0),
        updated_at=datetime(2026, 6, 8, 9, 1, 0),
    )


def _seed_issue(issue: CodexIssue) -> None:
    import app.bootstrap as bootstrap_module

    assert bootstrap_module.store is not None
    bootstrap_module.store.save_codex_issue(issue)


def _application_event(
    project_id: str,
    event_id="event-1",
    *,
    proposal_id="proposal-1",
    issue_id="issue-1",
    target_kind="project_memory",
    action="apply",
    status="succeeded",
    path=".agent-collab/team_notes.md",
    content_sha256: str | None = "a" * 64,
    result: dict | None = None,
    error: str | None = None,
    created_at: datetime | None = None,
) -> SelfImprovementApplicationEvent:
    return SelfImprovementApplicationEvent(
        id=event_id,
        proposal_id=proposal_id,
        project_id=project_id,
        issue_id=issue_id,
        target_kind=target_kind,
        action=action,
        status=status,
        path=path,
        content_sha256=content_sha256,
        result_json=json.dumps(result or {}, sort_keys=True),
        error=error,
        created_at=created_at or datetime(2026, 6, 8, 10, 0, 0),
    )


def _seed_application_event(event: SelfImprovementApplicationEvent) -> None:
    import app.bootstrap as bootstrap_module

    assert bootstrap_module.store is not None
    bootstrap_module.store.save_self_improvement_application_event(event)


def _applications(client, project_id: str, proposal_id: str = "proposal-1") -> list[dict]:
    return client.get(
        f"/api/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/applications"
    ).json()["applications"]


def _candidate_content_hash(proposal: SelfImprovementProposal) -> str:
    candidate = build_self_improvement_apply_plan(proposal)["candidate_changes"][0]
    content = candidate.get("content")
    assert isinstance(content, str)
    return hash_apply_candidate_content(content)


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


def test_project_self_improvement_proposal_activate_task_creates_issue_worktree_and_event(client, tmp_path):
    project = _create_project(client, tmp_path, name="self-improvement-activate-task")
    source_issue = _source_issue(project["id"])
    proposal = _proposal(project["id"], target_kind="code_spec", status="accepted")
    _seed_issue(source_issue)
    _seed_proposal(proposal)

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task"
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    activation = body["activation"]
    issue = activation["issue"]
    application = activation["application"]
    assert body["proposal"]["status"] == "accepted"
    assert activation["already_created"] is False
    assert issue["id"] != source_issue.id
    assert issue["project_id"] == project["id"]
    assert issue["session_id"] == source_issue.session_id
    assert issue["title"] == "Apply self-improvement proposal: Harden runtime failure handling"
    assert issue["current_phase"] == "requirements"
    assert issue["status"] == "open"
    assert issue["executor"] == source_issue.executor
    assert issue["provider"] == source_issue.provider
    assert issue["model"] == source_issue.model
    assert issue["git_branch"].startswith(f"issue/{issue['id'][:8]}-")
    assert issue["git_base_branch"] == "main"
    assert issue["git_worktree_path"]
    assert Path(issue["git_worktree_path"]).is_dir()
    assert "Proposal ID: `proposal-1`" in issue["description"]
    assert "Target kind: `code_spec`" in issue["description"]
    assert "Source issue ID: `issue-1`" in issue["description"]
    assert "conductor_task: task-1" in issue["description"]
    assert application["action"] == "open_pr_task"
    assert application["status"] == "succeeded"
    assert application["path"] == f"codex_issues/{issue['id']}"
    assert application["error"] is None
    assert application["result"]["issue_id"] == issue["id"]
    assert application["result"]["issue_title"] == issue["title"]
    assert application["result"]["git_branch"] == issue["git_branch"]
    assert application["result"]["git_base_branch"] == "main"
    assert application["result"]["git_worktree_path"] == issue["git_worktree_path"]

    proposals = client.get(f"/api/codex/projects/{project['id']}/self-improvement-proposals").json()["proposals"]
    assert proposals[0]["status"] == "accepted"
    events = client.get(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/applications"
    ).json()["applications"]
    assert len(events) == 1
    assert events[0]["action"] == "open_pr_task"


def test_project_self_improvement_proposal_activate_task_without_body_does_not_start_conductor(
    client,
    tmp_path,
    monkeypatch,
):
    from app.interfaces import api as api_module

    project = _create_project(client, tmp_path, name="self-improvement-activate-no-body")
    _seed_issue(_source_issue(project["id"]))
    _seed_proposal(_proposal(project["id"], target_kind="runtime_tooling", status="accepted"))

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("conductor should not start without explicit opt-in")

    monkeypatch.setattr(api_module, "_start_issue_conductor_graph", fail_if_called)

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task"
    )

    assert resp.status_code == 200, resp.text
    activation = resp.json()["activation"]
    assert "conductor" not in activation
    assert [event["action"] for event in _applications(client, project["id"])] == ["open_pr_task"]


def test_project_self_improvement_proposal_activate_task_empty_body_does_not_start_conductor(
    client,
    tmp_path,
    monkeypatch,
):
    from app.interfaces import api as api_module

    project = _create_project(client, tmp_path, name="self-improvement-activate-empty-body")
    _seed_issue(_source_issue(project["id"]))
    _seed_proposal(_proposal(project["id"], target_kind="runtime_tooling", status="accepted"))

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("conductor should not start without explicit opt-in")

    monkeypatch.setattr(api_module, "_start_issue_conductor_graph", fail_if_called)

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task",
        json={},
    )

    assert resp.status_code == 200, resp.text
    activation = resp.json()["activation"]
    assert "conductor" not in activation
    assert [event["action"] for event in _applications(client, project["id"])] == ["open_pr_task"]


def test_project_self_improvement_proposal_activate_task_can_start_conductor(client, tmp_path, monkeypatch):
    from app.interfaces import api as api_module

    project = _create_project(client, tmp_path, name="self-improvement-activate-start")
    _seed_issue(_source_issue(project["id"]))
    _seed_proposal(_proposal(project["id"], target_kind="runtime_tooling", status="accepted"))
    calls: list[str] = []

    async def fake_start(issue_id: str, *, store):
        calls.append(issue_id)
        return {
            "started": True,
            "already_running": False,
            "graph": {
                "id": "graph-1",
                "issue_id": issue_id,
                "status": "running",
                "nodes": [],
                "edges": [],
            },
        }

    monkeypatch.setattr(api_module, "_start_issue_conductor_graph", fake_start)

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task",
        json={"start_conductor": True},
    )

    assert resp.status_code == 200, resp.text
    activation = resp.json()["activation"]
    assert calls == [activation["issue"]["id"]]
    assert activation["conductor"]["started"] is True
    assert activation["conductor"]["already_running"] is False
    assert activation["conductor"]["graph"]["id"] == "graph-1"
    events = _applications(client, project["id"])
    assert [event["action"] for event in events] == ["start_conductor", "open_pr_task"]
    assert events[0]["status"] == "succeeded"
    assert events[0]["path"] == f"codex_issues/{activation['issue']['id']}"
    assert events[0]["result"]["graph_id"] == "graph-1"
    assert events[0]["result"]["started"] is True


def test_project_self_improvement_proposal_activate_task_reuses_issue_when_starting_conductor_twice(
    client,
    tmp_path,
    monkeypatch,
):
    from app.interfaces import api as api_module

    project = _create_project(client, tmp_path, name="self-improvement-activate-start-repeat")
    _seed_issue(_source_issue(project["id"]))
    _seed_proposal(_proposal(project["id"], target_kind="runtime_tooling", status="accepted"))
    starts: list[str] = []

    async def fake_start(issue_id: str, *, store):
        starts.append(issue_id)
        return {
            "started": len(starts) == 1,
            "already_running": len(starts) > 1,
            "graph": {"id": "graph-1", "issue_id": issue_id, "status": "running", "nodes": [], "edges": []},
        }

    monkeypatch.setattr(api_module, "_start_issue_conductor_graph", fake_start)

    first = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task",
        json={"start_conductor": True},
    )
    second = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task",
        json={"start_conductor": True},
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["activation"]["already_created"] is True
    assert second.json()["activation"]["issue"]["id"] == first.json()["activation"]["issue"]["id"]
    assert starts == [first.json()["activation"]["issue"]["id"], first.json()["activation"]["issue"]["id"]]
    issues = client.get(f"/api/codex/issues?project_id={project['id']}").json()
    assert len([issue for issue in issues if issue["title"].startswith("Apply self-improvement proposal:")]) == 1


def test_project_self_improvement_proposal_activate_task_can_start_existing_activation(
    client,
    tmp_path,
    monkeypatch,
):
    from app.interfaces import api as api_module

    project = _create_project(client, tmp_path, name="self-improvement-activate-late-start")
    _seed_issue(_source_issue(project["id"]))
    _seed_proposal(_proposal(project["id"], target_kind="runtime_tooling", status="accepted"))
    first = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task"
    )
    issue_id = first.json()["activation"]["issue"]["id"]

    async def fake_start(issue_id_arg: str, *, store):
        assert issue_id_arg == issue_id
        return {
            "started": True,
            "already_running": False,
            "graph": {"id": "graph-late", "issue_id": issue_id_arg, "status": "running", "nodes": [], "edges": []},
        }

    monkeypatch.setattr(api_module, "_start_issue_conductor_graph", fake_start)

    second = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task",
        json={"start_conductor": True},
    )

    assert second.status_code == 200, second.text
    assert second.json()["activation"]["already_created"] is True
    assert second.json()["activation"]["conductor"]["graph"]["id"] == "graph-late"


def test_project_self_improvement_proposal_activate_task_records_failed_start_event(
    client,
    tmp_path,
    monkeypatch,
):
    from app.interfaces import api as api_module

    project = _create_project(client, tmp_path, name="self-improvement-activate-start-fail")
    _seed_issue(_source_issue(project["id"]))
    _seed_proposal(_proposal(project["id"], target_kind="runtime_tooling", status="accepted"))

    async def fail_start(*_args, **_kwargs):
        raise RuntimeError("synthetic conductor start failure")

    monkeypatch.setattr(api_module, "_start_issue_conductor_graph", fail_start)

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task",
        json={"start_conductor": True},
    )

    assert resp.status_code == 500
    assert "synthetic conductor start failure" in resp.json()["detail"]
    proposals = client.get(f"/api/codex/projects/{project['id']}/self-improvement-proposals").json()["proposals"]
    assert proposals[0]["status"] == "accepted"
    events = _applications(client, project["id"])
    assert [event["action"] for event in events] == ["start_conductor", "open_pr_task"]
    assert events[0]["status"] == "failed"
    assert "synthetic conductor start failure" in events[0]["error"]


async def test_start_issue_conductor_graph_is_idempotent_while_session_is_alive(monkeypatch, tmp_path):
    from app.application import conductor_main_loop
    from app.interfaces import api as api_module

    store = AsyncSQLiteStore(tmp_path / "conductor-start.db")
    project = Project(
        id="project-1",
        name="project",
        repo_path=str(tmp_path / "repo"),
        default_branch="main",
        created_at=datetime(2026, 6, 9, 9, 0, 0),
        updated_at=datetime(2026, 6, 9, 9, 0, 0),
    )
    issue = _source_issue(project.id, issue_id="issue-start-helper")
    issue.git_worktree_path = str(tmp_path / "repo-worktree")
    await store.save_project(project)
    await store.save_codex_issue(issue)

    async def sleep_forever(**_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(conductor_main_loop, "run_issue_conductor_loop", sleep_forever)

    try:
        first = await api_module._start_issue_conductor_graph(issue.id, store=store)
        second = await api_module._start_issue_conductor_graph(issue.id, store=store)
        assert first["started"] is True
        assert first["already_running"] is False
        assert second["started"] is False
        assert second["already_running"] is True
        assert second["graph"]["id"] == first["graph"]["id"]
        assert ConductorSessionRegistry.instance().is_alive(issue.id)
    finally:
        await ConductorSessionRegistry.instance().stop(issue.id)
        await store.close()


def test_project_self_improvement_proposal_activate_task_is_idempotent(client, tmp_path):
    project = _create_project(client, tmp_path, name="self-improvement-activate-idempotent")
    _seed_issue(_source_issue(project["id"]))
    _seed_proposal(_proposal(project["id"], target_kind="runtime_tooling", status="accepted"))

    first = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task"
    )
    second = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task"
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_activation = first.json()["activation"]
    second_activation = second.json()["activation"]
    assert first_activation["already_created"] is False
    assert second_activation["already_created"] is True
    assert second_activation["issue"]["id"] == first_activation["issue"]["id"]
    events = client.get(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/applications"
    ).json()["applications"]
    assert len(events) == 1
    issues = client.get(f"/api/codex/issues?project_id={project['id']}").json()
    assert len([issue for issue in issues if issue["title"].startswith("Apply self-improvement proposal:")]) == 1


def test_project_self_improvement_proposal_activate_task_rejects_project_memory(client, tmp_path):
    project = _create_project(client, tmp_path, name="self-improvement-activate-memory")
    _seed_issue(_source_issue(project["id"]))
    _seed_proposal(_proposal(project["id"], target_kind="project_memory", status="accepted"))

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task"
    )

    assert resp.status_code == 409
    assert "project_memory" in resp.json()["detail"]


@pytest.mark.parametrize("status", ["proposed", "rejected", "applied"])
def test_project_self_improvement_proposal_activate_task_requires_accepted_status(client, tmp_path, status):
    project = _create_project(client, tmp_path, name=f"self-improvement-activate-{status}")
    _seed_issue(_source_issue(project["id"]))
    _seed_proposal(_proposal(project["id"], target_kind="runtime_tooling", status=status))

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task"
    )

    assert resp.status_code == 409
    assert "accepted" in resp.json()["detail"]


def test_project_self_improvement_proposal_activate_task_returns_404_for_unknown_or_cross_project(client, tmp_path):
    source_project = _create_project(client, tmp_path, name="self-improvement-activate-source")
    other_project = _create_project(client, tmp_path, name="self-improvement-activate-other")
    _seed_issue(_source_issue(source_project["id"]))
    _seed_proposal(_proposal(source_project["id"], target_kind="runtime_tooling", status="accepted"))

    missing_project_resp = client.post(
        "/api/codex/projects/missing-project/self-improvement-proposals/proposal-1/activate-task"
    )
    missing_proposal_resp = client.post(
        f"/api/codex/projects/{source_project['id']}/self-improvement-proposals/missing/activate-task"
    )
    cross_project_resp = client.post(
        f"/api/codex/projects/{other_project['id']}/self-improvement-proposals/proposal-1/activate-task"
    )

    assert missing_project_resp.status_code == 404
    assert missing_project_resp.json()["detail"] == "Project not found"
    assert missing_proposal_resp.status_code == 404
    assert missing_proposal_resp.json()["detail"] == "Self-improvement proposal not found"
    assert cross_project_resp.status_code == 404
    assert cross_project_resp.json()["detail"] == "Self-improvement proposal not found"


def test_project_self_improvement_proposal_activate_task_rejects_missing_source_issue(client, tmp_path):
    project = _create_project(client, tmp_path, name="self-improvement-activate-missing-source")
    _seed_proposal(_proposal(project["id"], target_kind="runtime_tooling", status="accepted"))

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task"
    )

    assert resp.status_code == 409
    assert "source issue" in resp.json()["detail"]


def test_project_self_improvement_proposal_activate_task_records_failed_event_on_worktree_error(
    client,
    tmp_path,
    monkeypatch,
):
    from app.application.worktree_manager import WorktreeError
    from app.interfaces import api as api_module

    project = _create_project(client, tmp_path, name="self-improvement-activate-worktree-error")
    _seed_issue(_source_issue(project["id"]))
    _seed_proposal(_proposal(project["id"], target_kind="runtime_tooling", status="accepted"))

    async def fail_prepare_issue_worktree(*_args, **_kwargs):
        raise WorktreeError("synthetic worktree failure")

    monkeypatch.setattr(api_module.worktree_manager, "prepare_issue_worktree", fail_prepare_issue_worktree)

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task"
    )

    assert resp.status_code == 500
    assert "synthetic worktree failure" in resp.json()["detail"]
    proposals = client.get(f"/api/codex/projects/{project['id']}/self-improvement-proposals").json()["proposals"]
    assert proposals[0]["status"] == "accepted"
    events = client.get(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/applications"
    ).json()["applications"]
    assert len(events) == 1
    assert events[0]["action"] == "open_pr_task"
    assert events[0]["status"] == "failed"
    assert "synthetic worktree failure" in events[0]["error"]
    issues = client.get(f"/api/codex/issues?project_id={project['id']}").json()
    assert len([issue for issue in issues if issue["title"].startswith("Apply self-improvement proposal:")]) == 0


def test_project_self_improvement_proposal_activate_task_returns_503_when_store_unavailable(client, monkeypatch):
    from app.interfaces import api as api_module

    monkeypatch.setattr(api_module, "codex_store", None)

    resp = client.post(
        "/api/codex/projects/project-1/self-improvement-proposals/proposal-1/activate-task"
    )

    assert resp.status_code == 503
    assert resp.json()["detail"] == "SQLite store not available"


def test_project_self_improvement_proposal_apply_project_memory_appends_and_marks_applied(client, tmp_path):
    name = "self-improvement-reviewed-apply-memory"
    project = _create_project(client, tmp_path, name=name)
    proposal = _proposal(project["id"], target_kind="project_memory", status="accepted")
    _seed_proposal(proposal)

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/apply",
        json={"content_sha256": _candidate_content_hash(proposal)},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    memory_content = (tmp_path / name / ".agent-collab" / "team_notes.md").read_text(encoding="utf-8")
    assert body["proposal"]["status"] == "applied"
    assert body["application"]["path"] == ".agent-collab/team_notes.md"
    assert body["application"]["already_present"] is False
    assert body["application"]["content_sha256"] == _candidate_content_hash(proposal)
    assert "self-improvement-proposal:proposal-1" in memory_content
    assert "Add a durable runtime guard." in memory_content


def test_project_self_improvement_proposal_apply_project_memory_skips_existing_marker(client, tmp_path):
    name = "self-improvement-reviewed-apply-existing"
    project = _create_project(client, tmp_path, name=name)
    proposal = _proposal(project["id"], target_kind="project_memory", status="accepted")
    _seed_proposal(proposal)
    plan = build_self_improvement_apply_plan(proposal)
    content = plan["candidate_changes"][0]["content"]
    memory_path = tmp_path / name / ".agent-collab" / "team_notes.md"
    memory_path.parent.mkdir()
    memory_path.write_text("Existing note\n\n" + content, encoding="utf-8")

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/apply",
        json={"content_sha256": hash_apply_candidate_content(content)},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["proposal"]["status"] == "applied"
    assert body["application"]["already_present"] is True
    assert body["application"]["bytes_written"] == 0
    assert memory_path.read_text(encoding="utf-8").count("self-improvement-proposal:proposal-1") == 1


def test_project_self_improvement_proposal_apply_rejects_hash_mismatch_without_writing(client, tmp_path):
    name = "self-improvement-reviewed-apply-hash"
    project = _create_project(client, tmp_path, name=name)
    _seed_proposal(_proposal(project["id"], target_kind="project_memory", status="accepted"))

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/apply",
        json={"content_sha256": "0" * 64},
    )

    assert resp.status_code == 409
    assert "hash" in resp.json()["detail"]
    assert not (tmp_path / name / ".agent-collab" / "team_notes.md").exists()
    proposals = client.get(f"/api/codex/projects/{project['id']}/self-improvement-proposals").json()["proposals"]
    assert proposals[0]["status"] == "accepted"


def test_project_self_improvement_proposal_apply_rejects_non_memory_target_without_writing(client, tmp_path):
    name = "self-improvement-reviewed-apply-spec"
    project = _create_project(client, tmp_path, name=name)
    proposal = _proposal(project["id"], target_kind="code_spec", status="accepted")
    _seed_proposal(proposal)

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/apply",
        json={"content_sha256": hash_apply_candidate_content("reviewed")},
    )

    assert resp.status_code == 409
    assert "project_memory" in resp.json()["detail"]
    assert not (tmp_path / name / ".agent-collab" / "team_notes.md").exists()


@pytest.mark.parametrize("status", ["proposed", "rejected", "applied"])
def test_project_self_improvement_proposal_apply_requires_accepted_status(client, tmp_path, status):
    name = f"self-improvement-reviewed-apply-{status}"
    project = _create_project(client, tmp_path, name=name)
    proposal = _proposal(project["id"], target_kind="project_memory", status=status)
    _seed_proposal(proposal)

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/apply",
        json={"content_sha256": _candidate_content_hash(proposal)},
    )

    assert resp.status_code == 409
    assert "accepted" in resp.json()["detail"]
    assert not (tmp_path / name / ".agent-collab" / "team_notes.md").exists()


def test_project_self_improvement_proposal_apply_returns_404_for_unknown_or_cross_project(client, tmp_path):
    source_project = _create_project(client, tmp_path, name="self-improvement-apply-source")
    other_project = _create_project(client, tmp_path, name="self-improvement-apply-other")
    proposal = _proposal(source_project["id"], target_kind="project_memory", status="accepted")
    _seed_proposal(proposal)
    payload = {"content_sha256": _candidate_content_hash(proposal)}

    missing_project_resp = client.post(
        "/api/codex/projects/missing-project/self-improvement-proposals/proposal-1/apply",
        json=payload,
    )
    missing_proposal_resp = client.post(
        f"/api/codex/projects/{source_project['id']}/self-improvement-proposals/missing/apply",
        json=payload,
    )
    cross_project_resp = client.post(
        f"/api/codex/projects/{other_project['id']}/self-improvement-proposals/proposal-1/apply",
        json=payload,
    )

    assert missing_project_resp.status_code == 404
    assert missing_project_resp.json()["detail"] == "Project not found"
    assert missing_proposal_resp.status_code == 404
    assert missing_proposal_resp.json()["detail"] == "Self-improvement proposal not found"
    assert cross_project_resp.status_code == 404
    assert cross_project_resp.json()["detail"] == "Self-improvement proposal not found"


def test_project_self_improvement_proposal_apply_returns_503_when_store_unavailable(client, monkeypatch):
    from app.interfaces import api as api_module

    monkeypatch.setattr(api_module, "codex_store", None)

    resp = client.post(
        "/api/codex/projects/project-1/self-improvement-proposals/proposal-1/apply",
        json={"content_sha256": "0" * 64},
    )

    assert resp.status_code == 503
    assert resp.json()["detail"] == "SQLite store not available"


def test_project_self_improvement_proposal_apply_returns_500_for_unavailable_repo(client, tmp_path):
    name = "self-improvement-reviewed-apply-missing-repo"
    project = _create_project(client, tmp_path, name=name)
    proposal = _proposal(project["id"], target_kind="project_memory", status="accepted")
    _seed_proposal(proposal)
    shutil.rmtree(tmp_path / name)

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/apply",
        json={"content_sha256": _candidate_content_hash(proposal)},
    )

    assert resp.status_code == 500
    assert "repository path" in resp.json()["detail"]
    proposals = client.get(f"/api/codex/projects/{project['id']}/self-improvement-proposals").json()["proposals"]
    assert proposals[0]["status"] == "accepted"
    event = client.get(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/applications"
    ).json()["applications"][0]
    assert event["action"] == "apply"
    assert event["status"] == "failed"
    assert event["content_sha256"] == _candidate_content_hash(proposal)
    assert "repository path" in event["error"]


def test_project_self_improvement_proposal_applications_endpoint_lists_project_scoped_events(client, tmp_path):
    project = _create_project(client, tmp_path, name="self-improvement-applications-list")
    other_project = _create_project(client, tmp_path, name="self-improvement-applications-other")
    _seed_proposal(_proposal(project["id"], target_kind="project_memory", status="applied"))
    _seed_application_event(
        _application_event(
            project["id"],
            "event-1",
            result={"already_present": False},
            created_at=datetime(2026, 6, 8, 10, 0, 0),
        )
    )
    _seed_application_event(
        _application_event(
            project["id"],
            "event-2",
            action="rollback",
            status="failed",
            content_sha256=None,
            result={},
            error="Self-improvement proposal must be applied before it can be rolled back",
            created_at=datetime(2026, 6, 8, 10, 1, 0),
        )
    )
    _seed_application_event(
        _application_event(
            other_project["id"],
            "event-3",
            proposal_id="proposal-other",
            issue_id="issue-other",
            created_at=datetime(2026, 6, 8, 10, 2, 0),
        )
    )

    resp = client.get(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/applications"
    )

    assert resp.status_code == 200, resp.text
    applications = resp.json()["applications"]
    assert [event["id"] for event in applications] == ["event-2", "event-1"]
    assert applications[0]["project_id"] == project["id"]
    assert applications[0]["action"] == "rollback"
    assert applications[0]["status"] == "failed"
    assert applications[0]["result"] == {}
    assert applications[0]["error"] == "Self-improvement proposal must be applied before it can be rolled back"
    assert applications[1]["result"] == {"already_present": False}
    assert applications[1]["created_at"] == "2026-06-08T10:00:00"


def test_project_self_improvement_proposal_applications_endpoint_hides_cross_project_proposal(client, tmp_path):
    source_project = _create_project(client, tmp_path, name="self-improvement-applications-source")
    other_project = _create_project(client, tmp_path, name="self-improvement-applications-cross")
    _seed_proposal(_proposal(source_project["id"], target_kind="project_memory", status="applied"))

    resp = client.get(
        f"/api/codex/projects/{other_project['id']}/self-improvement-proposals/proposal-1/applications"
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Self-improvement proposal not found"


def test_project_self_improvement_proposal_applications_endpoint_returns_503_when_store_unavailable(client, monkeypatch):
    from app.interfaces import api as api_module

    monkeypatch.setattr(api_module, "codex_store", None)

    resp = client.get("/api/codex/projects/project-1/self-improvement-proposals/proposal-1/applications")

    assert resp.status_code == 503
    assert resp.json()["detail"] == "SQLite store not available"


def test_project_self_improvement_proposal_apply_records_succeeded_application_event(client, tmp_path):
    name = "self-improvement-apply-event-success"
    project = _create_project(client, tmp_path, name=name)
    proposal = _proposal(project["id"], target_kind="project_memory", status="accepted")
    content_hash = _candidate_content_hash(proposal)
    _seed_proposal(proposal)

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/apply",
        json={"content_sha256": content_hash},
    )
    applications_resp = client.get(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/applications"
    )

    assert resp.status_code == 200, resp.text
    assert applications_resp.status_code == 200, applications_resp.text
    event = applications_resp.json()["applications"][0]
    assert event["proposal_id"] == "proposal-1"
    assert event["action"] == "apply"
    assert event["status"] == "succeeded"
    assert event["path"] == ".agent-collab/team_notes.md"
    assert event["content_sha256"] == content_hash
    assert event["error"] is None
    assert event["result"]["already_present"] is False
    assert event["result"]["bytes_written"] > 0


def test_project_self_improvement_proposal_apply_records_failed_application_event(client, tmp_path):
    name = "self-improvement-apply-event-failed"
    project = _create_project(client, tmp_path, name=name)
    proposal = _proposal(project["id"], target_kind="project_memory", status="accepted")
    _seed_proposal(proposal)

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/apply",
        json={"content_sha256": "0" * 64},
    )
    applications_resp = client.get(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/applications"
    )

    assert resp.status_code == 409
    assert applications_resp.status_code == 200, applications_resp.text
    event = applications_resp.json()["applications"][0]
    assert event["action"] == "apply"
    assert event["status"] == "failed"
    assert event["content_sha256"] == "0" * 64
    assert "hash" in event["error"]
    proposals = client.get(f"/api/codex/projects/{project['id']}/self-improvement-proposals").json()["proposals"]
    assert proposals[0]["status"] == "accepted"


def test_project_self_improvement_proposal_rollback_removes_memory_block_and_marks_accepted(client, tmp_path):
    name = "self-improvement-rollback-success"
    project = _create_project(client, tmp_path, name=name)
    proposal = _proposal(project["id"], target_kind="project_memory", status="applied")
    content = build_self_improvement_apply_plan(proposal)["candidate_changes"][0]["content"]
    _seed_proposal(proposal)
    memory_path = tmp_path / name / ".agent-collab" / "team_notes.md"
    memory_path.parent.mkdir()
    memory_path.write_text("Intro note\n\n" + content, encoding="utf-8")

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/rollback"
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    memory_content = memory_path.read_text(encoding="utf-8")
    assert body["proposal"]["status"] == "accepted"
    assert body["rollback"]["path"] == ".agent-collab/team_notes.md"
    assert body["rollback"]["already_absent"] is False
    assert body["rollback"]["content_sha256"] == hash_apply_candidate_content(content)
    assert "self-improvement-proposal:proposal-1" not in memory_content
    assert "Intro note" in memory_content

    event = client.get(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/applications"
    ).json()["applications"][0]
    assert event["action"] == "rollback"
    assert event["status"] == "succeeded"
    assert event["result"]["already_absent"] is False


def test_project_self_improvement_proposal_rollback_is_idempotent_when_marker_absent(client, tmp_path):
    name = "self-improvement-rollback-idempotent"
    project = _create_project(client, tmp_path, name=name)
    proposal = _proposal(project["id"], target_kind="project_memory", status="applied")
    _seed_proposal(proposal)

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/rollback"
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["proposal"]["status"] == "accepted"
    assert body["rollback"]["already_absent"] is True
    assert body["rollback"]["content_sha256"] is None
    event = client.get(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/applications"
    ).json()["applications"][0]
    assert event["action"] == "rollback"
    assert event["status"] == "succeeded"
    assert event["result"]["already_absent"] is True


def test_project_self_improvement_proposal_rollback_rejects_non_applied_status_without_status_change(client, tmp_path):
    project = _create_project(client, tmp_path, name="self-improvement-rollback-status")
    _seed_proposal(_proposal(project["id"], target_kind="project_memory", status="accepted"))

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/rollback"
    )

    assert resp.status_code == 409
    assert "applied" in resp.json()["detail"]
    proposals = client.get(f"/api/codex/projects/{project['id']}/self-improvement-proposals").json()["proposals"]
    assert proposals[0]["status"] == "accepted"
    event = client.get(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/applications"
    ).json()["applications"][0]
    assert event["action"] == "rollback"
    assert event["status"] == "failed"
    assert "applied" in event["error"]


def test_project_self_improvement_proposal_rollback_rejects_non_memory_target_without_status_change(client, tmp_path):
    project = _create_project(client, tmp_path, name="self-improvement-rollback-target")
    _seed_proposal(_proposal(project["id"], target_kind="code_spec", status="applied"))

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/rollback"
    )

    assert resp.status_code == 409
    assert "project_memory" in resp.json()["detail"]
    proposals = client.get(f"/api/codex/projects/{project['id']}/self-improvement-proposals").json()["proposals"]
    assert proposals[0]["status"] == "applied"
    event = client.get(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/applications"
    ).json()["applications"][0]
    assert event["action"] == "rollback"
    assert event["status"] == "failed"
    assert "project_memory" in event["error"]


def test_project_self_improvement_proposal_rollback_returns_404_for_unknown_or_cross_project(client, tmp_path):
    source_project = _create_project(client, tmp_path, name="self-improvement-rollback-source")
    other_project = _create_project(client, tmp_path, name="self-improvement-rollback-other")
    _seed_proposal(_proposal(source_project["id"], target_kind="project_memory", status="applied"))

    missing_project_resp = client.post(
        "/api/codex/projects/missing-project/self-improvement-proposals/proposal-1/rollback"
    )
    missing_proposal_resp = client.post(
        f"/api/codex/projects/{source_project['id']}/self-improvement-proposals/missing/rollback"
    )
    cross_project_resp = client.post(
        f"/api/codex/projects/{other_project['id']}/self-improvement-proposals/proposal-1/rollback"
    )

    assert missing_project_resp.status_code == 404
    assert missing_project_resp.json()["detail"] == "Project not found"
    assert missing_proposal_resp.status_code == 404
    assert missing_proposal_resp.json()["detail"] == "Self-improvement proposal not found"
    assert cross_project_resp.status_code == 404
    assert cross_project_resp.json()["detail"] == "Self-improvement proposal not found"


def test_project_self_improvement_proposal_rollback_returns_500_for_unavailable_repo_without_status_change(
    client,
    tmp_path,
):
    name = "self-improvement-rollback-missing-repo"
    project = _create_project(client, tmp_path, name=name)
    _seed_proposal(_proposal(project["id"], target_kind="project_memory", status="applied"))
    shutil.rmtree(tmp_path / name)

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/rollback"
    )

    assert resp.status_code == 500
    assert "repository path" in resp.json()["detail"]
    proposals = client.get(f"/api/codex/projects/{project['id']}/self-improvement-proposals").json()["proposals"]
    assert proposals[0]["status"] == "applied"
    event = client.get(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/applications"
    ).json()["applications"][0]
    assert event["action"] == "rollback"
    assert event["status"] == "failed"
    assert "repository path" in event["error"]


def test_project_self_improvement_proposal_rollback_returns_503_when_store_unavailable(client, monkeypatch):
    from app.interfaces import api as api_module

    monkeypatch.setattr(api_module, "codex_store", None)

    resp = client.post("/api/codex/projects/project-1/self-improvement-proposals/proposal-1/rollback")

    assert resp.status_code == 503
    assert resp.json()["detail"] == "SQLite store not available"
