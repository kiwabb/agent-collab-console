from __future__ import annotations

import json
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.application.structured_prototype_generation_contracts import GenerationBlueprintV1
from app.application.structured_prototype_generation_mcp import (
    StructuredPrototypeGenerationMcpService,
)
from app.application.structured_prototype_generation_service import (
    StructuredPrototypeGenerationService,
    StructuredPrototypeGenerationServiceError,
)
from app.domain.structured_prototype_generation import (
    PrototypeDocumentGenerationAcceptResult,
    PrototypeDocumentGenerationItemRecord,
    PrototypeDocumentGenerationSnapshot,
)

GENERATION_HTTP_CONTRACT_VERSION: Literal[1] = 1
structured_prototype_generation_service: StructuredPrototypeGenerationService | None = None
structured_prototype_generation_mcp_service: StructuredPrototypeGenerationMcpService | None = None


def configure_structured_prototype_generation(
    service: StructuredPrototypeGenerationService | None,
    mcp_service: StructuredPrototypeGenerationMcpService | None,
) -> None:
    global structured_prototype_generation_service, structured_prototype_generation_mcp_service
    structured_prototype_generation_service = service
    structured_prototype_generation_mcp_service = mcp_service


def _camel_alias(field_name: str) -> str:
    head, *tail = field_name.split("_")
    return head + "".join(part.capitalize() for part in tail)


class StrictRequestModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel_alias,
        extra="forbid",
        populate_by_name=False,
        strict=True,
    )


class StrictResponseModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel_alias,
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
        strict=True,
    )


class CreateGenerationJobRequestV1(StrictRequestModel):
    contract_version: Literal[1]
    client_request_id: Annotated[str, Field(min_length=36, max_length=36)]
    mode: Literal["requirements"]
    brief: Annotated[str, Field(min_length=1, max_length=8_000)]


class ConfirmGenerationBlueprintRequestV1(StrictRequestModel):
    contract_version: Literal[1]
    client_request_id: Annotated[str, Field(min_length=36, max_length=36)]
    expected_blueprint_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class AcceptGenerationCandidateRequestV1(StrictRequestModel):
    contract_version: Literal[1]
    client_request_id: Annotated[str, Field(min_length=36, max_length=36)]
    expected_candidate_object_hash: Annotated[
        str, Field(pattern=r"^sha256:[0-9a-f]{64}$")
    ]
    expected_preview_output_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class GenerationItemResponseV1(StrictResponseModel):
    id: str
    run_id: str
    kind: Literal["blueprint", "foundation", "page"]
    item_key: str
    page_key: str | None
    status: Literal["pending", "generating", "validating", "done", "failed", "interrupted"]
    phase: str
    task_kind: str
    operation_id: str
    context_object_hash: str
    output_object_hash: str | None
    submission_id: str | None
    submission_normalized_fields: list[str]
    task_id: str | None
    execution_process_id: str | None
    error_code: str | None
    error_message: str | None
    updated_at: str


class GenerationJobResponseV1(StrictResponseModel):
    contract_version: Literal[1]
    id: str
    project_id: str
    status: Literal[
        "queued",
        "planning",
        "awaiting_confirmation",
        "generating",
        "assembling",
        "validating",
        "rendering_preview",
        "ready",
        "accepted",
        "failed",
        "interrupted",
        "cancelled",
    ]
    operation_id: str
    blueprint_version: int
    blueprint_hash: str | None
    blueprint: GenerationBlueprintV1 | None
    candidate_object_hash: str | None
    preview_artifact_id: str | None
    preview_output_hash: str | None
    replay_manifest_object_hash: str | None
    document_id: str | None
    error_code: str | None
    error_message: str | None
    total: int
    processed: int
    succeeded: int
    failed: int
    running: int
    pending: int
    items: list[GenerationItemResponseV1]
    created_at: str
    updated_at: str
    completed_at: str | None
    can_confirm: bool
    can_accept: bool
    preview_path: str | None


class GenerationAcceptResponseV1(StrictResponseModel):
    contract_version: Literal[1]
    job: GenerationJobResponseV1
    document_id: str
    draft_id: str
    checkpoint_id: str
    head_sequence_no: int
    document_hash: str


class GenerationErrorDetailV1(StrictResponseModel):
    code: str
    message: str
    job_id: str | None


class GenerationErrorResponseV1(StrictResponseModel):
    contract_version: Literal[1]
    correlation_id: str
    error: GenerationErrorDetailV1


router = APIRouter(prefix="/api")


@router.post("/internal/structured-prototype-generation-mcp", include_in_schema=False)
async def structured_prototype_generation_mcp(request: Request) -> Response:
    service = structured_prototype_generation_mcp_service
    if service is None:
        return JSONResponse(status_code=503, content={"error": "prototype generation MCP unavailable"})
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(status_code=400, content={"error": "invalid JSON"})
    status, body = await service.handle(
        token=request.headers.get("X-Prototype-Generation-Token"),
        payload=payload,
    )
    if body is None:
        return Response(status_code=status)
    return JSONResponse(
        status_code=status,
        content=body,
        headers={"MCP-Protocol-Version": service.descriptor.protocol_version},
    )


@router.post(
    "/projects/{project_id}/prototype-document-generation-jobs",
    response_model=GenerationJobResponseV1,
    status_code=202,
)
async def create_generation_job(
    project_id: str,
    body: CreateGenerationJobRequestV1,
) -> Response:
    try:
        snapshot = await _require_service().create_requirements_job(
            project_id=project_id,
            client_request_id=body.client_request_id,
            brief=body.brief,
        )
        response = await _job_response(snapshot)
    except StructuredPrototypeGenerationServiceError as exc:
        return _service_failure(exc)
    return JSONResponse(status_code=202, content=response.model_dump(mode="json", by_alias=True))


@router.get(
    "/projects/{project_id}/prototype-document-generation-jobs/current",
    response_model=GenerationJobResponseV1 | None,
)
async def get_current_project_generation_job(project_id: str) -> Response:
    try:
        snapshot = await _require_service().get_latest_project_job(project_id)
        response = await _job_response(snapshot) if snapshot is not None else None
    except StructuredPrototypeGenerationServiceError as exc:
        return _service_failure(exc)
    return JSONResponse(
        content=response.model_dump(mode="json", by_alias=True) if response is not None else None
    )


@router.get(
    "/prototype-document-generation-jobs/{job_id}",
    response_model=GenerationJobResponseV1,
)
async def get_generation_job(job_id: str) -> Response:
    try:
        response = await _job_response(await _require_service().get_job(job_id))
    except StructuredPrototypeGenerationServiceError as exc:
        return _service_failure(exc)
    return JSONResponse(content=response.model_dump(mode="json", by_alias=True))


@router.post(
    "/prototype-document-generation-jobs/{job_id}/confirm",
    response_model=GenerationJobResponseV1,
    status_code=202,
)
async def confirm_generation_blueprint(
    job_id: str,
    body: ConfirmGenerationBlueprintRequestV1,
) -> Response:
    try:
        snapshot = await _require_service().confirm_blueprint(
            job_id=job_id,
            client_request_id=body.client_request_id,
            expected_blueprint_hash=body.expected_blueprint_hash,
        )
        response = await _job_response(snapshot)
    except StructuredPrototypeGenerationServiceError as exc:
        return _service_failure(exc)
    return JSONResponse(status_code=202, content=response.model_dump(mode="json", by_alias=True))


@router.post(
    "/prototype-document-generation-jobs/{job_id}/accept",
    response_model=GenerationAcceptResponseV1,
)
async def accept_generation_candidate(
    job_id: str,
    body: AcceptGenerationCandidateRequestV1,
) -> Response:
    try:
        result = await _require_service().accept_candidate(
            job_id=job_id,
            client_request_id=body.client_request_id,
            expected_candidate_object_hash=body.expected_candidate_object_hash,
            expected_preview_output_hash=body.expected_preview_output_hash,
        )
        response = await _accept_response(result)
    except StructuredPrototypeGenerationServiceError as exc:
        return _service_failure(exc)
    return JSONResponse(content=response.model_dump(mode="json", by_alias=True))


@router.get("/prototype-document-generation-jobs/{job_id}/preview/{relative_path:path}")
async def read_generation_preview(job_id: str, relative_path: str) -> Response:
    media_types = {
        "index.html": "text/html; charset=utf-8",
        "runtime.js": "text/javascript; charset=utf-8",
        "styles.css": "text/css; charset=utf-8",
    }
    if relative_path not in media_types:
        return _error_response(404, "preview_file_missing", "preview file is not available", job_id)
    try:
        content = await _require_service().read_preview_file(job_id, relative_path)
    except StructuredPrototypeGenerationServiceError as exc:
        return _service_failure(exc)
    return Response(content=content, media_type=media_types[relative_path])


async def _job_response(snapshot: PrototypeDocumentGenerationSnapshot) -> GenerationJobResponseV1:
    service = _require_service()
    blueprint = await service.get_blueprint(snapshot.job.id)
    run = snapshot.latest_run
    counts = {
        "total": run.total if run is not None else 0,
        "processed": run.processed if run is not None else 0,
        "succeeded": run.succeeded if run is not None else 0,
        "failed": run.failed if run is not None else 0,
        "running": run.running if run is not None else 0,
        "pending": run.pending if run is not None else 0,
    }
    job = snapshot.job
    return GenerationJobResponseV1(
        contract_version=GENERATION_HTTP_CONTRACT_VERSION,
        id=job.id,
        project_id=job.project_id,
        status=job.status,
        operation_id=job.operation_id,
        blueprint_version=job.blueprint_version,
        blueprint_hash=job.blueprint_hash,
        blueprint=blueprint,
        candidate_object_hash=job.candidate_object_hash,
        preview_artifact_id=job.preview_artifact_id,
        preview_output_hash=job.preview_output_hash,
        replay_manifest_object_hash=job.replay_manifest_object_hash,
        document_id=job.document_id,
        error_code=job.error_code,
        error_message=job.error_message,
        items=[_item_response(item) for item in snapshot.items],
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
        completed_at=job.completed_at.isoformat() if job.completed_at is not None else None,
        can_confirm=job.status == "awaiting_confirmation",
        can_accept=job.status == "ready",
        preview_path=f"/api/prototype-document-generation-jobs/{job.id}/preview/index.html"
        if job.status in {"ready", "accepted"}
        else None,
        **counts,
    )


def _item_response(item: PrototypeDocumentGenerationItemRecord) -> GenerationItemResponseV1:
    return GenerationItemResponseV1(
        id=item.id,
        run_id=item.run_id,
        kind=item.kind,
        item_key=item.item_key,
        page_key=item.page_key,
        status=item.status,
        phase=item.phase,
        task_kind=item.task_kind,
        operation_id=item.operation_id,
        context_object_hash=item.context_object_hash,
        output_object_hash=item.output_object_hash,
        submission_id=item.submission_id,
        submission_normalized_fields=list(item.submission_normalized_fields),
        task_id=item.task_id,
        execution_process_id=item.execution_process_id,
        error_code=item.error_code,
        error_message=item.error_message,
        updated_at=item.updated_at.isoformat(),
    )


async def _accept_response(
    result: PrototypeDocumentGenerationAcceptResult,
) -> GenerationAcceptResponseV1:
    return GenerationAcceptResponseV1(
        contract_version=GENERATION_HTTP_CONTRACT_VERSION,
        job=await _job_response(result.snapshot),
        document_id=result.document.id,
        draft_id=result.draft.id,
        checkpoint_id=result.checkpoint.id,
        head_sequence_no=result.draft.head_sequence_no,
        document_hash=result.draft.head_document_hash,
    )


def _require_service() -> StructuredPrototypeGenerationService:
    if structured_prototype_generation_service is None:
        raise StructuredPrototypeGenerationServiceError(
            "generation_unavailable", "structured prototype generation is unavailable"
        )
    return structured_prototype_generation_service


def _service_failure(exc: StructuredPrototypeGenerationServiceError) -> JSONResponse:
    status = 500
    if exc.code in {"project_missing", "generation_job_missing", "preview_file_missing"}:
        status = 404
    elif exc.code.endswith("_conflict") or exc.code in {
        "generation_job_conflict",
        "generation_candidate_conflict",
        "blueprint_conflict",
    }:
        status = 409
    elif exc.code.endswith("_invalid"):
        status = 422
    elif exc.code == "generation_unavailable":
        status = 503
    return _error_response(status, exc.code, str(exc), exc.job_id)


def _error_response(status: int, code: str, message: str, job_id: str | None) -> JSONResponse:
    body = GenerationErrorResponseV1(
        contract_version=GENERATION_HTTP_CONTRACT_VERSION,
        correlation_id=str(uuid4()),
        error=GenerationErrorDetailV1(code=code, message=message, job_id=job_id),
    )
    return JSONResponse(status_code=status, content=body.model_dump(mode="json", by_alias=True))
