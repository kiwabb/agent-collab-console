"""Engineer workflow tests — covers prompt building, schema validation,
the post-execution git-diff cross-check that downgrades dishonest
'completed' claims to 'partial', and the rework path triggered by an
upstream QA failure (review_comment injection)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from app.application.engineer_workflow import EngineerWorkflow, EngineerWorkflowError


class _FakeTask:
    def __init__(self, *, workspace_path: str, issue_id: str = "issue-1",
                 title: str = "Issue title", prompt: str = "Add /api/ping",
                 result: str = "{}", review_comment: str | None = None):
        self.workspace_path = workspace_path
        self.issue_id = issue_id
        self.id = "task-id"
        self.title = title
        self.prompt = prompt
        self.result = result
        self.review_comment = review_comment


@pytest.fixture
def workspace():
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "issues" / "issue-1").mkdir(parents=True)
        yield td


@pytest.fixture
def workflow():
    return EngineerWorkflow()


def _payload(**overrides):
    base = {
        "language": "en",
        "project_name": "demo",
        "issue_id": "issue-1",
        "issue_title": "Issue title",
        "status": "completed",
        "summary": "Added the ping endpoint and a pytest",
        "changed_files": ["backend/app/api.py", "backend/tests/test_ping.py"],
        "completed_tasks": [],
        "deferred_tasks": [],
        "risks": [],
        "verification_commands": ["pytest -q"],
        "qa_notes": [],
    }
    base.update(overrides)
    return base


def test_build_prompt_basic(workflow, workspace):
    task = _FakeTask(workspace_path=workspace)
    prompt = workflow.build_prompt(task, workspace_title="demo")
    assert "Engineer" in prompt
    assert "Add /api/ping" in prompt
    assert "demo" in prompt
    assert "required_schema" in prompt


def test_build_prompt_rework_includes_review_comment(workflow, workspace):
    task = _FakeTask(
        workspace_path=workspace,
        review_comment="QA failed: pytest exit 1",
    )
    prompt = workflow.build_prompt(task)
    assert "REWORK REQUIRED" in prompt
    assert "QA failed: pytest exit 1" in prompt


def test_persist_result_rejects_empty_result(workflow, workspace):
    task = _FakeTask(workspace_path=workspace, result="")
    with pytest.raises(EngineerWorkflowError, match="empty"):
        workflow.persist_result(task)


def test_persist_result_rejects_invalid_json(workflow, workspace):
    task = _FakeTask(workspace_path=workspace, result="not json")
    with pytest.raises(EngineerWorkflowError, match="not valid JSON"):
        workflow.persist_result(task)


def test_persist_result_writes_implementation_md(workflow, workspace):
    task = _FakeTask(workspace_path=workspace, result=json.dumps(_payload()))
    with mock.patch.object(workflow, "_git_changed_files", return_value=["x.py"]):
        doc = workflow.persist_result(task, workspace_title="demo")
    impl = list((Path(workspace) / "issues" / "issue-1" / "engineer").glob("implementation-*.md"))
    assert len(impl) == 1
    assert doc.status == "completed"


def test_completed_with_empty_diff_gets_downgraded(workflow, workspace):
    """Engineer lies about completing work → framework spots empty diff and
    downgrades to 'partial', prepending a qa_note."""
    task = _FakeTask(workspace_path=workspace, result=json.dumps(_payload()))
    with mock.patch.object(workflow, "_git_changed_files", return_value=[]):
        doc = workflow.persist_result(task)
    assert doc.status == "partial"
    assert doc.changed_files == []
    assert any("Engineer claimed status=completed" in n for n in doc.qa_notes)


def test_partial_with_empty_diff_stays_partial(workflow, workspace):
    task = _FakeTask(workspace_path=workspace, result=json.dumps(_payload(status="partial")))
    with mock.patch.object(workflow, "_git_changed_files", return_value=[]):
        doc = workflow.persist_result(task)
    assert doc.status == "partial"
    assert not any("Engineer claimed" in n for n in doc.qa_notes)


def test_blocked_status_skips_diff_check(workflow, workspace):
    payload = _payload(status="blocked", changed_files=[])
    task = _FakeTask(workspace_path=workspace, result=json.dumps(payload))
    with mock.patch.object(workflow, "_git_changed_files", return_value=[]):
        doc = workflow.persist_result(task)
    assert doc.status == "blocked"
    assert doc.changed_files == []


def test_clarification_question_optional(workflow, workspace):
    task = _FakeTask(workspace_path=workspace, result=json.dumps(_payload()))
    with mock.patch.object(workflow, "_git_changed_files", return_value=["x.py"]):
        doc = workflow.persist_result(task)
    assert doc.clarification_question is None


def test_clarification_question_persists(workflow, workspace):
    payload = _payload(status="blocked", changed_files=[])
    payload["clarification_question"] = "Use bcrypt or scrypt for hashing?"
    task = _FakeTask(workspace_path=workspace, result=json.dumps(payload))
    with mock.patch.object(workflow, "_git_changed_files", return_value=[]):
        doc = workflow.persist_result(task)
    assert doc.clarification_question == "Use bcrypt or scrypt for hashing?"
