from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

import pytest

from app.application.project_review_scheduler import (
    ProjectReviewTickResult,
    ProjectReviewTickSummary,
    get_project_review_scheduler_status,
    reset_project_review_scheduler_status,
    run_project_review_scheduler_loop,
    run_project_review_tick,
)
from app.domain.models import ConductorTask, Project


def _project(project_id: str) -> Project:
    return Project(
        id=project_id,
        name=f"Project {project_id}",
        repo_path=f"/tmp/{project_id}",
        default_branch="main",
        created_at=datetime(2026, 6, 8, 10, 0, 0),
    )


class _Store:
    def __init__(self, projects: list[Project]) -> None:
        self.projects = projects

    async def list_projects(self) -> list[Project]:
        return self.projects


@dataclass
class _Conductor:
    project_id: str
    calls: list[ConductorTask]
    fail: bool = False

    async def handle_task(self, task: ConductorTask) -> dict[str, object]:
        self.calls.append(task)
        if self.fail:
            raise RuntimeError(f"{self.project_id} unavailable")
        return {"status": "done", "task_id": task.id, "project_id": self.project_id}


@pytest.mark.asyncio
async def test_project_review_tick_runs_scheduled_review_for_each_project():
    calls: list[ConductorTask] = []

    def conductor_factory(*, project_id: str, store, event_bus):
        return _Conductor(project_id=project_id, calls=calls)

    summary = await run_project_review_tick(
        _Store([_project("project-1"), _project("project-2")]),
        event_bus="events",
        conductor_factory=conductor_factory,
    )

    assert summary.to_dict()["counts"] == {"done": 2}
    assert [result.project_id for result in summary.results] == ["project-1", "project-2"]
    assert [task.project_id for task in calls] == ["project-1", "project-2"]
    assert all(task.task_kind == "scheduled_review" for task in calls)
    assert all(
        task.payload == {"question": "Run a scheduled project health review."} for task in calls
    )


@pytest.mark.asyncio
async def test_project_review_tick_isolates_project_failures_and_continues():
    calls: list[ConductorTask] = []

    def conductor_factory(*, project_id: str, store, event_bus):
        return _Conductor(project_id=project_id, calls=calls, fail=project_id == "project-1")

    summary = await run_project_review_tick(
        _Store([_project("project-1"), _project("project-2")]),
        conductor_factory=conductor_factory,
    )

    payload = summary.to_dict()
    assert payload["counts"] == {"failed": 1, "done": 1}
    assert payload["results"][0]["project_id"] == "project-1"
    assert payload["results"][0]["status"] == "failed"
    assert payload["results"][0]["error"] == "project-1 unavailable"
    assert payload["results"][1]["project_id"] == "project-2"
    assert payload["results"][1]["status"] == "done"
    assert [task.project_id for task in calls] == ["project-1", "project-2"]


@pytest.mark.asyncio
async def test_project_review_tick_limit_bounds_project_selection():
    calls: list[ConductorTask] = []

    def conductor_factory(*, project_id: str, store, event_bus):
        return _Conductor(project_id=project_id, calls=calls)

    summary = await run_project_review_tick(
        _Store(
            [
                _project("project-1"),
                _project("project-2"),
                _project("project-3"),
            ]
        ),
        conductor_factory=conductor_factory,
        limit=2,
    )

    assert summary.to_dict()["counts"] == {"done": 2}
    assert [task.project_id for task in calls] == ["project-1", "project-2"]


@pytest.mark.asyncio
async def test_project_review_scheduler_loop_repeats_after_each_sleep():
    reset_project_review_scheduler_status()
    ticks = 0
    sleeps: list[float] = []

    async def tick(store, *, event_bus=None, limit=None):
        nonlocal ticks
        ticks += 1
        return ProjectReviewTickSummary()

    async def sleep(interval: float) -> None:
        sleeps.append(interval)
        if len(sleeps) == 2:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await run_project_review_scheduler_loop(
            _Store([]),
            event_bus="events",
            interval_s=12.5,
            limit=3,
            tick_fn=tick,
            sleep_fn=sleep,
        )

    assert ticks == 2
    assert sleeps == [12.5, 12.5]


@pytest.mark.asyncio
async def test_project_review_scheduler_loop_survives_tick_exception():
    reset_project_review_scheduler_status()
    attempts = 0
    sleeps = 0

    async def tick(store, *, event_bus=None, limit=None):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("store temporarily unavailable")
        return ProjectReviewTickSummary()

    async def sleep(interval: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps == 2:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await run_project_review_scheduler_loop(
            _Store([]),
            interval_s=1,
            tick_fn=tick,
            sleep_fn=sleep,
        )

    assert attempts == 2
    assert sleeps == 2


@pytest.mark.asyncio
async def test_project_review_scheduler_loop_propagates_cancellation_from_tick():
    reset_project_review_scheduler_status()

    async def tick(store, *, event_bus=None, limit=None):
        raise asyncio.CancelledError

    async def sleep(interval: float) -> None:
        raise AssertionError("sleep should not run after cancellation")

    with pytest.raises(asyncio.CancelledError):
        await run_project_review_scheduler_loop(
            _Store([]),
            tick_fn=tick,
            sleep_fn=sleep,
        )


@pytest.mark.asyncio
async def test_project_review_scheduler_status_records_successful_tick():
    reset_project_review_scheduler_status()

    async def tick(store, *, event_bus=None, limit=None):
        assert limit == 3
        return ProjectReviewTickSummary(
            results=[
                ProjectReviewTickResult(
                    project_id="project-1",
                    task_id="task-1",
                    status="done",
                )
            ]
        )

    async def sleep(interval: float) -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await run_project_review_scheduler_loop(
            _Store([]),
            interval_s=9,
            limit=3,
            tick_fn=tick,
            sleep_fn=sleep,
        )

    status = get_project_review_scheduler_status()
    assert status["configured"] is True
    assert status["interval_s"] == 9
    assert status["limit"] == 3
    assert status["running"] is False
    assert status["tick_count"] == 1
    assert status["last_started_at"]
    assert status["last_completed_at"]
    assert status["last_error"] is None
    assert status["last_summary_counts"] == {"done": 1}


@pytest.mark.asyncio
async def test_project_review_scheduler_status_records_failed_tick():
    reset_project_review_scheduler_status()

    async def tick(store, *, event_bus=None, limit=None):
        raise RuntimeError("store temporarily unavailable")

    async def sleep(interval: float) -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await run_project_review_scheduler_loop(
            _Store([]),
            interval_s=5,
            limit=2,
            tick_fn=tick,
            sleep_fn=sleep,
        )

    status = get_project_review_scheduler_status()
    assert status["running"] is False
    assert status["tick_count"] == 1
    assert status["last_completed_at"]
    assert status["last_error"] == "RuntimeError: store temporarily unavailable"
    assert status["last_summary_counts"] == {}


@pytest.mark.asyncio
async def test_project_review_scheduler_status_clears_running_on_tick_cancellation():
    reset_project_review_scheduler_status()

    async def tick(store, *, event_bus=None, limit=None):
        raise asyncio.CancelledError

    async def sleep(interval: float) -> None:
        raise AssertionError("sleep should not run")

    with pytest.raises(asyncio.CancelledError):
        await run_project_review_scheduler_loop(
            _Store([]),
            interval_s=7,
            tick_fn=tick,
            sleep_fn=sleep,
        )

    status = get_project_review_scheduler_status()
    assert status["running"] is False
    assert status["tick_count"] == 0
    assert status["last_completed_at"] is None
