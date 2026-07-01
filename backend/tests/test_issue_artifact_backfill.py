import json  # noqa: I001
from datetime import datetime

import pytest

from app.domain.models import CodexIssue, CodexSession, CodexTask
import app.interfaces.api as api_module


class ArtifactBackfillStoreStub:
    def __init__(self, issue: CodexIssue, task: CodexTask, workspace: CodexSession):
        self.issue = issue
        self.task = task
        self.workspace = workspace

    async def load_codex_issue(self, issue_id: str):
        return self.issue if issue_id == self.issue.id else None

    async def list_codex_tasks(self, session_id: str | None = None, issue_id: str | None = None):
        if session_id == self.issue.session_id and issue_id == self.issue.id:
            return [
                {
                    "id": self.task.id,
                    "issue_id": self.task.issue_id,
                    "role": self.task.role,
                    "status": self.task.status,
                    "workspace_path": self.task.workspace_path,
                    "updated_at": self.task.updated_at.isoformat()
                    if self.task.updated_at
                    else None,
                    "created_at": self.task.created_at.isoformat()
                    if self.task.created_at
                    else None,
                }
            ]
        return []

    async def load_codex_task(self, task_id: str):
        return self.task if task_id == self.task.id else None

    async def load_codex_workspace(self, workspace_id: str):
        return self.workspace if workspace_id == self.workspace.id else None

    async def list_artifacts(self, issue_id: str) -> list[dict]:
        return []

    async def save_artifact(self, artifact: dict) -> None:
        pass


@pytest.mark.asyncio
async def test_issue_artifacts_backfill_missing_prd_files(monkeypatch, tmp_path):
    now = datetime.now()
    issue = CodexIssue(
        id="issue-1",
        session_id="workspace-1",
        title="Need PRD",
        current_phase="requirements",
        status="open",
        created_at=now,
        updated_at=now,
    )
    workspace = CodexSession(
        id="workspace-1",
        title="Demo Workspace",
        cwd=str(tmp_path),
        created_at=now,
        last_active_at=now,
    )
    issue_root = tmp_path / "issues" / issue.id
    pm_dir = issue_root / "pm"
    pm_dir.mkdir(parents=True, exist_ok=True)
    (pm_dir / "requirement.md").write_text("# Requirement\n", encoding="utf-8")
    task_title = "需求 - 1+1"

    task = CodexTask(
        id="task-1",
        session_id=workspace.id,
        issue_id=issue.id,
        title=task_title,
        prompt="写一个简单需求",
        role="product_manager",
        executor="codex",
        status="done",
        result=json.dumps(
            {
                "language": "zh-CN",
                "project_name": "Demo Workspace",
                "issue_id": issue.id,
                "issue_title": task_title,
                "original_requirements": "写一个简单需求",
                "product_goals": ["目标1"],
                "user_stories": ["用户故事1"],
                "requirement_analysis": "分析内容",
                "requirement_pool": [{"priority": "P0", "title": "需求1", "description": "描述1"}],
                "acceptance_criteria": ["验收1"],
                "constraints": [],
                "open_questions": [],
                "risks": [],
            }
        ),
        workspace_path=str(tmp_path),
        created_at=now,
        updated_at=now,
    )

    monkeypatch.setattr(
        api_module, "codex_store", ArtifactBackfillStoreStub(issue, task, workspace)
    )

    artifacts = await api_module.get_codex_issue_artifacts(issue.id)

    names = {artifact["name"] for artifact in artifacts}
    assert "pm/prd.json" in names
    assert "pm/prd.md" in names
    assert (pm_dir / "prd.json").exists()
    assert (pm_dir / "prd.md").exists()
    assert task_title in (pm_dir / "prd.md").read_text(encoding="utf-8")
