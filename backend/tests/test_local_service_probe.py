from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest

from app.application.local_service_probe import (
    LocalServiceUrlError,
    canonicalize_local_service_url,
    probe_local_service,
    resolve_project_access_url,
    select_project_access_url,
)
from app.domain.models import CodexTask
from app.json_safety import JsonObject


@pytest.mark.parametrize(
    ("raw_url", "expected"),
    [
        ("http://localhost:3000", "http://localhost:3000"),
        ("HTTP://127.0.0.2:8080/path?q=1#ignored", "http://127.0.0.2:8080/path?q=1"),
        ("http://0.0.0.0:5173", "http://127.0.0.1:5173"),
        ("http://[::]:8000", "http://[::1]:8000"),
        ("https://[::1]", "https://[::1]"),
    ],
)
def test_canonicalize_local_service_url_accepts_loopback_targets(
    raw_url: str,
    expected: str,
) -> None:
    assert canonicalize_local_service_url(raw_url) == expected


@pytest.mark.parametrize(
    "raw_url",
    [
        "https://example.com",
        "http://192.168.1.2:3000",
        "http://169.254.169.254/latest/meta-data",
        "http://localhost.example.com:3000",
        "http://user:pass@localhost:3000",
        "file:///tmp/service.sock",
        "http://127.0.0.1:70000",
        "http://localhost:3000/\x00",
        "http://local\thost:3000",
    ],
)
def test_canonicalize_local_service_url_rejects_unsafe_targets(raw_url: str) -> None:
    with pytest.raises(LocalServiceUrlError):
        canonicalize_local_service_url(raw_url)


@pytest.mark.asyncio
async def test_probe_rejects_remote_url_before_transport() -> None:
    def unexpected_request(_: httpx.Request) -> httpx.Response:
        raise AssertionError("non-loopback URL must not reach the HTTP transport")

    result = await probe_local_service(
        "http://169.254.169.254/latest/meta-data",
        transport=httpx.MockTransport(unexpected_request),
    )

    assert result["state"] == "invalid_url"
    assert result["error"] == "host_not_loopback"
    assert result["url"] is None


@pytest.mark.asyncio
async def test_probe_reports_missing_url_without_network_request() -> None:
    result = await probe_local_service(None)

    assert result == {
        "state": "not_configured",
        "url": None,
        "http_status": None,
        "checked_at": None,
        "error": None,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [200, 302, 404, 500])
async def test_probe_treats_every_http_response_as_reachable(status_code: int) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status_code,
            headers={"location": "https://example.com/redirected"},
        )

    result = await probe_local_service(
        "http://127.0.0.1:3000",
        transport=httpx.MockTransport(handler),
    )

    assert result["state"] == "reachable"
    assert result["http_status"] == status_code
    assert result["url"] == "http://127.0.0.1:3000"
    assert len(requests) == 1


class _UnreadBody(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        raise AssertionError("reachability probe must not consume the response body")
        yield b""  # pragma: no cover

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_probe_closes_without_reading_response_body() -> None:
    body = _UnreadBody()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=body)

    result = await probe_local_service(
        "http://localhost:3000/events",
        transport=httpx.MockTransport(handler),
    )

    assert result["state"] == "reachable"
    assert body.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_type", "expected_error"),
    [
        (httpx.ConnectTimeout, "timeout"),
        (httpx.ConnectError, "connection_failed"),
    ],
)
async def test_probe_maps_expected_network_failures_to_unreachable(
    error_type: type[httpx.RequestError],
    expected_error: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error_type("unavailable", request=request)

    result = await probe_local_service(
        "http://127.0.0.1:3000",
        transport=httpx.MockTransport(handler),
    )

    assert result["state"] == "unreachable"
    assert result["error"] == expected_error


class _DelayedHeadersTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.cancelled = False

    async def handle_async_request(self, _request: httpx.Request) -> httpx.Response:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise AssertionError("unreachable")


@pytest.mark.asyncio
async def test_probe_enforces_total_deadline_while_waiting_for_headers() -> None:
    transport = _DelayedHeadersTransport()

    result = await asyncio.wait_for(
        probe_local_service(
            "http://127.0.0.1:3000",
            timeout_s=0.01,
            transport=transport,
        ),
        timeout=0.5,
    )

    assert result["state"] == "unreachable"
    assert result["error"] == "timeout"
    assert transport.cancelled is True


@pytest.mark.asyncio
async def test_probe_maps_httpx_invalid_url_without_leaking_exception() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.InvalidURL("invalid URL from transport")

    result = await probe_local_service(
        "http://localhost:3000",
        transport=httpx.MockTransport(handler),
    )

    assert result["state"] == "invalid_url"
    assert result["url"] is None
    assert result["error"] == "invalid_url"


def _analysis_task(
    task_id: str,
    *,
    run_command: str,
    access_url: str | None,
    status: str = "done",
    updated_at: datetime,
) -> CodexTask:
    return CodexTask(
        id=task_id,
        session_id="project-1",
        project_id="project-1",
        title="Analyze startup",
        prompt="Analyze",
        role="operations_engineer",
        status=status,
        task_kind="project_script_suggestion",
        result=json.dumps(
            {"setup_script": "", "run_command": run_command, "access_url": access_url}
        ),
        updated_at=updated_at,
    )


def test_select_project_access_url_requires_latest_successful_command_to_match() -> None:
    tasks = [
        _analysis_task(
            "matching",
            run_command="npm run dev",
            access_url="http://localhost:3000",
            updated_at=datetime(2026, 7, 12, 8, 0, tzinfo=UTC),
        ),
        _analysis_task(
            "newer-mismatch",
            run_command="npm run preview",
            access_url="http://localhost:4173",
            updated_at=datetime(2026, 7, 12, 9, 0, tzinfo=UTC),
        ),
        _analysis_task(
            "newest-failed",
            run_command="npm run dev",
            access_url="http://localhost:9999",
            status="failed",
            updated_at=datetime(2026, 7, 12, 10, 0, tzinfo=UTC),
        ),
    ]

    assert select_project_access_url(tasks, "npm run dev") is None
    assert select_project_access_url(tasks, "npm run other") is None


def test_select_project_access_url_ignores_newer_failed_analysis() -> None:
    tasks = [
        _analysis_task(
            "matching",
            run_command="npm run dev",
            access_url="http://localhost:3000",
            updated_at=datetime(2026, 7, 12, 8, 0, tzinfo=UTC),
        ),
        _analysis_task(
            "newer-failed",
            run_command="npm run preview",
            access_url="http://localhost:4173",
            status="failed",
            updated_at=datetime(2026, 7, 12, 9, 0, tzinfo=UTC),
        ),
    ]

    assert select_project_access_url(tasks, "npm run dev") == "http://localhost:3000"


def test_select_project_access_url_does_not_fall_back_when_latest_has_no_url() -> None:
    tasks = [
        _analysis_task(
            "older",
            run_command="npm run dev",
            access_url="http://localhost:3000",
            updated_at=datetime(2026, 7, 12, 8, 0, tzinfo=UTC),
        ),
        _analysis_task(
            "newer",
            run_command="npm run dev",
            access_url=None,
            updated_at=datetime(2026, 7, 12, 9, 0, tzinfo=UTC),
        ),
    ]

    assert select_project_access_url(tasks, "npm run dev") is None


def test_select_project_access_url_does_not_fall_back_when_latest_is_malformed() -> None:
    older = _analysis_task(
        "older",
        run_command="npm run dev",
        access_url="http://localhost:3000",
        updated_at=datetime(2026, 7, 12, 8, 0, tzinfo=UTC),
    )
    malformed = _analysis_task(
        "newer",
        run_command="npm run dev",
        access_url="http://localhost:4000",
        updated_at=datetime(2026, 7, 12, 9, 0, tzinfo=UTC),
    ).model_copy(update={"result": "{"})

    assert select_project_access_url([older, malformed], "npm run dev") is None


class _TaskStore:
    def __init__(self, tasks: list[CodexTask]) -> None:
        self.tasks = {task.id: task for task in tasks}

    async def list_codex_tasks(
        self,
        session_id: str | None = None,
        issue_id: str | None = None,
        project_id: str | None = None,
    ) -> list[JsonObject]:
        del session_id, issue_id
        return [
            task.model_dump(mode="json")
            for task in self.tasks.values()
            if task.project_id == project_id
        ]

    async def load_codex_task(self, task_id: str) -> CodexTask | None:
        return self.tasks.get(task_id)


@pytest.mark.asyncio
async def test_resolve_project_access_url_loads_typed_project_tasks() -> None:
    task = _analysis_task(
        "matching",
        run_command="npm run dev",
        access_url="http://localhost:3000",
        updated_at=datetime(2026, 7, 12, 8, 0, tzinfo=UTC),
    )

    assert (
        await resolve_project_access_url(_TaskStore([task]), "project-1", "npm run dev")
        == "http://localhost:3000"
    )
