from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import cast

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
        self.tasks: dict[str, ConductorTask] = {}
        self.latest_completed: dict[str, datetime] = {}

    async def list_projects(self) -> list[Project]:
        return self.projects

    async def create_conductor_task_if_absent(self, task: ConductorTask) -> bool:
        if task.id in self.tasks:
            return False
        self.tasks[task.id] = replace(task)
        return True

    async def load_latest_completed_project_review_at(
        self,
        project_id: str,
    ) -> datetime | None:
        return self.latest_completed.get(project_id)

    async def save_conductor_task(self, task: ConductorTask) -> None:
        self.tasks[task.id] = replace(task)


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
    results = cast(list[dict[str, object]], payload["results"])
    assert payload["counts"] == {"failed": 1, "done": 1}
    assert results[0]["project_id"] == "project-1"
    assert results[0]["status"] == "failed"
    assert results[0]["error"] == "project-1 unavailable"
    assert results[1]["project_id"] == "project-2"
    assert results[1]["status"] == "done"
    assert [task.project_id for task in calls] == ["project-1", "project-2"]


@pytest.mark.asyncio
async def test_project_review_tick_isolates_due_lookup_failures_and_continues():
    calls: list[ConductorTask] = []

    class DueLookupFailureStore(_Store):
        async def load_latest_completed_project_review_at(
            self,
            project_id: str,
        ) -> datetime | None:
            if project_id == "project-1":
                raise ValueError("invalid legacy review timestamp")
            return None

    store = DueLookupFailureStore([_project("project-1"), _project("project-2")])

    def conductor_factory(*, project_id: str, store, event_bus):
        return _Conductor(project_id=project_id, calls=calls)

    summary = await run_project_review_tick(
        store,
        conductor_factory=conductor_factory,
        due_after=datetime(2026, 6, 8, 9, 0, 0),
        review_slot="300:lookup-failure",
    )

    assert summary.counts == {"failed": 1, "done": 1}
    assert summary.results[0].error == "invalid legacy review timestamp"
    assert summary.results[1].status == "done"
    assert [task.project_id for task in calls] == ["project-2"]
    assert all(task.project_id != "project-1" for task in store.tasks.values())


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
async def test_project_review_tick_skips_projects_reviewed_within_interval():
    calls: list[ConductorTask] = []
    store = _Store([_project("project-1")])
    now = datetime(2026, 6, 8, 12, 0, 0)
    store.latest_completed["project-1"] = now

    def conductor_factory(*, project_id: str, store, event_bus):
        return _Conductor(project_id=project_id, calls=calls)

    summary = await run_project_review_tick(
        store,
        conductor_factory=conductor_factory,
        due_after=now - timedelta(minutes=5),
        review_slot="300:1",
    )

    assert summary.counts == {"skipped_recent": 1}
    assert calls == []
    assert store.tasks == {}


@pytest.mark.asyncio
async def test_project_review_tick_claim_prevents_duplicate_restart_run():
    calls: list[ConductorTask] = []
    store = _Store([_project("project-1")])

    def conductor_factory(*, project_id: str, store, event_bus):
        return _Conductor(project_id=project_id, calls=calls)

    first = await run_project_review_tick(
        store,
        conductor_factory=conductor_factory,
        review_slot="300:42",
    )
    second = await run_project_review_tick(
        store,
        conductor_factory=conductor_factory,
        review_slot="300:42",
    )

    assert first.counts == {"done": 1}
    assert second.counts == {"skipped_claimed": 1}
    assert len(calls) == 1
    assert first.results[0].task_id == second.results[0].task_id


@pytest.mark.asyncio
async def test_project_review_scheduler_loop_repeats_after_each_sleep():
    reset_project_review_scheduler_status()
    ticks = 0
    sleeps: list[float] = []

    async def tick(
        store,
        *,
        event_bus=None,
        limit=None,
        due_after=None,
        review_slot=None,
    ):
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

    async def tick(
        store,
        *,
        event_bus=None,
        limit=None,
        due_after=None,
        review_slot=None,
    ):
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

    async def tick(
        store,
        *,
        event_bus=None,
        limit=None,
        due_after=None,
        review_slot=None,
    ):
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

    async def tick(
        store,
        *,
        event_bus=None,
        limit=None,
        due_after=None,
        review_slot=None,
    ):
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

    async def tick(
        store,
        *,
        event_bus=None,
        limit=None,
        due_after=None,
        review_slot=None,
    ):
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

    async def tick(
        store,
        *,
        event_bus=None,
        limit=None,
        due_after=None,
        review_slot=None,
    ):
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
