"""Fail-closed specialist governance regressions."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from typing import cast

import pytest

from app.application.budget_service import BudgetExecutionProcess
from app.application.role_concurrency import RoleConcurrencyLimiter
from app.application.specialist_orchestrator import (
    _SPECIALIST_ROLE_SLOTS_BY_CHILD,
    SpecialistGovernanceError,
    SpecialistOrchestrator,
    SpecialistOrchestratorError,
    SpecialistStore,
)
from app.domain.models import AgentMessage, CodexIssue, CodexTask


@pytest.fixture(autouse=True)
def _reset_specialist_state() -> Generator[None, None, None]:
    RoleConcurrencyLimiter._instance = None
    _SPECIALIST_ROLE_SLOTS_BY_CHILD.clear()
    yield
    RoleConcurrencyLimiter._instance = None
    _SPECIALIST_ROLE_SLOTS_BY_CHILD.clear()



class _Store:
    def __init__(self, parent: CodexTask):
        self.issue = CodexIssue(
            id="issue-1",
            session_id="session-1",
            project_id="project-1",
            title="Budgeted issue",
            budget_usd=5.0,
        )
        self.tasks = {parent.id: parent}

    async def load_codex_issue(self, issue_id: str) -> CodexIssue | None:
        return self.issue if issue_id == self.issue.id else None

    async def load_codex_task(self, task_id: str) -> CodexTask | None:
        return self.tasks.get(task_id)

    async def save_codex_task(self, task: CodexTask) -> None:
        self.tasks[task.id] = task

    async def load_workflow_graph_for_issue(self, issue_id: str):
        return None

    async def save_agent_message(self, msg: AgentMessage) -> None:
        return None

    async def update_execution_process_status(
        self, proc_id: str, status: str, completed_at: datetime | None = None
    ) -> None:
        return None

    async def list_codex_tasks(
        self,
        *,
        issue_id: str | None = None,
        parent_task_id: str | None = None,
    ) -> list[CodexTask]:
        tasks = list(self.tasks.values())
        if parent_task_id is not None:
            tasks = [task for task in tasks if task.parent_task_id == parent_task_id]
        if issue_id is not None:
            tasks = [task for task in tasks if task.issue_id == issue_id]
        return tasks

    async def list_execution_processes(
        self, session_id: str | None = None, task_id: str | None = None
    ) -> list[BudgetExecutionProcess]:
        return []


class _EventBus:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def append(self, event: dict[str, object]) -> None:
        self.events.append(event)


class _TaskRunner:
    async def start_task_run(self, task: CodexTask, **kwargs):
        return None


def _parent_task() -> CodexTask:
    return CodexTask(
        id="parent-task",
        session_id="session-1",
        project_id="project-1",
        issue_id="issue-1",
        title="Implement feature",
        prompt="Do the work",
        role="engineer",
        executor="claude",
        status="running",
        task_kind="normal",
        workspace_path="/tmp/workspace",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


@pytest.mark.asyncio
async def test_request_specialist_fails_closed_when_budget_check_errors(monkeypatch):
    parent = _parent_task()
    store = _Store(parent)
    orchestrator = SpecialistOrchestrator(cast(SpecialistStore, store), _EventBus(), _TaskRunner())

    async def _boom(store_arg, issue_arg):
        raise RuntimeError("budget store unavailable")

    monkeypatch.setattr(
        "app.application.specialist_orchestrator.compute_issue_budget_status",
        _boom,
    )

    with pytest.raises(SpecialistGovernanceError) as excinfo:
        await orchestrator.request_specialist(
            parent_task=parent,
            specialist_role_key="specialist:security_reviewer",
            specialist_prompt="Review auth",
            why="Security",
        )

    assert excinfo.value.gate == "budget"
    assert "budget store unavailable" in excinfo.value.detail
    updated_parent = await store.load_codex_task(parent.id)
    assert updated_parent is not None
    assert updated_parent.status == "running"
    assert len(store.tasks) == 1


@pytest.mark.asyncio
async def test_request_specialist_rejects_over_budget_before_creating_child(monkeypatch):
    parent = _parent_task()
    store = _Store(parent)
    orchestrator = SpecialistOrchestrator(cast(SpecialistStore, store), _EventBus(), _TaskRunner())

    async def _over_budget(store_arg, issue_arg):
        class _BudgetStatus:
            over_budget = True

        return _BudgetStatus()

    monkeypatch.setattr(
        "app.application.specialist_orchestrator.compute_issue_budget_status",
        _over_budget,
    )

    with pytest.raises(SpecialistOrchestratorError) as excinfo:
        await orchestrator.request_specialist(
            parent_task=parent,
            specialist_role_key="specialist:security_reviewer",
            specialist_prompt="Review auth",
            why="Security",
        )
    assert "budget is exhausted" in str(excinfo.value)
    updated_parent = await store.load_codex_task(parent.id)
    assert updated_parent is not None
    assert updated_parent.status == "running"
    assert len(store.tasks) == 1


@pytest.mark.asyncio
async def test_request_specialist_fails_closed_when_concurrency_check_errors(monkeypatch):
    parent = _parent_task()
    store = _Store(parent)
    orchestrator = SpecialistOrchestrator(cast(SpecialistStore, store), _EventBus(), _TaskRunner())

    class _Limiter:
        @classmethod
        def instance(cls):
            return cls()

        async def acquire(self, role: str, *, timeout: float) -> bool:
            raise RuntimeError("limiter unavailable")

        def release(self, role: str) -> None:
            raise AssertionError("release should not run after failed acquire")

    monkeypatch.setattr(
        "app.application.specialist_orchestrator.RoleConcurrencyLimiter",
        _Limiter,
    )

    with pytest.raises(SpecialistGovernanceError) as excinfo:
        await orchestrator.request_specialist(
            parent_task=parent,
            specialist_role_key="specialist:security_reviewer",
            specialist_prompt="Review auth",
            why="Security",
        )

    assert excinfo.value.gate == "concurrency"
    assert "limiter unavailable" in excinfo.value.detail
    updated_parent = await store.load_codex_task(parent.id)
    assert updated_parent is not None
    assert updated_parent.status == "running"
    assert len(store.tasks) == 1


@pytest.mark.asyncio
async def test_request_specialist_preserves_busy_role_refusal(monkeypatch):
    parent = _parent_task()
    store = _Store(parent)
    orchestrator = SpecialistOrchestrator(cast(SpecialistStore, store), _EventBus(), _TaskRunner())

    class _Limiter:
        @classmethod
        def instance(cls):
            return cls()

        async def acquire(self, role: str, *, timeout: float) -> bool:
            return False

        def release(self, role: str) -> None:
            raise AssertionError("release should not run when no slot was acquired")

    monkeypatch.setattr(
        "app.application.specialist_orchestrator.RoleConcurrencyLimiter",
        _Limiter,
    )

    with pytest.raises(SpecialistOrchestratorError) as excinfo:
        await orchestrator.request_specialist(
            parent_task=parent,
            specialist_role_key="specialist:security_reviewer",
            specialist_prompt="Review auth",
            why="Security",
        )

    assert "max concurrency" in str(excinfo.value)
    updated_parent = await store.load_codex_task(parent.id)
    assert updated_parent is not None
    assert updated_parent.status == "running"
    assert len(store.tasks) == 1


@pytest.mark.asyncio
async def test_request_specialist_holds_role_slot_until_child_terminal(monkeypatch):
    parent = _parent_task()
    store = _Store(parent)
    orchestrator = SpecialistOrchestrator(cast(SpecialistStore, store), _EventBus(), _TaskRunner())
    events: list[tuple[str, str]] = []

    class _Limiter:
        _held = False

        @classmethod
        def instance(cls):
            return cls()

        async def acquire(self, role: str, *, timeout: float) -> bool:
            events.append(("acquire", role))
            if type(self)._held:
                return False
            type(self)._held = True
            return True

        def release(self, role: str) -> None:
            events.append(("release", role))
            type(self)._held = False

    monkeypatch.setattr(
        "app.application.specialist_orchestrator.RoleConcurrencyLimiter",
        _Limiter,
    )

    child = await orchestrator.request_specialist(
        parent_task=parent,
        specialist_role_key="specialist:security_reviewer",
        specialist_prompt="Review auth",
        why="Security",
    )

    assert events == [("acquire", "specialist:security_reviewer")]

    with pytest.raises(SpecialistOrchestratorError, match="current status: waiting_for_specialist"):
        await orchestrator.request_specialist(
            parent_task=parent,
            specialist_role_key="specialist:security_reviewer",
            specialist_prompt="Review again",
            why="Still busy",
        )

    child.status = "done"
    child.result = "ok"
    await store.save_codex_task(child)
    await orchestrator.complete_specialist_request(child.id, child.result)

    assert events == [
        ("acquire", "specialist:security_reviewer"),
        ("release", "specialist:security_reviewer"),
    ]


@pytest.mark.asyncio
async def test_request_specialist_releases_role_slot_when_runner_start_fails(monkeypatch):
    parent = _parent_task()
    store = _Store(parent)
    events: list[tuple[str, str]] = []

    class _Limiter:
        @classmethod
        def instance(cls):
            return cls()

        async def acquire(self, role: str, *, timeout: float) -> bool:
            events.append(("acquire", role))
            return True

        def release(self, role: str) -> None:
            events.append(("release", role))

    class _FailingRunner:
        async def start_task_run(self, task: CodexTask, **kwargs):
            raise RuntimeError("runner unavailable")

    monkeypatch.setattr(
        "app.application.specialist_orchestrator.RoleConcurrencyLimiter",
        _Limiter,
    )
    orchestrator = SpecialistOrchestrator(cast(SpecialistStore, store), _EventBus(), _FailingRunner())

    with pytest.raises(SpecialistOrchestratorError, match="Failed to start"):
        await orchestrator.request_specialist(
            parent_task=parent,
            specialist_role_key="specialist:security_reviewer",
            specialist_prompt="Review auth",
            why="Security",
        )

    assert events == [
        ("acquire", "specialist:security_reviewer"),
        ("release", "specialist:security_reviewer"),
    ]
