from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.application.structured_prototype_contracts import (
    DomainCommandBatchV1,
    EntityRefRuntimeValueV1,
    NewPrototypeDocumentV1,
    PrototypeDocumentV1,
    RuntimeValueV1,
)
from app.application.structured_prototype_service import (
    ActivePrototypeRuntimeState,
    ActivePrototypeState,
    ApplyStructuredPrototypeCommandsResult,
    CreateStructuredPrototypeResult,
    PublishedPrototypeSnapshot,
    PublishStructuredPrototypeResult,
    RecoverStructuredPrototypeResult,
    StructuredPrototypeService,
    StructuredPrototypeServiceError,
)

HTTP_CONTRACT_VERSION: Literal[1] = 1
structured_prototype_service: StructuredPrototypeService | None = None


def configure_structured_prototype_service(
    service: StructuredPrototypeService | None,
) -> None:
    global structured_prototype_service
    structured_prototype_service = service


def _camel_alias(field_name: str) -> str:
    head, *tail = field_name.split("_")
    return head + "".join(part.capitalize() for part in tail)


class StrictRequestModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel_alias,
        extra="forbid",
        populate_by_name=False,
        strict=True,
        str_strip_whitespace=False,
    )


class StrictResponseModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel_alias,
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
        strict=True,
        str_strip_whitespace=False,
    )


class CreateStructuredPrototypeRequestV1(StrictRequestModel):
    contract_version: Literal[1]
    client_request_id: Annotated[str, Field(min_length=36, max_length=36)]
    document: NewPrototypeDocumentV1

    @model_validator(mode="before")
    @classmethod
    def validate_nested_aliases(cls, value: object) -> object:
        if not isinstance(value, dict) or "document" not in value:
            return value
        validated = NewPrototypeDocumentV1.model_validate(
            value["document"],
            strict=True,
            by_alias=True,
            by_name=False,
        )
        result = dict(value)
        result["document"] = validated
        return result


class ApplyStructuredPrototypeCommandsRequestV1(StrictRequestModel):
    contract_version: Literal[1]
    client_request_id: Annotated[str, Field(min_length=36, max_length=36)]
    expected_head_sequence_no: Annotated[int, Field(ge=0)]
    expected_document_hash: Annotated[
        str,
        Field(pattern=r"^sha256:[0-9a-f]{64}$"),
    ]
    batch: DomainCommandBatchV1

    @model_validator(mode="before")
    @classmethod
    def validate_nested_aliases(cls, value: object) -> object:
        if not isinstance(value, dict) or "batch" not in value:
            return value
        validated = DomainCommandBatchV1.model_validate(
            value["batch"],
            strict=True,
            by_alias=True,
            by_name=False,
        )
        result = dict(value)
        result["batch"] = validated
        return result


class CreatePrototypeRuntimeSessionRequestV1(StrictRequestModel):
    contract_version: Literal[1]
    client_request_id: Annotated[str, Field(min_length=36, max_length=36)]
    scenario_id: Annotated[str, Field(min_length=1, max_length=128)]
    recording_kind: Literal["studio_preview", "recorded_review", "shared_preview"]
    actor_subject_id: Annotated[str, Field(min_length=1, max_length=128)] | None


class FieldValueCommittedEventV1(StrictRequestModel):
    kind: Literal["fieldValueCommitted"]
    node_id: Annotated[str, Field(min_length=1, max_length=128)]
    form_id: Annotated[str, Field(min_length=1, max_length=128)]
    field_id: Annotated[str, Field(min_length=1, max_length=128)]
    value: RuntimeValueV1


class NodeActivatedEventV1(StrictRequestModel):
    kind: Literal["nodeActivated"]
    node_id: Annotated[str, Field(min_length=1, max_length=128)]
    event: Literal["click", "submit"]


class TableRowActivatedEventV1(StrictRequestModel):
    kind: Literal["tableRowActivated"]
    node_id: Annotated[str, Field(min_length=1, max_length=128)]
    entity_ref: EntityRefRuntimeValueV1


class SwitchSimulatedRoleEventV1(StrictRequestModel):
    kind: Literal["switchSimulatedRole"]
    role_id: Annotated[str, Field(min_length=1, max_length=128)]


type RuntimeEventV1 = Annotated[
    FieldValueCommittedEventV1
    | NodeActivatedEventV1
    | TableRowActivatedEventV1
    | SwitchSimulatedRoleEventV1,
    Field(discriminator="kind"),
]


class RuntimeEventBatchV1(StrictRequestModel):
    client_event_id: Annotated[str, Field(min_length=36, max_length=36)]
    expected_sequence_no: Annotated[int, Field(ge=0)]
    events: Annotated[list[RuntimeEventV1], Field(min_length=1, max_length=20)]


class ApplyPrototypeRuntimeEventRequestV1(StrictRequestModel):
    contract_version: Literal[1]
    client_request_id: Annotated[str, Field(min_length=36, max_length=36)]
    expected_head_sequence_no: Annotated[int, Field(ge=0)]
    expected_state_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    batch: RuntimeEventBatchV1


class CheckpointPrototypeRuntimeSessionRequestV1(StrictRequestModel):
    contract_version: Literal[1]
    client_request_id: Annotated[str, Field(min_length=36, max_length=36)]


class PublishStructuredPrototypeRequestV1(StrictRequestModel):
    contract_version: Literal[1]
    client_request_id: Annotated[str, Field(min_length=36, max_length=36)]
    expected_head_sequence_no: Annotated[int, Field(ge=0)]
    expected_document_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class AllocatedEntityIdResponseV1(StrictResponseModel):
    new_node_key: str
    entity_id: str


class StructuredPrototypeDraftResponseV1(StrictResponseModel):
    contract_version: Literal[1]
    operation_id: str
    correlation_id: str
    document_id: str
    draft_id: str
    head_sequence_no: int
    document_hash: str
    document: PrototypeDocumentV1


class ApplyStructuredPrototypeCommandsResponseV1(StructuredPrototypeDraftResponseV1):
    applied_batch_id: str
    allocated_entity_ids: list[AllocatedEntityIdResponseV1]
    affected_entity_ids: list[str]


class PrototypeRuntimeSessionResponseV1(StrictResponseModel):
    contract_version: Literal[1]
    operation_id: str
    correlation_id: str
    session_id: str
    document_id: str
    source_kind: Literal["draft", "ai_preview", "published_revision"]
    source_id: str
    status: Literal["active", "completed", "interrupted", "corrupt"]
    recording_kind: Literal["studio_preview", "recorded_review", "shared_preview"]
    head_sequence_no: int
    state_hash: str
    view_model_hash: str
    state_json: str
    view_model_json: str
    runtime_core_version: str
    runtime_core_bundle_hash: str
    state_machine_kernel_version: str
    checkpoint_id: str
    checkpoint_sequence_no: int
    replayed_event_batch_ids: list[str]


class ApplyPrototypeRuntimeEventResponseV1(PrototypeRuntimeSessionResponseV1):
    event_batch_id: str
    outcome: Literal["applied", "guard_false", "validation_failed"]


class PublishedPrototypeResponseV1(StrictResponseModel):
    contract_version: Literal[1]
    document_id: str
    revision_id: str
    revision_no: int
    render_run_id: str
    artifact_id: str
    renderer_version: str
    document_hash: str
    output_hash: str
    output_manifest_hash: str
    visual_preflight_report_hash: str
    published_at: str
    share_path: str
    artifact_path: str


class PublishStructuredPrototypeResponseV1(PublishedPrototypeResponseV1):
    operation_id: str
    correlation_id: str
    active_draft: StructuredPrototypeDraftResponseV1


class PrototypeRuntimeErrorDetailV1(StrictResponseModel):
    code: str
    message: str
    retryable: bool
    current_head_sequence_no: int | None
    current_state_hash: str | None
    resource_url: str | None


class PrototypeRuntimeErrorResponseV1(StrictResponseModel):
    contract_version: Literal[1]
    correlation_id: str
    operation_id: str | None
    error: PrototypeRuntimeErrorDetailV1


class PrototypeErrorDetailV1(StrictResponseModel):
    code: str
    message: str
    retryable: bool
    current_head_sequence_no: int | None
    current_document_hash: str | None
    resource_url: str | None


class PrototypeErrorResponseV1(StrictResponseModel):
    contract_version: Literal[1]
    correlation_id: str
    operation_id: str | None
    error: PrototypeErrorDetailV1


def _status_for_error(code: str) -> int:
    if code in {
        "document_missing",
        "draft_missing",
        "revision_missing",
        "render_run_missing",
        "published_artifact_missing",
        "render_artifact_missing",
        "render_artifact_file_missing",
    }:
        return 404
    if code in {
        "draft_conflict",
        "draft_not_active",
        "draft_corrupt",
        "operation_in_progress",
        "idempotent_result_superseded",
        "object_hash_mismatch",
        "object_missing",
        "replay_document_hash_mismatch",
        "replay_batch_hash_mismatch",
        "publication_state_conflict",
        "revision_sequence_conflict",
        "render_run_conflict",
    }:
        return 409
    if code in {
        "client_request_id_invalid",
        "command_batch_invalid",
        "command_target_invalid",
        "command_target_missing",
        "command_index_invalid",
        "command_property_invalid",
        "command_new_key_duplicate",
        "command_batch_too_large",
        "renderer_document_invalid",
        "renderer_schema_unsupported",
        "renderer_token_unsupported",
        "renderer_assets_unsupported",
        "renderer_form_binding_incomplete",
        "renderer_form_binding_type_mismatch",
    }:
        return 422
    if code in {
        "object_write_failed",
        "checkpoint_required_unavailable",
        "operation_evidence_unavailable",
        "renderer_worker_unavailable",
        "renderer_worker_node_missing",
        "renderer_worker_spawn_failed",
        "renderer_worker_timeout",
        "render_artifact_store_unavailable",
        "render_artifact_write_failed",
    }:
        return 503
    return 500


def _error_response(
    *,
    status_code: int,
    correlation_id: str,
    operation_id: str | None,
    code: str,
    message: str,
    retryable: bool,
    current_head_sequence_no: int | None = None,
    current_document_hash: str | None = None,
) -> JSONResponse:
    payload = PrototypeErrorResponseV1(
        contract_version=HTTP_CONTRACT_VERSION,
        correlation_id=correlation_id,
        operation_id=operation_id,
        error=PrototypeErrorDetailV1(
            code=code,
            message=message,
            retryable=retryable,
            current_head_sequence_no=current_head_sequence_no,
            current_document_hash=current_document_hash,
            resource_url=None,
        ),
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json", by_alias=True),
    )


class StructuredPrototypeRoute(APIRoute):
    # FastAPI's APIRoute override hard-codes Coroutine[Any, Any, Response].
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def route_handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError:
                return _error_response(
                    status_code=422,
                    correlation_id=str(uuid4()),
                    operation_id=None,
                    code="request_invalid",
                    message="structured prototype request does not satisfy HTTP contract version 1",
                    retryable=False,
                )

        return route_handler


router = APIRouter(prefix="/api", route_class=StructuredPrototypeRoute)


def _require_service() -> StructuredPrototypeService:
    service = structured_prototype_service
    if service is None:
        raise StructuredPrototypeServiceError(
            "structured_prototype_unavailable",
            "structured prototype service is unavailable",
        )
    return service


def _service_failure(exc: StructuredPrototypeServiceError) -> JSONResponse:
    return _error_response(
        status_code=_status_for_error(exc.code),
        correlation_id=exc.correlation_id or str(uuid4()),
        operation_id=exc.operation_id,
        code=exc.code,
        message=str(exc),
        retryable=exc.retryable,
        current_head_sequence_no=exc.current_head_sequence_no,
        current_document_hash=exc.current_document_hash,
    )


def _runtime_status_for_error(code: str) -> int:
    if code in {"document_missing", "draft_missing", "runtime_session_missing"}:
        return 404
    if code in {
        "runtime_session_conflict",
        "runtime_session_not_active",
        "runtime_session_corrupt",
        "runtime_replay_state_hash_mismatch",
        "runtime_replay_evidence_mismatch",
        "runtime_replay_version_mismatch",
        "runtime_document_checkpoint_mismatch",
    }:
        return 409
    if code in {
        "client_request_id_invalid",
        "runtime_client_event_id_mismatch",
        "runtime_event_sequence_mismatch",
        "runtime_scenario_missing",
        "runtime_input_invalid",
        "runtime_state_invalid",
    }:
        return 422
    if code in {
        "runtime_worker_unavailable",
        "runtime_worker_node_missing",
        "runtime_worker_spawn_failed",
        "runtime_worker_timeout",
        "runtime_checkpoint_required_unavailable",
        "operation_evidence_unavailable",
        "object_write_failed",
    }:
        return 503
    return 500


def _runtime_service_failure(exc: StructuredPrototypeServiceError) -> JSONResponse:
    payload = PrototypeRuntimeErrorResponseV1(
        contract_version=HTTP_CONTRACT_VERSION,
        correlation_id=exc.correlation_id or str(uuid4()),
        operation_id=exc.operation_id,
        error=PrototypeRuntimeErrorDetailV1(
            code=exc.code,
            message=str(exc),
            retryable=exc.retryable,
            current_head_sequence_no=exc.current_head_sequence_no,
            current_state_hash=exc.current_state_hash,
            resource_url=None,
        ),
    )
    return JSONResponse(
        status_code=_runtime_status_for_error(exc.code),
        content=payload.model_dump(mode="json", by_alias=True),
    )


def _draft_response(
    result: CreateStructuredPrototypeResult | RecoverStructuredPrototypeResult,
) -> StructuredPrototypeDraftResponseV1:
    return _state_response(
        operation_id=result.operation_id,
        correlation_id=result.correlation_id,
        state=result.state,
    )


def _state_response(
    *,
    operation_id: str,
    correlation_id: str,
    state: ActivePrototypeState,
) -> StructuredPrototypeDraftResponseV1:
    return StructuredPrototypeDraftResponseV1(
        contract_version=HTTP_CONTRACT_VERSION,
        operation_id=operation_id,
        correlation_id=correlation_id,
        document_id=state.document_record.id,
        draft_id=state.draft.id,
        head_sequence_no=state.draft.head_sequence_no,
        document_hash=state.draft.head_document_hash,
        document=state.document,
    )


def _runtime_state_response(
    *,
    operation_id: str,
    correlation_id: str,
    state: ActivePrototypeRuntimeState,
) -> PrototypeRuntimeSessionResponseV1:
    session = state.session
    return PrototypeRuntimeSessionResponseV1(
        contract_version=HTTP_CONTRACT_VERSION,
        operation_id=operation_id,
        correlation_id=correlation_id,
        session_id=session.id,
        document_id=session.document_id,
        source_kind=session.source_kind,
        source_id=session.source_id,
        status=session.status,
        recording_kind=session.recording_kind,
        head_sequence_no=session.head_sequence_no,
        state_hash=session.head_state_hash,
        view_model_hash=session.head_view_model_hash,
        state_json=state.state_json,
        view_model_json=state.view_model_json,
        runtime_core_version=session.runtime_core_version,
        runtime_core_bundle_hash=session.runtime_core_bundle_hash,
        state_machine_kernel_version=session.state_machine_kernel_version,
        checkpoint_id=state.loaded_checkpoint_id,
        checkpoint_sequence_no=state.loaded_checkpoint_sequence_no,
        replayed_event_batch_ids=list(state.replayed_event_batch_ids),
    )


def _published_response(
    snapshot: PublishedPrototypeSnapshot,
) -> PublishedPrototypeResponseV1:
    artifact_path = (
        f"/api/structured-prototype-public/{snapshot.document_id}"
        f"/revisions/{snapshot.revision_no}/artifacts/{snapshot.artifact_id}/index.html"
    )
    return PublishedPrototypeResponseV1(
        contract_version=HTTP_CONTRACT_VERSION,
        document_id=snapshot.document_id,
        revision_id=snapshot.revision_id,
        revision_no=snapshot.revision_no,
        render_run_id=snapshot.render_run_id,
        artifact_id=snapshot.artifact_id,
        renderer_version=snapshot.renderer_version,
        document_hash=snapshot.document_hash,
        output_hash=snapshot.output_hash,
        output_manifest_hash=snapshot.output_manifest_hash,
        visual_preflight_report_hash=snapshot.visual_preflight_report_hash,
        published_at=snapshot.published_at.isoformat(),
        share_path=f"/prototype-share/{snapshot.document_id}",
        artifact_path=artifact_path,
    )


def _publish_response(
    result: PublishStructuredPrototypeResult,
) -> PublishStructuredPrototypeResponseV1:
    published = _published_response(result.publication)
    return PublishStructuredPrototypeResponseV1(
        **published.model_dump(),
        operation_id=result.operation_id,
        correlation_id=result.correlation_id,
        active_draft=_state_response(
            operation_id=result.operation_id,
            correlation_id=result.correlation_id,
            state=result.state,
        ),
    )


@router.post(
    "/projects/{project_id}/structured-prototype-documents",
    status_code=201,
    response_model=StructuredPrototypeDraftResponseV1,
)
async def create_structured_prototype_document(
    project_id: str,
    body: CreateStructuredPrototypeRequestV1,
) -> StructuredPrototypeDraftResponseV1 | JSONResponse:
    try:
        service = _require_service()
        result = await service.create_document(
            project_id=project_id,
            client_request_id=body.client_request_id,
            document=body.document,
        )
    except StructuredPrototypeServiceError as exc:
        return _service_failure(exc)
    return _draft_response(result)


@router.get(
    "/projects/{project_id}/structured-prototype-documents/current",
    response_model=StructuredPrototypeDraftResponseV1 | None,
)
async def get_current_structured_prototype_document(
    project_id: str,
    client_request_id: Annotated[
        str,
        Query(alias="clientRequestId", min_length=36, max_length=36),
    ],
) -> StructuredPrototypeDraftResponseV1 | None | JSONResponse:
    try:
        UUID(client_request_id)
        result = await _require_service().recover_current_project_draft(
            project_id=project_id,
            client_request_id=client_request_id,
        )
    except ValueError:
        return _error_response(
            status_code=422,
            correlation_id=str(uuid4()),
            operation_id=None,
            code="client_request_id_invalid",
            message="prototype client request ID must be a UUID",
            retryable=False,
        )
    except StructuredPrototypeServiceError as exc:
        return _service_failure(exc)
    return _draft_response(result) if result is not None else None


@router.get(
    "/structured-prototype-drafts/{draft_id}",
    response_model=StructuredPrototypeDraftResponseV1,
)
async def get_structured_prototype_draft(
    draft_id: str,
    client_request_id: Annotated[
        str,
        Query(alias="clientRequestId", min_length=36, max_length=36),
    ],
) -> StructuredPrototypeDraftResponseV1 | JSONResponse:
    try:
        UUID(client_request_id)
        service = _require_service()
        result = await service.recover_draft(
            draft_id=draft_id,
            client_request_id=client_request_id,
        )
    except ValueError:
        return _error_response(
            status_code=422,
            correlation_id=str(uuid4()),
            operation_id=None,
            code="client_request_id_invalid",
            message="prototype client request ID must be a UUID",
            retryable=False,
        )
    except StructuredPrototypeServiceError as exc:
        return _service_failure(exc)
    return _draft_response(result)


@router.post(
    "/structured-prototype-drafts/{draft_id}/commands",
    response_model=ApplyStructuredPrototypeCommandsResponseV1,
)
async def apply_structured_prototype_commands(
    draft_id: str,
    body: ApplyStructuredPrototypeCommandsRequestV1,
) -> ApplyStructuredPrototypeCommandsResponseV1 | JSONResponse:
    try:
        service = _require_service()
        result = await service.apply_command_batch(
            draft_id=draft_id,
            client_request_id=body.client_request_id,
            expected_head_sequence_no=body.expected_head_sequence_no,
            expected_document_hash=body.expected_document_hash,
            batch=body.batch,
        )
    except StructuredPrototypeServiceError as exc:
        return _service_failure(exc)
    return _apply_response(result)


@router.post(
    "/structured-prototype-drafts/{draft_id}/publish",
    status_code=201,
    response_model=PublishStructuredPrototypeResponseV1,
)
async def publish_structured_prototype_draft(
    draft_id: str,
    body: PublishStructuredPrototypeRequestV1,
) -> PublishStructuredPrototypeResponseV1 | JSONResponse:
    try:
        service = _require_service()
        result = await service.publish_draft(
            draft_id=draft_id,
            client_request_id=body.client_request_id,
            expected_head_sequence_no=body.expected_head_sequence_no,
            expected_document_hash=body.expected_document_hash,
        )
    except StructuredPrototypeServiceError as exc:
        return _service_failure(exc)
    return _publish_response(result)


@router.get(
    "/structured-prototype-documents/{document_id}/published",
    response_model=PublishedPrototypeResponseV1 | None,
)
async def get_structured_prototype_publication(
    document_id: str,
) -> PublishedPrototypeResponseV1 | None | JSONResponse:
    try:
        service = _require_service()
        snapshot = await service.get_published_prototype(document_id)
    except StructuredPrototypeServiceError as exc:
        return _service_failure(exc)
    return _published_response(snapshot) if snapshot is not None else None


@router.get(
    "/structured-prototype-public/{document_id}/current/index.html",
    response_model=None,
)
async def redirect_current_structured_prototype_publication(
    document_id: str,
) -> Response | JSONResponse:
    try:
        service = _require_service()
        snapshot = await service.get_published_prototype(document_id)
        if snapshot is None:
            raise StructuredPrototypeServiceError(
                "published_artifact_missing",
                "published prototype artifact does not exist",
            )
    except StructuredPrototypeServiceError as exc:
        return _service_failure(exc)
    location = (
        f"/api/structured-prototype-public/{snapshot.document_id}"
        f"/revisions/{snapshot.revision_no}/artifacts/{snapshot.artifact_id}/index.html"
    )
    return Response(
        status_code=307,
        headers={"Location": location, "Cache-Control": "no-store"},
    )


@router.get(
    "/structured-prototype-public/{document_id}/revisions/{revision_no}"
    "/artifacts/{artifact_id}/{relative_path:path}",
    response_model=None,
)
async def get_structured_prototype_publication_file(
    document_id: str,
    revision_no: int,
    artifact_id: str,
    relative_path: str,
) -> Response | JSONResponse:
    media_types = {
        "document.json": "application/json; charset=utf-8",
        "index.html": "text/html; charset=utf-8",
        "runtime.js": "text/javascript; charset=utf-8",
        "styles.css": "text/css; charset=utf-8",
    }
    media_type = media_types.get(relative_path)
    if media_type is None:
        return _error_response(
            status_code=404,
            correlation_id=str(uuid4()),
            operation_id=None,
            code="render_artifact_file_missing",
            message="published prototype artifact file does not exist",
            retryable=False,
        )
    try:
        service = _require_service()
        result = await service.read_published_file(
            document_id=document_id,
            revision_no=revision_no,
            artifact_id=artifact_id,
            relative_path=relative_path,
        )
    except StructuredPrototypeServiceError as exc:
        return _service_failure(exc)
    headers = {
        "Cache-Control": "public, max-age=31536000, immutable",
        "Content-Security-Policy": (
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; font-src 'self'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
        ),
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
        "ETag": f'"{result.publication.output_hash.removeprefix("sha256:")}"',
    }
    return Response(content=result.content, media_type=media_type, headers=headers)


@router.post(
    "/structured-prototype-drafts/{draft_id}/runtime-sessions",
    status_code=201,
    response_model=PrototypeRuntimeSessionResponseV1,
)
async def create_prototype_runtime_session(
    draft_id: str,
    body: CreatePrototypeRuntimeSessionRequestV1,
) -> PrototypeRuntimeSessionResponseV1 | JSONResponse:
    try:
        service = _require_service()
        result = await service.create_runtime_session(
            draft_id=draft_id,
            client_request_id=body.client_request_id,
            scenario_id=body.scenario_id,
            recording_kind=body.recording_kind,
            actor_subject_id=body.actor_subject_id,
        )
    except StructuredPrototypeServiceError as exc:
        return _runtime_service_failure(exc)
    return _runtime_state_response(
        operation_id=result.operation_id,
        correlation_id=result.correlation_id,
        state=result.state,
    )


@router.get(
    "/structured-prototype-runtime-sessions/{session_id}",
    response_model=PrototypeRuntimeSessionResponseV1,
)
async def get_prototype_runtime_session(
    session_id: str,
    client_request_id: Annotated[
        str,
        Query(alias="clientRequestId", min_length=36, max_length=36),
    ],
) -> PrototypeRuntimeSessionResponseV1 | JSONResponse:
    try:
        UUID(client_request_id)
        service = _require_service()
        result = await service.recover_runtime_session(
            session_id=session_id,
            client_request_id=client_request_id,
        )
    except ValueError:
        return _runtime_validation_failure("prototype client request ID must be a UUID")
    except StructuredPrototypeServiceError as exc:
        return _runtime_service_failure(exc)
    return _runtime_state_response(
        operation_id=result.operation_id,
        correlation_id=result.correlation_id,
        state=result.state,
    )


@router.post(
    "/structured-prototype-runtime-sessions/{session_id}/events",
    response_model=ApplyPrototypeRuntimeEventResponseV1,
)
async def apply_prototype_runtime_event(
    session_id: str,
    body: ApplyPrototypeRuntimeEventRequestV1,
) -> ApplyPrototypeRuntimeEventResponseV1 | JSONResponse:
    batch: dict[str, object] = body.batch.model_dump(mode="json", by_alias=True)
    try:
        service = _require_service()
        result = await service.apply_runtime_event_batch(
            session_id=session_id,
            client_request_id=body.client_request_id,
            expected_head_sequence_no=body.expected_head_sequence_no,
            expected_state_hash=body.expected_state_hash,
            batch=batch,
        )
    except StructuredPrototypeServiceError as exc:
        return _runtime_service_failure(exc)
    base = _runtime_state_response(
        operation_id=result.operation_id,
        correlation_id=result.correlation_id,
        state=result.state,
    )
    return ApplyPrototypeRuntimeEventResponseV1(
        **base.model_dump(),
        event_batch_id=result.event_batch_id,
        outcome=result.outcome,
    )


@router.post(
    "/structured-prototype-runtime-sessions/{session_id}/checkpoint",
    response_model=PrototypeRuntimeSessionResponseV1,
)
async def checkpoint_prototype_runtime_session(
    session_id: str,
    body: CheckpointPrototypeRuntimeSessionRequestV1,
) -> PrototypeRuntimeSessionResponseV1 | JSONResponse:
    try:
        service = _require_service()
        result = await service.checkpoint_runtime_session(
            session_id=session_id,
            client_request_id=body.client_request_id,
        )
    except StructuredPrototypeServiceError as exc:
        return _runtime_service_failure(exc)
    return _runtime_state_response(
        operation_id=result.operation_id,
        correlation_id=result.correlation_id,
        state=result.state,
    )


def _runtime_validation_failure(message: str) -> JSONResponse:
    payload = PrototypeRuntimeErrorResponseV1(
        contract_version=HTTP_CONTRACT_VERSION,
        correlation_id=str(uuid4()),
        operation_id=None,
        error=PrototypeRuntimeErrorDetailV1(
            code="client_request_id_invalid",
            message=message,
            retryable=False,
            current_head_sequence_no=None,
            current_state_hash=None,
            resource_url=None,
        ),
    )
    return JSONResponse(
        status_code=422,
        content=payload.model_dump(mode="json", by_alias=True),
    )


def _apply_response(
    result: ApplyStructuredPrototypeCommandsResult,
) -> ApplyStructuredPrototypeCommandsResponseV1:
    state = result.state
    return ApplyStructuredPrototypeCommandsResponseV1(
        contract_version=HTTP_CONTRACT_VERSION,
        operation_id=result.operation_id,
        correlation_id=result.correlation_id,
        document_id=state.document_record.id,
        draft_id=state.draft.id,
        head_sequence_no=state.draft.head_sequence_no,
        document_hash=state.draft.head_document_hash,
        applied_batch_id=result.applied_batch_id,
        allocated_entity_ids=[
            AllocatedEntityIdResponseV1(new_node_key=key, entity_id=entity_id)
            for key, entity_id in result.allocated_entity_ids
        ],
        affected_entity_ids=list(result.affected_entity_ids),
        document=state.document,
    )
