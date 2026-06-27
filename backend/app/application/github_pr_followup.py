from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable, Protocol  # noqa: UP035

from app.domain.models import CodexIssue


class GitHubPRFollowupError(Exception):
    def __init__(self, message: str, *, status: str = "failed") -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class CompletedProcessLike(Protocol):
    returncode: int
    stdout: str
    stderr: str


class GitHubPRFollowupStore(Protocol):
    async def load_codex_issue(self, issue_id: str) -> CodexIssue | None: ...
    async def save_codex_issue(self, issue: CodexIssue) -> None: ...
    async def list_codex_issues(
        self, session_id: str | None = None, project_id: str | None = None
    ) -> list[dict[str, object]]: ...
    async def list_codex_tasks(
        self, session_id: str | None = None, issue_id: str | None = None
    ) -> list[dict[str, object]]: ...
    async def load_codex_task(self, task_id: str) -> object | None: ...
    async def save_codex_task(self, task: object) -> None: ...
    async def append_project_audit(
        self,
        *,
        project_id: str | None,
        issue_id: str | None,
        event: str,
        sha: str | None = None,
        base_branch: str | None = None,
    ) -> None: ...


class EventBusLike(Protocol):
    async def append(self, event: dict[str, object]) -> None: ...


@dataclass
class GitHubPRFollowupStatus:
    configured: bool = True
    running: bool = False
    sweep_count: int = 0
    last_started_at: datetime | None = None
    last_completed_at: datetime | None = None
    last_error: str | None = None
    last_summary_counts: dict[str, int] = field(default_factory=dict)
    auto_merge_enabled: bool = False

    def mark_started(self, *, auto_merge: bool) -> None:
        self.configured = True
        self.running = True
        self.last_started_at = datetime.now()
        self.auto_merge_enabled = auto_merge

    def mark_completed(self, summary: GitHubPRFollowupSummary) -> None:
        self.running = False
        self.sweep_count += 1
        self.last_completed_at = datetime.now()
        self.last_error = None
        self.last_summary_counts = summary.counts

    def mark_failed(self, exc: Exception) -> None:
        self.running = False
        self.sweep_count += 1
        self.last_completed_at = datetime.now()
        self.last_error = f"{type(exc).__name__}: {exc}"
        self.last_summary_counts = {}

    def to_dict(self) -> dict[str, object]:
        return {
            "configured": self.configured,
            "running": self.running,
            "sweep_count": self.sweep_count,
            "last_started_at": self.last_started_at.isoformat() if self.last_started_at else None,
            "last_completed_at": self.last_completed_at.isoformat()
            if self.last_completed_at
            else None,
            "last_error": self.last_error,
            "last_summary_counts": dict(self.last_summary_counts),
            "auto_merge_enabled": self.auto_merge_enabled,
        }


_followup_status = GitHubPRFollowupStatus()


def reset_github_pr_followup_status() -> None:
    global _followup_status
    _followup_status = GitHubPRFollowupStatus()


def get_github_pr_followup_status() -> dict[str, object]:
    return _followup_status.to_dict()


@dataclass(frozen=True)
class GitHubPRFollowupResult:
    issue_id: str
    status: str
    github_pr_state: str | None = None
    message: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "issue_id": self.issue_id,
            "status": self.status,
            "github_pr_state": self.github_pr_state,
            "message": self.message,
            "error": self.error,
        }


@dataclass(frozen=True)
class GitHubPRFollowupSummary:
    project_id: str
    results: list[GitHubPRFollowupResult] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for result in self.results:
            counts[result.status] = counts.get(result.status, 0) + 1
        return counts

    def to_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "counts": self.counts,
            "results": [result.to_dict() for result in self.results],
        }


async def _append_event(event_bus: EventBusLike | None, event: dict[str, object]) -> None:
    if event_bus is not None:
        await event_bus.append(event)


async def _append_audit(
    store: GitHubPRFollowupStore,
    issue: CodexIssue,
    *,
    event: str,
) -> None:
    await store.append_project_audit(
        project_id=issue.project_id,
        issue_id=issue.id,
        event=event,
        base_branch=issue.git_base_branch,
    )


async def _record_failed_followup(
    issue: CodexIssue,
    *,
    store: GitHubPRFollowupStore,
    event_bus: EventBusLike | None,
    error: str,
) -> GitHubPRFollowupResult:
    result = GitHubPRFollowupResult(issue_id=issue.id, status="failed", error=error)
    await _append_audit(store, issue, event="github_pr_followup_failed")
    await _append_event(
        event_bus,
        {"type": "issue_pr_followup", "issue_id": issue.id, "status": "failed", "error": error},
    )
    return result


def _parse_pr_view(stdout: str) -> dict[str, object]:
    try:
        decoded = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise GitHubPRFollowupError("gh pr view returned non-JSON") from exc
    if not isinstance(decoded, dict):
        raise GitHubPRFollowupError("gh pr view returned an unexpected JSON shape")
    return decoded


def _latest_review_body(data: dict[str, object]) -> str:
    reviews = data.get("reviews")
    if not isinstance(reviews, list) or not reviews:
        return ""
    latest = reviews[-1]
    if not isinstance(latest, dict):
        return ""
    body = latest.get("body")
    return body if isinstance(body, str) else ""


def _failed_check_names(data: dict[str, object]) -> list[str]:
    rollup = data.get("statusCheckRollup")
    if not isinstance(rollup, list):
        return []
    failed: list[str] = []
    for raw in rollup:
        if not isinstance(raw, dict):
            continue
        conclusion = str(raw.get("conclusion") or "").upper()
        status = str(raw.get("status") or "").upper()
        if status == "COMPLETED" and conclusion not in {"", "SUCCESS", "SKIPPED", "NEUTRAL"}:
            failed.append(str(raw.get("name") or raw.get("workflowName") or "unknown check"))
    return failed


def _has_status_checks(data: dict[str, object]) -> bool:
    rollup = data.get("statusCheckRollup")
    return isinstance(rollup, list) and bool(rollup)


def _pending_check_names(data: dict[str, object]) -> list[str]:
    rollup = data.get("statusCheckRollup")
    if not isinstance(rollup, list):
        return []
    pending: list[str] = []
    for raw in rollup:
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status") or "").upper()
        if status and status != "COMPLETED":
            pending.append(str(raw.get("name") or raw.get("workflowName") or "unknown check"))
    return pending


def _is_mergeable_status(value: object) -> bool:
    return str(value or "").upper() in {"CLEAN", "HAS_HOOKS", "UNSTABLE"}


async def _enqueue_engineer_rework(
    issue: CodexIssue,
    *,
    store: GitHubPRFollowupStore,
    event_bus: EventBusLike | None,
    review_body: str,
) -> bool:
    if not review_body.strip():
        return False
    tasks = await store.list_codex_tasks(issue_id=issue.id)
    engineer_tasks = [task for task in tasks if task.get("role") == "engineer"]
    if not engineer_tasks:
        return False
    task_id = str(engineer_tasks[-1].get("id") or "")
    if not task_id:
        return False
    engineer = await store.load_codex_task(task_id)
    if engineer is None:
        return False
    setattr(engineer, "status", "pending")  # noqa: B010
    setattr(  # noqa: B010
        engineer,
        "review_comment",
        "GitHub PR review requested changes. Address the feedback below "
        "before re-submitting.\n\n" + review_body,
    )
    setattr(engineer, "updated_at", datetime.now())  # noqa: B010
    await store.save_codex_task(engineer)
    await _append_event(
        event_bus,
        {
            "type": "task_status",
            "task_id": getattr(engineer, "id", task_id),
            "issue_id": getattr(engineer, "issue_id", issue.id),
            "session_id": getattr(engineer, "session_id", issue.session_id),
            "status": "pending",
        },
    )
    return True


async def refresh_issue_github_pr(
    issue_id: str,
    *,
    store: GitHubPRFollowupStore,
    event_bus: EventBusLike | None,
    run_subprocess: Callable[..., Awaitable[CompletedProcessLike]],
    auto_merge: bool = False,
) -> GitHubPRFollowupResult:
    issue = await store.load_codex_issue(issue_id)
    if issue is None:
        raise GitHubPRFollowupError("Issue not found", status="not_found")
    if not issue.github_pr_url:
        raise GitHubPRFollowupError("Issue has no PR yet", status="no_pr")

    try:
        view = await run_subprocess(
            [
                "gh",
                "pr",
                "view",
                issue.github_pr_url,
                "--json",
                "state,reviewDecision,reviews,mergeStateStatus,statusCheckRollup",
            ],
            cwd=issue.git_worktree_path or ".",
            timeout_s=30,
        )
    except Exception as exc:  # noqa: BLE001, RUF100
        return await _record_failed_followup(
            issue,
            store=store,
            event_bus=event_bus,
            error=f"gh pr view failed: {exc}",
        )
    if view.returncode != 0:
        return await _record_failed_followup(
            issue,
            store=store,
            event_bus=event_bus,
            error=f"gh pr view failed: {view.stderr.strip()[:500]}",
        )

    try:
        data = _parse_pr_view(view.stdout)
    except GitHubPRFollowupError as exc:
        return await _record_failed_followup(
            issue,
            store=store,
            event_bus=event_bus,
            error=exc.message,
        )
    state = str(data.get("state") or "OPEN")
    decision = str(data.get("reviewDecision") or "")
    merge_state = str(data.get("mergeStateStatus") or "")
    pr_state = f"{state}:{decision}"
    issue.github_pr_state = pr_state

    status = "updated"
    message = ""
    if state == "MERGED":
        issue.git_merge_status = "merged"
        issue.status = "completed"
        status = "merged"
    elif decision == "CHANGES_REQUESTED":
        await _enqueue_engineer_rework(
            issue,
            store=store,
            event_bus=event_bus,
            review_body=_latest_review_body(data),
        )
        status = "changes_requested"
    else:
        failed_checks = _failed_check_names(data)
        if failed_checks:
            status = "checks_failed"
            message = "Failed status checks: " + ", ".join(failed_checks)
        else:
            pending_checks = _pending_check_names(data)
            if pending_checks:
                status = "checks_pending"
                message = "Pending status checks: " + ", ".join(pending_checks)
            elif auto_merge and not _has_status_checks(data):
                status = "checks_missing"
                message = "No status checks reported; auto-merge requires completed checks."
            elif auto_merge:
                if decision != "APPROVED":
                    status = "review_required"
                    message = "PR is not approved."
                elif not _is_mergeable_status(merge_state):
                    status = "merge_blocked"
                    message = f"PR merge state is {merge_state or 'unknown'}."
                else:
                    try:
                        merge = await run_subprocess(
                            [
                                "gh",
                                "pr",
                                "merge",
                                issue.github_pr_url,
                                "--merge",
                                "--delete-branch",
                            ],
                            cwd=issue.git_worktree_path or ".",
                            timeout_s=60,
                        )
                    except Exception as exc:  # noqa: BLE001, RUF100
                        status = "merge_failed"
                        message = f"gh pr merge failed: {exc}"
                    else:
                        if merge.returncode != 0:
                            status = "merge_failed"
                            message = f"gh pr merge failed: {merge.stderr.strip()[:500]}"
                        else:
                            issue.git_merge_status = "merged"
                            issue.status = "completed"
                            status = "merged"
                            message = "PR merged by automated follow-up."

    issue.updated_at = datetime.now()
    await store.save_codex_issue(issue)
    await _append_audit(store, issue, event=f"github_pr_followup_{status}")
    await _append_event(
        event_bus,
        {
            "type": "issue_pr_followup",
            "issue_id": issue.id,
            "status": status,
            "github_pr_state": pr_state,
            "message": message,
        },
    )
    return GitHubPRFollowupResult(
        issue_id=issue.id,
        status=status,
        github_pr_state=pr_state,
        message=message,
        error=message if status in {"merge_failed"} else "",
    )


async def sweep_project_github_prs(
    project_id: str,
    *,
    store: GitHubPRFollowupStore,
    event_bus: EventBusLike | None,
    run_subprocess: Callable[..., Awaitable[CompletedProcessLike]],
    auto_merge: bool = False,
) -> GitHubPRFollowupSummary:
    _followup_status.mark_started(auto_merge=auto_merge)
    try:
        issue_rows = await store.list_codex_issues(project_id=project_id)
        results: list[GitHubPRFollowupResult] = []
        for row in issue_rows:
            issue_id = str(row.get("id") or "")
            if not issue_id:
                continue
            if not row.get("github_pr_url"):
                continue
            if str(row.get("git_merge_status") or "open") == "merged":
                continue
            try:
                result = await refresh_issue_github_pr(
                    issue_id,
                    store=store,
                    event_bus=event_bus,
                    run_subprocess=run_subprocess,
                    auto_merge=auto_merge,
                )
            except GitHubPRFollowupError as exc:
                result = GitHubPRFollowupResult(
                    issue_id=issue_id, status=exc.status, error=exc.message
                )
            results.append(result)
        summary = GitHubPRFollowupSummary(project_id=project_id, results=results)
        await _append_event(
            event_bus,
            {
                "type": "project_pr_followup_sweep",
                "project_id": project_id,
                "counts": summary.counts,
            },
        )
    except Exception as exc:  # noqa: BLE001, RUF100
        _followup_status.mark_failed(exc)
        raise
    _followup_status.mark_completed(summary)
    return summary
