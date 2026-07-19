from __future__ import annotations

from typing import TypedDict

import pytest
from fastapi import HTTPException

import app.interfaces.api as api_module
from app.application.local_service_probe import LocalServiceState, LocalServiceStatus
from app.application.project_service_readiness import ApplicationReadinessStatus
from app.domain.models import Project, ProjectStartupService


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

    with pytest.raises(HTTPException) as raised:
        await api_module.start_project_run(project.id)

    assert raised.value.status_code == 409
    assert raised.value.detail == {
        "reason": "service_address_occupied",
        "url": "http://127.0.0.1:3000",
        "http_status": 200,
        "readiness_state": "invalid_config",
    }
    assert env_reconciled is False
    assert store.events == [
        {
            "project_id": project.id,
            "issue_id": None,
            "event": "run_refused:service_address_occupied",
        }
    ]


@pytest.mark.asyncio
async def test_service_start_blocks_legacy_config_before_env_or_spawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project()
    service = ProjectStartupService(
        project_id=project.id,
        service_id="backend",
        name="Backend",
        working_directory=".",
        setup_command="",
        run_command="npm run dev",
        access_url="http://127.0.0.1:3000",
    )
    env_reconciled = False

    async def load_service(_: str, __: str) -> tuple[Project, ProjectStartupService]:
        return project, service

    async def reconcile(_: Project, __: object) -> None:
        nonlocal env_reconciled
        env_reconciled = True

    async def unexpected_start(*_: object, **__: object) -> object:
        raise AssertionError("invalid startup config must not spawn")

    def stopped_status(*_: object, **__: object) -> dict[str, object]:
        return {
            "running": False,
            "command": None,
            "pid": None,
            "started_at": None,
            "exit_code": None,
        }

    monkeypatch.setattr(api_module, "_load_startup_service", load_service)
    monkeypatch.setattr(api_module, "_require_codex_store", lambda: object())
    monkeypatch.setattr(api_module, "_reconcile_project_env_file", reconcile)
    monkeypatch.setattr(api_module.project_run_manager, "status", stopped_status)
    monkeypatch.setattr(api_module.project_run_manager, "start", unexpected_start)

    with pytest.raises(HTTPException) as raised:
        await api_module.start_project_service_run(project.id, service.service_id)

    assert raised.value.status_code == 409
    assert isinstance(raised.value.detail, dict)
    assert raised.value.detail["reason"] == "startup_config_invalid"
    assert env_reconciled is False


@pytest.mark.asyncio
async def test_service_start_reports_occupied_unknown_before_env_or_spawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project()
    service = ProjectStartupService.model_validate(
        {
            "project_id": project.id,
            "service_id": "backend",
            "name": "Backend",
            "working_directory": ".",
            "setup_command": "",
            "run_command": "npm run dev",
            "access_url": "http://127.0.0.1:3000",
            "readiness_probe": {
                "kind": "http",
                "url": "http://127.0.0.1:3000/health",
                "expected_status": 200,
                "identity": {
                    "kind": "json_subset",
                    "expected": {"service": "expected-backend"},
                },
            },
        }
    )
    env_reconciled = False
    occupied: ApplicationReadinessStatus = {
        "state": "occupied_unknown",
        "url": "http://127.0.0.1:3000/health",
        "http_status": 200,
        "checked_at": "2026-07-14T00:00:00+00:00",
        "identity_matched": False,
        "error": "identity_mismatch",
    }

    async def load_service(_: str, __: str) -> tuple[Project, ProjectStartupService]:
        return project, service

    async def evaluate(
        _: ProjectStartupService,
    ) -> tuple[LocalServiceStatus, ApplicationReadinessStatus]:
        return _service(), occupied

    async def reconcile(_: Project, __: object) -> None:
        nonlocal env_reconciled
        env_reconciled = True

    def stopped_status(*_: object, **__: object) -> dict[str, object]:
        return {
            "running": False,
            "command": None,
            "pid": None,
            "started_at": None,
            "exit_code": None,
        }

    async def unexpected_start(*_: object, **__: object) -> object:
        raise AssertionError("occupied unknown service must not spawn")

    monkeypatch.setattr(api_module, "_load_startup_service", load_service)
    monkeypatch.setattr(api_module, "_require_codex_store", lambda: object())
    monkeypatch.setattr(api_module, "_startup_service_evaluation", evaluate)
    monkeypatch.setattr(api_module, "_reconcile_project_env_file", reconcile)
    monkeypatch.setattr(api_module.project_run_manager, "status", stopped_status)
    monkeypatch.setattr(api_module.project_run_manager, "start", unexpected_start)

    with pytest.raises(HTTPException) as raised:
        await api_module.start_project_service_run(project.id, service.service_id)

    assert raised.value.status_code == 409
    assert raised.value.detail == {
        "reason": "service_address_occupied",
        "service_id": "backend",
        "url": "http://127.0.0.1:3000",
        "http_status": 200,
        "readiness_state": "occupied_unknown",
    }
    assert env_reconciled is False


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
    assert response["readiness"]["state"] == "invalid_config"


@pytest.mark.asyncio
async def test_legacy_status_uses_compatible_readiness_matcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project()
    ready: ApplicationReadinessStatus = {
        "state": "ready",
        "url": "http://127.0.0.1:3000/health",
        "http_status": 200,
        "checked_at": "2026-07-14T00:00:00+00:00",
        "identity_matched": True,
        "error": None,
    }

    async def load_project(_: str) -> Project:
        return project

    async def service_status(_: Project, __: object) -> LocalServiceStatus:
        return _service()

    async def readiness_probe(_: Project, __: object) -> object:
        return object()

    async def evaluate(_: object) -> dict[str, object]:
        return {"service": _service(), "readiness": ready}

    monkeypatch.setattr(api_module, "_load_project_for_run", load_project)
    monkeypatch.setattr(api_module, "_project_service_status", service_status)
    monkeypatch.setattr(api_module, "_project_readiness_probe", readiness_probe)
    monkeypatch.setattr(api_module, "evaluate_project_service", evaluate)
    monkeypatch.setattr(api_module.project_run_manager, "status", lambda _: {
        "running": False,
        "command": None,
        "pid": None,
        "started_at": None,
        "exit_code": None,
    })

    response = await api_module.get_project_run_status(project.id)

    assert response["service"]["state"] == "reachable"
    assert response["readiness"]["state"] == "ready"
