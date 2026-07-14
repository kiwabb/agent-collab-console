from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    field_validator,
    model_validator,
)

from app.application import timeouts
from app.application.mcp_registry import MCP_PROTOCOL_VERSION
from app.application.prototype_generation_service import PrototypeGenerationError
from app.application.prototype_planning_service import PrototypePlanError
from app.application.prototype_service import PrototypeError
from app.bootstrap import (
    project_startup_mcp_service,
    prototype_generation_service,
    prototype_plan_service,
    prototype_planning_mcp_service,
    prototype_service,
)
from app.domain.project_evidence import EvidenceKind, SurfaceKind
from app.domain.prototype_generation import (
    GenerationItemPhase,
    GenerationItemStatus,
    GenerationRunStatus,
)
from app.domain.prototype_plan import (
    PlanAction,
    PlanConfidence,
    PlanDiscoveryOrigin,
    PlanOutputLocale,
    PlanReviewStatus,
    PlanStatus,
)

router = APIRouter(prefix="/api")

PROTOTYPE_CONTRACT_VERSION: Literal[1] = 1
SSE_HEARTBEAT_INTERVAL_S = 10.0
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.post("/internal/prototype-planning-mcp")
async def prototype_planning_mcp(request: Request) -> Response:
    if prototype_planning_mcp_service is None:
        return JSONResponse(status_code=503, content={"error": "prototype planning MCP unavailable"})
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(status_code=400, content={"error": "invalid JSON"})
    status, body = await prototype_planning_mcp_service.handle(
        token=request.headers.get("X-Prototype-Planning-Token"),
        payload=payload,
    )
    if body is None:
        return Response(status_code=status)
    return JSONResponse(
        status_code=status,
        content=body,
        headers={"MCP-Protocol-Version": MCP_PROTOCOL_VERSION},
    )


@router.post("/internal/project-startup-mcp")
async def project_startup_mcp(request: Request) -> Response:
    if project_startup_mcp_service is None:
        return JSONResponse(status_code=503, content={"error": "project startup MCP unavailable"})
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(status_code=400, content={"error": "invalid JSON"})
    status, body = await project_startup_mcp_service.handle(
        token=request.headers.get("X-Project-Startup-Token"),
        payload=payload,
    )
    if body is None:
        return Response(status_code=status)
    return JSONResponse(
        status_code=status,
        content=body,
        headers={"MCP-Protocol-Version": MCP_PROTOCOL_VERSION},
    )


class StrictPrototypeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PrototypeProjectContext(StrictPrototypeModel):
    product_summary: str
    audience: str
    visual_language: str
    shared_layout: str


class PrototypePlanScopeResponse(StrictPrototypeModel):
    packages: list[str] = Field(default_factory=list)
    supported_packages: list[str] = Field(default_factory=list)
    candidate_count: int = Field(default=0, ge=0)


class PrototypePlanEvidenceResponse(StrictPrototypeModel):
    evidence_id: str = Field(min_length=1, max_length=200)
    kind: EvidenceKind
    path: str = Field(min_length=1, max_length=2_000)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    detail: str = Field(max_length=4_000)
    content: str = Field(max_length=12_000)
    confidence: PlanConfidence
    diagnostic: str | None = Field(max_length=4_000)

    @model_validator(mode="after")
    def validate_line_range(self) -> PrototypePlanEvidenceResponse:
        if self.end_line < self.start_line:
            raise ValueError("prototype evidence end line must not precede its start line")
        return self


class CreatePrototypePlanBody(StrictPrototypeModel):
    global_instruction: str = ""
    output_locale: PlanOutputLocale = "zh-CN"


class PatchPrototypePlanBody(StrictPrototypeModel):
    global_instruction: str | None = None
    project_context: PrototypeProjectContext | None = None


class PatchPrototypePlanItemBody(StrictPrototypeModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, min_length=1, max_length=2_000)
    brief: str | None = Field(default=None, min_length=1, max_length=12_000)
    states: list[str] | None = Field(default=None, min_length=1, max_length=12)
    selected: bool | None = None


class PatchPrototypePlanSelectionBody(StrictPrototypeModel):
    item_ids: list[StrictStr] = Field(min_length=1, max_length=500)
    selected: StrictBool

    @field_validator("item_ids")
    @classmethod
    def validate_item_ids(cls, item_ids: list[str]) -> list[str]:
        if any(not item_id.strip() for item_id in item_ids):
            raise ValueError("prototype plan item IDs must not be blank")
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("prototype plan item IDs must be unique")
        return item_ids


class GeneratePrototypePlanBody(StrictPrototypeModel):
    expected_updated_at: str | None = None


class RetryPrototypePlanBody(StrictPrototypeModel):
    run_id: str


class PrototypePlanCreateResponse(StrictPrototypeModel):
    plan_id: str
    status: PlanStatus


class PrototypePlanItemResponse(StrictPrototypeModel):
    id: str
    plan_id: str
    candidate_id: str
    package_root: str
    surface_kind: SurfaceKind
    route_patterns: list[str]
    primary_source_path: str | None
    source_paths: list[str]
    layout_paths: list[str]
    title: str
    summary: str
    brief: str
    states: list[str]
    evidence_ids: list[str]
    evidence: list[PrototypePlanEvidenceResponse]
    confidence: PlanConfidence
    action: PlanAction
    selected: bool
    source_hash: str
    discovery_origin: PlanDiscoveryOrigin
    review_status: PlanReviewStatus
    prototype_id: str | None
    created_at: str | None
    updated_at: str | None


class PrototypePlanResponse(StrictPrototypeModel):
    contract_version: Literal[1]
    id: str
    project_id: str
    status: PlanStatus
    repository_fingerprint: str
    scope: PrototypePlanScopeResponse
    project_context: PrototypeProjectContext
    global_instruction: str
    output_locale: PlanOutputLocale
    analysis_phase: Literal[
        "queued", "scanning", "planning", "validating", "stale", "complete", "failed"
    ]
    analysis_completed: int = Field(ge=0)
    analysis_total: int = Field(ge=0)
    diagnostics: list[str]
    error_message: str | None
    created_at: str | None
    updated_at: str | None
    items: list[PrototypePlanItemResponse]


class PrototypeGenerationRunItemResponse(StrictPrototypeModel):
    id: str
    run_id: str
    plan_item_id: str
    prototype_id: str | None
    status: GenerationItemStatus
    title: str
    attempt: int = Field(ge=0)
    phase: GenerationItemPhase
    output_chars: int = Field(ge=0)
    last_event_at: str | None
    status_message: str
    task_id: str | None
    execution_process_id: str | None
    error_message: str | None
    version_no: int | None
    started_at: str | None
    completed_at: str | None
    created_at: str | None
    updated_at: str | None


class PrototypeGenerationRunResponse(StrictPrototypeModel):
    contract_version: Literal[1]
    id: str
    plan_id: str
    project_id: str
    status: GenerationRunStatus
    repository_fingerprint: str
    total: int = Field(ge=0)
    processed: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)
    running: int = Field(ge=0)
    pending: int = Field(ge=0)
    error_message: str | None
    started_at: str | None
    completed_at: str | None
    created_at: str | None
    updated_at: str | None
    items: list[PrototypeGenerationRunItemResponse]


class PrototypeGenerationCreateResponse(StrictPrototypeModel):
    run_id: str
    status: GenerationRunStatus


class PrototypeFeatureConfigResponse(StrictPrototypeModel):
    enabled: bool


class PrototypeStreamHeartbeatResponse(StrictPrototypeModel):
    contract_version: Literal[1]
    resource_id: str = Field(min_length=1, max_length=200)
    sent_at: datetime


def _to_event(event: str, data: dict[str, object], *, event_id: str) -> str:
    return f"id: {event_id}\nevent: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _snapshot_event_id(resource_id: str, data: dict[str, object]) -> str:
    updated_at = data.get("updated_at")
    revision = updated_at if isinstance(updated_at, str) else "initial"
    return f"{resource_id}:{revision}"


def _serialize_stream_event(event: str, data: object) -> str:
    payload = dict(data) if isinstance(data, Mapping) else {}
    return _to_event(
        event,
        payload,
        event_id=f"prototype:{event}:{time.time_ns()}",
    )


async def _stream_contract_events(
    source: AsyncIterator[dict[str, object]],
    *,
    resource_id: str,
    validate_snapshot: Callable[[object], StrictPrototypeModel],
) -> AsyncIterator[str]:
    last_snapshot_id: str | None = None
    last_heartbeat = time.monotonic()
    async for event in source:
        event_name = event.get("event")
        if event_name != "snapshot":
            raise RuntimeError(f"unsupported prototype stream event: {event_name!r}")
        snapshot = validate_snapshot(event.get("data")).model_dump(mode="json")
        if snapshot.get("id") != resource_id:
            raise RuntimeError("prototype stream snapshot resource identity mismatch")
        event_id = _snapshot_event_id(resource_id, snapshot)
        if event_id != last_snapshot_id:
            yield _to_event("snapshot", snapshot, event_id=event_id)
            last_snapshot_id = event_id
        now = time.monotonic()
        if now - last_heartbeat >= SSE_HEARTBEAT_INTERVAL_S:
            heartbeat = PrototypeStreamHeartbeatResponse(
                contract_version=PROTOTYPE_CONTRACT_VERSION,
                resource_id=resource_id,
                sent_at=datetime.now(),
            ).model_dump(mode="json")
            yield _to_event(
                "heartbeat",
                heartbeat,
                event_id=f"{resource_id}:heartbeat:{heartbeat['sent_at']}",
            )
            last_heartbeat = now


def _plan_not_found(exc: PrototypePlanError) -> HTTPException:
    if exc.code == "not_found":
        return HTTPException(status_code=404, detail=str(exc))
    if exc.code == "conflict":
        return HTTPException(status_code=409, detail=str(exc))
    if str(exc).startswith("project not found") or str(exc).startswith("prototype plan not found"):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def _generation_error(exc: PrototypeGenerationError) -> HTTPException:
    message = str(exc)
    if "not found" in message:
        return HTTPException(status_code=404, detail=message)
    if "unavailable" in message or "no usable LLM executor" in message:
        return HTTPException(status_code=503, detail=message)
    return HTTPException(status_code=409, detail=message)


def _ensure_project_generation_enabled() -> None:
    if not timeouts.prototype_generation_enabled():
        raise HTTPException(status_code=503, detail="project prototype generation is disabled")


@router.get("/prototype-plans/config", response_model=PrototypeFeatureConfigResponse)
async def get_prototype_plan_config() -> PrototypeFeatureConfigResponse:
    return PrototypeFeatureConfigResponse(enabled=timeouts.prototype_generation_enabled())


@router.post(
    "/projects/{project_id}/prototype-plans",
    status_code=202,
    response_model=PrototypePlanCreateResponse,
)
async def create_prototype_plan(
    project_id: str, body: CreatePrototypePlanBody | None = None
) -> PrototypePlanCreateResponse:
    _ensure_project_generation_enabled()
    if prototype_plan_service is None:
        raise HTTPException(status_code=503, detail="prototype planning service unavailable")
    try:
        plan = await prototype_plan_service.create_plan(
            project_id,
            global_instruction=body.global_instruction if body is not None else "",
            output_locale=body.output_locale if body is not None else "zh-CN",
        )
    except PrototypePlanError as exc:
        raise _plan_not_found(exc) from exc
    return PrototypePlanCreateResponse(plan_id=plan.id, status=plan.status)


@router.get("/prototype-plans/{plan_id}", response_model=PrototypePlanResponse)
async def get_prototype_plan(plan_id: str) -> PrototypePlanResponse:
    if prototype_plan_service is None:
        raise HTTPException(status_code=503, detail="prototype planning service unavailable")
    try:
        plan, items = await prototype_plan_service.get_plan(plan_id)
    except PrototypePlanError as exc:
        raise _plan_not_found(exc) from exc
    return PrototypePlanResponse.model_validate(plan.to_dict(items))


@router.get(
    "/projects/{project_id}/prototype-plans/latest",
    response_model=PrototypePlanResponse | None,
)
async def get_latest_prototype_plan(project_id: str) -> PrototypePlanResponse | None:
    if prototype_plan_service is None:
        raise HTTPException(status_code=503, detail="prototype planning service unavailable")
    try:
        loaded = await prototype_plan_service.get_latest_plan_for_project(project_id)
    except PrototypePlanError as exc:
        raise _plan_not_found(exc) from exc
    if loaded is None:
        return None
    plan, items = loaded
    return PrototypePlanResponse.model_validate(plan.to_dict(items))


@router.patch("/prototype-plans/{plan_id}", response_model=PrototypePlanResponse)
async def patch_prototype_plan(plan_id: str, body: PatchPrototypePlanBody) -> PrototypePlanResponse:
    if prototype_plan_service is None:
        raise HTTPException(status_code=503, detail="prototype planning service unavailable")
    try:
        plan, items = await prototype_plan_service.patch_plan(
            plan_id,
            global_instruction=body.global_instruction,
            project_context=(
                body.project_context.model_dump() if body.project_context is not None else None
            ),
        )
    except PrototypePlanError as exc:
        raise _plan_not_found(exc) from exc
    return PrototypePlanResponse.model_validate(plan.to_dict(items))


@router.patch("/prototype-plan-items/{item_id}", response_model=PrototypePlanResponse)
async def patch_prototype_plan_item(
    item_id: str, body: PatchPrototypePlanItemBody
) -> PrototypePlanResponse:
    if prototype_plan_service is None:
        raise HTTPException(status_code=503, detail="prototype planning service unavailable")
    try:
        plan, items = await prototype_plan_service.patch_item(
            item_id,
            title=body.title,
            summary=body.summary,
            brief=body.brief,
            states=body.states,
            selected=body.selected,
        )
    except PrototypePlanError as exc:
        raise _plan_not_found(exc) from exc
    return PrototypePlanResponse.model_validate(plan.to_dict(items))


@router.patch(
    "/prototype-plans/{plan_id}/selection",
    response_model=PrototypePlanResponse,
)
async def patch_prototype_plan_selection(
    plan_id: str,
    body: PatchPrototypePlanSelectionBody,
) -> PrototypePlanResponse:
    if prototype_plan_service is None:
        raise HTTPException(status_code=503, detail="prototype planning service unavailable")
    try:
        plan, items = await prototype_plan_service.patch_selection(
            plan_id,
            item_ids=body.item_ids,
            selected=body.selected,
        )
    except PrototypePlanError as exc:
        raise _plan_not_found(exc) from exc
    return PrototypePlanResponse.model_validate(plan.to_dict(items))


@router.post(
    "/prototype-plans/{plan_id}/reanalyze",
    status_code=202,
    response_model=PrototypePlanCreateResponse,
)
async def reanalyze_prototype_plan(plan_id: str) -> PrototypePlanCreateResponse:
    _ensure_project_generation_enabled()
    if prototype_plan_service is None:
        raise HTTPException(status_code=503, detail="prototype planning service unavailable")
    try:
        plan = await prototype_plan_service.retry_analysis(plan_id)
    except PrototypePlanError as exc:
        raise _plan_not_found(exc) from exc
    return PrototypePlanCreateResponse(plan_id=plan.id, status=plan.status)


@router.get("/prototype-plans/{plan_id}/events")
async def stream_prototype_plan(plan_id: str) -> StreamingResponse:
    if prototype_plan_service is None:
        raise HTTPException(status_code=503, detail="prototype planning service unavailable")
    try:
        await prototype_plan_service.get_plan(plan_id)
    except PrototypePlanError as exc:
        raise _plan_not_found(exc) from exc

    async def event_iter() -> AsyncIterator[str]:
        async for frame in _stream_contract_events(
            prototype_plan_service.stream_events(plan_id),
            resource_id=plan_id,
            validate_snapshot=PrototypePlanResponse.model_validate,
        ):
            yield frame

    return StreamingResponse(event_iter(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post(
    "/prototype-plans/{plan_id}/generate",
    status_code=202,
    response_model=PrototypeGenerationCreateResponse,
)
async def generate_prototype_plan(
    plan_id: str, body: GeneratePrototypePlanBody
) -> PrototypeGenerationCreateResponse:
    _ensure_project_generation_enabled()
    if prototype_generation_service is None:
        raise HTTPException(status_code=503, detail="prototype generation service unavailable")
    try:
        run = await prototype_generation_service.create_run(
            plan_id, expected_updated_at=body.expected_updated_at
        )
    except PrototypeGenerationError as exc:
        raise _generation_error(exc) from exc
    return PrototypeGenerationCreateResponse(run_id=run.id, status=run.status)


@router.get(
    "/prototype-generation-runs/{run_id}",
    response_model=PrototypeGenerationRunResponse,
)
async def get_prototype_generation_run(run_id: str) -> PrototypeGenerationRunResponse:
    if prototype_generation_service is None:
        raise HTTPException(status_code=503, detail="prototype generation service unavailable")
    try:
        run, items = await prototype_generation_service.get_run(run_id)
    except PrototypeGenerationError as exc:
        raise _generation_error(exc) from exc
    return PrototypeGenerationRunResponse.model_validate(run.to_dict(items))


@router.get(
    "/prototype-plans/{plan_id}/generation-run",
    response_model=PrototypeGenerationRunResponse | None,
)
async def get_latest_prototype_generation_run(
    plan_id: str,
) -> PrototypeGenerationRunResponse | None:
    if prototype_generation_service is None:
        raise HTTPException(status_code=503, detail="prototype generation service unavailable")
    loaded = await prototype_generation_service.store.load_latest_prototype_generation_run_for_plan(
        plan_id
    )
    if loaded is None:
        return None
    run, items = loaded
    return PrototypeGenerationRunResponse.model_validate(run.to_dict(items))


@router.get("/prototype-generation-runs/{run_id}/events")
async def stream_prototype_generation_run(run_id: str) -> StreamingResponse:
    if prototype_generation_service is None:
        raise HTTPException(status_code=503, detail="prototype generation service unavailable")
    try:
        await prototype_generation_service.get_run(run_id)
    except PrototypeGenerationError as exc:
        raise _generation_error(exc) from exc

    async def event_iter() -> AsyncIterator[str]:
        async for frame in _stream_contract_events(
            prototype_generation_service.stream_events(run_id),
            resource_id=run_id,
            validate_snapshot=PrototypeGenerationRunResponse.model_validate,
        ):
            yield frame

    return StreamingResponse(event_iter(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post(
    "/prototype-plans/{plan_id}/retry",
    status_code=202,
    response_model=PrototypeGenerationCreateResponse,
)
async def retry_prototype_plan(
    plan_id: str, body: RetryPrototypePlanBody
) -> PrototypeGenerationCreateResponse:
    _ensure_project_generation_enabled()
    if prototype_generation_service is None:
        raise HTTPException(status_code=503, detail="prototype generation service unavailable")
    try:
        run = await prototype_generation_service.retry(plan_id, body.run_id)
    except PrototypeGenerationError as exc:
        raise _generation_error(exc) from exc
    return PrototypeGenerationCreateResponse(run_id=run.id, status=run.status)


@router.get("/projects/{project_id}/prototypes")
async def list_prototypes(project_id: str) -> object:
    if prototype_service is None:
        raise HTTPException(status_code=503, detail="prototype service unavailable")
    # Confirm project exists.
    project = await prototype_service.store.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")
    return await prototype_service.list_for_project(project_id)


@router.post("/projects/{project_id}/prototypes", status_code=201)
async def create_prototype(project_id: str, body: dict[str, object]) -> object:
    if prototype_service is None:
        raise HTTPException(status_code=503, detail="prototype service unavailable")
    # Keep behavior deterministic for missing project.
    project = await prototype_service.store.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")

    title = str(body.get("title") or "").strip()
    brief = str(body.get("brief") or "").strip()
    if not brief:
        raise HTTPException(status_code=400, detail="brief is required")
    return await prototype_service.create(project_id, title, brief)


@router.get("/prototypes/{prototype_id}")
async def get_prototype(prototype_id: str) -> object:
    if prototype_service is None:
        raise HTTPException(status_code=503, detail="prototype service unavailable")
    try:
        return await prototype_service.get_with_versions(prototype_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/prototypes/{prototype_id}/versions/{version_no}")
async def get_prototype_version(prototype_id: str, version_no: int) -> dict[str, object]:
    if prototype_service is None:
        raise HTTPException(status_code=503, detail="prototype service unavailable")
    html = await prototype_service.get_version_html(
        prototype_id,
        version_no,
    )
    return {
        "prototype_id": prototype_id,
        "version_no": version_no,
        "html": html,
    }


@router.delete("/prototypes/{prototype_id}")
async def delete_prototype(prototype_id: str) -> dict[str, str]:
    if prototype_service is None:
        raise HTTPException(status_code=503, detail="prototype service unavailable")
    try:
        await prototype_service.delete(prototype_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": prototype_id}


@router.get("/prototypes/{prototype_id}/stream")
async def stream_prototype(prototype_id: str, instruction: str | None = None) -> StreamingResponse:
    if prototype_service is None:
        raise HTTPException(status_code=503, detail="prototype service unavailable")

    try:
        await prototype_service.get(prototype_id)
    except PrototypeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def event_iter() -> AsyncIterator[str]:
        try:
            async for ev in prototype_service.stream_events(prototype_id, instruction):
                yield _serialize_stream_event(ev.event, ev.data)
                if ev.event in {"done", "error"}:
                    return
        except Exception as exc:
            yield _serialize_stream_event("error", {"message": str(exc)})

    return StreamingResponse(event_iter(), media_type="text/event-stream")


@router.get("/projects/{project_id}/prototypes/regenerate-all/stream")
async def regenerate_all_prototypes(project_id: str) -> StreamingResponse:
    if prototype_service is None:
        raise HTTPException(status_code=503, detail="prototype service unavailable")
    project = await prototype_service.store.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")

    async def event_iter() -> AsyncIterator[str]:
        async for ev in prototype_service.regenerate_all_stream(project_id):
            yield _serialize_stream_event(ev.event, ev.data)

    return StreamingResponse(event_iter(), media_type="text/event-stream")
