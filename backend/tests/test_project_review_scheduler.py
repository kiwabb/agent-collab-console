from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pytest

from app.application.project_review_scheduler import run_project_review_tick
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
    assert all(task.payload == {"question": "Run a scheduled project health review."} for task in calls)


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
