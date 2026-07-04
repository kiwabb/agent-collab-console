from __future__ import annotations

import pytest

from app.application.orchestration_service import OrchestrationService
from app.domain.models import Session, Task


class _SessionService:
    def __init__(self, session: Session) -> None:
        self.sessions = {session.id: session}

    async def get_session(self, session_id: str) -> Session:
        return self.sessions[session_id]

    async def update_session(self, session: Session) -> None:
        self.sessions[session.id] = session


class _EventBus:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def append(self, event: dict) -> None:
        self.events.append(event)


class _WorkerAdapter:
    def __init__(self, status: str) -> None:
        self.status = status

    def execute(self, payload: dict) -> dict:
        return {
            "agent_id": "worker-1",
            "role": "engineer",
            "status": self.status,
            "summary": "finished",
            "artifacts": [],
        }


@pytest.mark.asyncio
async def test_run_task_emits_completed_for_shared_success_status() -> None:
    session = Session(id="session-1", title="Demo")
    session.tasks.append(Task(id="task-1", session_id=session.id, title="Build"))
    events = _EventBus()
    service = OrchestrationService(
        _SessionService(session),
        events,
        worker_adapter=_WorkerAdapter("success"),
    )

    await service.run_task("task-1")

    assert session.tasks[0].status == "success"
    assert events.events[-1]["type"] == "run.completed"


@pytest.mark.asyncio
async def test_retry_task_accepts_shared_failure_status() -> None:
    session = Session(id="session-1", title="Demo")
    session.tasks.append(Task(id="task-1", session_id=session.id, title="Build", status="error"))
    service = OrchestrationService(
        _SessionService(session),
        _EventBus(),
        worker_adapter=_WorkerAdapter("completed"),
    )

    result = await service.retry_task("task-1")

    assert result["status"] == "completed"
    assert session.tasks[0].status == "completed"
