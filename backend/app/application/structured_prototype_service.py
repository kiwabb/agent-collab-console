from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID, uuid5

from app.adapters.prototype_object_store import (
    CANONICALIZER_VERSION,
    PrototypeObjectStoreError,
    canonical_json_bytes,
)
from app.adapters.prototype_render_artifact_store import (
    PrototypeRenderArtifactStoreError,
)
from app.adapters.prototype_renderer_worker import PrototypeRendererWorkerError
from app.adapters.prototype_runtime_worker import PrototypeRuntimeWorkerError
from app.adapters.structured_prototype_store import StructuredPrototypeStoreError
from app.application.structured_prototype_contracts import (
    COMMAND_CONTRACT_VERSION,
    DOCUMENT_SCHEMA_VERSION,
    DomainCommandBatchV1,
    NewPrototypeDocumentV1,
    PrototypeDocumentV1,
    StructuredPrototypeContractError,
    apply_inverse_commands,
    canonical_model_json,
    command_batch_hash,
    document_hash,
    document_payload,
    execute_command_batch,
    parse_command_batch_json,
    parse_inverse_command_batch_json,
    parse_prototype_document_json,
)
from app.domain.structured_prototype import (
    PrototypeCheckpointRecord,
    PrototypeCommandAppendResult,
    PrototypeCommandBatchRecord,
    PrototypeDocumentRecord,
    PrototypeDraftRecord,
    PrototypeDraftRecoveryBundle,
    PrototypeObjectDescriptor,
    PrototypeObjectReference,
    PrototypeOperation,
    PrototypeOperationCreateResult,
    PrototypeOperationEvent,
    PrototypeOperationKind,
    PrototypeOperationStep,
    PrototypePublicationCompletionResult,
    PrototypePublicationFreezeResult,
    PrototypePublishedRecord,
    PrototypeRenderArtifactRecord,
    PrototypeRenderBundleDescriptor,
    PrototypeRendererWorkerIdentity,
    PrototypeRendererWorkerResult,
    PrototypeRenderRunRecord,
    PrototypeRevisionRecord,
    PrototypeRuntimeCheckpointRecord,
    PrototypeRuntimeEventAppendResult,
    PrototypeRuntimeEventBatchRecord,
    PrototypeRuntimeRecordingKind,
    PrototypeRuntimeRecoveryBundle,
    PrototypeRuntimeSessionRecord,
    PrototypeRuntimeWorkerIdentity,
    PrototypeRuntimeWorkerReplayResult,
    PrototypeRuntimeWorkerStateResult,
    PrototypeRuntimeWorkerTransitionResult,
)
from app.json_safety import object_dict_or_none

OPERATION_EVIDENCE_VERSION = 1
SERVICE_VERSION = "structured-prototype-service/0.1.0"
PROTOTYPE_SERVICE_NAMESPACE = UUID("7c196dbd-592b-50a3-908b-6de3288d8829")
RUNTIME_STATE_SCHEMA_VERSION = 1
RUNTIME_EVENT_CONTRACT_VERSION = 1

CORRUPTION_ERROR_CODES = frozenset(
    {
        "object_missing",
        "object_hash_mismatch",
        "object_readback_failed",
        "object_path_invalid",
        "object_descriptor_corrupt",
        "document_invalid",
        "document_identity_mismatch",
        "replay_sequence_gap",
        "replay_batch_hash_mismatch",
        "replay_document_hash_mismatch",
        "replay_contract_unsupported",
        "inverse_command_batch_invalid",
        "inverse_command_mismatch",
        "draft_corrupt",
        "checkpoint_missing",
        "runtime_session_corrupt",
        "runtime_checkpoint_missing",
        "runtime_replay_sequence_gap",
        "runtime_replay_state_hash_mismatch",
        "runtime_replay_version_mismatch",
        "runtime_worker_state_hash_mismatch",
        "runtime_worker_view_model_hash_mismatch",
        "runtime_worker_event_batch_hash_mismatch",
        "runtime_worker_guard_report_hash_mismatch",
        "runtime_worker_effect_report_hash_mismatch",
        "runtime_worker_transition_evidence_mismatch",
        "runtime_worker_replay_hash_mismatch",
        "runtime_checkpoint_state_hash_mismatch",
        "runtime_document_hash_mismatch",
        "runtime_scenario_hash_mismatch",
        "runtime_replay_evidence_mismatch",
        "runtime_event_payload_invalid",
        "runtime_checkpoint_state_invalid",
        "runtime_document_identity_mismatch",
    }
)

RETRYABLE_ERROR_CODES = frozenset(
    {
        "draft_conflict",
        "operation_in_progress",
        "object_write_failed",
        "checkpoint_required_unavailable",
        "operation_evidence_unavailable",
        "runtime_session_conflict",
        "runtime_checkpoint_required_unavailable",
        "runtime_worker_timeout",
        "runtime_worker_spawn_failed",
    }
)


class StructuredPrototypePersistence(Protocol):
    async def create_operation(
        self,
        operation: PrototypeOperation,
        initial_event: PrototypeOperationEvent,
    ) -> PrototypeOperationCreateResult: ...

    async def load_operation(self, operation_id: str) -> PrototypeOperation | None: ...

    async def record_operation_transition(
        self,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        event: PrototypeOperationEvent,
    ) -> None: ...

    async def create_document_with_initial_checkpoint(
        self,
        *,
        descriptor: PrototypeObjectDescriptor,
        reference: PrototypeObjectReference,
        document: PrototypeDocumentRecord,
        draft: PrototypeDraftRecord,
        checkpoint: PrototypeCheckpointRecord,
        completed_operation: PrototypeOperation,
        completion_step: PrototypeOperationStep,
        completion_event: PrototypeOperationEvent,
    ) -> None: ...

    async def load_document(self, document_id: str) -> PrototypeDocumentRecord | None: ...

    async def load_current_project_document(
        self,
        project_id: str,
    ) -> PrototypeDocumentRecord | None: ...

    async def load_draft(self, draft_id: str) -> PrototypeDraftRecord | None: ...

    async def load_command_batch_by_request(
        self,
        draft_id: str,
        client_request_id: str,
    ) -> PrototypeCommandBatchRecord | None: ...

    async def append_command_batch(
        self,
        *,
        batch: PrototypeCommandBatchRecord,
        completed_operation: PrototypeOperation,
        completion_step: PrototypeOperationStep,
        completion_event: PrototypeOperationEvent,
    ) -> PrototypeCommandAppendResult: ...

    async def register_draft_checkpoint(
        self,
        *,
        descriptor: PrototypeObjectDescriptor,
        reference: PrototypeObjectReference,
        checkpoint: PrototypeCheckpointRecord,
        completed_operation: PrototypeOperation,
        completion_step: PrototypeOperationStep,
        completion_event: PrototypeOperationEvent,
    ) -> PrototypeDraftRecord: ...

    async def load_draft_recovery_bundle(
        self,
        draft_id: str,
    ) -> PrototypeDraftRecoveryBundle: ...

    async def mark_draft_corrupt(
        self,
        *,
        draft_id: str,
        expected_head_sequence_no: int,
        expected_document_hash: str,
        failed_operation: PrototypeOperation,
        failed_step: PrototypeOperationStep,
        failure_event: PrototypeOperationEvent,
    ) -> PrototypeDraftRecord: ...

    async def load_object(
        self,
        project_id: str,
        content_hash: str,
    ) -> PrototypeObjectDescriptor | None: ...

    async def load_runtime_session(
        self,
        session_id: str,
    ) -> PrototypeRuntimeSessionRecord | None: ...

    async def load_runtime_event_batch_by_request(
        self,
        session_id: str,
        client_event_id: str,
    ) -> PrototypeRuntimeEventBatchRecord | None: ...

    async def create_runtime_session_with_initial_checkpoint(
        self,
        *,
        descriptor: PrototypeObjectDescriptor,
        reference: PrototypeObjectReference,
        session: PrototypeRuntimeSessionRecord,
        checkpoint: PrototypeRuntimeCheckpointRecord,
        completed_operation: PrototypeOperation,
        completion_step: PrototypeOperationStep,
        completion_event: PrototypeOperationEvent,
    ) -> None: ...

    async def next_revision_no(self, document_id: str) -> int: ...

    async def load_revision(self, revision_id: str) -> PrototypeRevisionRecord | None: ...

    async def load_render_run_by_operation(
        self,
        operation_id: str,
    ) -> PrototypeRenderRunRecord | None: ...

    async def load_render_artifact(
        self,
        artifact_id: str,
    ) -> PrototypeRenderArtifactRecord | None: ...

    async def freeze_publication(
        self,
        *,
        document_descriptor: PrototypeObjectDescriptor,
        revision_reference: PrototypeObjectReference,
        input_descriptor: PrototypeObjectDescriptor,
        input_reference: PrototypeObjectReference,
        revision: PrototypeRevisionRecord,
        revision_checkpoint: PrototypeCheckpointRecord,
        render_run: PrototypeRenderRunRecord,
        expected_draft_id: str,
        expected_head_sequence_no: int,
        expected_document_hash: str,
        running_operation: PrototypeOperation,
        completed_step: PrototypeOperationStep,
        completion_event: PrototypeOperationEvent,
    ) -> PrototypePublicationFreezeResult: ...

    async def mark_publication_rendering(
        self,
        *,
        render_run_id: str,
        started_at: datetime,
        running_operation: PrototypeOperation,
        running_step: PrototypeOperationStep,
        started_event: PrototypeOperationEvent,
    ) -> PrototypeRenderRunRecord: ...

    async def fail_publication(
        self,
        *,
        render_run_id: str,
        draft_id: str,
        error_code: str,
        error_message: str,
        failed_at: datetime,
        failed_operation: PrototypeOperation,
        failed_step: PrototypeOperationStep,
        failed_event: PrototypeOperationEvent,
    ) -> None: ...

    async def complete_publication(
        self,
        *,
        artifact: PrototypeRenderArtifactRecord,
        output_descriptor: PrototypeObjectDescriptor,
        output_reference: PrototypeObjectReference,
        preflight_descriptor: PrototypeObjectDescriptor,
        preflight_reference: PrototypeObjectReference,
        replay_descriptor: PrototypeObjectDescriptor,
        replay_reference: PrototypeObjectReference,
        publishing_draft_id: str,
        active_draft: PrototypeDraftRecord,
        active_checkpoint: PrototypeCheckpointRecord,
        active_checkpoint_reference: PrototypeObjectReference,
        completed_operation: PrototypeOperation,
        completed_step: PrototypeOperationStep,
        completion_event: PrototypeOperationEvent,
    ) -> PrototypePublicationCompletionResult: ...

    async def load_published_record(self, document_id: str) -> PrototypePublishedRecord | None: ...

    async def load_ready_publication(
        self,
        document_id: str,
        revision_no: int,
        artifact_id: str,
    ) -> PrototypePublishedRecord | None: ...

    async def recover_interrupted_publications(self, recovered_at: datetime) -> int: ...

    async def append_runtime_event_batch(
        self,
        *,
        event_batch: PrototypeRuntimeEventBatchRecord,
        completed_operation: PrototypeOperation,
        completion_step: PrototypeOperationStep,
        completion_event: PrototypeOperationEvent,
    ) -> PrototypeRuntimeEventAppendResult: ...

    async def register_runtime_checkpoint(
        self,
        *,
        descriptor: PrototypeObjectDescriptor,
        reference: PrototypeObjectReference,
        checkpoint: PrototypeRuntimeCheckpointRecord,
        completed_operation: PrototypeOperation,
        completion_step: PrototypeOperationStep,
        completion_event: PrototypeOperationEvent,
    ) -> PrototypeRuntimeSessionRecord: ...

    async def load_runtime_recovery_bundle(
        self,
        session_id: str,
    ) -> PrototypeRuntimeRecoveryBundle: ...

    async def mark_runtime_session_corrupt(
        self,
        *,
        session_id: str,
        expected_head_sequence_no: int,
        expected_state_hash: str,
        expected_view_model_hash: str,
        failed_operation: PrototypeOperation,
        failed_step: PrototypeOperationStep,
        failure_event: PrototypeOperationEvent,
    ) -> PrototypeRuntimeSessionRecord: ...


class PrototypeObjectStorage(Protocol):
    def write_json(self, project_id: str, value: object) -> PrototypeObjectDescriptor: ...

    def read_canonical_bytes(self, descriptor: PrototypeObjectDescriptor) -> bytes: ...


class PrototypeRuntimeExecution(Protocol):
    identity: PrototypeRuntimeWorkerIdentity

    async def initialize_state(
        self,
        *,
        request_id: str,
        definition: dict[str, object],
        scenario_id: str,
        session_id: str,
    ) -> PrototypeRuntimeWorkerStateResult: ...

    async def apply_event_batch(
        self,
        *,
        request_id: str,
        definition: dict[str, object],
        state_json: str,
        batch: dict[str, object],
    ) -> PrototypeRuntimeWorkerTransitionResult: ...

    async def replay_event_batches(
        self,
        *,
        request_id: str,
        definition: dict[str, object],
        state_json: str,
        batches: list[dict[str, object]],
    ) -> PrototypeRuntimeWorkerReplayResult: ...


class PrototypeRendererExecution(Protocol):
    identity: PrototypeRendererWorkerIdentity

    async def render(
        self,
        *,
        request_id: str,
        artifact_id: str,
        input_manifest: dict[str, object],
        document: dict[str, object],
    ) -> PrototypeRendererWorkerResult: ...


class PrototypeRenderArtifactStorage(Protocol):
    def write_bundle(
        self,
        *,
        project_id: str,
        document_id: str,
        artifact_id: str,
        result: PrototypeRendererWorkerResult,
    ) -> PrototypeRenderBundleDescriptor: ...

    def read_file(
        self,
        descriptor: PrototypeRenderBundleDescriptor,
        relative_path: str,
    ) -> bytes: ...


class StructuredPrototypeServiceError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        operation_id: str | None = None,
        current_head_sequence_no: int | None = None,
        current_document_hash: str | None = None,
        current_state_hash: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.operation_id = operation_id
        self.correlation_id = (
            _stable_id(operation_id, "correlation") if operation_id is not None else None
        )
        self.retryable = code in RETRYABLE_ERROR_CODES
        self.current_head_sequence_no = current_head_sequence_no
        self.current_document_hash = current_document_hash
        self.current_state_hash = current_state_hash


@dataclass(frozen=True, slots=True)
class ActivePrototypeState:
    document_record: PrototypeDocumentRecord
    draft: PrototypeDraftRecord
    document: PrototypeDocumentV1
    loaded_checkpoint_id: str
    loaded_checkpoint_sequence_no: int
    applied_tail_batch_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CreateStructuredPrototypeResult:
    operation_id: str
    correlation_id: str
    state: ActivePrototypeState


@dataclass(frozen=True, slots=True)
class RecoverStructuredPrototypeResult:
    operation_id: str
    correlation_id: str
    state: ActivePrototypeState


@dataclass(frozen=True, slots=True)
class CheckpointStructuredPrototypeResult:
    operation_id: str
    correlation_id: str
    checkpoint_id: str
    state: ActivePrototypeState


@dataclass(frozen=True, slots=True)
class ApplyStructuredPrototypeCommandsResult:
    operation_id: str
    correlation_id: str
    applied_batch_id: str
    allocated_entity_ids: tuple[tuple[str, str], ...]
    affected_entity_ids: tuple[str, ...]
    state: ActivePrototypeState


@dataclass(frozen=True, slots=True)
class PublishedPrototypeSnapshot:
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
    published_at: datetime


@dataclass(frozen=True, slots=True)
class PublishStructuredPrototypeResult:
    operation_id: str
    correlation_id: str
    publication: PublishedPrototypeSnapshot
    state: ActivePrototypeState


@dataclass(frozen=True, slots=True)
class PublishedPrototypeFile:
    publication: PublishedPrototypeSnapshot
    relative_path: str
    content: bytes


@dataclass(frozen=True, slots=True)
class ActivePrototypeRuntimeState:
    session: PrototypeRuntimeSessionRecord
    state_json: str
    view_model_json: str
    loaded_checkpoint_id: str
    loaded_checkpoint_sequence_no: int
    replayed_event_batch_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CreatePrototypeRuntimeSessionResult:
    operation_id: str
    correlation_id: str
    state: ActivePrototypeRuntimeState


@dataclass(frozen=True, slots=True)
class ApplyPrototypeRuntimeEventResult:
    operation_id: str
    correlation_id: str
    event_batch_id: str
    outcome: Literal["applied", "guard_false", "validation_failed"]
    state: ActivePrototypeRuntimeState


@dataclass(frozen=True, slots=True)
class RecoverPrototypeRuntimeSessionResult:
    operation_id: str
    correlation_id: str
    state: ActivePrototypeRuntimeState


@dataclass(frozen=True, slots=True)
class CheckpointPrototypeRuntimeSessionResult:
    operation_id: str
    correlation_id: str
    checkpoint_id: str
    state: ActivePrototypeRuntimeState


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _stable_id(*parts: str) -> str:
    return str(uuid5(PROTOTYPE_SERVICE_NAMESPACE, "\x1f".join(parts)))


def _manifest_hash(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def _require_client_request_id(value: str) -> None:
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise StructuredPrototypeServiceError(
            "client_request_id_invalid",
            "prototype client request ID must be a UUID",
        ) from exc
    if str(parsed) != value:
        raise StructuredPrototypeServiceError(
            "client_request_id_invalid",
            "prototype client request ID must use canonical lowercase UUID form",
        )


class StructuredPrototypeService:
    def __init__(
        self,
        *,
        store: StructuredPrototypePersistence,
        object_store: PrototypeObjectStorage,
        runtime_worker: PrototypeRuntimeExecution | None = None,
        renderer_worker: PrototypeRendererExecution | None = None,
        artifact_store: PrototypeRenderArtifactStorage | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._store = store
        self._object_store = object_store
        self._runtime_worker = runtime_worker
        self._renderer_worker = renderer_worker
        self._artifact_store = artifact_store
        self._clock = clock

    async def create_document(
        self,
        *,
        project_id: str,
        client_request_id: str,
        document: NewPrototypeDocumentV1,
    ) -> CreateStructuredPrototypeResult:
        _require_client_request_id(client_request_id)
        document_id = _stable_id(project_id, client_request_id, "document")
        materialized = document.materialize(document_id)
        materialized_hash = document_hash(materialized)
        request_hash = _manifest_hash(
            {
                "kind": "create_document",
                "projectId": project_id,
                "clientRequestId": client_request_id,
                "documentHash": materialized_hash,
            }
        )
        operation = self._queued_operation(
            operation_kind="create_document",
            project_id=project_id,
            resource_kind="document",
            resource_id=document_id,
            client_request_id=client_request_id,
            request_manifest_hash=request_hash,
        )
        created = await self._create_operation(operation)
        if not created.created:
            return await self._resolve_existing_create(created.operation)
        running, step = await self._start_operation(operation, "persist_initial_checkpoint")
        try:
            descriptor = await asyncio.to_thread(
                self._object_store.write_json,
                project_id,
                document_payload(materialized),
            )
            if descriptor.content_hash != materialized_hash:
                raise StructuredPrototypeServiceError(
                    "object_hash_mismatch",
                    "prototype object identity does not match the validated document",
                    operation_id=operation.id,
                )
            now = self._now()
            draft_id = _stable_id(operation.id, "draft")
            checkpoint_id = _stable_id(operation.id, "checkpoint", "0")
            document_record = PrototypeDocumentRecord(
                id=document_id,
                project_id=project_id,
                title=materialized.title,
                published_revision_no=None,
                active_draft_id=draft_id,
                created_at=now,
                updated_at=now,
            )
            draft = PrototypeDraftRecord(
                id=draft_id,
                document_id=document_id,
                base_revision_no=None,
                status="active",
                head_sequence_no=0,
                head_document_hash=materialized_hash,
                latest_checkpoint_id=checkpoint_id,
                publish_revision_no=None,
                created_at=now,
                updated_at=now,
                closed_at=None,
            )
            checkpoint = PrototypeCheckpointRecord(
                id=checkpoint_id,
                document_id=document_id,
                draft_id=draft_id,
                revision_id=None,
                checkpoint_kind="draft",
                checkpoint_sequence_no=0,
                document_object_hash=materialized_hash,
                document_schema_version=DOCUMENT_SCHEMA_VERSION,
                command_contract_version=COMMAND_CONTRACT_VERSION,
                document_hash=materialized_hash,
                created_by_operation_id=operation.id,
                created_at=now,
            )
            result_hash = _manifest_hash(
                {
                    "operationId": operation.id,
                    "documentId": document_id,
                    "draftId": draft_id,
                    "checkpointId": checkpoint_id,
                    "documentHash": materialized_hash,
                }
            )
            completed, completed_step, event = self._succeed_operation(
                running,
                step,
                result_hash=result_hash,
                evidence_kind="checkpoint",
                evidence_ref=checkpoint_id,
            )
            reference = PrototypeObjectReference(
                project_id=project_id,
                owner_kind="checkpoint",
                owner_id=checkpoint_id,
                role="draft-checkpoint",
                content_hash=materialized_hash,
                payload_type="prototype_document",
                schema_version=DOCUMENT_SCHEMA_VERSION,
                created_at=now,
            )
            await self._store.create_document_with_initial_checkpoint(
                descriptor=descriptor,
                reference=reference,
                document=document_record,
                draft=draft,
                checkpoint=checkpoint,
                completed_operation=completed,
                completion_step=completed_step,
                completion_event=event,
            )
        except PrototypeObjectStoreError as exc:
            await self._fail_operation(running, step, exc.code)
            raise self._service_error(exc.code, str(exc), operation.id) from exc
        except StructuredPrototypeStoreError as exc:
            await self._fail_operation(running, step, exc.code)
            raise self._service_error(exc.code, str(exc), operation.id) from exc
        except StructuredPrototypeServiceError as exc:
            await self._fail_operation(running, step, exc.code)
            raise
        state = ActivePrototypeState(
            document_record=document_record,
            draft=draft,
            document=materialized,
            loaded_checkpoint_id=checkpoint_id,
            loaded_checkpoint_sequence_no=0,
            applied_tail_batch_ids=(),
        )
        return CreateStructuredPrototypeResult(
            operation_id=operation.id,
            correlation_id=operation.correlation_id,
            state=state,
        )

    async def recover_current_project_draft(
        self,
        *,
        project_id: str,
        client_request_id: str,
    ) -> RecoverStructuredPrototypeResult | None:
        _require_client_request_id(client_request_id)
        document = await self._store.load_current_project_document(project_id)
        if document is None:
            return None
        if document.active_draft_id is None:
            raise StructuredPrototypeServiceError(
                "active_draft_missing",
                "current prototype document has no active draft",
            )
        return await self.recover_draft(
            draft_id=document.active_draft_id,
            client_request_id=client_request_id,
        )

    async def recover_draft(
        self,
        *,
        draft_id: str,
        client_request_id: str,
    ) -> RecoverStructuredPrototypeResult:
        _require_client_request_id(client_request_id)
        draft = await self._store.load_draft(draft_id)
        if draft is None:
            raise StructuredPrototypeServiceError("draft_missing", "prototype draft does not exist")
        document_record = await self._store.load_document(draft.document_id)
        if document_record is None:
            raise StructuredPrototypeServiceError(
                "document_missing", "prototype document does not exist"
            )
        if draft.status == "corrupt":
            raise StructuredPrototypeServiceError(
                "draft_corrupt",
                "prototype draft is marked corrupt and cannot be recovered for editing",
                current_head_sequence_no=draft.head_sequence_no,
                current_document_hash=draft.head_document_hash,
            )
        request_hash = _manifest_hash(
            {
                "kind": "recover_draft",
                "draftId": draft.id,
                "headSequenceNo": draft.head_sequence_no,
                "documentHash": draft.head_document_hash,
            }
        )
        operation = self._queued_operation(
            operation_kind="recover_draft",
            project_id=document_record.project_id,
            resource_kind="draft",
            resource_id=draft.id,
            client_request_id=client_request_id,
            request_manifest_hash=request_hash,
        )
        created = await self._create_operation(operation)
        if not created.created:
            if created.operation.status == "succeeded":
                try:
                    state = await self._replay_draft(draft.id)
                except (
                    PrototypeObjectStoreError,
                    StructuredPrototypeContractError,
                    StructuredPrototypeStoreError,
                ):
                    return await self.recover_draft(
                        draft_id=draft.id,
                        client_request_id=_stable_id(
                            created.operation.id,
                            str(draft.head_sequence_no),
                            draft.head_document_hash,
                            "integrity-recheck",
                        ),
                    )
                return RecoverStructuredPrototypeResult(
                    operation_id=created.operation.id,
                    correlation_id=created.operation.correlation_id,
                    state=state,
                )
            raise self._existing_operation_error(created.operation)
        running, step = await self._start_operation(operation, "replay_command_tail")
        try:
            state = await self._replay_draft(draft.id)
            latest = await self._store.load_draft(draft.id)
            if latest is None:
                raise StructuredPrototypeServiceError(
                    "draft_missing", "prototype draft disappeared during recovery"
                )
            if (
                latest.head_sequence_no != state.draft.head_sequence_no
                or latest.head_document_hash != state.draft.head_document_hash
            ):
                raise StructuredPrototypeServiceError(
                    "draft_conflict",
                    "prototype draft head changed during recovery",
                    operation_id=operation.id,
                    current_head_sequence_no=latest.head_sequence_no,
                    current_document_hash=latest.head_document_hash,
                )
            result_hash = _manifest_hash(
                {
                    "operationId": operation.id,
                    "draftId": state.draft.id,
                    "headSequenceNo": state.draft.head_sequence_no,
                    "documentHash": state.draft.head_document_hash,
                    "checkpointId": state.loaded_checkpoint_id,
                    "tailBatchIds": list(state.applied_tail_batch_ids),
                }
            )
            completed, completed_step, event = self._succeed_operation(
                running,
                step,
                result_hash=result_hash,
                evidence_kind="replay_document_hash",
                evidence_ref=state.draft.head_document_hash,
            )
            await self._store.record_operation_transition(completed, completed_step, event)
            return RecoverStructuredPrototypeResult(
                operation_id=operation.id,
                correlation_id=operation.correlation_id,
                state=state,
            )
        except (
            PrototypeObjectStoreError,
            StructuredPrototypeContractError,
            StructuredPrototypeStoreError,
        ) as exc:
            await self._handle_recovery_failure(running, step, draft, exc.code)
            raise self._service_error(
                exc.code,
                str(exc),
                operation.id,
                draft,
            ) from exc
        except StructuredPrototypeServiceError as exc:
            await self._handle_recovery_failure(running, step, draft, exc.code)
            raise

    async def apply_command_batch(
        self,
        *,
        draft_id: str,
        client_request_id: str,
        expected_head_sequence_no: int,
        expected_document_hash: str,
        batch: DomainCommandBatchV1,
        origin: Literal["user", "ai", "system"] = "user",
    ) -> ApplyStructuredPrototypeCommandsResult:
        _require_client_request_id(client_request_id)
        current_draft = await self._store.load_draft(draft_id)
        if current_draft is None:
            raise StructuredPrototypeServiceError("draft_missing", "prototype draft does not exist")
        recovery_request_id = _stable_id(
            client_request_id,
            draft_id,
            str(current_draft.head_sequence_no),
            current_draft.head_document_hash,
            "pre-apply-recovery",
        )
        recovered = await self.recover_draft(
            draft_id=draft_id,
            client_request_id=recovery_request_id,
        )
        state = recovered.state
        request_hash = _manifest_hash(
            {
                "kind": "apply_command_batch",
                "draftId": draft_id,
                "clientRequestId": client_request_id,
                "expectedHeadSequenceNo": expected_head_sequence_no,
                "expectedDocumentHash": expected_document_hash,
                "commandBatchHash": command_batch_hash(batch),
                "origin": origin,
            }
        )
        operation = self._queued_operation(
            operation_kind="apply_command_batch",
            project_id=state.document_record.project_id,
            resource_kind="draft",
            resource_id=draft_id,
            client_request_id=client_request_id,
            request_manifest_hash=request_hash,
        )
        created = await self._create_operation(operation)
        if not created.created:
            return await self._resolve_existing_apply(created.operation, state)
        running, step = await self._start_operation(operation, "commit_command_batch")
        if (
            state.draft.head_sequence_no != expected_head_sequence_no
            or state.draft.head_document_hash != expected_document_hash
        ):
            await self._fail_operation(running, step, "draft_conflict")
            raise StructuredPrototypeServiceError(
                "draft_conflict",
                "prototype command base does not match the current draft head",
                operation_id=operation.id,
                current_head_sequence_no=state.draft.head_sequence_no,
                current_document_hash=state.draft.head_document_hash,
            )
        try:
            execution = execute_command_batch(
                state.document,
                batch,
                draft_id=draft_id,
                client_request_id=client_request_id,
            )
            now = self._now()
            batch_id = _stable_id(operation.id, "command-batch")
            batch_record = PrototypeCommandBatchRecord(
                id=batch_id,
                draft_id=draft_id,
                base_sequence_no=expected_head_sequence_no,
                result_sequence_no=expected_head_sequence_no + 1,
                client_request_id=client_request_id,
                origin=origin,
                operation_kind="forward",
                target_batch_id=None,
                command_contract_version=COMMAND_CONTRACT_VERSION,
                commands_json=canonical_model_json(batch),
                inverse_commands_json=canonical_model_json(execution.inverse_commands),
                command_batch_hash=command_batch_hash(batch),
                base_document_hash=execution.base_document_hash,
                result_document_hash=execution.result_document_hash,
                operation_id=operation.id,
                created_at=now,
            )
            result_hash = _manifest_hash(
                {
                    "operationId": operation.id,
                    "batchId": batch_id,
                    "resultSequenceNo": batch_record.result_sequence_no,
                    "resultDocumentHash": batch_record.result_document_hash,
                    "allocatedEntityIds": [
                        {"newNodeKey": key, "entityId": entity_id}
                        for key, entity_id in execution.allocated_entity_ids
                    ],
                    "affectedEntityIds": list(execution.affected_entity_ids),
                }
            )
            completed, completed_step, event = self._succeed_operation(
                running,
                step,
                result_hash=result_hash,
                evidence_kind="command_batch",
                evidence_ref=batch_id,
            )
            appended = await self._store.append_command_batch(
                batch=batch_record,
                completed_operation=completed,
                completion_step=completed_step,
                completion_event=event,
            )
        except StructuredPrototypeContractError as exc:
            await self._fail_operation(running, step, exc.code)
            raise self._service_error(exc.code, str(exc), operation.id, state.draft) from exc
        except StructuredPrototypeStoreError as exc:
            await self._fail_operation(running, step, exc.code)
            current = await self._store.load_draft(draft_id)
            raise self._service_error(
                exc.code,
                str(exc),
                operation.id,
                current or state.draft,
            ) from exc
        updated_state = ActivePrototypeState(
            document_record=state.document_record,
            draft=appended.draft,
            document=execution.document,
            loaded_checkpoint_id=state.loaded_checkpoint_id,
            loaded_checkpoint_sequence_no=state.loaded_checkpoint_sequence_no,
            applied_tail_batch_ids=(*state.applied_tail_batch_ids, appended.batch.id),
        )
        return ApplyStructuredPrototypeCommandsResult(
            operation_id=operation.id,
            correlation_id=operation.correlation_id,
            applied_batch_id=appended.batch.id,
            allocated_entity_ids=execution.allocated_entity_ids,
            affected_entity_ids=execution.affected_entity_ids,
            state=updated_state,
        )

    async def checkpoint_draft(
        self,
        *,
        draft_id: str,
        client_request_id: str,
    ) -> CheckpointStructuredPrototypeResult:
        _require_client_request_id(client_request_id)
        current_draft = await self._store.load_draft(draft_id)
        if current_draft is None:
            raise StructuredPrototypeServiceError("draft_missing", "prototype draft does not exist")
        recovered = await self.recover_draft(
            draft_id=draft_id,
            client_request_id=_stable_id(
                client_request_id,
                draft_id,
                str(current_draft.head_sequence_no),
                current_draft.head_document_hash,
                "pre-checkpoint-recovery",
            ),
        )
        state = recovered.state
        request_hash = _manifest_hash(
            {
                "kind": "create_checkpoint",
                "draftId": draft_id,
                "headSequenceNo": state.draft.head_sequence_no,
                "documentHash": state.draft.head_document_hash,
            }
        )
        operation = self._queued_operation(
            operation_kind="create_checkpoint",
            project_id=state.document_record.project_id,
            resource_kind="draft",
            resource_id=draft_id,
            client_request_id=client_request_id,
            request_manifest_hash=request_hash,
        )
        created = await self._create_operation(operation)
        if not created.created:
            if created.operation.status != "succeeded":
                raise self._existing_operation_error(created.operation)
            if state.loaded_checkpoint_sequence_no != state.draft.head_sequence_no:
                raise StructuredPrototypeServiceError(
                    "operation_result_missing",
                    "prototype checkpoint operation result is not the current draft head",
                    operation_id=created.operation.id,
                )
            return CheckpointStructuredPrototypeResult(
                operation_id=created.operation.id,
                correlation_id=created.operation.correlation_id,
                checkpoint_id=state.loaded_checkpoint_id,
                state=state,
            )
        running, step = await self._start_operation(operation, "persist_draft_checkpoint")
        if state.loaded_checkpoint_sequence_no == state.draft.head_sequence_no:
            result_hash = _manifest_hash(
                {
                    "operationId": operation.id,
                    "checkpointId": state.loaded_checkpoint_id,
                    "documentHash": state.draft.head_document_hash,
                }
            )
            completed, completed_step, event = self._succeed_operation(
                running,
                step,
                result_hash=result_hash,
                evidence_kind="checkpoint",
                evidence_ref=state.loaded_checkpoint_id,
            )
            try:
                await self._store.record_operation_transition(completed, completed_step, event)
            except StructuredPrototypeStoreError as exc:
                await self._fail_operation(running, step, exc.code)
                raise self._service_error(exc.code, str(exc), operation.id, state.draft) from exc
            return CheckpointStructuredPrototypeResult(
                operation_id=operation.id,
                correlation_id=operation.correlation_id,
                checkpoint_id=state.loaded_checkpoint_id,
                state=state,
            )
        try:
            descriptor = await asyncio.to_thread(
                self._object_store.write_json,
                state.document_record.project_id,
                document_payload(state.document),
            )
            if descriptor.content_hash != state.draft.head_document_hash:
                raise StructuredPrototypeServiceError(
                    "object_hash_mismatch",
                    "prototype checkpoint object does not match the draft head",
                    operation_id=operation.id,
                )
            now = self._now()
            checkpoint_id = _stable_id(operation.id, "checkpoint")
            checkpoint = PrototypeCheckpointRecord(
                id=checkpoint_id,
                document_id=state.document_record.id,
                draft_id=draft_id,
                revision_id=None,
                checkpoint_kind="draft",
                checkpoint_sequence_no=state.draft.head_sequence_no,
                document_object_hash=descriptor.content_hash,
                document_schema_version=DOCUMENT_SCHEMA_VERSION,
                command_contract_version=COMMAND_CONTRACT_VERSION,
                document_hash=descriptor.content_hash,
                created_by_operation_id=operation.id,
                created_at=now,
            )
            reference = PrototypeObjectReference(
                project_id=state.document_record.project_id,
                owner_kind="checkpoint",
                owner_id=checkpoint_id,
                role="draft-checkpoint",
                content_hash=descriptor.content_hash,
                payload_type="prototype_document",
                schema_version=DOCUMENT_SCHEMA_VERSION,
                created_at=now,
            )
            result_hash = _manifest_hash(
                {
                    "operationId": operation.id,
                    "checkpointId": checkpoint_id,
                    "checkpointSequenceNo": checkpoint.checkpoint_sequence_no,
                    "documentHash": checkpoint.document_hash,
                }
            )
            completed, completed_step, event = self._succeed_operation(
                running,
                step,
                result_hash=result_hash,
                evidence_kind="checkpoint",
                evidence_ref=checkpoint_id,
            )
            updated_draft = await self._store.register_draft_checkpoint(
                descriptor=descriptor,
                reference=reference,
                checkpoint=checkpoint,
                completed_operation=completed,
                completion_step=completed_step,
                completion_event=event,
            )
        except PrototypeObjectStoreError as exc:
            await self._fail_operation(running, step, exc.code)
            raise self._service_error(exc.code, str(exc), operation.id, state.draft) from exc
        except StructuredPrototypeStoreError as exc:
            await self._fail_operation(running, step, exc.code)
            current = await self._store.load_draft(draft_id)
            raise self._service_error(
                exc.code,
                str(exc),
                operation.id,
                current or state.draft,
            ) from exc
        except StructuredPrototypeServiceError as exc:
            await self._fail_operation(running, step, exc.code)
            raise
        updated_state = ActivePrototypeState(
            document_record=state.document_record,
            draft=updated_draft,
            document=state.document,
            loaded_checkpoint_id=checkpoint_id,
            loaded_checkpoint_sequence_no=updated_draft.head_sequence_no,
            applied_tail_batch_ids=(),
        )
        return CheckpointStructuredPrototypeResult(
            operation_id=operation.id,
            correlation_id=operation.correlation_id,
            checkpoint_id=checkpoint_id,
            state=updated_state,
        )

    async def publish_draft(
        self,
        *,
        draft_id: str,
        client_request_id: str,
        expected_head_sequence_no: int,
        expected_document_hash: str,
    ) -> PublishStructuredPrototypeResult:
        _require_client_request_id(client_request_id)
        draft = await self._store.load_draft(draft_id)
        if draft is None:
            raise StructuredPrototypeServiceError("draft_missing", "prototype draft does not exist")
        document_record = await self._store.load_document(draft.document_id)
        if document_record is None:
            raise StructuredPrototypeServiceError(
                "document_missing", "prototype document does not exist"
            )
        renderer = self._renderer_worker
        request_hash = _manifest_hash(
            {
                "kind": "publish",
                "draftId": draft_id,
                "clientRequestId": client_request_id,
                "expectedHeadSequenceNo": expected_head_sequence_no,
                "expectedDocumentHash": expected_document_hash,
            }
        )
        operation = self._queued_operation(
            operation_kind="publish",
            project_id=document_record.project_id,
            resource_kind="draft",
            resource_id=draft_id,
            client_request_id=client_request_id,
            request_manifest_hash=request_hash,
            config_manifest_hash=self._renderer_config_manifest_hash(
                renderer.identity if renderer is not None else None
            ),
        )
        created = await self._create_operation(operation)
        if not created.created:
            return await self._resolve_existing_publish(created.operation)
        running, freeze_step = await self._start_operation(operation, "freeze_publication")
        if (
            draft.status != "active"
            or draft.head_sequence_no != expected_head_sequence_no
            or draft.head_document_hash != expected_document_hash
        ):
            await self._fail_operation(running, freeze_step, "draft_conflict")
            raise StructuredPrototypeServiceError(
                "draft_conflict",
                "prototype publication base does not match the current active draft",
                operation_id=operation.id,
                current_head_sequence_no=draft.head_sequence_no,
                current_document_hash=draft.head_document_hash,
            )
        try:
            renderer, artifact_store = self._require_publication_dependencies()
            self._assert_renderer_runtime_compatibility(renderer.identity)
            checkpointed = await self.checkpoint_draft(
                draft_id=draft_id,
                client_request_id=_stable_id(
                    client_request_id,
                    draft_id,
                    str(expected_head_sequence_no),
                    expected_document_hash,
                    "publication-checkpoint",
                ),
            )
            state = checkpointed.state
            if (
                state.loaded_checkpoint_sequence_no != state.draft.head_sequence_no
                or state.draft.head_sequence_no != expected_head_sequence_no
                or state.draft.head_document_hash != expected_document_hash
            ):
                raise StructuredPrototypeServiceError(
                    "publication_checkpoint_mismatch",
                    "prototype publication checkpoint does not match the requested draft head",
                    operation_id=operation.id,
                )
            recovery_bundle = await self._store.load_draft_recovery_bundle(draft_id)
            if recovery_bundle.checkpoint.id != state.loaded_checkpoint_id:
                raise StructuredPrototypeServiceError(
                    "publication_checkpoint_mismatch",
                    "prototype publication checkpoint changed before freeze",
                    operation_id=operation.id,
                )
            revision_no = await self._store.next_revision_no(document_record.id)
            now = self._now()
            revision_id = _stable_id(operation.id, "revision")
            revision_checkpoint_id = _stable_id(operation.id, "revision-checkpoint")
            render_run_id = _stable_id(operation.id, "render-run")
            artifact_id = _stable_id(operation.id, "render-artifact")
            input_manifest = self._renderer_input_manifest(
                renderer.identity,
                document_object_hash=expected_document_hash,
                output_locale=state.document.locale,
                asset_object_hashes=[asset.content_hash for asset in state.document.asset_refs],
            )
            input_descriptor = await asyncio.to_thread(
                self._object_store.write_json,
                document_record.project_id,
                input_manifest,
            )
            revision_checkpoint = PrototypeCheckpointRecord(
                id=revision_checkpoint_id,
                document_id=document_record.id,
                draft_id=None,
                revision_id=revision_id,
                checkpoint_kind="revision",
                checkpoint_sequence_no=expected_head_sequence_no,
                document_object_hash=expected_document_hash,
                document_schema_version=DOCUMENT_SCHEMA_VERSION,
                command_contract_version=COMMAND_CONTRACT_VERSION,
                document_hash=expected_document_hash,
                created_by_operation_id=operation.id,
                created_at=now,
            )
            revision = PrototypeRevisionRecord(
                id=revision_id,
                document_id=document_record.id,
                revision_no=revision_no,
                schema_version=DOCUMENT_SCHEMA_VERSION,
                checkpoint_id=revision_checkpoint_id,
                document_object_hash=expected_document_hash,
                document_hash=expected_document_hash,
                summary=f"Publish draft sequence {expected_head_sequence_no}",
                source="user",
                created_at=now,
            )
            identity = renderer.identity
            render_run = PrototypeRenderRunRecord(
                id=render_run_id,
                document_id=document_record.id,
                kind="publication",
                revision_id=revision_id,
                ai_edit_run_id=None,
                status="queued",
                renderer_version=identity.renderer_version,
                renderer_environment_version=identity.renderer_environment_version,
                runtime_core_version=identity.runtime_core_version,
                runtime_core_source_hash=identity.runtime_core_source_hash,
                runtime_core_bundle_hash=identity.runtime_core_bundle_hash,
                state_machine_kernel_version=identity.state_machine_kernel_version,
                render_runtime_image_hash=identity.render_runtime_image_hash,
                browser_version=identity.browser_version,
                font_pack_hash=identity.font_pack_hash,
                viewport_profile_hash=identity.viewport_profile_hash,
                sandbox_policy_version=identity.sandbox_policy_version,
                input_manifest_hash=input_descriptor.content_hash,
                document_object_hash=expected_document_hash,
                document_hash=expected_document_hash,
                operation_id=operation.id,
                attempt=1,
                artifact_id=None,
                output_manifest_hash=None,
                error_code=None,
                error_message=None,
                started_at=None,
                completed_at=None,
                created_at=now,
                updated_at=now,
            )
            freeze_hash = _manifest_hash(
                {
                    "operationId": operation.id,
                    "revisionId": revision_id,
                    "revisionNo": revision_no,
                    "revisionCheckpointId": revision_checkpoint_id,
                    "renderRunId": render_run_id,
                    "inputManifestHash": input_descriptor.content_hash,
                    "documentHash": expected_document_hash,
                }
            )
            frozen_operation, completed_freeze_step, freeze_event = (
                self._complete_nonterminal_step(
                    running,
                    freeze_step,
                    output_hash=freeze_hash,
                    evidence_kind="publication_revision",
                    evidence_ref=revision_id,
                    event_no=2,
                )
            )
            frozen = await self._store.freeze_publication(
                document_descriptor=recovery_bundle.object_descriptor,
                revision_reference=PrototypeObjectReference(
                    project_id=document_record.project_id,
                    owner_kind="checkpoint",
                    owner_id=revision_checkpoint_id,
                    role="revision-document",
                    content_hash=expected_document_hash,
                    payload_type="prototype_document",
                    schema_version=DOCUMENT_SCHEMA_VERSION,
                    created_at=now,
                ),
                input_descriptor=input_descriptor,
                input_reference=PrototypeObjectReference(
                    project_id=document_record.project_id,
                    owner_kind="render_run",
                    owner_id=render_run_id,
                    role="renderer-input-manifest",
                    content_hash=input_descriptor.content_hash,
                    payload_type="renderer_input_manifest",
                    schema_version=1,
                    created_at=now,
                ),
                revision=revision,
                revision_checkpoint=revision_checkpoint,
                render_run=render_run,
                expected_draft_id=draft_id,
                expected_head_sequence_no=expected_head_sequence_no,
                expected_document_hash=expected_document_hash,
                running_operation=frozen_operation,
                completed_step=completed_freeze_step,
                completion_event=freeze_event,
            )
        except (
            PrototypeObjectStoreError,
            PrototypeRendererWorkerError,
            PrototypeRenderArtifactStoreError,
            StructuredPrototypeContractError,
            StructuredPrototypeStoreError,
        ) as exc:
            await self._fail_operation(running, freeze_step, exc.code)
            raise self._service_error(exc.code, str(exc), operation.id, draft) from exc
        except StructuredPrototypeServiceError as exc:
            await self._fail_operation(running, freeze_step, exc.code)
            raise

        render_operation, render_step, render_started = await self._start_followup_step(
            frozen_operation,
            step_kind="render_publication",
            step_ordinal=1,
            event_no=3,
            input_manifest_hash=input_descriptor.content_hash,
        )
        try:
            await self._store.mark_publication_rendering(
                render_run_id=frozen.render_run.id,
                started_at=self._now(),
                running_operation=render_operation,
                running_step=render_step,
                started_event=render_started,
            )
        except StructuredPrototypeStoreError as exc:
            await self._fail_frozen_publication(
                frozen=frozen,
                operation=render_operation,
                step=render_step,
                event_no=3,
                error_code=exc.code,
                error_message=str(exc),
            )
            raise self._service_error(exc.code, str(exc), operation.id, frozen.draft) from exc

        try:
            render_result = await renderer.render(
                request_id=operation.id,
                artifact_id=artifact_id,
                input_manifest=input_manifest,
                document=document_payload(state.document),
            )
            if render_result.input_manifest_hash != input_descriptor.content_hash:
                raise StructuredPrototypeServiceError(
                    "renderer_input_manifest_mismatch",
                    "prototype renderer did not use the frozen input manifest",
                    operation_id=operation.id,
                )
            bundle_descriptor = await asyncio.to_thread(
                artifact_store.write_bundle,
                project_id=document_record.project_id,
                document_id=document_record.id,
                artifact_id=artifact_id,
                result=render_result,
            )
            output_descriptor = await asyncio.to_thread(
                self._object_store.write_json,
                document_record.project_id,
                render_result.output_manifest,
            )
            preflight_descriptor = await asyncio.to_thread(
                self._object_store.write_json,
                document_record.project_id,
                render_result.visual_preflight_report,
            )
            if (
                output_descriptor.content_hash != render_result.output_manifest_hash
                or preflight_descriptor.content_hash
                != render_result.visual_preflight_report_hash
                or bundle_descriptor.output_hash != render_result.bundle_hash
            ):
                raise StructuredPrototypeServiceError(
                    "renderer_evidence_mismatch",
                    "prototype renderer evidence does not match persisted output",
                    operation_id=operation.id,
                )
            render_completed_operation, completed_render_step, render_completed_event = (
                self._complete_nonterminal_step(
                    render_operation,
                    render_step,
                    output_hash=render_result.output_manifest_hash,
                    evidence_kind="renderer_output_manifest",
                    evidence_ref=render_result.output_manifest_hash,
                    event_no=4,
                )
            )
            await self._store.record_operation_transition(
                render_completed_operation,
                completed_render_step,
                render_completed_event,
            )
        except (
            PrototypeObjectStoreError,
            PrototypeRendererWorkerError,
            PrototypeRenderArtifactStoreError,
            StructuredPrototypeStoreError,
        ) as exc:
            await self._fail_frozen_publication(
                frozen=frozen,
                operation=render_operation,
                step=render_step,
                event_no=4,
                error_code=exc.code,
                error_message=str(exc),
            )
            raise self._service_error(exc.code, str(exc), operation.id, frozen.draft) from exc
        except StructuredPrototypeServiceError as exc:
            await self._fail_frozen_publication(
                frozen=frozen,
                operation=render_operation,
                step=render_step,
                event_no=4,
                error_code=exc.code,
                error_message=str(exc),
            )
            raise

        complete_operation, complete_step, complete_started = await self._start_followup_step(
            render_completed_operation,
            step_kind="complete_publication",
            step_ordinal=2,
            event_no=5,
            input_manifest_hash=render_result.output_manifest_hash,
        )
        try:
            await self._store.record_operation_transition(
                complete_operation,
                complete_step,
                complete_started,
            )
        except StructuredPrototypeStoreError as exc:
            await self._fail_frozen_publication(
                frozen=frozen,
                operation=complete_operation,
                step=complete_step,
                event_no=5,
                error_code=exc.code,
                error_message=str(exc),
            )
            raise self._service_error(exc.code, str(exc), operation.id, frozen.draft) from exc

        try:
            completed_at = self._now()
            active_draft_id = _stable_id(frozen.revision.id, "active-draft")
            active_checkpoint_id = _stable_id(frozen.revision.id, "active-checkpoint")
            replay_manifest = {
                "contractVersion": 1,
                "operationId": operation.id,
                "operationKind": "publish",
                "parentOperationId": None,
                "requestManifestHash": operation.request_manifest_hash,
                "contextManifestHash": input_descriptor.content_hash,
                "orderedInputObjectHashes": [expected_document_hash, input_descriptor.content_hash],
                "versions": {
                    "documentSchemaVersion": DOCUMENT_SCHEMA_VERSION,
                    "commandContractVersion": COMMAND_CONTRACT_VERSION,
                    "rendererVersion": renderer.identity.renderer_version,
                    "rendererEnvironmentVersion": renderer.identity.renderer_environment_version,
                    "runtimeCoreVersion": renderer.identity.runtime_core_version,
                    "runtimeCoreSourceHash": renderer.identity.runtime_core_source_hash,
                    "runtimeCoreBundleHash": renderer.identity.runtime_core_bundle_hash,
                    "stateMachineKernelVersion": renderer.identity.state_machine_kernel_version,
                    "sandboxPolicyVersion": renderer.identity.sandbox_policy_version,
                },
                "baseCheckpointHash": expected_document_hash,
                "baseSequenceNo": expected_head_sequence_no,
                "resultCheckpointHash": expected_document_hash,
                "resultSequenceNo": 0,
                "rendererInputHash": input_descriptor.content_hash,
                "rendererOutputHash": render_result.bundle_hash,
                "validationReportHashes": [render_result.visual_preflight_report_hash],
                "terminalStatus": "succeeded",
                "errorCode": None,
            }
            replay_descriptor = await asyncio.to_thread(
                self._object_store.write_json,
                document_record.project_id,
                replay_manifest,
            )
            active_draft = PrototypeDraftRecord(
                id=active_draft_id,
                document_id=document_record.id,
                base_revision_no=frozen.revision.revision_no,
                status="active",
                head_sequence_no=0,
                head_document_hash=expected_document_hash,
                latest_checkpoint_id=None,
                publish_revision_no=None,
                created_at=completed_at,
                updated_at=completed_at,
                closed_at=None,
            )
            active_checkpoint = PrototypeCheckpointRecord(
                id=active_checkpoint_id,
                document_id=document_record.id,
                draft_id=active_draft_id,
                revision_id=None,
                checkpoint_kind="draft",
                checkpoint_sequence_no=0,
                document_object_hash=expected_document_hash,
                document_schema_version=DOCUMENT_SCHEMA_VERSION,
                command_contract_version=COMMAND_CONTRACT_VERSION,
                document_hash=expected_document_hash,
                created_by_operation_id=operation.id,
                created_at=completed_at,
            )
            artifact = PrototypeRenderArtifactRecord(
                id=artifact_id,
                render_run_id=frozen.render_run.id,
                document_id=document_record.id,
                revision_id=frozen.revision.id,
                renderer_version=renderer.identity.renderer_version,
                document_hash=expected_document_hash,
                output_hash=render_result.bundle_hash,
                output_manifest_hash=render_result.output_manifest_hash,
                storage_key=bundle_descriptor.storage_key,
                entrypoint=bundle_descriptor.entrypoint,
                visual_preflight_report_hash=render_result.visual_preflight_report_hash,
                created_at=completed_at,
            )
            successful_operation, completed_step, completion_event = self._succeed_operation_at(
                complete_operation,
                complete_step,
                result_hash=replay_descriptor.content_hash,
                evidence_kind="published_artifact",
                evidence_ref=artifact.id,
                event_no=6,
            )
            completed = await self._store.complete_publication(
                artifact=artifact,
                output_descriptor=output_descriptor,
                output_reference=PrototypeObjectReference(
                    project_id=document_record.project_id,
                    owner_kind="render_run",
                    owner_id=frozen.render_run.id,
                    role="renderer-output-manifest",
                    content_hash=output_descriptor.content_hash,
                    payload_type="renderer_output_manifest",
                    schema_version=1,
                    created_at=completed_at,
                ),
                preflight_descriptor=preflight_descriptor,
                preflight_reference=PrototypeObjectReference(
                    project_id=document_record.project_id,
                    owner_kind="render_run",
                    owner_id=frozen.render_run.id,
                    role="visual-preflight-report",
                    content_hash=preflight_descriptor.content_hash,
                    payload_type="visual_preflight_report",
                    schema_version=1,
                    created_at=completed_at,
                ),
                replay_descriptor=replay_descriptor,
                replay_reference=PrototypeObjectReference(
                    project_id=document_record.project_id,
                    owner_kind="replay_manifest",
                    owner_id=operation.id,
                    role="publish-replay-manifest",
                    content_hash=replay_descriptor.content_hash,
                    payload_type="replay_manifest",
                    schema_version=1,
                    created_at=completed_at,
                ),
                publishing_draft_id=draft_id,
                active_draft=active_draft,
                active_checkpoint=active_checkpoint,
                active_checkpoint_reference=PrototypeObjectReference(
                    project_id=document_record.project_id,
                    owner_kind="checkpoint",
                    owner_id=active_checkpoint_id,
                    role="published-base-document",
                    content_hash=expected_document_hash,
                    payload_type="prototype_document",
                    schema_version=DOCUMENT_SCHEMA_VERSION,
                    created_at=completed_at,
                ),
                completed_operation=successful_operation,
                completed_step=completed_step,
                completion_event=completion_event,
            )
        except (PrototypeObjectStoreError, StructuredPrototypeStoreError) as exc:
            await self._fail_frozen_publication(
                frozen=frozen,
                operation=complete_operation,
                step=complete_step,
                event_no=6,
                error_code=exc.code,
                error_message=str(exc),
            )
            raise self._service_error(exc.code, str(exc), operation.id, frozen.draft) from exc

        active_state = ActivePrototypeState(
            document_record=completed.document,
            draft=completed.active_draft,
            document=state.document,
            loaded_checkpoint_id=completed.active_checkpoint.id,
            loaded_checkpoint_sequence_no=0,
            applied_tail_batch_ids=(),
        )
        return PublishStructuredPrototypeResult(
            operation_id=operation.id,
            correlation_id=operation.correlation_id,
            publication=self._published_snapshot(
                completed.document,
                completed.revision,
                replace(
                    frozen.render_run,
                    status="ready",
                    artifact_id=completed.artifact.id,
                    output_manifest_hash=completed.artifact.output_manifest_hash,
                    started_at=render_started.occurred_at,
                    completed_at=completed.artifact.created_at,
                    updated_at=completed.artifact.created_at,
                ),
                completed.artifact,
            ),
            state=active_state,
        )

    async def get_published_prototype(
        self,
        document_id: str,
    ) -> PublishedPrototypeSnapshot | None:
        try:
            record = await self._store.load_published_record(document_id)
        except StructuredPrototypeStoreError as exc:
            raise self._service_error(exc.code, str(exc), None) from exc
        if record is None:
            return None
        return self._published_snapshot(
            record.document,
            record.revision,
            record.render_run,
            record.artifact,
        )

    async def read_published_file(
        self,
        *,
        document_id: str,
        revision_no: int,
        artifact_id: str,
        relative_path: str,
    ) -> PublishedPrototypeFile:
        artifact_store = self._artifact_store
        if artifact_store is None:
            raise StructuredPrototypeServiceError(
                "render_artifact_store_unavailable",
                "prototype render artifact store is unavailable",
            )
        try:
            record = await self._store.load_ready_publication(
                document_id,
                revision_no,
                artifact_id,
            )
            if record is None:
                raise StructuredPrototypeServiceError(
                    "published_artifact_missing",
                    "published prototype artifact does not exist",
                )
            descriptor = PrototypeRenderBundleDescriptor(
                project_id=record.document.project_id,
                document_id=record.document.id,
                artifact_id=record.artifact.id,
                storage_key=record.artifact.storage_key,
                entrypoint=record.artifact.entrypoint,
                output_hash=record.artifact.output_hash,
                output_manifest_hash=record.artifact.output_manifest_hash,
                visual_preflight_report_hash=record.artifact.visual_preflight_report_hash,
                file_count=4,
            )
            content = await asyncio.to_thread(
                artifact_store.read_file,
                descriptor,
                relative_path,
            )
        except PrototypeRenderArtifactStoreError as exc:
            raise self._service_error(exc.code, str(exc), None) from exc
        return PublishedPrototypeFile(
            publication=self._published_snapshot(
                record.document,
                record.revision,
                record.render_run,
                record.artifact,
            ),
            relative_path=relative_path,
            content=content,
        )

    async def recover_interrupted_publications(self) -> int:
        try:
            return await self._store.recover_interrupted_publications(self._now())
        except StructuredPrototypeStoreError as exc:
            raise self._service_error(exc.code, str(exc), None) from exc

    async def create_runtime_session(
        self,
        *,
        draft_id: str,
        client_request_id: str,
        scenario_id: str,
        recording_kind: PrototypeRuntimeRecordingKind,
        actor_subject_id: str | None,
    ) -> CreatePrototypeRuntimeSessionResult:
        _require_client_request_id(client_request_id)
        worker = self._runtime_worker
        draft = await self._store.load_draft(draft_id)
        if draft is None:
            raise StructuredPrototypeServiceError("draft_missing", "prototype draft does not exist")
        document_record = await self._store.load_document(draft.document_id)
        if document_record is None:
            raise StructuredPrototypeServiceError(
                "document_missing", "prototype document does not exist"
            )
        session_id = _stable_id(document_record.project_id, client_request_id, "runtime-session")
        request_hash = _manifest_hash(
            {
                "kind": "create_runtime_session",
                "draftId": draft_id,
                "headSequenceNo": draft.head_sequence_no,
                "documentHash": draft.head_document_hash,
                "scenarioId": scenario_id,
                "recordingKind": recording_kind,
                "actorSubjectId": actor_subject_id,
            }
        )
        operation = self._queued_operation(
            operation_kind="create_runtime_session",
            project_id=document_record.project_id,
            resource_kind="runtime_session",
            resource_id=session_id,
            client_request_id=client_request_id,
            request_manifest_hash=request_hash,
            config_manifest_hash=self._runtime_config_manifest_hash(
                worker.identity if worker is not None else None
            ),
        )
        created = await self._create_operation(operation)
        if not created.created:
            if created.operation.status != "succeeded":
                raise self._existing_operation_error(created.operation)
            state = await self._replay_runtime_session(session_id)
            return CreatePrototypeRuntimeSessionResult(
                operation_id=created.operation.id,
                correlation_id=created.operation.correlation_id,
                state=state,
            )
        running, step = await self._start_operation(operation, "initialize_runtime_session")
        try:
            worker = self._require_runtime_worker()
            checkpointed = await self.checkpoint_draft(
                draft_id=draft_id,
                client_request_id=_stable_id(
                    client_request_id,
                    draft_id,
                    str(draft.head_sequence_no),
                    draft.head_document_hash,
                    "runtime-document-checkpoint",
                ),
            )
            document_state = checkpointed.state
            if (
                document_state.loaded_checkpoint_sequence_no
                != document_state.draft.head_sequence_no
            ):
                raise StructuredPrototypeServiceError(
                    "runtime_document_checkpoint_missing",
                    "prototype runtime session requires a document checkpoint at the draft head",
                    operation_id=operation.id,
                )
            document_bundle = await self._store.load_draft_recovery_bundle(draft_id)
            if document_bundle.checkpoint.id != document_state.loaded_checkpoint_id:
                raise StructuredPrototypeServiceError(
                    "runtime_document_checkpoint_mismatch",
                    "prototype runtime document checkpoint changed during initialization",
                    operation_id=operation.id,
                )
            scenario = next(
                (
                    candidate
                    for candidate in document_state.document.runtime.scenarios
                    if candidate.id == scenario_id
                ),
                None,
            )
            if scenario is None:
                raise StructuredPrototypeServiceError(
                    "runtime_scenario_missing",
                    "prototype runtime scenario does not exist",
                    operation_id=operation.id,
                )
            definition = self._runtime_definition_payload(document_state.document)
            initial = await worker.initialize_state(
                request_id=operation.id,
                definition=definition,
                scenario_id=scenario_id,
                session_id=session_id,
            )
            try:
                state_payload: object = json.loads(initial.state_json)
            except json.JSONDecodeError as exc:
                raise StructuredPrototypeServiceError(
                    "runtime_worker_response_invalid",
                    "prototype runtime worker returned invalid state JSON",
                    operation_id=operation.id,
                ) from exc
            state_descriptor = await asyncio.to_thread(
                self._object_store.write_json,
                document_record.project_id,
                state_payload,
            )
            if state_descriptor.content_hash != initial.state_hash:
                raise StructuredPrototypeServiceError(
                    "runtime_checkpoint_state_hash_mismatch",
                    "prototype runtime state object does not match the worker result",
                    operation_id=operation.id,
                )
            now = self._now()
            checkpoint_id = _stable_id(operation.id, "runtime-checkpoint", "0")
            session = PrototypeRuntimeSessionRecord(
                id=session_id,
                project_id=document_record.project_id,
                document_id=document_record.id,
                source_kind="draft",
                source_id=draft_id,
                pinned_document_object_hash=document_bundle.object_descriptor.content_hash,
                runtime_core_version=worker.identity.runtime_core_version,
                runtime_core_bundle_hash=worker.identity.runtime_core_bundle_hash,
                state_machine_kernel_version=worker.identity.state_machine_kernel_version,
                scenario_id=scenario_id,
                scenario_hash=_manifest_hash(scenario.model_dump(mode="json", by_alias=True)),
                status="active",
                head_sequence_no=0,
                head_state_hash=initial.state_hash,
                head_view_model_hash=initial.view_model_hash,
                latest_checkpoint_id=checkpoint_id,
                recording_kind=recording_kind,
                allow_simulated_role_switch=scenario.allow_simulated_role_switch,
                actor_subject_id=actor_subject_id,
                created_at=now,
                updated_at=now,
                completed_at=None,
            )
            runtime_checkpoint = PrototypeRuntimeCheckpointRecord(
                id=checkpoint_id,
                session_id=session_id,
                checkpoint_sequence_no=0,
                state_object_hash=initial.state_hash,
                runtime_state_schema_version=RUNTIME_STATE_SCHEMA_VERSION,
                runtime_event_contract_version=RUNTIME_EVENT_CONTRACT_VERSION,
                state_hash=initial.state_hash,
                view_model_hash=initial.view_model_hash,
                created_by_operation_id=operation.id,
                created_at=now,
            )
            result_hash = _manifest_hash(
                {
                    "operationId": operation.id,
                    "sessionId": session_id,
                    "runtimeCheckpointId": checkpoint_id,
                    "documentObjectHash": session.pinned_document_object_hash,
                    "stateHash": initial.state_hash,
                    "viewModelHash": initial.view_model_hash,
                    "runtimeCoreBundleHash": worker.identity.runtime_core_bundle_hash,
                }
            )
            completed, completed_step, event = self._succeed_operation(
                running,
                step,
                result_hash=result_hash,
                evidence_kind="runtime_checkpoint",
                evidence_ref=checkpoint_id,
            )
            reference = PrototypeObjectReference(
                project_id=document_record.project_id,
                owner_kind="runtime_checkpoint",
                owner_id=checkpoint_id,
                role="runtime-state-checkpoint",
                content_hash=initial.state_hash,
                payload_type="prototype_runtime_state",
                schema_version=RUNTIME_STATE_SCHEMA_VERSION,
                created_at=now,
            )
            await self._store.create_runtime_session_with_initial_checkpoint(
                descriptor=state_descriptor,
                reference=reference,
                session=session,
                checkpoint=runtime_checkpoint,
                completed_operation=completed,
                completion_step=completed_step,
                completion_event=event,
            )
        except PrototypeRuntimeWorkerError as exc:
            await self._fail_operation(running, step, exc.code)
            raise self._runtime_service_error(exc.code, str(exc), operation.id) from exc
        except PrototypeObjectStoreError as exc:
            await self._fail_operation(running, step, exc.code)
            raise self._runtime_service_error(exc.code, str(exc), operation.id) from exc
        except StructuredPrototypeStoreError as exc:
            await self._fail_operation(running, step, exc.code)
            raise self._runtime_service_error(exc.code, str(exc), operation.id) from exc
        except StructuredPrototypeServiceError as exc:
            await self._fail_operation(running, step, exc.code)
            raise self._runtime_service_error(exc.code, str(exc), operation.id) from exc
        state = ActivePrototypeRuntimeState(
            session=session,
            state_json=initial.state_json,
            view_model_json=initial.view_model_json,
            loaded_checkpoint_id=checkpoint_id,
            loaded_checkpoint_sequence_no=0,
            replayed_event_batch_ids=(),
        )
        return CreatePrototypeRuntimeSessionResult(
            operation_id=operation.id,
            correlation_id=operation.correlation_id,
            state=state,
        )

    async def apply_runtime_event_batch(
        self,
        *,
        session_id: str,
        client_request_id: str,
        expected_head_sequence_no: int,
        expected_state_hash: str,
        batch: dict[str, object],
    ) -> ApplyPrototypeRuntimeEventResult:
        _require_client_request_id(client_request_id)
        worker = self._runtime_worker
        session = await self._store.load_runtime_session(session_id)
        if session is None:
            raise StructuredPrototypeServiceError(
                "runtime_session_missing",
                "prototype runtime session does not exist",
            )
        request_hash = _manifest_hash(
            {
                "kind": "apply_runtime_event",
                "sessionId": session_id,
                "expectedHeadSequenceNo": expected_head_sequence_no,
                "expectedStateHash": expected_state_hash,
                "batch": batch,
            }
        )
        operation = self._queued_operation(
            operation_kind="apply_runtime_event",
            project_id=session.project_id,
            resource_kind="runtime_session",
            resource_id=session_id,
            client_request_id=client_request_id,
            request_manifest_hash=request_hash,
            config_manifest_hash=self._runtime_config_manifest_hash(
                worker.identity if worker is not None else None
            ),
        )
        created = await self._create_operation(operation)
        if not created.created:
            if created.operation.status != "succeeded":
                raise self._existing_operation_error(created.operation)
            existing = await self._store.load_runtime_event_batch_by_request(
                session_id,
                client_request_id,
            )
            if existing is None:
                raise StructuredPrototypeServiceError(
                    "operation_result_missing",
                    "prototype runtime operation has no event-batch result",
                    operation_id=created.operation.id,
                )
            state = await self._replay_runtime_session(session_id)
            return ApplyPrototypeRuntimeEventResult(
                operation_id=created.operation.id,
                correlation_id=created.operation.correlation_id,
                event_batch_id=existing.id,
                outcome=existing.outcome,
                state=state,
            )
        running, step = await self._start_operation(operation, "execute_runtime_event")
        try:
            worker = self._require_runtime_worker()
            client_event_id = batch.get("clientEventId")
            batch_sequence = batch.get("expectedSequenceNo")
            if client_event_id != client_request_id:
                raise StructuredPrototypeServiceError(
                    "runtime_client_event_id_mismatch",
                    "prototype runtime client event ID must equal the client request ID",
                    operation_id=operation.id,
                )
            if (
                not isinstance(batch_sequence, int)
                or isinstance(batch_sequence, bool)
                or batch_sequence != expected_head_sequence_no
            ):
                raise StructuredPrototypeServiceError(
                    "runtime_event_sequence_mismatch",
                    "prototype runtime event sequence does not match the expected session head",
                    operation_id=operation.id,
                )
            active = await self._replay_runtime_session(session_id)
            current = active.session
            if current.status != "active":
                raise StructuredPrototypeServiceError(
                    "runtime_session_not_active",
                    "prototype runtime session does not accept events",
                    operation_id=operation.id,
                    current_head_sequence_no=current.head_sequence_no,
                    current_state_hash=current.head_state_hash,
                )
            if (
                current.head_sequence_no != expected_head_sequence_no
                or current.head_state_hash != expected_state_hash
            ):
                raise StructuredPrototypeServiceError(
                    "runtime_session_conflict",
                    "prototype runtime event base does not match the current session head",
                    operation_id=operation.id,
                    current_head_sequence_no=current.head_sequence_no,
                    current_state_hash=current.head_state_hash,
                )
            document = await self._load_runtime_document(current)
            definition = self._runtime_definition_payload(document)
            transition = await worker.apply_event_batch(
                request_id=operation.id,
                definition=definition,
                state_json=active.state_json,
                batch=batch,
            )
            event_batch_id = _stable_id(operation.id, "runtime-event-batch")
            now = self._now()
            record = PrototypeRuntimeEventBatchRecord(
                id=event_batch_id,
                session_id=session_id,
                client_event_id=client_request_id,
                base_sequence_no=transition.base_sequence_no,
                result_sequence_no=transition.result_sequence_no,
                events_json=transition.events_json,
                event_batch_hash=transition.event_batch_hash,
                matched_rule_ids_json=transition.matched_rule_ids_json,
                guard_report_hash=transition.guard_report_hash,
                effect_report_hash=transition.effect_report_hash,
                outcome=transition.outcome,
                base_state_hash=expected_state_hash,
                result_state_hash=transition.state_hash,
                result_view_model_hash=transition.view_model_hash,
                runtime_core_version=worker.identity.runtime_core_version,
                runtime_core_bundle_hash=worker.identity.runtime_core_bundle_hash,
                state_machine_kernel_version=worker.identity.state_machine_kernel_version,
                operation_id=operation.id,
                created_at=now,
            )
            result_hash = _manifest_hash(
                {
                    "operationId": operation.id,
                    "eventBatchId": event_batch_id,
                    "eventBatchHash": transition.event_batch_hash,
                    "resultStateHash": transition.state_hash,
                    "resultViewModelHash": transition.view_model_hash,
                    "guardReportHash": transition.guard_report_hash,
                    "effectReportHash": transition.effect_report_hash,
                }
            )
            completed, completed_step, event = self._succeed_operation(
                running,
                step,
                result_hash=result_hash,
                evidence_kind="runtime_event_batch",
                evidence_ref=event_batch_id,
            )
            appended = await self._store.append_runtime_event_batch(
                event_batch=record,
                completed_operation=completed,
                completion_step=completed_step,
                completion_event=event,
            )
        except PrototypeRuntimeWorkerError as exc:
            await self._fail_operation(running, step, exc.code)
            raise self._runtime_service_error(exc.code, str(exc), operation.id, session) from exc
        except PrototypeObjectStoreError as exc:
            await self._fail_operation(running, step, exc.code)
            raise self._runtime_service_error(exc.code, str(exc), operation.id, session) from exc
        except StructuredPrototypeStoreError as exc:
            await self._fail_operation(running, step, exc.code)
            latest = await self._store.load_runtime_session(session_id)
            raise self._runtime_service_error(
                exc.code,
                str(exc),
                operation.id,
                latest or session,
            ) from exc
        except StructuredPrototypeServiceError as exc:
            await self._fail_operation(running, step, exc.code)
            raise self._runtime_service_error(exc.code, str(exc), operation.id, session) from exc
        updated_state = ActivePrototypeRuntimeState(
            session=appended.session,
            state_json=transition.state_json,
            view_model_json=transition.view_model_json,
            loaded_checkpoint_id=active.loaded_checkpoint_id,
            loaded_checkpoint_sequence_no=active.loaded_checkpoint_sequence_no,
            replayed_event_batch_ids=(*active.replayed_event_batch_ids, appended.event_batch.id),
        )
        return ApplyPrototypeRuntimeEventResult(
            operation_id=operation.id,
            correlation_id=operation.correlation_id,
            event_batch_id=appended.event_batch.id,
            outcome=appended.event_batch.outcome,
            state=updated_state,
        )

    async def recover_runtime_session(
        self,
        *,
        session_id: str,
        client_request_id: str,
    ) -> RecoverPrototypeRuntimeSessionResult:
        _require_client_request_id(client_request_id)
        worker = self._runtime_worker
        session = await self._store.load_runtime_session(session_id)
        if session is None:
            raise StructuredPrototypeServiceError(
                "runtime_session_missing",
                "prototype runtime session does not exist",
            )
        if session.status == "corrupt":
            raise StructuredPrototypeServiceError(
                "runtime_session_corrupt",
                "prototype runtime session is marked corrupt and cannot be replayed",
                current_head_sequence_no=session.head_sequence_no,
                current_state_hash=session.head_state_hash,
            )
        operation = self._queued_operation(
            operation_kind="replay_runtime_session",
            project_id=session.project_id,
            resource_kind="runtime_session",
            resource_id=session_id,
            client_request_id=client_request_id,
            request_manifest_hash=_manifest_hash(
                {
                    "kind": "replay_runtime_session",
                    "sessionId": session_id,
                    "headSequenceNo": session.head_sequence_no,
                    "stateHash": session.head_state_hash,
                    "viewModelHash": session.head_view_model_hash,
                }
            ),
            config_manifest_hash=self._runtime_config_manifest_hash(
                worker.identity if worker is not None else None
            ),
        )
        created = await self._create_operation(operation)
        if not created.created:
            if created.operation.status != "succeeded":
                raise self._existing_operation_error(created.operation)
            state = await self._replay_runtime_session(session_id)
            return RecoverPrototypeRuntimeSessionResult(
                operation_id=created.operation.id,
                correlation_id=created.operation.correlation_id,
                state=state,
            )
        running, step = await self._start_operation(operation, "replay_runtime_event_tail")
        try:
            self._require_runtime_worker()
            state = await self._replay_runtime_session(session_id)
            latest = await self._store.load_runtime_session(session_id)
            if latest is None:
                raise StructuredPrototypeServiceError(
                    "runtime_session_missing",
                    "prototype runtime session disappeared during replay",
                    operation_id=operation.id,
                )
            if (
                latest.head_sequence_no != state.session.head_sequence_no
                or latest.head_state_hash != state.session.head_state_hash
                or latest.head_view_model_hash != state.session.head_view_model_hash
            ):
                raise StructuredPrototypeServiceError(
                    "runtime_session_conflict",
                    "prototype runtime session head changed during replay",
                    operation_id=operation.id,
                    current_head_sequence_no=latest.head_sequence_no,
                    current_state_hash=latest.head_state_hash,
                )
            completed, completed_step, event = self._succeed_operation(
                running,
                step,
                result_hash=_manifest_hash(
                    {
                        "operationId": operation.id,
                        "sessionId": session_id,
                        "headSequenceNo": state.session.head_sequence_no,
                        "stateHash": state.session.head_state_hash,
                        "viewModelHash": state.session.head_view_model_hash,
                        "checkpointId": state.loaded_checkpoint_id,
                        "eventBatchIds": list(state.replayed_event_batch_ids),
                    }
                ),
                evidence_kind="runtime_state_hash",
                evidence_ref=state.session.head_state_hash,
            )
            await self._store.record_operation_transition(completed, completed_step, event)
            return RecoverPrototypeRuntimeSessionResult(
                operation_id=operation.id,
                correlation_id=operation.correlation_id,
                state=state,
            )
        except PrototypeRuntimeWorkerError as exc:
            await self._handle_runtime_recovery_failure(running, step, session, exc.code)
            raise self._runtime_service_error(exc.code, str(exc), operation.id, session) from exc
        except PrototypeObjectStoreError as exc:
            await self._handle_runtime_recovery_failure(running, step, session, exc.code)
            raise self._runtime_service_error(exc.code, str(exc), operation.id, session) from exc
        except StructuredPrototypeStoreError as exc:
            await self._handle_runtime_recovery_failure(running, step, session, exc.code)
            raise self._runtime_service_error(exc.code, str(exc), operation.id, session) from exc
        except StructuredPrototypeServiceError as exc:
            await self._handle_runtime_recovery_failure(running, step, session, exc.code)
            raise self._runtime_service_error(exc.code, str(exc), operation.id, session) from exc

    async def checkpoint_runtime_session(
        self,
        *,
        session_id: str,
        client_request_id: str,
    ) -> CheckpointPrototypeRuntimeSessionResult:
        _require_client_request_id(client_request_id)
        worker = self._runtime_worker
        session = await self._store.load_runtime_session(session_id)
        if session is None:
            raise StructuredPrototypeServiceError(
                "runtime_session_missing",
                "prototype runtime session does not exist",
            )
        operation = self._queued_operation(
            operation_kind="create_checkpoint",
            project_id=session.project_id,
            resource_kind="runtime_session",
            resource_id=session_id,
            client_request_id=client_request_id,
            request_manifest_hash=_manifest_hash(
                {
                    "kind": "create_runtime_checkpoint",
                    "sessionId": session_id,
                    "headSequenceNo": session.head_sequence_no,
                    "stateHash": session.head_state_hash,
                    "viewModelHash": session.head_view_model_hash,
                }
            ),
            config_manifest_hash=self._runtime_config_manifest_hash(
                worker.identity if worker is not None else None
            ),
        )
        created = await self._create_operation(operation)
        if not created.created:
            if created.operation.status != "succeeded":
                raise self._existing_operation_error(created.operation)
            state = await self._replay_runtime_session(session_id)
            if state.loaded_checkpoint_sequence_no != state.session.head_sequence_no:
                raise StructuredPrototypeServiceError(
                    "operation_result_missing",
                    "prototype runtime checkpoint result is no longer the session head",
                    operation_id=created.operation.id,
                )
            return CheckpointPrototypeRuntimeSessionResult(
                operation_id=created.operation.id,
                correlation_id=created.operation.correlation_id,
                checkpoint_id=state.loaded_checkpoint_id,
                state=state,
            )
        running, step = await self._start_operation(operation, "persist_runtime_checkpoint")
        try:
            self._require_runtime_worker()
            active = await self._replay_runtime_session(session_id)
            if active.session.status != "active":
                raise StructuredPrototypeServiceError(
                    "runtime_session_not_active",
                    "prototype runtime session does not accept checkpoints",
                    operation_id=operation.id,
                    current_head_sequence_no=active.session.head_sequence_no,
                    current_state_hash=active.session.head_state_hash,
                )
            if active.loaded_checkpoint_sequence_no == active.session.head_sequence_no:
                completed, completed_step, event = self._succeed_operation(
                    running,
                    step,
                    result_hash=_manifest_hash(
                        {
                            "operationId": operation.id,
                            "checkpointId": active.loaded_checkpoint_id,
                            "stateHash": active.session.head_state_hash,
                        }
                    ),
                    evidence_kind="runtime_checkpoint",
                    evidence_ref=active.loaded_checkpoint_id,
                )
                await self._store.record_operation_transition(completed, completed_step, event)
                return CheckpointPrototypeRuntimeSessionResult(
                    operation_id=operation.id,
                    correlation_id=operation.correlation_id,
                    checkpoint_id=active.loaded_checkpoint_id,
                    state=active,
                )
            try:
                state_payload: object = json.loads(active.state_json)
            except json.JSONDecodeError as exc:
                raise StructuredPrototypeServiceError(
                    "runtime_worker_response_invalid",
                    "prototype runtime replay returned invalid state JSON",
                    operation_id=operation.id,
                ) from exc
            descriptor = await asyncio.to_thread(
                self._object_store.write_json,
                active.session.project_id,
                state_payload,
            )
            if descriptor.content_hash != active.session.head_state_hash:
                raise StructuredPrototypeServiceError(
                    "runtime_checkpoint_state_hash_mismatch",
                    "prototype runtime checkpoint object does not match the session head",
                    operation_id=operation.id,
                )
            checkpoint_id = _stable_id(operation.id, "runtime-checkpoint")
            now = self._now()
            checkpoint = PrototypeRuntimeCheckpointRecord(
                id=checkpoint_id,
                session_id=session_id,
                checkpoint_sequence_no=active.session.head_sequence_no,
                state_object_hash=descriptor.content_hash,
                runtime_state_schema_version=RUNTIME_STATE_SCHEMA_VERSION,
                runtime_event_contract_version=RUNTIME_EVENT_CONTRACT_VERSION,
                state_hash=descriptor.content_hash,
                view_model_hash=active.session.head_view_model_hash,
                created_by_operation_id=operation.id,
                created_at=now,
            )
            completed, completed_step, event = self._succeed_operation(
                running,
                step,
                result_hash=_manifest_hash(
                    {
                        "operationId": operation.id,
                        "checkpointId": checkpoint_id,
                        "checkpointSequenceNo": checkpoint.checkpoint_sequence_no,
                        "stateHash": checkpoint.state_hash,
                        "viewModelHash": checkpoint.view_model_hash,
                    }
                ),
                evidence_kind="runtime_checkpoint",
                evidence_ref=checkpoint_id,
            )
            reference = PrototypeObjectReference(
                project_id=active.session.project_id,
                owner_kind="runtime_checkpoint",
                owner_id=checkpoint_id,
                role="runtime-state-checkpoint",
                content_hash=descriptor.content_hash,
                payload_type="prototype_runtime_state",
                schema_version=RUNTIME_STATE_SCHEMA_VERSION,
                created_at=now,
            )
            updated_session = await self._store.register_runtime_checkpoint(
                descriptor=descriptor,
                reference=reference,
                checkpoint=checkpoint,
                completed_operation=completed,
                completion_step=completed_step,
                completion_event=event,
            )
        except PrototypeRuntimeWorkerError as exc:
            await self._fail_operation(running, step, exc.code)
            raise self._runtime_service_error(exc.code, str(exc), operation.id, session) from exc
        except PrototypeObjectStoreError as exc:
            await self._fail_operation(running, step, exc.code)
            raise self._runtime_service_error(exc.code, str(exc), operation.id, session) from exc
        except StructuredPrototypeStoreError as exc:
            await self._fail_operation(running, step, exc.code)
            latest = await self._store.load_runtime_session(session_id)
            raise self._runtime_service_error(
                exc.code,
                str(exc),
                operation.id,
                latest or session,
            ) from exc
        except StructuredPrototypeServiceError as exc:
            await self._fail_operation(running, step, exc.code)
            raise self._runtime_service_error(exc.code, str(exc), operation.id, session) from exc
        state = ActivePrototypeRuntimeState(
            session=updated_session,
            state_json=active.state_json,
            view_model_json=active.view_model_json,
            loaded_checkpoint_id=checkpoint_id,
            loaded_checkpoint_sequence_no=checkpoint.checkpoint_sequence_no,
            replayed_event_batch_ids=(),
        )
        return CheckpointPrototypeRuntimeSessionResult(
            operation_id=operation.id,
            correlation_id=operation.correlation_id,
            checkpoint_id=checkpoint_id,
            state=state,
        )

    async def _replay_runtime_session(self, session_id: str) -> ActivePrototypeRuntimeState:
        worker = self._require_runtime_worker()
        bundle = await self._store.load_runtime_recovery_bundle(session_id)
        session = bundle.session
        self._assert_runtime_identity(session, worker.identity)
        if (
            bundle.checkpoint.runtime_state_schema_version != RUNTIME_STATE_SCHEMA_VERSION
            or bundle.checkpoint.runtime_event_contract_version != RUNTIME_EVENT_CONTRACT_VERSION
        ):
            raise StructuredPrototypeServiceError(
                "runtime_replay_contract_unsupported",
                "prototype runtime checkpoint contract version is unsupported",
            )
        document = await self._load_runtime_document(session)
        scenario = next(
            (
                candidate
                for candidate in document.runtime.scenarios
                if candidate.id == session.scenario_id
            ),
            None,
        )
        if scenario is None:
            raise StructuredPrototypeServiceError(
                "runtime_scenario_missing",
                "prototype runtime scenario does not exist in the pinned document",
            )
        if _manifest_hash(scenario.model_dump(mode="json", by_alias=True)) != session.scenario_hash:
            raise StructuredPrototypeServiceError(
                "runtime_scenario_hash_mismatch",
                "prototype runtime scenario does not match the pinned session hash",
            )
        state_bytes = await asyncio.to_thread(
            self._object_store.read_canonical_bytes,
            bundle.object_descriptor,
        )
        try:
            checkpoint_state_json = state_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise StructuredPrototypeServiceError(
                "runtime_checkpoint_state_invalid",
                "prototype runtime checkpoint state is not valid UTF-8",
            ) from exc
        try:
            checkpoint_state: object = json.loads(checkpoint_state_json)
        except json.JSONDecodeError as exc:
            raise StructuredPrototypeServiceError(
                "runtime_checkpoint_state_invalid",
                "prototype runtime checkpoint state is invalid JSON",
            ) from exc
        if _manifest_hash(checkpoint_state) != bundle.checkpoint.state_hash:
            raise StructuredPrototypeServiceError(
                "runtime_checkpoint_state_hash_mismatch",
                "prototype runtime checkpoint state does not match its durable hash",
            )
        replay_batches: list[dict[str, object]] = []
        for stored in bundle.event_batches:
            try:
                events: object = json.loads(stored.events_json)
            except json.JSONDecodeError as exc:
                raise StructuredPrototypeServiceError(
                    "runtime_event_payload_invalid",
                    "prototype runtime event payload is invalid JSON",
                ) from exc
            if not isinstance(events, list):
                raise StructuredPrototypeServiceError(
                    "runtime_event_payload_invalid",
                    "prototype runtime event payload must be an array",
                )
            replay_batches.append(
                {
                    "clientEventId": stored.client_event_id,
                    "expectedSequenceNo": stored.base_sequence_no,
                    "events": events,
                }
            )
        replayed = await worker.replay_event_batches(
            request_id=_stable_id(
                session.id,
                str(session.head_sequence_no),
                session.head_state_hash,
                "runtime-replay",
            ),
            definition=self._runtime_definition_payload(document),
            state_json=checkpoint_state_json,
            batches=replay_batches,
        )
        if len(replayed.transitions) != len(bundle.event_batches):
            raise StructuredPrototypeServiceError(
                "runtime_replay_evidence_mismatch",
                "prototype runtime replay did not return one result per event batch",
            )
        for stored, transition in zip(bundle.event_batches, replayed.transitions, strict=True):
            if (
                transition.client_event_id != stored.client_event_id
                or transition.base_sequence_no != stored.base_sequence_no
                or transition.result_sequence_no != stored.result_sequence_no
                or transition.outcome != stored.outcome
                or transition.events_json != stored.events_json
                or transition.event_batch_hash != stored.event_batch_hash
                or transition.matched_rule_ids_json != stored.matched_rule_ids_json
                or transition.guard_report_hash != stored.guard_report_hash
                or transition.effect_report_hash != stored.effect_report_hash
                or transition.state_hash != stored.result_state_hash
                or transition.view_model_hash != stored.result_view_model_hash
            ):
                raise StructuredPrototypeServiceError(
                    "runtime_replay_evidence_mismatch",
                    "prototype runtime replay result does not match durable event evidence",
                )
        if (
            replayed.final.state_hash != session.head_state_hash
            or replayed.final.view_model_hash != session.head_view_model_hash
        ):
            raise StructuredPrototypeServiceError(
                "runtime_replay_state_hash_mismatch",
                "prototype runtime replay result does not match the durable session head",
            )
        return ActivePrototypeRuntimeState(
            session=session,
            state_json=replayed.final.state_json,
            view_model_json=replayed.final.view_model_json,
            loaded_checkpoint_id=bundle.checkpoint.id,
            loaded_checkpoint_sequence_no=bundle.checkpoint.checkpoint_sequence_no,
            replayed_event_batch_ids=tuple(batch.id for batch in bundle.event_batches),
        )

    async def _replay_draft(self, draft_id: str) -> ActivePrototypeState:
        bundle = await self._store.load_draft_recovery_bundle(draft_id)
        if bundle.checkpoint.document_schema_version != DOCUMENT_SCHEMA_VERSION:
            raise StructuredPrototypeContractError(
                "replay_contract_unsupported",
                "prototype checkpoint document schema version is unsupported",
            )
        if bundle.checkpoint.command_contract_version != COMMAND_CONTRACT_VERSION:
            raise StructuredPrototypeContractError(
                "replay_contract_unsupported",
                "prototype checkpoint command contract version is unsupported",
            )
        canonical_bytes = await asyncio.to_thread(
            self._object_store.read_canonical_bytes,
            bundle.object_descriptor,
        )
        document = parse_prototype_document_json(canonical_bytes)
        if document.id != bundle.document.id:
            raise StructuredPrototypeContractError(
                "document_identity_mismatch",
                "prototype checkpoint document identity does not match its record",
            )
        if document_hash(document) != bundle.checkpoint.document_hash:
            raise StructuredPrototypeContractError(
                "replay_document_hash_mismatch",
                "prototype checkpoint document hash does not match its record",
            )
        applied_ids: list[str] = []
        for stored_batch in bundle.command_batches:
            if stored_batch.command_contract_version != COMMAND_CONTRACT_VERSION:
                raise StructuredPrototypeContractError(
                    "replay_contract_unsupported",
                    "prototype command contract version is unsupported",
                )
            parsed_batch = parse_command_batch_json(stored_batch.commands_json)
            if (
                canonical_model_json(parsed_batch) != stored_batch.commands_json
                or command_batch_hash(parsed_batch) != stored_batch.command_batch_hash
            ):
                raise StructuredPrototypeContractError(
                    "replay_batch_hash_mismatch",
                    "prototype command batch hash does not match its payload",
                )
            if document_hash(document) != stored_batch.base_document_hash:
                raise StructuredPrototypeContractError(
                    "replay_document_hash_mismatch",
                    "prototype replay document does not match the command base hash",
                )
            execution = execute_command_batch(
                document,
                parsed_batch,
                draft_id=stored_batch.draft_id,
                client_request_id=stored_batch.client_request_id,
            )
            parsed_inverse = parse_inverse_command_batch_json(stored_batch.inverse_commands_json)
            if canonical_model_json(parsed_inverse) != stored_batch.inverse_commands_json:
                raise StructuredPrototypeContractError(
                    "inverse_command_mismatch",
                    "prototype inverse command payload is not canonical",
                )
            if (
                canonical_model_json(execution.inverse_commands)
                != stored_batch.inverse_commands_json
            ):
                raise StructuredPrototypeContractError(
                    "inverse_command_mismatch",
                    "prototype inverse commands do not match deterministic execution",
                )
            if execution.result_document_hash != stored_batch.result_document_hash:
                raise StructuredPrototypeContractError(
                    "replay_document_hash_mismatch",
                    "prototype replay result does not match the command result hash",
                )
            document = execution.document
            applied_ids.append(stored_batch.id)
        if document_hash(document) != bundle.draft.head_document_hash:
            raise StructuredPrototypeContractError(
                "replay_document_hash_mismatch",
                "prototype replay result does not match the draft head",
            )
        return ActivePrototypeState(
            document_record=bundle.document,
            draft=bundle.draft,
            document=document,
            loaded_checkpoint_id=bundle.checkpoint.id,
            loaded_checkpoint_sequence_no=bundle.checkpoint.checkpoint_sequence_no,
            applied_tail_batch_ids=tuple(applied_ids),
        )

    async def _resolve_existing_create(
        self,
        operation: PrototypeOperation,
    ) -> CreateStructuredPrototypeResult:
        if operation.status != "succeeded" or operation.resource_id is None:
            raise self._existing_operation_error(operation)
        document_record = await self._store.load_document(operation.resource_id)
        if document_record is None or document_record.active_draft_id is None:
            raise StructuredPrototypeServiceError(
                "operation_result_missing",
                "prototype create operation has no durable document result",
                operation_id=operation.id,
            )
        draft = await self._store.load_draft(document_record.active_draft_id)
        if draft is None:
            raise StructuredPrototypeServiceError(
                "operation_result_missing",
                "prototype create operation has no durable draft result",
                operation_id=operation.id,
            )
        recovered = await self.recover_draft(
            draft_id=document_record.active_draft_id,
            client_request_id=_stable_id(
                operation.id,
                str(draft.head_sequence_no),
                draft.head_document_hash,
                "idempotent-recovery",
            ),
        )
        state = recovered.state
        return CreateStructuredPrototypeResult(
            operation_id=operation.id,
            correlation_id=operation.correlation_id,
            state=state,
        )

    async def _resolve_existing_apply(
        self,
        operation: PrototypeOperation,
        state: ActivePrototypeState,
    ) -> ApplyStructuredPrototypeCommandsResult:
        if operation.status != "succeeded":
            raise self._existing_operation_error(operation)
        batch = await self._store.load_command_batch_by_request(
            state.draft.id,
            operation.client_request_id,
        )
        if batch is None:
            raise StructuredPrototypeServiceError(
                "operation_result_missing",
                "prototype command operation has no durable batch result",
                operation_id=operation.id,
            )
        if (
            state.draft.head_sequence_no != batch.result_sequence_no
            or state.draft.head_document_hash != batch.result_document_hash
        ):
            raise StructuredPrototypeServiceError(
                "idempotent_result_superseded",
                "prototype command was already applied but its original response is no longer the head",
                operation_id=operation.id,
                current_head_sequence_no=state.draft.head_sequence_no,
                current_document_hash=state.draft.head_document_hash,
            )
        inverse = parse_inverse_command_batch_json(batch.inverse_commands_json)
        base_document = apply_inverse_commands(state.document, inverse)
        parsed_batch = parse_command_batch_json(batch.commands_json)
        execution = execute_command_batch(
            base_document,
            parsed_batch,
            draft_id=batch.draft_id,
            client_request_id=batch.client_request_id,
        )
        if execution.result_document_hash != state.draft.head_document_hash:
            raise StructuredPrototypeServiceError(
                "operation_result_corrupt",
                "prototype idempotent command result cannot be reconstructed",
                operation_id=operation.id,
            )
        return ApplyStructuredPrototypeCommandsResult(
            operation_id=operation.id,
            correlation_id=operation.correlation_id,
            applied_batch_id=batch.id,
            allocated_entity_ids=execution.allocated_entity_ids,
            affected_entity_ids=execution.affected_entity_ids,
            state=state,
        )

    async def _resolve_existing_publish(
        self,
        operation: PrototypeOperation,
    ) -> PublishStructuredPrototypeResult:
        if operation.status != "succeeded":
            raise self._existing_operation_error(operation)
        run = await self._store.load_render_run_by_operation(operation.id)
        if run is None or run.status != "ready" or run.artifact_id is None or run.revision_id is None:
            raise StructuredPrototypeServiceError(
                "operation_result_missing",
                "prototype publish operation has no durable ready render result",
                operation_id=operation.id,
            )
        published = await self._store.load_published_record(run.document_id)
        if (
            published is None
            or published.revision.id != run.revision_id
            or published.artifact.id != run.artifact_id
        ):
            raise StructuredPrototypeServiceError(
                "idempotent_result_superseded",
                "prototype publication succeeded but a newer revision is now public",
                operation_id=operation.id,
            )
        if published.document.active_draft_id is None:
            raise StructuredPrototypeServiceError(
                "operation_result_missing",
                "prototype published document has no active draft",
                operation_id=operation.id,
            )
        state = await self._replay_draft(published.document.active_draft_id)
        return PublishStructuredPrototypeResult(
            operation_id=operation.id,
            correlation_id=operation.correlation_id,
            publication=self._published_snapshot(
                published.document,
                published.revision,
                published.render_run,
                published.artifact,
            ),
            state=state,
        )

    async def _fail_frozen_publication(
        self,
        *,
        frozen: PrototypePublicationFreezeResult,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        event_no: int,
        error_code: str,
        error_message: str,
    ) -> None:
        failed, failed_step, failed_event = self._failed_transition_at(
            operation,
            step,
            error_code,
            event_no,
        )
        try:
            await self._store.fail_publication(
                render_run_id=frozen.render_run.id,
                draft_id=frozen.draft.id,
                error_code=error_code,
                error_message=error_message,
                failed_at=self._now(),
                failed_operation=failed,
                failed_step=failed_step,
                failed_event=failed_event,
            )
        except StructuredPrototypeStoreError as exc:
            raise StructuredPrototypeServiceError(
                "operation_evidence_unavailable",
                "prototype publication failure evidence could not be persisted",
                operation_id=operation.id,
            ) from exc

    def _require_publication_dependencies(
        self,
    ) -> tuple[PrototypeRendererExecution, PrototypeRenderArtifactStorage]:
        if self._renderer_worker is None:
            raise StructuredPrototypeServiceError(
                "renderer_worker_unavailable",
                "prototype renderer worker is unavailable",
            )
        if self._artifact_store is None:
            raise StructuredPrototypeServiceError(
                "render_artifact_store_unavailable",
                "prototype render artifact store is unavailable",
            )
        return self._renderer_worker, self._artifact_store

    def _assert_renderer_runtime_compatibility(
        self,
        renderer: PrototypeRendererWorkerIdentity,
    ) -> None:
        runtime = self._runtime_worker
        if runtime is None:
            raise StructuredPrototypeServiceError(
                "runtime_worker_unavailable",
                "prototype runtime worker is required to publish a runnable artifact",
            )
        identity = runtime.identity
        if (
            renderer.runtime_core_version != identity.runtime_core_version
            or renderer.runtime_core_source_hash != identity.runtime_core_source_hash
            or renderer.state_machine_kernel_version != identity.state_machine_kernel_version
        ):
            raise StructuredPrototypeServiceError(
                "renderer_runtime_compatibility_mismatch",
                "prototype renderer and backend runtime worker do not share the same runtime core",
            )

    @staticmethod
    def _renderer_input_manifest(
        identity: PrototypeRendererWorkerIdentity,
        *,
        document_object_hash: str,
        output_locale: Literal["zh-CN", "en-US"],
        asset_object_hashes: list[str],
    ) -> dict[str, object]:
        return {
            "rendererVersion": identity.renderer_version,
            "rendererEnvironmentVersion": identity.renderer_environment_version,
            "runtimeCoreVersion": identity.runtime_core_version,
            "runtimeCoreSourceHash": identity.runtime_core_source_hash,
            "runtimeCoreBundleHash": identity.runtime_core_bundle_hash,
            "stateMachineKernelVersion": identity.state_machine_kernel_version,
            "renderRuntimeImageHash": identity.render_runtime_image_hash,
            "browserVersion": identity.browser_version,
            "fontPackHash": identity.font_pack_hash,
            "viewportProfileHash": identity.viewport_profile_hash,
            "documentObjectHash": document_object_hash,
            "documentSchemaVersion": DOCUMENT_SCHEMA_VERSION,
            "assetObjectHashes": sorted(asset_object_hashes),
            "sandboxPolicyVersion": identity.sandbox_policy_version,
            "outputLocale": output_locale,
        }

    @staticmethod
    def _published_snapshot(
        document: PrototypeDocumentRecord,
        revision: PrototypeRevisionRecord,
        run: PrototypeRenderRunRecord,
        artifact: PrototypeRenderArtifactRecord,
    ) -> PublishedPrototypeSnapshot:
        if (
            revision.document_id != document.id
            or run.revision_id != revision.id
            or artifact.render_run_id != run.id
            or artifact.revision_id != revision.id
            or run.status != "ready"
        ):
            raise StructuredPrototypeServiceError(
                "published_artifact_corrupt",
                "prototype published artifact identities are inconsistent",
            )
        return PublishedPrototypeSnapshot(
            document_id=document.id,
            revision_id=revision.id,
            revision_no=revision.revision_no,
            render_run_id=run.id,
            artifact_id=artifact.id,
            renderer_version=run.renderer_version,
            document_hash=revision.document_hash,
            output_hash=artifact.output_hash,
            output_manifest_hash=artifact.output_manifest_hash,
            visual_preflight_report_hash=artifact.visual_preflight_report_hash,
            published_at=artifact.created_at,
        )

    async def _load_runtime_document(
        self,
        session: PrototypeRuntimeSessionRecord,
    ) -> PrototypeDocumentV1:
        descriptor = await self._store.load_object(
            session.project_id,
            session.pinned_document_object_hash,
        )
        if descriptor is None:
            raise StructuredPrototypeServiceError(
                "object_missing",
                "prototype runtime pinned document object is missing",
            )
        canonical_bytes = await asyncio.to_thread(
            self._object_store.read_canonical_bytes,
            descriptor,
        )
        document = parse_prototype_document_json(canonical_bytes)
        if document.id != session.document_id:
            raise StructuredPrototypeServiceError(
                "runtime_document_identity_mismatch",
                "prototype runtime pinned document identity does not match the session",
            )
        if document_hash(document) != session.pinned_document_object_hash:
            raise StructuredPrototypeServiceError(
                "runtime_document_hash_mismatch",
                "prototype runtime pinned document does not match its session hash",
            )
        return document

    @staticmethod
    def _runtime_definition_payload(document: PrototypeDocumentV1) -> dict[str, object]:
        payload: object = document.runtime.model_dump(mode="json", by_alias=True)
        parsed = object_dict_or_none(payload)
        if parsed is None:
            raise StructuredPrototypeServiceError(
                "runtime_definition_invalid",
                "prototype runtime definition did not serialize to an object",
            )
        return parsed

    @staticmethod
    def _assert_runtime_identity(
        session: PrototypeRuntimeSessionRecord,
        identity: PrototypeRuntimeWorkerIdentity,
    ) -> None:
        if (
            session.runtime_core_version != identity.runtime_core_version
            or session.runtime_core_bundle_hash != identity.runtime_core_bundle_hash
            or session.state_machine_kernel_version != identity.state_machine_kernel_version
        ):
            raise StructuredPrototypeServiceError(
                "runtime_replay_version_mismatch",
                "prototype runtime worker identity does not match the pinned session",
            )

    def _require_runtime_worker(self) -> PrototypeRuntimeExecution:
        if self._runtime_worker is None:
            raise StructuredPrototypeServiceError(
                "runtime_worker_unavailable",
                "prototype runtime worker is unavailable",
            )
        return self._runtime_worker

    async def _handle_runtime_recovery_failure(
        self,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        session: PrototypeRuntimeSessionRecord,
        error_code: str,
    ) -> None:
        failed, failed_step, event = self._failed_transition(operation, step, error_code)
        if error_code not in CORRUPTION_ERROR_CODES:
            await self._record_failed_transition(failed, failed_step, event)
            return
        try:
            await self._store.mark_runtime_session_corrupt(
                session_id=session.id,
                expected_head_sequence_no=session.head_sequence_no,
                expected_state_hash=session.head_state_hash,
                expected_view_model_hash=session.head_view_model_hash,
                failed_operation=failed,
                failed_step=failed_step,
                failure_event=event,
            )
        except StructuredPrototypeStoreError as exc:
            replacement, replacement_step, replacement_event = self._failed_transition(
                operation,
                step,
                exc.code,
            )
            await self._record_failed_transition(
                replacement,
                replacement_step,
                replacement_event,
            )
            raise self._runtime_service_error(
                exc.code,
                str(exc),
                operation.id,
                session,
            ) from exc

    async def _handle_recovery_failure(
        self,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        draft: PrototypeDraftRecord,
        error_code: str,
    ) -> None:
        failed, failed_step, event = self._failed_transition(operation, step, error_code)
        if error_code not in CORRUPTION_ERROR_CODES:
            await self._record_failed_transition(failed, failed_step, event)
            return
        try:
            await self._store.mark_draft_corrupt(
                draft_id=draft.id,
                expected_head_sequence_no=draft.head_sequence_no,
                expected_document_hash=draft.head_document_hash,
                failed_operation=failed,
                failed_step=failed_step,
                failure_event=event,
            )
        except StructuredPrototypeStoreError as exc:
            replacement, replacement_step, replacement_event = self._failed_transition(
                operation,
                step,
                exc.code,
            )
            await self._record_failed_transition(
                replacement,
                replacement_step,
                replacement_event,
            )
            raise self._service_error(exc.code, str(exc), operation.id, draft) from exc

    async def _create_operation(
        self,
        operation: PrototypeOperation,
    ) -> PrototypeOperationCreateResult:
        try:
            return await self._store.create_operation(operation, self._queued_event(operation))
        except StructuredPrototypeStoreError as exc:
            raise self._service_error(exc.code, str(exc), operation.id) from exc

    async def _start_operation(
        self,
        operation: PrototypeOperation,
        step_kind: str,
    ) -> tuple[PrototypeOperation, PrototypeOperationStep]:
        now = self._now()
        running = replace(
            operation,
            status="running",
            phase=step_kind,
            started_at=now,
        )
        step = PrototypeOperationStep(
            id=_stable_id(operation.id, "step", "0"),
            operation_id=operation.id,
            parent_step_id=None,
            step_kind=step_kind,
            step_ordinal=0,
            attempt=1,
            status="running",
            phase=step_kind,
            input_manifest_hash=operation.request_manifest_hash,
            config_manifest_hash=operation.config_manifest_hash,
            output_manifest_hash=None,
            completion_evidence_kind=None,
            completion_evidence_ref=None,
            error_code=None,
            started_at=now,
            completed_at=None,
        )
        event = PrototypeOperationEvent(
            operation_id=operation.id,
            event_no=1,
            step_id=step.id,
            event_kind="step_started",
            status="running",
            phase=step_kind,
            input_hash=operation.request_manifest_hash,
            output_hash=None,
            evidence_hash=None,
            error_code=None,
            occurred_at=now,
        )
        try:
            await self._store.record_operation_transition(running, step, event)
        except StructuredPrototypeStoreError as exc:
            raise self._service_error(exc.code, str(exc), operation.id) from exc
        return running, step

    async def _start_followup_step(
        self,
        operation: PrototypeOperation,
        *,
        step_kind: str,
        step_ordinal: int,
        event_no: int,
        input_manifest_hash: str,
    ) -> tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent]:
        now = self._now()
        running = replace(operation, status="running", phase=step_kind)
        step = PrototypeOperationStep(
            id=_stable_id(operation.id, "step", str(step_ordinal)),
            operation_id=operation.id,
            parent_step_id=None,
            step_kind=step_kind,
            step_ordinal=step_ordinal,
            attempt=1,
            status="running",
            phase=step_kind,
            input_manifest_hash=input_manifest_hash,
            config_manifest_hash=operation.config_manifest_hash,
            output_manifest_hash=None,
            completion_evidence_kind=None,
            completion_evidence_ref=None,
            error_code=None,
            started_at=now,
            completed_at=None,
        )
        event = PrototypeOperationEvent(
            operation_id=operation.id,
            event_no=event_no,
            step_id=step.id,
            event_kind="step_started",
            status="running",
            phase=step_kind,
            input_hash=input_manifest_hash,
            output_hash=None,
            evidence_hash=None,
            error_code=None,
            occurred_at=now,
        )
        return running, step, event

    def _complete_nonterminal_step(
        self,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        *,
        output_hash: str,
        evidence_kind: str,
        evidence_ref: str,
        event_no: int,
    ) -> tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent]:
        now = self._now()
        running = replace(operation, status="running", phase=step.phase)
        completed_step = replace(
            step,
            status="succeeded",
            output_manifest_hash=output_hash,
            completion_evidence_kind=evidence_kind,
            completion_evidence_ref=evidence_ref,
            completed_at=now,
        )
        event = PrototypeOperationEvent(
            operation_id=operation.id,
            event_no=event_no,
            step_id=step.id,
            event_kind="step_succeeded",
            status="succeeded",
            phase=step.phase,
            input_hash=step.input_manifest_hash,
            output_hash=output_hash,
            evidence_hash=output_hash,
            error_code=None,
            occurred_at=now,
        )
        return running, completed_step, event

    def _succeed_operation_at(
        self,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        *,
        result_hash: str,
        evidence_kind: str,
        evidence_ref: str,
        event_no: int,
    ) -> tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent]:
        completed, completed_step, event = self._succeed_operation(
            operation,
            step,
            result_hash=result_hash,
            evidence_kind=evidence_kind,
            evidence_ref=evidence_ref,
        )
        return completed, completed_step, replace(event, event_no=event_no)

    async def _fail_operation(
        self,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        error_code: str,
    ) -> None:
        failed, failed_step, event = self._failed_transition(operation, step, error_code)
        await self._record_failed_transition(failed, failed_step, event)

    async def _record_failed_transition(
        self,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        event: PrototypeOperationEvent,
    ) -> None:
        try:
            await self._store.record_operation_transition(operation, step, event)
        except StructuredPrototypeStoreError as exc:
            raise StructuredPrototypeServiceError(
                "operation_evidence_unavailable",
                "prototype operation failure evidence could not be persisted",
                operation_id=operation.id,
            ) from exc

    def _queued_operation(
        self,
        *,
        operation_kind: PrototypeOperationKind,
        project_id: str,
        resource_kind: str,
        resource_id: str | None,
        client_request_id: str,
        request_manifest_hash: str,
        config_manifest_hash: str | None = None,
    ) -> PrototypeOperation:
        operation_id = _stable_id(project_id, operation_kind, client_request_id, "operation")
        return PrototypeOperation(
            id=operation_id,
            operation_kind=operation_kind,
            project_id=project_id,
            resource_kind=resource_kind,
            resource_id=resource_id,
            client_request_id=client_request_id,
            correlation_id=_stable_id(operation_id, "correlation"),
            parent_operation_id=None,
            status="queued",
            phase="queued",
            attempt=1,
            request_manifest_hash=request_manifest_hash,
            config_manifest_hash=(
                config_manifest_hash
                if config_manifest_hash is not None
                else self._config_manifest_hash()
            ),
            result_manifest_hash=None,
            failure_evidence_hash=None,
            error_code=None,
            created_at=self._now(),
            started_at=None,
            completed_at=None,
        )

    def _queued_event(self, operation: PrototypeOperation) -> PrototypeOperationEvent:
        return PrototypeOperationEvent(
            operation_id=operation.id,
            event_no=0,
            step_id=None,
            event_kind="operation_queued",
            status="queued",
            phase="queued",
            input_hash=operation.request_manifest_hash,
            output_hash=None,
            evidence_hash=None,
            error_code=None,
            occurred_at=operation.created_at,
        )

    def _succeed_operation(
        self,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        *,
        result_hash: str,
        evidence_kind: str,
        evidence_ref: str,
    ) -> tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent]:
        now = self._now()
        completed = replace(
            operation,
            status="succeeded",
            result_manifest_hash=result_hash,
            completed_at=now,
        )
        completed_step = replace(
            step,
            status="succeeded",
            output_manifest_hash=result_hash,
            completion_evidence_kind=evidence_kind,
            completion_evidence_ref=evidence_ref,
            completed_at=now,
        )
        event = PrototypeOperationEvent(
            operation_id=operation.id,
            event_no=2,
            step_id=step.id,
            event_kind="step_succeeded",
            status="succeeded",
            phase=step.phase,
            input_hash=step.input_manifest_hash,
            output_hash=result_hash,
            evidence_hash=result_hash,
            error_code=None,
            occurred_at=now,
        )
        return completed, completed_step, event

    def _failed_transition(
        self,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        error_code: str,
    ) -> tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent]:
        now = self._now()
        failure_hash = _manifest_hash(
            {
                "operationEvidenceVersion": OPERATION_EVIDENCE_VERSION,
                "operationId": operation.id,
                "stepId": step.id,
                "phase": step.phase,
                "errorCode": error_code,
            }
        )
        failed = replace(
            operation,
            status="failed",
            failure_evidence_hash=failure_hash,
            error_code=error_code,
            completed_at=now,
        )
        failed_step = replace(
            step,
            status="failed",
            output_manifest_hash=failure_hash,
            completion_evidence_kind="failure_manifest_hash",
            completion_evidence_ref=failure_hash,
            error_code=error_code,
            completed_at=now,
        )
        event = PrototypeOperationEvent(
            operation_id=operation.id,
            event_no=2,
            step_id=step.id,
            event_kind="step_failed",
            status="failed",
            phase=step.phase,
            input_hash=step.input_manifest_hash,
            output_hash=None,
            evidence_hash=failure_hash,
            error_code=error_code,
            occurred_at=now,
        )
        return failed, failed_step, event

    def _failed_transition_at(
        self,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        error_code: str,
        event_no: int,
    ) -> tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent]:
        failed, failed_step, event = self._failed_transition(operation, step, error_code)
        return failed, failed_step, replace(event, event_no=event_no)

    def _config_manifest_hash(self) -> str:
        return _manifest_hash(
            {
                "serviceVersion": SERVICE_VERSION,
                "documentSchemaVersion": DOCUMENT_SCHEMA_VERSION,
                "commandContractVersion": COMMAND_CONTRACT_VERSION,
                "canonicalizerVersion": CANONICALIZER_VERSION,
                "operationEvidenceVersion": OPERATION_EVIDENCE_VERSION,
            }
        )

    @staticmethod
    def _runtime_config_manifest_hash(
        identity: PrototypeRuntimeWorkerIdentity | None,
    ) -> str:
        if identity is None:
            return _manifest_hash(
                {
                    "serviceVersion": SERVICE_VERSION,
                    "runtimeWorkerAvailable": False,
                    "runtimeStateSchemaVersion": RUNTIME_STATE_SCHEMA_VERSION,
                    "runtimeEventContractVersion": RUNTIME_EVENT_CONTRACT_VERSION,
                    "operationEvidenceVersion": OPERATION_EVIDENCE_VERSION,
                }
            )
        return _manifest_hash(
            {
                "serviceVersion": SERVICE_VERSION,
                "runtimeWorkerAvailable": True,
                "runtimeStateSchemaVersion": RUNTIME_STATE_SCHEMA_VERSION,
                "runtimeEventContractVersion": RUNTIME_EVENT_CONTRACT_VERSION,
                "runtimeWorkerProtocolVersion": identity.protocol_version,
                "runtimeCoreVersion": identity.runtime_core_version,
                "runtimeCoreSourceHash": identity.runtime_core_source_hash,
                "runtimeCoreBundleHash": identity.runtime_core_bundle_hash,
                "runtimeCoreBundleByteSize": identity.runtime_core_bundle_byte_size,
                "stateMachineKernelVersion": identity.state_machine_kernel_version,
                "buildTool": identity.build_tool,
                "target": identity.target,
                "operationEvidenceVersion": OPERATION_EVIDENCE_VERSION,
            }
        )

    @staticmethod
    def _renderer_config_manifest_hash(
        identity: PrototypeRendererWorkerIdentity | None,
    ) -> str:
        if identity is None:
            return _manifest_hash(
                {
                    "serviceVersion": SERVICE_VERSION,
                    "rendererWorkerAvailable": False,
                    "operationEvidenceVersion": OPERATION_EVIDENCE_VERSION,
                }
            )
        return _manifest_hash(
            {
                "serviceVersion": SERVICE_VERSION,
                "rendererWorkerAvailable": True,
                "rendererWorkerProtocolVersion": identity.protocol_version,
                "rendererVersion": identity.renderer_version,
                "rendererEnvironmentVersion": identity.renderer_environment_version,
                "rendererSourceHash": identity.renderer_source_hash,
                "runtimeCoreVersion": identity.runtime_core_version,
                "runtimeCoreSourceHash": identity.runtime_core_source_hash,
                "runtimeCoreBundleHash": identity.runtime_core_bundle_hash,
                "stateMachineKernelVersion": identity.state_machine_kernel_version,
                "renderRuntimeImageHash": identity.render_runtime_image_hash,
                "browserVersion": identity.browser_version,
                "fontPackHash": identity.font_pack_hash,
                "viewportProfileHash": identity.viewport_profile_hash,
                "sandboxPolicyVersion": identity.sandbox_policy_version,
                "publicRuntimeHash": identity.public_runtime_hash,
                "publicRuntimeByteSize": identity.public_runtime_byte_size,
                "workerBundleHash": identity.bundle_hash,
                "workerBundleByteSize": identity.bundle_byte_size,
                "buildTool": identity.build_tool,
                "target": identity.target,
                "operationEvidenceVersion": OPERATION_EVIDENCE_VERSION,
            }
        )

    def _now(self) -> datetime:
        now = self._clock()
        if now.utcoffset() is None:
            raise StructuredPrototypeServiceError(
                "clock_invalid", "prototype service clock must be timezone-aware"
            )
        return now.astimezone(UTC)

    @staticmethod
    def _existing_operation_error(operation: PrototypeOperation) -> StructuredPrototypeServiceError:
        if operation.status in {"queued", "running"}:
            return StructuredPrototypeServiceError(
                "operation_in_progress",
                "prototype operation is already in progress",
                operation_id=operation.id,
            )
        return StructuredPrototypeServiceError(
            operation.error_code or "operation_terminal",
            "prototype operation already reached a terminal state",
            operation_id=operation.id,
        )

    @staticmethod
    def _service_error(
        code: str,
        message: str,
        operation_id: str | None,
        draft: PrototypeDraftRecord | None = None,
    ) -> StructuredPrototypeServiceError:
        return StructuredPrototypeServiceError(
            code,
            message,
            operation_id=operation_id,
            current_head_sequence_no=draft.head_sequence_no if draft is not None else None,
            current_document_hash=draft.head_document_hash if draft is not None else None,
        )

    @staticmethod
    def _runtime_service_error(
        code: str,
        message: str,
        operation_id: str,
        session: PrototypeRuntimeSessionRecord | None = None,
    ) -> StructuredPrototypeServiceError:
        return StructuredPrototypeServiceError(
            code,
            message,
            operation_id=operation_id,
            current_head_sequence_no=(session.head_sequence_no if session is not None else None),
            current_state_hash=session.head_state_hash if session is not None else None,
        )
