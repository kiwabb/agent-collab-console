from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from app.application.project_conductor import ProjectConductor
from app.domain.models import ConductorTask, Project

logger = logging.getLogger(__name__)


class ProjectReviewSchedulerStore(Protocol):
    async def list_projects(self) -> list[Project]: ...


class ProjectReviewConductor(Protocol):
    async def handle_task(self, task: ConductorTask) -> dict[str, object]: ...


class ProjectReviewConductorFactory(Protocol):
    def __call__(
        self,
        *,
        project_id: str,
        store: ProjectReviewSchedulerStore,
        event_bus: object | None,
    ) -> ProjectReviewConductor: ...


@dataclass(frozen=True)
class ProjectReviewTickResult:
    project_id: str
    task_id: str
    status: str
    result: dict[str, object] | None = None
    error: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "task_id": self.task_id,
            "status": self.status,
            "result": self.result or {},
            "error": self.error,
        }


@dataclass(frozen=True)
class ProjectReviewTickSummary:
    results: list[ProjectReviewTickResult] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for result in self.results:
            counts[result.status] = counts.get(result.status, 0) + 1
        return counts

    def to_dict(self) -> dict[str, object]:
        return {
            "counts": self.counts,
            "results": [result.to_dict() for result in self.results],
        }


def _default_conductor_factory(
    *,
    project_id: str,
    store: ProjectReviewSchedulerStore,
    event_bus: object | None,
) -> ProjectReviewConductor:
    return ProjectConductor(project_id=project_id, store=store, event_bus=event_bus)


async def run_project_review_tick(
    store: ProjectReviewSchedulerStore,
    *,
    event_bus: object | None = None,
    conductor_factory: ProjectReviewConductorFactory = _default_conductor_factory,
    limit: int | None = None,
) -> ProjectReviewTickSummary:
    projects = await store.list_projects()
    if limit is not None:
        projects = projects[: max(0, limit)]

    results: list[ProjectReviewTickResult] = []
    for project in projects:
        task = ConductorTask(
            id=str(uuid4()),
            project_id=project.id,
            task_kind="scheduled_review",
            payload={"question": "Run a scheduled project health review."},
            created_at=datetime.now(),
        )
        try:
            conductor = conductor_factory(
                project_id=project.id,
                store=store,
                event_bus=event_bus,
            )
            result = await conductor.handle_task(task)
        except Exception as exc:  # noqa: BLE001 - one project must not stop the scheduler tick.
            logger.exception(
                "project review tick failed project_id=%s task_id=%s",
                project.id,
                task.id,
            )
            results.append(
                ProjectReviewTickResult(
                    project_id=project.id,
                    task_id=task.id,
                    status="failed",
                    error=str(exc),
                )
            )
            continue

        results.append(
            ProjectReviewTickResult(
                project_id=project.id,
                task_id=task.id,
                status=str(result.get("status") or "done"),
                result=result,
            )
        )

    return ProjectReviewTickSummary(results=results)
