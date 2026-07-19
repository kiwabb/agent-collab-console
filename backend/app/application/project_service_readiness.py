"""Application-specific readiness evaluation for loopback project services."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Literal, TypedDict

import httpx

from app.application import timeouts
from app.application.local_service_probe import (
    LocalServiceStatus,
    LocalServiceUrlError,
    canonicalize_local_service_url,
    probe_local_service,
)
from app.domain.models import ProjectReadinessProbe
from app.json_safety import object_dict_or_none, parse_json_value

READINESS_RESPONSE_MAX_BYTES = 64 * 1024
ReadinessState = Literal[
    "ready",
    "unreachable",
    "occupied_unknown",
    "identified_unready",
    "invalid_config",
]


class ApplicationReadinessStatus(TypedDict):
    state: ReadinessState
    url: str | None
    http_status: int | None
    checked_at: str | None
    identity_matched: bool
    error: str | None


class ProjectServiceEvaluation(TypedDict):
    service: LocalServiceStatus
    readiness: ApplicationReadinessStatus


_PARSE_FAILED = object()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def invalid_readiness_status(reason: str) -> ApplicationReadinessStatus:
    return {
        "state": "invalid_config",
        "url": None,
        "http_status": None,
        "checked_at": None,
        "identity_matched": False,
        "error": reason,
    }


def _json_subset_matches(actual: object, expected: object) -> bool:
    if isinstance(expected, bool) or expected is None:
        return actual is expected
    if isinstance(expected, dict):
        actual_object = object_dict_or_none(actual)
        if actual_object is None:
            return False
        return all(
            key in actual_object and _json_subset_matches(actual_object[key], expected_value)
            for key, expected_value in expected.items()
        )
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return False
        return all(
            _json_subset_matches(actual_value, expected_value)
            for actual_value, expected_value in zip(actual, expected, strict=True)
        )
    return type(actual) is type(expected) and actual == expected


def _identity_matches(probe: ProjectReadinessProbe, body: bytes) -> tuple[bool, str | None]:
    identity = probe.identity
    if identity.kind == "text_contains":
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            return False, "malformed_text"
        return (identity.text in text, None if identity.text in text else "identity_mismatch")

    parsed = parse_json_value(body, default=_PARSE_FAILED)
    if parsed is _PARSE_FAILED:
        return False, "malformed_json"
    matched = _json_subset_matches(parsed, identity.expected)
    return matched, None if matched else "identity_mismatch"


async def evaluate_project_service(
    readiness_probe: ProjectReadinessProbe | None,
    *,
    fallback_access_url: str | None = None,
    timeout_s: float | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    max_body_bytes: int = READINESS_RESPONSE_MAX_BYTES,
) -> ProjectServiceEvaluation:
    """Return address occupation and application readiness as separate facts."""

    if readiness_probe is None:
        service = await probe_local_service(
            fallback_access_url,
            timeout_s=timeout_s,
            transport=transport,
        )
        return {
            "service": service,
            "readiness": invalid_readiness_status("readiness_not_configured"),
        }

    checked_at = _now_iso()
    try:
        url = canonicalize_local_service_url(readiness_probe.url)
    except LocalServiceUrlError as exc:
        return {
            "service": {
                "state": "invalid_url",
                "url": None,
                "http_status": None,
                "checked_at": checked_at,
                "error": exc.reason,
            },
            "readiness": {
                **invalid_readiness_status(exc.reason),
                "checked_at": checked_at,
            },
        }

    timeout = timeout_s if timeout_s is not None else timeouts.project_service_probe_timeout_s()
    try:
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
                verify=False,
                transport=transport,
            ) as client:
                async with client.stream(
                    "GET",
                    url,
                    headers={"Accept-Encoding": "identity"},
                ) as response:
                    transport_status: LocalServiceStatus = {
                        "state": "reachable",
                        "url": url,
                        "http_status": response.status_code,
                        "checked_at": checked_at,
                        "error": None,
                    }
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > max_body_bytes:
                            return {
                                "service": transport_status,
                                "readiness": {
                                    "state": "occupied_unknown",
                                    "url": url,
                                    "http_status": response.status_code,
                                    "checked_at": checked_at,
                                    "identity_matched": False,
                                    "error": "response_too_large",
                                },
                            }
                        body.extend(chunk)
                    identity_matched, identity_error = _identity_matches(
                        readiness_probe, bytes(body)
                    )
                    if not identity_matched:
                        readiness_state: ReadinessState = "occupied_unknown"
                        readiness_error = identity_error
                    elif response.status_code != readiness_probe.expected_status:
                        readiness_state = "identified_unready"
                        readiness_error = "unexpected_status"
                    else:
                        readiness_state = "ready"
                        readiness_error = None
                    return {
                        "service": transport_status,
                        "readiness": {
                            "state": readiness_state,
                            "url": url,
                            "http_status": response.status_code,
                            "checked_at": checked_at,
                            "identity_matched": identity_matched,
                            "error": readiness_error,
                        },
                    }
    except (TimeoutError, httpx.TimeoutException):
        error = "timeout"
    except httpx.InvalidURL:
        return {
            "service": {
                "state": "invalid_url",
                "url": None,
                "http_status": None,
                "checked_at": checked_at,
                "error": "invalid_url",
            },
            "readiness": {
                **invalid_readiness_status("invalid_url"),
                "checked_at": checked_at,
            },
        }
    except httpx.RequestError:
        error = "connection_failed"

    return {
        "service": {
            "state": "unreachable",
            "url": url,
            "http_status": None,
            "checked_at": checked_at,
            "error": error,
        },
        "readiness": {
            "state": "unreachable",
            "url": url,
            "http_status": None,
            "checked_at": checked_at,
            "identity_matched": False,
            "error": error,
        },
    }
