from __future__ import annotations  # noqa: I001

from datetime import datetime  # noqa: I001, RUF100
from uuid import uuid4

from app.domain.models import Task, Message, Artifact, AgentRun


class OrchestrationService:
    def __init__(self, session_service, event_bus, master_adapter=None, worker_adapter=None):
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
                    content=art["content"],
                    steps=art.get("steps"),
                    created_at=datetime.now(),
                )
                session.artifacts.append(artifact)
            # Persist after master planning artifacts are added
            await self.session_service.update_session(session)
        await self.event_bus.append({"type": "task.assigned", "task_id": task.id})
        return task

    async def run_task(self, task_id: str) -> dict:
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
                    payload = {
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
                        payload=payload,
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
                            content=art["content"],
                            created_at=datetime.now(),
                        )
                        session.artifacts.append(artifact)
                    session.runs.append(agent_run)
                    session.messages.append(message)
                    await self.session_service.update_session(session)
                    event_type = "run.completed" if run_status == "completed" else "run.failed"
                    await self.event_bus.append(
                        {"type": event_type, "task_id": task.id, "agent_id": result["agent_id"]}
                    )
                    return result
        raise KeyError(task_id)

    async def retry_task(self, task_id: str) -> dict:
        """Retry a failed task by resetting its status to pending and re-running."""
        for session in list(self.session_service.sessions.values()):
            for task in session.tasks:
                if task.id == task_id:
                    if task.status != "failed":
                        raise ValueError(f"Task {task_id} is not in failed state, cannot retry")
                    task.status = "pending"
                    await self.session_service.update_session(session)
                    return await self.run_task(task_id)
        raise KeyError(task_id)
