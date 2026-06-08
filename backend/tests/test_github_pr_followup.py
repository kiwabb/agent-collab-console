from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

import pytest

import app.interfaces.api as api_module
from app.application.github_pr_followup import (
    refresh_issue_github_pr,
    sweep_project_github_prs,
)
from app.domain.models import CodexIssue, CodexTask


@dataclass
class _Proc:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class _Store:
    def __init__(
        self,
        *,
        issues: list[CodexIssue],
        tasks: list[CodexTask] | None = None,
    ) -> None:
        self.issues = {issue.id: issue for issue in issues}
        self.tasks = {task.id: task for task in (tasks or [])}
        self.saved_issues: list[CodexIssue] = []
        self.saved_tasks: list[CodexTask] = []
        self.audit_events: list[dict[str, str | None]] = []

    async def load_codex_issue(self, issue_id: str) -> CodexIssue | None:
        return self.issues.get(issue_id)

    async def save_codex_issue(self, issue: CodexIssue) -> None:
        self.issues[issue.id] = issue
        self.saved_issues.append(issue)

    async def list_codex_issues(self, project_id: str | None = None, **kwargs) -> list[dict[str, object]]:
        issues = list(self.issues.values())
        if project_id is not None:
            issues = [issue for issue in issues if issue.project_id == project_id]
        return [issue.model_dump() for issue in issues]

    async def list_codex_tasks(self, issue_id: str | None = None, **kwargs) -> list[dict[str, object]]:
        tasks = list(self.tasks.values())
        if issue_id is not None:
            tasks = [task for task in tasks if task.issue_id == issue_id]
        return [task.model_dump() for task in tasks]

    async def load_codex_task(self, task_id: str) -> CodexTask | None:
        return self.tasks.get(task_id)

    async def save_codex_task(self, task: CodexTask) -> None:
        self.tasks[task.id] = task
        self.saved_tasks.append(task)

    async def append_project_audit(
        self,
        *,
        project_id: str | None,
        issue_id: str | None,
        event: str,
        sha: str | None = None,
        base_branch: str | None = None,
    ) -> None:
        self.audit_events.append(
            {
                "project_id": project_id,
                "issue_id": issue_id,
                "event": event,
                "sha": sha,
                "base_branch": base_branch,
            }
        )


class _EventBus:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def append(self, event: dict[str, object]) -> None:
        self.events.append(event)


def _issue(issue_id: str, **overrides) -> CodexIssue:
    data = {
        "id": issue_id,
        "session_id": "session-1",
        "project_id": "project-1",
        "title": f"Issue {issue_id}",
        "description": "desc",
        "status": "awaiting_merge",
        "git_branch": f"codex/{issue_id}",
        "git_base_branch": "main",
        "git_worktree_path": "/tmp/worktree",
        "git_merge_status": "open",
        "github_pr_url": f"https://github.com/acme/repo/pull/{issue_id[-1]}",
        "github_pr_state": "OPEN:REVIEW_REQUIRED",
        "created_at": datetime(2026, 6, 8, 10, 0, 0),
        "updated_at": datetime(2026, 6, 8, 10, 0, 0),
    }
    data.update(overrides)
    return CodexIssue(**data)


def _task(task_id: str, *, issue_id: str, role: str = "engineer", status: str = "done") -> CodexTask:
    return CodexTask(
        id=task_id,
        session_id="session-1",
        project_id="project-1",
        issue_id=issue_id,
        title=f"Task {task_id}",
        prompt="do work",
        role=role,
        status=status,
        updated_at=datetime(2026, 6, 8, 10, 0, 0),
    )


def _gh_payload(
    *,
    state: str = "OPEN",
    decision: str = "",
    reviews: list[dict[str, object]] | None = None,
    checks: list[dict[str, object]] | None = None,
) -> str:
    return json.dumps(
        {
            "state": state,
            "reviewDecision": decision,
            "reviews": reviews or [],
            "mergeStateStatus": "CLEAN",
            "statusCheckRollup": checks or [],
        }
    )


@pytest.mark.asyncio
async def test_refresh_marks_remote_merged_pr_completed_and_audits():
    issue = _issue("issue-1")
    store = _Store(issues=[issue])
    bus = _EventBus()

    async def run_subprocess(args: list[str], *, cwd: str, timeout_s: int = 30) -> _Proc:
        assert args[:3] == ["gh", "pr", "view"]
        return _Proc(0, stdout=_gh_payload(state="MERGED", decision="APPROVED"))

    result = await refresh_issue_github_pr(
        issue.id,
        store=store,
        event_bus=bus,
        run_subprocess=run_subprocess,
    )

    assert result.status == "merged"
    assert result.github_pr_state == "MERGED:APPROVED"
    assert store.saved_issues[-1].git_merge_status == "merged"
    assert store.saved_issues[-1].status == "completed"
    assert store.audit_events[-1]["event"] == "github_pr_followup_merged"
    assert bus.events[-1]["type"] == "issue_pr_followup"
    assert bus.events[-1]["status"] == "merged"


@pytest.mark.asyncio
async def test_refresh_changes_requested_requeues_latest_engineer_task():
    issue = _issue("issue-2")
    older = _task("eng-older", issue_id=issue.id)
    latest = _task("eng-latest", issue_id=issue.id)
    store = _Store(issues=[issue], tasks=[older, latest])
    bus = _EventBus()

    async def run_subprocess(args: list[str], *, cwd: str, timeout_s: int = 30) -> _Proc:
        return _Proc(
            0,
            stdout=_gh_payload(
                decision="CHANGES_REQUESTED",
                reviews=[
                    {"body": "first review"},
                    {"body": "please add a regression test"},
                ],
            ),
        )

    result = await refresh_issue_github_pr(
        issue.id,
        store=store,
        event_bus=bus,
        run_subprocess=run_subprocess,
    )

    assert result.status == "changes_requested"
    assert store.saved_tasks[-1].id == "eng-latest"
    assert store.saved_tasks[-1].status == "pending"
    assert "please add a regression test" in (store.saved_tasks[-1].review_comment or "")
    assert store.audit_events[-1]["event"] == "github_pr_followup_changes_requested"
    assert any(event.get("type") == "task_status" and event.get("status") == "pending" for event in bus.events)


@pytest.mark.asyncio
async def test_refresh_failed_status_check_records_checks_failed():
    issue = _issue("issue-5")
    store = _Store(issues=[issue])
    bus = _EventBus()

    async def run_subprocess(args: list[str], *, cwd: str, timeout_s: int = 30) -> _Proc:
        assert "statusCheckRollup" in args[-1]
        return _Proc(
            0,
            stdout=_gh_payload(
                state="OPEN",
                decision="APPROVED",
                checks=[{"name": "Backend tests", "status": "COMPLETED", "conclusion": "FAILURE"}],
            ),
        )

    result = await refresh_issue_github_pr(
        issue.id,
        store=store,
        event_bus=bus,
        run_subprocess=run_subprocess,
    )

    assert result.status == "checks_failed"
    assert "Backend tests" in result.message
    assert store.audit_events[-1]["event"] == "github_pr_followup_checks_failed"
    assert bus.events[-1]["status"] == "checks_failed"


@pytest.mark.asyncio
async def test_sweep_project_prs_isolates_issue_failures_and_continues():
    broken = _issue("issue-1", github_pr_url="https://github.com/acme/repo/pull/1")
    healthy = _issue("issue-2", github_pr_url="https://github.com/acme/repo/pull/2")
    ignored = _issue("issue-3", github_pr_url=None)
    store = _Store(issues=[broken, healthy, ignored])
    bus = _EventBus()

    async def run_subprocess(args: list[str], *, cwd: str, timeout_s: int = 30) -> _Proc:
        if args[3].endswith("/1"):
            return _Proc(1, stderr="network unavailable")
        return _Proc(0, stdout=_gh_payload(state="OPEN", decision="APPROVED"))

    summary = await sweep_project_github_prs(
        "project-1",
        store=store,
        event_bus=bus,
        run_subprocess=run_subprocess,
    )

    assert [result.issue_id for result in summary.results] == ["issue-1", "issue-2"]
    assert [result.status for result in summary.results] == ["failed", "updated"]
    assert summary.counts == {"failed": 1, "updated": 1}
    assert store.saved_issues[-1].id == "issue-2"
    assert store.saved_issues[-1].github_pr_state == "OPEN:APPROVED"
    assert [event["event"] for event in store.audit_events] == [
        "github_pr_followup_failed",
        "github_pr_followup_updated",
    ]


@pytest.mark.asyncio
async def test_refresh_bad_gh_json_is_audited_failure_not_exception():
    issue = _issue("issue-4")
    store = _Store(issues=[issue])
    bus = _EventBus()

    async def run_subprocess(args: list[str], *, cwd: str, timeout_s: int = 30) -> _Proc:
        return _Proc(0, stdout="not json")

    result = await refresh_issue_github_pr(
        issue.id,
        store=store,
        event_bus=bus,
        run_subprocess=run_subprocess,
    )

    assert result.status == "failed"
    assert "non-JSON" in result.error
    assert store.audit_events[-1]["event"] == "github_pr_followup_failed"
    assert bus.events[-1]["status"] == "failed"


@pytest.mark.asyncio
async def test_project_followup_endpoint_returns_best_effort_summary(monkeypatch):
    broken = _issue("issue-1", github_pr_url="https://github.com/acme/repo/pull/1")
    healthy = _issue("issue-2", github_pr_url="https://github.com/acme/repo/pull/2")
    store = _Store(issues=[broken, healthy])

    async def run_subprocess(args: list[str], *, cwd: str, timeout_s: int = 30) -> _Proc:
        if args[3].endswith("/1"):
            return _Proc(1, stderr="network unavailable")
        return _Proc(0, stdout=_gh_payload(state="OPEN", decision="APPROVED"))

    monkeypatch.setattr(api_module, "codex_store", store)
    monkeypatch.setattr(api_module, "event_bus", _EventBus())
    monkeypatch.setattr(api_module, "_run_subprocess", run_subprocess)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/gh" if name == "gh" else None)

    payload = await api_module.follow_up_project_github_prs("project-1")

    assert payload["project_id"] == "project-1"
    assert payload["counts"] == {"failed": 1, "updated": 1}
    assert [result["status"] for result in payload["results"]] == ["failed", "updated"]
