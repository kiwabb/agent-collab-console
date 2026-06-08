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
async def test_capability_issue_without_eval_evidence_creates_benchmark_eval_proposal():
    issue = _issue(
        title="Improve SWE-bench Verified solve rate",
        description=(
            "Capability work improved autonomy, but no reviewed measurement artifact was attached."
        ),
    )
    store = MemoryStore(
        tasks=[
            _task(
                "task-1",
                status="done",
                payload={"phase": "implementation", "summary": "autonomy improvement"},
                result_json={
                    "summary": (
                        "implemented capability improvement without measured "
                        "acceptance evidence"
                    )
                },
            )
        ]
    )

    proposals = await extract_self_improvement_proposals(issue, store)

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.target_kind == "benchmark_eval"
    assert (
        proposal.fingerprint
        == "project-1|issue-1|benchmark_eval|missing_capability_eval_contract"
    )
    assert proposal.severity == "medium"
    assert "benchmark" in proposal.recommendation.lower()
    assert "eval" in proposal.recommendation.lower()
    assert '"codex_issue"' in proposal.evidence_json
    assert '"conductor_task"' in proposal.evidence_json
    assert store.saved == proposals


@pytest.mark.asyncio
async def test_capability_issue_with_eval_evidence_does_not_create_benchmark_eval_proposal():
    issue = _issue(title="Improve SWE-bench Verified solve rate")
    store = MemoryStore(
        tasks=[
            _task(
                "task-1",
                status="done",
                result_json={
                    "summary": "validated capability improvement",
                    "benchmark_run": {"fixture_id": "swebench-verified-smoke", "pass_at_1": 0.42},
                },
            )
        ]
    )

    proposals = await extract_self_improvement_proposals(issue, store)

    assert proposals == []
    assert store.saved == []


@pytest.mark.asyncio
async def test_duplicate_benchmark_eval_matches_save_once_per_issue_rule():
    issue = _issue(title="Improve autonomous capability")
    store = MemoryStore(
        tasks=[
            _task(
                "task-1",
                status="done",
                result_json={"summary": "autonomy capability improvement"},
            ),
            _task(
                "task-2",
                status="done",
                result_json={"summary": "solve-rate capability work"},
            ),
        ]
    )

    proposals = await extract_self_improvement_proposals(issue, store)

    assert len(proposals) == 1
    assert proposals[0].target_kind == "benchmark_eval"
    assert len(store.saved) == 1


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


@pytest.mark.asyncio
async def test_retries_exhausted_creates_conductor_policy_proposal():
    store = MemoryStore(
        tasks=[
            _task(
                "task-1",
                result_json={
                    "status": "done",
                    "tool_events": [
                        {
                            "name": "dispatch_subagent",
                            "result": {"status": "retries_exhausted", "role": "engineer"},
                        }
                    ],
                },
            )
        ]
    )

    proposals = await extract_self_improvement_proposals(_issue(), store)

    policy = [proposal for proposal in proposals if proposal.target_kind == "conductor_policy"]
    assert len(policy) == 1
    assert policy[0].fingerprint == "project-1|issue-1|conductor_policy|role_retries_exhausted"
    assert "engineer" in policy[0].evidence_json
    assert store.saved == proposals


@pytest.mark.asyncio
async def test_role_busy_creates_conductor_policy_proposal():
    store = MemoryStore(
        tasks=[
            _task(
                "task-1",
                result_json={
                    "tool_events": [
                        {
                            "name": "dispatch_subagent",
                            "result": {"status": "role_busy", "role": "qa"},
                        }
                    ],
                },
            )
        ]
    )

    proposals = await extract_self_improvement_proposals(_issue(), store)

    policy = [proposal for proposal in proposals if proposal.target_kind == "conductor_policy"]
    assert len(policy) == 1
    assert policy[0].fingerprint == "project-1|issue-1|conductor_policy|role_busy"
    assert "qa" in policy[0].evidence_json


@pytest.mark.asyncio
async def test_dispatch_batch_conflict_creates_conductor_policy_proposal():
    store = MemoryStore(
        tasks=[
            _task(
                "task-1",
                result_json={
                    "tool_events": [
                        {
                            "name": "dispatch_batch",
                            "result": {
                                "merge_status": "conflict",
                                "conflicts": [{"file": "backend/app.py"}],
                            },
                        }
                    ],
                },
            )
        ]
    )

    proposals = await extract_self_improvement_proposals(_issue(), store)

    policy = [proposal for proposal in proposals if proposal.target_kind == "conductor_policy"]
    assert len(policy) == 1
    assert policy[0].fingerprint == "project-1|issue-1|conductor_policy|dispatch_batch_conflict"
    assert "backend/app.py" in policy[0].evidence_json
