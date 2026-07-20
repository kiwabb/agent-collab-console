from __future__ import annotations

from collections.abc import Callable, Coroutine
from datetime import datetime
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
    SNAP_WORKER_INFRASTRUCTURE_ERROR_CODES,
    ActivePrototypeRuntimeState,
    ActivePrototypeState,
    ApplyStructuredPrototypeCommandsResult,
    CreateStructuredPrototypeResult,
    PrototypeOperationDetail,
    PublishedPrototypeHistory,
    PublishedPrototypeSnapshot,
    PublishedRevisionDiffResult,
    PublishStructuredPrototypeResult,
    RecoverStructuredPrototypeResult,
    RollbackStructuredPrototypeResult,
    StructuredPrototypeService,
    StructuredPrototypeServiceError,
)
from app.domain.structured_prototype import (
    PrototypeOperation,
    PrototypeOperationEvent,
    PrototypeOperationKind,
    PrototypeOperationObservabilitySnapshot,
    PrototypeOperationStatus,
    PrototypeOperationStep,
    PrototypeReplayManifestV1,
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


class ApplyStructuredPrototypeHistoryRequestV1(StrictRequestModel):
    contract_version: Literal[1]
    client_request_id: Annotated[str, Field(min_length=36, max_length=36)]
    expected_head_sequence_no: Annotated[int, Field(ge=0)]
    expected_document_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


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


class ResetPrototypeRuntimeSessionRequestV1(StrictRequestModel):
    contract_version: Literal[1]
    client_request_id: Annotated[str, Field(min_length=36, max_length=36)]
    cause_operation_id: (
        Annotated[
            str,
            Field(pattern=r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$"),
        ]
        | None
    )
    expected_old_head_sequence_no: Annotated[int, Field(ge=0)]
    expected_old_state_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    expected_old_view_model_hash: Annotated[
        str,
        Field(pattern=r"^sha256:[0-9a-f]{64}$"),
    ]
    expected_old_runtime_core_bundle_hash: Annotated[
        str,
        Field(pattern=r"^sha256:[0-9a-f]{64}$"),
    ]
    target_draft_id: Annotated[str, Field(min_length=1, max_length=128)]
    expected_target_head_sequence_no: Annotated[int, Field(ge=0)]
    expected_target_document_hash: Annotated[
        str,
        Field(pattern=r"^sha256:[0-9a-f]{64}$"),
    ]
    scenario_id: Annotated[str, Field(min_length=1, max_length=128)]


class PublishStructuredPrototypeRequestV1(StrictRequestModel):
    contract_version: Literal[1]
    client_request_id: Annotated[str, Field(min_length=36, max_length=36)]
    expected_head_sequence_no: Annotated[int, Field(ge=0)]
    expected_document_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    summary: Annotated[str, Field(min_length=1, max_length=200)] | None = None


class RollbackStructuredPrototypeRequestV1(StrictRequestModel):
    contract_version: Literal[1]
    client_request_id: Annotated[str, Field(min_length=36, max_length=36)]
    target_revision_no: Annotated[int, Field(ge=1)]
    expected_current_revision_no: Annotated[int, Field(ge=1)]


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
    can_undo: bool
    can_redo: bool
    document: PrototypeDocumentV1


class DeleteStructuredPrototypeResponseV1(StrictResponseModel):
    contract_version: Literal[1]
    operation_id: str
    correlation_id: str
    deleted: bool


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
    pinned_document_object_hash: str
    replaces_session_id: str | None
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
    reset_manifest_hash: str | None


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


class RollbackStructuredPrototypeResponseV1(PublishedPrototypeResponseV1):
    operation_id: str
    correlation_id: str


class PublishedPrototypeRevisionResponseV1(StrictResponseModel):
    revision_id: str
    revision_no: int
    summary: str
    source: Literal["user", "ai", "initial_generation"]
    is_current: bool
    render_run_id: str
    artifact_id: str
    renderer_version: str
    document_hash: str
    output_hash: str
    published_at: str
    artifact_path: str


class PublicationTimelineEventResponseV1(StrictResponseModel):
    kind: Literal["publish", "rollback"]
    revision_no: int
    occurred_at: str
    summary: str | None


class StructuredPrototypeRevisionHistoryResponseV1(StrictResponseModel):
    contract_version: Literal[1]
    document_id: str
    current_revision_no: int | None
    revisions: list[PublishedPrototypeRevisionResponseV1]
    events: list[PublicationTimelineEventResponseV1]


class PrototypeRevisionDiffPageResponseV1(StrictResponseModel):
    id: str
    title: str
    route: str


class PrototypeRevisionDiffPageChangeResponseV1(PrototypeRevisionDiffPageResponseV1):
    title_changed: bool
    route_changed: bool
    nodes_added: int
    nodes_removed: int
    nodes_modified: int


class StructuredPrototypeRevisionDiffResponseV1(StrictResponseModel):
    contract_version: Literal[1]
    document_id: str
    base_revision_no: int
    target_revision_no: int
    identical: bool
    title_from: str | None
    title_to: str | None
    pages_added: list[PrototypeRevisionDiffPageResponseV1]
    pages_removed: list[PrototypeRevisionDiffPageResponseV1]
    pages_modified: list[PrototypeRevisionDiffPageChangeResponseV1]
    flows_added: int
    flows_removed: int
    flows_modified: int
    component_definitions_changed: bool
    settings_changed: bool
    tokens_changed: bool
    navigation_changed: bool
    runtime_changed: bool
    asset_refs_added: int
    asset_refs_removed: int


class StructuredPrototypeOperationOutcomeResponseV1(StrictResponseModel):
    contract_version: Literal[1]
    known: Literal[True]
    terminal: bool
    operation_id: str
    operation_kind: PrototypeOperationKind
    project_id: str
    resource_kind: str
    resource_id: str | None
    client_request_id: str
    correlation_id: str
    parent_operation_id: str | None
    status: PrototypeOperationStatus
    phase: str
    attempt: int
    request_manifest_hash: str
    config_manifest_hash: str
    result_manifest_hash: str | None
    failure_evidence_hash: str | None
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class StructuredPrototypeOperationStepResponseV1(StrictResponseModel):
    id: str
    operation_id: str
    parent_step_id: str | None
    step_kind: str
    step_ordinal: int
    attempt: int
    status: Literal["pending", "running", "succeeded", "failed", "skipped", "interrupted"]
    phase: str
    input_manifest_hash: str
    config_manifest_hash: str
    output_manifest_hash: str | None
    completion_evidence_kind: str | None
    completion_evidence_ref: str | None
    error_code: str | None
    started_at: datetime | None
    completed_at: datetime | None


class StructuredPrototypeOperationEventResponseV1(StrictResponseModel):
    operation_id: str
    event_no: int
    step_id: str | None
    event_kind: str
    status: Literal[
        "queued",
        "pending",
        "running",
        "succeeded",
        "failed",
        "skipped",
        "interrupted",
        "cancelled",
    ]
    phase: str
    input_hash: str | None
    output_hash: str | None
    evidence_hash: str | None
    error_code: str | None
    occurred_at: datetime


class PrototypeReplayManifestVersionsResponseV1(StrictResponseModel):
    service_version: str
    document_schema_version: int
    command_contract_version: int
    runtime_state_schema_version: int
    runtime_event_contract_version: int
    runtime_core_version: str | None
    runtime_core_bundle_hash: str | None
    state_machine_kernel_version: str | None
    renderer_version: str | None
    renderer_environment_version: str | None
    replay_manifest_version: Literal[1]


class PrototypeReplayManifestResponseV1(StrictResponseModel):
    manifest_version: Literal[1]
    operation_id: str
    operation_kind: PrototypeOperationKind
    parent_operation_id: str | None
    request_manifest_hash: str
    context_manifest_hash: str | None
    ordered_input_object_hashes: list[str]
    versions: PrototypeReplayManifestVersionsResponseV1
    agent_task_identity: dict[str, str] | None
    submission_hash: str | None
    ordered_command_batch_hashes: list[str]
    base_checkpoint_hash: str | None
    base_sequence_no: int | None
    result_checkpoint_hash: str | None
    result_sequence_no: int | None
    renderer_input_hash: str | None
    renderer_output_hash: str | None
    runtime_session_id: str | None
    runtime_core_bundle_hash: str | None
    ordered_runtime_event_hashes: list[str]
    runtime_final_state_hash: str | None
    runtime_final_view_model_hash: str | None
    validation_report_hashes: list[str]
    terminal_status: Literal["succeeded"]
    error_code: None


class StructuredPrototypeOperationDetailResponseV1(StrictResponseModel):
    contract_version: Literal[1]
    operation: StructuredPrototypeOperationOutcomeResponseV1
    steps: list[StructuredPrototypeOperationStepResponseV1]
    child_operation_ids: list[str]
    replay_manifest: PrototypeReplayManifestResponseV1 | None


class StructuredPrototypeOperationEventsResponseV1(StrictResponseModel):
    contract_version: Literal[1]
    operation_id: str
    events: list[StructuredPrototypeOperationEventResponseV1]


class PrototypeRuntimeErrorDetailV1(StrictResponseModel):
    code: str
    message: str
    retryable: bool
    current_head_sequence_no: int | None
    current_state_hash: str | None
    current_view_model_hash: str | None
    runtime_core_bundle_hash: str | None
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
    if code in SNAP_WORKER_INFRASTRUCTURE_ERROR_CODES:
        return 503
    if code in {
        "document_missing",
        "draft_missing",
        "revision_missing",
        "render_run_missing",
        "published_artifact_missing",
        "render_artifact_missing",
        "render_artifact_file_missing",
        "operation_missing",
        "operation_outcome_unknown",
    }:
        return 404
    if code in {
        "draft_conflict",
        "command_history_conflict",
        "command_history_corrupt",
        "operation_idempotency_conflict",
        "draft_not_active",
        "draft_corrupt",
        "operation_in_progress",
        "prototype_busy",
        "idempotent_result_superseded",
        "object_hash_mismatch",
        "object_missing",
        "replay_document_hash_mismatch",
        "replay_batch_hash_mismatch",
        "publication_state_conflict",
        "revision_sequence_conflict",
        "render_run_conflict",
        "rollback_target_current",
        "rollback_conflict",
        "undo_unavailable",
        "redo_unavailable",
    }:
        return 409
    if code in {
        "client_request_id_invalid",
        "operation_id_invalid",
        "command_batch_invalid",
        "command_evidence_mismatch",
        "command_target_invalid",
        "command_target_in_use",
        "command_target_missing",
        "command_index_invalid",
        "command_property_invalid",
        "command_result_invalid",
        "command_value_invalid",
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
        "runtime_replay_contract_unsupported",
        "runtime_document_checkpoint_mismatch",
        "runtime_session_reset_not_allowed",
        "runtime_session_reset_target_mismatch",
        "draft_conflict",
        "operation_in_progress",
        "operation_idempotency_conflict",
        "operation_identity_conflict",
        "runtime_reset_cause_invalid",
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
        "runtime_worker_identity_mismatch",
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
            current_view_model_hash=exc.current_view_model_hash,
            runtime_core_bundle_hash=exc.runtime_core_bundle_hash,
            resource_url=exc.resource_url,
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


def _operation_outcome_response(
    operation: PrototypeOperation,
) -> StructuredPrototypeOperationOutcomeResponseV1:
    return StructuredPrototypeOperationOutcomeResponseV1(
        contract_version=HTTP_CONTRACT_VERSION,
        known=True,
        terminal=operation.status in {"succeeded", "failed", "interrupted", "cancelled"},
        operation_id=operation.id,
        operation_kind=operation.operation_kind,
        project_id=operation.project_id,
        resource_kind=operation.resource_kind,
        resource_id=operation.resource_id,
        client_request_id=operation.client_request_id,
        correlation_id=operation.correlation_id,
        parent_operation_id=operation.parent_operation_id,
        status=operation.status,
        phase=operation.phase,
        attempt=operation.attempt,
        request_manifest_hash=operation.request_manifest_hash,
        config_manifest_hash=operation.config_manifest_hash,
        result_manifest_hash=operation.result_manifest_hash,
        failure_evidence_hash=operation.failure_evidence_hash,
        error_code=operation.error_code,
        created_at=operation.created_at,
        started_at=operation.started_at,
        completed_at=operation.completed_at,
    )


def _operation_step_response(
    step: PrototypeOperationStep,
) -> StructuredPrototypeOperationStepResponseV1:
    return StructuredPrototypeOperationStepResponseV1(
        id=step.id,
        operation_id=step.operation_id,
        parent_step_id=step.parent_step_id,
        step_kind=step.step_kind,
        step_ordinal=step.step_ordinal,
        attempt=step.attempt,
        status=step.status,
        phase=step.phase,
        input_manifest_hash=step.input_manifest_hash,
        config_manifest_hash=step.config_manifest_hash,
        output_manifest_hash=step.output_manifest_hash,
        completion_evidence_kind=step.completion_evidence_kind,
        completion_evidence_ref=step.completion_evidence_ref,
        error_code=step.error_code,
        started_at=step.started_at,
        completed_at=step.completed_at,
    )


def _operation_event_response(
    event: PrototypeOperationEvent,
) -> StructuredPrototypeOperationEventResponseV1:
    return StructuredPrototypeOperationEventResponseV1(
        operation_id=event.operation_id,
        event_no=event.event_no,
        step_id=event.step_id,
        event_kind=event.event_kind,
        status=event.status,
        phase=event.phase,
        input_hash=event.input_hash,
        output_hash=event.output_hash,
        evidence_hash=event.evidence_hash,
        error_code=event.error_code,
        occurred_at=event.occurred_at,
    )


def _replay_manifest_response(
    manifest: PrototypeReplayManifestV1,
) -> PrototypeReplayManifestResponseV1:
    versions = manifest.versions
    return PrototypeReplayManifestResponseV1(
        manifest_version=1,
        operation_id=manifest.operation_id,
        operation_kind=manifest.operation_kind,
        parent_operation_id=manifest.parent_operation_id,
        request_manifest_hash=manifest.request_manifest_hash,
        context_manifest_hash=manifest.context_manifest_hash,
        ordered_input_object_hashes=list(manifest.ordered_input_object_hashes),
        versions=PrototypeReplayManifestVersionsResponseV1(
            service_version=versions.service_version,
            document_schema_version=versions.document_schema_version,
            command_contract_version=versions.command_contract_version,
            runtime_state_schema_version=versions.runtime_state_schema_version,
            runtime_event_contract_version=versions.runtime_event_contract_version,
            runtime_core_version=versions.runtime_core_version,
            runtime_core_bundle_hash=versions.runtime_core_bundle_hash,
            state_machine_kernel_version=versions.state_machine_kernel_version,
            renderer_version=versions.renderer_version,
            renderer_environment_version=versions.renderer_environment_version,
            replay_manifest_version=1,
        ),
        agent_task_identity=(
            dict(manifest.agent_task_identity) if manifest.agent_task_identity is not None else None
        ),
        submission_hash=manifest.submission_hash,
        ordered_command_batch_hashes=list(manifest.ordered_command_batch_hashes),
        base_checkpoint_hash=manifest.base_checkpoint_hash,
        base_sequence_no=manifest.base_sequence_no,
        result_checkpoint_hash=manifest.result_checkpoint_hash,
        result_sequence_no=manifest.result_sequence_no,
        renderer_input_hash=manifest.renderer_input_hash,
        renderer_output_hash=manifest.renderer_output_hash,
        runtime_session_id=manifest.runtime_session_id,
        runtime_core_bundle_hash=manifest.runtime_core_bundle_hash,
        ordered_runtime_event_hashes=list(manifest.ordered_runtime_event_hashes),
        runtime_final_state_hash=manifest.runtime_final_state_hash,
        runtime_final_view_model_hash=manifest.runtime_final_view_model_hash,
        validation_report_hashes=list(manifest.validation_report_hashes),
        terminal_status="succeeded",
        error_code=None,
    )


def _operation_detail_response(
    detail: PrototypeOperationDetail,
) -> StructuredPrototypeOperationDetailResponseV1:
    return StructuredPrototypeOperationDetailResponseV1(
        contract_version=HTTP_CONTRACT_VERSION,
        operation=_operation_outcome_response(detail.snapshot.operation),
        steps=[_operation_step_response(step) for step in detail.snapshot.steps],
        child_operation_ids=[child.id for child in detail.snapshot.child_operations],
        replay_manifest=(
            _replay_manifest_response(detail.replay_manifest)
            if detail.replay_manifest is not None
            else None
        ),
    )


def _operation_events_response(
    snapshot: PrototypeOperationObservabilitySnapshot,
) -> StructuredPrototypeOperationEventsResponseV1:
    return StructuredPrototypeOperationEventsResponseV1(
        contract_version=HTTP_CONTRACT_VERSION,
        operation_id=snapshot.operation.id,
        events=[_operation_event_response(event) for event in snapshot.events],
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
        can_undo=state.command_history.can_undo,
        can_redo=state.command_history.can_redo,
        document=state.document,
    )


def _runtime_state_response(
    *,
    operation_id: str,
    correlation_id: str,
    state: ActivePrototypeRuntimeState,
    reset_manifest_hash: str | None = None,
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
        pinned_document_object_hash=session.pinned_document_object_hash,
        replaces_session_id=session.replaces_session_id,
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
        reset_manifest_hash=reset_manifest_hash,
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


def _revision_history_response(
    history: PublishedPrototypeHistory,
) -> StructuredPrototypeRevisionHistoryResponseV1:
    return StructuredPrototypeRevisionHistoryResponseV1(
        contract_version=HTTP_CONTRACT_VERSION,
        document_id=history.document_id,
        current_revision_no=history.current_revision_no,
        revisions=[
            PublishedPrototypeRevisionResponseV1(
                revision_id=entry.publication.revision_id,
                revision_no=entry.publication.revision_no,
                summary=entry.summary,
                source=entry.source,
                is_current=entry.is_current,
                render_run_id=entry.publication.render_run_id,
                artifact_id=entry.publication.artifact_id,
                renderer_version=entry.publication.renderer_version,
                document_hash=entry.publication.document_hash,
                output_hash=entry.publication.output_hash,
                published_at=entry.publication.published_at.isoformat(),
                artifact_path=(
                    f"/api/structured-prototype-public/{entry.publication.document_id}"
                    f"/revisions/{entry.publication.revision_no}"
                    f"/artifacts/{entry.publication.artifact_id}/index.html"
                ),
            )
            for entry in history.revisions
        ],
        events=[
            PublicationTimelineEventResponseV1(
                kind=event.kind,
                revision_no=event.revision_no,
                occurred_at=event.occurred_at.isoformat(),
                summary=event.summary,
            )
            for event in history.events
        ],
    )


def _revision_diff_response(
    result: PublishedRevisionDiffResult,
) -> StructuredPrototypeRevisionDiffResponseV1:
    diff = result.diff
    return StructuredPrototypeRevisionDiffResponseV1(
        contract_version=HTTP_CONTRACT_VERSION,
        document_id=result.document_id,
        base_revision_no=result.base_revision_no,
        target_revision_no=result.target_revision_no,
        identical=diff.identical,
        title_from=diff.title_from,
        title_to=diff.title_to,
        pages_added=[
            PrototypeRevisionDiffPageResponseV1(id=page.id, title=page.title, route=page.route)
            for page in diff.pages_added
        ],
        pages_removed=[
            PrototypeRevisionDiffPageResponseV1(id=page.id, title=page.title, route=page.route)
            for page in diff.pages_removed
        ],
        pages_modified=[
            PrototypeRevisionDiffPageChangeResponseV1(
                id=page.id,
                title=page.title,
                route=page.route,
                title_changed=page.title_changed,
                route_changed=page.route_changed,
                nodes_added=page.nodes_added,
                nodes_removed=page.nodes_removed,
                nodes_modified=page.nodes_modified,
            )
            for page in diff.pages_modified
        ],
        flows_added=diff.flows_added,
        flows_removed=diff.flows_removed,
        flows_modified=diff.flows_modified,
        component_definitions_changed=diff.component_definitions_changed,
        settings_changed=diff.settings_changed,
        tokens_changed=diff.tokens_changed,
        navigation_changed=diff.navigation_changed,
        runtime_changed=diff.runtime_changed,
        asset_refs_added=diff.asset_refs_added,
        asset_refs_removed=diff.asset_refs_removed,
    )


def _rollback_response(
    result: RollbackStructuredPrototypeResult,
) -> RollbackStructuredPrototypeResponseV1:
    published = _published_response(result.publication)
    return RollbackStructuredPrototypeResponseV1(
        **published.model_dump(),
        operation_id=result.operation_id,
        correlation_id=result.correlation_id,
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


@router.get(
    "/projects/{project_id}/structured-prototype-operations/outcome",
    response_model=StructuredPrototypeOperationOutcomeResponseV1,
)
async def get_structured_prototype_operation_outcome(
    project_id: str,
    operation_kind: Annotated[
        PrototypeOperationKind,
        Query(alias="operationKind"),
    ],
    client_request_id: Annotated[
        str,
        Query(alias="clientRequestId", min_length=36, max_length=36),
    ],
) -> StructuredPrototypeOperationOutcomeResponseV1 | JSONResponse:
    try:
        operation = await _require_service().get_operation_outcome(
            project_id=project_id,
            operation_kind=operation_kind,
            client_request_id=client_request_id,
        )
    except StructuredPrototypeServiceError as exc:
        return _service_failure(exc)
    return _operation_outcome_response(operation)


@router.get(
    "/prototype-operations/{operation_id}/events",
    response_model=StructuredPrototypeOperationEventsResponseV1,
)
async def get_structured_prototype_operation_events(
    operation_id: str,
) -> StructuredPrototypeOperationEventsResponseV1 | JSONResponse:
    try:
        snapshot = await _require_service().get_operation_events(operation_id)
    except StructuredPrototypeServiceError as exc:
        return _service_failure(exc)
    return _operation_events_response(snapshot)


@router.get(
    "/prototype-operations/{operation_id}",
    response_model=StructuredPrototypeOperationDetailResponseV1,
)
async def get_structured_prototype_operation_detail(
    operation_id: str,
) -> StructuredPrototypeOperationDetailResponseV1 | JSONResponse:
    try:
        detail = await _require_service().get_operation_detail(operation_id)
    except StructuredPrototypeServiceError as exc:
        return _service_failure(exc)
    return _operation_detail_response(detail)


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


@router.delete(
    "/projects/{project_id}/structured-prototype-documents",
    response_model=DeleteStructuredPrototypeResponseV1,
)
async def delete_project_structured_prototype(
    project_id: str,
    client_request_id: Annotated[
        str,
        Query(alias="clientRequestId", min_length=36, max_length=36),
    ],
) -> DeleteStructuredPrototypeResponseV1 | JSONResponse:
    try:
        UUID(client_request_id)
        result = await _require_service().delete_project_prototype(
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
    return DeleteStructuredPrototypeResponseV1(
        contract_version=HTTP_CONTRACT_VERSION,
        operation_id=result.operation_id,
        correlation_id=result.correlation_id,
        deleted=result.deleted,
    )


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
    "/structured-prototype-drafts/{draft_id}/undo",
    response_model=ApplyStructuredPrototypeCommandsResponseV1,
)
async def undo_structured_prototype_commands(
    draft_id: str,
    body: ApplyStructuredPrototypeHistoryRequestV1,
) -> ApplyStructuredPrototypeCommandsResponseV1 | JSONResponse:
    try:
        result = await _require_service().undo(
            draft_id=draft_id,
            client_request_id=body.client_request_id,
            expected_head_sequence_no=body.expected_head_sequence_no,
            expected_document_hash=body.expected_document_hash,
        )
    except StructuredPrototypeServiceError as exc:
        return _service_failure(exc)
    return _apply_response(result)


@router.post(
    "/structured-prototype-drafts/{draft_id}/redo",
    response_model=ApplyStructuredPrototypeCommandsResponseV1,
)
async def redo_structured_prototype_commands(
    draft_id: str,
    body: ApplyStructuredPrototypeHistoryRequestV1,
) -> ApplyStructuredPrototypeCommandsResponseV1 | JSONResponse:
    try:
        result = await _require_service().redo(
            draft_id=draft_id,
            client_request_id=body.client_request_id,
            expected_head_sequence_no=body.expected_head_sequence_no,
            expected_document_hash=body.expected_document_hash,
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
            summary=body.summary,
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
    "/structured-prototype-documents/{document_id}/revisions",
    response_model=StructuredPrototypeRevisionHistoryResponseV1,
)
async def list_structured_prototype_revisions(
    document_id: str,
) -> StructuredPrototypeRevisionHistoryResponseV1 | JSONResponse:
    try:
        history = await _require_service().list_published_revisions(document_id)
    except StructuredPrototypeServiceError as exc:
        return _service_failure(exc)
    return _revision_history_response(history)


@router.get(
    "/structured-prototype-documents/{document_id}/revisions/{revision_no}/diff",
    response_model=StructuredPrototypeRevisionDiffResponseV1,
)
async def diff_structured_prototype_revisions(
    document_id: str,
    revision_no: int,
    against: Annotated[int | None, Query(alias="against", ge=1)] = None,
) -> StructuredPrototypeRevisionDiffResponseV1 | JSONResponse:
    try:
        result = await _require_service().diff_published_revisions(
            document_id=document_id,
            target_revision_no=revision_no,
            base_revision_no=against,
        )
    except StructuredPrototypeServiceError as exc:
        return _service_failure(exc)
    return _revision_diff_response(result)


@router.post(
    "/structured-prototype-documents/{document_id}/rollback",
    response_model=RollbackStructuredPrototypeResponseV1,
)
async def rollback_structured_prototype_publication(
    document_id: str,
    body: RollbackStructuredPrototypeRequestV1,
) -> RollbackStructuredPrototypeResponseV1 | JSONResponse:
    try:
        result = await _require_service().rollback_publication(
            document_id=document_id,
            client_request_id=body.client_request_id,
            target_revision_no=body.target_revision_no,
            expected_current_revision_no=body.expected_current_revision_no,
        )
    except StructuredPrototypeServiceError as exc:
        return _service_failure(exc)
    return _rollback_response(result)


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


@router.post(
    "/structured-prototype-runtime-sessions/{session_id}/reset",
    response_model=PrototypeRuntimeSessionResponseV1,
    status_code=201,
)
async def reset_prototype_runtime_session(
    session_id: str,
    body: ResetPrototypeRuntimeSessionRequestV1,
) -> PrototypeRuntimeSessionResponseV1 | JSONResponse:
    try:
        service = _require_service()
        result = await service.reset_runtime_session(
            session_id=session_id,
            client_request_id=body.client_request_id,
            cause_operation_id=body.cause_operation_id,
            expected_old_head_sequence_no=body.expected_old_head_sequence_no,
            expected_old_state_hash=body.expected_old_state_hash,
            expected_old_view_model_hash=body.expected_old_view_model_hash,
            expected_old_runtime_core_bundle_hash=(body.expected_old_runtime_core_bundle_hash),
            target_draft_id=body.target_draft_id,
            expected_target_head_sequence_no=body.expected_target_head_sequence_no,
            expected_target_document_hash=body.expected_target_document_hash,
            scenario_id=body.scenario_id,
        )
    except StructuredPrototypeServiceError as exc:
        return _runtime_service_failure(exc)
    return _runtime_state_response(
        operation_id=result.operation_id,
        correlation_id=result.correlation_id,
        state=result.state,
        reset_manifest_hash=result.reset_manifest_hash,
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
            current_view_model_hash=None,
            runtime_core_bundle_hash=None,
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
        can_undo=state.command_history.can_undo,
        can_redo=state.command_history.can_redo,
        applied_batch_id=result.applied_batch_id,
        allocated_entity_ids=[
            AllocatedEntityIdResponseV1(new_node_key=key, entity_id=entity_id)
            for key, entity_id in result.allocated_entity_ids
        ],
        affected_entity_ids=list(result.affected_entity_ids),
        document=state.document,
    )
