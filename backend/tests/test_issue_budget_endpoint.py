"""Tests for GET /api/codex/issues/{id}/budget.

Covers the three branches called out in the task ADR:
  - ceiling issue (explicit budget_usd > 0)
  - unlimited issue (budget_usd <= 0)
  - missing issue (404)

Also pins the field shape so the frontend type contract is stable.
"""

from __future__ import annotations  # noqa: I001

from datetime import datetime
from uuid import uuid4

import pytest

import app.interfaces.api as api_module
from app.domain.models import CodexIssue, CodexTask, ExecutionProcess


# ---------------------------------------------------------------------------
# Store stub: real AsyncSQLiteStore is heavy; a tiny in-memory stub is enough
# for the endpoint logic. Tests of the *aggregation* itself live in
# test_issue_budget.py and exercise the real store.
# ---------------------------------------------------------------------------


class _BudgetStoreStub:
    """Stubs just enough of the store surface for the new endpoint."""

    def __init__(
        self,
        issue: CodexIssue | None,
        tasks: list[CodexTask] | None = None,
        processes: list[ExecutionProcess] | None = None,
    ):
        self.issue = issue
        self.tasks = tasks or []
        self.processes = processes or []

    async def load_codex_issue(self, issue_id: str):
        if self.issue is not None and issue_id == self.issue.id:
            return self.issue
        return None

    async def list_codex_tasks(self, issue_id: str | None = None, **kwargs):
        if issue_id is None:
            return list(self.tasks)
        return [t for t in self.tasks if t.issue_id == issue_id]

    async def list_execution_processes(self, task_id: str, **kwargs):
        return [p for p in self.processes if p.task_id == task_id]


def _make_issue(budget_usd: float | None) -> CodexIssue:
    now = datetime.now()
    return CodexIssue(
        id=str(uuid4()),
        session_id="sess-budget-ep",
        project_id="proj-budget-ep",
        title="Budget endpoint test",
        description="desc",
        status="open",
        budget_usd=budget_usd,
        created_at=now,
        updated_at=now,
    )


def _proc(task_id: str, status: str, cost: float | None) -> ExecutionProcess:
    now = datetime.now()
    return ExecutionProcess(
        id=f"ep-{status}-{task_id}",
        task_id=task_id,
        session_id="sess-budget-ep",
        status=status,
        total_cost_usd=cost,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Field shape (frontend type contract)
# ---------------------------------------------------------------------------


EXPECTED_FIELDS = {
    "issue_id",
    "spent_usd",
    "reserved_usd",
    "effective_spend_usd",
    "budget_usd",
    "remaining_usd",
    "used_ratio",
    "soft_warn",
    "over_budget",
    "soft_warn_ratio",
    "has_ceiling",
    "budget_source",
}


def test_budget_status_dict_has_stable_shape():
    """Pin the JSON shape so a frontend type contract change is a deliberate edit."""
    from app.application.budget_service import IssueBudgetStatus

    status = IssueBudgetStatus(
        issue_id="i",
        spent_usd=1.0,
        budget_usd=2.0,
        budget_source="issue",
        soft_warn_ratio=0.8,
    )
    payload = status.to_dict()
    assert set(payload.keys()) == EXPECTED_FIELDS
    assert payload["issue_id"] == "i"
    assert payload["has_ceiling"] is True
    assert payload["spent_usd"] == 1.0
    assert payload["reserved_usd"] == 0.0
    assert payload["effective_spend_usd"] == 1.0
    assert payload["budget_usd"] == 2.0
    assert payload["remaining_usd"] == 1.0
    assert payload["used_ratio"] == 0.5
    assert payload["soft_warn"] is False
    assert payload["over_budget"] is False


def test_budget_status_dict_no_ceiling_uses_null_not_zero():
    from app.application.budget_service import IssueBudgetStatus

    status = IssueBudgetStatus(
        issue_id="i",
        spent_usd=3.0,
        budget_usd=0.0,
        budget_source="default",
        soft_warn_ratio=0.8,
    )
    payload = status.to_dict()
    assert payload["has_ceiling"] is False
    assert payload["remaining_usd"] is None
    assert payload["used_ratio"] is None
    # spent is still real money, not None.
    assert payload["spent_usd"] == 3.0


# ---------------------------------------------------------------------------
# Endpoint: ceiling issue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_endpoint_ceiling_issue_returns_aggregated_spend(monkeypatch):
    issue = _make_issue(budget_usd=10.0)
    task = CodexTask(
        id="t-1",
        session_id=issue.session_id,
        project_id=issue.project_id,
        issue_id=issue.id,
        title="impl",
        prompt="do it",
    )
    procs = [
        _proc("t-1", "Completed", 1.50),
        _proc("t-1", "Failed", 0.25),
        _proc("t-1", "Killed", 0.25),
        # Running: NOT counted
        _proc("t-1", "Running", 99.0),
    ]
    monkeypatch.setattr(
        api_module,
        "codex_store",
        _BudgetStoreStub(issue, tasks=[task], processes=procs),
    )

    result = await api_module.get_issue_budget(issue.id)
    assert set(result.keys()) == EXPECTED_FIELDS
    assert result["issue_id"] == issue.id
    assert result["budget_usd"] == 10.0
    assert result["budget_source"] == "issue"
    assert result["has_ceiling"] is True
    assert result["spent_usd"] == pytest.approx(2.0)
    assert result["remaining_usd"] == pytest.approx(8.0)
    assert result["used_ratio"] == pytest.approx(0.2)
    assert result["soft_warn"] is False
    assert result["over_budget"] is False


# ---------------------------------------------------------------------------
# Endpoint: unlimited issue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_endpoint_unlimited_issue_uses_default_budget(monkeypatch):
    """budget_usd unset → resolve to global default; still has_ceiling=True.
    budget_usd explicitly <= 0 → has_ceiling=False (per the Q3 decision in the ADR).
    """
    # Case A: unset budget (None) resolves to a positive global default
    issue = _make_issue(budget_usd=None)
    monkeypatch.setattr(api_module, "codex_store", _BudgetStoreStub(issue))
    result = await api_module.get_issue_budget(issue.id)
    assert result["budget_source"] == "default"
    assert result["has_ceiling"] is True
    assert result["budget_usd"] > 0
    assert result["remaining_usd"] is not None

    # Case B: explicit 0 → no ceiling, derived fields are null
    issue0 = _make_issue(budget_usd=0.0)
    monkeypatch.setattr(api_module, "codex_store", _BudgetStoreStub(issue0))
    result0 = await api_module.get_issue_budget(issue0.id)
    assert result0["budget_source"] == "issue"
    assert result0["has_ceiling"] is False
    assert result0["budget_usd"] == 0.0
    assert result0["remaining_usd"] is None
    assert result0["used_ratio"] is None
    assert result0["soft_warn"] is False
    assert result0["over_budget"] is False


@pytest.mark.asyncio
async def test_endpoint_unlimited_issue_still_reports_spend(monkeypatch):
    """An issue with no ceiling can still show accrued cost; over_budget is false."""
    issue = _make_issue(budget_usd=0.0)
    task = CodexTask(
        id="t-unlim",
        session_id=issue.session_id,
        project_id=issue.project_id,
        issue_id=issue.id,
        title="impl",
        prompt="do it",
    )
    procs = [_proc("t-unlim", "Completed", 7.5)]
    monkeypatch.setattr(
        api_module,
        "codex_store",
        _BudgetStoreStub(issue, tasks=[task], processes=procs),
    )

    result = await api_module.get_issue_budget(issue.id)
    assert result["has_ceiling"] is False
    assert result["spent_usd"] == pytest.approx(7.5)
    # No ceiling → cannot be over budget
    assert result["over_budget"] is False
    assert result["soft_warn"] is False


# ---------------------------------------------------------------------------
# Endpoint: missing issue (404)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_endpoint_404_when_issue_missing(monkeypatch):
    monkeypatch.setattr(api_module, "codex_store", _BudgetStoreStub(issue=None))
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await api_module.get_issue_budget("ghost-id")
    assert exc.value.status_code == 404
    assert "ghost-id" in exc.value.detail


# ---------------------------------------------------------------------------
# Endpoint: store unavailable (503)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_endpoint_503_when_store_unavailable(monkeypatch):
    monkeypatch.setattr(api_module, "codex_store", None)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await api_module.get_issue_budget("any")
    assert exc.value.status_code == 503


# ---------------------------------------------------------------------------
# Thresholds: soft_warn + over_budget actually flip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_endpoint_soft_warn_flips_at_threshold(monkeypatch):
    """At 80% spent the soft_warn flag should be True; over_budget still False."""
    issue = _make_issue(budget_usd=10.0)
    task = CodexTask(
        id="t-warn",
        session_id=issue.session_id,
        project_id=issue.project_id,
        issue_id=issue.id,
        title="impl",
        prompt="do it",
    )
    procs = [_proc("t-warn", "Completed", 8.5)]
    monkeypatch.setattr(
        api_module,
        "codex_store",
        _BudgetStoreStub(issue, tasks=[task], processes=procs),
    )
    result = await api_module.get_issue_budget(issue.id)
    assert result["soft_warn"] is True
    assert result["over_budget"] is False


@pytest.mark.asyncio
async def test_endpoint_over_budget_flips_at_ceiling(monkeypatch):
    """At 100% spent the over_budget flag should be True; soft_warn also True."""
    issue = _make_issue(budget_usd=4.0)
    task = CodexTask(
        id="t-over",
        session_id=issue.session_id,
        project_id=issue.project_id,
        issue_id=issue.id,
        title="impl",
        prompt="do it",
    )
    procs = [_proc("t-over", "Completed", 4.0)]
    monkeypatch.setattr(
        api_module,
        "codex_store",
        _BudgetStoreStub(issue, tasks=[task], processes=procs),
    )
    result = await api_module.get_issue_budget(issue.id)
    assert result["soft_warn"] is True
    assert result["over_budget"] is True
    assert result["remaining_usd"] == pytest.approx(0.0)
