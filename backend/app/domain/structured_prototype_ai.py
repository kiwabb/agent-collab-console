from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

PrototypeAiThreadStatus = Literal["active", "archived"]
PrototypeAiMessageRole = Literal["user", "assistant"]
PrototypeAiMessageKind = Literal[
    "instruction",
    "answer",
    "clarification",
    "proposal",
    "error",
]
PrototypeAiMessageStatus = Literal["pending", "completed", "failed", "rejected", "applied"]
PrototypeAiEditRunStatus = Literal[
    "queued",
    "building_context",
    "generating",
    "validating",
    "rendering_preview",
    "preview_ready",
    "completed_answer",
    "completed_clarification",
    "applied",
    "rejected",
    "stale",
    "failed",
    "interrupted",
]
PrototypeAiScope = Literal["selection", "page", "document", "flow"]


@dataclass(frozen=True, slots=True)
class PrototypeAiThreadRecord:
    id: str
    document_id: str
    title: str
    status: PrototypeAiThreadStatus
    summary_json: str | None
    summary_through_message_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PrototypeAiMessageRecord:
    id: str
    thread_id: str
    client_message_id: str | None
    role: PrototypeAiMessageRole
    kind: PrototypeAiMessageKind
    content: str
    run_id: str | None
    command_batch_id: str | None
    status: PrototypeAiMessageStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PrototypeAiEditRunRecord:
    id: str
    thread_id: str
    user_message_id: str
    assistant_message_id: str | None
    document_id: str
    draft_id: str
    operation_id: str
    retry_of_run_id: str | None
    status: PrototypeAiEditRunStatus
    scope_json: str
    base_head_sequence_no: int
    base_document_hash: str
    context_object_hash: str | None
    outcome_object_hash: str | None
    submission_id: str | None
    submission_request_hash: str | None
    submission_accepted_at: datetime | None
    replay_manifest_object_hash: str | None
    proposed_command_batch_json: str | None
    proposed_command_batch_hash: str | None
    candidate_object_hash: str | None
    preview_render_run_id: str | None
    preview_artifact_id: str | None
    summary: str | None
    affected_entity_ids_json: str | None
    task_id: str | None
    execution_process_id: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class PrototypeAiMessageRunCreateResult:
    message: PrototypeAiMessageRecord
    run: PrototypeAiEditRunRecord
    created: bool


@dataclass(frozen=True, slots=True)
class PrototypeAiThreadSnapshot:
    thread: PrototypeAiThreadRecord
    messages: tuple[PrototypeAiMessageRecord, ...]
    latest_run: PrototypeAiEditRunRecord | None
