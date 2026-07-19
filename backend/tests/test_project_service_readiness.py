from __future__ import annotations

import httpx
import pytest

from app.application.project_service_readiness import evaluate_project_service
from app.domain.models import ProjectReadinessProbe


def _json_probe(expected_status: int = 200) -> ProjectReadinessProbe:
    return ProjectReadinessProbe.model_validate(
        {
            "kind": "http",
            "url": "http://127.0.0.1:8080/api/health/ready",
            "expected_status": expected_status,
            "identity": {
                "kind": "json_subset",
                "expected": {"service": "admin-demo-backend", "status": "ready"},
            },
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 404, 500])
async def test_http_errors_remain_reachable_but_not_ready(status: int) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            status,
            json={"service": "admin-demo-backend", "status": "ready"},
            request=request,
        )
    )

    result = await evaluate_project_service(_json_probe(), transport=transport)

    assert result["service"]["state"] == "reachable"
    assert result["service"]["http_status"] == status
    assert result["readiness"]["state"] == "identified_unready"
    assert result["readiness"]["identity_matched"] is True


@pytest.mark.asyncio
async def test_foreign_http_200_is_occupied_unknown() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"service": "some-other-app", "status": "ready"},
            request=request,
        )
    )

    result = await evaluate_project_service(_json_probe(), transport=transport)

    assert result["service"]["state"] == "reachable"
    assert result["readiness"]["state"] == "occupied_unknown"
    assert result["readiness"]["error"] == "identity_mismatch"


@pytest.mark.asyncio
async def test_json_subset_distinguishes_booleans_from_numbers() -> None:
    probe = ProjectReadinessProbe.model_validate(
        {
            "kind": "http",
            "url": "http://127.0.0.1:8080/ready",
            "expected_status": 200,
            "identity": {"kind": "json_subset", "expected": {"ready": True}},
        }
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"ready": 1}, request=request)
    )

    result = await evaluate_project_service(probe, transport=transport)

    assert result["readiness"]["state"] == "occupied_unknown"


@pytest.mark.asyncio
async def test_admin_demo_readiness_response_passes_json_subset() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "service": "admin-demo-backend",
                "status": "ready",
                "version": "1.0",
            },
            request=request,
        )
    )

    result = await evaluate_project_service(_json_probe(), transport=transport)

    assert result["readiness"]["state"] == "ready"
    assert result["readiness"]["identity_matched"] is True


@pytest.mark.asyncio
async def test_frontend_text_identity_is_independent() -> None:
    probe = ProjectReadinessProbe.model_validate(
        {
            "kind": "http",
            "url": "http://127.0.0.1:5173/",
            "expected_status": 200,
            "identity": {"kind": "text_contains", "text": "Northstar 管理后台"},
        }
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            text="<!doctype html><title>Northstar 管理后台</title>",
            request=request,
        )
    )

    result = await evaluate_project_service(probe, transport=transport)

    assert result["readiness"]["state"] == "ready"


@pytest.mark.asyncio
async def test_malformed_and_oversized_bodies_fail_closed() -> None:
    malformed = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"{", request=request)
    )
    oversized = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"x" * 32, request=request)
    )

    malformed_result = await evaluate_project_service(_json_probe(), transport=malformed)
    oversized_result = await evaluate_project_service(
        _json_probe(),
        transport=oversized,
        max_body_bytes=16,
    )

    assert malformed_result["readiness"]["state"] == "occupied_unknown"
    assert malformed_result["readiness"]["error"] == "malformed_json"
    assert oversized_result["service"]["state"] == "reachable"
    assert oversized_result["readiness"]["error"] == "response_too_large"


@pytest.mark.asyncio
async def test_missing_matcher_is_invalid_even_when_address_is_reachable() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text="anything", request=request)
    )

    result = await evaluate_project_service(
        None,
        fallback_access_url="http://127.0.0.1:8080",
        transport=transport,
    )

    assert result["service"]["state"] == "reachable"
    assert result["readiness"]["state"] == "invalid_config"
    assert result["readiness"]["error"] == "readiness_not_configured"
