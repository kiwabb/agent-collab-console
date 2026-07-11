from __future__ import annotations

from datetime import datetime
from typing import cast

import pytest

from app.application.role_workflow_service import RoleWorkflowService, RoleWorkflowStore
from app.domain.models import CodexIssue, CodexTask


class _IssueStore:
    def __init__(self, issue: CodexIssue) -> None:
        self.issue = issue

    async def load_codex_issue(self, issue_id: str) -> CodexIssue | None:
        assert issue_id == self.issue.id
        return self.issue


@pytest.mark.asyncio
async def test_role_workflow_loads_authoritative_criteria_for_qa_prompt(tmp_path):
    issue = CodexIssue(
        id="issue-criteria",
        session_id="workspace-criteria",
        title="Secure local API",
        description="Require local authentication",
        acceptance_criteria=["Anonymous requests return 401"],
        acceptance_criteria_confirmed=True,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    task = CodexTask(
        id="qa-criteria",
        session_id=issue.session_id,
        issue_id=issue.id,
        title=issue.title,
        prompt="Verify the implementation",
        role="qa",
        executor="codex",
        status="pending",
        workspace_path=str(tmp_path),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    service = RoleWorkflowService(
        codex_store=cast(RoleWorkflowStore, _IssueStore(issue))
    )

    prompt = await service.build_prompt(task)

    assert prompt is not None
    assert "AUTHORITATIVE ACCEPTANCE CRITERIA" in prompt
    assert "Anonymous requests return 401" in prompt
