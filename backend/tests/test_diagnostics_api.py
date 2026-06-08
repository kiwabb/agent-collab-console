from __future__ import annotations

import asyncio

import pytest

from app.domain.models import (
    RuntimeCatalog,
    RuntimeExecutorConfig,
    RuntimeModelConfig,
    RuntimeProviderConfig,
)


def test_diagnostics_returns_operational_snapshot(client):
    from app.application.project_review_scheduler import reset_project_review_scheduler_status

    reset_project_review_scheduler_status()

    resp = client.get("/api/diagnostics")

    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "agent-collab-console"
    assert body["status"] in {"ok", "degraded"}
    assert body["database"]["status"] == "ok"
    assert body["runtime_catalog"]["status"] == "ok"
    assert body["runtime_catalog"]["executors_total"] >= 1
    assert "global_event_subscribers" in body["websockets"]
    assert "codex_binary_available" in body["executors"]
    assert "real_cli_enabled" in body["config"]
    assert body["project_review_scheduler"]["configured"] is True
    assert body["project_review_scheduler"]["interval_s"] == 3600.0
    assert body["project_review_scheduler"]["limit"] == 25


def test_diagnostics_never_leaks_runtime_api_keys(client):
    from app.application.project_review_scheduler import reset_project_review_scheduler_status

    reset_project_review_scheduler_status()
    catalog = RuntimeCatalog(
        executors=[
            RuntimeExecutorConfig(
                id="secure-executor",
                label="Secure Executor",
                enabled=True,
                executor_type="claude",
                api_key="super-secret-test-key",
                api_endpoint="https://example.test/api",
                default_model="secure-model",
                default_provider_id="secure-provider",
                providers=[
                    RuntimeProviderConfig(
                        id="secure-provider",
                        label="Secure Provider",
                        enabled=True,
                        default_model_id="secure-model",
                        models=[
                            RuntimeModelConfig(
                                id="secure-model",
                                label="Secure Model",
                                enabled=True,
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )
    update = client.put("/api/runtime-catalog", json={"catalog": catalog.model_dump()})
    assert update.status_code == 200, update.text

    resp = client.get("/api/diagnostics")

    assert resp.status_code == 200
    body_text = resp.text
    assert "super-secret-test-key" not in body_text
    executor = resp.json()["runtime_catalog"]["executors"][0]
    assert executor["id"] == "secure-executor"
    assert executor["api_key_configured"] is True


def test_diagnostics_includes_project_review_scheduler_error(client):
    from app.application.project_review_scheduler import (
        reset_project_review_scheduler_status,
        run_project_review_scheduler_loop,
    )

    reset_project_review_scheduler_status()

    async def tick(store, *, event_bus=None, limit=None):
        raise RuntimeError("store temporarily unavailable")

    async def sleep(interval: float) -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            run_project_review_scheduler_loop(
                object(),
                interval_s=11,
                limit=4,
                tick_fn=tick,
                sleep_fn=sleep,
            )
        )

    resp = client.get("/api/diagnostics")

    assert resp.status_code == 200
    scheduler = resp.json()["project_review_scheduler"]
    assert scheduler["interval_s"] == 11
    assert scheduler["limit"] == 4
    assert scheduler["last_error"] == "RuntimeError: store temporarily unavailable"


def test_diagnostics_returns_503_when_store_unavailable(client, monkeypatch):
    from app.interfaces import api as api_module

    monkeypatch.setattr(api_module, "codex_store", None)

    resp = client.get("/api/diagnostics")

    assert resp.status_code == 503
    assert "not available" in resp.json()["detail"]
