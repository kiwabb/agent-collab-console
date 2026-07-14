from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

import pytest
from pydantic import ValidationError

from app.application.prototype_generation_service import PrototypeGenerationError
from app.application.prototype_planning_service import PrototypePlanError
from app.domain.prototype_generation import PrototypeGenerationRun
from app.domain.prototype_plan import PlanOutputLocale, PrototypePlan, PrototypePlanItem
from app.interfaces.sse import (
    PrototypeGenerationRunResponse,
    PrototypePlanEvidenceResponse,
    PrototypePlanResponse,
    _stream_contract_events,
)


class _FakePlanService:
    def __init__(self) -> None:
        self.plan = PrototypePlan(
            id="plan-api",
            project_id="project-api",
            status="ready",
            repository_fingerprint="sha256:repo",
            project_context={
                "product_summary": "demo",
                "audience": "",
                "visual_language": "",
                "shared_layout": "",
            },
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        self.items: list[PrototypePlanItem] = []
        self.selection_calls: list[tuple[list[str], bool]] = []

    async def create_plan(
        self,
        project_id: str,
        *,
        global_instruction: str = "",
        output_locale: PlanOutputLocale = "zh-CN",
    ) -> PrototypePlan:
        assert project_id == "project-api"
        self.plan.global_instruction = global_instruction
        assert output_locale in {"zh-CN", "en-US"}
        self.plan.output_locale = output_locale
        return self.plan

    async def get_plan(self, plan_id: str) -> tuple[PrototypePlan, list[PrototypePlanItem]]:
        if plan_id != self.plan.id:
            raise PrototypePlanError(f"prototype plan not found: {plan_id}")
        return self.plan, self.items

    async def patch_plan(
        self, plan_id: str, **kwargs: object
    ) -> tuple[PrototypePlan, list[PrototypePlanItem]]:
        assert plan_id == self.plan.id
        instruction = kwargs.get("global_instruction")
        if isinstance(instruction, str):
            self.plan.global_instruction = instruction
        return self.plan, self.items

    async def patch_item(
        self, item_id: str, **kwargs: object
    ) -> tuple[PrototypePlan, list[PrototypePlanItem]]:
        assert item_id == "item-api"
        return self.plan, self.items

    async def patch_selection(
        self,
        plan_id: str,
        *,
        item_ids: list[str],
        selected: bool,
    ) -> tuple[PrototypePlan, list[PrototypePlanItem]]:
        assert plan_id == self.plan.id
        if item_ids == ["missing"]:
            raise PrototypePlanError("prototype plan items not found: missing", code="not_found")
        if item_ids == ["ineligible"]:
            raise PrototypePlanError(
                "prototype plan items are not eligible for generation: ineligible",
                code="conflict",
            )
        self.selection_calls.append((item_ids, selected))
        return self.plan, self.items

    async def stream_events(self, plan_id: str) -> AsyncIterator[dict[str, object]]:
        assert plan_id == self.plan.id
        yield {"event": "snapshot", "data": self.plan.to_dict(self.items)}

    async def retry_analysis(self, plan_id: str) -> PrototypePlan:
        assert plan_id == self.plan.id
        return self.plan


class _FakeGenerationService:
    async def create_run(self, plan_id: str, **kwargs: object) -> PrototypeGenerationRun:
        assert plan_id == "plan-api"
        now = datetime.now()
        return PrototypeGenerationRun(
            id="run-api",
            plan_id=plan_id,
            project_id="project-api",
            status="queued",
            repository_fingerprint="sha256:repo",
            total=1,
            pending=1,
            created_at=now,
            updated_at=now,
        )

    async def get_run(self, run_id: str):
        if run_id != "run-api":
            raise PrototypeGenerationError(f"generation run not found: {run_id}")
        return await self.create_run("plan-api"), []

    async def stream_events(self, run_id: str) -> AsyncIterator[dict[str, object]]:
        run, items = await self.get_run(run_id)
        yield {"event": "snapshot", "data": run.to_dict(items)}

    async def retry(self, plan_id: str, run_id: str):
        assert plan_id == "plan-api"
        assert run_id == "run-api"
        return await self.create_run(plan_id)


def test_create_plan_route_returns_202(client, monkeypatch):
    service = _FakePlanService()
    monkeypatch.setattr("app.interfaces.sse.prototype_plan_service", service)

    response = client.post(
        "/api/projects/project-api/prototype-plans",
        json={"global_instruction": "restore current layout"},
    )

    assert response.status_code == 202
    assert response.json() == {"plan_id": "plan-api", "status": "ready"}


def test_create_plan_route_accepts_empty_body(client, monkeypatch):
    service = _FakePlanService()
    monkeypatch.setattr("app.interfaces.sse.prototype_plan_service", service)

    response = client.post("/api/projects/project-api/prototype-plans")

    assert response.status_code == 202
    assert service.plan.global_instruction == ""


def test_plan_requests_reject_extra_fields_and_partial_project_context(client, monkeypatch):
    service = _FakePlanService()
    monkeypatch.setattr("app.interfaces.sse.prototype_plan_service", service)

    extra = client.post(
        "/api/projects/project-api/prototype-plans",
        json={"unexpected": True},
    )
    partial_context = client.patch(
        "/api/prototype-plans/plan-api",
        json={"project_context": {"product_summary": "demo"}},
    )
    coerced_item_selection = client.patch(
        "/api/prototype-plan-items/item-api",
        json={"selected": "false"},
    )

    assert extra.status_code == 422
    assert partial_context.status_code == 422
    assert coerced_item_selection.status_code == 422


def test_prototype_response_models_reject_numeric_string_coercion() -> None:
    now = datetime.now()
    payload = PrototypeGenerationRun(
        id="run-strict",
        plan_id="plan-strict",
        project_id="project-strict",
        status="queued",
        repository_fingerprint="sha256:repo",
        total=1,
        pending=1,
        created_at=now,
        updated_at=now,
    ).to_dict([])
    payload["total"] = "1"

    with pytest.raises(ValidationError):
        PrototypeGenerationRunResponse.model_validate(payload)


def test_plan_get_patch_and_events_routes_use_typed_contract(client, monkeypatch):
    service = _FakePlanService()
    monkeypatch.setattr("app.interfaces.sse.prototype_plan_service", service)
    monkeypatch.setattr("app.interfaces.sse.SSE_HEARTBEAT_INTERVAL_S", 0.0)

    fetched = client.get("/api/prototype-plans/plan-api")
    patched = client.patch(
        "/api/prototype-plans/plan-api", json={"global_instruction": "keep navigation"}
    )
    streamed = client.get("/api/prototype-plans/plan-api/events")

    assert fetched.status_code == 200
    assert fetched.json()["project_context"]["product_summary"] == "demo"
    assert patched.status_code == 200
    assert patched.json()["global_instruction"] == "keep navigation"
    assert streamed.status_code == 200
    assert streamed.headers["cache-control"] == "no-cache, no-transform"
    assert streamed.headers["x-accel-buffering"] == "no"
    assert "id: plan-api:" in streamed.text
    assert "event: snapshot" in streamed.text
    assert "event: heartbeat" in streamed.text
    assert '"resource_id": "plan-api"' in streamed.text


def test_plan_evidence_response_is_strict_and_typed() -> None:
    payload: dict[str, object] = {
        "evidence_id": "evidence--home",
        "kind": "page-source",
        "path": "src/Home.tsx",
        "start_line": 4,
        "end_line": 8,
        "detail": "bounded source evidence",
        "content": "export function Home() {}",
        "confidence": "high",
        "diagnostic": None,
    }

    parsed = PrototypePlanEvidenceResponse.model_validate(payload)
    assert parsed.confidence == "high"
    assert parsed.diagnostic is None
    with pytest.raises(ValidationError):
        PrototypePlanEvidenceResponse.model_validate({**payload, "kind": "unknown"})
    with pytest.raises(ValidationError):
        PrototypePlanEvidenceResponse.model_validate({**payload, "confidence": "certain"})
    with pytest.raises(ValidationError):
        PrototypePlanEvidenceResponse.model_validate({**payload, "start_line": 9})
    missing_diagnostic = dict(payload)
    del missing_diagnostic["diagnostic"]
    with pytest.raises(ValidationError):
        PrototypePlanEvidenceResponse.model_validate(missing_diagnostic)


@pytest.mark.asyncio
async def test_stream_contract_rejects_snapshot_for_another_resource() -> None:
    service = _FakePlanService()
    payload = service.plan.to_dict(service.items)
    payload["id"] = "plan-other"

    async def source() -> AsyncIterator[dict[str, object]]:
        yield {"event": "snapshot", "data": payload}

    with pytest.raises(RuntimeError, match="resource identity mismatch"):
        _ = [
            frame
            async for frame in _stream_contract_events(
                source(),
                resource_id="plan-api",
                validate_snapshot=PrototypePlanResponse.model_validate,
            )
        ]


def test_bulk_selection_route_uses_strict_atomic_contract(client, monkeypatch):
    service = _FakePlanService()
    monkeypatch.setattr("app.interfaces.sse.prototype_plan_service", service)

    updated = client.patch(
        "/api/prototype-plans/plan-api/selection",
        json={"item_ids": ["item-a", "item-b"], "selected": False},
    )
    extra = client.patch(
        "/api/prototype-plans/plan-api/selection",
        json={"item_ids": ["item-a"], "selected": False, "unexpected": True},
    )
    duplicate = client.patch(
        "/api/prototype-plans/plan-api/selection",
        json={"item_ids": ["item-a", "item-a"], "selected": False},
    )
    coerced_bool = client.patch(
        "/api/prototype-plans/plan-api/selection",
        json={"item_ids": ["item-a"], "selected": "false"},
    )
    missing = client.patch(
        "/api/prototype-plans/plan-api/selection",
        json={"item_ids": ["missing"], "selected": True},
    )
    ineligible = client.patch(
        "/api/prototype-plans/plan-api/selection",
        json={"item_ids": ["ineligible"], "selected": True},
    )

    assert updated.status_code == 200
    assert updated.json()["contract_version"] == 1
    assert service.selection_calls == [(["item-a", "item-b"], False)]
    assert extra.status_code == 422
    assert duplicate.status_code == 422
    assert coerced_bool.status_code == 422
    assert missing.status_code == 404
    assert ineligible.status_code == 409


def test_plan_unknown_route_returns_404(client, monkeypatch):
    service = _FakePlanService()
    monkeypatch.setattr("app.interfaces.sse.prototype_plan_service", service)

    response = client.get("/api/prototype-plans/missing")

    assert response.status_code == 404


def test_generation_routes_return_run_and_snapshot(client, monkeypatch):
    monkeypatch.setattr("app.interfaces.sse.prototype_generation_service", _FakeGenerationService())
    monkeypatch.setattr("app.interfaces.sse.SSE_HEARTBEAT_INTERVAL_S", 0.0)

    created = client.post("/api/prototype-plans/plan-api/generate", json={})
    fetched = client.get("/api/prototype-generation-runs/run-api")
    streamed = client.get("/api/prototype-generation-runs/run-api/events")
    retried = client.post("/api/prototype-plans/plan-api/retry", json={"run_id": "run-api"})

    assert created.status_code == 202
    assert created.json()["run_id"] == "run-api"
    assert fetched.status_code == 200
    assert fetched.json()["contract_version"] == 1
    assert fetched.json()["pending"] == 1
    assert streamed.status_code == 200
    assert streamed.headers["cache-control"] == "no-cache, no-transform"
    assert streamed.headers["x-accel-buffering"] == "no"
    assert "id: run-api:" in streamed.text
    assert "event: snapshot" in streamed.text
    assert "event: heartbeat" in streamed.text
    assert retried.status_code == 202
