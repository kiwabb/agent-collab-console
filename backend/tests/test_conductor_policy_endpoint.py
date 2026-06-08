from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException

import app.interfaces.api as api_module
from app.domain.models import CodexIssue


EXPECTED_FIELDS = {
    "issue_id",
    "recommendation",
    "batch_allowed",
    "signals",
    "guidance",
}


class _PolicyStoreStub:
    def __init__(self, issue: CodexIssue | None):
        self.issue = issue

    async def load_codex_issue(self, issue_id: str):
        if self.issue is not None and issue_id == self.issue.id:
            return self.issue
        return None


def _make_issue(title: str, description: str | None) -> CodexIssue:
    now = datetime.now()
    return CodexIssue(
        id=str(uuid4()),
        session_id="sess-policy-panel",
        project_id="proj-policy-panel",
        title=title,
        description=description,
        status="open",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_policy_endpoint_returns_single_engineer_for_trivial_issue(monkeypatch):
    issue = _make_issue("Fix typo", "Change one string in README.md.")
    monkeypatch.setattr(api_module, "codex_store", _PolicyStoreStub(issue))

    result = await api_module.get_issue_orchestration_policy(issue.id)

    assert set(result.keys()) == EXPECTED_FIELDS
    assert result["issue_id"] == issue.id
    assert result["recommendation"] == "single_engineer"
    assert result["batch_allowed"] is False
    assert "trivial" in result["signals"]
    assert result["guidance"]


@pytest.mark.asyncio
async def test_policy_endpoint_allows_explicit_independent_parallel_issue(monkeypatch):
    issue = _make_issue(
        "REAL run: three tiny independent modules in parallel",
        (
            "Create alpha.py, beta.py, and gamma.py independently. "
            "Dispatch all three engineers in parallel as one batch."
        ),
    )
    monkeypatch.setattr(api_module, "codex_store", _PolicyStoreStub(issue))

    result = await api_module.get_issue_orchestration_policy(issue.id)

    assert result["recommendation"] == "batch_allowed"
    assert result["batch_allowed"] is True
    assert "explicit_parallel" in result["signals"]
    assert "independent_slices" in result["signals"]


@pytest.mark.asyncio
async def test_policy_endpoint_404_when_issue_missing(monkeypatch):
    monkeypatch.setattr(api_module, "codex_store", _PolicyStoreStub(issue=None))

    with pytest.raises(HTTPException) as exc:
        await api_module.get_issue_orchestration_policy("missing")

    assert exc.value.status_code == 404
    assert "missing" in exc.value.detail


@pytest.mark.asyncio
async def test_policy_endpoint_503_when_store_unavailable(monkeypatch):
    monkeypatch.setattr(api_module, "codex_store", None)

    with pytest.raises(HTTPException) as exc:
        await api_module.get_issue_orchestration_policy("any")

    assert exc.value.status_code == 503
