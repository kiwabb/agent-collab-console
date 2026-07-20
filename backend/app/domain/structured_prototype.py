from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

PROTOTYPE_FORWARD_COMMAND_BATCH_MAX_BYTES = 262_144
REPLAY_MANIFEST_SCHEMA_VERSION = 1
_CONTENT_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_REPLAY_MANIFEST_KEYS = frozenset(
    {
        "manifestVersion",
        "operationId",
        "operationKind",
        "parentOperationId",
        "requestManifestHash",
        "contextManifestHash",
        "orderedInputObjectHashes",
        "versions",
        "agentTaskIdentity",
        "submissionHash",
        "orderedCommandBatchHashes",
        "baseCheckpointHash",
        "baseSequenceNo",
        "resultCheckpointHash",
        "resultSequenceNo",
        "rendererInputHash",
        "rendererOutputHash",
        "runtimeSessionId",
        "runtimeCoreBundleHash",
        "orderedRuntimeEventHashes",
        "runtimeFinalStateHash",
        "runtimeFinalViewModelHash",
        "validationReportHashes",
        "terminalStatus",
        "errorCode",
    }
)
_REPLAY_VERSION_KEYS = frozenset(
    {
        "serviceVersion",
        "documentSchemaVersion",
        "commandContractVersion",
        "runtimeStateSchemaVersion",
        "runtimeEventContractVersion",
        "runtimeCoreVersion",
        "runtimeCoreBundleHash",
        "stateMachineKernelVersion",
        "rendererVersion",
        "rendererEnvironmentVersion",
        "replayManifestVersion",
    }
)


class PrototypeReplayManifestError(ValueError):
    pass


def _manifest_hash(value: object, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or _CONTENT_HASH_RE.fullmatch(value) is None:
        raise PrototypeReplayManifestError(f"{field} must be a SHA-256 content hash")
    return value


def _manifest_string(value: object, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value:
        raise PrototypeReplayManifestError(f"{field} must be a non-empty string")
    return value


def _manifest_sequence(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PrototypeReplayManifestError(f"{field} must be an array")
    result: list[str] = []
    for index, item in enumerate(value):
        result.append(_manifest_hash(item, f"{field}[{index}]") or "")
    return tuple(result)


def _manifest_sequence_no(value: object, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PrototypeReplayManifestError(f"{field} must be a non-negative integer or null")
    return value


@dataclass(frozen=True, slots=True)
class PrototypeReplayManifestVersionsV1:
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
    replay_manifest_version: int = REPLAY_MANIFEST_SCHEMA_VERSION

    def to_payload(self) -> dict[str, object]:
        return {
            "serviceVersion": self.service_version,
            "documentSchemaVersion": self.document_schema_version,
            "commandContractVersion": self.command_contract_version,
            "runtimeStateSchemaVersion": self.runtime_state_schema_version,
            "runtimeEventContractVersion": self.runtime_event_contract_version,
            "runtimeCoreVersion": self.runtime_core_version,
            "runtimeCoreBundleHash": self.runtime_core_bundle_hash,
            "stateMachineKernelVersion": self.state_machine_kernel_version,
            "rendererVersion": self.renderer_version,
            "rendererEnvironmentVersion": self.renderer_environment_version,
            "replayManifestVersion": self.replay_manifest_version,
        }

    @classmethod
    def from_payload(cls, value: object) -> PrototypeReplayManifestVersionsV1:
        if not isinstance(value, dict):
            raise PrototypeReplayManifestError("versions must be an object")
        payload: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise PrototypeReplayManifestError("versions keys must be strings")
            payload[key] = item
        if frozenset(payload) != _REPLAY_VERSION_KEYS:
            raise PrototypeReplayManifestError("versions keys do not match replay manifest v1")
        positive_int_fields = (
            "documentSchemaVersion",
            "commandContractVersion",
            "runtimeStateSchemaVersion",
            "runtimeEventContractVersion",
            "replayManifestVersion",
        )
        parsed_ints: dict[str, int] = {}
        for field in positive_int_fields:
            field_value = payload[field]
            if (
                isinstance(field_value, bool)
                or not isinstance(field_value, int)
                or field_value <= 0
            ):
                raise PrototypeReplayManifestError(f"versions.{field} must be a positive integer")
            parsed_ints[field] = field_value
        if parsed_ints["replayManifestVersion"] != REPLAY_MANIFEST_SCHEMA_VERSION:
            raise PrototypeReplayManifestError("versions.replayManifestVersion is unsupported")
        return cls(
            service_version=_manifest_string(payload["serviceVersion"], "versions.serviceVersion")
            or "",
            document_schema_version=parsed_ints["documentSchemaVersion"],
            command_contract_version=parsed_ints["commandContractVersion"],
            runtime_state_schema_version=parsed_ints["runtimeStateSchemaVersion"],
            runtime_event_contract_version=parsed_ints["runtimeEventContractVersion"],
            runtime_core_version=_manifest_string(
                payload["runtimeCoreVersion"], "versions.runtimeCoreVersion", nullable=True
            ),
            runtime_core_bundle_hash=_manifest_hash(
                payload["runtimeCoreBundleHash"],
                "versions.runtimeCoreBundleHash",
                nullable=True,
            ),
            state_machine_kernel_version=_manifest_string(
                payload["stateMachineKernelVersion"],
                "versions.stateMachineKernelVersion",
                nullable=True,
            ),
            renderer_version=_manifest_string(
                payload["rendererVersion"], "versions.rendererVersion", nullable=True
            ),
            renderer_environment_version=_manifest_string(
                payload["rendererEnvironmentVersion"],
                "versions.rendererEnvironmentVersion",
                nullable=True,
            ),
            replay_manifest_version=parsed_ints["replayManifestVersion"],
        )


@dataclass(frozen=True, slots=True)
class PrototypeReplayManifestV1:
    operation_id: str
    operation_kind: PrototypeOperationKind
    parent_operation_id: str | None
    request_manifest_hash: str
    context_manifest_hash: str | None
    ordered_input_object_hashes: tuple[str, ...]
    versions: PrototypeReplayManifestVersionsV1
    agent_task_identity: dict[str, str] | None
    submission_hash: str | None
    ordered_command_batch_hashes: tuple[str, ...]
    base_checkpoint_hash: str | None
    base_sequence_no: int | None
    result_checkpoint_hash: str | None
    result_sequence_no: int | None
    renderer_input_hash: str | None
    renderer_output_hash: str | None
    runtime_session_id: str | None
    runtime_core_bundle_hash: str | None
    ordered_runtime_event_hashes: tuple[str, ...]
    runtime_final_state_hash: str | None
    runtime_final_view_model_hash: str | None
    validation_report_hashes: tuple[str, ...]
    terminal_status: Literal["succeeded"]
    error_code: None

    def to_payload(self) -> dict[str, object]:
        return {
            "manifestVersion": REPLAY_MANIFEST_SCHEMA_VERSION,
            "operationId": self.operation_id,
            "operationKind": self.operation_kind,
            "parentOperationId": self.parent_operation_id,
            "requestManifestHash": self.request_manifest_hash,
            "contextManifestHash": self.context_manifest_hash,
            "orderedInputObjectHashes": list(self.ordered_input_object_hashes),
            "versions": self.versions.to_payload(),
            "agentTaskIdentity": self.agent_task_identity,
            "submissionHash": self.submission_hash,
            "orderedCommandBatchHashes": list(self.ordered_command_batch_hashes),
            "baseCheckpointHash": self.base_checkpoint_hash,
            "baseSequenceNo": self.base_sequence_no,
            "resultCheckpointHash": self.result_checkpoint_hash,
            "resultSequenceNo": self.result_sequence_no,
            "rendererInputHash": self.renderer_input_hash,
            "rendererOutputHash": self.renderer_output_hash,
            "runtimeSessionId": self.runtime_session_id,
            "runtimeCoreBundleHash": self.runtime_core_bundle_hash,
            "orderedRuntimeEventHashes": list(self.ordered_runtime_event_hashes),
            "runtimeFinalStateHash": self.runtime_final_state_hash,
            "runtimeFinalViewModelHash": self.runtime_final_view_model_hash,
            "validationReportHashes": list(self.validation_report_hashes),
            "terminalStatus": self.terminal_status,
            "errorCode": self.error_code,
        }

    @classmethod
    def from_canonical_json(cls, canonical_bytes: bytes) -> PrototypeReplayManifestV1:
        try:
            decoded = canonical_bytes.decode("utf-8")
            value: object = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PrototypeReplayManifestError("replay manifest object is not JSON") from exc
        return cls.from_payload(value)

    @classmethod
    def from_payload(cls, value: object) -> PrototypeReplayManifestV1:
        if not isinstance(value, dict):
            raise PrototypeReplayManifestError("replay manifest must be an object")
        payload: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise PrototypeReplayManifestError("replay manifest keys must be strings")
            payload[key] = item
        if frozenset(payload) != _REPLAY_MANIFEST_KEYS:
            raise PrototypeReplayManifestError("replay manifest keys do not match v1")
        if payload["manifestVersion"] != REPLAY_MANIFEST_SCHEMA_VERSION:
            raise PrototypeReplayManifestError("replay manifest version is unsupported")
        operation_kind = _manifest_string(payload["operationKind"], "operationKind")
        valid_operation_kinds = {
            "create_document",
            "apply_command_batch",
            "undo",
            "redo",
            "create_checkpoint",
            "recover_draft",
            "delete_project_prototype",
            "generation_job",
            "generation_item",
            "ai_edit",
            "reject_ai_proposal",
            "semantic_repair",
            "render_preview",
            "publish",
            "rollback_publication",
            "create_runtime_session",
            "apply_runtime_event",
            "replay_runtime_session",
            "reset_runtime_session",
            "gc_run",
            "diagnostic_replay",
        }
        if operation_kind not in valid_operation_kinds:
            raise PrototypeReplayManifestError("operationKind is unsupported")
        agent_task_identity_value = payload["agentTaskIdentity"]
        agent_task_identity: dict[str, str] | None
        if agent_task_identity_value is None:
            agent_task_identity = None
        elif isinstance(agent_task_identity_value, dict):
            agent_task_identity = {}
            for key, item in agent_task_identity_value.items():
                if not isinstance(key, str) or not isinstance(item, str) or not key or not item:
                    raise PrototypeReplayManifestError(
                        "agentTaskIdentity must contain non-empty string pairs"
                    )
                agent_task_identity[key] = item
            if not agent_task_identity:
                raise PrototypeReplayManifestError("agentTaskIdentity must be null or non-empty")
        else:
            raise PrototypeReplayManifestError("agentTaskIdentity must be an object or null")
        terminal_status = payload["terminalStatus"]
        if terminal_status != "succeeded" or payload["errorCode"] is not None:
            raise PrototypeReplayManifestError(
                "successful replay manifests require terminalStatus=succeeded and errorCode=null"
            )
        runtime_core_bundle_hash = _manifest_hash(
            payload["runtimeCoreBundleHash"], "runtimeCoreBundleHash", nullable=True
        )
        versions = PrototypeReplayManifestVersionsV1.from_payload(payload["versions"])
        if versions.runtime_core_bundle_hash != runtime_core_bundle_hash:
            raise PrototypeReplayManifestError(
                "runtimeCoreBundleHash must match versions.runtimeCoreBundleHash"
            )
        return cls(
            operation_id=_manifest_string(payload["operationId"], "operationId") or "",
            operation_kind=cast(PrototypeOperationKind, operation_kind),
            parent_operation_id=_manifest_string(
                payload["parentOperationId"], "parentOperationId", nullable=True
            ),
            request_manifest_hash=_manifest_hash(
                payload["requestManifestHash"], "requestManifestHash"
            )
            or "",
            context_manifest_hash=_manifest_hash(
                payload["contextManifestHash"], "contextManifestHash", nullable=True
            ),
            ordered_input_object_hashes=_manifest_sequence(
                payload["orderedInputObjectHashes"], "orderedInputObjectHashes"
            ),
            versions=versions,
            agent_task_identity=agent_task_identity,
            submission_hash=_manifest_hash(
                payload["submissionHash"], "submissionHash", nullable=True
            ),
            ordered_command_batch_hashes=_manifest_sequence(
                payload["orderedCommandBatchHashes"], "orderedCommandBatchHashes"
            ),
            base_checkpoint_hash=_manifest_hash(
                payload["baseCheckpointHash"], "baseCheckpointHash", nullable=True
            ),
            base_sequence_no=_manifest_sequence_no(payload["baseSequenceNo"], "baseSequenceNo"),
            result_checkpoint_hash=_manifest_hash(
                payload["resultCheckpointHash"], "resultCheckpointHash", nullable=True
            ),
            result_sequence_no=_manifest_sequence_no(
                payload["resultSequenceNo"], "resultSequenceNo"
            ),
            renderer_input_hash=_manifest_hash(
                payload["rendererInputHash"], "rendererInputHash", nullable=True
            ),
            renderer_output_hash=_manifest_hash(
                payload["rendererOutputHash"], "rendererOutputHash", nullable=True
            ),
            runtime_session_id=_manifest_string(
                payload["runtimeSessionId"], "runtimeSessionId", nullable=True
            ),
            runtime_core_bundle_hash=runtime_core_bundle_hash,
            ordered_runtime_event_hashes=_manifest_sequence(
                payload["orderedRuntimeEventHashes"], "orderedRuntimeEventHashes"
            ),
            runtime_final_state_hash=_manifest_hash(
                payload["runtimeFinalStateHash"], "runtimeFinalStateHash", nullable=True
            ),
            runtime_final_view_model_hash=_manifest_hash(
                payload["runtimeFinalViewModelHash"], "runtimeFinalViewModelHash", nullable=True
            ),
            validation_report_hashes=_manifest_sequence(
                payload["validationReportHashes"], "validationReportHashes"
            ),
            terminal_status="succeeded",
            error_code=None,
        )


PrototypeObjectMediaType = Literal["application/json"]
PrototypeObjectStorageCodec = Literal["zstd"]
PrototypeObjectOwnerKind = Literal[
    "checkpoint",
    "generation_job",
    "generation_run",
    "generation_item",
    "ai_edit_run",
    "render_run",
    "runtime_session",
    "runtime_checkpoint",
    "replay_manifest",
]
PrototypeObjectPayloadType = Literal[
    "prototype_document",
    "prototype_command_history_checkpoint",
    "generation_request_manifest",
    "generation_context_manifest",
    "generation_source_snapshot_manifest",
    "generation_blueprint",
    "generation_foundation",
    "generation_page",
    "ai_edit_context_manifest",
    "agent_submission",
    "generation_evidence_manifest",
    "validation_report",
    "replay_manifest",
    "prototype_runtime_state",
    "runtime_transition_report",
    "runtime_replay_manifest",
    "runtime_session_reset_manifest",
    "renderer_input_manifest",
    "renderer_output_manifest",
    "visual_preflight_report",
]
PrototypeOperationKind = Literal[
    "create_document",
    "apply_command_batch",
    "undo",
    "redo",
    "create_checkpoint",
    "recover_draft",
    "delete_project_prototype",
    "generation_job",
    "generation_item",
    "ai_edit",
    "reject_ai_proposal",
    "semantic_repair",
    "render_preview",
    "publish",
    "rollback_publication",
    "create_runtime_session",
    "apply_runtime_event",
    "replay_runtime_session",
    "reset_runtime_session",
    "gc_run",
    "diagnostic_replay",
]
PrototypeOperationStatus = Literal[
    "queued",
    "running",
    "succeeded",
    "failed",
    "interrupted",
    "cancelled",
]
PrototypeOperationStepStatus = Literal[
    "pending",
    "running",
    "succeeded",
    "failed",
    "skipped",
    "interrupted",
]
PrototypeOperationEventStatus = Literal[
    "queued",
    "pending",
    "running",
    "succeeded",
    "failed",
    "skipped",
    "interrupted",
    "cancelled",
]
PrototypeDraftStatus = Literal["active", "publishing", "closed", "corrupt"]
PrototypeCheckpointKind = Literal["draft", "revision", "generation_accept", "ai_apply"]
PrototypeCommandOrigin = Literal["user", "ai", "system"]
PrototypeCommandOperationKind = Literal["forward", "undo", "redo"]
PrototypeRuntimeSourceKind = Literal["draft", "ai_preview", "published_revision"]
PrototypeRuntimeSessionStatus = Literal["active", "completed", "interrupted", "corrupt"]
PrototypeRuntimeRecordingKind = Literal[
    "studio_preview",
    "recorded_review",
    "shared_preview",
]
PrototypeRuntimeTransitionOutcome = Literal["applied", "guard_false", "validation_failed"]
PrototypeRevisionSource = Literal["user", "ai", "initial_generation"]
PrototypeRenderKind = Literal["ai_preview", "publication"]
PrototypeRenderStatus = Literal["queued", "rendering", "ready", "failed", "interrupted"]


@dataclass(frozen=True, slots=True)
class PrototypeObjectDescriptor:
    project_id: str
    content_hash: str
    media_type: PrototypeObjectMediaType
    storage_codec: PrototypeObjectStorageCodec
    storage_codec_version: str
    canonical_byte_size: int
    stored_byte_size: int
    storage_hash: str
    storage_key: str
    created_at: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "content_hash": self.content_hash,
            "media_type": self.media_type,
            "storage_codec": self.storage_codec,
            "storage_codec_version": self.storage_codec_version,
            "canonical_byte_size": self.canonical_byte_size,
            "stored_byte_size": self.stored_byte_size,
            "storage_hash": self.storage_hash,
            "storage_key": self.storage_key,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class PrototypeObjectReference:
    project_id: str
    owner_kind: PrototypeObjectOwnerKind
    owner_id: str
    role: str
    content_hash: str
    payload_type: PrototypeObjectPayloadType
    schema_version: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PrototypeOperation:
    id: str
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


@dataclass(frozen=True, slots=True)
class PrototypeOperationStep:
    id: str
    operation_id: str
    parent_step_id: str | None
    step_kind: str
    step_ordinal: int
    attempt: int
    status: PrototypeOperationStepStatus
    phase: str
    input_manifest_hash: str
    config_manifest_hash: str
    output_manifest_hash: str | None
    completion_evidence_kind: str | None
    completion_evidence_ref: str | None
    error_code: str | None
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class PrototypeOperationEvent:
    operation_id: str
    event_no: int
    step_id: str | None
    event_kind: str
    status: PrototypeOperationEventStatus
    phase: str
    input_hash: str | None
    output_hash: str | None
    evidence_hash: str | None
    error_code: str | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class PrototypeOperationObservabilitySnapshot:
    operation: PrototypeOperation
    steps: tuple[PrototypeOperationStep, ...]
    events: tuple[PrototypeOperationEvent, ...]
    child_operations: tuple[PrototypeOperation, ...]


@dataclass(frozen=True, slots=True)
class PrototypeProjectDeletionCounts:
    documents: int
    generation_jobs: int
    object_references: int


@dataclass(frozen=True, slots=True)
class PrototypeDocumentRecord:
    id: str
    project_id: str
    title: str
    published_revision_no: int | None
    active_draft_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PrototypeDraftRecord:
    id: str
    document_id: str
    base_revision_no: int | None
    status: PrototypeDraftStatus
    head_sequence_no: int
    head_document_hash: str
    latest_checkpoint_id: str | None
    publish_revision_no: int | None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None


@dataclass(frozen=True, slots=True)
class PrototypeCheckpointRecord:
    id: str
    document_id: str
    draft_id: str | None
    revision_id: str | None
    checkpoint_kind: PrototypeCheckpointKind
    checkpoint_sequence_no: int
    document_object_hash: str
    document_schema_version: int
    command_contract_version: int
    document_hash: str
    history_snapshot_object_hash: str | None
    history_snapshot_schema_version: int | None
    journal_prefix_hash: str | None
    created_by_operation_id: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PrototypeCommandBatchRecord:
    id: str
    draft_id: str
    base_sequence_no: int
    result_sequence_no: int
    client_request_id: str
    origin: PrototypeCommandOrigin
    operation_kind: PrototypeCommandOperationKind
    target_batch_id: str | None
    command_contract_version: int
    commands_json: str
    inverse_commands_json: str
    command_batch_hash: str
    base_document_hash: str
    result_document_hash: str
    operation_id: str
    created_at: datetime


class PrototypeCommandHistoryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PrototypeCommandHistoryEntry:
    batch_id: str
    command_batch_hash: str

    def to_payload(self) -> dict[str, object]:
        return {
            "batchId": self.batch_id,
            "envelopeHash": self.command_batch_hash,
        }


@dataclass(frozen=True, slots=True)
class PrototypeCommandHistory:
    undo_stack: tuple[PrototypeCommandHistoryEntry, ...]
    redo_stack: tuple[PrototypeCommandHistoryEntry, ...]

    @property
    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self.redo_stack)


def advance_prototype_command_history(
    history: PrototypeCommandHistory,
    batch: PrototypeCommandBatchRecord,
) -> PrototypeCommandHistory:
    entry = PrototypeCommandHistoryEntry(
        batch_id=batch.id,
        command_batch_hash=batch.command_batch_hash,
    )
    if batch.operation_kind == "forward":
        if batch.target_batch_id is not None:
            raise PrototypeCommandHistoryError("forward command batch cannot target another batch")
        return PrototypeCommandHistory(
            undo_stack=(*history.undo_stack, entry),
            redo_stack=(),
        )
    if batch.operation_kind == "undo":
        if not history.undo_stack or batch.target_batch_id != history.undo_stack[-1].batch_id:
            raise PrototypeCommandHistoryError(
                "undo command batch does not target the undo stack top"
            )
        return PrototypeCommandHistory(
            undo_stack=history.undo_stack[:-1],
            redo_stack=(*history.redo_stack, entry),
        )
    if not history.redo_stack or batch.target_batch_id != history.redo_stack[-1].batch_id:
        raise PrototypeCommandHistoryError("redo command batch does not target the redo stack top")
    return PrototypeCommandHistory(
        undo_stack=(*history.undo_stack, entry),
        redo_stack=history.redo_stack[:-1],
    )


def fold_prototype_command_history(
    batches: Sequence[PrototypeCommandBatchRecord],
    *,
    initial_history: PrototypeCommandHistory | None = None,
    expected_base_sequence_no: int = 0,
    expected_base_document_hash: str | None = None,
) -> PrototypeCommandHistory:
    if expected_base_sequence_no < 0:
        raise PrototypeCommandHistoryError("prototype command journal base sequence is invalid")
    history = initial_history or PrototypeCommandHistory(undo_stack=(), redo_stack=())
    previous_result_hash = expected_base_document_hash
    for sequence_no, batch in enumerate(batches, start=expected_base_sequence_no + 1):
        if batch.base_sequence_no != sequence_no - 1 or batch.result_sequence_no != sequence_no:
            raise PrototypeCommandHistoryError(
                "prototype command journal sequence is not continuous"
            )
        if previous_result_hash is not None and batch.base_document_hash != previous_result_hash:
            raise PrototypeCommandHistoryError(
                "prototype command journal hash chain is not continuous"
            )
        history = advance_prototype_command_history(history, batch)
        previous_result_hash = batch.result_document_hash
    return history


@dataclass(frozen=True, slots=True)
class PrototypeCommandHistoryCheckpoint:
    draft_id: str
    checkpoint_sequence_no: int
    checkpoint_document_hash: str
    journal_prefix_hash: str
    history: PrototypeCommandHistory
    snapshot_object_hash: str
    snapshot_schema_version: int

    def to_payload(self) -> dict[str, object]:
        return {
            "schemaVersion": self.snapshot_schema_version,
            "draftId": self.draft_id,
            "checkpointSequenceNo": self.checkpoint_sequence_no,
            "checkpointDocumentHash": self.checkpoint_document_hash,
            "journalPrefixHash": self.journal_prefix_hash,
            "undoStack": [entry.to_payload() for entry in self.history.undo_stack],
            "redoStack": [entry.to_payload() for entry in self.history.redo_stack],
        }


@dataclass(frozen=True, slots=True)
class PrototypeOperationCreateResult:
    operation: PrototypeOperation
    created: bool


@dataclass(frozen=True, slots=True)
class PrototypeCommandAppendResult:
    batch: PrototypeCommandBatchRecord
    draft: PrototypeDraftRecord
    created: bool


@dataclass(frozen=True, slots=True)
class PrototypeRevisionRecord:
    id: str
    document_id: str
    revision_no: int
    schema_version: int
    checkpoint_id: str
    document_object_hash: str
    document_hash: str
    summary: str
    source: PrototypeRevisionSource
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PrototypeRenderRunRecord:
    id: str
    document_id: str
    kind: PrototypeRenderKind
    revision_id: str | None
    ai_edit_run_id: str | None
    status: PrototypeRenderStatus
    renderer_version: str
    renderer_environment_version: str
    runtime_core_version: str
    runtime_core_source_hash: str
    runtime_core_bundle_hash: str
    state_machine_kernel_version: str
    render_runtime_image_hash: str
    browser_version: str
    font_pack_hash: str
    viewport_profile_hash: str
    sandbox_policy_version: str
    input_manifest_hash: str
    document_object_hash: str
    document_hash: str
    operation_id: str
    attempt: int
    artifact_id: str | None
    output_manifest_hash: str | None
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PrototypeRenderArtifactRecord:
    id: str
    render_run_id: str
    document_id: str
    revision_id: str | None
    renderer_version: str
    document_hash: str
    output_hash: str
    output_manifest_hash: str
    storage_key: str
    entrypoint: str
    visual_preflight_report_hash: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PrototypePublicationFreezeResult:
    revision: PrototypeRevisionRecord
    revision_checkpoint: PrototypeCheckpointRecord
    draft: PrototypeDraftRecord
    render_run: PrototypeRenderRunRecord


@dataclass(frozen=True, slots=True)
class PrototypePublicationCompletionResult:
    document: PrototypeDocumentRecord
    revision: PrototypeRevisionRecord
    artifact: PrototypeRenderArtifactRecord
    closed_draft: PrototypeDraftRecord
    active_draft: PrototypeDraftRecord
    active_checkpoint: PrototypeCheckpointRecord


@dataclass(frozen=True, slots=True)
class PrototypePublishedRecord:
    document: PrototypeDocumentRecord
    revision: PrototypeRevisionRecord
    render_run: PrototypeRenderRunRecord
    artifact: PrototypeRenderArtifactRecord


@dataclass(frozen=True, slots=True)
class PrototypeRevisionHistoryEntry:
    revision: PrototypeRevisionRecord
    render_run: PrototypeRenderRunRecord
    artifact: PrototypeRenderArtifactRecord


@dataclass(frozen=True, slots=True)
class PrototypeDraftRecoveryBundle:
    document: PrototypeDocumentRecord
    draft: PrototypeDraftRecord
    checkpoint: PrototypeCheckpointRecord
    object_descriptor: PrototypeObjectDescriptor
    history_object_descriptor: PrototypeObjectDescriptor
    command_batches: tuple[PrototypeCommandBatchRecord, ...]


@dataclass(frozen=True, slots=True)
class PrototypeRuntimeSessionRecord:
    id: str
    project_id: str
    document_id: str
    source_kind: PrototypeRuntimeSourceKind
    source_id: str
    pinned_document_object_hash: str
    runtime_core_version: str
    runtime_core_bundle_hash: str
    state_machine_kernel_version: str
    scenario_id: str
    scenario_hash: str
    status: PrototypeRuntimeSessionStatus
    head_sequence_no: int
    head_state_hash: str
    head_view_model_hash: str
    latest_checkpoint_id: str | None
    recording_kind: PrototypeRuntimeRecordingKind
    allow_simulated_role_switch: bool
    actor_subject_id: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    replaces_session_id: str | None = None


@dataclass(frozen=True, slots=True)
class PrototypeRuntimeEventBatchRecord:
    id: str
    session_id: str
    client_event_id: str
    base_sequence_no: int
    result_sequence_no: int
    events_json: str
    event_batch_hash: str
    matched_rule_ids_json: str
    guard_report_hash: str
    effect_report_hash: str
    outcome: PrototypeRuntimeTransitionOutcome
    base_state_hash: str
    result_state_hash: str
    result_view_model_hash: str
    runtime_core_version: str
    runtime_core_bundle_hash: str
    state_machine_kernel_version: str
    operation_id: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PrototypeRuntimeCheckpointRecord:
    id: str
    session_id: str
    checkpoint_sequence_no: int
    state_object_hash: str
    runtime_state_schema_version: int
    runtime_event_contract_version: int
    state_hash: str
    view_model_hash: str
    created_by_operation_id: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PrototypeRuntimeEventAppendResult:
    event_batch: PrototypeRuntimeEventBatchRecord
    session: PrototypeRuntimeSessionRecord
    created: bool


@dataclass(frozen=True, slots=True)
class PrototypeRuntimeRecoveryBundle:
    session: PrototypeRuntimeSessionRecord
    checkpoint: PrototypeRuntimeCheckpointRecord
    object_descriptor: PrototypeObjectDescriptor
    event_batches: tuple[PrototypeRuntimeEventBatchRecord, ...]


@dataclass(frozen=True, slots=True)
class PrototypeSnapWorkerIdentity:
    protocol_version: str
    snap_solver_version: str
    snap_solver_source_hash: str
    snap_solver_bundle_hash: str
    snap_solver_bundle_byte_size: int
    build_tool: str
    target: str


@dataclass(frozen=True, slots=True)
class PrototypeSnapWorkerAttestationResult:
    evidence_hash: str


@dataclass(frozen=True, slots=True)
class PrototypeRuntimeWorkerIdentity:
    protocol_version: str
    runtime_core_version: str
    runtime_core_source_hash: str
    runtime_core_bundle_hash: str
    runtime_core_bundle_byte_size: int
    state_machine_kernel_version: str
    build_tool: str
    target: str


@dataclass(frozen=True, slots=True)
class PrototypeRuntimeWorkerStateResult:
    state_json: str
    state_hash: str
    view_model_json: str
    view_model_hash: str


@dataclass(frozen=True, slots=True)
class PrototypeRuntimeWorkerTransitionResult:
    client_event_id: str
    base_sequence_no: int
    result_sequence_no: int
    outcome: PrototypeRuntimeTransitionOutcome
    state_json: str
    state_hash: str
    view_model_json: str
    view_model_hash: str
    events_json: str
    event_batch_json: str
    event_batch_hash: str
    matched_rule_ids_json: str
    guard_report_json: str
    guard_report_hash: str
    effect_report_json: str
    effect_report_hash: str


@dataclass(frozen=True, slots=True)
class PrototypeRuntimeWorkerReplayResult:
    transitions: tuple[PrototypeRuntimeWorkerTransitionResult, ...]
    final: PrototypeRuntimeWorkerStateResult


@dataclass(frozen=True, slots=True)
class PrototypeRendererWorkerIdentity:
    protocol_version: str
    renderer_version: str
    renderer_environment_version: str
    renderer_source_hash: str
    runtime_core_version: str
    runtime_core_source_hash: str
    runtime_core_bundle_hash: str
    state_machine_kernel_version: str
    render_runtime_image_hash: str
    browser_version: str
    font_pack_hash: str
    viewport_profile_hash: str
    sandbox_policy_version: str
    public_runtime_hash: str
    public_runtime_byte_size: int
    bundle_hash: str
    bundle_byte_size: int
    build_tool: str
    target: str


@dataclass(frozen=True, slots=True)
class PrototypeRenderedFile:
    relative_path: str
    content: bytes
    byte_size: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class PrototypeRendererWorkerResult:
    input_manifest_hash: str
    output_manifest: dict[str, object]
    output_manifest_hash: str
    visual_preflight_report: dict[str, object]
    visual_preflight_report_hash: str
    bundle_hash: str
    files: tuple[PrototypeRenderedFile, ...]


@dataclass(frozen=True, slots=True)
class PrototypeRenderBundleDescriptor:
    project_id: str
    document_id: str
    artifact_id: str
    storage_key: str
    entrypoint: str
    output_hash: str
    output_manifest_hash: str
    visual_preflight_report_hash: str
    file_count: int
