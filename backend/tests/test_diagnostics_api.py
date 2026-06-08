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
    from app.application.github_pr_followup import reset_github_pr_followup_status
    from app.application.project_review_scheduler import reset_project_review_scheduler_status

    reset_github_pr_followup_status()
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
    assert body["github_pr_followup"]["configured"] is True
    assert body["github_pr_followup"]["running"] is False
    assert body["github_pr_followup"]["sweep_count"] == 0
    assert body["github_pr_followup"]["last_summary_counts"] == {}


def test_diagnostics_never_leaks_runtime_api_keys(client):
    from app.application.github_pr_followup import reset_github_pr_followup_status
    from app.application.project_review_scheduler import reset_project_review_scheduler_status

    reset_github_pr_followup_status()
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
    from app.application.github_pr_followup import reset_github_pr_followup_status
    from app.application.project_review_scheduler import (
        reset_project_review_scheduler_status,
        run_project_review_scheduler_loop,
    )

    reset_github_pr_followup_status()
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
    body = resp.json()
    assert body["status"] == "degraded"
    assert any(
        check["name"] == "project_review_scheduler"
        and check["status"] == "degraded"
        and check["detail"] == "RuntimeError: store temporarily unavailable"
        for check in body["checks"]
    )


def test_diagnostics_degrades_when_github_pr_followup_is_running(client, monkeypatch):
    from app.application import github_pr_followup
    from app.application.project_review_scheduler import reset_project_review_scheduler_status

    reset_project_review_scheduler_status()
    monkeypatch.setattr(
        github_pr_followup,
        "get_github_pr_followup_status",
        lambda: {
            "configured": True,
            "running": True,
            "sweep_count": 3,
            "last_started_at": "2026-06-08T10:00:00",
            "last_completed_at": None,
            "last_error": None,
            "last_summary_counts": {},
            "auto_merge_enabled": True,
        },
    )

    resp = client.get("/api/diagnostics")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["github_pr_followup"]["running"] is True
    assert any(
        check["name"] == "github_pr_followup"
        and check["status"] == "degraded"
        and check["detail"] == "GitHub PR follow-up sweep is running"
        for check in body["checks"]
    )


def test_diagnostics_degrades_when_project_review_scheduler_is_running(client, monkeypatch):
    from app.application.github_pr_followup import reset_github_pr_followup_status
    from app.application import project_review_scheduler

    reset_github_pr_followup_status()
    monkeypatch.setattr(
        project_review_scheduler,
        "get_project_review_scheduler_status",
        lambda: {
            "configured": True,
            "interval_s": 3600.0,
            "limit": 25,
            "running": True,
            "tick_count": 5,
            "last_started_at": "2026-06-08T10:00:00",
            "last_completed_at": None,
            "last_error": None,
            "last_summary_counts": {},
        },
    )

    resp = client.get("/api/diagnostics")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["project_review_scheduler"]["running"] is True
    assert any(
        check["name"] == "project_review_scheduler"
        and check["status"] == "degraded"
        and check["detail"] == "Project review scheduler is running"
        for check in body["checks"]
    )


def test_diagnostics_returns_503_when_store_unavailable(client, monkeypatch):
    from app.interfaces import api as api_module

    monkeypatch.setattr(api_module, "codex_store", None)

    resp = client.get("/api/diagnostics")

    assert resp.status_code == 503
    assert "not available" in resp.json()["detail"]
