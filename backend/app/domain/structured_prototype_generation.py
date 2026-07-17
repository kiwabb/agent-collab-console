from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.domain.structured_prototype import (
    PrototypeCheckpointRecord,
    PrototypeDocumentRecord,
    PrototypeDraftRecord,
    PrototypeOperation,
    PrototypeOperationStep,
)

PrototypeDocumentGenerationJobStatus = Literal[
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
PrototypeDocumentGenerationRunStatus = Literal[
    "queued",
    "running",
    "completed",
    "failed",
    "interrupted",
    "cancelled",
]
PrototypeDocumentGenerationItemKind = Literal["blueprint", "foundation", "page"]
PrototypeDocumentGenerationItemStatus = Literal[
    "pending",
    "generating",
    "validating",
    "done",
    "failed",
    "interrupted",
]
PrototypeGenerationSourcePolicy = Literal["committed_head_v1"]
PrototypeGenerationSourceFileExclusionPolicy = Literal["dotenv_checkout_filter_v1"]


@dataclass(frozen=True, slots=True)
class PrototypeGenerationCommittedHeadCapture:
    snapshot_ref: str
    repository_object_format: str
    worktree_base_commit: str
    repository_project_prefix: str
    repository_tree_object_id: str
    source_file_exclusion_policy: PrototypeGenerationSourceFileExclusionPolicy
    working_tree_dirty: bool
    excluded_tracked_change_count: int
    excluded_untracked_count: int
    excluded_sensitive_file_count: int
    excluded_status_hash: str


@dataclass(frozen=True, slots=True)
class PrototypeGenerationSourceSnapshot:
    source_policy: PrototypeGenerationSourcePolicy
    source_snapshot_object_hash: str
    source_fingerprint: str
    source_snapshot_ref: str
    repository_object_format: str
    worktree_base_commit: str
    repository_project_prefix: str
    repository_tree_object_id: str
    source_file_exclusion_policy: PrototypeGenerationSourceFileExclusionPolicy
    working_tree_dirty: bool
    excluded_tracked_change_count: int
    excluded_untracked_count: int
    excluded_sensitive_file_count: int
    excluded_status_hash: str


@dataclass(frozen=True, slots=True)
class PrototypeDocumentGenerationJobRecord:
    id: str
    project_id: str
    client_request_id: str
    status: PrototypeDocumentGenerationJobStatus
    operation_id: str
    request_manifest_object_hash: str
    request_hash: str
    context_manifest_object_hash: str
    blueprint_object_hash: str | None
    blueprint_version: int
    blueprint_hash: str | None
    candidate_object_hash: str | None
    candidate_document_hash: str | None
    preview_render_run_id: str | None
    preview_artifact_id: str | None
    preview_renderer_version: str | None
    preview_storage_key: str | None
    preview_output_hash: str | None
    preview_output_manifest_hash: str | None
    preview_visual_preflight_report_hash: str | None
    replay_manifest_object_hash: str | None
    document_id: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    # Nullable only for rows created before committed_head_v1 was introduced.
    source_policy: PrototypeGenerationSourcePolicy | None = None
    source_snapshot_object_hash: str | None = None
    source_fingerprint: str | None = None
    source_snapshot_ref: str | None = None
    repository_object_format: str | None = None
    worktree_base_commit: str | None = None
    repository_project_prefix: str | None = None
    repository_tree_object_id: str | None = None
    working_tree_dirty: bool | None = None
    excluded_tracked_change_count: int | None = None
    excluded_untracked_count: int | None = None
    source_file_exclusion_policy: PrototypeGenerationSourceFileExclusionPolicy | None = None
    excluded_sensitive_file_count: int | None = None
    excluded_status_hash: str | None = None


@dataclass(frozen=True, slots=True)
class PrototypeDocumentGenerationRunRecord:
    id: str
    job_id: str
    status: PrototypeDocumentGenerationRunStatus
    blueprint_hash: str | None
    total: int
    processed: int
    succeeded: int
    failed: int
    running: int
    pending: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class PrototypeDocumentGenerationItemRecord:
    id: str
    job_id: str
    run_id: str
    kind: PrototypeDocumentGenerationItemKind
    item_key: str
    page_key: str | None
    item_ordinal: int
    status: PrototypeDocumentGenerationItemStatus
    phase: str
    attempt: int
    task_kind: str
    operation_id: str
    context_object_hash: str
    submission_id: str | None
    submission_request_hash: str | None
    submission_normalized_fields: tuple[str, ...]
    submission_accepted_at: datetime | None
    output_object_hash: str | None
    task_id: str | None
    execution_process_id: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class PrototypeDocumentGenerationSnapshot:
    job: PrototypeDocumentGenerationJobRecord
    latest_run: PrototypeDocumentGenerationRunRecord | None
    items: tuple[PrototypeDocumentGenerationItemRecord, ...]


@dataclass(frozen=True, slots=True)
class PrototypeDocumentGenerationCreateResult:
    snapshot: PrototypeDocumentGenerationSnapshot
    created: bool


@dataclass(frozen=True, slots=True)
class PrototypeDocumentGenerationRunCreateResult:
    snapshot: PrototypeDocumentGenerationSnapshot
    created: bool


@dataclass(frozen=True, slots=True)
class PrototypeDocumentGenerationConfirmResult:
    operation_id: str
    correlation_id: str
    snapshot: PrototypeDocumentGenerationSnapshot


@dataclass(frozen=True, slots=True)
class PrototypeDocumentGenerationAcceptResult:
    operation_id: str
    correlation_id: str
    snapshot: PrototypeDocumentGenerationSnapshot
    document: PrototypeDocumentRecord
    draft: PrototypeDraftRecord
    checkpoint: PrototypeCheckpointRecord


@dataclass(frozen=True, slots=True)
class PrototypeGenerationRestartOperationTarget:
    operation: PrototypeOperation
    active_step: PrototypeOperationStep | None
    next_step_ordinal: int
    next_event_no: int


@dataclass(frozen=True, slots=True)
class PrototypeGenerationRestartRecoveryScope:
    fingerprint: str
    operations: tuple[PrototypeGenerationRestartOperationTarget, ...]
    affected_root_count: int
    active_job_count: int
    active_run_count: int
    active_item_count: int
