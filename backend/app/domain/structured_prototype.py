from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

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
    "generation_request_manifest",
    "generation_context_manifest",
    "generation_blueprint",
    "generation_foundation",
    "generation_page",
    "ai_edit_context_manifest",
    "agent_submission",
    "validation_report",
    "replay_manifest",
    "prototype_runtime_state",
    "runtime_transition_report",
    "runtime_replay_manifest",
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
    "generation_job",
    "generation_item",
    "ai_edit",
    "reject_ai_proposal",
    "semantic_repair",
    "render_preview",
    "publish",
    "create_runtime_session",
    "apply_runtime_event",
    "replay_runtime_session",
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
    status: str
    phase: str
    input_hash: str | None
    output_hash: str | None
    evidence_hash: str | None
    error_code: str | None
    occurred_at: datetime


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
class PrototypeDraftRecoveryBundle:
    document: PrototypeDocumentRecord
    draft: PrototypeDraftRecord
    checkpoint: PrototypeCheckpointRecord
    object_descriptor: PrototypeObjectDescriptor
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
