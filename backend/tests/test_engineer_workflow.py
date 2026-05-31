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


def test_partial_with_empty_diff_claiming_files_gets_flagged(workflow, workspace):
    """C1: partial ALSO claims it landed some code (non-empty changed_files).
    A zero real diff is a claim-vs-reality contradiction → flag + clear files,
    even though the status was already 'partial'."""
    task = _FakeTask(workspace_path=workspace, result=json.dumps(_payload(status="partial")))
    with mock.patch.object(workflow, "_git_changed_files", return_value=[]):
        doc = workflow.persist_result(task)
    assert doc.status == "partial"
    assert doc.changed_files == []
    assert any("Engineer claimed status=partial" in n for n in doc.qa_notes)


def test_partial_with_real_diff_left_untouched(workflow, workspace):
    """C1: partial + a real (matching) git diff → no downgrade note, files kept."""
    payload = _payload(status="partial", changed_files=["x.py"])
    task = _FakeTask(workspace_path=workspace, result=json.dumps(payload))
    with mock.patch.object(workflow, "_git_changed_files", return_value=["x.py"]):
        doc = workflow.persist_result(task)
    assert doc.status == "partial"
    assert doc.changed_files == ["x.py"]
    assert not any("Engineer claimed" in n for n in doc.qa_notes)


def test_partial_legal_empty_changed_files_not_flagged(workflow, workspace):
    """C1 boundary: an honest partial with changed_files=[] (no completed_tasks)
    is NOT a landing claim → must not be flagged even with a zero diff."""
    payload = _payload(status="partial", changed_files=[], completed_tasks=[])
    task = _FakeTask(workspace_path=workspace, result=json.dumps(payload))
    with mock.patch.object(workflow, "_git_changed_files", return_value=[]):
        doc = workflow.persist_result(task)
    assert doc.status == "partial"
    assert doc.changed_files == []
    assert not any("Engineer claimed" in n for n in doc.qa_notes)


def test_completed_legal_already_implemented_not_flagged(workflow, workspace):
    """C1 boundary (AC4-style): completed + honest changed_files=[] + no
    completed_tasks (already implemented / nothing to change) + zero diff →
    NOT flagged. The 'already implemented' path must survive."""
    payload = _payload(status="completed", changed_files=[], completed_tasks=[])
    task = _FakeTask(workspace_path=workspace, result=json.dumps(payload))
    with mock.patch.object(workflow, "_git_changed_files", return_value=[]):
        doc = workflow.persist_result(task)
    assert doc.status == "completed"
    assert doc.changed_files == []
    assert not any("Engineer claimed" in n for n in doc.qa_notes)


def test_completed_already_implemented_with_completed_tasks_not_flagged(workflow, workspace):
    """C1 boundary (AC4, regression): an honest 'already implemented' report
    (status=completed, changed_files=[], zero diff) that legitimately lists the
    task it addressed in completed_tasks must NOT be downgraded. completed_tasks
    is NOT a code-landing signal — only a non-empty changed_files is. This keeps
    the Engineer C1 trigger aligned with review_guard (which uses bool(claimed)
    only) so the legal already-implemented path survives on BOTH sides."""
    payload = _payload(
        status="completed",
        changed_files=[],
        completed_tasks=[
            {"title": "Verify /api/ping already exists", "description": "it does", "priority": "P1"}
        ],
    )
    task = _FakeTask(workspace_path=workspace, result=json.dumps(payload))
    with mock.patch.object(workflow, "_git_changed_files", return_value=[]):
        doc = workflow.persist_result(task)
    assert doc.status == "completed"
    assert doc.changed_files == []
    assert not any("Engineer claimed" in n for n in doc.qa_notes)


def test_c2_rewrites_changed_files_to_ground_truth(workflow, workspace):
    """C2: Engineer claims changed_files=[X] but actually changed [Y] →
    changed_files rewritten to the actual set + a reconcile note recording the
    divergence."""
    payload = _payload(status="completed", changed_files=["claimed_a.py"])
    task = _FakeTask(workspace_path=workspace, result=json.dumps(payload))
    with mock.patch.object(workflow, "_git_changed_files", return_value=["actual_b.py"]):
        doc = workflow.persist_result(task)
    assert doc.status == "completed"
    assert doc.changed_files == ["actual_b.py"]
    assert any("did not match the actual git diff" in n for n in doc.qa_notes)


def test_c2_no_note_when_claim_matches_actual(workflow, workspace):
    """C2: claimed == actual (modulo path normalization) → no reconcile note,
    and the model's original changed_files list is left untouched (no noise)."""
    payload = _payload(status="completed", changed_files=["./pkg/a.py", "pkg/b.py"])
    task = _FakeTask(workspace_path=workspace, result=json.dumps(payload))
    with mock.patch.object(workflow, "_git_changed_files", return_value=["pkg/b.py", "pkg/a.py"]):
        doc = workflow.persist_result(task)
    # No divergence (after normalization) → list preserved verbatim, no note.
    assert doc.changed_files == ["./pkg/a.py", "pkg/b.py"]
    assert not any("did not match" in n for n in doc.qa_notes)


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
