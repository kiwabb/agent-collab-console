from __future__ import annotations

from typing import TypedDict

import pytest
from fastapi import HTTPException

import app.interfaces.api as api_module
from app.application.local_service_probe import LocalServiceState, LocalServiceStatus
from app.domain.models import Project


class _AuditEvent(TypedDict):
    project_id: str | None
    issue_id: str | None
    event: str


class _AuditStore:
    def __init__(self) -> None:
        self.events: list[_AuditEvent] = []

    async def append_project_audit(
        self,
        *,
        project_id: str | None,
        issue_id: str | None,
        event: str,
        sha: str | None = None,
        base_branch: str | None = None,
    ) -> None:
        del sha, base_branch
        self.events.append(
            {
                "project_id": project_id,
                "issue_id": issue_id,
                "event": event,
            }
        )


def _project() -> Project:
    return Project(
        id="project-1",
        name="Demo",
        repo_path="/tmp/demo",
        run_command="npm run dev",
    )


def _service(state: LocalServiceState = "reachable") -> LocalServiceStatus:
    return {
        "state": state,
        "url": "http://127.0.0.1:3000",
        "http_status": 200 if state == "reachable" else None,
        "checked_at": "2026-07-12T08:00:00+00:00",
        "error": None if state == "reachable" else "connection_failed",
    }


@pytest.mark.asyncio
async def test_start_refuses_before_env_materialization_when_external_service_is_reachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project()
    store = _AuditStore()
    env_reconciled = False

    async def load_project(_: str) -> Project:
        return project

    async def service_status(_: Project, __: object) -> LocalServiceStatus:
        return _service()

    async def reconcile(_: Project, __: object) -> None:
        nonlocal env_reconciled
        env_reconciled = True

    async def unexpected_start(*_: object) -> object:
        raise AssertionError("external reachable service must block process creation")

    monkeypatch.setattr(api_module, "_load_project_for_run", load_project)
    monkeypatch.setattr(api_module, "_require_codex_store", lambda: store)
    monkeypatch.setattr(api_module, "_project_service_status", service_status)
    monkeypatch.setattr(api_module, "_reconcile_project_env_file", reconcile)
    monkeypatch.setattr(api_module.project_run_manager, "status", lambda _: {
        "running": False,
        "command": None,
        "pid": None,
        "started_at": None,
        "exit_code": None,
    })
    monkeypatch.setattr(api_module.project_run_manager, "start", unexpected_start)

    with pytest.raises(HTTPException) as raised:
        await api_module.start_project_run(project.id)

    assert raised.value.status_code == 409
    assert raised.value.detail == {
        "reason": "service_already_reachable",
        "url": "http://127.0.0.1:3000",
        "http_status": 200,
    }
    assert env_reconciled is False
    assert store.events == [
        {
            "project_id": project.id,
            "issue_id": None,
            "event": "run_refused:service_already_reachable",
        }
    ]


@pytest.mark.asyncio
async def test_status_keeps_managed_process_and_service_reachability_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project()

    async def load_project(_: str) -> Project:
        return project

    async def service_status(_: Project, __: object) -> LocalServiceStatus:
        return _service("unreachable")

    monkeypatch.setattr(api_module, "_load_project_for_run", load_project)
    monkeypatch.setattr(api_module, "_project_service_status", service_status)
    monkeypatch.setattr(api_module.project_run_manager, "status", lambda _: {
        "running": True,
        "command": "npm run dev",
        "pid": 123,
        "started_at": "2026-07-12T08:00:00+00:00",
        "exit_code": None,
    })

    response = await api_module.get_project_run_status(project.id)

    assert response["running"] is True
    assert response["service"]["state"] == "unreachable"
