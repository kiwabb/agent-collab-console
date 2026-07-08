from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, cast
from uuid import uuid4

from app.application import timeouts
from app.application.github_pr_followup import EventBusLike
from app.application.project_conductor import ProjectConductor, ProjectConductorStore
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


class ProjectReviewTickFn(Protocol):
    async def __call__(
        self,
        store: ProjectReviewSchedulerStore,
        *,
        event_bus: object | None = None,
        limit: int | None = None,
    ) -> ProjectReviewTickSummary: ...


class ProjectReviewSleepFn(Protocol):
    async def __call__(self, interval: float) -> None: ...


async def _sleep(interval: float) -> None:
    await asyncio.sleep(interval)


@dataclass
class ProjectReviewSchedulerStatus:
    configured: bool = True
    interval_s: float = field(default_factory=timeouts.project_review_interval_s)
    limit: int = field(default_factory=timeouts.project_review_limit)
    running: bool = False
    tick_count: int = 0
    last_started_at: datetime | None = None
    last_completed_at: datetime | None = None
    last_error: str | None = None
    last_summary_counts: dict[str, int] = field(default_factory=dict)

    def mark_started(self, *, interval_s: float, limit: int) -> None:
        self.configured = True
        self.interval_s = interval_s
        self.limit = limit
        self.running = True
        self.last_started_at = datetime.now()

    def mark_completed(self, summary: ProjectReviewTickSummary) -> None:
        self.running = False
        self.tick_count += 1
        self.last_completed_at = datetime.now()
        self.last_error = None
        self.last_summary_counts = summary.counts

    def mark_failed(self, exc: Exception) -> None:
        self.running = False
        self.tick_count += 1
        self.last_completed_at = datetime.now()
        self.last_error = f"{type(exc).__name__}: {exc}"
        self.last_summary_counts = {}

    def mark_cancelled(self) -> None:
        self.running = False

    def to_dict(self) -> dict[str, object]:
        return {
            "configured": self.configured,
            "interval_s": self.interval_s,
            "limit": self.limit,
            "running": self.running,
            "tick_count": self.tick_count,
            "last_started_at": self.last_started_at.isoformat() if self.last_started_at else None,
            "last_completed_at": self.last_completed_at.isoformat()
            if self.last_completed_at
            else None,
            "last_error": self.last_error,
            "last_summary_counts": dict(self.last_summary_counts),
        }


_scheduler_status = ProjectReviewSchedulerStatus()


def reset_project_review_scheduler_status() -> None:
    global _scheduler_status
    _scheduler_status = ProjectReviewSchedulerStatus()


def get_project_review_scheduler_status() -> dict[str, object]:
    return _scheduler_status.to_dict()


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
    return ProjectConductor(
        project_id=project_id,
        store=cast(ProjectConductorStore, store),
        event_bus=cast(EventBusLike | None, event_bus),
    )


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
        except Exception as exc:  # noqa: BLE001, RUF100
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


async def run_project_review_scheduler_loop(
    store: ProjectReviewSchedulerStore,
    *,
    event_bus: object | None = None,
    interval_s: float | None = None,
    limit: int | None = None,
    tick_fn: ProjectReviewTickFn = run_project_review_tick,
    sleep_fn: ProjectReviewSleepFn = _sleep,
) -> None:
    interval = interval_s if interval_s is not None else timeouts.project_review_interval_s()
    review_limit = limit if limit is not None else timeouts.project_review_limit()

    try:
        while True:
            _scheduler_status.mark_started(interval_s=interval, limit=review_limit)
            try:
                summary = await tick_fn(store, event_bus=event_bus, limit=review_limit)
            except asyncio.CancelledError:
                _scheduler_status.mark_cancelled()
                raise
            except Exception as exc:  # noqa: BLE001, RUF100
                _scheduler_status.mark_failed(exc)
                logger.exception("project review scheduler tick failed")
            else:
                _scheduler_status.mark_completed(summary)
            await sleep_fn(interval)
    except asyncio.CancelledError:
        raise
