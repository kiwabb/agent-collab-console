from __future__ import annotations

import hmac
import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from starlette.requests import HTTPConnection

CONSOLE_AUTH_COOKIE = "console_auth_token"
CONSOLE_AUTH_HEADER = "x-console-token"
_ANONYMOUS_PATHS = frozenset({"/api/health"})
_DEFAULT_ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_LOOPBACK_HOSTS = _DEFAULT_ALLOWED_HOSTS
_DEFAULT_ALLOWED_ORIGINS = frozenset(
    {
        "http://localhost:4000",
        "http://127.0.0.1:4000",
    }
)
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,}$")


class LocalAuthConfigError(RuntimeError):
    """Raised when the local control-plane boundary is not configured safely."""


@dataclass(frozen=True)
class LocalAuthFailure:
    status_code: int
    reason: str


@dataclass(frozen=True)
class LocalAuthConfig:
    token: str
    allowed_hosts: frozenset[str]
    allowed_origins: frozenset[str]


def _csv_env(name: str, default: frozenset[str]) -> frozenset[str]:
    raw = os.getenv(name)
    if raw is None:
        return default
    values = frozenset(value.strip().lower() for value in raw.split(",") if value.strip())
    if not values:
        raise LocalAuthConfigError(f"{name} must contain at least one value")
    return values


def _allowed_hosts() -> frozenset[str]:
    internal_hosts = _csv_env("CONSOLE_INTERNAL_HOSTS", frozenset())
    if any(re.fullmatch(r"[a-z0-9.-]+", host) is None for host in internal_hosts):
        raise LocalAuthConfigError("CONSOLE_INTERNAL_HOSTS contains an invalid hostname")
    allowed_hosts = _csv_env("CONSOLE_ALLOWED_HOSTS", _DEFAULT_ALLOWED_HOSTS)
    if not allowed_hosts.issubset(_LOOPBACK_HOSTS | internal_hosts):
        raise LocalAuthConfigError(
            "CONSOLE_ALLOWED_HOSTS may contain only loopback or declared internal hosts"
        )
    return allowed_hosts


def _allowed_origins() -> frozenset[str]:
    configured = _csv_env("CONSOLE_ALLOWED_ORIGINS", _DEFAULT_ALLOWED_ORIGINS)
    allowed_origin_hosts = _LOOPBACK_HOSTS | _csv_env("CONSOLE_INTERNAL_HOSTS", frozenset())
    normalized: set[str] = set()
    for origin in configured:
        try:
            parsed = urlsplit(origin)
            port = parsed.port
        except ValueError as exc:
            raise LocalAuthConfigError(
                "CONSOLE_ALLOWED_ORIGINS contains an invalid origin"
            ) from exc
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in allowed_origin_hosts
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise LocalAuthConfigError(
                "CONSOLE_ALLOWED_ORIGINS may contain only loopback HTTP origins"
            )
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        normalized.add(f"{parsed.scheme}://{host}{f':{port}' if port is not None else ''}")
    return frozenset(normalized)


def load_local_auth_config() -> LocalAuthConfig:
    token = (os.getenv("CONSOLE_AUTH_TOKEN") or "").strip()
    if _TOKEN_PATTERN.fullmatch(token) is None:
        raise LocalAuthConfigError("CONSOLE_AUTH_TOKEN must be at least 32 URL-safe characters")
    return LocalAuthConfig(
        token=token,
        allowed_hosts=_allowed_hosts(),
        allowed_origins=_allowed_origins(),
    )


def validate_local_auth_startup() -> None:
    load_local_auth_config()


def _request_hostname(connection: HTTPConnection) -> str | None:
    host_header = connection.headers.get("host")
    if not host_header or any(char in host_header for char in ("/", "\\", "@", ",")):
        return None
    try:
        parsed = urlsplit(f"//{host_header}")
        if parsed.username is not None or parsed.password is not None:
            return None
        return parsed.hostname.lower() if parsed.hostname else None
    except ValueError:
        return None


def _presented_token(connection: HTTPConnection) -> str | None:
    header_token = connection.headers.get(CONSOLE_AUTH_HEADER)
    if header_token is not None:
        return header_token
    return connection.cookies.get(CONSOLE_AUTH_COOKIE)


def _boundary_failure(
    connection: HTTPConnection,
    config: LocalAuthConfig,
    *,
    require_origin: bool,
) -> LocalAuthFailure | None:
    hostname = _request_hostname(connection)
    if hostname is None or hostname not in config.allowed_hosts:
        return LocalAuthFailure(status_code=403, reason="host_not_allowed")

    origin = connection.headers.get("origin")
    if origin is None:
        if require_origin:
            return LocalAuthFailure(status_code=403, reason="origin_required")
    elif origin.rstrip("/").lower() not in config.allowed_origins:
        return LocalAuthFailure(status_code=403, reason="origin_not_allowed")
    return None


def authorize_http_request(connection: HTTPConnection) -> LocalAuthFailure | None:
    try:
        config = load_local_auth_config()
    except LocalAuthConfigError:
        return LocalAuthFailure(status_code=503, reason="local_auth_unavailable")

    boundary_failure = _boundary_failure(connection, config, require_origin=False)
    if boundary_failure is not None:
        return boundary_failure
    if connection.url.path in _ANONYMOUS_PATHS:
        return None

    token = _presented_token(connection)
    if token is None or not hmac.compare_digest(token, config.token):
        return LocalAuthFailure(status_code=401, reason="invalid_console_token")
    return None


def authorize_loopback_request(connection: HTTPConnection) -> LocalAuthFailure | None:
    """Apply host restrictions for a capability-authenticated internal endpoint."""
    try:
        config = load_local_auth_config()
    except LocalAuthConfigError:
        return LocalAuthFailure(status_code=503, reason="local_auth_unavailable")
    return _boundary_failure(connection, config, require_origin=False)


def authorize_websocket(connection: HTTPConnection) -> LocalAuthFailure | None:
    try:
        config = load_local_auth_config()
    except LocalAuthConfigError:
        return LocalAuthFailure(status_code=503, reason="local_auth_unavailable")

    boundary_failure = _boundary_failure(connection, config, require_origin=True)
    if boundary_failure is not None:
        return boundary_failure
    token = _presented_token(connection)
    if token is None or not hmac.compare_digest(token, config.token):
        return LocalAuthFailure(status_code=401, reason="invalid_console_token")
    return None
