from __future__ import annotations

from collections.abc import Awaitable
from datetime import datetime  # noqa: I001, RUF100
from typing import Protocol
from uuid import uuid4

from app.adapters.base import AgentArtifact, AgentResult, WorkerTaskPayload
from app.application.task_statuses import is_task_failure_status, is_task_success_status
from app.domain.models import AgentRun, Artifact, Message, PlanDetails, Session, Task


class OrchestrationEventBus(Protocol):
    def append(self, event: dict[str, object]) -> Awaitable[None]: ...


class OrchestrationSessionService(Protocol):
    sessions: dict[str, Session]

    async def get_session(self, session_id: str) -> Session: ...

    async def update_session(self, session: Session) -> None: ...


class MasterAdapter(Protocol):
    def execute(self, task_title: str) -> AgentResult: ...


class WorkerAdapter(Protocol):
    def execute(self, payload: WorkerTaskPayload) -> AgentResult: ...


def _artifact_content(value: object) -> str | PlanDetails:
    if isinstance(value, str | PlanDetails):
        return value
    if isinstance(value, dict):
        return PlanDetails.model_validate(value)
    return str(value)


def _artifact_steps(artifact: AgentArtifact) -> list[str] | None:
    steps = artifact.get("steps")
    return steps if isinstance(steps, list) else None


class OrchestrationService:
    def __init__(
        self,
        session_service: OrchestrationSessionService,
        event_bus: OrchestrationEventBus,
        master_adapter: MasterAdapter | None = None,
        worker_adapter: WorkerAdapter | None = None,
    ) -> None:
        self.session_service = session_service
        self.event_bus = event_bus
        self.master_adapter = master_adapter
        self.worker_adapter = worker_adapter

    async def plan_task(self, session_id: str, title: str, assignee: str) -> Task:
        session = await self.session_service.get_session(session_id)
        task = Task(
            id=str(uuid4()),
            session_id=session_id,
            title=title,
            assignee=assignee,
            created_at=datetime.now(),
        )
        session.tasks.append(task)
        await self.session_service.update_session(session)
        if self.master_adapter:
            planning_result = self.master_adapter.execute(title)
            planning_message = Message(
                id=str(uuid4()),
                task_id=task.id,
                agent_id=planning_result["agent_id"],
                role=planning_result["role"],
                content=planning_result["summary"],
                created_at=datetime.now(),
            )
            session.messages.append(planning_message)
            for art in planning_result.get("artifacts", []):
                artifact = Artifact(
                    id=str(uuid4()),
                    task_id=task.id,
                    kind=art["kind"],
                    content=_artifact_content(art["content"]),
                    steps=_artifact_steps(art),
                    created_at=datetime.now(),
                )
                session.artifacts.append(artifact)
            # Persist after master planning artifacts are added
            await self.session_service.update_session(session)
        await self.event_bus.append({"type": "task.assigned", "task_id": task.id})
        return task

    async def run_task(self, task_id: str) -> AgentResult:
        if self.worker_adapter is None:
            raise RuntimeError("Worker adapter is not configured")
        for session in list(self.session_service.sessions.values()):
            for task in session.tasks:
                if task.id == task_id:
                    # Construct handoff payload with task_id, task_title, plan, session_id
                    plan_artifacts = [
                        a for a in session.artifacts if a.kind == "plan" and a.task_id == task_id
                    ]
                    plan = None
                    if plan_artifacts:
                        plan_artifact = plan_artifacts[0]
                        if isinstance(plan_artifact.content, dict):
                            plan = plan_artifact.content
                        elif hasattr(plan_artifact.content, "model_dump"):
                            plan = plan_artifact.content.model_dump()
                        elif isinstance(plan_artifact.content, str):
                            plan = {"summary": plan_artifact.content}
                    payload: WorkerTaskPayload = {
                        "task_id": task.id,
                        "task_title": task.title,
                        "plan": plan,
                        "session_id": session.id,
                    }
                    result = self.worker_adapter.execute(payload)
                    run_status = result.get("status", "completed")
                    task.status = run_status
                    agent_run = AgentRun(
                        id=str(uuid4()),
                        task_id=task.id,
                        agent_id=result["agent_id"],
                        role=result["role"],
                        status=run_status,
                        summary=result["summary"],
                        payload=dict(payload),
                        created_at=datetime.now(),
                    )
                    message = Message(
                        id=str(uuid4()),
                        task_id=task.id,
                        agent_id=result["agent_id"],
                        role=result["role"],
                        content=result["summary"],
                        created_at=datetime.now(),
                    )
                    for art in result.get("artifacts", []):
                        artifact = Artifact(
                            id=str(uuid4()),
                            task_id=task.id,
                            kind=art["kind"],
                            content=_artifact_content(art["content"]),
                            created_at=datetime.now(),
                        )
                        session.artifacts.append(artifact)
                    session.runs.append(agent_run)
                    session.messages.append(message)
                    await self.session_service.update_session(session)
                    event_type = (
                        "run.completed" if is_task_success_status(run_status) else "run.failed"
                    )
                    await self.event_bus.append(
                        {"type": event_type, "task_id": task.id, "agent_id": result["agent_id"]}
                    )
                    return result
        raise KeyError(task_id)

    async def retry_task(self, task_id: str) -> AgentResult:
        """Retry a failed task by resetting its status to pending and re-running."""
        for session in list(self.session_service.sessions.values()):
            for task in session.tasks:
                if task.id == task_id:
                    if not is_task_failure_status(task.status):
                        raise ValueError(f"Task {task_id} is not in failed state, cannot retry")
                    task.status = "pending"
                    await self.session_service.update_session(session)
                    return await self.run_task(task_id)
        raise KeyError(task_id)
