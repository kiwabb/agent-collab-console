from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.domain.structured_prototype import (
    PrototypeCheckpointRecord,
    PrototypeDocumentRecord,
    PrototypeDraftRecord,
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
class PrototypeDocumentGenerationAcceptResult:
    snapshot: PrototypeDocumentGenerationSnapshot
    document: PrototypeDocumentRecord
    draft: PrototypeDraftRecord
    checkpoint: PrototypeCheckpointRecord
