import json
from datetime import datetime

import pytest

from app.application.self_improvement_service import extract_self_improvement_proposals
from app.domain.models import CodexIssue, ConductorTask


class MemoryStore:
    def __init__(self, *, tasks=None, save_error: Exception | None = None):
        self.tasks = tasks or []
        self.save_error = save_error
        self.saved = []

    async def list_conductor_tasks(self, *, status=None):
        if status is None:
            return self.tasks
        return [task for task in self.tasks if task.status == status]

    async def save_self_improvement_proposal(self, proposal):
        if self.save_error is not None:
            raise self.save_error
        self.saved.append(proposal)


def _issue(**overrides):
    data = {
        "id": "issue-1",
        "session_id": "session-1",
        "title": "Fix flaky QA workflow",
        "description": "QA reported command failures and runtime tracebacks.",
        "status": "completed",
        "project_id": "project-1",
        "created_at": datetime(2026, 6, 8, 10, 0, 0),
    }
    data.update(overrides)
    return CodexIssue(**data)


def _task(task_id, *, status="failed", result_json=None, payload=None):
    return ConductorTask(
        id=task_id,
        project_id="project-1",
        issue_id="issue-1",
        task_kind="issue",
        status=status,
        payload=payload or {"phase": "qa"},
        result_json=json.dumps(result_json or {"traceback": "RuntimeError: qa command failed"}),
    )


@pytest.mark.asyncio
async def test_qa_failure_creates_code_spec_proposal_with_evidence():
    store = MemoryStore(
        tasks=[
            _task(
                "task-1",
                result_json={
                    "qa": {"verdict": "failed", "bugs_found": ["missing regression contract"]},
                    "commands": [{"cmd": "pytest backend/tests/test_qa_workflow.py", "exit_code": 1}],
                },
            )
        ]
    )

    proposals = await extract_self_improvement_proposals(_issue(), store)

    assert len(proposals) == 1
    assert proposals[0].target_kind == "code_spec"
    assert proposals[0].severity == "medium"
    assert proposals[0].fingerprint == "project-1|issue-1|code_spec|qa_failure_contract"
    assert '"conductor_task"' in proposals[0].evidence_json
    assert store.saved == proposals


@pytest.mark.asyncio
async def test_runtime_failure_creates_runtime_tooling_proposal():
    store = MemoryStore(tasks=[_task("task-1", result_json={"traceback": "RuntimeError: browser observed failure"})])

    proposals = await extract_self_improvement_proposals(_issue(title="Fix browser runtime failure"), store)

    assert len(proposals) == 1
    assert proposals[0].target_kind == "runtime_tooling"
    assert proposals[0].fingerprint == "project-1|issue-1|runtime_tooling|runtime_failure_contract"


@pytest.mark.asyncio
async def test_clean_issue_creates_no_proposals():
    store = MemoryStore(tasks=[_task("task-1", status="done", result_json={"summary": "all good"})])

    proposals = await extract_self_improvement_proposals(_issue(title="Rename label"), store)

    assert proposals == []
    assert store.saved == []


@pytest.mark.asyncio
async def test_duplicate_rules_save_once_per_rule():
    store = MemoryStore(
        tasks=[
            _task("task-1", result_json={"traceback": "RuntimeError: failed once"}),
            _task("task-2", result_json={"traceback": "RuntimeError: failed twice"}),
        ]
    )

    proposals = await extract_self_improvement_proposals(_issue(), store)

    assert len(proposals) == 1
    assert len(store.saved) == 1


@pytest.mark.asyncio
async def test_store_save_failure_is_best_effort():
    store = MemoryStore(tasks=[_task("task-1")], save_error=RuntimeError("db unavailable"))

    proposals = await extract_self_improvement_proposals(_issue(), store)

    assert proposals == []
