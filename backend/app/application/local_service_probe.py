"""Safe, local-only HTTP reachability checks for project startup URLs."""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal, Protocol, TypedDict
from urllib.parse import SplitResult, urlsplit, urlunsplit

import httpx

from app.application import timeouts
from app.application.project_run_manager import RunStatus
from app.application.task_statuses import is_task_success_status
from app.domain.models import CodexTask
from app.json_safety import JsonObject

LocalServiceState = Literal[
    "reachable",
    "unreachable",
    "not_configured",
    "invalid_url",
    "unknown",
]


class LocalServiceStatus(TypedDict):
    state: LocalServiceState
    url: str | None
    http_status: int | None
    checked_at: str | None
    error: str | None


class ProjectRunStatusPayload(TypedDict):
    running: bool
    command: str | None
    pid: int | None
    started_at: str | None
    exit_code: int | None
    service: LocalServiceStatus


class LocalServiceUrlError(ValueError):
    """Raised when a candidate URL is not an allowed local service target."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ProjectStartupTaskStore(Protocol):
    async def list_codex_tasks(
        self,
        session_id: str | None = None,
        issue_id: str | None = None,
        project_id: str | None = None,
    ) -> list[JsonObject]: ...

    async def load_codex_task(self, task_id: str) -> CodexTask | None: ...


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_netloc(parts: SplitResult, host: str) -> str:
    try:
        port = parts.port
    except ValueError as exc:
        raise LocalServiceUrlError("invalid_port") from exc
    rendered_host = f"[{host}]" if ":" in host else host
    return rendered_host if port is None else f"{rendered_host}:{port}"


def canonicalize_local_service_url(raw_url: str) -> str:
    """Validate and rebuild a loopback HTTP(S) URL before making a request."""

    if any(not character.isprintable() for character in raw_url):
        raise LocalServiceUrlError("invalid_url")
    value = raw_url.strip()
    if not value:
        raise LocalServiceUrlError("missing_url")
    try:
        parts = urlsplit(value)
        host = parts.hostname
    except ValueError as exc:
        raise LocalServiceUrlError("invalid_url") from exc
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise LocalServiceUrlError("scheme_not_allowed")
    if parts.username is not None or parts.password is not None:
        raise LocalServiceUrlError("userinfo_not_allowed")
    if host is None or not host:
        raise LocalServiceUrlError("host_required")
    host = host.lower()
    if host == "0.0.0.0":
        host = "127.0.0.1"
    elif host == "::":
        host = "::1"
    elif host != "localhost":
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise LocalServiceUrlError("host_not_loopback")
        except ValueError as exc:
            raise LocalServiceUrlError("host_not_loopback") from exc
    netloc = _canonical_netloc(parts, host)
    return urlunsplit((scheme, netloc, parts.path, parts.query, ""))


def _not_configured() -> LocalServiceStatus:
    return {
        "state": "not_configured",
        "url": None,
        "http_status": None,
        "checked_at": None,
        "error": None,
    }


def unknown_local_service_status(reason: str) -> LocalServiceStatus:
    return {
        "state": "unknown",
        "url": None,
        "http_status": None,
        "checked_at": None,
        "error": reason,
    }


def add_service_status(
    run_status: RunStatus, service: LocalServiceStatus
) -> ProjectRunStatusPayload:
    return {
        "running": run_status["running"],
        "command": run_status["command"],
        "pid": run_status["pid"],
        "started_at": run_status["started_at"],
        "exit_code": run_status["exit_code"],
        "service": service,
    }


def _task_timestamp(task: CodexTask) -> float:
    timestamp = task.updated_at or task.created_at
    return timestamp.timestamp() if timestamp is not None else 0.0


def select_project_access_url(tasks: Sequence[CodexTask], run_command: str | None) -> str | None:
    """Select a URL from the newest successful analysis for the current command."""

    current_command = (run_command or "").strip()
    if not current_command:
        return None
    # Import lazily because project_script_suggestions reuses this probe for
    # its launch verification path.
    from app.application.project_script_suggestions import parse_project_script_suggestion

    successful = [
        task
        for task in tasks
        if task.task_kind == "project_script_suggestion"
        and task.role == "operations_engineer"
        and is_task_success_status(task.status)
    ]
    if not successful:
        return None
    latest = max(successful, key=_task_timestamp)
    if not latest.result:
        return None
    suggestion = parse_project_script_suggestion(latest.result)
    if suggestion is None or suggestion.run_command.strip() != current_command:
        return None
    access_url = suggestion.access_url
    return access_url.strip() if access_url and access_url.strip() else None


async def resolve_project_access_url(
    store: ProjectStartupTaskStore,
    project_id: str,
    run_command: str | None,
) -> str | None:
    """Load typed task rows before selecting an access URL at the DB boundary."""

    rows = await store.list_codex_tasks(project_id=project_id)
    candidates: list[CodexTask] = []
    for row in rows:
        if row.get("task_kind") != "project_script_suggestion":
            continue
        if row.get("role") != "operations_engineer":
            continue
        if not is_task_success_status(row.get("status")):
            continue
        task_id = row.get("id")
        if not isinstance(task_id, str) or not task_id:
            continue
        task = await store.load_codex_task(task_id)
        if task is not None:
            candidates.append(task)
    return select_project_access_url(candidates, run_command)


async def probe_local_service(
    raw_url: str | None,
    *,
    timeout_s: float | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> LocalServiceStatus:
    """Return reachability without reading response bodies or following redirects."""

    if raw_url is None or not raw_url.strip():
        return _not_configured()
    checked_at = _now_iso()
    try:
        url = canonicalize_local_service_url(raw_url)
    except LocalServiceUrlError as exc:
        return {
            "state": "invalid_url",
            "url": None,
            "http_status": None,
            "checked_at": checked_at,
            "error": exc.reason,
        }

    timeout = timeout_s if timeout_s is not None else timeouts.project_service_probe_timeout_s()
    try:
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
                # This check proves loopback reachability, not server identity. Local
                # dev HTTPS commonly uses self-signed certificates.
                verify=False,
                transport=transport,
            ) as client:
                async with client.stream("GET", url) as response:
                    return {
                        "state": "reachable",
                        "url": url,
                        "http_status": response.status_code,
                        "checked_at": checked_at,
                        "error": None,
                    }
    except (TimeoutError, httpx.TimeoutException):
        return {
            "state": "unreachable",
            "url": url,
            "http_status": None,
            "checked_at": checked_at,
            "error": "timeout",
        }
    except httpx.InvalidURL:
        return {
            "state": "invalid_url",
            "url": None,
            "http_status": None,
            "checked_at": checked_at,
            "error": "invalid_url",
        }
    except httpx.RequestError:
        return {
            "state": "unreachable",
            "url": url,
            "http_status": None,
            "checked_at": checked_at,
            "error": "connection_failed",
        }
