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
from app.adapters.prototype_snap_worker import PrototypeSnapWorkerError
from app.adapters.structured_prototype_store import StructuredPrototypeStoreError
from app.application.structured_prototype_contracts import (
    COMMAND_CONTRACT_VERSION,
    COMMAND_HISTORY_CHECKPOINT_SCHEMA_VERSION,
    DOCUMENT_SCHEMA_VERSION,
    CommandExecutionResultV1,
    CommandHistoryCheckpointV1,
    CommandHistoryEntryV1,
    DomainCommandBatchV1,
    InverseCommandBatchV1,
    NewPrototypeDocumentV1,
    PrototypeDocumentV1,
    StructuredPrototypeContractError,
    advance_journal_prefix_hash,
    canonical_command_history_checkpoint_json,
    canonical_model_json,
    command_batch_envelope_hash,
    command_batch_hash,
    command_history_checkpoint_payload,
    command_history_checkpoint_to_domain,
    document_hash,
    document_payload,
    execute_command_batch,
    execute_inverse_command_batch,
    initial_journal_prefix_hash,
    parse_command_batch_json,
    parse_command_history_checkpoint_json,
    parse_inverse_command_batch_json,
    parse_prototype_document_json,
    validate_command_batch_evidence_context,
)
from app.domain.structured_prototype import (
    PROTOTYPE_FORWARD_COMMAND_BATCH_MAX_BYTES,
    REPLAY_MANIFEST_SCHEMA_VERSION,
    PrototypeCheckpointRecord,
    PrototypeCommandAppendResult,
    PrototypeCommandBatchRecord,
    PrototypeCommandHistory,
    PrototypeCommandHistoryCheckpoint,
    PrototypeCommandHistoryEntry,
    PrototypeCommandHistoryError,
    PrototypeDocumentRecord,
    PrototypeDraftRecord,
    PrototypeDraftRecoveryBundle,
    PrototypeObjectDescriptor,
    PrototypeObjectReference,
    PrototypeOperation,
    PrototypeOperationCreateResult,
    PrototypeOperationEvent,
    PrototypeOperationKind,
    PrototypeOperationObservabilitySnapshot,
    PrototypeOperationStep,
    PrototypeProjectDeletionCounts,
    PrototypePublicationCompletionResult,
    PrototypePublicationFreezeResult,
    PrototypePublishedRecord,
    PrototypeRenderArtifactRecord,
    PrototypeRenderBundleDescriptor,
    PrototypeRendererWorkerIdentity,
    PrototypeRendererWorkerResult,
    PrototypeRenderRunRecord,
    PrototypeReplayManifestError,
    PrototypeReplayManifestV1,
    PrototypeReplayManifestVersionsV1,
    PrototypeRevisionRecord,
    PrototypeRuntimeCheckpointRecord,
    PrototypeRuntimeEventAppendResult,
    PrototypeRuntimeEventBatchRecord,
    PrototypeRuntimeRecordingKind,
    PrototypeRuntimeRecoveryBundle,
    PrototypeRuntimeSessionRecord,
    PrototypeRuntimeSessionStatus,
    PrototypeRuntimeWorkerIdentity,
    PrototypeRuntimeWorkerReplayResult,
    PrototypeRuntimeWorkerStateResult,
    PrototypeRuntimeWorkerTransitionResult,
    PrototypeSnapWorkerAttestationResult,
    PrototypeSnapWorkerIdentity,
    advance_prototype_command_history,
)
from app.json_safety import object_dict_or_none

OPERATION_EVIDENCE_VERSION = 1
SERVICE_VERSION = "structured-prototype-service/0.1.0"
PROTOTYPE_SERVICE_NAMESPACE = UUID("7c196dbd-592b-50a3-908b-6de3288d8829")
RUNTIME_STATE_SCHEMA_VERSION = 1
RUNTIME_EVENT_CONTRACT_VERSION = 1
COMMAND_BATCHES_PER_AUTOMATIC_CHECKPOINT = 50

SNAP_WORKER_INFRASTRUCTURE_ERROR_CODES = frozenset(
    {
        "snap_worker_action_unsupported",
        "snap_worker_attestation_count_invalid",
        "snap_worker_attestation_count_mismatch",
        "snap_worker_bundle_hash_mismatch",
        "snap_worker_bundle_invalid",
        "snap_worker_bundle_missing",
        "snap_worker_evidence_hash_mismatch",
        "snap_worker_identity_mismatch",
        "snap_worker_internal_error",
        "snap_worker_manifest_invalid",
        "snap_worker_manifest_missing",
        "snap_worker_node_missing",
        "snap_worker_output_too_large",
        "snap_worker_process_failed",
        "snap_worker_protocol_mismatch",
        "snap_worker_request_invalid",
        "snap_worker_request_invalid_json",
        "snap_worker_request_too_large",
        "snap_worker_response_invalid",
        "snap_worker_response_too_large",
        "snap_worker_spawn_failed",
        "snap_worker_stderr_unexpected",
        "snap_worker_timeout",
        "snap_worker_unavailable",
    }
)

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
        "inverse_command_invalid",
        "inverse_command_mismatch",
        "inverse_round_trip_mismatch",
        "command_evidence_mismatch",
        "command_history_corrupt",
        "command_history_checkpoint_invalid",
        "command_history_checkpoint_missing",
        "command_history_checkpoint_identity_mismatch",
        "command_history_checkpoint_hash_mismatch",
        "journal_prefix_hash_mismatch",
        "command_history_entry_missing",
        "command_history_entry_hash_mismatch",
        "command_target_invalid",
        "command_target_missing",
        "command_index_invalid",
        "command_property_invalid",
        "command_new_key_duplicate",
        "command_entity_id_conflict",
        "draft_corrupt",
        "checkpoint_missing",
        "runtime_session_corrupt",
        "runtime_checkpoint_missing",
        "runtime_replay_sequence_gap",
        "runtime_replay_state_hash_mismatch",
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

RETRYABLE_ERROR_CODES = (
    frozenset(
        {
            "draft_conflict",
            "command_history_conflict",
            "operation_in_progress",
            "prototype_busy",
            "object_write_failed",
            "checkpoint_required_unavailable",
            "operation_evidence_unavailable",
            "runtime_session_conflict",
            "runtime_checkpoint_required_unavailable",
            "runtime_worker_timeout",
            "runtime_worker_spawn_failed",
            "operation_outcome_unknown",
        }
    )
    | SNAP_WORKER_INFRASTRUCTURE_ERROR_CODES
)


class StructuredPrototypePersistence(Protocol):
    async def create_operation(
        self,
        operation: PrototypeOperation,
        initial_event: PrototypeOperationEvent,
    ) -> PrototypeOperationCreateResult: ...

    async def load_operation(self, operation_id: str) -> PrototypeOperation | None: ...

    async def load_operation_by_request(
        self,
        project_id: str,
        operation_kind: PrototypeOperationKind,
        client_request_id: str,
    ) -> PrototypeOperation | None: ...

    async def load_operation_observability(
        self,
        operation_id: str,
    ) -> PrototypeOperationObservabilitySnapshot | None: ...

    async def record_operation_transition(
        self,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        event: PrototypeOperationEvent,
    ) -> None: ...

    async def register_replay_manifest_and_transition(
        self,
        *,
        replay_descriptor: PrototypeObjectDescriptor,
        replay_reference: PrototypeObjectReference,
        completed_operation: PrototypeOperation,
        completion_step: PrototypeOperationStep,
        completion_event: PrototypeOperationEvent,
    ) -> None: ...

    async def create_document_with_initial_checkpoint(
        self,
        *,
        descriptor: PrototypeObjectDescriptor,
        reference: PrototypeObjectReference,
        history_descriptor: PrototypeObjectDescriptor,
        history_reference: PrototypeObjectReference,
        history_checkpoint: PrototypeCommandHistoryCheckpoint,
        replay_descriptor: PrototypeObjectDescriptor,
        replay_reference: PrototypeObjectReference,
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

    async def delete_project_prototype(
        self,
        *,
        project_id: str,
        deletion_operation_id: str,
        completed_operation: PrototypeOperation,
        completion_step: PrototypeOperationStep,
        completion_event: PrototypeOperationEvent,
        replay_descriptor: PrototypeObjectDescriptor,
        replay_reference: PrototypeObjectReference,
    ) -> PrototypeProjectDeletionCounts: ...

    async def load_command_batch_by_request(
        self,
        draft_id: str,
        client_request_id: str,
    ) -> PrototypeCommandBatchRecord | None: ...

    async def load_command_batch(
        self,
        draft_id: str,
        batch_id: str,
    ) -> PrototypeCommandBatchRecord | None: ...

    async def append_command_batch(
        self,
        *,
        batch: PrototypeCommandBatchRecord,
        base_history_checkpoint: PrototypeCommandHistoryCheckpoint,
        base_tail_batches: tuple[PrototypeCommandBatchRecord, ...],
        base_journal_prefix_hash: str,
        replay_descriptor: PrototypeObjectDescriptor,
        replay_reference: PrototypeObjectReference,
        completed_operation: PrototypeOperation,
        completion_step: PrototypeOperationStep,
        completion_event: PrototypeOperationEvent,
    ) -> PrototypeCommandAppendResult: ...

    async def register_draft_checkpoint(
        self,
        *,
        descriptor: PrototypeObjectDescriptor,
        reference: PrototypeObjectReference,
        history_descriptor: PrototypeObjectDescriptor,
        history_reference: PrototypeObjectReference,
        history_checkpoint: PrototypeCommandHistoryCheckpoint,
        checkpoint: PrototypeCheckpointRecord,
        replay_descriptor: PrototypeObjectDescriptor,
        replay_reference: PrototypeObjectReference,
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

    async def list_object_references(
        self,
        project_id: str,
        owner_kind: str,
        owner_id: str,
    ) -> list[PrototypeObjectReference]: ...

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
        replay_descriptor: PrototypeObjectDescriptor,
        replay_reference: PrototypeObjectReference,
        session: PrototypeRuntimeSessionRecord,
        checkpoint: PrototypeRuntimeCheckpointRecord,
        completed_operation: PrototypeOperation,
        completion_step: PrototypeOperationStep,
        completion_event: PrototypeOperationEvent,
    ) -> None: ...

    async def reset_runtime_session(
        self,
        *,
        expected_old_status: PrototypeRuntimeSessionStatus,
        expected_old_latest_checkpoint_id: str | None,
        expected_old_head_sequence_no: int,
        expected_old_state_hash: str,
        expected_old_view_model_hash: str,
        expected_old_runtime_core_bundle_hash: str,
        target_draft_id: str,
        expected_target_head_sequence_no: int,
        expected_target_document_hash: str,
        state_descriptor: PrototypeObjectDescriptor,
        state_reference: PrototypeObjectReference,
        reset_manifest_descriptor: PrototypeObjectDescriptor,
        old_reset_reference: PrototypeObjectReference,
        new_reset_reference: PrototypeObjectReference,
        replay_descriptor: PrototypeObjectDescriptor,
        replay_reference: PrototypeObjectReference,
        session: PrototypeRuntimeSessionRecord,
        checkpoint: PrototypeRuntimeCheckpointRecord,
        completed_operation: PrototypeOperation,
        completion_step: PrototypeOperationStep,
        completion_event: PrototypeOperationEvent,
    ) -> PrototypeRuntimeSessionRecord: ...

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
        active_history_descriptor: PrototypeObjectDescriptor,
        active_history_reference: PrototypeObjectReference,
        active_history_checkpoint: PrototypeCommandHistoryCheckpoint,
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
        replay_descriptor: PrototypeObjectDescriptor,
        replay_reference: PrototypeObjectReference,
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
        replay_descriptor: PrototypeObjectDescriptor,
        replay_reference: PrototypeObjectReference,
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


class PrototypeSnapAttestation(Protocol):
    identity: PrototypeSnapWorkerIdentity

    async def attest(
        self,
        *,
        request_id: str,
        evidence_json: str,
    ) -> PrototypeSnapWorkerAttestationResult: ...

    async def attest_many(
        self,
        *,
        request_id: str,
        evidence_jsons: list[str],
    ) -> tuple[PrototypeSnapWorkerAttestationResult, ...]: ...


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
        current_view_model_hash: str | None = None,
        runtime_core_bundle_hash: str | None = None,
        resource_url: str | None = None,
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
        self.current_view_model_hash = current_view_model_hash
        self.runtime_core_bundle_hash = runtime_core_bundle_hash
        self.resource_url = resource_url


@dataclass(frozen=True, slots=True)
class ActivePrototypeState:
    document_record: PrototypeDocumentRecord
    draft: PrototypeDraftRecord
    document: PrototypeDocumentV1
    loaded_checkpoint_id: str
    loaded_checkpoint_sequence_no: int
    applied_tail_batch_ids: tuple[str, ...]
    command_history: PrototypeCommandHistory
    history_checkpoint: PrototypeCommandHistoryCheckpoint
    journal_prefix_hash: str
    validated_tail_batches: tuple[PrototypeCommandBatchRecord, ...]


@dataclass(frozen=True, slots=True)
class PrototypeCommandHistoryCheckpointArtifact:
    checkpoint: PrototypeCommandHistoryCheckpoint
    descriptor: PrototypeObjectDescriptor
    reference: PrototypeObjectReference


@dataclass(frozen=True, slots=True)
class PrototypeReplayManifestArtifact:
    manifest: PrototypeReplayManifestV1
    descriptor: PrototypeObjectDescriptor
    reference: PrototypeObjectReference


@dataclass(frozen=True, slots=True)
class PrototypeOperationDetail:
    snapshot: PrototypeOperationObservabilitySnapshot
    replay_manifest: PrototypeReplayManifestV1 | None


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
class DeleteStructuredPrototypeResult:
    operation_id: str
    correlation_id: str
    deleted: bool


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
class ResetPrototypeRuntimeSessionResult:
    operation_id: str
    correlation_id: str
    reset_manifest_hash: str
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


def _require_operation_id(value: str) -> None:
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise StructuredPrototypeServiceError(
            "operation_id_invalid",
            "prototype operation ID must be a UUID",
        ) from exc
    if str(parsed) != value:
        raise StructuredPrototypeServiceError(
            "operation_id_invalid",
            "prototype operation ID must use canonical lowercase UUID form",
        )


def _require_runtime_reset_cause_id(value: str) -> None:
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise StructuredPrototypeServiceError(
            "runtime_reset_cause_invalid",
            "prototype runtime reset cause operation ID must be a UUID",
        ) from exc
    if str(parsed) != value:
        raise StructuredPrototypeServiceError(
            "runtime_reset_cause_invalid",
            "prototype runtime reset cause operation ID must use canonical lowercase UUID form",
        )


class StructuredPrototypeService:
    def __init__(
        self,
        *,
        store: StructuredPrototypePersistence,
        object_store: PrototypeObjectStorage,
        snap_attester: PrototypeSnapAttestation | None = None,
        runtime_worker: PrototypeRuntimeExecution | None = None,
        renderer_worker: PrototypeRendererExecution | None = None,
        artifact_store: PrototypeRenderArtifactStorage | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._store = store
        self._object_store = object_store
        self._snap_attester = snap_attester
        self._runtime_worker = runtime_worker
        self._renderer_worker = renderer_worker
        self._artifact_store = artifact_store
        self._clock = clock

    async def get_operation_outcome(
        self,
        *,
        project_id: str,
        operation_kind: PrototypeOperationKind,
        client_request_id: str,
    ) -> PrototypeOperation:
        _require_client_request_id(client_request_id)
        operation = await self._store.load_operation_by_request(
            project_id,
            operation_kind,
            client_request_id,
        )
        if operation is None:
            raise StructuredPrototypeServiceError(
                "operation_outcome_unknown",
                "structured prototype operation outcome is not recorded",
            )
        return operation

    async def get_operation_detail(
        self,
        operation_id: str,
    ) -> PrototypeOperationDetail:
        snapshot = await self._load_operation_observability_snapshot(operation_id)
        replay_manifest = await self._load_operation_replay_manifest(snapshot.operation)
        return PrototypeOperationDetail(
            snapshot=snapshot,
            replay_manifest=replay_manifest,
        )

    async def get_operation_events(
        self,
        operation_id: str,
    ) -> PrototypeOperationObservabilitySnapshot:
        return await self._load_operation_observability_snapshot(operation_id)

    async def _load_operation_observability_snapshot(
        self,
        operation_id: str,
    ) -> PrototypeOperationObservabilitySnapshot:
        _require_operation_id(operation_id)
        try:
            snapshot = await self._store.load_operation_observability(operation_id)
        except StructuredPrototypeStoreError as exc:
            raise StructuredPrototypeServiceError(
                "operation_observability_corrupt",
                "prototype operation observability records could not be read",
                operation_id=operation_id,
            ) from exc
        if snapshot is None:
            raise StructuredPrototypeServiceError(
                "operation_missing",
                "prototype operation is not recorded",
                operation_id=operation_id,
            )
        self._validate_operation_observability_snapshot(snapshot, operation_id)
        return snapshot

    @staticmethod
    def _validate_operation_observability_snapshot(
        snapshot: PrototypeOperationObservabilitySnapshot,
        requested_operation_id: str,
    ) -> None:
        operation = snapshot.operation

        def fail(message: str) -> None:
            raise StructuredPrototypeServiceError(
                "operation_observability_corrupt",
                message,
                operation_id=requested_operation_id,
            )

        def canonical_uuid(value: str) -> bool:
            try:
                return str(UUID(value)) == value
            except ValueError:
                return False

        if operation.id != requested_operation_id or not canonical_uuid(operation.id):
            fail("prototype operation snapshot identity is invalid")
        if not canonical_uuid(operation.client_request_id) or not canonical_uuid(
            operation.correlation_id
        ):
            fail("prototype operation request identity is invalid")
        if operation.parent_operation_id is not None and not canonical_uuid(
            operation.parent_operation_id
        ):
            fail("prototype operation parent identity is invalid")

        terminal = operation.status in {"succeeded", "failed", "interrupted", "cancelled"}
        if operation.status == "queued":
            if any(
                value is not None
                for value in (
                    operation.started_at,
                    operation.completed_at,
                    operation.result_manifest_hash,
                    operation.failure_evidence_hash,
                    operation.error_code,
                )
            ):
                fail("queued prototype operation has lifecycle or terminal evidence")
        elif operation.status == "running":
            if operation.started_at is None or any(
                value is not None
                for value in (
                    operation.completed_at,
                    operation.result_manifest_hash,
                    operation.failure_evidence_hash,
                    operation.error_code,
                )
            ):
                fail("running prototype operation has invalid lifecycle evidence")
        elif not terminal or operation.completed_at is None:
            fail("terminal prototype operation has no completion timestamp")

        if operation.status == "succeeded" and (
            operation.result_manifest_hash is None
            or operation.failure_evidence_hash is not None
            or operation.error_code is not None
        ):
            fail("succeeded prototype operation has invalid replay evidence")
        if operation.status == "failed" and (
            operation.result_manifest_hash is not None
            or operation.failure_evidence_hash is None
            or operation.error_code is None
        ):
            fail("failed prototype operation has invalid failure evidence")
        if operation.status in {"interrupted", "cancelled"} and (
            operation.result_manifest_hash is not None or operation.error_code is None
        ):
            fail("interrupted prototype operation has invalid terminal evidence")
        if operation.started_at is not None and operation.started_at < operation.created_at:
            fail("prototype operation started before it was created")
        if operation.completed_at is not None:
            lower_bound = operation.started_at or operation.created_at
            if operation.completed_at < lower_bound:
                fail("prototype operation completed before its lifecycle began")

        step_ids: set[str] = set()
        step_keys: list[tuple[int, int]] = []
        for step in snapshot.steps:
            if (
                step.operation_id != operation.id
                or not canonical_uuid(step.id)
                or step.id in step_ids
            ):
                fail("prototype operation step identity is invalid")
            step_ids.add(step.id)
            step_keys.append((step.step_ordinal, step.attempt))
            if (step.completion_evidence_kind is None) != (step.completion_evidence_ref is None):
                fail("prototype operation step completion evidence is incomplete")
            if step.status == "pending":
                if any(
                    value is not None
                    for value in (
                        step.started_at,
                        step.completed_at,
                        step.output_manifest_hash,
                        step.completion_evidence_kind,
                        step.error_code,
                    )
                ):
                    fail("pending prototype operation step has lifecycle evidence")
            elif step.status == "running":
                if step.started_at is None or any(
                    value is not None
                    for value in (
                        step.completed_at,
                        step.output_manifest_hash,
                        step.completion_evidence_kind,
                        step.error_code,
                    )
                ):
                    fail("running prototype operation step has invalid lifecycle evidence")
            elif step.status == "succeeded":
                if (
                    step.started_at is None
                    or step.completed_at is None
                    or step.output_manifest_hash is None
                    or step.completion_evidence_kind is None
                    or step.error_code is not None
                ):
                    fail("succeeded prototype operation step has invalid completion evidence")
            elif step.status in {"failed", "interrupted"}:
                if (
                    step.started_at is None
                    or step.completed_at is None
                    or step.completion_evidence_kind is None
                    or step.error_code is None
                ):
                    fail("failed prototype operation step has invalid failure evidence")
            elif step.status == "skipped" and (
                step.completed_at is None
                or step.completion_evidence_kind is None
                or step.error_code is not None
            ):
                fail("skipped prototype operation step has invalid completion evidence")
            if (
                step.started_at is not None
                and step.completed_at is not None
                and step.completed_at < step.started_at
            ):
                fail("prototype operation step completed before it started")
        if step_keys != sorted(step_keys) or len(step_keys) != len(set(step_keys)):
            fail("prototype operation steps are not in stable unique order")
        for step in snapshot.steps:
            if step.parent_step_id is not None and step.parent_step_id not in step_ids:
                fail("prototype operation step parent is outside the operation")

        if not snapshot.events:
            fail("prototype operation has no durable event history")
        if tuple(event.event_no for event in snapshot.events) != tuple(range(len(snapshot.events))):
            fail("prototype operation event history is not gap-free")
        prior_occurred_at: datetime | None = None
        last_step_event_status: dict[str, str] = {}
        valid_event_statuses = {
            "queued",
            "pending",
            "running",
            "succeeded",
            "failed",
            "skipped",
            "interrupted",
            "cancelled",
        }
        for event in snapshot.events:
            if event.operation_id != operation.id:
                fail("prototype operation event belongs to another operation")
            if event.step_id is not None and event.step_id not in step_ids:
                fail("prototype operation event references an unknown step")
            if event.status not in valid_event_statuses:
                fail("prototype operation event status is unsupported")
            if prior_occurred_at is not None and event.occurred_at < prior_occurred_at:
                fail("prototype operation event timestamps are not monotonic")
            if event.step_id is not None:
                last_step_event_status[event.step_id] = event.status
            prior_occurred_at = event.occurred_at
        for step in snapshot.steps:
            if last_step_event_status.get(step.id) != step.status:
                fail("prototype operation step disagrees with its durable event history")
        if operation.status != "running" and snapshot.events[-1].status != operation.status:
            fail("prototype operation event history disagrees with current status")

        child_order: list[tuple[datetime, str]] = []
        child_ids: set[str] = set()
        for child in snapshot.child_operations:
            if (
                child.parent_operation_id != operation.id
                or child.project_id != operation.project_id
                or not canonical_uuid(child.id)
                or child.id in child_ids
            ):
                fail("prototype child operation identity is invalid")
            child_ids.add(child.id)
            child_order.append((child.created_at, child.id))
        if child_order != sorted(child_order):
            fail("prototype child operations are not in stable order")

    async def _load_operation_replay_manifest(
        self,
        operation: PrototypeOperation,
    ) -> PrototypeReplayManifestV1 | None:
        if operation.status != "succeeded":
            return None
        result_manifest_hash = operation.result_manifest_hash
        if result_manifest_hash is None:
            raise StructuredPrototypeServiceError(
                "operation_observability_corrupt",
                "succeeded prototype operation has no replay manifest hash",
                operation_id=operation.id,
            )
        try:
            descriptor = await self._store.load_object(operation.project_id, result_manifest_hash)
            references = await self._store.list_object_references(
                operation.project_id,
                "replay_manifest",
                operation.id,
            )
        except StructuredPrototypeStoreError as exc:
            raise StructuredPrototypeServiceError(
                "operation_observability_corrupt",
                "prototype operation replay manifest records could not be read",
                operation_id=operation.id,
            ) from exc
        if descriptor is None:
            raise StructuredPrototypeServiceError(
                "operation_replay_manifest_missing",
                "prototype operation replay manifest object is missing",
                operation_id=operation.id,
            )
        if (
            descriptor.project_id != operation.project_id
            or descriptor.content_hash != result_manifest_hash
            or len(references) != 1
        ):
            raise StructuredPrototypeServiceError(
                "operation_replay_reference_invalid",
                "prototype operation replay manifest reference is invalid",
                operation_id=operation.id,
            )
        reference = references[0]
        if (
            reference.project_id != operation.project_id
            or reference.owner_kind != "replay_manifest"
            or reference.owner_id != operation.id
            or reference.role not in {"operation-replay-manifest", "publish-replay-manifest"}
            or reference.content_hash != result_manifest_hash
            or reference.payload_type != "replay_manifest"
            or reference.schema_version != REPLAY_MANIFEST_SCHEMA_VERSION
        ):
            raise StructuredPrototypeServiceError(
                "operation_replay_reference_invalid",
                "prototype operation replay manifest ownership is invalid",
                operation_id=operation.id,
            )
        try:
            canonical_bytes = await asyncio.to_thread(
                self._object_store.read_canonical_bytes,
                descriptor,
            )
            manifest = PrototypeReplayManifestV1.from_canonical_json(canonical_bytes)
        except (PrototypeObjectStoreError, PrototypeReplayManifestError) as exc:
            raise StructuredPrototypeServiceError(
                "operation_replay_manifest_invalid",
                "prototype operation replay manifest failed strict read-back validation",
                operation_id=operation.id,
            ) from exc
        actual_hash = f"sha256:{hashlib.sha256(canonical_bytes).hexdigest()}"
        if actual_hash != result_manifest_hash:
            raise StructuredPrototypeServiceError(
                "operation_replay_manifest_invalid",
                "prototype operation replay manifest hash does not match its operation",
                operation_id=operation.id,
            )
        if (
            manifest.operation_id != operation.id
            or manifest.operation_kind != operation.operation_kind
            or manifest.parent_operation_id != operation.parent_operation_id
            or manifest.request_manifest_hash != operation.request_manifest_hash
        ):
            raise StructuredPrototypeServiceError(
                "operation_replay_manifest_invalid",
                "prototype operation replay manifest identity does not match its operation",
                operation_id=operation.id,
            )
        return manifest

    async def materialize_command_history_checkpoint(
        self,
        *,
        project_id: str,
        checkpoint_id: str,
        draft_id: str,
        checkpoint_sequence_no: int,
        checkpoint_document_hash: str,
        journal_prefix_hash: str,
        history: PrototypeCommandHistory,
        created_at: datetime,
    ) -> PrototypeCommandHistoryCheckpointArtifact:
        snapshot = CommandHistoryCheckpointV1(
            schema_version=COMMAND_HISTORY_CHECKPOINT_SCHEMA_VERSION,
            draft_id=draft_id,
            checkpoint_sequence_no=checkpoint_sequence_no,
            checkpoint_document_hash=checkpoint_document_hash,
            journal_prefix_hash=journal_prefix_hash,
            undo_stack=[
                CommandHistoryEntryV1(
                    batch_id=entry.batch_id,
                    envelope_hash=entry.command_batch_hash,
                )
                for entry in history.undo_stack
            ],
            redo_stack=[
                CommandHistoryEntryV1(
                    batch_id=entry.batch_id,
                    envelope_hash=entry.command_batch_hash,
                )
                for entry in history.redo_stack
            ],
        )
        descriptor = await asyncio.to_thread(
            self._object_store.write_json,
            project_id,
            command_history_checkpoint_payload(snapshot),
        )
        canonical_bytes = await asyncio.to_thread(
            self._object_store.read_canonical_bytes,
            descriptor,
        )
        parsed = parse_command_history_checkpoint_json(canonical_bytes)
        if canonical_command_history_checkpoint_json(parsed).encode("utf-8") != canonical_bytes:
            raise StructuredPrototypeContractError(
                "command_history_checkpoint_hash_mismatch",
                "prototype command history checkpoint is not canonical after read-back",
            )
        checkpoint = command_history_checkpoint_to_domain(
            parsed,
            snapshot_object_hash=descriptor.content_hash,
        )
        return PrototypeCommandHistoryCheckpointArtifact(
            checkpoint=checkpoint,
            descriptor=descriptor,
            reference=PrototypeObjectReference(
                project_id=project_id,
                owner_kind="checkpoint",
                owner_id=checkpoint_id,
                role="command-history-checkpoint",
                content_hash=descriptor.content_hash,
                payload_type="prototype_command_history_checkpoint",
                schema_version=COMMAND_HISTORY_CHECKPOINT_SCHEMA_VERSION,
                created_at=created_at,
            ),
        )

    async def _write_replay_manifest(
        self,
        *,
        operation: PrototypeOperation,
        created_at: datetime,
        ordered_input_object_hashes: tuple[str, ...],
        ordered_command_batch_hashes: tuple[str, ...] = (),
        base_checkpoint_hash: str | None = None,
        base_sequence_no: int | None = None,
        result_checkpoint_hash: str | None = None,
        result_sequence_no: int | None = None,
        runtime_session_id: str | None = None,
        runtime_identity: PrototypeRuntimeWorkerIdentity | None = None,
        ordered_runtime_event_hashes: tuple[str, ...] = (),
        runtime_final_state_hash: str | None = None,
        runtime_final_view_model_hash: str | None = None,
        validation_report_hashes: tuple[str, ...] = (),
    ) -> PrototypeReplayManifestArtifact:
        versions = PrototypeReplayManifestVersionsV1(
            service_version=SERVICE_VERSION,
            document_schema_version=DOCUMENT_SCHEMA_VERSION,
            command_contract_version=COMMAND_CONTRACT_VERSION,
            runtime_state_schema_version=RUNTIME_STATE_SCHEMA_VERSION,
            runtime_event_contract_version=RUNTIME_EVENT_CONTRACT_VERSION,
            runtime_core_version=(
                runtime_identity.runtime_core_version if runtime_identity is not None else None
            ),
            runtime_core_bundle_hash=(
                runtime_identity.runtime_core_bundle_hash if runtime_identity is not None else None
            ),
            state_machine_kernel_version=(
                runtime_identity.state_machine_kernel_version
                if runtime_identity is not None
                else None
            ),
            renderer_version=None,
            renderer_environment_version=None,
        )
        manifest = PrototypeReplayManifestV1(
            operation_id=operation.id,
            operation_kind=operation.operation_kind,
            parent_operation_id=operation.parent_operation_id,
            request_manifest_hash=operation.request_manifest_hash,
            context_manifest_hash=None,
            ordered_input_object_hashes=ordered_input_object_hashes,
            versions=versions,
            agent_task_identity=None,
            submission_hash=None,
            ordered_command_batch_hashes=ordered_command_batch_hashes,
            base_checkpoint_hash=base_checkpoint_hash,
            base_sequence_no=base_sequence_no,
            result_checkpoint_hash=result_checkpoint_hash,
            result_sequence_no=result_sequence_no,
            renderer_input_hash=None,
            renderer_output_hash=None,
            runtime_session_id=runtime_session_id,
            runtime_core_bundle_hash=versions.runtime_core_bundle_hash,
            ordered_runtime_event_hashes=ordered_runtime_event_hashes,
            runtime_final_state_hash=runtime_final_state_hash,
            runtime_final_view_model_hash=runtime_final_view_model_hash,
            validation_report_hashes=validation_report_hashes,
            terminal_status="succeeded",
            error_code=None,
        )
        descriptor = await asyncio.to_thread(
            self._object_store.write_json,
            operation.project_id,
            manifest.to_payload(),
        )
        canonical_bytes = await asyncio.to_thread(
            self._object_store.read_canonical_bytes,
            descriptor,
        )
        try:
            read_back = PrototypeReplayManifestV1.from_canonical_json(canonical_bytes)
        except PrototypeReplayManifestError as exc:
            raise StructuredPrototypeServiceError(
                "replay_manifest_readback_invalid",
                "prototype replay manifest failed strict read-back validation",
                operation_id=operation.id,
            ) from exc
        if read_back != manifest or read_back.to_payload() != manifest.to_payload():
            raise StructuredPrototypeServiceError(
                "replay_manifest_readback_invalid",
                "prototype replay manifest changed during durable read-back",
                operation_id=operation.id,
            )
        return PrototypeReplayManifestArtifact(
            manifest=manifest,
            descriptor=descriptor,
            reference=PrototypeObjectReference(
                project_id=operation.project_id,
                owner_kind="replay_manifest",
                owner_id=operation.id,
                role="operation-replay-manifest",
                content_hash=descriptor.content_hash,
                payload_type="replay_manifest",
                schema_version=REPLAY_MANIFEST_SCHEMA_VERSION,
                created_at=created_at,
            ),
        )

    async def ensure_mutation_checkpoint(
        self,
        *,
        state: ActivePrototypeState,
        client_request_id: str,
    ) -> ActivePrototypeState:
        if len(state.validated_tail_batches) < COMMAND_BATCHES_PER_AUTOMATIC_CHECKPOINT:
            return state
        if state.draft.head_sequence_no - state.loaded_checkpoint_sequence_no != len(
            state.validated_tail_batches
        ):
            raise StructuredPrototypeServiceError(
                "command_history_corrupt",
                "prototype validated command tail does not match the draft head",
                current_head_sequence_no=state.draft.head_sequence_no,
                current_document_hash=state.draft.head_document_hash,
            )
        checkpoint_request_id = _stable_id(
            client_request_id,
            state.draft.id,
            str(state.draft.head_sequence_no),
            state.draft.head_document_hash,
            "automatic-mutation-checkpoint",
        )
        try:
            checkpointed = await self._checkpoint_recovered_state(
                state=state,
                client_request_id=checkpoint_request_id,
            )
        except StructuredPrototypeServiceError as exc:
            if exc.code in CORRUPTION_ERROR_CODES:
                raise
            raise StructuredPrototypeServiceError(
                "checkpoint_required_unavailable",
                "prototype mutation requires a durable history checkpoint",
                operation_id=exc.operation_id,
                current_head_sequence_no=state.draft.head_sequence_no,
                current_document_hash=state.draft.head_document_hash,
            ) from exc
        return checkpointed.state

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
            command_history = PrototypeCommandHistory(undo_stack=(), redo_stack=())
            journal_prefix_hash = initial_journal_prefix_hash(draft_id=draft_id)
            history_artifact = await self.materialize_command_history_checkpoint(
                project_id=project_id,
                checkpoint_id=checkpoint_id,
                draft_id=draft_id,
                checkpoint_sequence_no=0,
                checkpoint_document_hash=materialized_hash,
                journal_prefix_hash=journal_prefix_hash,
                history=command_history,
                created_at=now,
            )
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
                history_snapshot_object_hash=history_artifact.descriptor.content_hash,
                history_snapshot_schema_version=COMMAND_HISTORY_CHECKPOINT_SCHEMA_VERSION,
                journal_prefix_hash=journal_prefix_hash,
                created_by_operation_id=operation.id,
                created_at=now,
            )
            replay_artifact = await self._write_replay_manifest(
                operation=operation,
                created_at=now,
                ordered_input_object_hashes=(
                    descriptor.content_hash,
                    history_artifact.descriptor.content_hash,
                ),
                base_checkpoint_hash=None,
                base_sequence_no=None,
                result_checkpoint_hash=checkpoint.document_hash,
                result_sequence_no=checkpoint.checkpoint_sequence_no,
            )
            completed, completed_step, event = self._succeed_operation(
                running,
                step,
                result_hash=replay_artifact.descriptor.content_hash,
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
                history_descriptor=history_artifact.descriptor,
                history_reference=history_artifact.reference,
                history_checkpoint=history_artifact.checkpoint,
                replay_descriptor=replay_artifact.descriptor,
                replay_reference=replay_artifact.reference,
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
        except StructuredPrototypeContractError as exc:
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
            command_history=command_history,
            history_checkpoint=history_artifact.checkpoint,
            journal_prefix_hash=journal_prefix_hash,
            validated_tail_batches=(),
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

    async def delete_project_prototype(
        self,
        *,
        project_id: str,
        client_request_id: str,
    ) -> DeleteStructuredPrototypeResult:
        _require_client_request_id(client_request_id)
        request_hash = _manifest_hash(
            {
                "kind": "delete_project_prototype",
                "projectId": project_id,
                "clientRequestId": client_request_id,
            }
        )
        operation = self._queued_operation(
            operation_kind="delete_project_prototype",
            project_id=project_id,
            resource_kind="project_prototype",
            resource_id=project_id,
            client_request_id=client_request_id,
            request_manifest_hash=request_hash,
        )
        created = await self._create_operation(operation)
        if not created.created:
            if created.operation.status == "succeeded":
                return DeleteStructuredPrototypeResult(
                    operation_id=created.operation.id,
                    correlation_id=created.operation.correlation_id,
                    deleted=True,
                )
            raise self._existing_operation_error(created.operation)

        running, step = await self._start_operation(operation, "delete_project_prototype")
        try:
            replay_artifact = await self._write_replay_manifest(
                operation=operation,
                created_at=self._now(),
                ordered_input_object_hashes=(),
            )
            completed, completed_step, event = self._succeed_operation(
                running,
                step,
                result_hash=replay_artifact.descriptor.content_hash,
                evidence_kind="project_prototype_deleted",
                evidence_ref=project_id,
            )
            await self._store.delete_project_prototype(
                project_id=project_id,
                deletion_operation_id=operation.id,
                completed_operation=completed,
                completion_step=completed_step,
                completion_event=event,
                replay_descriptor=replay_artifact.descriptor,
                replay_reference=replay_artifact.reference,
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
        return DeleteStructuredPrototypeResult(
            operation_id=operation.id,
            correlation_id=operation.correlation_id,
            deleted=True,
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
            replay_artifact = await self._write_replay_manifest(
                operation=operation,
                created_at=self._now(),
                ordered_input_object_hashes=(
                    state.history_checkpoint.checkpoint_document_hash,
                    state.history_checkpoint.snapshot_object_hash,
                ),
                ordered_command_batch_hashes=tuple(
                    batch.command_batch_hash for batch in state.validated_tail_batches
                ),
                base_checkpoint_hash=state.history_checkpoint.checkpoint_document_hash,
                base_sequence_no=state.history_checkpoint.checkpoint_sequence_no,
                result_sequence_no=state.draft.head_sequence_no,
            )
            completed, completed_step, event = self._succeed_operation(
                running,
                step,
                result_hash=replay_artifact.descriptor.content_hash,
                evidence_kind="replay_document_hash",
                evidence_ref=state.draft.head_document_hash,
            )
            await self._store.register_replay_manifest_and_transition(
                replay_descriptor=replay_artifact.descriptor,
                replay_reference=replay_artifact.reference,
                completed_operation=completed,
                completion_step=completed_step,
                completion_event=event,
            )
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
        canonical_batch_json = canonical_model_json(batch)
        canonical_batch = parse_command_batch_json(canonical_batch_json)
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
        state = await self.ensure_mutation_checkpoint(
            state=recovered.state,
            client_request_id=client_request_id,
        )
        request_hash = _manifest_hash(
            {
                "kind": "apply_command_batch",
                "draftId": draft_id,
                "clientRequestId": client_request_id,
                "expectedHeadSequenceNo": expected_head_sequence_no,
                "expectedDocumentHash": expected_document_hash,
                "commandBatchHash": command_batch_hash(canonical_batch),
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
        snap_attestation: PrototypeSnapWorkerAttestationResult | None = None
        try:
            validate_command_batch_evidence_context(
                state.document,
                canonical_batch,
                draft_id=draft_id,
                base_head_sequence_no=expected_head_sequence_no,
                base_document_hash=expected_document_hash,
            )
            if canonical_batch.evidence is not None:
                snap_attestation = await self._attest_snap_evidence(
                    request_id=_stable_id(operation.id, "snap-attest"),
                    evidence_json=canonical_model_json(canonical_batch.evidence),
                )
            execution = execute_command_batch(
                state.document,
                canonical_batch,
                draft_id=draft_id,
                client_request_id=client_request_id,
            )
            now = self._now()
            batch_id = _stable_id(operation.id, "command-batch")
            inverse_commands_json = canonical_model_json(execution.inverse_commands)
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
                commands_json=canonical_batch_json,
                inverse_commands_json=inverse_commands_json,
                command_batch_hash=command_batch_envelope_hash(
                    draft_id=draft_id,
                    base_sequence_no=expected_head_sequence_no,
                    result_sequence_no=expected_head_sequence_no + 1,
                    origin=origin,
                    operation_kind="forward",
                    target_batch_id=None,
                    commands=canonical_batch,
                    inverse_commands=execution.inverse_commands,
                ),
                base_document_hash=execution.base_document_hash,
                result_document_hash=execution.result_document_hash,
                operation_id=operation.id,
                created_at=now,
            )
            result_prefix_hash = advance_journal_prefix_hash(
                previous_prefix_hash=state.journal_prefix_hash,
                batch_id=batch_record.id,
                base_sequence_no=batch_record.base_sequence_no,
                result_sequence_no=batch_record.result_sequence_no,
                command_batch_hash=batch_record.command_batch_hash,
                base_document_hash=batch_record.base_document_hash,
                result_document_hash=batch_record.result_document_hash,
            )
            replay_artifact = await self._write_replay_manifest(
                operation=operation,
                created_at=now,
                ordered_input_object_hashes=(
                    state.draft.head_document_hash,
                    state.history_checkpoint.snapshot_object_hash,
                ),
                ordered_command_batch_hashes=(batch_record.command_batch_hash,),
                base_checkpoint_hash=state.history_checkpoint.checkpoint_document_hash,
                base_sequence_no=batch_record.base_sequence_no,
                result_checkpoint_hash=None,
                result_sequence_no=batch_record.result_sequence_no,
                validation_report_hashes=(
                    (snap_attestation.evidence_hash,) if snap_attestation is not None else ()
                ),
            )
            completed, completed_step, event = self._succeed_operation(
                running,
                step,
                result_hash=replay_artifact.descriptor.content_hash,
                evidence_kind="command_batch",
                evidence_ref=batch_id,
            )
            appended = await self._store.append_command_batch(
                batch=batch_record,
                base_history_checkpoint=state.history_checkpoint,
                base_tail_batches=state.validated_tail_batches,
                base_journal_prefix_hash=state.journal_prefix_hash,
                replay_descriptor=replay_artifact.descriptor,
                replay_reference=replay_artifact.reference,
                completed_operation=completed,
                completion_step=completed_step,
                completion_event=event,
            )
        except StructuredPrototypeContractError as exc:
            await self._fail_operation(running, step, exc.code)
            raise self._service_error(exc.code, str(exc), operation.id, state.draft) from exc
        except StructuredPrototypeServiceError as exc:
            await self._fail_operation(running, step, exc.code)
            raise
        except StructuredPrototypeStoreError as exc:
            if exc.code in CORRUPTION_ERROR_CODES:
                await self._handle_recovery_failure(running, step, state.draft, exc.code)
            else:
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
            command_history=advance_prototype_command_history(
                state.command_history,
                appended.batch,
            ),
            history_checkpoint=state.history_checkpoint,
            journal_prefix_hash=result_prefix_hash,
            validated_tail_batches=(*state.validated_tail_batches, appended.batch),
        )
        return ApplyStructuredPrototypeCommandsResult(
            operation_id=operation.id,
            correlation_id=operation.correlation_id,
            applied_batch_id=appended.batch.id,
            allocated_entity_ids=execution.allocated_entity_ids,
            affected_entity_ids=execution.affected_entity_ids,
            state=updated_state,
        )

    async def undo(
        self,
        *,
        draft_id: str,
        client_request_id: str,
        expected_head_sequence_no: int,
        expected_document_hash: str,
    ) -> ApplyStructuredPrototypeCommandsResult:
        return await self._apply_history_command(
            operation_kind="undo",
            draft_id=draft_id,
            client_request_id=client_request_id,
            expected_head_sequence_no=expected_head_sequence_no,
            expected_document_hash=expected_document_hash,
        )

    async def redo(
        self,
        *,
        draft_id: str,
        client_request_id: str,
        expected_head_sequence_no: int,
        expected_document_hash: str,
    ) -> ApplyStructuredPrototypeCommandsResult:
        return await self._apply_history_command(
            operation_kind="redo",
            draft_id=draft_id,
            client_request_id=client_request_id,
            expected_head_sequence_no=expected_head_sequence_no,
            expected_document_hash=expected_document_hash,
        )

    async def _apply_history_command(
        self,
        *,
        operation_kind: Literal["undo", "redo"],
        draft_id: str,
        client_request_id: str,
        expected_head_sequence_no: int,
        expected_document_hash: str,
    ) -> ApplyStructuredPrototypeCommandsResult:
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
                f"pre-{operation_kind}-recovery",
            ),
        )
        state = await self.ensure_mutation_checkpoint(
            state=recovered.state,
            client_request_id=client_request_id,
        )
        request_hash = _manifest_hash(
            {
                "kind": operation_kind,
                "draftId": draft_id,
                "clientRequestId": client_request_id,
                "expectedHeadSequenceNo": expected_head_sequence_no,
                "expectedDocumentHash": expected_document_hash,
            }
        )
        operation = self._queued_operation(
            operation_kind=operation_kind,
            project_id=state.document_record.project_id,
            resource_kind="draft",
            resource_id=draft_id,
            client_request_id=client_request_id,
            request_manifest_hash=request_hash,
        )
        created = await self._create_operation(operation)
        if not created.created:
            return await self._resolve_existing_apply(
                created.operation,
                state,
                expected_batch_kind=operation_kind,
            )
        running, step = await self._start_operation(
            operation,
            f"commit_{operation_kind}_command_batch",
        )
        if (
            state.draft.head_sequence_no != expected_head_sequence_no
            or state.draft.head_document_hash != expected_document_hash
        ):
            await self._fail_operation(running, step, "draft_conflict")
            raise StructuredPrototypeServiceError(
                "draft_conflict",
                "prototype history command base does not match the current draft head",
                operation_id=operation.id,
                current_head_sequence_no=state.draft.head_sequence_no,
                current_document_hash=state.draft.head_document_hash,
            )
        stack = (
            state.command_history.undo_stack
            if operation_kind == "undo"
            else state.command_history.redo_stack
        )
        if not stack:
            error_code = f"{operation_kind}_unavailable"
            await self._fail_operation(running, step, error_code)
            raise StructuredPrototypeServiceError(
                error_code,
                f"prototype draft has no command available to {operation_kind}",
                operation_id=operation.id,
                current_head_sequence_no=state.draft.head_sequence_no,
                current_document_hash=state.draft.head_document_hash,
            )
        target_entry = stack[-1]
        try:
            target = next(
                (
                    stored
                    for stored in reversed(state.validated_tail_batches)
                    if stored.id == target_entry.batch_id
                ),
                None,
            )
            if target is None:
                target = await self._load_verified_history_target(
                    draft_id=draft_id,
                    entry=target_entry,
                )
            else:
                self._validate_history_target(target, target_entry)
            commands = parse_inverse_command_batch_json(target.inverse_commands_json)
            execution = execute_inverse_command_batch(state.document, commands)
            if (
                execution.base_document_hash != target.result_document_hash
                or execution.result_document_hash != target.base_document_hash
            ):
                raise StructuredPrototypeContractError(
                    "command_history_corrupt",
                    "prototype history target does not invert the current document hash",
                )
            now = self._now()
            batch_id = _stable_id(operation.id, "command-batch")
            inverse_commands_json = canonical_model_json(execution.inverse_commands)
            batch_record = PrototypeCommandBatchRecord(
                id=batch_id,
                draft_id=draft_id,
                base_sequence_no=expected_head_sequence_no,
                result_sequence_no=expected_head_sequence_no + 1,
                client_request_id=client_request_id,
                origin="user",
                operation_kind=operation_kind,
                target_batch_id=target.id,
                command_contract_version=COMMAND_CONTRACT_VERSION,
                commands_json=target.inverse_commands_json,
                inverse_commands_json=inverse_commands_json,
                command_batch_hash=command_batch_envelope_hash(
                    draft_id=draft_id,
                    base_sequence_no=expected_head_sequence_no,
                    result_sequence_no=expected_head_sequence_no + 1,
                    origin="user",
                    operation_kind=operation_kind,
                    target_batch_id=target.id,
                    commands=commands,
                    inverse_commands=execution.inverse_commands,
                ),
                base_document_hash=execution.base_document_hash,
                result_document_hash=execution.result_document_hash,
                operation_id=operation.id,
                created_at=now,
            )
            result_prefix_hash = advance_journal_prefix_hash(
                previous_prefix_hash=state.journal_prefix_hash,
                batch_id=batch_record.id,
                base_sequence_no=batch_record.base_sequence_no,
                result_sequence_no=batch_record.result_sequence_no,
                command_batch_hash=batch_record.command_batch_hash,
                base_document_hash=batch_record.base_document_hash,
                result_document_hash=batch_record.result_document_hash,
            )
            next_history = advance_prototype_command_history(
                state.command_history,
                batch_record,
            )
            replay_artifact = await self._write_replay_manifest(
                operation=operation,
                created_at=now,
                ordered_input_object_hashes=(
                    state.draft.head_document_hash,
                    state.history_checkpoint.snapshot_object_hash,
                ),
                ordered_command_batch_hashes=(batch_record.command_batch_hash,),
                base_checkpoint_hash=state.history_checkpoint.checkpoint_document_hash,
                base_sequence_no=batch_record.base_sequence_no,
                result_checkpoint_hash=None,
                result_sequence_no=batch_record.result_sequence_no,
            )
            completed, completed_step, event = self._succeed_operation(
                running,
                step,
                result_hash=replay_artifact.descriptor.content_hash,
                evidence_kind="command_batch",
                evidence_ref=batch_id,
            )
            appended = await self._store.append_command_batch(
                batch=batch_record,
                base_history_checkpoint=state.history_checkpoint,
                base_tail_batches=state.validated_tail_batches,
                base_journal_prefix_hash=state.journal_prefix_hash,
                replay_descriptor=replay_artifact.descriptor,
                replay_reference=replay_artifact.reference,
                completed_operation=completed,
                completion_step=completed_step,
                completion_event=event,
            )
        except (StructuredPrototypeContractError, PrototypeCommandHistoryError) as exc:
            await self._handle_recovery_failure(
                running,
                step,
                state.draft,
                "command_history_corrupt",
            )
            raise self._service_error(
                "command_history_corrupt",
                str(exc),
                operation.id,
                state.draft,
            ) from exc
        except StructuredPrototypeStoreError as exc:
            if exc.code in CORRUPTION_ERROR_CODES:
                await self._handle_recovery_failure(running, step, state.draft, exc.code)
            else:
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
            command_history=next_history,
            history_checkpoint=state.history_checkpoint,
            journal_prefix_hash=result_prefix_hash,
            validated_tail_batches=(*state.validated_tail_batches, appended.batch),
        )
        return ApplyStructuredPrototypeCommandsResult(
            operation_id=operation.id,
            correlation_id=operation.correlation_id,
            applied_batch_id=appended.batch.id,
            allocated_entity_ids=(),
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
        return await self._checkpoint_recovered_state(
            state=recovered.state,
            client_request_id=client_request_id,
        )

    async def _checkpoint_recovered_state(
        self,
        *,
        state: ActivePrototypeState,
        client_request_id: str,
    ) -> CheckpointStructuredPrototypeResult:
        _require_client_request_id(client_request_id)
        draft_id = state.draft.id
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
            try:
                replay_artifact = await self._write_replay_manifest(
                    operation=operation,
                    created_at=self._now(),
                    ordered_input_object_hashes=(
                        state.draft.head_document_hash,
                        state.history_checkpoint.snapshot_object_hash,
                    ),
                    base_checkpoint_hash=state.history_checkpoint.checkpoint_document_hash,
                    base_sequence_no=state.draft.head_sequence_no,
                    result_checkpoint_hash=state.draft.head_document_hash,
                    result_sequence_no=state.draft.head_sequence_no,
                )
                completed, completed_step, event = self._succeed_operation(
                    running,
                    step,
                    result_hash=replay_artifact.descriptor.content_hash,
                    evidence_kind="checkpoint",
                    evidence_ref=state.loaded_checkpoint_id,
                )
                await self._store.register_replay_manifest_and_transition(
                    replay_descriptor=replay_artifact.descriptor,
                    replay_reference=replay_artifact.reference,
                    completed_operation=completed,
                    completion_step=completed_step,
                    completion_event=event,
                )
            except PrototypeObjectStoreError as exc:
                await self._fail_operation(running, step, exc.code)
                raise self._service_error(exc.code, str(exc), operation.id, state.draft) from exc
            except StructuredPrototypeStoreError as exc:
                await self._fail_operation(running, step, exc.code)
                raise self._service_error(exc.code, str(exc), operation.id, state.draft) from exc
            except StructuredPrototypeServiceError as exc:
                await self._fail_operation(running, step, exc.code)
                raise
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
            history_artifact = await self.materialize_command_history_checkpoint(
                project_id=state.document_record.project_id,
                checkpoint_id=checkpoint_id,
                draft_id=draft_id,
                checkpoint_sequence_no=state.draft.head_sequence_no,
                checkpoint_document_hash=descriptor.content_hash,
                journal_prefix_hash=state.journal_prefix_hash,
                history=state.command_history,
                created_at=now,
            )
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
                history_snapshot_object_hash=history_artifact.descriptor.content_hash,
                history_snapshot_schema_version=COMMAND_HISTORY_CHECKPOINT_SCHEMA_VERSION,
                journal_prefix_hash=state.journal_prefix_hash,
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
            replay_artifact = await self._write_replay_manifest(
                operation=operation,
                created_at=now,
                ordered_input_object_hashes=(
                    descriptor.content_hash,
                    history_artifact.descriptor.content_hash,
                ),
                base_checkpoint_hash=state.history_checkpoint.checkpoint_document_hash,
                base_sequence_no=state.loaded_checkpoint_sequence_no,
                result_checkpoint_hash=checkpoint.document_hash,
                result_sequence_no=checkpoint.checkpoint_sequence_no,
            )
            completed, completed_step, event = self._succeed_operation(
                running,
                step,
                result_hash=replay_artifact.descriptor.content_hash,
                evidence_kind="checkpoint",
                evidence_ref=checkpoint_id,
            )
            updated_draft = await self._store.register_draft_checkpoint(
                descriptor=descriptor,
                reference=reference,
                history_descriptor=history_artifact.descriptor,
                history_reference=history_artifact.reference,
                history_checkpoint=history_artifact.checkpoint,
                checkpoint=checkpoint,
                replay_descriptor=replay_artifact.descriptor,
                replay_reference=replay_artifact.reference,
                completed_operation=completed,
                completion_step=completed_step,
                completion_event=event,
            )
        except PrototypeObjectStoreError as exc:
            await self._fail_operation(running, step, exc.code)
            raise self._service_error(exc.code, str(exc), operation.id, state.draft) from exc
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
            command_history=state.command_history,
            history_checkpoint=history_artifact.checkpoint,
            journal_prefix_hash=state.journal_prefix_hash,
            validated_tail_batches=(),
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
                history_snapshot_object_hash=None,
                history_snapshot_schema_version=None,
                journal_prefix_hash=None,
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
            frozen_operation, completed_freeze_step, freeze_event = self._complete_nonterminal_step(
                running,
                freeze_step,
                output_hash=freeze_hash,
                evidence_kind="publication_revision",
                evidence_ref=revision_id,
                event_no=2,
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
                or preflight_descriptor.content_hash != render_result.visual_preflight_report_hash
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
            active_history = PrototypeCommandHistory(undo_stack=(), redo_stack=())
            active_prefix_hash = initial_journal_prefix_hash(draft_id=active_draft_id)
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
                history_snapshot_object_hash=None,
                history_snapshot_schema_version=None,
                journal_prefix_hash=active_prefix_hash,
                created_by_operation_id=operation.id,
                created_at=completed_at,
            )
            active_history_artifact = await self.materialize_command_history_checkpoint(
                project_id=document_record.project_id,
                checkpoint_id=active_checkpoint_id,
                draft_id=active_draft_id,
                checkpoint_sequence_no=0,
                checkpoint_document_hash=expected_document_hash,
                journal_prefix_hash=active_prefix_hash,
                history=active_history,
                created_at=completed_at,
            )
            active_checkpoint = replace(
                active_checkpoint,
                history_snapshot_object_hash=active_history_artifact.descriptor.content_hash,
                history_snapshot_schema_version=COMMAND_HISTORY_CHECKPOINT_SCHEMA_VERSION,
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
                active_history_descriptor=active_history_artifact.descriptor,
                active_history_reference=active_history_artifact.reference,
                active_history_checkpoint=active_history_artifact.checkpoint,
                completed_operation=successful_operation,
                completed_step=completed_step,
                completion_event=completion_event,
            )
        except (
            PrototypeObjectStoreError,
            StructuredPrototypeContractError,
            StructuredPrototypeStoreError,
        ) as exc:
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
            command_history=active_history,
            history_checkpoint=active_history_artifact.checkpoint,
            journal_prefix_hash=active_prefix_hash,
            validated_tail_batches=(),
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
            replay_artifact = await self._write_replay_manifest(
                operation=operation,
                created_at=now,
                ordered_input_object_hashes=(
                    session.pinned_document_object_hash,
                    state_descriptor.content_hash,
                ),
                base_checkpoint_hash=document_bundle.checkpoint.document_hash,
                base_sequence_no=document_bundle.checkpoint.checkpoint_sequence_no,
                result_checkpoint_hash=state_descriptor.content_hash,
                result_sequence_no=0,
                runtime_session_id=session_id,
                runtime_identity=worker.identity,
                runtime_final_state_hash=initial.state_hash,
                runtime_final_view_model_hash=initial.view_model_hash,
            )
            completed, completed_step, event = self._succeed_operation(
                running,
                step,
                result_hash=replay_artifact.descriptor.content_hash,
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
                replay_descriptor=replay_artifact.descriptor,
                replay_reference=replay_artifact.reference,
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

    async def reset_runtime_session(
        self,
        *,
        session_id: str,
        client_request_id: str,
        cause_operation_id: str | None,
        expected_old_head_sequence_no: int,
        expected_old_state_hash: str,
        expected_old_view_model_hash: str,
        expected_old_runtime_core_bundle_hash: str,
        target_draft_id: str,
        expected_target_head_sequence_no: int,
        expected_target_document_hash: str,
        scenario_id: str,
    ) -> ResetPrototypeRuntimeSessionResult:
        _require_client_request_id(client_request_id)
        old_session = await self._store.load_runtime_session(session_id)
        if old_session is None:
            raise StructuredPrototypeServiceError(
                "runtime_session_missing",
                "prototype runtime session does not exist",
            )
        cause_operation = await self._load_runtime_reset_cause(
            old_session=old_session,
            cause_operation_id=cause_operation_id,
        )
        worker = self._runtime_worker
        new_session_id = _stable_id(session_id, client_request_id, "runtime-session-reset")
        request_hash = _manifest_hash(
            {
                "kind": "reset_runtime_session",
                "oldSessionId": session_id,
                "causeOperationId": cause_operation_id,
                "expectedOldHeadSequenceNo": expected_old_head_sequence_no,
                "expectedOldStateHash": expected_old_state_hash,
                "expectedOldViewModelHash": expected_old_view_model_hash,
                "expectedOldRuntimeCoreBundleHash": (expected_old_runtime_core_bundle_hash),
                "targetDraftId": target_draft_id,
                "expectedTargetHeadSequenceNo": expected_target_head_sequence_no,
                "expectedTargetDocumentHash": expected_target_document_hash,
                "scenarioId": scenario_id,
            }
        )
        operation = self._queued_operation(
            operation_kind="reset_runtime_session",
            project_id=old_session.project_id,
            resource_kind="runtime_session",
            resource_id=new_session_id,
            client_request_id=client_request_id,
            parent_operation_id=(cause_operation.id if cause_operation is not None else None),
            request_manifest_hash=request_hash,
            config_manifest_hash=self._runtime_config_manifest_hash(
                worker.identity if worker is not None else None
            ),
        )
        created = await self._create_operation(operation)
        if not created.created:
            if created.operation.status != "succeeded":
                raise self._existing_operation_error(created.operation)
            new_session = await self._store.load_runtime_session(new_session_id)
            if new_session is None or new_session.replaces_session_id != session_id:
                raise StructuredPrototypeServiceError(
                    "operation_result_missing",
                    "prototype runtime reset operation has no replacement session",
                    operation_id=created.operation.id,
                )
            reset_references = await self._store.list_object_references(
                old_session.project_id,
                "runtime_session",
                new_session_id,
            )
            reset_manifest_hash = next(
                (
                    reference.content_hash
                    for reference in reset_references
                    if reference.role == "runtime-session-reset-manifest"
                    and reference.payload_type == "runtime_session_reset_manifest"
                ),
                None,
            )
            if reset_manifest_hash is None:
                raise StructuredPrototypeServiceError(
                    "operation_result_missing",
                    "prototype runtime reset operation has no reset manifest",
                    operation_id=created.operation.id,
                )
            state = await self._replay_runtime_session(new_session_id)
            return ResetPrototypeRuntimeSessionResult(
                operation_id=created.operation.id,
                correlation_id=created.operation.correlation_id,
                reset_manifest_hash=reset_manifest_hash,
                state=state,
            )
        running, step = await self._start_operation(operation, "rebuild_runtime_session")
        try:
            worker = self._require_runtime_worker()
            if old_session.recording_kind != "studio_preview" or old_session.source_kind != "draft":
                raise StructuredPrototypeServiceError(
                    "runtime_session_reset_not_allowed",
                    "only draft-backed Studio preview sessions can be reset",
                    operation_id=operation.id,
                )
            if (
                old_session.head_sequence_no != expected_old_head_sequence_no
                or old_session.head_state_hash != expected_old_state_hash
                or old_session.head_view_model_hash != expected_old_view_model_hash
                or old_session.runtime_core_bundle_hash != expected_old_runtime_core_bundle_hash
            ):
                raise StructuredPrototypeServiceError(
                    "runtime_session_conflict",
                    "prototype runtime reset source does not match the expected head",
                    operation_id=operation.id,
                )
            target_draft = await self._store.load_draft(target_draft_id)
            if target_draft is None:
                raise StructuredPrototypeServiceError(
                    "draft_missing",
                    "prototype runtime reset target draft does not exist",
                    operation_id=operation.id,
                )
            target_document = await self._store.load_document(target_draft.document_id)
            if target_document is None:
                raise StructuredPrototypeServiceError(
                    "document_missing",
                    "prototype runtime reset target document does not exist",
                    operation_id=operation.id,
                )
            if (
                target_document.project_id != old_session.project_id
                or target_document.id != old_session.document_id
            ):
                raise StructuredPrototypeServiceError(
                    "runtime_session_reset_target_mismatch",
                    "prototype runtime reset target belongs to another document",
                    operation_id=operation.id,
                )
            if (
                target_draft.status != "active"
                or target_draft.head_sequence_no != expected_target_head_sequence_no
                or target_draft.head_document_hash != expected_target_document_hash
            ):
                raise StructuredPrototypeServiceError(
                    "draft_conflict",
                    "prototype runtime reset target does not match the expected draft head",
                    operation_id=operation.id,
                )
            checkpointed = await self.checkpoint_draft(
                draft_id=target_draft_id,
                client_request_id=_stable_id(
                    client_request_id,
                    target_draft_id,
                    str(expected_target_head_sequence_no),
                    expected_target_document_hash,
                    "runtime-reset-document-checkpoint",
                ),
            )
            target_state = checkpointed.state
            if (
                target_state.draft.head_sequence_no != expected_target_head_sequence_no
                or target_state.draft.head_document_hash != expected_target_document_hash
                or target_state.loaded_checkpoint_sequence_no != expected_target_head_sequence_no
            ):
                raise StructuredPrototypeServiceError(
                    "draft_conflict",
                    "prototype runtime reset target changed during checkpointing",
                    operation_id=operation.id,
                )
            target_bundle = await self._store.load_draft_recovery_bundle(target_draft_id)
            if (
                target_bundle.checkpoint.id != target_state.loaded_checkpoint_id
                or target_bundle.checkpoint.checkpoint_sequence_no
                != expected_target_head_sequence_no
                or target_bundle.object_descriptor.content_hash != expected_target_document_hash
            ):
                raise StructuredPrototypeServiceError(
                    "runtime_document_checkpoint_mismatch",
                    "prototype runtime reset target checkpoint changed",
                    operation_id=operation.id,
                )
            scenario = next(
                (
                    candidate
                    for candidate in target_state.document.runtime.scenarios
                    if candidate.id == scenario_id
                ),
                None,
            )
            if scenario is None:
                raise StructuredPrototypeServiceError(
                    "runtime_scenario_missing",
                    "prototype runtime reset scenario does not exist",
                    operation_id=operation.id,
                )
            definition = self._runtime_definition_payload(target_state.document)
            initial = await worker.initialize_state(
                request_id=operation.id,
                definition=definition,
                scenario_id=scenario_id,
                session_id=new_session_id,
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
                old_session.project_id,
                state_payload,
            )
            if state_descriptor.content_hash != initial.state_hash:
                raise StructuredPrototypeServiceError(
                    "runtime_checkpoint_state_hash_mismatch",
                    "prototype runtime reset state object does not match the worker result",
                    operation_id=operation.id,
                )
            now = self._now()
            checkpoint_id = _stable_id(operation.id, "runtime-checkpoint", "0")
            new_session = PrototypeRuntimeSessionRecord(
                id=new_session_id,
                project_id=old_session.project_id,
                document_id=old_session.document_id,
                source_kind="draft",
                source_id=target_draft_id,
                pinned_document_object_hash=target_bundle.object_descriptor.content_hash,
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
                recording_kind="studio_preview",
                allow_simulated_role_switch=scenario.allow_simulated_role_switch,
                actor_subject_id=old_session.actor_subject_id,
                created_at=now,
                updated_at=now,
                completed_at=None,
                replaces_session_id=old_session.id,
            )
            runtime_checkpoint = PrototypeRuntimeCheckpointRecord(
                id=checkpoint_id,
                session_id=new_session_id,
                checkpoint_sequence_no=0,
                state_object_hash=initial.state_hash,
                runtime_state_schema_version=RUNTIME_STATE_SCHEMA_VERSION,
                runtime_event_contract_version=RUNTIME_EVENT_CONTRACT_VERSION,
                state_hash=initial.state_hash,
                view_model_hash=initial.view_model_hash,
                created_by_operation_id=operation.id,
                created_at=now,
            )
            reset_reason = self._runtime_reset_reason(
                old_session=old_session,
                target_draft_id=target_draft_id,
                target_document_hash=expected_target_document_hash,
                identity=worker.identity,
            )
            reset_manifest = self._runtime_reset_manifest(
                operation=operation,
                occurred_at=now,
                reset_reason=reset_reason,
                cause_operation_id=cause_operation_id,
                old_session=old_session,
                target_bundle=target_bundle,
                new_session=new_session,
                new_checkpoint=runtime_checkpoint,
            )
            reset_manifest_descriptor = await asyncio.to_thread(
                self._object_store.write_json,
                old_session.project_id,
                reset_manifest,
            )
            replay_artifact = await self._write_replay_manifest(
                operation=operation,
                created_at=now,
                ordered_input_object_hashes=(
                    target_bundle.object_descriptor.content_hash,
                    state_descriptor.content_hash,
                    reset_manifest_descriptor.content_hash,
                ),
                base_checkpoint_hash=target_bundle.checkpoint.document_hash,
                base_sequence_no=target_bundle.checkpoint.checkpoint_sequence_no,
                result_checkpoint_hash=state_descriptor.content_hash,
                result_sequence_no=0,
                runtime_session_id=new_session_id,
                runtime_identity=worker.identity,
                runtime_final_state_hash=initial.state_hash,
                runtime_final_view_model_hash=initial.view_model_hash,
            )
            completed, completed_step, event = self._succeed_operation(
                running,
                step,
                result_hash=replay_artifact.descriptor.content_hash,
                evidence_kind="runtime_session_reset_manifest",
                evidence_ref=reset_manifest_descriptor.content_hash,
            )
            state_reference = PrototypeObjectReference(
                project_id=old_session.project_id,
                owner_kind="runtime_checkpoint",
                owner_id=checkpoint_id,
                role="runtime-state-checkpoint",
                content_hash=state_descriptor.content_hash,
                payload_type="prototype_runtime_state",
                schema_version=RUNTIME_STATE_SCHEMA_VERSION,
                created_at=now,
            )
            old_reset_reference = PrototypeObjectReference(
                project_id=old_session.project_id,
                owner_kind="runtime_session",
                owner_id=old_session.id,
                role="runtime-session-reset-manifest",
                content_hash=reset_manifest_descriptor.content_hash,
                payload_type="runtime_session_reset_manifest",
                schema_version=1,
                created_at=now,
            )
            new_reset_reference = replace(old_reset_reference, owner_id=new_session_id)
            persisted_session = await self._store.reset_runtime_session(
                expected_old_status=old_session.status,
                expected_old_latest_checkpoint_id=old_session.latest_checkpoint_id,
                expected_old_head_sequence_no=expected_old_head_sequence_no,
                expected_old_state_hash=expected_old_state_hash,
                expected_old_view_model_hash=expected_old_view_model_hash,
                expected_old_runtime_core_bundle_hash=(expected_old_runtime_core_bundle_hash),
                target_draft_id=target_draft_id,
                expected_target_head_sequence_no=expected_target_head_sequence_no,
                expected_target_document_hash=expected_target_document_hash,
                state_descriptor=state_descriptor,
                state_reference=state_reference,
                reset_manifest_descriptor=reset_manifest_descriptor,
                old_reset_reference=old_reset_reference,
                new_reset_reference=new_reset_reference,
                replay_descriptor=replay_artifact.descriptor,
                replay_reference=replay_artifact.reference,
                session=new_session,
                checkpoint=runtime_checkpoint,
                completed_operation=completed,
                completion_step=completed_step,
                completion_event=event,
            )
        except PrototypeRuntimeWorkerError as exc:
            await self._fail_operation(running, step, exc.code)
            raise self._runtime_service_error(
                exc.code,
                str(exc),
                operation.id,
                old_session,
            ) from exc
        except PrototypeObjectStoreError as exc:
            await self._fail_operation(running, step, exc.code)
            raise self._runtime_service_error(
                exc.code,
                str(exc),
                operation.id,
                old_session,
            ) from exc
        except StructuredPrototypeStoreError as exc:
            await self._fail_operation(running, step, exc.code)
            latest = await self._store.load_runtime_session(session_id)
            raise self._runtime_service_error(
                exc.code,
                str(exc),
                operation.id,
                latest or old_session,
            ) from exc
        except StructuredPrototypeServiceError as exc:
            await self._fail_operation(running, step, exc.code)
            raise self._runtime_service_error(
                exc.code,
                str(exc),
                operation.id,
                old_session,
            ) from exc
        return ResetPrototypeRuntimeSessionResult(
            operation_id=operation.id,
            correlation_id=operation.correlation_id,
            reset_manifest_hash=reset_manifest_descriptor.content_hash,
            state=ActivePrototypeRuntimeState(
                session=persisted_session,
                state_json=initial.state_json,
                view_model_json=initial.view_model_json,
                loaded_checkpoint_id=runtime_checkpoint.id,
                loaded_checkpoint_sequence_no=0,
                replayed_event_batch_ids=(),
            ),
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
            recovery_bundle = await self._store.load_runtime_recovery_bundle(session_id)
            if (
                recovery_bundle.checkpoint.id != active.loaded_checkpoint_id
                or recovery_bundle.session.head_sequence_no != current.head_sequence_no
                or recovery_bundle.session.head_state_hash != current.head_state_hash
            ):
                raise StructuredPrototypeServiceError(
                    "runtime_session_conflict",
                    "prototype runtime session changed before replay manifest creation",
                    operation_id=operation.id,
                )
            replay_artifact = await self._write_replay_manifest(
                operation=operation,
                created_at=now,
                ordered_input_object_hashes=(
                    current.pinned_document_object_hash,
                    recovery_bundle.checkpoint.state_object_hash,
                ),
                base_checkpoint_hash=recovery_bundle.checkpoint.state_object_hash,
                base_sequence_no=recovery_bundle.checkpoint.checkpoint_sequence_no,
                result_sequence_no=record.result_sequence_no,
                runtime_session_id=session_id,
                runtime_identity=worker.identity,
                ordered_runtime_event_hashes=(
                    *(item.event_batch_hash for item in recovery_bundle.event_batches),
                    record.event_batch_hash,
                ),
                runtime_final_state_hash=record.result_state_hash,
                runtime_final_view_model_hash=record.result_view_model_hash,
                validation_report_hashes=(
                    record.guard_report_hash,
                    record.effect_report_hash,
                ),
            )
            completed, completed_step, event = self._succeed_operation(
                running,
                step,
                result_hash=replay_artifact.descriptor.content_hash,
                evidence_kind="runtime_event_batch",
                evidence_ref=event_batch_id,
            )
            appended = await self._store.append_runtime_event_batch(
                event_batch=record,
                replay_descriptor=replay_artifact.descriptor,
                replay_reference=replay_artifact.reference,
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
            raise self._runtime_service_error(
                "runtime_session_corrupt",
                "prototype runtime session is marked corrupt and cannot be replayed",
                None,
                session,
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
            worker = self._require_runtime_worker()
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
            recovery_bundle = await self._store.load_runtime_recovery_bundle(session_id)
            if (
                recovery_bundle.checkpoint.id != state.loaded_checkpoint_id
                or recovery_bundle.session.head_sequence_no != state.session.head_sequence_no
                or recovery_bundle.session.head_state_hash != state.session.head_state_hash
                or recovery_bundle.session.head_view_model_hash
                != state.session.head_view_model_hash
            ):
                raise StructuredPrototypeServiceError(
                    "runtime_session_conflict",
                    "prototype runtime session changed before replay manifest creation",
                    operation_id=operation.id,
                )
            replay_artifact = await self._write_replay_manifest(
                operation=operation,
                created_at=self._now(),
                ordered_input_object_hashes=(
                    state.session.pinned_document_object_hash,
                    recovery_bundle.checkpoint.state_object_hash,
                ),
                base_checkpoint_hash=recovery_bundle.checkpoint.state_object_hash,
                base_sequence_no=recovery_bundle.checkpoint.checkpoint_sequence_no,
                result_sequence_no=state.session.head_sequence_no,
                runtime_session_id=session_id,
                runtime_identity=worker.identity,
                ordered_runtime_event_hashes=tuple(
                    item.event_batch_hash for item in recovery_bundle.event_batches
                ),
                runtime_final_state_hash=state.session.head_state_hash,
                runtime_final_view_model_hash=state.session.head_view_model_hash,
            )
            completed, completed_step, event = self._succeed_operation(
                running,
                step,
                result_hash=replay_artifact.descriptor.content_hash,
                evidence_kind="runtime_state_hash",
                evidence_ref=state.session.head_state_hash,
            )
            await self._store.register_replay_manifest_and_transition(
                replay_descriptor=replay_artifact.descriptor,
                replay_reference=replay_artifact.reference,
                completed_operation=completed,
                completion_step=completed_step,
                completion_event=event,
            )
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
            await self._handle_runtime_recovery_failure(
                running,
                step,
                session,
                exc.code,
                force_corruption=exc.code == "runtime_replay_version_mismatch",
            )
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
            worker = self._require_runtime_worker()
            active = await self._replay_runtime_session(session_id)
            if active.session.status != "active":
                raise StructuredPrototypeServiceError(
                    "runtime_session_not_active",
                    "prototype runtime session does not accept checkpoints",
                    operation_id=operation.id,
                    current_head_sequence_no=active.session.head_sequence_no,
                    current_state_hash=active.session.head_state_hash,
                )
            recovery_bundle = await self._store.load_runtime_recovery_bundle(session_id)
            if (
                recovery_bundle.checkpoint.id != active.loaded_checkpoint_id
                or recovery_bundle.session.head_sequence_no != active.session.head_sequence_no
                or recovery_bundle.session.head_state_hash != active.session.head_state_hash
                or recovery_bundle.session.head_view_model_hash
                != active.session.head_view_model_hash
            ):
                raise StructuredPrototypeServiceError(
                    "runtime_session_conflict",
                    "prototype runtime session changed before checkpoint manifest creation",
                    operation_id=operation.id,
                )
            if active.loaded_checkpoint_sequence_no == active.session.head_sequence_no:
                replay_artifact = await self._write_replay_manifest(
                    operation=operation,
                    created_at=self._now(),
                    ordered_input_object_hashes=(
                        active.session.pinned_document_object_hash,
                        recovery_bundle.checkpoint.state_object_hash,
                    ),
                    base_checkpoint_hash=recovery_bundle.checkpoint.state_object_hash,
                    base_sequence_no=recovery_bundle.checkpoint.checkpoint_sequence_no,
                    result_checkpoint_hash=recovery_bundle.checkpoint.state_object_hash,
                    result_sequence_no=active.session.head_sequence_no,
                    runtime_session_id=session_id,
                    runtime_identity=worker.identity,
                    ordered_runtime_event_hashes=tuple(
                        item.event_batch_hash for item in recovery_bundle.event_batches
                    ),
                    runtime_final_state_hash=active.session.head_state_hash,
                    runtime_final_view_model_hash=active.session.head_view_model_hash,
                )
                completed, completed_step, event = self._succeed_operation(
                    running,
                    step,
                    result_hash=replay_artifact.descriptor.content_hash,
                    evidence_kind="runtime_checkpoint",
                    evidence_ref=active.loaded_checkpoint_id,
                )
                await self._store.register_replay_manifest_and_transition(
                    replay_descriptor=replay_artifact.descriptor,
                    replay_reference=replay_artifact.reference,
                    completed_operation=completed,
                    completion_step=completed_step,
                    completion_event=event,
                )
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
            replay_artifact = await self._write_replay_manifest(
                operation=operation,
                created_at=now,
                ordered_input_object_hashes=(
                    active.session.pinned_document_object_hash,
                    recovery_bundle.checkpoint.state_object_hash,
                    descriptor.content_hash,
                ),
                base_checkpoint_hash=recovery_bundle.checkpoint.state_object_hash,
                base_sequence_no=recovery_bundle.checkpoint.checkpoint_sequence_no,
                result_checkpoint_hash=descriptor.content_hash,
                result_sequence_no=checkpoint.checkpoint_sequence_no,
                runtime_session_id=session_id,
                runtime_identity=worker.identity,
                ordered_runtime_event_hashes=tuple(
                    item.event_batch_hash for item in recovery_bundle.event_batches
                ),
                runtime_final_state_hash=checkpoint.state_hash,
                runtime_final_view_model_hash=checkpoint.view_model_hash,
            )
            completed, completed_step, event = self._succeed_operation(
                running,
                step,
                result_hash=replay_artifact.descriptor.content_hash,
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
                replay_descriptor=replay_artifact.descriptor,
                replay_reference=replay_artifact.reference,
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
        if (
            bundle.checkpoint.history_snapshot_object_hash is None
            or bundle.checkpoint.history_snapshot_schema_version is None
            or bundle.checkpoint.journal_prefix_hash is None
        ):
            raise StructuredPrototypeContractError(
                "command_history_checkpoint_missing",
                "prototype draft checkpoint has no command history seal",
            )
        if (
            bundle.checkpoint.history_snapshot_schema_version
            != COMMAND_HISTORY_CHECKPOINT_SCHEMA_VERSION
        ):
            raise StructuredPrototypeContractError(
                "replay_contract_unsupported",
                "prototype command history checkpoint schema version is unsupported",
            )
        document_bytes, history_bytes = await asyncio.gather(
            asyncio.to_thread(
                self._object_store.read_canonical_bytes,
                bundle.object_descriptor,
            ),
            asyncio.to_thread(
                self._object_store.read_canonical_bytes,
                bundle.history_object_descriptor,
            ),
        )
        document = parse_prototype_document_json(document_bytes)
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
        parsed_history_checkpoint = parse_command_history_checkpoint_json(history_bytes)
        if (
            canonical_command_history_checkpoint_json(parsed_history_checkpoint).encode("utf-8")
            != history_bytes
        ):
            raise StructuredPrototypeContractError(
                "command_history_checkpoint_hash_mismatch",
                "prototype command history checkpoint is not canonical",
            )
        history_checkpoint = command_history_checkpoint_to_domain(
            parsed_history_checkpoint,
            snapshot_object_hash=bundle.history_object_descriptor.content_hash,
        )
        self._validate_history_checkpoint_identity(bundle, history_checkpoint)
        history, journal_prefix_hash, snap_evidence_jsons = await self._validate_command_tail(
            history_checkpoint,
            bundle.command_batches,
        )
        await self._attest_snap_evidence_many(
            request_id=_stable_id(
                bundle.draft.id,
                str(bundle.draft.head_sequence_no),
                bundle.draft.head_document_hash,
                "snap-attest-tail",
            ),
            evidence_jsons=snap_evidence_jsons,
        )
        applied_ids: list[str] = []
        for stored_batch in bundle.command_batches:
            execution = self._execute_stored_command_batch(document, stored_batch)
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
            command_history=history,
            history_checkpoint=history_checkpoint,
            journal_prefix_hash=journal_prefix_hash,
            validated_tail_batches=bundle.command_batches,
        )

    @staticmethod
    def _validate_history_checkpoint_identity(
        bundle: PrototypeDraftRecoveryBundle,
        history_checkpoint: PrototypeCommandHistoryCheckpoint,
    ) -> None:
        checkpoint = bundle.checkpoint
        if (
            history_checkpoint.draft_id != bundle.draft.id
            or history_checkpoint.checkpoint_sequence_no != checkpoint.checkpoint_sequence_no
            or history_checkpoint.checkpoint_document_hash != checkpoint.document_hash
            or history_checkpoint.journal_prefix_hash != checkpoint.journal_prefix_hash
            or history_checkpoint.snapshot_object_hash != checkpoint.history_snapshot_object_hash
            or history_checkpoint.snapshot_schema_version
            != checkpoint.history_snapshot_schema_version
        ):
            raise StructuredPrototypeContractError(
                "command_history_checkpoint_identity_mismatch",
                "prototype command history checkpoint does not match its draft checkpoint",
            )
        if (
            checkpoint.checkpoint_sequence_no == 0
            and history_checkpoint.journal_prefix_hash
            != initial_journal_prefix_hash(draft_id=bundle.draft.id)
        ):
            raise StructuredPrototypeContractError(
                "journal_prefix_hash_mismatch",
                "prototype initial journal prefix hash is invalid",
            )

    async def _validate_command_tail(
        self,
        history_checkpoint: PrototypeCommandHistoryCheckpoint,
        batches: tuple[PrototypeCommandBatchRecord, ...],
    ) -> tuple[PrototypeCommandHistory, str, tuple[str, ...]]:
        records_by_id: dict[str, PrototypeCommandBatchRecord] = {}
        snap_evidence_jsons: list[str] = []
        history = history_checkpoint.history
        journal_prefix_hash = history_checkpoint.journal_prefix_hash
        expected_sequence_no = history_checkpoint.checkpoint_sequence_no
        expected_document_hash = history_checkpoint.checkpoint_document_hash
        try:
            for stored_batch in batches:
                if stored_batch.id in records_by_id:
                    raise StructuredPrototypeContractError(
                        "command_history_corrupt",
                        "prototype command journal contains duplicate batch IDs",
                    )
                if (
                    stored_batch.draft_id != history_checkpoint.draft_id
                    or stored_batch.base_sequence_no != expected_sequence_no
                    or stored_batch.result_sequence_no != expected_sequence_no + 1
                    or stored_batch.base_document_hash != expected_document_hash
                ):
                    raise StructuredPrototypeContractError(
                        "replay_sequence_gap",
                        "prototype command tail is not continuous from its checkpoint",
                    )
                parsed_commands, _ = self._parse_and_validate_stored_batch(stored_batch)
                if (
                    isinstance(parsed_commands, DomainCommandBatchV1)
                    and parsed_commands.evidence is not None
                ):
                    snap_evidence_jsons.append(canonical_model_json(parsed_commands.evidence))
                if stored_batch.operation_kind != "forward":
                    stack = (
                        history.undo_stack
                        if stored_batch.operation_kind == "undo"
                        else history.redo_stack
                    )
                    if not stack or stored_batch.target_batch_id != stack[-1].batch_id:
                        raise StructuredPrototypeContractError(
                            "command_history_corrupt",
                            "prototype history command does not target the sealed stack top",
                        )
                    target_entry = stack[-1]
                    target = records_by_id.get(target_entry.batch_id)
                    if target is None:
                        target = await self._load_verified_history_target(
                            draft_id=history_checkpoint.draft_id,
                            entry=target_entry,
                        )
                    elif target.command_batch_hash != target_entry.command_batch_hash:
                        raise StructuredPrototypeContractError(
                            "command_history_entry_hash_mismatch",
                            "prototype command history entry hash does not match its batch",
                        )
                    if (
                        stored_batch.commands_json != target.inverse_commands_json
                        or stored_batch.base_document_hash != target.result_document_hash
                        or stored_batch.result_document_hash != target.base_document_hash
                    ):
                        raise StructuredPrototypeContractError(
                            "command_history_corrupt",
                            "prototype history command does not exactly invert its target",
                        )
                journal_prefix_hash = advance_journal_prefix_hash(
                    previous_prefix_hash=journal_prefix_hash,
                    batch_id=stored_batch.id,
                    base_sequence_no=stored_batch.base_sequence_no,
                    result_sequence_no=stored_batch.result_sequence_no,
                    command_batch_hash=stored_batch.command_batch_hash,
                    base_document_hash=stored_batch.base_document_hash,
                    result_document_hash=stored_batch.result_document_hash,
                )
                history = advance_prototype_command_history(history, stored_batch)
                records_by_id[stored_batch.id] = stored_batch
                expected_sequence_no = stored_batch.result_sequence_no
                expected_document_hash = stored_batch.result_document_hash
            return history, journal_prefix_hash, tuple(snap_evidence_jsons)
        except PrototypeCommandHistoryError as exc:
            raise StructuredPrototypeContractError(
                "command_history_corrupt",
                "prototype command journal cannot be folded",
            ) from exc

    @staticmethod
    def _parse_and_validate_stored_batch(
        stored_batch: PrototypeCommandBatchRecord,
    ) -> tuple[DomainCommandBatchV1 | InverseCommandBatchV1, InverseCommandBatchV1]:
        if stored_batch.command_contract_version != COMMAND_CONTRACT_VERSION:
            raise StructuredPrototypeContractError(
                "replay_contract_unsupported",
                "prototype command contract version is unsupported",
            )
        parsed_inverse = parse_inverse_command_batch_json(stored_batch.inverse_commands_json)
        if canonical_model_json(parsed_inverse) != stored_batch.inverse_commands_json:
            raise StructuredPrototypeContractError(
                "inverse_command_mismatch",
                "prototype inverse command payload is not canonical",
            )
        if (
            stored_batch.operation_kind == "forward"
            and len(stored_batch.commands_json.encode("utf-8"))
            > PROTOTYPE_FORWARD_COMMAND_BATCH_MAX_BYTES
        ):
            raise StructuredPrototypeContractError(
                "command_batch_too_large",
                "prototype forward command payload exceeds 256 KiB",
            )
        parsed_commands: DomainCommandBatchV1 | InverseCommandBatchV1
        if stored_batch.operation_kind == "forward":
            if stored_batch.target_batch_id is not None:
                raise StructuredPrototypeContractError(
                    "command_history_corrupt",
                    "prototype forward command unexpectedly targets a history batch",
                )
            parsed_commands = parse_command_batch_json(stored_batch.commands_json)
        else:
            if stored_batch.target_batch_id is None:
                raise StructuredPrototypeContractError(
                    "command_history_corrupt",
                    "prototype history command has no target batch",
                )
            parsed_commands = parse_inverse_command_batch_json(stored_batch.commands_json)
        if canonical_model_json(parsed_commands) != stored_batch.commands_json:
            raise StructuredPrototypeContractError(
                "replay_batch_hash_mismatch",
                "prototype command payload is not canonical",
            )
        envelope_hash = command_batch_envelope_hash(
            draft_id=stored_batch.draft_id,
            base_sequence_no=stored_batch.base_sequence_no,
            result_sequence_no=stored_batch.result_sequence_no,
            origin=stored_batch.origin,
            operation_kind=stored_batch.operation_kind,
            target_batch_id=stored_batch.target_batch_id,
            commands=parsed_commands,
            inverse_commands=parsed_inverse,
        )
        if envelope_hash != stored_batch.command_batch_hash:
            raise StructuredPrototypeContractError(
                "replay_batch_hash_mismatch",
                "prototype command batch hash does not match its canonical envelope",
            )
        return parsed_commands, parsed_inverse

    async def _load_verified_history_target(
        self,
        *,
        draft_id: str,
        entry: PrototypeCommandHistoryEntry,
    ) -> PrototypeCommandBatchRecord:
        target = await self._store.load_command_batch(draft_id, entry.batch_id)
        if target is None:
            raise StructuredPrototypeContractError(
                "command_history_entry_missing",
                "prototype sealed history target batch is missing",
            )
        self._validate_history_target(target, entry)
        return target

    @classmethod
    def _validate_history_target(
        cls,
        target: PrototypeCommandBatchRecord,
        entry: PrototypeCommandHistoryEntry,
    ) -> None:
        cls._parse_and_validate_stored_batch(target)
        if target.command_batch_hash != entry.command_batch_hash:
            raise StructuredPrototypeContractError(
                "command_history_entry_hash_mismatch",
                "prototype sealed history target hash does not match its batch",
            )

    @staticmethod
    def _execute_stored_command_batch(
        document: PrototypeDocumentV1,
        stored_batch: PrototypeCommandBatchRecord,
    ) -> CommandExecutionResultV1:
        if document_hash(document) != stored_batch.base_document_hash:
            raise StructuredPrototypeContractError(
                "replay_document_hash_mismatch",
                "prototype replay document does not match the command base hash",
            )
        if stored_batch.operation_kind == "forward":
            parsed_forward = parse_command_batch_json(stored_batch.commands_json)
            validate_command_batch_evidence_context(
                document,
                parsed_forward,
                draft_id=stored_batch.draft_id,
                base_head_sequence_no=stored_batch.base_sequence_no,
                base_document_hash=stored_batch.base_document_hash,
            )
            execution = execute_command_batch(
                document,
                parsed_forward,
                draft_id=stored_batch.draft_id,
                client_request_id=stored_batch.client_request_id,
            )
        else:
            parsed_history = parse_inverse_command_batch_json(stored_batch.commands_json)
            execution = execute_inverse_command_batch(document, parsed_history)
        if (
            execution.base_document_hash != stored_batch.base_document_hash
            or execution.result_document_hash != stored_batch.result_document_hash
        ):
            raise StructuredPrototypeContractError(
                "replay_document_hash_mismatch",
                "prototype replay result does not match the command hash transition",
            )
        if canonical_model_json(execution.inverse_commands) != stored_batch.inverse_commands_json:
            raise StructuredPrototypeContractError(
                "inverse_command_mismatch",
                "prototype inverse commands do not match deterministic execution",
            )
        return execution

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
        *,
        expected_batch_kind: Literal["forward", "undo", "redo"] = "forward",
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
        if batch.operation_kind != expected_batch_kind:
            raise StructuredPrototypeServiceError(
                "operation_result_corrupt",
                "prototype command operation result has the wrong history kind",
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
        try:
            inverse = parse_inverse_command_batch_json(batch.inverse_commands_json)
            reverse_execution = execute_inverse_command_batch(state.document, inverse)
            if (
                reverse_execution.base_document_hash != batch.result_document_hash
                or reverse_execution.result_document_hash != batch.base_document_hash
            ):
                raise StructuredPrototypeContractError(
                    "inverse_command_mismatch",
                    "prototype idempotent command inverse does not reconstruct its base",
                )
            execution = self._execute_stored_command_batch(
                reverse_execution.document,
                batch,
            )
            if execution.result_document_hash != state.draft.head_document_hash or (
                expected_batch_kind != "forward" and execution.allocated_entity_ids
            ):
                raise StructuredPrototypeContractError(
                    "replay_document_hash_mismatch",
                    "prototype idempotent command result does not match its durable head",
                )
        except StructuredPrototypeContractError as exc:
            raise StructuredPrototypeServiceError(
                "operation_result_corrupt",
                "prototype idempotent command result cannot be reconstructed",
                operation_id=operation.id,
            ) from exc
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
        if (
            run is None
            or run.status != "ready"
            or run.artifact_id is None
            or run.revision_id is None
        ):
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

    async def _load_runtime_reset_cause(
        self,
        *,
        old_session: PrototypeRuntimeSessionRecord,
        cause_operation_id: str | None,
    ) -> PrototypeOperation | None:
        if cause_operation_id is None:
            return None
        _require_runtime_reset_cause_id(cause_operation_id)
        cause = await self._store.load_operation(cause_operation_id)
        failed_replay_for_old_session = (
            cause is not None
            and cause.operation_kind == "replay_runtime_session"
            and cause.resource_kind == "runtime_session"
            and cause.resource_id == old_session.id
        )
        failed_reset_for_old_session = (
            cause is not None
            and cause.operation_kind == "reset_runtime_session"
            and cause.resource_kind == "runtime_session"
            and cause.resource_id
            == _stable_id(
                old_session.id,
                cause.client_request_id,
                "runtime-session-reset",
            )
        )
        if (
            cause is None
            or cause.project_id != old_session.project_id
            or cause.status != "failed"
            or not (failed_replay_for_old_session or failed_reset_for_old_session)
        ):
            raise self._runtime_service_error(
                "runtime_reset_cause_invalid",
                "prototype runtime reset cause is not a failed operation for the old session",
                None,
                old_session,
            )
        return cause

    @staticmethod
    def _runtime_reset_reason(
        *,
        old_session: PrototypeRuntimeSessionRecord,
        target_draft_id: str,
        target_document_hash: str,
        identity: PrototypeRuntimeWorkerIdentity,
    ) -> str:
        if (
            old_session.runtime_core_version != identity.runtime_core_version
            or old_session.runtime_core_bundle_hash != identity.runtime_core_bundle_hash
            or old_session.state_machine_kernel_version != identity.state_machine_kernel_version
        ):
            return "runtime_identity_changed"
        if old_session.status == "corrupt":
            return "runtime_session_corrupt"
        if (
            old_session.source_id != target_draft_id
            or old_session.pinned_document_object_hash != target_document_hash
        ):
            return "target_draft_changed"
        return "explicit_runtime_rebuild"

    @staticmethod
    def _runtime_reset_manifest(
        *,
        operation: PrototypeOperation,
        occurred_at: datetime,
        reset_reason: str,
        cause_operation_id: str | None,
        old_session: PrototypeRuntimeSessionRecord,
        target_bundle: PrototypeDraftRecoveryBundle,
        new_session: PrototypeRuntimeSessionRecord,
        new_checkpoint: PrototypeRuntimeCheckpointRecord,
    ) -> dict[str, object]:
        return {
            "contractVersion": 1,
            "schemaVersion": 1,
            "payloadType": "runtime_session_reset_manifest",
            "oldSession": {
                "sessionId": old_session.id,
                "projectId": old_session.project_id,
                "documentId": old_session.document_id,
                "status": old_session.status,
                "recordingKind": old_session.recording_kind,
                "allowSimulatedRoleSwitch": old_session.allow_simulated_role_switch,
                "scenarioId": old_session.scenario_id,
                "scenarioHash": old_session.scenario_hash,
                "source": {
                    "kind": old_session.source_kind,
                    "id": old_session.source_id,
                    "documentObjectHash": old_session.pinned_document_object_hash,
                },
                "identity": {
                    "runtimeCoreVersion": old_session.runtime_core_version,
                    "runtimeCoreBundleHash": old_session.runtime_core_bundle_hash,
                    "stateMachineKernelVersion": old_session.state_machine_kernel_version,
                },
                "head": {
                    "sequenceNo": old_session.head_sequence_no,
                    "stateHash": old_session.head_state_hash,
                    "viewModelHash": old_session.head_view_model_hash,
                },
                "latestCheckpointId": old_session.latest_checkpoint_id,
                "checkpointInspectionPolicy": "none",
            },
            "target": {
                "draftId": target_bundle.draft.id,
                "documentId": target_bundle.document.id,
                "head": {
                    "sequenceNo": target_bundle.draft.head_sequence_no,
                    "documentHash": target_bundle.draft.head_document_hash,
                },
                "checkpoint": {
                    "checkpointId": target_bundle.checkpoint.id,
                    "sequenceNo": target_bundle.checkpoint.checkpoint_sequence_no,
                    "documentObjectHash": target_bundle.checkpoint.document_object_hash,
                    "documentHash": target_bundle.checkpoint.document_hash,
                },
            },
            "newSession": {
                "sessionId": new_session.id,
                "replacesSessionId": old_session.id,
                "recordingKind": new_session.recording_kind,
                "allowSimulatedRoleSwitch": new_session.allow_simulated_role_switch,
                "scenarioId": new_session.scenario_id,
                "scenarioHash": new_session.scenario_hash,
                "source": {
                    "kind": new_session.source_kind,
                    "id": new_session.source_id,
                    "documentObjectHash": new_session.pinned_document_object_hash,
                },
                "identity": {
                    "runtimeCoreVersion": new_session.runtime_core_version,
                    "runtimeCoreBundleHash": new_session.runtime_core_bundle_hash,
                    "stateMachineKernelVersion": new_session.state_machine_kernel_version,
                },
                "head": {
                    "sequenceNo": new_session.head_sequence_no,
                    "stateHash": new_session.head_state_hash,
                    "viewModelHash": new_session.head_view_model_hash,
                },
                "checkpoint": {
                    "checkpointId": new_checkpoint.id,
                    "sequenceNo": new_checkpoint.checkpoint_sequence_no,
                    "stateObjectHash": new_checkpoint.state_object_hash,
                    "stateHash": new_checkpoint.state_hash,
                    "viewModelHash": new_checkpoint.view_model_hash,
                },
            },
            "eventReplayPolicy": "none",
            "resetReason": reset_reason,
            "causeOperationId": cause_operation_id,
            "operation": {
                "operationId": operation.id,
                "clientRequestId": operation.client_request_id,
                "correlationId": operation.correlation_id,
                "resourceKind": operation.resource_kind,
                "resourceId": operation.resource_id,
                "parentOperationId": operation.parent_operation_id,
                "occurredAt": occurred_at.isoformat(),
            },
        }

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

    def _require_snap_attester(self) -> PrototypeSnapAttestation:
        if self._snap_attester is None:
            raise StructuredPrototypeServiceError(
                "snap_worker_unavailable",
                "prototype snap worker is unavailable",
            )
        return self._snap_attester

    async def _attest_snap_evidence(
        self,
        *,
        request_id: str,
        evidence_json: str,
    ) -> PrototypeSnapWorkerAttestationResult:
        worker = self._require_snap_attester()
        try:
            return await worker.attest(
                request_id=request_id,
                evidence_json=evidence_json,
            )
        except PrototypeSnapWorkerError as exc:
            if exc.code in {"snap_attestation_mismatch", "snap_evidence_invalid"}:
                raise StructuredPrototypeContractError(
                    "command_evidence_mismatch",
                    "freeform move evidence does not match the pinned snap solver",
                ) from exc
            raise StructuredPrototypeServiceError(exc.code, str(exc)) from exc

    async def _attest_snap_evidence_many(
        self,
        *,
        request_id: str,
        evidence_jsons: tuple[str, ...],
    ) -> tuple[PrototypeSnapWorkerAttestationResult, ...]:
        if not evidence_jsons:
            return ()
        worker = self._require_snap_attester()
        try:
            return await worker.attest_many(
                request_id=request_id,
                evidence_jsons=list(evidence_jsons),
            )
        except PrototypeSnapWorkerError as exc:
            if exc.code in {"snap_attestation_mismatch", "snap_evidence_invalid"}:
                raise StructuredPrototypeContractError(
                    "command_evidence_mismatch",
                    "stored freeform move evidence does not match the pinned snap solver",
                ) from exc
            raise StructuredPrototypeServiceError(exc.code, str(exc)) from exc

    async def _handle_runtime_recovery_failure(
        self,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        session: PrototypeRuntimeSessionRecord,
        error_code: str,
        *,
        force_corruption: bool = False,
    ) -> None:
        failed, failed_step, event = self._failed_transition(operation, step, error_code)
        if not force_corruption and error_code not in CORRUPTION_ERROR_CODES:
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
        parent_operation_id: str | None = None,
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
            parent_operation_id=parent_operation_id,
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
        identity = self._snap_attester.identity if self._snap_attester is not None else None
        manifest: dict[str, object] = {
            "serviceVersion": SERVICE_VERSION,
            "documentSchemaVersion": DOCUMENT_SCHEMA_VERSION,
            "commandContractVersion": COMMAND_CONTRACT_VERSION,
            "canonicalizerVersion": CANONICALIZER_VERSION,
            "operationEvidenceVersion": OPERATION_EVIDENCE_VERSION,
            "snapWorkerAvailable": identity is not None,
        }
        if identity is not None:
            manifest.update(
                {
                    "snapWorkerProtocolVersion": identity.protocol_version,
                    "snapSolverVersion": identity.snap_solver_version,
                    "snapSolverSourceHash": identity.snap_solver_source_hash,
                    "snapSolverBundleHash": identity.snap_solver_bundle_hash,
                }
            )
        return _manifest_hash(manifest)

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
        operation_id: str | None,
        session: PrototypeRuntimeSessionRecord | None = None,
    ) -> StructuredPrototypeServiceError:
        return StructuredPrototypeServiceError(
            code,
            message,
            operation_id=operation_id,
            current_head_sequence_no=(session.head_sequence_no if session is not None else None),
            current_state_hash=session.head_state_hash if session is not None else None,
            current_view_model_hash=(session.head_view_model_hash if session is not None else None),
            runtime_core_bundle_hash=(
                session.runtime_core_bundle_hash if session is not None else None
            ),
            resource_url=(
                f"/api/structured-prototype-runtime-sessions/{session.id}/reset"
                if session is not None
                and code
                in {
                    "runtime_replay_version_mismatch",
                    "runtime_replay_contract_unsupported",
                    "runtime_session_corrupt",
                }
                else None
            ),
        )
