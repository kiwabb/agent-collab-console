from __future__ import annotations

import json
from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.adapters.structured_prototype_store import StructuredPrototypeStoreError
from app.application.structured_prototype_ai_contracts import PrototypeAiSelectionV1
from app.application.structured_prototype_ai_mcp import PrototypeAiMcpService
from app.application.structured_prototype_ai_service import (
    PrototypeAiApplyResult,
    StructuredPrototypeAiService,
    StructuredPrototypeAiServiceError,
)
from app.application.structured_prototype_service import StructuredPrototypeServiceError
from app.domain.structured_prototype_ai import (
    PrototypeAiEditRunRecord,
    PrototypeAiEditRunStatus,
    PrototypeAiMessageRecord,
    PrototypeAiThreadRecord,
    PrototypeAiThreadSnapshot,
)
from app.interfaces.structured_prototype_api import (
    StructuredPrototypeDraftResponseV1,
    _draft_response,
)

AI_HTTP_CONTRACT_VERSION: Literal[1] = 1
structured_prototype_ai_service: StructuredPrototypeAiService | None = None
structured_prototype_ai_mcp_service: PrototypeAiMcpService | None = None


def configure_structured_prototype_ai(
    service: StructuredPrototypeAiService | None,
    mcp_service: PrototypeAiMcpService | None,
) -> None:
    global structured_prototype_ai_service, structured_prototype_ai_mcp_service
    structured_prototype_ai_service = service
    structured_prototype_ai_mcp_service = mcp_service


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


class CreatePrototypeAiThreadRequestV1(StrictRequestModel):
    contract_version: Literal[1]
    client_request_id: Annotated[str, Field(min_length=36, max_length=36)]
    title: Annotated[str, Field(min_length=1, max_length=120)]


class SendPrototypeAiMessageRequestV1(StrictRequestModel):
    contract_version: Literal[1]
    client_message_id: Annotated[str, Field(min_length=36, max_length=36)]
    draft_id: Annotated[str, Field(min_length=1, max_length=128)]
    expected_head_sequence_no: Annotated[int, Field(ge=0)]
    expected_document_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    content: Annotated[str, Field(min_length=1, max_length=8_000)]
    selection: PrototypeAiSelectionV1

    @model_validator(mode="before")
    @classmethod
    def validate_selection_aliases(cls, value: object) -> object:
        if not isinstance(value, dict) or "selection" not in value:
            return value
        validated = PrototypeAiSelectionV1.model_validate(
            value["selection"],
            strict=True,
            by_alias=True,
            by_name=False,
        )
        result = dict(value)
        result["selection"] = validated
        return result


class ApplyPrototypeAiProposalRequestV1(StrictRequestModel):
    contract_version: Literal[1]
    client_request_id: Annotated[str, Field(min_length=36, max_length=36)]
    expected_head_sequence_no: Annotated[int, Field(ge=0)]
    expected_document_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class RejectPrototypeAiProposalRequestV1(StrictRequestModel):
    contract_version: Literal[1]
    client_request_id: Annotated[str, Field(min_length=36, max_length=36)]


class PrototypeAiThreadResponseV1(StrictResponseModel):
    contract_version: Literal[1]
    id: str
    document_id: str
    title: str
    status: Literal["active", "archived"]
    created_at: str
    updated_at: str


class PrototypeAiMessageResponseV1(StrictResponseModel):
    id: str
    role: Literal["user", "assistant"]
    kind: Literal["instruction", "answer", "clarification", "proposal", "error"]
    content: str
    run_id: str | None
    command_batch_id: str | None
    status: Literal["pending", "completed", "failed", "rejected", "applied"]
    created_at: str
    updated_at: str


class PrototypeAiEditRunResponseV1(StrictResponseModel):
    contract_version: Literal[1]
    id: str
    thread_id: str
    user_message_id: str
    assistant_message_id: str | None
    document_id: str
    draft_id: str
    operation_id: str
    status: PrototypeAiEditRunStatus
    base_head_sequence_no: int
    base_document_hash: str
    context_object_hash: str | None
    outcome_object_hash: str | None
    submission_id: str | None
    submission_request_hash: str | None
    submission_accepted_at: str | None
    replay_manifest_object_hash: str | None
    proposed_command_batch_hash: str | None
    candidate_object_hash: str | None
    preview_render_run_id: str | None
    preview_artifact_id: str | None
    preview_path: str | None
    summary: str | None
    affected_entity_ids: list[str]
    task_id: str | None
    execution_process_id: str | None
    error_code: str | None
    error_message: str | None
    can_apply: bool
    can_reject: bool
    created_at: str
    updated_at: str
    completed_at: str | None


class PrototypeAiThreadSnapshotResponseV1(StrictResponseModel):
    contract_version: Literal[1]
    thread: PrototypeAiThreadResponseV1
    messages: list[PrototypeAiMessageResponseV1]
    latest_run: PrototypeAiEditRunResponseV1 | None


class PrototypeAiApplyResponseV1(StrictResponseModel):
    contract_version: Literal[1]
    run: PrototypeAiEditRunResponseV1
    draft: StructuredPrototypeDraftResponseV1
    command_batch_id: str


class PrototypeAiErrorDetailV1(StrictResponseModel):
    code: str
    message: str
    run_id: str | None


class PrototypeAiErrorResponseV1(StrictResponseModel):
    contract_version: Literal[1]
    correlation_id: str
    error: PrototypeAiErrorDetailV1


class StructuredPrototypeAiRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def route_handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError:
                return _error_response(
                    status_code=422,
                    code="request_invalid",
                    message="structured prototype AI request does not satisfy contract version 1",
                    run_id=None,
                )
            except StructuredPrototypeStoreError as exc:
                return _service_failure(StructuredPrototypeAiServiceError(exc.code, str(exc)))
            except StructuredPrototypeServiceError as exc:
                return _service_failure(
                    StructuredPrototypeAiServiceError(
                        exc.code,
                        str(exc),
                        operation_id=exc.operation_id,
                    )
                )

        return route_handler


router = APIRouter(prefix="/api", route_class=StructuredPrototypeAiRoute)


@router.post(
    "/internal/structured-prototype-ai-mcp",
    include_in_schema=False,
)
async def structured_prototype_ai_mcp(request: Request) -> Response:
    service = structured_prototype_ai_mcp_service
    if service is None:
        return JSONResponse(status_code=503, content={"error": "prototype AI MCP unavailable"})
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(status_code=400, content={"error": "invalid JSON"})
    status, body = await service.handle(
        token=request.headers.get("X-Prototype-Ai-Token"),
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
    "/prototype-documents/{document_id}/ai-threads",
    response_model=PrototypeAiThreadResponseV1,
    status_code=201,
)
async def create_prototype_ai_thread(
    document_id: str,
    body: CreatePrototypeAiThreadRequestV1,
) -> Response:
    try:
        thread = await _require_service().create_thread(
            document_id=document_id,
            client_request_id=body.client_request_id,
            title=body.title,
        )
    except StructuredPrototypeAiServiceError as exc:
        return _service_failure(exc)
    return JSONResponse(status_code=201, content=_thread_response(thread).model_dump(mode="json"))


@router.get(
    "/prototype-documents/{document_id}/ai-threads",
    response_model=list[PrototypeAiThreadResponseV1],
)
async def list_prototype_ai_threads(document_id: str) -> Response:
    try:
        threads = await _require_service().list_threads(document_id)
    except StructuredPrototypeAiServiceError as exc:
        return _service_failure(exc)
    return JSONResponse(
        content=[item.model_dump(mode="json") for item in map(_thread_response, threads)]
    )


@router.get(
    "/prototype-ai-threads/{thread_id}",
    response_model=PrototypeAiThreadSnapshotResponseV1,
)
async def get_prototype_ai_thread(thread_id: str) -> Response:
    try:
        snapshot = await _require_service().get_thread(thread_id)
    except StructuredPrototypeAiServiceError as exc:
        return _service_failure(exc)
    return JSONResponse(content=_snapshot_response(snapshot).model_dump(mode="json"))


@router.post(
    "/prototype-ai-threads/{thread_id}/messages",
    response_model=PrototypeAiEditRunResponseV1,
    status_code=202,
)
async def send_prototype_ai_message(
    thread_id: str,
    body: SendPrototypeAiMessageRequestV1,
) -> Response:
    try:
        run = await _require_service().send_message(
            thread_id=thread_id,
            client_message_id=body.client_message_id,
            draft_id=body.draft_id,
            expected_head_sequence_no=body.expected_head_sequence_no,
            expected_document_hash=body.expected_document_hash,
            content=body.content,
            selection=body.selection,
        )
    except StructuredPrototypeAiServiceError as exc:
        return _service_failure(exc)
    return JSONResponse(status_code=202, content=_run_response(run).model_dump(mode="json"))


@router.get(
    "/prototype-ai-edit-runs/{run_id}",
    response_model=PrototypeAiEditRunResponseV1,
)
async def get_prototype_ai_edit_run(run_id: str) -> Response:
    try:
        run = await _require_service().get_run(run_id)
    except StructuredPrototypeAiServiceError as exc:
        return _service_failure(exc)
    return JSONResponse(content=_run_response(run).model_dump(mode="json"))


@router.post(
    "/prototype-ai-edit-runs/{run_id}/apply",
    response_model=PrototypeAiApplyResponseV1,
)
async def apply_prototype_ai_edit_run(
    run_id: str,
    body: ApplyPrototypeAiProposalRequestV1,
) -> Response:
    try:
        applied = await _require_service().apply(
            run_id=run_id,
            client_request_id=body.client_request_id,
            expected_head_sequence_no=body.expected_head_sequence_no,
            expected_document_hash=body.expected_document_hash,
        )
    except StructuredPrototypeAiServiceError as exc:
        return _service_failure(exc)
    return JSONResponse(content=_apply_response(applied).model_dump(mode="json"))


@router.post(
    "/prototype-ai-edit-runs/{run_id}/reject",
    response_model=PrototypeAiEditRunResponseV1,
)
async def reject_prototype_ai_edit_run(
    run_id: str,
    body: RejectPrototypeAiProposalRequestV1,
) -> Response:
    try:
        rejected = await _require_service().reject(
            run_id=run_id,
            client_request_id=body.client_request_id,
        )
    except StructuredPrototypeAiServiceError as exc:
        return _service_failure(exc)
    return JSONResponse(content=_run_response(rejected).model_dump(mode="json"))


@router.get("/prototype-ai-edit-runs/{run_id}/preview/{relative_path:path}")
async def get_prototype_ai_preview_file(run_id: str, relative_path: str) -> Response:
    try:
        file = await _require_service().read_preview_file(
            run_id=run_id,
            relative_path=relative_path,
        )
    except StructuredPrototypeAiServiceError as exc:
        return _service_failure(exc)
    return Response(
        content=file.content,
        media_type=file.media_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'none'; frame-ancestors 'self'",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _require_service() -> StructuredPrototypeAiService:
    service = structured_prototype_ai_service
    if service is None:
        raise StructuredPrototypeAiServiceError(
            "structured_prototype_ai_unavailable",
            "structured prototype AI service is unavailable",
        )
    return service


def _thread_response(thread: PrototypeAiThreadRecord) -> PrototypeAiThreadResponseV1:
    return PrototypeAiThreadResponseV1(
        contract_version=1,
        id=thread.id,
        document_id=thread.document_id,
        title=thread.title,
        status=thread.status,
        created_at=thread.created_at.isoformat(),
        updated_at=thread.updated_at.isoformat(),
    )


def _message_response(message: PrototypeAiMessageRecord) -> PrototypeAiMessageResponseV1:
    return PrototypeAiMessageResponseV1(
        id=message.id,
        role=message.role,
        kind=message.kind,
        content=message.content,
        run_id=message.run_id,
        command_batch_id=message.command_batch_id,
        status=message.status,
        created_at=message.created_at.isoformat(),
        updated_at=message.updated_at.isoformat(),
    )


def _run_response(run: PrototypeAiEditRunRecord) -> PrototypeAiEditRunResponseV1:
    affected: list[str] = []
    if run.affected_entity_ids_json is not None:
        parsed = json.loads(run.affected_entity_ids_json)
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise StructuredPrototypeAiServiceError(
                "completion_evidence_missing",
                "prototype AI affected entity evidence is invalid",
                run_id=run.id,
            )
        affected = parsed
    return PrototypeAiEditRunResponseV1(
        contract_version=1,
        id=run.id,
        thread_id=run.thread_id,
        user_message_id=run.user_message_id,
        assistant_message_id=run.assistant_message_id,
        document_id=run.document_id,
        draft_id=run.draft_id,
        operation_id=run.operation_id,
        status=run.status,
        base_head_sequence_no=run.base_head_sequence_no,
        base_document_hash=run.base_document_hash,
        context_object_hash=run.context_object_hash,
        outcome_object_hash=run.outcome_object_hash,
        submission_id=run.submission_id,
        submission_request_hash=run.submission_request_hash,
        submission_accepted_at=(
            run.submission_accepted_at.isoformat()
            if run.submission_accepted_at is not None
            else None
        ),
        replay_manifest_object_hash=run.replay_manifest_object_hash,
        proposed_command_batch_hash=run.proposed_command_batch_hash,
        candidate_object_hash=run.candidate_object_hash,
        preview_render_run_id=run.preview_render_run_id,
        preview_artifact_id=run.preview_artifact_id,
        preview_path=(
            f"/api/prototype-ai-edit-runs/{run.id}/preview/index.html"
            if run.preview_artifact_id is not None
            else None
        ),
        summary=run.summary,
        affected_entity_ids=affected,
        task_id=run.task_id,
        execution_process_id=run.execution_process_id,
        error_code=run.error_code,
        error_message=run.error_message,
        can_apply=run.status == "preview_ready",
        can_reject=run.status == "preview_ready",
        created_at=run.created_at.isoformat(),
        updated_at=run.updated_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at is not None else None,
    )


def _snapshot_response(
    snapshot: PrototypeAiThreadSnapshot,
) -> PrototypeAiThreadSnapshotResponseV1:
    return PrototypeAiThreadSnapshotResponseV1(
        contract_version=1,
        thread=_thread_response(snapshot.thread),
        messages=[_message_response(message) for message in snapshot.messages],
        latest_run=_run_response(snapshot.latest_run) if snapshot.latest_run is not None else None,
    )


def _apply_response(result: PrototypeAiApplyResult) -> PrototypeAiApplyResponseV1:
    return PrototypeAiApplyResponseV1(
        contract_version=1,
        run=_run_response(result.run),
        draft=_draft_response(result.draft_result),
        command_batch_id=result.command_batch_id,
    )


def _service_failure(exc: StructuredPrototypeAiServiceError) -> JSONResponse:
    status = 500
    if exc.code in {"document_missing", "draft_missing", "ai_thread_missing", "ai_run_missing"}:
        status = 404
    elif exc.code in {
        "draft_conflict",
        "ai_run_conflict",
        "ai_thread_unavailable",
        "ai_message_conflict",
    }:
        status = 409
    elif exc.code in {
        "request_invalid",
        "context_invalid",
        "scope_violation",
        "schema_invalid",
        "client_request_id_invalid",
        "client_message_id_invalid",
    }:
        status = 422
    elif exc.code in {
        "runtime_unavailable",
        "structured_prototype_ai_unavailable",
        "object_write_failed",
        "preview_render_failed",
    }:
        status = 503
    return _error_response(
        status_code=status,
        code=exc.code,
        message=str(exc),
        run_id=exc.run_id,
    )


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    run_id: str | None,
) -> JSONResponse:
    payload = PrototypeAiErrorResponseV1(
        contract_version=1,
        correlation_id=str(uuid4()),
        error=PrototypeAiErrorDetailV1(code=code, message=message, run_id=run_id),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))
