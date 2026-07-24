from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import aiosqlite

from app.adapters.prototype_object_store import canonical_json_bytes
from app.domain.structured_prototype import (
    PROTOTYPE_FORWARD_COMMAND_BATCH_MAX_BYTES,
    PrototypeCheckpointRecord,
    PrototypeCommandAppendResult,
    PrototypeCommandBatchRecord,
    PrototypeCommandHistory,
    PrototypeCommandHistoryCheckpoint,
    PrototypeCommandHistoryError,
    PrototypeDocumentRecord,
    PrototypeDraftRecord,
    PrototypeDraftRecoveryBundle,
    PrototypeObjectDescriptor,
    PrototypeObjectMediaType,
    PrototypeObjectOwnerKind,
    PrototypeObjectPayloadType,
    PrototypeObjectReference,
    PrototypeObjectStorageCodec,
    PrototypeOperation,
    PrototypeOperationCreateResult,
    PrototypeOperationEvent,
    PrototypeOperationKind,
    PrototypeOperationObservabilitySnapshot,
    PrototypeOperationStatus,
    PrototypeOperationStep,
    PrototypeOperationStepStatus,
    PrototypeProjectDeletionCounts,
    PrototypePublicationCompletionResult,
    PrototypePublicationFreezeResult,
    PrototypePublishedRecord,
    PrototypeRenderArtifactRecord,
    PrototypeRenderRunRecord,
    PrototypeRevisionHistoryEntry,
    PrototypeRevisionRecord,
    PrototypeRollbackEventRecord,
    PrototypeRuntimeCheckpointRecord,
    PrototypeRuntimeEventAppendResult,
    PrototypeRuntimeEventBatchRecord,
    PrototypeRuntimeRecoveryBundle,
    PrototypeRuntimeSessionRecord,
    PrototypeRuntimeSessionStatus,
    advance_prototype_command_history,
)
from app.domain.structured_prototype_ai import (
    PrototypeAiEditRunRecord,
    PrototypeAiMessageRecord,
    PrototypeAiMessageRunCreateResult,
    PrototypeAiThreadRecord,
    PrototypeAiThreadSnapshot,
)
from app.domain.structured_prototype_generation import (
    PrototypeDocumentGenerationAcceptResult,
    PrototypeDocumentGenerationConfirmResult,
    PrototypeDocumentGenerationCreateResult,
    PrototypeDocumentGenerationItemRecord,
    PrototypeDocumentGenerationJobRecord,
    PrototypeDocumentGenerationRunCreateResult,
    PrototypeDocumentGenerationRunRecord,
    PrototypeDocumentGenerationSnapshot,
    PrototypeGenerationRestartOperationTarget,
    PrototypeGenerationRestartRecoveryScope,
    PrototypeGenerationSourceFileExclusionPolicy,
    PrototypeGenerationSourcePolicy,
)

SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
GIT_OBJECT_ID_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
MAX_REPLAY_TAIL_BATCHES = 200
STRUCTURED_PROTOTYPE_CHECKPOINT_HISTORY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("history_snapshot_object_hash", "TEXT"),
    ("history_snapshot_schema_version", "INTEGER"),
    ("journal_prefix_hash", "TEXT"),
)
STRUCTURED_PROTOTYPE_GENERATION_SNAPSHOT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("source_policy", "TEXT"),
    ("source_snapshot_object_hash", "TEXT"),
    ("source_fingerprint", "TEXT"),
    ("source_snapshot_ref", "TEXT"),
    ("repository_object_format", "TEXT"),
    ("worktree_base_commit", "TEXT"),
    ("repository_project_prefix", "TEXT"),
    ("repository_tree_object_id", "TEXT"),
    ("working_tree_dirty", "INTEGER"),
    ("excluded_tracked_change_count", "INTEGER"),
    ("excluded_untracked_count", "INTEGER"),
    ("source_file_exclusion_policy", "TEXT"),
    ("excluded_sensitive_file_count", "INTEGER"),
    ("excluded_status_hash", "TEXT"),
)
STRUCTURED_PROTOTYPE_RUNTIME_SESSION_COLUMNS: tuple[tuple[str, str], ...] = (
    ("replaces_session_id", "TEXT"),
)
STRUCTURED_PROTOTYPE_RUNTIME_SESSION_REPLACEMENT_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_prototype_runtime_sessions_replaces_session
    ON prototype_runtime_sessions(replaces_session_id)
    WHERE replaces_session_id IS NOT NULL
"""


async def _rollback_to_completion(conn: aiosqlite.Connection) -> None:
    rollback_task = asyncio.create_task(conn.rollback())
    while not rollback_task.done():
        try:
            await asyncio.shield(rollback_task)
        except BaseException:
            # Transaction boundary: retain rollback until its result is observable.
            continue
    rollback_task.result()


async def _commit_to_completion(conn: aiosqlite.Connection) -> None:
    commit_task = asyncio.create_task(conn.commit())
    try:
        await asyncio.shield(commit_task)
    except asyncio.CancelledError as cancellation_error:
        while not commit_task.done():
            try:
                await asyncio.shield(commit_task)
            except BaseException:
                # Transaction boundary: retain the task until its result is observable.
                continue
        try:
            commit_task.result()
        except BaseException as commit_error:
            # Transaction boundary: rollback only after commit reports failure.
            await _rollback_to_completion(conn)
            raise commit_error from cancellation_error
        raise
    except BaseException:
        # Transaction boundary: a reported commit failure remains reversible.
        await _rollback_to_completion(conn)
        raise


def _hash_canonical_json(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _initial_journal_prefix_hash(draft_id: str) -> str:
    return _hash_canonical_json(
        {
            "journalPrefixContractVersion": 1,
            "kind": "initial",
            "draftId": draft_id,
        }
    )


def _advance_journal_prefix_hash(previous_hash: str, batch: PrototypeCommandBatchRecord) -> str:
    return _hash_canonical_json(
        {
            "journalPrefixContractVersion": 1,
            "kind": "batch",
            "previousPrefixHash": previous_hash,
            "batchId": batch.id,
            "baseSequenceNo": batch.base_sequence_no,
            "resultSequenceNo": batch.result_sequence_no,
            "envelopeHash": batch.command_batch_hash,
            "baseDocumentHash": batch.base_document_hash,
            "resultDocumentHash": batch.result_document_hash,
        }
    )


STRUCTURED_PROTOTYPE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS prototype_objects (
    project_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    media_type TEXT NOT NULL CHECK (media_type = 'application/json'),
    storage_codec TEXT NOT NULL CHECK (storage_codec = 'zstd'),
    storage_codec_version TEXT NOT NULL,
    canonical_byte_size INTEGER NOT NULL CHECK (canonical_byte_size >= 0),
    stored_byte_size INTEGER NOT NULL CHECK (stored_byte_size >= 0),
    storage_hash TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, content_hash),
    UNIQUE (storage_key)
);

CREATE TABLE IF NOT EXISTS prototype_operations (
    id TEXT PRIMARY KEY,
    operation_kind TEXT NOT NULL,
    project_id TEXT NOT NULL,
    resource_kind TEXT NOT NULL,
    resource_id TEXT,
    client_request_id TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    parent_operation_id TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'interrupted', 'cancelled')
    ),
    phase TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    request_manifest_hash TEXT NOT NULL,
    config_manifest_hash TEXT NOT NULL,
    result_manifest_hash TEXT,
    failure_evidence_hash TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    UNIQUE (project_id, operation_kind, client_request_id),
    FOREIGN KEY (parent_operation_id) REFERENCES prototype_operations(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS prototype_operation_steps (
    id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL,
    parent_step_id TEXT,
    step_kind TEXT NOT NULL,
    step_ordinal INTEGER NOT NULL CHECK (step_ordinal >= 0),
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'running', 'succeeded', 'failed', 'skipped', 'interrupted')
    ),
    phase TEXT NOT NULL,
    input_manifest_hash TEXT NOT NULL,
    config_manifest_hash TEXT NOT NULL,
    output_manifest_hash TEXT,
    completion_evidence_kind TEXT,
    completion_evidence_ref TEXT,
    error_code TEXT,
    started_at TEXT,
    completed_at TEXT,
    UNIQUE (operation_id, step_ordinal, attempt),
    FOREIGN KEY (operation_id) REFERENCES prototype_operations(id) ON DELETE RESTRICT,
    FOREIGN KEY (parent_step_id) REFERENCES prototype_operation_steps(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS prototype_operation_events (
    operation_id TEXT NOT NULL,
    event_no INTEGER NOT NULL CHECK (event_no >= 0),
    step_id TEXT,
    event_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    phase TEXT NOT NULL,
    input_hash TEXT,
    output_hash TEXT,
    evidence_hash TEXT,
    error_code TEXT,
    occurred_at TEXT NOT NULL,
    PRIMARY KEY (operation_id, event_no),
    FOREIGN KEY (operation_id) REFERENCES prototype_operations(id) ON DELETE RESTRICT,
    FOREIGN KEY (step_id) REFERENCES prototype_operation_steps(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS prototype_documents (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    published_revision_no INTEGER,
    active_draft_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (published_revision_no IS NULL OR published_revision_no > 0),
    FOREIGN KEY (active_draft_id) REFERENCES prototype_drafts(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS prototype_drafts (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    base_revision_no INTEGER,
    status TEXT NOT NULL CHECK (status IN ('active', 'publishing', 'closed', 'corrupt')),
    head_sequence_no INTEGER NOT NULL CHECK (head_sequence_no >= 0),
    head_document_hash TEXT NOT NULL,
    latest_checkpoint_id TEXT,
    publish_revision_no INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT,
    CHECK (base_revision_no IS NULL OR base_revision_no > 0),
    CHECK (publish_revision_no IS NULL OR publish_revision_no > 0),
    FOREIGN KEY (document_id) REFERENCES prototype_documents(id) ON DELETE RESTRICT,
    FOREIGN KEY (latest_checkpoint_id) REFERENCES prototype_checkpoints(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS prototype_checkpoints (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    draft_id TEXT,
    revision_id TEXT,
    checkpoint_kind TEXT NOT NULL CHECK (
        checkpoint_kind IN ('draft', 'revision', 'generation_accept', 'ai_apply')
    ),
    checkpoint_sequence_no INTEGER NOT NULL CHECK (checkpoint_sequence_no >= 0),
    document_object_hash TEXT NOT NULL,
    document_schema_version INTEGER NOT NULL CHECK (document_schema_version > 0),
    command_contract_version INTEGER NOT NULL CHECK (command_contract_version > 0),
    document_hash TEXT NOT NULL,
    history_snapshot_object_hash TEXT,
    history_snapshot_schema_version INTEGER CHECK (
        history_snapshot_schema_version IS NULL OR history_snapshot_schema_version > 0
    ),
    journal_prefix_hash TEXT,
    created_by_operation_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (document_hash = document_object_hash),
    CHECK ((draft_id IS NULL) <> (revision_id IS NULL)),
    CHECK (
        revision_id IS NOT NULL OR (
            history_snapshot_object_hash IS NOT NULL
            AND history_snapshot_schema_version IS NOT NULL
            AND journal_prefix_hash IS NOT NULL
        )
    ),
    UNIQUE (draft_id, checkpoint_sequence_no),
    UNIQUE (revision_id),
    FOREIGN KEY (document_id) REFERENCES prototype_documents(id) ON DELETE RESTRICT,
    FOREIGN KEY (draft_id) REFERENCES prototype_drafts(id) ON DELETE RESTRICT,
    FOREIGN KEY (created_by_operation_id) REFERENCES prototype_operations(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS prototype_command_batches (
    id TEXT PRIMARY KEY,
    draft_id TEXT NOT NULL,
    base_sequence_no INTEGER NOT NULL CHECK (base_sequence_no >= 0),
    result_sequence_no INTEGER NOT NULL CHECK (result_sequence_no = base_sequence_no + 1),
    client_request_id TEXT NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('user', 'ai', 'system')),
    operation_kind TEXT NOT NULL CHECK (operation_kind IN ('forward', 'undo', 'redo')),
    target_batch_id TEXT,
    command_contract_version INTEGER NOT NULL CHECK (command_contract_version > 0),
    commands_json TEXT NOT NULL,
    inverse_commands_json TEXT NOT NULL,
    command_batch_hash TEXT NOT NULL,
    base_document_hash TEXT NOT NULL,
    result_document_hash TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (draft_id, result_sequence_no),
    UNIQUE (draft_id, client_request_id),
    FOREIGN KEY (draft_id) REFERENCES prototype_drafts(id) ON DELETE RESTRICT,
    FOREIGN KEY (target_batch_id) REFERENCES prototype_command_batches(id) ON DELETE RESTRICT,
    FOREIGN KEY (operation_id) REFERENCES prototype_operations(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS prototype_ai_threads (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'archived')),
    summary_json TEXT,
    summary_through_message_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES prototype_documents(id) ON DELETE RESTRICT,
    FOREIGN KEY (summary_through_message_id)
        REFERENCES prototype_ai_messages(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS prototype_ai_messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    client_message_id TEXT,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    kind TEXT NOT NULL CHECK (
        kind IN ('instruction', 'answer', 'clarification', 'proposal', 'error')
    ),
    content TEXT NOT NULL,
    run_id TEXT,
    command_batch_id TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'completed', 'failed', 'rejected', 'applied')
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (thread_id, client_message_id),
    FOREIGN KEY (thread_id) REFERENCES prototype_ai_threads(id) ON DELETE RESTRICT,
    FOREIGN KEY (command_batch_id) REFERENCES prototype_command_batches(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS prototype_ai_edit_runs (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    user_message_id TEXT NOT NULL UNIQUE,
    assistant_message_id TEXT UNIQUE,
    document_id TEXT NOT NULL,
    draft_id TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    retry_of_run_id TEXT,
    status TEXT NOT NULL CHECK (
        status IN (
            'queued', 'building_context', 'generating', 'validating',
            'rendering_preview', 'preview_ready', 'completed_answer',
            'completed_clarification', 'applied', 'rejected', 'stale',
            'failed', 'interrupted'
        )
    ),
    scope_json TEXT NOT NULL,
    base_head_sequence_no INTEGER NOT NULL CHECK (base_head_sequence_no >= 0),
    base_document_hash TEXT NOT NULL,
    context_object_hash TEXT,
    outcome_object_hash TEXT,
    submission_id TEXT,
    submission_request_hash TEXT,
    submission_accepted_at TEXT,
    replay_manifest_object_hash TEXT,
    proposed_command_batch_json TEXT,
    proposed_command_batch_hash TEXT,
    candidate_object_hash TEXT,
    preview_render_run_id TEXT,
    preview_artifact_id TEXT,
    summary TEXT,
    affected_entity_ids_json TEXT,
    task_id TEXT,
    execution_process_id TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (thread_id) REFERENCES prototype_ai_threads(id) ON DELETE RESTRICT,
    FOREIGN KEY (user_message_id) REFERENCES prototype_ai_messages(id) ON DELETE RESTRICT,
    FOREIGN KEY (assistant_message_id) REFERENCES prototype_ai_messages(id) ON DELETE RESTRICT,
    FOREIGN KEY (document_id) REFERENCES prototype_documents(id) ON DELETE RESTRICT,
    FOREIGN KEY (draft_id) REFERENCES prototype_drafts(id) ON DELETE RESTRICT,
    FOREIGN KEY (operation_id) REFERENCES prototype_operations(id) ON DELETE RESTRICT,
    FOREIGN KEY (retry_of_run_id) REFERENCES prototype_ai_edit_runs(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS prototype_document_generation_jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    client_request_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'queued', 'planning', 'awaiting_confirmation', 'generating',
            'assembling', 'validating', 'rendering_preview', 'ready',
            'accepted', 'failed', 'interrupted', 'cancelled'
        )
    ),
    operation_id TEXT NOT NULL UNIQUE,
    request_manifest_object_hash TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    context_manifest_object_hash TEXT NOT NULL,
    source_policy TEXT,
    source_snapshot_object_hash TEXT,
    source_fingerprint TEXT,
    source_snapshot_ref TEXT,
    repository_object_format TEXT,
    worktree_base_commit TEXT,
    repository_project_prefix TEXT,
    repository_tree_object_id TEXT,
    working_tree_dirty INTEGER CHECK (working_tree_dirty IN (0, 1)),
    excluded_tracked_change_count INTEGER CHECK (excluded_tracked_change_count >= 0),
    excluded_untracked_count INTEGER CHECK (excluded_untracked_count >= 0),
    source_file_exclusion_policy TEXT,
    excluded_sensitive_file_count INTEGER CHECK (excluded_sensitive_file_count >= 0),
    excluded_status_hash TEXT,
    blueprint_object_hash TEXT,
    blueprint_version INTEGER NOT NULL CHECK (blueprint_version >= 0),
    blueprint_hash TEXT,
    candidate_object_hash TEXT,
    candidate_document_hash TEXT,
    preview_render_run_id TEXT,
    preview_artifact_id TEXT,
    preview_renderer_version TEXT,
    preview_storage_key TEXT,
    preview_output_hash TEXT,
    preview_output_manifest_hash TEXT,
    preview_visual_preflight_report_hash TEXT,
    replay_manifest_object_hash TEXT,
    document_id TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE (project_id, client_request_id),
    FOREIGN KEY (operation_id) REFERENCES prototype_operations(id) ON DELETE RESTRICT,
    FOREIGN KEY (document_id) REFERENCES prototype_documents(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS prototype_document_generation_runs (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'running', 'completed', 'failed', 'interrupted', 'cancelled')
    ),
    blueprint_hash TEXT,
    total INTEGER NOT NULL CHECK (total > 0),
    processed INTEGER NOT NULL CHECK (processed >= 0),
    succeeded INTEGER NOT NULL CHECK (succeeded >= 0),
    failed INTEGER NOT NULL CHECK (failed >= 0),
    running INTEGER NOT NULL CHECK (running >= 0),
    pending INTEGER NOT NULL CHECK (pending >= 0),
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    FOREIGN KEY (job_id) REFERENCES prototype_document_generation_jobs(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS prototype_document_generation_run_items (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('blueprint', 'foundation', 'page')),
    item_key TEXT NOT NULL,
    page_key TEXT,
    item_ordinal INTEGER NOT NULL CHECK (item_ordinal >= 0),
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'generating', 'validating', 'done', 'failed', 'interrupted')
    ),
    phase TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    task_kind TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    context_object_hash TEXT NOT NULL,
    submission_id TEXT,
    submission_request_hash TEXT,
    submission_normalized_fields_json TEXT NOT NULL DEFAULT '[]',
    submission_accepted_at TEXT,
    output_object_hash TEXT,
    task_id TEXT,
    execution_process_id TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE (run_id, kind, item_key),
    UNIQUE (run_id, item_ordinal),
    FOREIGN KEY (job_id) REFERENCES prototype_document_generation_jobs(id) ON DELETE RESTRICT,
    FOREIGN KEY (run_id) REFERENCES prototype_document_generation_runs(id) ON DELETE RESTRICT,
    FOREIGN KEY (operation_id) REFERENCES prototype_operations(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS prototype_revisions (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    revision_no INTEGER NOT NULL CHECK (revision_no > 0),
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    checkpoint_id TEXT NOT NULL UNIQUE,
    document_object_hash TEXT NOT NULL,
    document_hash TEXT NOT NULL,
    summary TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('user', 'ai', 'initial_generation')),
    created_at TEXT NOT NULL,
    CHECK (document_hash = document_object_hash),
    UNIQUE (document_id, revision_no),
    FOREIGN KEY (document_id) REFERENCES prototype_documents(id) ON DELETE RESTRICT,
    FOREIGN KEY (checkpoint_id) REFERENCES prototype_checkpoints(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS prototype_render_runs (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('ai_preview', 'publication')),
    revision_id TEXT,
    ai_edit_run_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('queued', 'rendering', 'ready', 'failed', 'interrupted')),
    renderer_version TEXT NOT NULL,
    renderer_environment_version TEXT NOT NULL,
    runtime_core_version TEXT NOT NULL,
    runtime_core_source_hash TEXT NOT NULL,
    runtime_core_bundle_hash TEXT NOT NULL,
    state_machine_kernel_version TEXT NOT NULL,
    render_runtime_image_hash TEXT NOT NULL,
    browser_version TEXT NOT NULL,
    font_pack_hash TEXT NOT NULL,
    viewport_profile_hash TEXT NOT NULL,
    sandbox_policy_version TEXT NOT NULL,
    input_manifest_hash TEXT NOT NULL,
    document_object_hash TEXT NOT NULL,
    document_hash TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    artifact_id TEXT,
    output_manifest_hash TEXT,
    error_code TEXT,
    error_message TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (document_hash = document_object_hash),
    CHECK ((kind = 'publication' AND revision_id IS NOT NULL AND ai_edit_run_id IS NULL)
        OR (kind = 'ai_preview' AND revision_id IS NULL AND ai_edit_run_id IS NOT NULL)),
    UNIQUE (revision_id, attempt),
    FOREIGN KEY (document_id) REFERENCES prototype_documents(id) ON DELETE RESTRICT,
    FOREIGN KEY (revision_id) REFERENCES prototype_revisions(id) ON DELETE RESTRICT,
    FOREIGN KEY (operation_id) REFERENCES prototype_operations(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS prototype_render_artifacts (
    id TEXT PRIMARY KEY,
    render_run_id TEXT NOT NULL UNIQUE,
    document_id TEXT NOT NULL,
    revision_id TEXT,
    renderer_version TEXT NOT NULL,
    document_hash TEXT NOT NULL,
    output_hash TEXT NOT NULL,
    output_manifest_hash TEXT NOT NULL,
    storage_key TEXT NOT NULL UNIQUE,
    entrypoint TEXT NOT NULL,
    visual_preflight_report_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (render_run_id) REFERENCES prototype_render_runs(id) ON DELETE RESTRICT,
    FOREIGN KEY (document_id) REFERENCES prototype_documents(id) ON DELETE RESTRICT,
    FOREIGN KEY (revision_id) REFERENCES prototype_revisions(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS prototype_object_references (
    project_id TEXT NOT NULL,
    owner_kind TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    payload_type TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    created_at TEXT NOT NULL,
    PRIMARY KEY (
        project_id,
        owner_kind,
        owner_id,
        role,
        content_hash,
        payload_type,
        schema_version
    ),
    FOREIGN KEY (project_id, content_hash)
        REFERENCES prototype_objects(project_id, content_hash)
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS prototype_runtime_sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (
        source_kind IN ('draft', 'ai_preview', 'published_revision')
    ),
    source_id TEXT NOT NULL,
    pinned_document_object_hash TEXT NOT NULL,
    runtime_core_version TEXT NOT NULL,
    runtime_core_bundle_hash TEXT NOT NULL,
    state_machine_kernel_version TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    scenario_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('active', 'completed', 'interrupted', 'corrupt')
    ),
    head_sequence_no INTEGER NOT NULL CHECK (head_sequence_no >= 0),
    head_state_hash TEXT NOT NULL,
    head_view_model_hash TEXT NOT NULL,
    latest_checkpoint_id TEXT,
    recording_kind TEXT NOT NULL CHECK (
        recording_kind IN ('studio_preview', 'recorded_review', 'shared_preview')
    ),
    allow_simulated_role_switch INTEGER NOT NULL CHECK (
        allow_simulated_role_switch IN (0, 1)
    ),
    actor_subject_id TEXT,
    replaces_session_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (document_id) REFERENCES prototype_documents(id) ON DELETE RESTRICT,
    FOREIGN KEY (latest_checkpoint_id)
        REFERENCES prototype_runtime_checkpoints(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS prototype_runtime_event_batches (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    client_event_id TEXT NOT NULL,
    base_sequence_no INTEGER NOT NULL CHECK (base_sequence_no >= 0),
    result_sequence_no INTEGER NOT NULL CHECK (result_sequence_no = base_sequence_no + 1),
    events_json TEXT NOT NULL,
    event_batch_hash TEXT NOT NULL,
    matched_rule_ids_json TEXT NOT NULL,
    guard_report_hash TEXT NOT NULL,
    effect_report_hash TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (
        outcome IN ('applied', 'guard_false', 'validation_failed')
    ),
    base_state_hash TEXT NOT NULL,
    result_state_hash TEXT NOT NULL,
    result_view_model_hash TEXT NOT NULL,
    runtime_core_version TEXT NOT NULL,
    runtime_core_bundle_hash TEXT NOT NULL,
    state_machine_kernel_version TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (session_id, client_event_id),
    UNIQUE (session_id, result_sequence_no),
    FOREIGN KEY (session_id) REFERENCES prototype_runtime_sessions(id) ON DELETE RESTRICT,
    FOREIGN KEY (operation_id) REFERENCES prototype_operations(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS prototype_runtime_checkpoints (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    checkpoint_sequence_no INTEGER NOT NULL CHECK (checkpoint_sequence_no >= 0),
    state_object_hash TEXT NOT NULL,
    runtime_state_schema_version INTEGER NOT NULL CHECK (runtime_state_schema_version > 0),
    runtime_event_contract_version INTEGER NOT NULL CHECK (runtime_event_contract_version > 0),
    state_hash TEXT NOT NULL,
    view_model_hash TEXT NOT NULL,
    created_by_operation_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (session_id, checkpoint_sequence_no),
    FOREIGN KEY (session_id) REFERENCES prototype_runtime_sessions(id) ON DELETE RESTRICT,
    FOREIGN KEY (created_by_operation_id) REFERENCES prototype_operations(id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_prototype_documents_one_active_draft
    ON prototype_drafts(document_id)
    WHERE status IN ('active', 'publishing');
CREATE INDEX IF NOT EXISTS idx_prototype_documents_project_updated
    ON prototype_documents(project_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_prototype_command_batches_draft_sequence
    ON prototype_command_batches(draft_id, result_sequence_no);
CREATE INDEX IF NOT EXISTS idx_prototype_checkpoints_draft_sequence
    ON prototype_checkpoints(draft_id, checkpoint_sequence_no);
CREATE INDEX IF NOT EXISTS idx_prototype_operations_project_created
    ON prototype_operations(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_prototype_operation_steps_operation
    ON prototype_operation_steps(operation_id, step_ordinal, attempt);
CREATE INDEX IF NOT EXISTS idx_prototype_object_references_owner
    ON prototype_object_references(project_id, owner_kind, owner_id);
CREATE INDEX IF NOT EXISTS idx_prototype_object_references_hash
    ON prototype_object_references(project_id, content_hash);
CREATE INDEX IF NOT EXISTS idx_prototype_runtime_sessions_document_created
    ON prototype_runtime_sessions(document_id, created_at);
CREATE INDEX IF NOT EXISTS idx_prototype_runtime_sessions_status_updated
    ON prototype_runtime_sessions(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_prototype_runtime_event_batches_session_sequence
    ON prototype_runtime_event_batches(session_id, result_sequence_no);
CREATE INDEX IF NOT EXISTS idx_prototype_runtime_checkpoints_session_sequence
    ON prototype_runtime_checkpoints(session_id, checkpoint_sequence_no);
CREATE INDEX IF NOT EXISTS idx_prototype_revisions_document_revision
    ON prototype_revisions(document_id, revision_no);
CREATE INDEX IF NOT EXISTS idx_prototype_render_runs_document_status
    ON prototype_render_runs(document_id, status);
CREATE INDEX IF NOT EXISTS idx_prototype_render_artifacts_document_revision
    ON prototype_render_artifacts(document_id, revision_id);
CREATE INDEX IF NOT EXISTS idx_prototype_ai_threads_document_updated
    ON prototype_ai_threads(document_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_prototype_ai_messages_thread_created
    ON prototype_ai_messages(thread_id, created_at);
CREATE INDEX IF NOT EXISTS idx_prototype_ai_edit_runs_thread_created
    ON prototype_ai_edit_runs(thread_id, created_at);
CREATE INDEX IF NOT EXISTS idx_prototype_document_generation_jobs_project_created
    ON prototype_document_generation_jobs(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_prototype_document_generation_runs_job_created
    ON prototype_document_generation_runs(job_id, created_at);
CREATE INDEX IF NOT EXISTS idx_prototype_document_generation_items_run_kind
    ON prototype_document_generation_run_items(run_id, kind, item_key);
CREATE UNIQUE INDEX IF NOT EXISTS idx_prototype_document_generation_one_active_project
    ON prototype_document_generation_jobs(project_id)
    WHERE status IN (
        'queued', 'planning', 'awaiting_confirmation', 'generating',
        'assembling', 'validating', 'rendering_preview', 'ready'
    );
CREATE UNIQUE INDEX IF NOT EXISTS idx_prototype_ai_edit_runs_one_active_draft
    ON prototype_ai_edit_runs(draft_id)
    WHERE status IN (
        'queued', 'building_context', 'generating', 'validating', 'rendering_preview'
    );
CREATE UNIQUE INDEX IF NOT EXISTS idx_prototype_ai_edit_runs_one_open_draft
    ON prototype_ai_edit_runs(draft_id)
    WHERE status IN (
        'queued', 'building_context', 'generating', 'validating',
        'rendering_preview', 'preview_ready'
    );
"""


class StructuredPrototypeStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _corrupt(field: str) -> StructuredPrototypeStoreError:
    return StructuredPrototypeStoreError(
        "object_descriptor_corrupt",
        f"prototype persistence field is invalid: {field}",
    )


def _required_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise _corrupt(field)
    return value


def _optional_str(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _required_str(value, field)


def _required_non_negative_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _corrupt(field)
    return value


def _required_positive_int(value: object, field: str) -> int:
    parsed = _required_non_negative_int(value, field)
    if parsed == 0:
        raise _corrupt(field)
    return parsed


def _optional_positive_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _required_positive_int(value, field)


def _required_sqlite_bool(value: object, field: str) -> bool:
    if not isinstance(value, int) or isinstance(value, bool):
        raise _corrupt(field)
    if value == 0:
        return False
    if value == 1:
        return True
    raise _corrupt(field)


def _optional_sqlite_bool(value: object, field: str) -> bool | None:
    if value is None:
        return None
    return _required_sqlite_bool(value, field)


def _optional_non_negative_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _required_non_negative_int(value, field)


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _corrupt(field)
    return value


def _required_hash(value: object, field: str) -> str:
    parsed = _required_str(value, field)
    if SHA256_RE.fullmatch(parsed) is None:
        raise _corrupt(field)
    return parsed


def _optional_hash(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _required_hash(value, field)


def _literal[StringLiteral: str](
    value: object,
    allowed: tuple[StringLiteral, ...],
    field: str,
) -> StringLiteral:
    if isinstance(value, str):
        for candidate in allowed:
            if value == candidate:
                return candidate
    raise _corrupt(field)


def _media_type(value: object) -> PrototypeObjectMediaType:
    return _literal(value, ("application/json",), "media_type")


def _storage_codec(value: object) -> PrototypeObjectStorageCodec:
    return _literal(value, ("zstd",), "storage_codec")


def _owner_kind(value: object) -> PrototypeObjectOwnerKind:
    return _literal(
        value,
        (
            "checkpoint",
            "generation_job",
            "generation_run",
            "generation_item",
            "ai_edit_run",
            "render_run",
            "runtime_session",
            "runtime_checkpoint",
            "replay_manifest",
        ),
        "owner_kind",
    )


def _payload_type(value: object) -> PrototypeObjectPayloadType:
    return _literal(
        value,
        (
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
        ),
        "payload_type",
    )


def _generation_source_policy(value: object) -> PrototypeGenerationSourcePolicy | None:
    if value is None:
        return None
    allowed: tuple[PrototypeGenerationSourcePolicy, ...] = ("committed_head_v1",)
    return _literal(value, allowed, "generation_job.source_policy")


def _generation_source_file_exclusion_policy(
    value: object,
) -> PrototypeGenerationSourceFileExclusionPolicy | None:
    if value is None:
        return None
    allowed: tuple[PrototypeGenerationSourceFileExclusionPolicy, ...] = (
        "dotenv_checkout_filter_v1",
    )
    return _literal(
        value,
        allowed,
        "generation_job.source_file_exclusion_policy",
    )


def _datetime(value: object, field: str) -> datetime:
    raw = _required_str(value, field)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise _corrupt(field) from exc
    if parsed.utcoffset() is None:
        raise _corrupt(field)
    return parsed


def _optional_datetime(value: object, field: str) -> datetime | None:
    if value is None:
        return None
    return _datetime(value, field)


def _string_tuple_from_json(value: object, field: str) -> tuple[str, ...]:
    raw = _required_str(value, field)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _corrupt(field) from exc
    if (
        not isinstance(parsed, list)
        or any(not isinstance(item, str) or not item for item in parsed)
        or len(set(parsed)) != len(parsed)
    ):
        raise _corrupt(field)
    return tuple(parsed)


class AsyncStructuredPrototypeStore:
    _AI_EDIT_RUN_COLUMNS = """
        id, thread_id, user_message_id, assistant_message_id, document_id,
        draft_id, operation_id, retry_of_run_id, status, scope_json,
        base_head_sequence_no, base_document_hash, context_object_hash,
        outcome_object_hash, submission_id, submission_request_hash,
        submission_accepted_at, replay_manifest_object_hash,
        proposed_command_batch_json,
        proposed_command_batch_hash, candidate_object_hash,
        preview_render_run_id, preview_artifact_id, summary,
        affected_entity_ids_json, task_id, execution_process_id, error_code,
        error_message, created_at, updated_at, completed_at
    """
    _GENERATION_JOB_COLUMNS = """
        id, project_id, client_request_id, status, operation_id,
        request_manifest_object_hash, request_hash, context_manifest_object_hash,
        source_policy, source_snapshot_object_hash, source_fingerprint,
        source_snapshot_ref, repository_object_format, worktree_base_commit,
        repository_project_prefix, repository_tree_object_id, working_tree_dirty,
        excluded_tracked_change_count, excluded_untracked_count,
        source_file_exclusion_policy, excluded_sensitive_file_count, excluded_status_hash,
        blueprint_object_hash, blueprint_version, blueprint_hash,
        candidate_object_hash, candidate_document_hash, preview_render_run_id,
        preview_artifact_id, preview_renderer_version, preview_storage_key,
        preview_output_hash, preview_output_manifest_hash,
        preview_visual_preflight_report_hash, replay_manifest_object_hash,
        document_id, error_code, error_message, created_at, updated_at, completed_at
    """
    _GENERATION_RUN_COLUMNS = """
        id, job_id, status, blueprint_hash, total, processed, succeeded,
        failed, running, pending, error_code, error_message, created_at,
        updated_at, started_at, completed_at
    """
    _GENERATION_ITEM_COLUMNS = """
        id, job_id, run_id, kind, item_key, page_key, item_ordinal, status, phase,
        attempt, task_kind, operation_id, context_object_hash, submission_id,
        submission_request_hash, submission_normalized_fields_json,
        submission_accepted_at, output_object_hash,
        task_id, execution_process_id, error_code, error_message, created_at,
        updated_at, completed_at
    """

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._conn_lock = asyncio.Lock()
        self._transaction_lock = asyncio.Lock()
        self._initialized = False

    async def close(self) -> None:
        async with self._conn_lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None
                self._initialized = False

    async def initialize(self) -> None:
        async with self._conn_lock:
            if self._initialized:
                return
            conn = await self._connect_locked()
            await conn.executescript(STRUCTURED_PROTOTYPE_SCHEMA_SQL)
            await self._ensure_schema_columns(conn)
            await conn.commit()
            self._initialized = True

    @staticmethod
    async def _ensure_schema_columns(conn: aiosqlite.Connection) -> None:
        async with conn.execute("PRAGMA table_info(prototype_checkpoints)") as cursor:
            checkpoint_columns = {str(row[1]) for row in await cursor.fetchall()}
        for name, declaration in STRUCTURED_PROTOTYPE_CHECKPOINT_HISTORY_COLUMNS:
            if name not in checkpoint_columns:
                await conn.execute(
                    f"ALTER TABLE prototype_checkpoints ADD COLUMN {name} {declaration}"
                )
        async with conn.execute("PRAGMA table_info(prototype_ai_edit_runs)") as cursor:
            columns = {str(row[1]) for row in await cursor.fetchall()}
        for name, declaration in (
            ("submission_id", "TEXT"),
            ("submission_request_hash", "TEXT"),
            ("submission_accepted_at", "TEXT"),
            ("replay_manifest_object_hash", "TEXT"),
        ):
            if name not in columns:
                await conn.execute(
                    f"ALTER TABLE prototype_ai_edit_runs ADD COLUMN {name} {declaration}"
                )
        async with conn.execute("PRAGMA table_info(prototype_document_generation_jobs)") as cursor:
            generation_columns = {str(row[1]) for row in await cursor.fetchall()}
        for name, declaration in STRUCTURED_PROTOTYPE_GENERATION_SNAPSHOT_COLUMNS:
            if name not in generation_columns:
                await conn.execute(
                    "ALTER TABLE prototype_document_generation_jobs "
                    f"ADD COLUMN {name} {declaration}"
                )
        for name in (
            "preview_renderer_version",
            "preview_storage_key",
            "preview_output_hash",
            "preview_output_manifest_hash",
            "preview_visual_preflight_report_hash",
        ):
            if name not in generation_columns:
                await conn.execute(
                    f"ALTER TABLE prototype_document_generation_jobs ADD COLUMN {name} TEXT"
                )
        async with conn.execute("PRAGMA table_info(prototype_runtime_sessions)") as cursor:
            runtime_session_columns = {str(row[1]) for row in await cursor.fetchall()}
        for name, declaration in STRUCTURED_PROTOTYPE_RUNTIME_SESSION_COLUMNS:
            if name not in runtime_session_columns:
                await conn.execute(
                    f"ALTER TABLE prototype_runtime_sessions ADD COLUMN {name} {declaration}"
                )
        await conn.execute(STRUCTURED_PROTOTYPE_RUNTIME_SESSION_REPLACEMENT_INDEX_SQL)
        async with conn.execute(
            "PRAGMA table_info(prototype_document_generation_run_items)"
        ) as cursor:
            generation_item_columns = {str(row[1]) for row in await cursor.fetchall()}
        if "submission_normalized_fields_json" not in generation_item_columns:
            await conn.execute(
                "ALTER TABLE prototype_document_generation_run_items "
                "ADD COLUMN submission_normalized_fields_json TEXT NOT NULL DEFAULT '[]'"
            )
        if "item_ordinal" not in generation_item_columns:
            await conn.execute(
                "ALTER TABLE prototype_document_generation_run_items "
                "ADD COLUMN item_ordinal INTEGER NOT NULL DEFAULT 0"
            )
            await conn.execute(
                """
                UPDATE prototype_document_generation_run_items AS item
                SET item_ordinal = (
                    SELECT COUNT(*)
                    FROM prototype_document_generation_run_items AS prior
                    WHERE prior.run_id = item.run_id AND prior.rowid < item.rowid
                )
                """
            )
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "prototype_generation_run_item_ordinal_uq "
            "ON prototype_document_generation_run_items(run_id, item_ordinal)"
        )

    async def create_operation(
        self,
        operation: PrototypeOperation,
        initial_event: PrototypeOperationEvent,
    ) -> PrototypeOperationCreateResult:
        self._validate_new_operation(operation, initial_event)
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                existing_row = await self._load_operation_by_request_row(
                    conn,
                    operation.project_id,
                    operation.operation_kind,
                    operation.client_request_id,
                )
                if existing_row is not None:
                    existing = self._operation_from_row(existing_row)
                    self._assert_idempotent_operation(existing, operation)
                    result = PrototypeOperationCreateResult(operation=existing, created=False)
                else:
                    async with conn.execute(
                        """
                        SELECT id
                        FROM prototype_operations
                        WHERE project_id = ?
                          AND operation_kind = 'delete_project_prototype'
                          AND status IN ('queued', 'running')
                        LIMIT 1
                        """,
                        (operation.project_id,),
                    ) as cursor:
                        active_delete_row = await cursor.fetchone()
                    if active_delete_row is not None:
                        raise StructuredPrototypeStoreError(
                            "prototype_busy",
                            "prototype deletion cleanup is already in progress",
                        )
                    await self._insert_operation(conn, operation)
                    await self._insert_operation_event(conn, initial_event)
                    result = PrototypeOperationCreateResult(operation=operation, created=True)
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return result

    async def load_operation(self, operation_id: str) -> PrototypeOperation | None:
        await self.initialize()
        conn = await self._get_conn()
        row = await self._load_operation_row(conn, operation_id)
        return self._operation_from_row(row) if row is not None else None

    async def load_operation_by_request(
        self,
        project_id: str,
        operation_kind: PrototypeOperationKind,
        client_request_id: str,
    ) -> PrototypeOperation | None:
        await self.initialize()
        conn = await self._get_conn()
        row = await self._load_operation_by_request_row(
            conn,
            project_id,
            operation_kind,
            client_request_id,
        )
        return self._operation_from_row(row) if row is not None else None

    async def list_active_project_deletion_operations(self) -> tuple[PrototypeOperation, ...]:
        await self.initialize()
        conn = await self._get_conn()
        async with conn.execute(
            """
            SELECT
                id, operation_kind, project_id, resource_kind, resource_id,
                client_request_id, correlation_id, parent_operation_id, status,
                phase, attempt, request_manifest_hash, config_manifest_hash,
                result_manifest_hash, failure_evidence_hash, error_code,
                created_at, started_at, completed_at
            FROM prototype_operations
            WHERE operation_kind = 'delete_project_prototype'
              AND status IN ('queued', 'running')
            ORDER BY created_at, id
            """
        ) as cursor:
            rows = await cursor.fetchall()
        return tuple(self._operation_from_row(row) for row in rows)

    async def list_generation_snapshot_owner_ids(self) -> frozenset[str]:
        await self.initialize()
        conn = await self._get_conn()
        async with conn.execute(
            """
            SELECT id AS owner_id
            FROM prototype_document_generation_jobs
            UNION
            SELECT resource_id AS owner_id
            FROM prototype_operations
            WHERE operation_kind = 'generation_job'
              AND resource_kind = 'generation_job'
              AND resource_id IS NOT NULL
              AND status IN ('queued', 'running')
            """
        ) as cursor:
            rows = await cursor.fetchall()
        return frozenset(_required_str(row[0], "generation_snapshot_owner.id") for row in rows)

    async def load_operation_observability(
        self,
        operation_id: str,
    ) -> PrototypeOperationObservabilitySnapshot | None:
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN")
            try:
                operation_row = await self._load_operation_row(conn, operation_id)
                if operation_row is None:
                    await conn.commit()
                    return None
                operation = self._operation_from_row(operation_row)
                async with conn.execute(
                    """
                    SELECT
                        id, operation_id, parent_step_id, step_kind, step_ordinal,
                        attempt, status, phase, input_manifest_hash, config_manifest_hash,
                        output_manifest_hash, completion_evidence_kind,
                        completion_evidence_ref, error_code, started_at, completed_at
                    FROM prototype_operation_steps
                    WHERE operation_id = ?
                    ORDER BY step_ordinal, attempt
                    """,
                    (operation_id,),
                ) as cursor:
                    step_rows = await cursor.fetchall()
                async with conn.execute(
                    """
                    SELECT
                        operation_id, event_no, step_id, event_kind, status, phase,
                        input_hash, output_hash, evidence_hash, error_code, occurred_at
                    FROM prototype_operation_events
                    WHERE operation_id = ?
                    ORDER BY event_no
                    """,
                    (operation_id,),
                ) as cursor:
                    event_rows = await cursor.fetchall()
                async with conn.execute(
                    """
                    SELECT
                        id, operation_kind, project_id, resource_kind, resource_id,
                        client_request_id, correlation_id, parent_operation_id, status,
                        phase, attempt, request_manifest_hash, config_manifest_hash,
                        result_manifest_hash, failure_evidence_hash, error_code,
                        created_at, started_at, completed_at
                    FROM prototype_operations
                    WHERE parent_operation_id = ?
                    ORDER BY created_at, id
                    """,
                    (operation_id,),
                ) as cursor:
                    child_rows = await cursor.fetchall()
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return PrototypeOperationObservabilitySnapshot(
            operation=operation,
            steps=tuple(self._operation_step_from_row(row) for row in step_rows),
            events=tuple(self._operation_event_from_row(row) for row in event_rows),
            child_operations=tuple(self._operation_from_row(row) for row in child_rows),
        )

    async def list_operation_events(
        self,
        operation_id: str,
    ) -> list[PrototypeOperationEvent]:
        await self.initialize()
        conn = await self._get_conn()
        async with conn.execute(
            """
            SELECT
                operation_id,
                event_no,
                step_id,
                event_kind,
                status,
                phase,
                input_hash,
                output_hash,
                evidence_hash,
                error_code,
                occurred_at
            FROM prototype_operation_events
            WHERE operation_id = ?
            ORDER BY event_no
            """,
            (operation_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._operation_event_from_row(row) for row in rows]

    async def list_operation_steps(
        self,
        operation_id: str,
    ) -> list[PrototypeOperationStep]:
        await self.initialize()
        conn = await self._get_conn()
        async with conn.execute(
            """
            SELECT
                id, operation_id, parent_step_id, step_kind, step_ordinal,
                attempt, status, phase, input_manifest_hash, config_manifest_hash,
                output_manifest_hash, completion_evidence_kind,
                completion_evidence_ref, error_code, started_at, completed_at
            FROM prototype_operation_steps
            WHERE operation_id = ?
            ORDER BY step_ordinal, attempt
            """,
            (operation_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._operation_step_from_row(row) for row in rows]

    async def recover_interrupted_non_generation_operations(
        self,
        recovered_at: datetime,
    ) -> int:
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            try:
                await conn.execute("BEGIN IMMEDIATE")
                async with conn.execute(
                    """
                    WITH RECURSIVE generation_tree(id) AS (
                        SELECT id
                        FROM prototype_operations
                        WHERE operation_kind = 'generation_job'
                          AND resource_kind = 'generation_job'
                          AND parent_operation_id IS NULL
                        UNION
                        SELECT child.id
                        FROM prototype_operations AS child
                        JOIN generation_tree AS parent
                          ON child.parent_operation_id = parent.id
                    )
                    SELECT
                        operation.id, operation.operation_kind, operation.project_id,
                        operation.resource_kind, operation.resource_id,
                        operation.client_request_id, operation.correlation_id,
                        operation.parent_operation_id, operation.status, operation.phase,
                        operation.attempt, operation.request_manifest_hash,
                        operation.config_manifest_hash, operation.result_manifest_hash,
                        operation.failure_evidence_hash, operation.error_code,
                        operation.created_at, operation.started_at, operation.completed_at
                    FROM prototype_operations AS operation
                    WHERE operation.status IN ('queued', 'running')
                      AND operation.operation_kind <> 'delete_project_prototype'
                      AND NOT EXISTS (
                          SELECT 1 FROM generation_tree
                          WHERE generation_tree.id = operation.id
                      )
                    ORDER BY operation.created_at, operation.id
                    """
                ) as cursor:
                    operation_rows = list(await cursor.fetchall())

                for operation_row in operation_rows:
                    operation = self._operation_from_row(operation_row)
                    if operation.operation_kind in {"generation_job", "generation_item"}:
                        raise StructuredPrototypeStoreError(
                            "operation_recovery_corrupt",
                            "active generation operation is outside its restart recovery tree",
                        )
                    try:
                        operation_id_is_canonical = str(UUID(operation.id)) == operation.id
                    except ValueError:
                        operation_id_is_canonical = False
                    if not operation_id_is_canonical:
                        raise StructuredPrototypeStoreError(
                            "operation_recovery_corrupt",
                            "active prototype operation has a non-canonical identity",
                        )
                    if any(
                        value is not None
                        for value in (
                            operation.result_manifest_hash,
                            operation.failure_evidence_hash,
                            operation.error_code,
                            operation.completed_at,
                        )
                    ):
                        raise StructuredPrototypeStoreError(
                            "operation_recovery_corrupt",
                            "active prototype operation contains terminal evidence",
                        )
                    if (operation.status == "queued" and operation.started_at is not None) or (
                        operation.status == "running" and operation.started_at is None
                    ):
                        raise StructuredPrototypeStoreError(
                            "operation_recovery_corrupt",
                            "active prototype operation has invalid lifecycle timestamps",
                        )
                    if operation.created_at > recovered_at or (
                        operation.started_at is not None and operation.started_at > recovered_at
                    ):
                        raise StructuredPrototypeStoreError(
                            "operation_recovery_corrupt",
                            "active prototype operation begins after restart recovery",
                        )

                    async with conn.execute(
                        """
                        SELECT
                            id, operation_id, parent_step_id, step_kind, step_ordinal,
                            attempt, status, phase, input_manifest_hash,
                            config_manifest_hash, output_manifest_hash,
                            completion_evidence_kind, completion_evidence_ref,
                            error_code, started_at, completed_at
                        FROM prototype_operation_steps
                        WHERE operation_id = ? AND status IN ('pending', 'running')
                        ORDER BY step_ordinal, attempt
                        """,
                        (operation.id,),
                    ) as cursor:
                        active_step_rows = list(await cursor.fetchall())
                    if len(active_step_rows) > 1:
                        raise StructuredPrototypeStoreError(
                            "operation_recovery_corrupt",
                            "active prototype operation has multiple active steps",
                        )
                    active_step = (
                        self._operation_step_from_row(active_step_rows[0])
                        if active_step_rows
                        else None
                    )
                    if operation.status == "queued" and active_step is not None:
                        raise StructuredPrototypeStoreError(
                            "operation_recovery_corrupt",
                            "queued prototype operation unexpectedly has an active step",
                        )
                    if active_step is not None:
                        try:
                            step_id_is_canonical = str(UUID(active_step.id)) == active_step.id
                        except ValueError:
                            step_id_is_canonical = False
                        if not step_id_is_canonical:
                            raise StructuredPrototypeStoreError(
                                "operation_recovery_corrupt",
                                "active prototype operation step has a non-canonical identity",
                            )
                        if active_step.status == "pending":
                            invalid_step_evidence = any(
                                value is not None
                                for value in (
                                    active_step.started_at,
                                    active_step.completed_at,
                                    active_step.output_manifest_hash,
                                    active_step.completion_evidence_kind,
                                    active_step.completion_evidence_ref,
                                    active_step.error_code,
                                )
                            )
                        else:
                            invalid_step_evidence = (
                                active_step.started_at is None
                                or active_step.completed_at is not None
                                or active_step.output_manifest_hash is not None
                                or active_step.completion_evidence_kind is not None
                                or active_step.completion_evidence_ref is not None
                                or active_step.error_code is not None
                            )
                        if invalid_step_evidence or (
                            active_step.started_at is not None
                            and active_step.started_at > recovered_at
                        ):
                            raise StructuredPrototypeStoreError(
                                "operation_recovery_corrupt",
                                "active prototype operation step has invalid lifecycle evidence",
                            )

                    async with conn.execute(
                        """
                        SELECT COALESCE(MAX(step_ordinal), -1) + 1
                        FROM prototype_operation_steps
                        WHERE operation_id = ?
                        """,
                        (operation.id,),
                    ) as cursor:
                        ordinal_row = await cursor.fetchone()
                    if ordinal_row is None:
                        raise StructuredPrototypeStoreError(
                            "operation_recovery_corrupt",
                            "prototype restart recovery step ordinal could not be loaded",
                        )
                    next_step_ordinal = _required_non_negative_int(
                        ordinal_row[0],
                        "operation_recovery.next_step_ordinal",
                    )
                    next_event_no = await self._next_operation_event_no(conn, operation.id)
                    if next_event_no == 0:
                        raise StructuredPrototypeStoreError(
                            "operation_recovery_corrupt",
                            "active prototype operation has no queued event",
                        )

                    prior_status = operation.status
                    prior_phase = operation.phase
                    prior_step_id = active_step.id if active_step is not None else None
                    recovery_phase = "service_restart_recovery"
                    if active_step is None or active_step.status == "pending":
                        running_operation = replace(
                            operation,
                            status="running",
                            phase=recovery_phase,
                            started_at=operation.started_at or recovered_at,
                        )
                        running_step = (
                            replace(
                                active_step,
                                status="running",
                                phase=recovery_phase,
                                started_at=recovered_at,
                            )
                            if active_step is not None
                            else PrototypeOperationStep(
                                id=str(
                                    uuid5(
                                        NAMESPACE_URL,
                                        "\x1f".join(
                                            (
                                                "structured-prototype-restart-recovery",
                                                operation.id,
                                                str(next_step_ordinal),
                                            )
                                        ),
                                    )
                                ),
                                operation_id=operation.id,
                                parent_step_id=None,
                                step_kind=recovery_phase,
                                step_ordinal=next_step_ordinal,
                                attempt=1,
                                status="running",
                                phase=recovery_phase,
                                input_manifest_hash=operation.request_manifest_hash,
                                config_manifest_hash=operation.config_manifest_hash,
                                output_manifest_hash=None,
                                completion_evidence_kind=None,
                                completion_evidence_ref=None,
                                error_code=None,
                                started_at=recovered_at,
                                completed_at=None,
                            )
                        )
                        running_event = PrototypeOperationEvent(
                            operation_id=operation.id,
                            event_no=next_event_no,
                            step_id=running_step.id,
                            event_kind="recovery_step_started",
                            status="running",
                            phase=recovery_phase,
                            input_hash=running_step.input_manifest_hash,
                            output_hash=None,
                            evidence_hash=None,
                            error_code=None,
                            occurred_at=recovered_at,
                        )
                        self._validate_operation_transition_payload(
                            running_operation,
                            running_step,
                            running_event,
                        )
                        await self._apply_operation_transition(
                            conn,
                            running_operation,
                            running_step,
                            running_event,
                        )
                        operation = running_operation
                        active_step = running_step
                        next_event_no += 1
                    if active_step is None or active_step.status != "running":
                        raise StructuredPrototypeStoreError(
                            "operation_recovery_corrupt",
                            "prototype operation has no running step to interrupt",
                        )

                    failure_hash = _hash_canonical_json(
                        {
                            "operationInterruptionEvidenceVersion": 1,
                            "operationId": operation.id,
                            "priorStatus": prior_status,
                            "priorPhase": prior_phase,
                            "priorActiveStepId": prior_step_id,
                            "errorCode": "service_restart",
                        }
                    )
                    interrupted_operation = replace(
                        operation,
                        status="interrupted",
                        phase=recovery_phase,
                        failure_evidence_hash=failure_hash,
                        error_code="service_restart",
                        completed_at=recovered_at,
                    )
                    interrupted_step = replace(
                        active_step,
                        status="interrupted",
                        phase=recovery_phase,
                        output_manifest_hash=failure_hash,
                        completion_evidence_kind="failure_manifest_hash",
                        completion_evidence_ref=failure_hash,
                        error_code="service_restart",
                        completed_at=recovered_at,
                    )
                    interrupted_event = PrototypeOperationEvent(
                        operation_id=operation.id,
                        event_no=next_event_no,
                        step_id=interrupted_step.id,
                        event_kind="operation_interrupted",
                        status="interrupted",
                        phase=recovery_phase,
                        input_hash=interrupted_step.input_manifest_hash,
                        output_hash=failure_hash,
                        evidence_hash=failure_hash,
                        error_code="service_restart",
                        occurred_at=recovered_at,
                    )
                    self._validate_operation_transition_payload(
                        interrupted_operation,
                        interrupted_step,
                        interrupted_event,
                    )
                    await self._apply_operation_transition(
                        conn,
                        interrupted_operation,
                        interrupted_step,
                        interrupted_event,
                    )
                async with conn.execute(
                    """
                    WITH RECURSIVE generation_tree(id) AS (
                        SELECT id
                        FROM prototype_operations
                        WHERE operation_kind = 'generation_job'
                          AND resource_kind = 'generation_job'
                          AND parent_operation_id IS NULL
                        UNION
                        SELECT child.id
                        FROM prototype_operations AS child
                        JOIN generation_tree AS parent
                          ON child.parent_operation_id = parent.id
                    )
                    SELECT COUNT(*)
                    FROM prototype_operations AS operation
                    WHERE operation.status IN ('queued', 'running')
                      AND operation.operation_kind <> 'delete_project_prototype'
                      AND NOT EXISTS (
                          SELECT 1 FROM generation_tree
                          WHERE generation_tree.id = operation.id
                      )
                    """
                ) as cursor:
                    remaining_row = await cursor.fetchone()
                if (
                    remaining_row is None
                    or _required_non_negative_int(
                        remaining_row[0],
                        "operation_recovery.remaining_count",
                    )
                    != 0
                ):
                    raise StructuredPrototypeStoreError(
                        "operation_recovery_incomplete",
                        "prototype restart recovery left active ordinary operations",
                    )
            except BaseException:
                # Before commit is queued, DB errors and cancellation remain reversible.
                await _rollback_to_completion(conn)
                raise

            # Queuing commit is the point of no return; resolve it before rollback.
            commit_task = asyncio.create_task(conn.commit())
            try:
                await asyncio.shield(commit_task)
            except asyncio.CancelledError as cancellation_error:
                while not commit_task.done():
                    try:
                        await asyncio.shield(commit_task)
                    except BaseException:
                        # Transaction boundary: retain the task until its result is observable.
                        continue
                try:
                    commit_task.result()
                except BaseException as commit_error:
                    # Transaction boundary: rollback only after commit reports failure.
                    await _rollback_to_completion(conn)
                    raise commit_error from cancellation_error
                raise
            except BaseException:
                # Transaction boundary: a reported commit failure remains reversible.
                await _rollback_to_completion(conn)
                raise
        return len(operation_rows)

    async def create_generation_job(
        self,
        *,
        job_operation: PrototypeOperation,
        job_event: PrototypeOperationEvent | None,
        item_operation: PrototypeOperation,
        item_event: PrototypeOperationEvent,
        job: PrototypeDocumentGenerationJobRecord,
        run: PrototypeDocumentGenerationRunRecord,
        item: PrototypeDocumentGenerationItemRecord,
        descriptors_and_references: tuple[
            tuple[PrototypeObjectDescriptor, PrototypeObjectReference], ...
        ],
        operation_transitions: tuple[
            tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent], ...
        ] = (),
    ) -> PrototypeDocumentGenerationCreateResult:
        if job_event is not None:
            self._validate_new_operation(job_operation, job_event)
        self._validate_new_operation(item_operation, item_event)
        self._validate_generation_job_create(
            job_operation=job_operation,
            item_operation=item_operation,
            job=job,
            run=run,
            item=item,
        )
        self._validate_generation_run_counts(run, (item,))
        for descriptor, reference in descriptors_and_references:
            self._validate_registration(descriptor, reference)
            if reference.owner_kind != "generation_job" or reference.owner_id != job.id:
                raise StructuredPrototypeStoreError(
                    "generation_object_identity_mismatch",
                    "generation job object reference does not match the new job",
                )
        source_references = tuple(
            (descriptor, reference)
            for descriptor, reference in descriptors_and_references
            if reference.role == "source-snapshot-manifest"
        )
        if (
            len(source_references) != 1
            or source_references[0][0].content_hash != job.source_snapshot_object_hash
            or source_references[0][1].content_hash != job.source_snapshot_object_hash
            or source_references[0][1].payload_type != "generation_source_snapshot_manifest"
        ):
            raise StructuredPrototypeStoreError(
                "generation_source_snapshot_missing",
                "new generation job requires one registered source snapshot manifest",
            )
        allowed_transition_operation_ids = {job_operation.id, item_operation.id}
        for operation, step, event in operation_transitions:
            if operation.id not in allowed_transition_operation_ids:
                raise StructuredPrototypeStoreError(
                    "generation_evidence_identity_mismatch",
                    "generation job transition belongs to an unrelated operation",
                )
            self._validate_operation_transition_payload(operation, step, event)
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                existing_row = await self._load_generation_job_by_request_row(
                    conn,
                    job.project_id,
                    job.client_request_id,
                )
                if existing_row is not None:
                    existing = self._generation_job_from_row(existing_row)
                    self._assert_generation_job_idempotent(existing, job)
                    snapshot = await self._load_generation_snapshot_tx(conn, existing.id)
                    result = PrototypeDocumentGenerationCreateResult(
                        snapshot=snapshot,
                        created=False,
                    )
                else:
                    async with conn.execute(
                        """
                        SELECT id
                        FROM prototype_document_generation_jobs
                        WHERE project_id = ? AND status IN (
                            'queued', 'planning', 'awaiting_confirmation', 'generating',
                            'assembling', 'validating', 'rendering_preview', 'ready'
                        )
                        LIMIT 1
                        """,
                        (job.project_id,),
                    ) as cursor:
                        active = await cursor.fetchone()
                    if active is not None:
                        raise StructuredPrototypeStoreError(
                            "generation_job_conflict",
                            "project already has an open structured prototype generation job",
                        )
                    if job_event is None:
                        existing_operation_row = await self._load_operation_row(
                            conn,
                            job_operation.id,
                        )
                        if existing_operation_row is None:
                            raise StructuredPrototypeStoreError(
                                "operation_missing",
                                "pre-created generation root operation does not exist",
                            )
                        self._assert_idempotent_operation(
                            self._operation_from_row(existing_operation_row),
                            job_operation,
                        )
                    else:
                        await self._insert_operation(conn, job_operation)
                        await self._insert_operation_event(conn, job_event)
                    await self._insert_operation(conn, item_operation)
                    await self._insert_operation_event(conn, item_event)
                    for descriptor, reference in descriptors_and_references:
                        await self._register_object_tx(conn, descriptor)
                        await self._insert_object_reference(conn, reference)
                    await self._insert_generation_job(conn, job)
                    await self._insert_generation_run(conn, run)
                    await self._insert_generation_item(conn, item)
                    for operation, step, event in operation_transitions:
                        await self._apply_operation_transition(conn, operation, step, event)
                    result = PrototypeDocumentGenerationCreateResult(
                        snapshot=PrototypeDocumentGenerationSnapshot(
                            job=job,
                            latest_run=run,
                            items=(item,),
                        ),
                        created=True,
                    )
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return result

    async def load_generation_job(
        self,
        job_id: str,
    ) -> PrototypeDocumentGenerationSnapshot | None:
        await self.initialize()
        conn = await self._get_conn()
        row = await self._load_generation_job_row(conn, job_id)
        if row is None:
            return None
        return await self._load_generation_snapshot_tx(conn, job_id)

    async def load_latest_project_generation_job(
        self,
        project_id: str,
    ) -> PrototypeDocumentGenerationSnapshot | None:
        await self.initialize()
        conn = await self._get_conn()
        async with conn.execute(
            """
            SELECT id
            FROM prototype_document_generation_jobs
            WHERE project_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """,
            (project_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return await self._load_generation_snapshot_tx(conn, str(row[0]))

    async def list_generation_job_ids(self) -> tuple[str, ...]:
        await self.initialize()
        conn = await self._get_conn()
        async with conn.execute(
            "SELECT id FROM prototype_document_generation_jobs ORDER BY id"
        ) as cursor:
            rows = await cursor.fetchall()
        return tuple(_required_str(row[0], "generation_job.id") for row in rows)

    async def bind_generation_item_execution_process(
        self,
        *,
        item_id: str,
        task_id: str,
        execution_process_id: str,
        bound_at: datetime,
    ) -> PrototypeDocumentGenerationItemRecord:
        _required_str(item_id, "generation_item.id")
        _required_str(task_id, "generation_item.task_id")
        _required_str(execution_process_id, "generation_item.execution_process_id")
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                item_row = await self._load_generation_item_row(conn, item_id)
                if item_row is None:
                    raise StructuredPrototypeStoreError(
                        "generation_item_missing",
                        "structured prototype generation item does not exist",
                    )
                item = self._generation_item_from_row(item_row)
                if item.status != "generating" or item.task_id != task_id:
                    raise StructuredPrototypeStoreError(
                        "generation_execution_identity_mismatch",
                        "generation execution does not match the active item",
                    )
                if item.execution_process_id is not None:
                    if item.execution_process_id != execution_process_id:
                        raise StructuredPrototypeStoreError(
                            "generation_execution_identity_mismatch",
                            "generation item is already bound to another execution process",
                        )
                    await conn.commit()
                    return item

                operation_row = await self._load_operation_row(conn, item.operation_id)
                if operation_row is None:
                    raise StructuredPrototypeStoreError(
                        "operation_missing",
                        "generation item operation does not exist",
                    )
                operation = self._operation_from_row(operation_row)
                if (
                    operation.status != "running"
                    or operation.resource_kind != "generation_item"
                    or operation.resource_id != item.id
                ):
                    raise StructuredPrototypeStoreError(
                        "generation_execution_identity_mismatch",
                        "generation item operation is not actively running",
                    )
                async with conn.execute(
                    """
                    SELECT
                        id, operation_id, parent_step_id, step_kind, step_ordinal,
                        attempt, status, phase, input_manifest_hash, config_manifest_hash,
                        output_manifest_hash, completion_evidence_kind,
                        completion_evidence_ref, error_code, started_at, completed_at
                    FROM prototype_operation_steps
                    WHERE operation_id = ? AND status = 'running'
                    ORDER BY step_ordinal DESC, attempt DESC
                    LIMIT 1
                    """,
                    (operation.id,),
                ) as cursor:
                    step_row = await cursor.fetchone()
                if step_row is None:
                    raise StructuredPrototypeStoreError(
                        "generation_evidence_missing",
                        "generation execution has no active operation step",
                    )
                step = self._operation_step_from_row(step_row)
                if step.step_kind != "claude_process_started":
                    raise StructuredPrototypeStoreError(
                        "generation_evidence_missing",
                        "generation execution is not awaiting typed process-start evidence",
                    )
                cursor = await conn.execute(
                    """
                    UPDATE prototype_document_generation_run_items
                    SET execution_process_id = ?, updated_at = ?
                    WHERE id = ? AND status = 'generating' AND task_id = ?
                      AND execution_process_id IS NULL
                    """,
                    (
                        execution_process_id,
                        bound_at.isoformat(),
                        item.id,
                        task_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StructuredPrototypeStoreError(
                        "generation_execution_bind_conflict",
                        "generation execution binding changed concurrently",
                    )
                updated_row = await self._load_generation_item_row(conn, item.id)
                if updated_row is None:
                    raise StructuredPrototypeStoreError(
                        "generation_item_missing",
                        "generation item disappeared after execution binding",
                    )
                updated = self._generation_item_from_row(updated_row)
            except StructuredPrototypeStoreError:
                await conn.rollback()
                raise
            except aiosqlite.Error as exc:
                await conn.rollback()
                raise StructuredPrototypeStoreError(
                    "generation_execution_bind_failed",
                    "generation execution process could not be persisted",
                ) from exc
            await conn.commit()
        return updated

    async def create_generation_run(
        self,
        *,
        operation: PrototypeOperation,
        initial_event: PrototypeOperationEvent | None,
        job: PrototypeDocumentGenerationJobRecord,
        run: PrototypeDocumentGenerationRunRecord,
        item_operations: tuple[
            tuple[
                PrototypeDocumentGenerationItemRecord,
                PrototypeOperation,
                PrototypeOperationEvent,
            ],
            ...,
        ],
        expected_job_statuses: tuple[str, ...],
        expected_blueprint_version: int,
        expected_blueprint_hash: str,
        descriptors_and_references: tuple[
            tuple[PrototypeObjectDescriptor, PrototypeObjectReference], ...
        ] = (),
        operation_transitions: tuple[
            tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent], ...
        ] = (),
    ) -> PrototypeDocumentGenerationRunCreateResult:
        if (
            not expected_job_statuses
            or not item_operations
            or expected_blueprint_version <= 0
            or SHA256_RE.fullmatch(expected_blueprint_hash) is None
        ):
            raise StructuredPrototypeStoreError(
                "generation_run_invalid",
                "generation run creation requires expected state and durable items",
            )
        if (
            job.blueprint_version != expected_blueprint_version
            or job.blueprint_hash != expected_blueprint_hash
        ):
            raise StructuredPrototypeStoreError(
                "blueprint_conflict",
                "scheduled generation run does not match the expected blueprint",
            )
        if initial_event is None:
            if (
                operation.status != "running"
                or operation.started_at is None
                or operation.completed_at is not None
                or operation.result_manifest_hash is not None
                or operation.failure_evidence_hash is not None
                or operation.error_code is not None
            ):
                raise StructuredPrototypeStoreError(
                    "generation_run_invalid",
                    "pre-created generation run operation must be actively running",
                )
        else:
            self._validate_new_operation(operation, initial_event)
        items = tuple(
            sorted(
                (item for item, _, _ in item_operations),
                key=lambda item: item.item_ordinal,
            )
        )
        self._validate_generation_run_counts(run, items)
        self._validate_generation_run_create(operation, job, run, item_operations)
        for _, item_operation, item_event in item_operations:
            self._validate_new_operation(item_operation, item_event)
        allowed_transition_operation_ids = {
            operation.id,
            *(item_operation.id for _, item_operation, _ in item_operations),
        }
        for transitioned_operation, step, event in operation_transitions:
            if transitioned_operation.id not in allowed_transition_operation_ids:
                raise StructuredPrototypeStoreError(
                    "generation_evidence_identity_mismatch",
                    "generation run transition belongs to an unrelated operation",
                )
            self._validate_operation_transition_payload(transitioned_operation, step, event)
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                current_job_row = await self._load_generation_job_row(conn, job.id)
                if current_job_row is None:
                    raise StructuredPrototypeStoreError(
                        "generation_job_missing",
                        "structured prototype generation job does not exist",
                    )
                current_job = self._generation_job_from_row(current_job_row)
                if (
                    current_job.blueprint_version != expected_blueprint_version
                    or current_job.blueprint_hash != expected_blueprint_hash
                ):
                    raise StructuredPrototypeStoreError(
                        "blueprint_conflict",
                        "generation blueprint changed before scheduling",
                    )
                existing_run_row = await self._load_generation_run_row(conn, run.id)
                if existing_run_row is not None:
                    existing_run = self._generation_run_from_row(existing_run_row)
                    self._assert_generation_run_schedule_idempotent(existing_run, run)
                    existing_operation_row = await self._load_operation_row(conn, operation.id)
                    if existing_operation_row is None:
                        raise StructuredPrototypeStoreError(
                            "generation_run_corrupt",
                            "generation run has no scheduling operation",
                        )
                    self._assert_idempotent_operation(
                        self._operation_from_row(existing_operation_row),
                        operation,
                    )
                    snapshot = await self._load_generation_snapshot_tx(conn, job.id)
                    await conn.commit()
                    return PrototypeDocumentGenerationRunCreateResult(
                        snapshot=snapshot,
                        created=False,
                    )
                if current_job.status not in expected_job_statuses:
                    raise StructuredPrototypeStoreError(
                        "generation_job_conflict",
                        "structured prototype generation job status changed before scheduling",
                    )
                self._assert_generation_job_identity(current_job, job)
                self._assert_generation_job_status_transition(current_job.status, job.status)
                for descriptor, reference in descriptors_and_references:
                    self._validate_registration(descriptor, reference)
                    if reference.owner_kind not in {"generation_run", "generation_item"}:
                        raise StructuredPrototypeStoreError(
                            "generation_object_identity_mismatch",
                            "generation run context has an unsupported object owner",
                        )
                    valid_owner_ids = {run.id, *(item.id for item in items)}
                    if reference.owner_id not in valid_owner_ids:
                        raise StructuredPrototypeStoreError(
                            "generation_object_identity_mismatch",
                            "generation run context owner does not match the scheduled records",
                        )
                existing_operation_row = await self._load_operation_row(conn, operation.id)
                if existing_operation_row is None:
                    if initial_event is None:
                        raise StructuredPrototypeStoreError(
                            "generation_evidence_missing",
                            "new generation run operation requires its queued event",
                        )
                    await self._insert_operation(conn, operation)
                    await self._insert_operation_event(conn, initial_event)
                else:
                    existing_operation = self._operation_from_row(existing_operation_row)
                    if initial_event is not None or existing_operation != operation:
                        raise StructuredPrototypeStoreError(
                            "generation_evidence_conflict",
                            "pre-created generation run operation changed before scheduling",
                        )
                for descriptor, reference in descriptors_and_references:
                    await self._register_object_tx(conn, descriptor)
                    await self._insert_object_reference(conn, reference)
                await self._update_generation_job(conn, job)
                await self._insert_generation_run(conn, run)
                for item, item_operation, item_event in item_operations:
                    await self._insert_operation(conn, item_operation)
                    await self._insert_operation_event(conn, item_event)
                    await self._insert_generation_item(conn, item)
                for transitioned_operation, step, event in operation_transitions:
                    await self._apply_operation_transition(
                        conn,
                        transitioned_operation,
                        step,
                        event,
                    )
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return PrototypeDocumentGenerationRunCreateResult(
            snapshot=PrototypeDocumentGenerationSnapshot(
                job=job,
                latest_run=run,
                items=items,
            ),
            created=True,
        )

    async def load_generation_confirm_result(
        self,
        *,
        job_id: str,
        client_request_id: str,
        request_hash: str,
        expected_operation_id: str,
        expected_run_id: str,
        expected_blueprint_hash: str,
    ) -> PrototypeDocumentGenerationConfirmResult | None:
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN")
            try:
                job_row = await self._load_generation_job_row(conn, job_id)
                if job_row is None:
                    await conn.commit()
                    return None
                job = self._generation_job_from_row(job_row)
                operation_row = await self._load_operation_by_request_row(
                    conn,
                    job.project_id,
                    "generation_job",
                    client_request_id,
                )
                if operation_row is None:
                    await conn.commit()
                    return None
                operation = self._operation_from_row(operation_row)
                if (
                    operation.id != expected_operation_id
                    or operation.parent_operation_id != job.operation_id
                    or operation.resource_kind != "generation_job"
                    or operation.resource_id != job.id
                    or operation.request_manifest_hash != request_hash
                ):
                    raise StructuredPrototypeStoreError(
                        "generation_confirm_idempotency_conflict",
                        "generation blueprint confirmation was retried with different inputs",
                    )
                run_row = await self._load_generation_run_row(conn, expected_run_id)
                if run_row is None:
                    if operation.status in {"queued", "running"}:
                        raise StructuredPrototypeStoreError(
                            "generation_confirm_in_progress",
                            "generation blueprint confirmation is still freezing its context",
                        )
                    if operation.status in {"failed", "interrupted", "cancelled"}:
                        raise StructuredPrototypeStoreError(
                            "generation_confirm_conflict",
                            "generation blueprint confirmation is already terminal",
                        )
                    raise StructuredPrototypeStoreError(
                        "generation_confirm_result_corrupt",
                        "generation blueprint confirmation has no foundation run",
                    )
                run = self._generation_run_from_row(run_row)
                async with conn.execute(
                    """
                    SELECT
                        item.kind,
                        item.item_key,
                        item.page_key,
                        item.status,
                        operation.parent_operation_id
                    FROM prototype_document_generation_run_items AS item
                    JOIN prototype_operations AS operation ON operation.id = item.operation_id
                    WHERE item.run_id = ?
                    ORDER BY item.item_ordinal
                    """,
                    (run.id,),
                ) as cursor:
                    item_rows = list(await cursor.fetchall())
                if (
                    run.job_id != job.id
                    or run.blueprint_hash != expected_blueprint_hash
                    or job.blueprint_hash != expected_blueprint_hash
                    or len(item_rows) != 1
                    or str(item_rows[0][0]) != "foundation"
                    or str(item_rows[0][1]) != "foundation"
                    or item_rows[0][2] is not None
                    or item_rows[0][4] != operation.id
                ):
                    raise StructuredPrototypeStoreError(
                        "generation_confirm_result_corrupt",
                        "generation blueprint confirmation lineage is inconsistent",
                    )
                if operation.status in {"queued", "running"}:
                    raise StructuredPrototypeStoreError(
                        "generation_confirm_in_progress",
                        "generation blueprint confirmation is still in progress",
                    )
                if operation.status != "succeeded":
                    raise StructuredPrototypeStoreError(
                        "generation_confirm_conflict",
                        "generation blueprint confirmation is already terminal",
                    )
                if (
                    run.status != "completed"
                    or str(item_rows[0][3]) != "done"
                    or job.status == "awaiting_confirmation"
                ):
                    raise StructuredPrototypeStoreError(
                        "generation_confirm_result_corrupt",
                        "completed blueprint confirmation has inconsistent durable state",
                    )
                snapshot = await self._load_generation_snapshot_tx(conn, job.id)
            except StructuredPrototypeStoreError:
                await conn.rollback()
                raise
            except aiosqlite.Error as exc:
                await conn.rollback()
                raise StructuredPrototypeStoreError(
                    "generation_confirm_result_unavailable",
                    "generation blueprint confirmation result could not be loaded",
                ) from exc
            await conn.commit()
        return PrototypeDocumentGenerationConfirmResult(
            operation_id=operation.id,
            correlation_id=operation.correlation_id,
            snapshot=snapshot,
        )

    async def load_generation_accept_result(
        self,
        *,
        job_id: str,
        client_request_id: str,
        request_hash: str,
    ) -> PrototypeDocumentGenerationAcceptResult | None:
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN")
            try:
                job_row = await self._load_generation_job_row(conn, job_id)
                if job_row is None:
                    await conn.commit()
                    return None
                job = self._generation_job_from_row(job_row)
                operation_row = await self._load_operation_by_request_row(
                    conn,
                    job.project_id,
                    "create_document",
                    client_request_id,
                )
                if operation_row is None:
                    await conn.commit()
                    return None
                operation = self._operation_from_row(operation_row)
                if (
                    operation.parent_operation_id != job.operation_id
                    or operation.resource_kind != "document"
                    or operation.request_manifest_hash != request_hash
                ):
                    raise StructuredPrototypeStoreError(
                        "generation_accept_idempotency_conflict",
                        "generation accept request was retried with different inputs",
                    )
                if operation.status == "queued":
                    await conn.commit()
                    return None
                if operation.status == "running":
                    raise StructuredPrototypeStoreError(
                        "generation_accept_in_progress",
                        "generation accept request is still in progress",
                    )
                if operation.status != "succeeded":
                    raise StructuredPrototypeStoreError(
                        "generation_accept_conflict",
                        "generation accept request is already terminal",
                    )
                if (
                    job.status != "accepted"
                    or job.document_id is None
                    or operation.resource_id != job.document_id
                    or operation.result_manifest_hash is None
                    or job.replay_manifest_object_hash is None
                ):
                    raise StructuredPrototypeStoreError(
                        "generation_accept_result_corrupt",
                        "accepted generation result does not match its operation",
                    )
                root_operation_row = await self._load_operation_row(conn, job.operation_id)
                if root_operation_row is None:
                    raise StructuredPrototypeStoreError(
                        "generation_accept_result_corrupt",
                        "accepted generation root operation is missing",
                    )
                root_operation = self._operation_from_row(root_operation_row)
                if (
                    root_operation.status != "succeeded"
                    or root_operation.result_manifest_hash != job.replay_manifest_object_hash
                ):
                    raise StructuredPrototypeStoreError(
                        "generation_accept_result_corrupt",
                        "accepted generation root replay identity is inconsistent",
                    )
                async with conn.execute(
                    """
                    SELECT 1
                    FROM prototype_object_references
                    WHERE project_id = ?
                      AND owner_kind = 'replay_manifest'
                      AND owner_id = ?
                      AND role = 'operation-replay-manifest'
                      AND content_hash = ?
                      AND payload_type = 'replay_manifest'
                      AND schema_version = 1
                    LIMIT 1
                    """,
                    (
                        job.project_id,
                        operation.id,
                        operation.result_manifest_hash,
                    ),
                ) as cursor:
                    replay_reference_row = await cursor.fetchone()
                if replay_reference_row is None:
                    raise StructuredPrototypeStoreError(
                        "generation_accept_result_corrupt",
                        "accepted generation operation replay reference is missing",
                    )
                document = await self._require_document(conn, job.document_id)
                if document.active_draft_id is None:
                    raise StructuredPrototypeStoreError(
                        "generation_accept_result_corrupt",
                        "accepted generation document has no active draft",
                    )
                draft = await self._require_draft(conn, document.active_draft_id)
                if draft.latest_checkpoint_id is None:
                    raise StructuredPrototypeStoreError(
                        "generation_accept_result_corrupt",
                        "accepted generation draft has no checkpoint",
                    )
                checkpoint = await self._require_checkpoint(conn, draft.latest_checkpoint_id)
                if (
                    document.project_id != job.project_id
                    or draft.document_id != document.id
                    or draft.head_document_hash != job.candidate_object_hash
                    or checkpoint.document_id != document.id
                    or checkpoint.draft_id != draft.id
                    or checkpoint.checkpoint_kind != "generation_accept"
                    or checkpoint.document_object_hash != job.candidate_object_hash
                    or checkpoint.document_hash != job.candidate_object_hash
                    or checkpoint.created_by_operation_id != operation.id
                ):
                    raise StructuredPrototypeStoreError(
                        "generation_accept_result_corrupt",
                        "accepted generation document lineage is inconsistent",
                    )
                snapshot = await self._load_generation_snapshot_tx(conn, job.id)
            except StructuredPrototypeStoreError:
                await conn.rollback()
                raise
            except aiosqlite.Error as exc:
                await conn.rollback()
                raise StructuredPrototypeStoreError(
                    "generation_accept_result_unavailable",
                    "generation accept result could not be loaded",
                ) from exc
            await conn.commit()
        return PrototypeDocumentGenerationAcceptResult(
            operation_id=operation.id,
            correlation_id=operation.correlation_id,
            snapshot=snapshot,
            document=document,
            draft=draft,
            checkpoint=checkpoint,
        )

    async def transition_generation_records(
        self,
        *,
        job: PrototypeDocumentGenerationJobRecord,
        run: PrototypeDocumentGenerationRunRecord,
        items: tuple[PrototypeDocumentGenerationItemRecord, ...],
        expected_job_statuses: tuple[str, ...],
        expected_run_statuses: tuple[str, ...],
        expected_item_statuses: tuple[str, ...],
        descriptors_and_references: tuple[
            tuple[PrototypeObjectDescriptor, PrototypeObjectReference], ...
        ] = (),
        operation_transitions: tuple[
            tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent], ...
        ] = (),
    ) -> PrototypeDocumentGenerationSnapshot:
        if not expected_job_statuses or not expected_run_statuses or not expected_item_statuses:
            raise StructuredPrototypeStoreError(
                "generation_transition_invalid",
                "generation transition requires explicit expected lifecycle states",
            )
        if not operation_transitions:
            raise StructuredPrototypeStoreError(
                "generation_evidence_missing",
                "generation transition requires a durable operation step and event",
            )
        items = tuple(sorted(items, key=lambda item: item.item_ordinal))
        self._validate_generation_run_counts(run, items)
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                current_job_row = await self._load_generation_job_row(conn, job.id)
                current_run_row = await self._load_generation_run_row(conn, run.id)
                if current_job_row is None or current_run_row is None:
                    raise StructuredPrototypeStoreError(
                        "generation_job_missing",
                        "structured prototype generation job or run does not exist",
                    )
                current_job = self._generation_job_from_row(current_job_row)
                current_run = self._generation_run_from_row(current_run_row)
                if current_job.status not in expected_job_statuses:
                    raise StructuredPrototypeStoreError(
                        "generation_job_conflict",
                        "structured prototype generation job status changed",
                    )
                if current_run.status not in expected_run_statuses:
                    raise StructuredPrototypeStoreError(
                        "generation_run_conflict",
                        "structured prototype generation run status changed",
                    )
                self._assert_generation_job_identity(current_job, job)
                self._assert_generation_run_identity(current_run, run)
                self._assert_generation_job_status_transition(current_job.status, job.status)
                self._assert_generation_run_status_transition(current_run.status, run.status)
                transition_operation_ids = {
                    operation.id for operation, _, _ in operation_transitions
                }
                item_operation_ids = {item.operation_id for item in items}
                phase_operation_ids = {
                    operation.id
                    for operation, _, _ in operation_transitions
                    if operation.operation_kind == "generation_job"
                    and operation.project_id == job.project_id
                    and operation.resource_kind == "generation_job"
                    and operation.resource_id == job.id
                    and operation.parent_operation_id == job.operation_id
                }
                replay_operation_ids = {
                    job.operation_id,
                    *item_operation_ids,
                    *phase_operation_ids,
                }
                succeeded_operation_ids = {
                    operation.id
                    for operation, _, _ in operation_transitions
                    if operation.status == "succeeded"
                }
                failed_operation_ids = {
                    operation.id
                    for operation, _, _ in operation_transitions
                    if operation.status == "failed"
                }
                replay_reference_counts: dict[str, int] = {}
                failure_reference_counts: dict[str, int] = {}
                for _, reference in descriptors_and_references:
                    if reference.owner_kind == "replay_manifest":
                        if reference.owner_id not in replay_operation_ids:
                            raise StructuredPrototypeStoreError(
                                "generation_object_identity_mismatch",
                                "generation transition replay owner does not match its records",
                            )
                        if reference.role not in {
                            "operation-replay-manifest",
                            "operation-failure-evidence",
                        }:
                            raise StructuredPrototypeStoreError(
                                "generation_replay_manifest_identity_mismatch",
                                "generation operation evidence role is unsupported",
                            )
                        if reference.role == "operation-replay-manifest":
                            replay_reference_counts[reference.owner_id] = (
                                replay_reference_counts.get(reference.owner_id, 0) + 1
                            )
                        elif reference.role == "operation-failure-evidence":
                            failure_reference_counts[reference.owner_id] = (
                                failure_reference_counts.get(reference.owner_id, 0) + 1
                            )
                registered_replay_operation_ids = set(replay_reference_counts)
                if registered_replay_operation_ids - succeeded_operation_ids:
                    raise StructuredPrototypeStoreError(
                        "generation_replay_manifest_identity_mismatch",
                        "generation replay manifest cannot seal a nonterminal operation",
                    )
                if succeeded_operation_ids - registered_replay_operation_ids or any(
                    count != 1 for count in replay_reference_counts.values()
                ):
                    raise StructuredPrototypeStoreError(
                        "generation_replay_manifest_registration_required",
                        "every successful generation operation requires exactly one replay manifest",
                    )
                registered_failure_operation_ids = set(failure_reference_counts)
                if registered_failure_operation_ids - failed_operation_ids:
                    raise StructuredPrototypeStoreError(
                        "generation_failure_evidence_invalid",
                        "generation failure evidence cannot seal a nonfailed operation",
                    )
                if failed_operation_ids - registered_failure_operation_ids or any(
                    count != 1 for count in failure_reference_counts.values()
                ):
                    raise StructuredPrototypeStoreError(
                        "generation_failure_evidence_required",
                        "every failed generation operation requires exactly one evidence object",
                    )
                if (
                    current_job.status != job.status
                    and job.operation_id not in transition_operation_ids
                ):
                    raise StructuredPrototypeStoreError(
                        "generation_evidence_missing",
                        "generation job state change has no correlated operation evidence",
                    )
                for item in items:
                    current_item_row = await self._load_generation_item_row(conn, item.id)
                    if current_item_row is None:
                        raise StructuredPrototypeStoreError(
                            "generation_item_missing",
                            "structured prototype generation item does not exist",
                        )
                    current_item = self._generation_item_from_row(current_item_row)
                    if current_item.status not in expected_item_statuses:
                        raise StructuredPrototypeStoreError(
                            "generation_item_conflict",
                            "structured prototype generation item status changed: "
                            f"item_id={item.id} current={current_item.status} "
                            f"expected={','.join(expected_item_statuses)}",
                        )
                    self._assert_generation_item_identity(current_item, item)
                    self._assert_generation_item_status_transition(
                        current_item.status,
                        item.status,
                    )
                    if (
                        current_item.status != item.status
                        and item.operation_id not in transition_operation_ids
                    ):
                        raise StructuredPrototypeStoreError(
                            "generation_evidence_missing",
                            "generation item state change has no correlated operation evidence",
                        )
                for descriptor, reference in descriptors_and_references:
                    self._validate_registration(descriptor, reference)
                    if reference.owner_kind not in {
                        "generation_job",
                        "generation_item",
                        "replay_manifest",
                    }:
                        raise StructuredPrototypeStoreError(
                            "generation_object_identity_mismatch",
                            "generation transition object has an unsupported owner",
                        )
                    if (
                        (reference.owner_kind == "generation_job" and reference.owner_id != job.id)
                        or (
                            reference.owner_kind == "generation_item"
                            and reference.owner_id not in {item.id for item in items}
                        )
                        or (
                            reference.owner_kind == "replay_manifest"
                            and reference.owner_id not in replay_operation_ids
                        )
                    ):
                        raise StructuredPrototypeStoreError(
                            "generation_object_identity_mismatch",
                            "generation transition object owner does not match its records",
                        )
                    if reference.owner_kind == "replay_manifest":
                        terminal_transition = next(
                            (
                                transition
                                for transition in operation_transitions
                                if transition[0].id == reference.owner_id
                            ),
                            None,
                        )
                        if terminal_transition is None:
                            raise StructuredPrototypeStoreError(
                                "generation_replay_manifest_identity_mismatch",
                                "generation evidence has no owning terminal transition",
                            )
                        if reference.role == "operation-replay-manifest":
                            if (
                                terminal_transition[0].status != "succeeded"
                                or terminal_transition[0].result_manifest_hash
                                != descriptor.content_hash
                                or reference.payload_type != "replay_manifest"
                                or reference.schema_version != 1
                            ):
                                raise StructuredPrototypeStoreError(
                                    "generation_replay_manifest_identity_mismatch",
                                    "generation replay manifest does not seal its owning operation",
                                )
                            self._validate_operation_transition_payload(*terminal_transition)
                        elif reference.role == "operation-failure-evidence":
                            self._validate_generation_failure_evidence_registration(
                                descriptor=descriptor,
                                reference=reference,
                                operation=terminal_transition[0],
                                step=terminal_transition[1],
                                event=terminal_transition[2],
                            )
                        else:
                            raise StructuredPrototypeStoreError(
                                "generation_replay_manifest_identity_mismatch",
                                "generation operation evidence role is unsupported",
                            )
                        async with conn.execute(
                            """
                            SELECT COUNT(*)
                            FROM prototype_object_references
                            WHERE project_id = ?
                              AND owner_kind = 'replay_manifest'
                              AND owner_id = ?
                            """,
                            (job.project_id, reference.owner_id),
                        ) as cursor:
                            existing_replay_row = await cursor.fetchone()
                        if existing_replay_row is None:
                            raise StructuredPrototypeStoreError(
                                "generation_replay_manifest_identity_mismatch",
                                "generation replay ownership could not be verified",
                            )
                        existing_replay_count = _required_non_negative_int(
                            existing_replay_row[0],
                            "generation_replay_manifest.reference_count",
                        )
                        if existing_replay_count != 0:
                            raise StructuredPrototypeStoreError(
                                "generation_replay_manifest_identity_mismatch",
                                "generation operation already owns replay manifest evidence",
                            )
                    await self._register_object_tx(conn, descriptor)
                    await self._insert_object_reference(conn, reference)
                for operation, step, event in operation_transitions:
                    await self._apply_operation_transition(conn, operation, step, event)
                await self._update_generation_job(conn, job)
                await self._update_generation_run(conn, run)
                for item in items:
                    await self._update_generation_item(conn, item)
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return PrototypeDocumentGenerationSnapshot(job=job, latest_run=run, items=items)

    async def load_generation_restart_recovery_scope(
        self,
    ) -> PrototypeGenerationRestartRecoveryScope:
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN")
            try:
                scope = await self._load_generation_restart_recovery_scope_tx(conn)
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return scope

    async def interrupt_active_generation_jobs(
        self,
        *,
        expected_scope_fingerprint: str,
        descriptors_and_references: tuple[
            tuple[PrototypeObjectDescriptor, PrototypeObjectReference], ...
        ],
        interrupted_at: datetime,
    ) -> int:
        _required_hash(expected_scope_fingerprint, "generation_recovery.scope_fingerprint")
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                scope = await self._load_generation_restart_recovery_scope_tx(conn)
                if scope.fingerprint != expected_scope_fingerprint:
                    raise StructuredPrototypeStoreError(
                        "generation_recovery_conflict",
                        "structured prototype generation changed before restart recovery",
                    )
                targets_by_id = {target.operation.id: target for target in scope.operations}
                evidence_by_operation_id: dict[
                    str,
                    tuple[PrototypeObjectDescriptor, PrototypeObjectReference],
                ] = {}
                for descriptor, reference in descriptors_and_references:
                    self._validate_registration(descriptor, reference)
                    if (
                        reference.owner_kind != "replay_manifest"
                        or reference.owner_id not in targets_by_id
                        or reference.role != "operation-interruption-evidence"
                        or reference.payload_type != "generation_evidence_manifest"
                        or reference.schema_version != 1
                        or descriptor.project_id
                        != targets_by_id[reference.owner_id].operation.project_id
                        or reference.owner_id in evidence_by_operation_id
                    ):
                        raise StructuredPrototypeStoreError(
                            "generation_recovery_evidence_invalid",
                            "generation restart evidence does not match its active operation",
                        )
                    evidence_by_operation_id[reference.owner_id] = (descriptor, reference)
                if set(evidence_by_operation_id) != set(targets_by_id):
                    raise StructuredPrototypeStoreError(
                        "generation_recovery_evidence_missing",
                        "generation restart recovery requires evidence for every active operation",
                    )
                for descriptor, reference in evidence_by_operation_id.values():
                    async with conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM prototype_object_references
                        WHERE project_id = ?
                          AND owner_kind = 'replay_manifest'
                          AND owner_id = ?
                        """,
                        (reference.project_id, reference.owner_id),
                    ) as cursor:
                        existing_row = await cursor.fetchone()
                    if (
                        existing_row is None
                        or _required_non_negative_int(
                            existing_row[0],
                            "generation_recovery_evidence.reference_count",
                        )
                        != 0
                    ):
                        raise StructuredPrototypeStoreError(
                            "generation_recovery_evidence_invalid",
                            "generation operation already owns terminal evidence",
                        )
                    await self._register_object_tx(conn, descriptor)
                    await self._insert_object_reference(conn, reference)
                for target in scope.operations:
                    descriptor, _ = evidence_by_operation_id[target.operation.id]
                    await self._interrupt_generation_operation(
                        conn,
                        target,
                        evidence_hash=descriptor.content_hash,
                        interrupted_at=interrupted_at,
                    )

                timestamp = interrupted_at.isoformat()
                item_cursor = await conn.execute(
                    """
                    UPDATE prototype_document_generation_run_items
                    SET status = 'interrupted', phase = 'service_restart_recovery',
                        error_code = 'restart_interrupted',
                        error_message = 'generation item was interrupted by backend restart',
                        updated_at = ?, completed_at = ?
                    WHERE status IN ('pending', 'generating', 'validating')
                    """,
                    (timestamp, timestamp),
                )
                if item_cursor.rowcount != scope.active_item_count:
                    raise StructuredPrototypeStoreError(
                        "generation_recovery_conflict",
                        "generation restart item scope changed during recovery",
                    )
                run_cursor = await conn.execute(
                    """
                    UPDATE prototype_document_generation_runs AS run
                    SET status = 'interrupted', error_code = 'restart_interrupted',
                        error_message = 'generation run was interrupted by backend restart',
                        processed = (
                            SELECT COUNT(*) FROM prototype_document_generation_run_items AS item
                            WHERE item.run_id = run.id
                              AND item.status IN ('done', 'failed', 'interrupted')
                        ),
                        succeeded = (
                            SELECT COUNT(*) FROM prototype_document_generation_run_items AS item
                            WHERE item.run_id = run.id AND item.status = 'done'
                        ),
                        failed = (
                            SELECT COUNT(*) FROM prototype_document_generation_run_items AS item
                            WHERE item.run_id = run.id
                              AND item.status IN ('failed', 'interrupted')
                        ),
                        running = 0, pending = 0, updated_at = ?, completed_at = ?
                    WHERE status IN ('queued', 'running')
                    """,
                    (timestamp, timestamp),
                )
                if run_cursor.rowcount != scope.active_run_count:
                    raise StructuredPrototypeStoreError(
                        "generation_recovery_conflict",
                        "generation restart run scope changed during recovery",
                    )
                job_cursor = await conn.execute(
                    """
                    UPDATE prototype_document_generation_jobs
                    SET status = 'interrupted', error_code = 'restart_interrupted',
                        error_message = 'generation job was interrupted by backend restart',
                        updated_at = ?, completed_at = ?
                    WHERE status IN (
                        'queued', 'planning', 'generating', 'assembling',
                        'validating', 'rendering_preview'
                    )
                    """,
                    (timestamp, timestamp),
                )
                if job_cursor.rowcount != scope.active_job_count:
                    raise StructuredPrototypeStoreError(
                        "generation_recovery_conflict",
                        "generation restart job scope changed during recovery",
                    )
                remaining = await self._load_generation_restart_recovery_scope_tx(conn)
                if (
                    remaining.operations
                    or remaining.active_job_count
                    or remaining.active_run_count
                    or remaining.active_item_count
                ):
                    raise StructuredPrototypeStoreError(
                        "generation_recovery_incomplete",
                        "generation restart recovery left active durable state",
                    )
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return scope.affected_root_count

    async def accept_generation_candidate(
        self,
        *,
        descriptor: PrototypeObjectDescriptor,
        checkpoint_reference: PrototypeObjectReference,
        history_descriptor: PrototypeObjectDescriptor,
        history_reference: PrototypeObjectReference,
        history_checkpoint: PrototypeCommandHistoryCheckpoint,
        accept_replay_descriptor: PrototypeObjectDescriptor,
        accept_replay_reference: PrototypeObjectReference,
        job: PrototypeDocumentGenerationJobRecord,
        document: PrototypeDocumentRecord,
        draft: PrototypeDraftRecord,
        checkpoint: PrototypeCheckpointRecord,
        expected_candidate_object_hash: str,
        expected_preview_output_hash: str,
        expected_source_fingerprint: str,
        completed_transition: tuple[
            PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent
        ],
    ) -> PrototypeDocumentGenerationAcceptResult:
        completed_operation, completed_step, completed_event = completed_transition
        self._validate_operation_transition_payload(
            completed_operation,
            completed_step,
            completed_event,
        )
        self._validate_initial_checkpoint(
            descriptor=descriptor,
            reference=checkpoint_reference,
            history_descriptor=history_descriptor,
            history_reference=history_reference,
            history_checkpoint=history_checkpoint,
            document=document,
            draft=draft,
            checkpoint=checkpoint,
            completed_operation=completed_operation,
            completion_step=completed_step,
            completion_event=completed_event,
        )
        self._validate_replay_manifest_registration(
            descriptor=accept_replay_descriptor,
            reference=accept_replay_reference,
            operation=completed_operation,
            step=completed_step,
            event=completed_event,
        )
        if (
            job.status != "accepted"
            or job.document_id != document.id
            or job.completed_at is None
            or descriptor.content_hash != expected_candidate_object_hash
            or job.candidate_object_hash != expected_candidate_object_hash
            or job.candidate_document_hash != descriptor.content_hash
            or job.preview_output_hash != expected_preview_output_hash
            or job.source_fingerprint != expected_source_fingerprint
            or job.replay_manifest_object_hash is None
            or completed_operation.parent_operation_id != job.operation_id
            or completed_operation.operation_kind != "create_document"
            or completed_operation.result_manifest_hash != accept_replay_descriptor.content_hash
        ):
            raise StructuredPrototypeStoreError(
                "generation_accept_identity_mismatch",
                "generation accept document, job, and replay identities are inconsistent",
            )
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                current_job_row = await self._load_generation_job_row(conn, job.id)
                if current_job_row is None:
                    raise StructuredPrototypeStoreError(
                        "generation_job_missing",
                        "structured prototype generation job does not exist",
                    )
                current_job = self._generation_job_from_row(current_job_row)
                if current_job.status != "ready":
                    raise StructuredPrototypeStoreError(
                        "generation_job_conflict",
                        "structured prototype generation candidate is no longer ready",
                    )
                self._assert_generation_job_identity(current_job, job)
                self._assert_generation_job_status_transition(current_job.status, job.status)
                if (
                    current_job.candidate_object_hash != expected_candidate_object_hash
                    or current_job.preview_artifact_id != job.preview_artifact_id
                    or current_job.preview_output_hash != expected_preview_output_hash
                    or current_job.source_fingerprint != expected_source_fingerprint
                ):
                    raise StructuredPrototypeStoreError(
                        "generation_candidate_conflict",
                        "generation candidate or preview changed before accept",
                    )
                root_operation_row = await self._load_operation_row(conn, job.operation_id)
                if root_operation_row is None:
                    raise StructuredPrototypeStoreError(
                        "generation_evidence_conflict",
                        "generation root operation is missing before accept",
                    )
                root_operation = self._operation_from_row(root_operation_row)
                if (
                    root_operation.status != "succeeded"
                    or root_operation.result_manifest_hash
                    != current_job.replay_manifest_object_hash
                ):
                    raise StructuredPrototypeStoreError(
                        "generation_evidence_conflict",
                        "generation root replay evidence is not terminal before accept",
                    )
                current_snapshot = await self._load_generation_snapshot_tx(conn, job.id)
                if (
                    current_snapshot.latest_run is None
                    or current_snapshot.latest_run.status != "completed"
                    or any(item.status != "done" for item in current_snapshot.items)
                ):
                    raise StructuredPrototypeStoreError(
                        "generation_evidence_conflict",
                        "generation candidate evidence is not terminal before accept",
                    )
                await self._register_object_tx(conn, descriptor)
                await self._register_object_tx(conn, history_descriptor)
                await conn.execute(
                    """
                    INSERT INTO prototype_documents (
                        id, project_id, title, published_revision_no,
                        active_draft_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (
                        document.id,
                        document.project_id,
                        document.title,
                        document.published_revision_no,
                        document.created_at.isoformat(),
                        document.updated_at.isoformat(),
                    ),
                )
                await conn.execute(
                    """
                    INSERT INTO prototype_drafts (
                        id, document_id, base_revision_no, status, head_sequence_no,
                        head_document_hash, latest_checkpoint_id, publish_revision_no,
                        created_at, updated_at, closed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
                    """,
                    self._initial_draft_params(draft),
                )
                await self._insert_checkpoint(conn, checkpoint)
                await self._insert_object_reference(conn, checkpoint_reference)
                await self._insert_object_reference(conn, history_reference)
                await conn.execute(
                    "UPDATE prototype_documents SET active_draft_id = ? WHERE id = ?",
                    (draft.id, document.id),
                )
                await conn.execute(
                    "UPDATE prototype_drafts SET latest_checkpoint_id = ? WHERE id = ?",
                    (checkpoint.id, draft.id),
                )
                await self._register_object_tx(conn, accept_replay_descriptor)
                await self._insert_object_reference(conn, accept_replay_reference)
                await self._update_generation_job(conn, job)
                await self._apply_operation_transition(
                    conn,
                    completed_operation,
                    completed_step,
                    completed_event,
                )
                snapshot = await self._load_generation_snapshot_tx(conn, job.id)
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return PrototypeDocumentGenerationAcceptResult(
            operation_id=completed_operation.id,
            correlation_id=completed_operation.correlation_id,
            snapshot=snapshot,
            document=document,
            draft=draft,
            checkpoint=checkpoint,
        )

    async def load_document(self, document_id: str) -> PrototypeDocumentRecord | None:
        await self.initialize()
        conn = await self._get_conn()
        row = await self._load_document_row(conn, document_id)
        return self._document_from_row(row) if row is not None else None

    async def load_current_project_document(
        self,
        project_id: str,
    ) -> PrototypeDocumentRecord | None:
        await self.initialize()
        conn = await self._get_conn()
        async with conn.execute(
            """
            SELECT document.id
            FROM prototype_documents AS document
            JOIN prototype_drafts AS draft ON draft.id = document.active_draft_id
            WHERE document.project_id = ?
            ORDER BY draft.updated_at DESC, document.created_at DESC, document.rowid DESC
            LIMIT 1
            """,
            (project_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        document_row = await self._load_document_row(conn, str(row[0]))
        if document_row is None:
            raise StructuredPrototypeStoreError(
                "document_missing",
                "current structured prototype document disappeared during load",
            )
        return self._document_from_row(document_row)

    async def prepare_project_prototype_deletion(
        self,
        *,
        project_id: str,
        deletion_operation_id: str,
    ) -> PrototypeProjectDeletionCounts:
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            try:
                await conn.execute("BEGIN IMMEDIATE")
                await conn.execute("PRAGMA defer_foreign_keys = ON")
                operation_row = await self._load_operation_row(conn, deletion_operation_id)
                if operation_row is None:
                    raise StructuredPrototypeStoreError(
                        "operation_missing",
                        "prototype deletion operation does not exist",
                    )
                current_operation = self._operation_from_row(operation_row)
                if (
                    current_operation.operation_kind != "delete_project_prototype"
                    or current_operation.project_id != project_id
                    or current_operation.status != "running"
                ):
                    raise StructuredPrototypeStoreError(
                        "prototype_delete_conflict",
                        "prototype deletion operation is not running for this project",
                    )

                async with conn.execute(
                    """
                    SELECT operation.id
                    FROM prototype_operations AS operation
                    LEFT JOIN prototype_document_generation_jobs AS generation_job
                      ON generation_job.operation_id = operation.id
                     AND generation_job.project_id = operation.project_id
                    WHERE operation.project_id = ? AND operation.id <> ?
                      AND operation.status IN ('queued', 'running')
                      AND NOT (
                          operation.operation_kind = 'generation_job'
                          AND generation_job.operation_id IS NOT NULL
                          AND generation_job.status IN ('awaiting_confirmation', 'ready')
                      )
                    LIMIT 1
                    """,
                    (project_id, deletion_operation_id),
                ) as cursor:
                    busy_row = await cursor.fetchone()
                if busy_row is not None:
                    raise StructuredPrototypeStoreError(
                        "prototype_busy",
                        "prototype cannot be deleted while another prototype operation is active",
                    )

                async with conn.execute(
                    "SELECT COUNT(*) FROM prototype_documents WHERE project_id = ?",
                    (project_id,),
                ) as cursor:
                    document_row = await cursor.fetchone()
                async with conn.execute(
                    "SELECT COUNT(*) FROM prototype_document_generation_jobs WHERE project_id = ?",
                    (project_id,),
                ) as cursor:
                    generation_row = await cursor.fetchone()
                async with conn.execute(
                    "SELECT COUNT(*) FROM prototype_object_references WHERE project_id = ?",
                    (project_id,),
                ) as cursor:
                    reference_row = await cursor.fetchone()
                if document_row is None or generation_row is None or reference_row is None:
                    raise StructuredPrototypeStoreError(
                        "prototype_delete_failed",
                        "prototype deletion counts could not be loaded",
                    )
                counts = PrototypeProjectDeletionCounts(
                    documents=int(document_row[0]),
                    generation_jobs=int(generation_row[0]),
                    object_references=int(reference_row[0]),
                )

                await conn.execute(
                    "DELETE FROM prototype_object_references WHERE project_id = ?",
                    (project_id,),
                )
                await conn.execute(
                    """
                    DELETE FROM prototype_runtime_event_batches
                    WHERE session_id IN (
                        SELECT id FROM prototype_runtime_sessions WHERE project_id = ?
                    )
                    """,
                    (project_id,),
                )
                await conn.execute(
                    """
                    DELETE FROM prototype_runtime_checkpoints
                    WHERE session_id IN (
                        SELECT id FROM prototype_runtime_sessions WHERE project_id = ?
                    )
                    """,
                    (project_id,),
                )
                await conn.execute(
                    "DELETE FROM prototype_runtime_sessions WHERE project_id = ?",
                    (project_id,),
                )
                await conn.execute(
                    """
                    DELETE FROM prototype_render_artifacts
                    WHERE document_id IN (
                        SELECT id FROM prototype_documents WHERE project_id = ?
                    )
                    """,
                    (project_id,),
                )
                await conn.execute(
                    """
                    DELETE FROM prototype_render_runs
                    WHERE document_id IN (
                        SELECT id FROM prototype_documents WHERE project_id = ?
                    )
                    """,
                    (project_id,),
                )
                await conn.execute(
                    """
                    DELETE FROM prototype_ai_edit_runs
                    WHERE document_id IN (
                        SELECT id FROM prototype_documents WHERE project_id = ?
                    )
                    """,
                    (project_id,),
                )
                await conn.execute(
                    """
                    DELETE FROM prototype_ai_messages
                    WHERE thread_id IN (
                        SELECT thread.id
                        FROM prototype_ai_threads AS thread
                        JOIN prototype_documents AS document ON document.id = thread.document_id
                        WHERE document.project_id = ?
                    )
                    """,
                    (project_id,),
                )
                await conn.execute(
                    """
                    DELETE FROM prototype_ai_threads
                    WHERE document_id IN (
                        SELECT id FROM prototype_documents WHERE project_id = ?
                    )
                    """,
                    (project_id,),
                )
                await conn.execute(
                    """
                    DELETE FROM prototype_document_generation_run_items
                    WHERE job_id IN (
                        SELECT id FROM prototype_document_generation_jobs WHERE project_id = ?
                    )
                    """,
                    (project_id,),
                )
                await conn.execute(
                    """
                    DELETE FROM prototype_document_generation_runs
                    WHERE job_id IN (
                        SELECT id FROM prototype_document_generation_jobs WHERE project_id = ?
                    )
                    """,
                    (project_id,),
                )
                await conn.execute(
                    "DELETE FROM prototype_document_generation_jobs WHERE project_id = ?",
                    (project_id,),
                )
                await conn.execute(
                    """
                    DELETE FROM prototype_command_batches
                    WHERE draft_id IN (
                        SELECT draft.id
                        FROM prototype_drafts AS draft
                        JOIN prototype_documents AS document ON document.id = draft.document_id
                        WHERE document.project_id = ?
                    )
                    """,
                    (project_id,),
                )
                await conn.execute(
                    """
                    DELETE FROM prototype_revisions
                    WHERE document_id IN (
                        SELECT id FROM prototype_documents WHERE project_id = ?
                    )
                    """,
                    (project_id,),
                )
                await conn.execute(
                    """
                    DELETE FROM prototype_checkpoints
                    WHERE document_id IN (
                        SELECT id FROM prototype_documents WHERE project_id = ?
                    )
                    """,
                    (project_id,),
                )
                await conn.execute(
                    """
                    DELETE FROM prototype_drafts
                    WHERE document_id IN (
                        SELECT id FROM prototype_documents WHERE project_id = ?
                    )
                    """,
                    (project_id,),
                )
                await conn.execute(
                    "DELETE FROM prototype_documents WHERE project_id = ?",
                    (project_id,),
                )
                await conn.execute(
                    """
                    DELETE FROM prototype_operation_events
                    WHERE operation_id IN (
                        SELECT id FROM prototype_operations
                        WHERE project_id = ?
                          AND id <> ?
                    )
                    """,
                    (project_id, deletion_operation_id),
                )
                await conn.execute(
                    """
                    DELETE FROM prototype_operation_steps
                    WHERE operation_id IN (
                        SELECT id FROM prototype_operations
                        WHERE project_id = ?
                          AND id <> ?
                    )
                    """,
                    (project_id, deletion_operation_id),
                )
                await conn.execute(
                    """
                    DELETE FROM prototype_operations
                    WHERE project_id = ?
                      AND id <> ?
                    """,
                    (project_id, deletion_operation_id),
                )
            except StructuredPrototypeStoreError:
                await _rollback_to_completion(conn)
                raise
            except aiosqlite.Error as exc:
                await _rollback_to_completion(conn)
                raise StructuredPrototypeStoreError(
                    "prototype_delete_failed",
                    "prototype records could not be prepared for deletion atomically",
                ) from exc
            except BaseException:
                # Transaction boundary: cancellation must not leave an open write transaction.
                await _rollback_to_completion(conn)
                raise
            try:
                await _commit_to_completion(conn)
            except aiosqlite.Error as exc:
                raise StructuredPrototypeStoreError(
                    "prototype_delete_failed",
                    "prototype records could not be prepared for deletion atomically",
                ) from exc
        return counts

    async def finalize_project_prototype_deletion(
        self,
        *,
        project_id: str,
        deletion_operation_id: str,
        completed_operation: PrototypeOperation,
        completion_step: PrototypeOperationStep,
        completion_event: PrototypeOperationEvent,
        replay_descriptor: PrototypeObjectDescriptor,
        replay_reference: PrototypeObjectReference,
    ) -> None:
        self._validate_operation_transition_payload(
            completed_operation,
            completion_step,
            completion_event,
        )
        if (
            completed_operation.id != deletion_operation_id
            or completed_operation.operation_kind != "delete_project_prototype"
            or completed_operation.project_id != project_id
            or completed_operation.resource_kind != "project_prototype"
            or completed_operation.resource_id != project_id
            or completed_operation.status != "succeeded"
            or completion_step.completion_evidence_kind != "project_prototype_deleted"
            or completion_step.completion_evidence_ref != project_id
        ):
            raise StructuredPrototypeStoreError(
                "prototype_delete_identity_mismatch",
                "prototype deletion operation identity is inconsistent",
            )
        self._validate_replay_manifest_registration(
            descriptor=replay_descriptor,
            reference=replay_reference,
            operation=completed_operation,
            step=completion_step,
            event=completion_event,
        )

        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            try:
                await conn.execute("BEGIN IMMEDIATE")
                operation_row = await self._load_operation_row(conn, deletion_operation_id)
                if operation_row is None:
                    raise StructuredPrototypeStoreError(
                        "operation_missing",
                        "prototype deletion operation does not exist",
                    )
                current_operation = self._operation_from_row(operation_row)
                if (
                    current_operation.operation_kind != "delete_project_prototype"
                    or current_operation.project_id != project_id
                    or current_operation.status != "running"
                ):
                    raise StructuredPrototypeStoreError(
                        "prototype_delete_conflict",
                        "prototype deletion operation is not running for this project",
                    )
                async with conn.execute(
                    """
                    SELECT
                        EXISTS(SELECT 1 FROM prototype_documents WHERE project_id = ?),
                        EXISTS(
                            SELECT 1 FROM prototype_document_generation_jobs
                            WHERE project_id = ?
                        ),
                        EXISTS(
                            SELECT 1 FROM prototype_object_references WHERE project_id = ?
                        ),
                        EXISTS(
                            SELECT 1 FROM prototype_operations
                            WHERE project_id = ? AND id <> ?
                        )
                    """,
                    (project_id, project_id, project_id, project_id, deletion_operation_id),
                ) as cursor:
                    prepared_row = await cursor.fetchone()
                if prepared_row is None or any(int(value) != 0 for value in prepared_row):
                    raise StructuredPrototypeStoreError(
                        "prototype_delete_not_prepared",
                        "prototype deletion cannot finish before its records are prepared",
                    )
                await conn.execute(
                    "DELETE FROM prototype_objects WHERE project_id = ?",
                    (project_id,),
                )
                await self._register_object_tx(conn, replay_descriptor)
                await self._insert_object_reference(conn, replay_reference)
                await self._apply_operation_transition(
                    conn,
                    completed_operation,
                    completion_step,
                    completion_event,
                )
            except StructuredPrototypeStoreError:
                await _rollback_to_completion(conn)
                raise
            except aiosqlite.Error as exc:
                await _rollback_to_completion(conn)
                raise StructuredPrototypeStoreError(
                    "prototype_delete_failed",
                    "prototype deletion could not be finalized atomically",
                ) from exc
            except BaseException:
                # Transaction boundary: cancellation must not leave an open write transaction.
                await _rollback_to_completion(conn)
                raise
            try:
                await _commit_to_completion(conn)
            except aiosqlite.Error as exc:
                raise StructuredPrototypeStoreError(
                    "prototype_delete_failed",
                    "prototype deletion could not be finalized atomically",
                ) from exc

    async def load_draft(self, draft_id: str) -> PrototypeDraftRecord | None:
        await self.initialize()
        conn = await self._get_conn()
        row = await self._load_draft_row(conn, draft_id)
        return self._draft_from_row(row) if row is not None else None

    async def create_ai_thread(
        self,
        thread: PrototypeAiThreadRecord,
    ) -> PrototypeAiThreadRecord:
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                document = await self._load_document_row(conn, thread.document_id)
                if document is None:
                    raise StructuredPrototypeStoreError(
                        "document_missing",
                        "prototype document does not exist",
                    )
                existing = await self._load_ai_thread_row(conn, thread.id)
                if existing is None:
                    await conn.execute(
                        """
                        INSERT INTO prototype_ai_threads (
                            id, document_id, title, status, summary_json,
                            summary_through_message_id, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        self._ai_thread_params(thread),
                    )
                    result = thread
                else:
                    result = self._ai_thread_from_row(existing)
                    if self._ai_thread_params(result)[:6] != self._ai_thread_params(thread)[:6]:
                        raise StructuredPrototypeStoreError(
                            "ai_thread_idempotency_conflict",
                            "prototype AI thread identity conflicts with an existing thread",
                        )
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return result

    async def list_ai_threads(self, document_id: str) -> list[PrototypeAiThreadRecord]:
        await self.initialize()
        conn = await self._get_conn()
        async with conn.execute(
            """
            SELECT id, document_id, title, status, summary_json,
                   summary_through_message_id, created_at, updated_at
            FROM prototype_ai_threads
            WHERE document_id = ?
            ORDER BY updated_at DESC, id DESC
            """,
            (document_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._ai_thread_from_row(row) for row in rows]

    async def load_ai_thread_snapshot(
        self,
        thread_id: str,
    ) -> PrototypeAiThreadSnapshot | None:
        await self.initialize()
        conn = await self._get_conn()
        thread_row = await self._load_ai_thread_row(conn, thread_id)
        if thread_row is None:
            return None
        async with conn.execute(
            """
            SELECT id, thread_id, client_message_id, role, kind, content,
                   run_id, command_batch_id, status, created_at, updated_at
            FROM prototype_ai_messages
            WHERE thread_id = ?
            ORDER BY created_at, rowid
            """,
            (thread_id,),
        ) as cursor:
            message_rows = await cursor.fetchall()
        async with conn.execute(
            f"""
            SELECT {self._AI_EDIT_RUN_COLUMNS}
            FROM prototype_ai_edit_runs
            WHERE thread_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (thread_id,),
        ) as cursor:
            run_row = await cursor.fetchone()
        return PrototypeAiThreadSnapshot(
            thread=self._ai_thread_from_row(thread_row),
            messages=tuple(self._ai_message_from_row(row) for row in message_rows),
            latest_run=self._ai_edit_run_from_row(run_row) if run_row is not None else None,
        )

    async def load_ai_edit_run(self, run_id: str) -> PrototypeAiEditRunRecord | None:
        await self.initialize()
        conn = await self._get_conn()
        row = await self._load_ai_edit_run_row(conn, run_id)
        return self._ai_edit_run_from_row(row) if row is not None else None

    async def create_ai_message_run(
        self,
        *,
        operation: PrototypeOperation,
        initial_event: PrototypeOperationEvent,
        message: PrototypeAiMessageRecord,
        run: PrototypeAiEditRunRecord,
    ) -> PrototypeAiMessageRunCreateResult:
        self._validate_new_operation(operation, initial_event)
        if (
            operation.id != run.operation_id
            or message.id != run.user_message_id
            or message.thread_id != run.thread_id
            or message.run_id != run.id
            or message.role != "user"
            or message.kind != "instruction"
            or message.status != "pending"
        ):
            raise StructuredPrototypeStoreError(
                "ai_run_identity_mismatch",
                "prototype AI message, run, and operation identities do not match",
            )
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                existing_message_row = await self._load_ai_message_by_request_row(
                    conn,
                    message.thread_id,
                    message.client_message_id,
                )
                if existing_message_row is not None:
                    existing_message = self._ai_message_from_row(existing_message_row)
                    if existing_message.run_id is None:
                        raise StructuredPrototypeStoreError(
                            "ai_run_result_missing",
                            "prototype AI message has no correlated edit run",
                        )
                    existing_run_row = await self._load_ai_edit_run_row(
                        conn,
                        existing_message.run_id,
                    )
                    if existing_run_row is None:
                        raise StructuredPrototypeStoreError(
                            "ai_run_result_missing",
                            "prototype AI edit run disappeared",
                        )
                    existing_run = self._ai_edit_run_from_row(existing_run_row)
                    self._assert_ai_message_idempotent(existing_message, message)
                    self._assert_ai_edit_run_idempotent(existing_run, run)
                    result = PrototypeAiMessageRunCreateResult(
                        message=existing_message,
                        run=existing_run,
                        created=False,
                    )
                else:
                    thread_row = await self._load_ai_thread_row(conn, message.thread_id)
                    if thread_row is None:
                        raise StructuredPrototypeStoreError(
                            "ai_thread_missing",
                            "prototype AI thread does not exist",
                        )
                    thread = self._ai_thread_from_row(thread_row)
                    if thread.status != "active" or thread.document_id != run.document_id:
                        raise StructuredPrototypeStoreError(
                            "ai_thread_unavailable",
                            "prototype AI thread cannot accept this message",
                        )
                    draft = await self._require_draft(conn, run.draft_id)
                    if (
                        draft.document_id != run.document_id
                        or draft.status != "active"
                        or draft.head_sequence_no != run.base_head_sequence_no
                        or draft.head_document_hash != run.base_document_hash
                    ):
                        raise StructuredPrototypeStoreError(
                            "draft_conflict",
                            "prototype AI run base does not match the active draft",
                        )
                    async with conn.execute(
                        """
                        SELECT id
                        FROM prototype_ai_edit_runs
                        WHERE draft_id = ? AND status IN (
                            'queued', 'building_context', 'generating',
                            'validating', 'rendering_preview', 'preview_ready'
                        )
                        LIMIT 1
                        """,
                        (run.draft_id,),
                    ) as cursor:
                        active_run = await cursor.fetchone()
                    if active_run is not None:
                        raise StructuredPrototypeStoreError(
                            "ai_run_conflict",
                            "prototype draft already has an open AI edit run",
                        )
                    await self._insert_operation(conn, operation)
                    await self._insert_operation_event(conn, initial_event)
                    await self._insert_ai_message(conn, message)
                    await self._insert_ai_edit_run(conn, run)
                    await conn.execute(
                        "UPDATE prototype_ai_threads SET updated_at = ? WHERE id = ?",
                        (run.created_at.isoformat(), run.thread_id),
                    )
                    result = PrototypeAiMessageRunCreateResult(
                        message=message,
                        run=run,
                        created=True,
                    )
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return result

    async def transition_ai_edit_run(
        self,
        *,
        run: PrototypeAiEditRunRecord,
        expected_statuses: tuple[str, ...],
        assistant_message: PrototypeAiMessageRecord | None = None,
        descriptors_and_references: tuple[
            tuple[PrototypeObjectDescriptor, PrototypeObjectReference], ...
        ] = (),
        operation_transitions: tuple[
            tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent], ...
        ] = (),
    ) -> PrototypeAiEditRunRecord:
        if not expected_statuses:
            raise StructuredPrototypeStoreError(
                "ai_run_transition_invalid",
                "prototype AI transition requires an expected status",
            )
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                current_row = await self._load_ai_edit_run_row(conn, run.id)
                if current_row is None:
                    raise StructuredPrototypeStoreError(
                        "ai_run_missing",
                        "prototype AI edit run does not exist",
                    )
                current = self._ai_edit_run_from_row(current_row)
                if current.status not in expected_statuses:
                    raise StructuredPrototypeStoreError(
                        "ai_run_conflict",
                        "prototype AI edit run status changed before transition",
                    )
                self._assert_ai_edit_run_immutable_identity(current, run)
                for descriptor, reference in descriptors_and_references:
                    self._validate_registration(descriptor, reference)
                    await self._register_object_tx(conn, descriptor)
                    await self._insert_object_reference(conn, reference)
                if assistant_message is not None:
                    if (
                        assistant_message.thread_id != run.thread_id
                        or assistant_message.run_id != run.id
                        or assistant_message.role != "assistant"
                        or assistant_message.id != run.assistant_message_id
                    ):
                        raise StructuredPrototypeStoreError(
                            "ai_message_identity_mismatch",
                            "prototype AI assistant message does not match its run",
                        )
                    await self._insert_ai_message(conn, assistant_message)
                    user_status = "failed" if assistant_message.status == "failed" else "completed"
                    await conn.execute(
                        """
                        UPDATE prototype_ai_messages
                        SET status = ?, updated_at = ?
                        WHERE id = ? AND run_id = ? AND role = 'user' AND status = 'pending'
                        """,
                        (
                            user_status,
                            run.updated_at.isoformat(),
                            run.user_message_id,
                            run.id,
                        ),
                    )
                for operation, step, event in operation_transitions:
                    await self._apply_operation_transition(conn, operation, step, event)
                await self._update_ai_edit_run(conn, run)
                if run.status == "failed" and run.preview_render_run_id is not None:
                    await conn.execute(
                        """
                        UPDATE prototype_render_runs
                        SET status = 'failed', error_code = ?, error_message = ?,
                            completed_at = ?, updated_at = ?
                        WHERE id = ? AND status IN ('queued', 'rendering')
                        """,
                        (
                            run.error_code,
                            run.error_message,
                            run.completed_at.isoformat() if run.completed_at is not None else None,
                            run.updated_at.isoformat(),
                            run.preview_render_run_id,
                        ),
                    )
                await conn.execute(
                    "UPDATE prototype_ai_threads SET updated_at = ? WHERE id = ?",
                    (run.updated_at.isoformat(), run.thread_id),
                )
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return run

    async def reject_ai_edit_run(
        self,
        *,
        queued_operation: PrototypeOperation,
        queued_event: PrototypeOperationEvent,
        running_transition: tuple[
            PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent
        ],
        replay_descriptor: PrototypeObjectDescriptor,
        replay_reference: PrototypeObjectReference,
        completed_transition: tuple[
            PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent
        ],
        run: PrototypeAiEditRunRecord,
        assistant_message: PrototypeAiMessageRecord,
    ) -> PrototypeAiEditRunRecord:
        self._validate_new_operation(queued_operation, queued_event)
        running_operation, running_step, running_event = running_transition
        completed_operation, completed_step, completed_event = completed_transition
        self._validate_operation_transition_payload(
            running_operation,
            running_step,
            running_event,
        )
        self._validate_operation_transition_payload(
            completed_operation,
            completed_step,
            completed_event,
        )
        self._validate_registration(replay_descriptor, replay_reference)
        if (
            run.status != "rejected"
            or queued_operation.operation_kind != "reject_ai_proposal"
            or queued_operation.resource_kind != "ai_edit_run"
            or queued_operation.resource_id != run.id
            or queued_operation.parent_operation_id != run.operation_id
            or completed_operation.status != "succeeded"
            or completed_operation.result_manifest_hash != replay_descriptor.content_hash
            or completed_step.status != "succeeded"
            or completed_step.completion_evidence_ref != replay_descriptor.content_hash
            or replay_reference.owner_kind != "replay_manifest"
            or replay_reference.owner_id != queued_operation.id
            or replay_reference.payload_type != "replay_manifest"
            or assistant_message.id != run.assistant_message_id
            or assistant_message.run_id != run.id
            or assistant_message.status != "rejected"
        ):
            raise StructuredPrototypeStoreError(
                "ai_reject_identity_mismatch",
                "prototype AI reject identities are inconsistent",
            )
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                current_row = await self._load_ai_edit_run_row(conn, run.id)
                if current_row is None:
                    raise StructuredPrototypeStoreError(
                        "ai_run_missing", "prototype AI edit run does not exist"
                    )
                current = self._ai_edit_run_from_row(current_row)
                if current.status != "preview_ready":
                    raise StructuredPrototypeStoreError(
                        "ai_run_conflict", "prototype AI proposal is no longer ready"
                    )
                self._assert_ai_edit_run_immutable_identity(current, run)
                await self._insert_operation(conn, queued_operation)
                await self._insert_operation_event(conn, queued_event)
                await self._apply_operation_transition(
                    conn,
                    running_operation,
                    running_step,
                    running_event,
                )
                await self._register_object_tx(conn, replay_descriptor)
                await self._insert_object_reference(conn, replay_reference)
                cursor = await conn.execute(
                    """
                    UPDATE prototype_ai_messages
                    SET status = 'rejected', updated_at = ?
                    WHERE id = ? AND run_id = ? AND status = 'completed'
                    """,
                    (assistant_message.updated_at.isoformat(), assistant_message.id, run.id),
                )
                if cursor.rowcount != 1:
                    raise StructuredPrototypeStoreError(
                        "ai_message_conflict",
                        "prototype AI proposal message changed before reject",
                    )
                await self._update_ai_edit_run(conn, run)
                await self._apply_operation_transition(
                    conn,
                    completed_operation,
                    completed_step,
                    completed_event,
                )
                await conn.execute(
                    "UPDATE prototype_ai_threads SET updated_at = ? WHERE id = ?",
                    (run.updated_at.isoformat(), run.thread_id),
                )
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return run

    async def interrupt_active_ai_edit_runs(self, interrupted_at: datetime) -> int:
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = await conn.execute(
                    """
                    UPDATE prototype_ai_edit_runs
                    SET status = 'interrupted', error_code = 'restart_interrupted',
                        error_message = 'prototype AI edit was interrupted by backend restart',
                        updated_at = ?, completed_at = ?
                    WHERE status IN (
                        'queued', 'building_context', 'generating',
                        'validating', 'rendering_preview'
                    )
                    """,
                    (interrupted_at.isoformat(), interrupted_at.isoformat()),
                )
                await conn.execute(
                    """
                    UPDATE prototype_ai_messages
                    SET status = 'failed', updated_at = ?
                    WHERE role = 'user' AND status = 'pending'
                      AND run_id IN (
                          SELECT id FROM prototype_ai_edit_runs
                          WHERE status = 'interrupted' AND error_code = 'restart_interrupted'
                      )
                    """,
                    (interrupted_at.isoformat(),),
                )
            except aiosqlite.Error:
                await conn.rollback()
                raise
            await conn.commit()
        return cursor.rowcount

    async def freeze_ai_preview(
        self,
        *,
        run: PrototypeAiEditRunRecord,
        render_run: PrototypeRenderRunRecord,
        descriptors_and_references: tuple[
            tuple[PrototypeObjectDescriptor, PrototypeObjectReference], ...
        ],
        operation_transitions: tuple[
            tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent], ...
        ],
    ) -> None:
        if run.status != "rendering_preview" or render_run.status != "rendering":
            raise StructuredPrototypeStoreError(
                "ai_preview_transition_invalid",
                "prototype AI preview must enter the rendering state",
            )
        if (
            render_run.ai_edit_run_id != run.id
            or render_run.document_id != run.document_id
            or render_run.operation_id != run.operation_id
            or render_run.document_hash != run.candidate_object_hash
        ):
            raise StructuredPrototypeStoreError(
                "ai_preview_identity_mismatch",
                "prototype AI preview identities do not match",
            )
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                current_row = await self._load_ai_edit_run_row(conn, run.id)
                if current_row is None:
                    raise StructuredPrototypeStoreError(
                        "ai_run_missing", "prototype AI edit run does not exist"
                    )
                current = self._ai_edit_run_from_row(current_row)
                if current.status != "validating":
                    raise StructuredPrototypeStoreError(
                        "ai_run_conflict",
                        "prototype AI edit run changed before preview freeze",
                    )
                self._assert_ai_edit_run_immutable_identity(current, run)
                draft = await self._require_draft(conn, run.draft_id)
                if (
                    draft.status != "active"
                    or draft.head_sequence_no != run.base_head_sequence_no
                    or draft.head_document_hash != run.base_document_hash
                ):
                    raise StructuredPrototypeStoreError(
                        "draft_conflict",
                        "prototype draft changed before AI preview freeze",
                    )
                for descriptor, reference in descriptors_and_references:
                    self._validate_registration(descriptor, reference)
                    await self._register_object_tx(conn, descriptor)
                    await self._insert_object_reference(conn, reference)
                await self._insert_render_run(conn, render_run)
                for operation, step, event in operation_transitions:
                    await self._apply_operation_transition(conn, operation, step, event)
                await self._update_ai_edit_run(conn, run)
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()

    async def complete_ai_preview(
        self,
        *,
        run: PrototypeAiEditRunRecord,
        render_run: PrototypeRenderRunRecord,
        artifact: PrototypeRenderArtifactRecord,
        assistant_message: PrototypeAiMessageRecord,
        descriptors_and_references: tuple[
            tuple[PrototypeObjectDescriptor, PrototypeObjectReference], ...
        ],
        operation_transitions: tuple[
            tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent], ...
        ],
    ) -> None:
        if run.status != "preview_ready" or render_run.status != "ready":
            raise StructuredPrototypeStoreError(
                "ai_preview_transition_invalid",
                "prototype AI preview completion state is invalid",
            )
        if (
            run.preview_render_run_id != render_run.id
            or run.preview_artifact_id != artifact.id
            or render_run.artifact_id != artifact.id
            or artifact.render_run_id != render_run.id
            or artifact.document_id != run.document_id
            or artifact.revision_id is not None
        ):
            raise StructuredPrototypeStoreError(
                "ai_preview_identity_mismatch",
                "prototype AI preview completion identities do not match",
            )
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                current_row = await self._load_ai_edit_run_row(conn, run.id)
                if current_row is None:
                    raise StructuredPrototypeStoreError(
                        "ai_run_missing", "prototype AI edit run does not exist"
                    )
                current = self._ai_edit_run_from_row(current_row)
                if current.status != "rendering_preview":
                    raise StructuredPrototypeStoreError(
                        "ai_run_conflict",
                        "prototype AI edit run changed before preview completion",
                    )
                self._assert_ai_edit_run_immutable_identity(current, run)
                current_render_row = await self._load_render_run_row(conn, render_run.id)
                if current_render_row is None:
                    raise StructuredPrototypeStoreError(
                        "render_run_missing", "prototype AI preview render run does not exist"
                    )
                current_render = self._render_run_from_row(current_render_row)
                if current_render.status != "rendering":
                    raise StructuredPrototypeStoreError(
                        "render_run_conflict",
                        "prototype AI preview render run changed before completion",
                    )
                for descriptor, reference in descriptors_and_references:
                    self._validate_registration(descriptor, reference)
                    await self._register_object_tx(conn, descriptor)
                    await self._insert_object_reference(conn, reference)
                await conn.execute(
                    """
                    UPDATE prototype_render_runs
                    SET status = 'ready', artifact_id = ?, output_manifest_hash = ?,
                        error_code = NULL, error_message = NULL, completed_at = ?, updated_at = ?
                    WHERE id = ? AND status = 'rendering'
                    """,
                    (
                        render_run.artifact_id,
                        render_run.output_manifest_hash,
                        render_run.completed_at.isoformat()
                        if render_run.completed_at is not None
                        else None,
                        render_run.updated_at.isoformat(),
                        render_run.id,
                    ),
                )
                await self._insert_render_artifact(conn, artifact)
                await self._insert_ai_message(conn, assistant_message)
                await conn.execute(
                    """
                    UPDATE prototype_ai_messages
                    SET status = 'completed', updated_at = ?
                    WHERE id = ? AND run_id = ? AND role = 'user' AND status = 'pending'
                    """,
                    (run.updated_at.isoformat(), run.user_message_id, run.id),
                )
                for operation, step, event in operation_transitions:
                    await self._apply_operation_transition(conn, operation, step, event)
                await self._update_ai_edit_run(conn, run)
                await conn.execute(
                    "UPDATE prototype_ai_threads SET updated_at = ? WHERE id = ?",
                    (run.updated_at.isoformat(), run.thread_id),
                )
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()

    async def apply_ai_edit_run(
        self,
        *,
        queued_operation: PrototypeOperation,
        queued_event: PrototypeOperationEvent,
        running_transition: tuple[
            PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent
        ],
        batch: PrototypeCommandBatchRecord,
        base_history_checkpoint: PrototypeCommandHistoryCheckpoint,
        base_tail_batches: tuple[PrototypeCommandBatchRecord, ...],
        base_journal_prefix_hash: str,
        descriptor: PrototypeObjectDescriptor,
        reference: PrototypeObjectReference,
        history_descriptor: PrototypeObjectDescriptor,
        history_reference: PrototypeObjectReference,
        history_checkpoint: PrototypeCommandHistoryCheckpoint,
        replay_descriptor: PrototypeObjectDescriptor,
        replay_reference: PrototypeObjectReference,
        checkpoint: PrototypeCheckpointRecord,
        completed_transition: tuple[
            PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent
        ],
        run: PrototypeAiEditRunRecord,
        assistant_message: PrototypeAiMessageRecord,
    ) -> PrototypeCommandAppendResult:
        self._validate_new_operation(queued_operation, queued_event)
        running_operation, running_step, running_event = running_transition
        completed_operation, completed_step, completed_event = completed_transition
        self._validate_command_append(
            batch,
            completed_operation,
            completed_step,
            completed_event,
        )
        self._validate_registration(descriptor, reference)
        self._validate_history_checkpoint_artifact(
            descriptor=history_descriptor,
            reference=history_reference,
            history_checkpoint=history_checkpoint,
            checkpoint=checkpoint,
        )
        self._validate_registration(replay_descriptor, replay_reference)
        if (
            run.status != "applied"
            or batch.origin != "ai"
            or batch.operation_kind != "forward"
            or run.proposed_command_batch_json != batch.commands_json
            or run.candidate_object_hash != batch.result_document_hash
            or checkpoint.draft_id != run.draft_id
            or checkpoint.checkpoint_kind != "ai_apply"
            or checkpoint.checkpoint_sequence_no != batch.result_sequence_no
            or checkpoint.document_object_hash != descriptor.content_hash
            or checkpoint.document_hash != batch.result_document_hash
            or checkpoint.created_by_operation_id != queued_operation.id
            or reference.owner_kind != "checkpoint"
            or reference.owner_id != checkpoint.id
            or reference.payload_type != "prototype_document"
            or completed_operation.result_manifest_hash != replay_descriptor.content_hash
            or replay_reference.owner_kind != "replay_manifest"
            or replay_reference.owner_id != queued_operation.id
            or replay_reference.payload_type != "replay_manifest"
            or assistant_message.id != run.assistant_message_id
            or assistant_message.command_batch_id != batch.id
            or assistant_message.status != "applied"
        ):
            raise StructuredPrototypeStoreError(
                "ai_apply_identity_mismatch",
                "prototype AI apply identities are inconsistent",
            )
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                current_run_row = await self._load_ai_edit_run_row(conn, run.id)
                if current_run_row is None:
                    raise StructuredPrototypeStoreError(
                        "ai_run_missing", "prototype AI edit run does not exist"
                    )
                current_run = self._ai_edit_run_from_row(current_run_row)
                if current_run.status != "preview_ready":
                    raise StructuredPrototypeStoreError(
                        "ai_run_conflict", "prototype AI proposal is no longer ready"
                    )
                self._assert_ai_edit_run_immutable_identity(current_run, run)
                draft = await self._require_draft(conn, run.draft_id)
                await self._assert_draft_accepts_batch(conn, draft, batch)
                history, records_by_id = await self._validate_bounded_command_history_base(
                    conn,
                    draft=draft,
                    base_history_checkpoint=base_history_checkpoint,
                    base_tail_batches=base_tail_batches,
                    base_journal_prefix_hash=base_journal_prefix_hash,
                )
                await self._assert_command_history_accepts_batch(
                    conn,
                    history,
                    batch,
                    records_by_id,
                )
                await self._insert_operation(conn, queued_operation)
                await self._insert_operation_event(conn, queued_event)
                await self._apply_operation_transition(
                    conn,
                    running_operation,
                    running_step,
                    running_event,
                )
                await self._register_object_tx(conn, descriptor)
                await self._insert_object_reference(conn, reference)
                await self._register_object_tx(conn, history_descriptor)
                await self._insert_object_reference(conn, history_reference)
                await self._register_object_tx(conn, replay_descriptor)
                await self._insert_object_reference(conn, replay_reference)
                await self._insert_command_batch(conn, batch)
                await self._insert_checkpoint(conn, checkpoint)
                cursor = await conn.execute(
                    """
                    UPDATE prototype_drafts
                    SET head_sequence_no = ?, head_document_hash = ?,
                        latest_checkpoint_id = ?, updated_at = ?
                    WHERE id = ? AND status = 'active'
                      AND head_sequence_no = ? AND head_document_hash = ?
                    """,
                    (
                        batch.result_sequence_no,
                        batch.result_document_hash,
                        checkpoint.id,
                        run.updated_at.isoformat(),
                        run.draft_id,
                        batch.base_sequence_no,
                        batch.base_document_hash,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StructuredPrototypeStoreError(
                        "draft_conflict",
                        "prototype draft changed before AI proposal apply",
                    )
                message_cursor = await conn.execute(
                    """
                    UPDATE prototype_ai_messages
                    SET command_batch_id = ?, status = 'applied', updated_at = ?
                    WHERE id = ? AND run_id = ? AND status = 'completed'
                    """,
                    (
                        batch.id,
                        assistant_message.updated_at.isoformat(),
                        assistant_message.id,
                        run.id,
                    ),
                )
                if message_cursor.rowcount != 1:
                    raise StructuredPrototypeStoreError(
                        "ai_message_conflict",
                        "prototype AI proposal message changed before apply",
                    )
                await self._apply_operation_transition(
                    conn,
                    completed_operation,
                    completed_step,
                    completed_event,
                )
                await self._update_ai_edit_run(conn, run)
                updated_draft = await self._require_draft(conn, run.draft_id)
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return PrototypeCommandAppendResult(batch=batch, draft=updated_draft, created=True)

    async def load_command_batch_by_request(
        self,
        draft_id: str,
        client_request_id: str,
    ) -> PrototypeCommandBatchRecord | None:
        await self.initialize()
        conn = await self._get_conn()
        row = await self._load_command_batch_by_request_row(
            conn,
            draft_id,
            client_request_id,
        )
        return self._command_batch_from_row(row) if row is not None else None

    async def load_command_batch(
        self,
        draft_id: str,
        batch_id: str,
    ) -> PrototypeCommandBatchRecord | None:
        await self.initialize()
        conn = await self._get_conn()
        row = await self._load_command_batch_row(conn, draft_id, batch_id)
        return self._command_batch_from_row(row) if row is not None else None

    async def record_operation_transition(
        self,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        event: PrototypeOperationEvent,
    ) -> None:
        self._validate_operation_transition_payload(operation, step, event)
        if operation.status == "succeeded":
            raise StructuredPrototypeStoreError(
                "replay_manifest_registration_required",
                "successful prototype operations require atomic replay manifest registration",
            )
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                await self._apply_operation_transition(conn, operation, step, event)
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()

    async def register_replay_manifest_and_transition(
        self,
        *,
        replay_descriptor: PrototypeObjectDescriptor,
        replay_reference: PrototypeObjectReference,
        completed_operation: PrototypeOperation,
        completion_step: PrototypeOperationStep,
        completion_event: PrototypeOperationEvent,
    ) -> None:
        self._validate_replay_manifest_registration(
            descriptor=replay_descriptor,
            reference=replay_reference,
            operation=completed_operation,
            step=completion_step,
            event=completion_event,
        )
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                await self._register_object_tx(conn, replay_descriptor)
                await self._insert_object_reference(conn, replay_reference)
                await self._apply_operation_transition(
                    conn,
                    completed_operation,
                    completion_step,
                    completion_event,
                )
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()

    async def register_generation_failure_evidence_and_transition(
        self,
        *,
        descriptor: PrototypeObjectDescriptor,
        reference: PrototypeObjectReference,
        failed_operation: PrototypeOperation,
        failed_step: PrototypeOperationStep,
        failed_event: PrototypeOperationEvent,
    ) -> None:
        self._validate_generation_failure_evidence_registration(
            descriptor=descriptor,
            reference=reference,
            operation=failed_operation,
            step=failed_step,
            event=failed_event,
        )
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                async with conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM prototype_object_references
                    WHERE project_id = ?
                      AND owner_kind = 'replay_manifest'
                      AND owner_id = ?
                    """,
                    (reference.project_id, reference.owner_id),
                ) as cursor:
                    existing_row = await cursor.fetchone()
                if (
                    existing_row is None
                    or _required_non_negative_int(
                        existing_row[0],
                        "generation_failure_evidence.reference_count",
                    )
                    != 0
                ):
                    raise StructuredPrototypeStoreError(
                        "generation_failure_evidence_invalid",
                        "generation operation already owns terminal evidence",
                    )
                await self._register_object_tx(conn, descriptor)
                await self._insert_object_reference(conn, reference)
                await self._apply_operation_transition(
                    conn,
                    failed_operation,
                    failed_step,
                    failed_event,
                )
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()

    async def create_document_with_initial_checkpoint(
        self,
        *,
        descriptor: PrototypeObjectDescriptor,
        reference: PrototypeObjectReference,
        history_descriptor: PrototypeObjectDescriptor,
        history_reference: PrototypeObjectReference,
        history_checkpoint: PrototypeCommandHistoryCheckpoint,
        document: PrototypeDocumentRecord,
        draft: PrototypeDraftRecord,
        checkpoint: PrototypeCheckpointRecord,
        completed_operation: PrototypeOperation,
        completion_step: PrototypeOperationStep,
        completion_event: PrototypeOperationEvent,
        replay_descriptor: PrototypeObjectDescriptor,
        replay_reference: PrototypeObjectReference,
    ) -> None:
        self._validate_initial_checkpoint(
            descriptor=descriptor,
            reference=reference,
            history_descriptor=history_descriptor,
            history_reference=history_reference,
            history_checkpoint=history_checkpoint,
            document=document,
            draft=draft,
            checkpoint=checkpoint,
            completed_operation=completed_operation,
            completion_step=completion_step,
            completion_event=completion_event,
        )
        self._validate_replay_manifest_registration(
            descriptor=replay_descriptor,
            reference=replay_reference,
            operation=completed_operation,
            step=completion_step,
            event=completion_event,
        )
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                await self._register_object_tx(conn, descriptor)
                await self._register_object_tx(conn, history_descriptor)
                await self._register_object_tx(conn, replay_descriptor)
                await conn.execute(
                    """
                    INSERT INTO prototype_documents (
                        id,
                        project_id,
                        title,
                        published_revision_no,
                        active_draft_id,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (
                        document.id,
                        document.project_id,
                        document.title,
                        document.published_revision_no,
                        document.created_at.isoformat(),
                        document.updated_at.isoformat(),
                    ),
                )
                await conn.execute(
                    """
                    INSERT INTO prototype_drafts (
                        id,
                        document_id,
                        base_revision_no,
                        status,
                        head_sequence_no,
                        head_document_hash,
                        latest_checkpoint_id,
                        publish_revision_no,
                        created_at,
                        updated_at,
                        closed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
                    """,
                    self._initial_draft_params(draft),
                )
                await self._insert_checkpoint(conn, checkpoint)
                await self._insert_object_reference(conn, reference)
                await self._insert_object_reference(conn, history_reference)
                await self._insert_object_reference(conn, replay_reference)
                await conn.execute(
                    "UPDATE prototype_documents SET active_draft_id = ? WHERE id = ?",
                    (draft.id, document.id),
                )
                await conn.execute(
                    "UPDATE prototype_drafts SET latest_checkpoint_id = ? WHERE id = ?",
                    (checkpoint.id, draft.id),
                )
                await self._apply_operation_transition(
                    conn,
                    completed_operation,
                    completion_step,
                    completion_event,
                )
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()

    async def append_command_batch(
        self,
        *,
        batch: PrototypeCommandBatchRecord,
        base_history_checkpoint: PrototypeCommandHistoryCheckpoint,
        base_tail_batches: tuple[PrototypeCommandBatchRecord, ...],
        base_journal_prefix_hash: str,
        completed_operation: PrototypeOperation,
        completion_step: PrototypeOperationStep,
        completion_event: PrototypeOperationEvent,
        replay_descriptor: PrototypeObjectDescriptor,
        replay_reference: PrototypeObjectReference,
    ) -> PrototypeCommandAppendResult:
        self._validate_command_append(
            batch,
            completed_operation,
            completion_step,
            completion_event,
        )
        self._validate_replay_manifest_registration(
            descriptor=replay_descriptor,
            reference=replay_reference,
            operation=completed_operation,
            step=completion_step,
            event=completion_event,
        )
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                draft = await self._require_draft(conn, batch.draft_id)
                existing_row = await self._load_command_batch_by_request_row(
                    conn, batch.draft_id, batch.client_request_id
                )
                if existing_row is not None:
                    existing = self._command_batch_from_row(existing_row)
                    self._assert_idempotent_command_batch(existing, batch)
                    result = PrototypeCommandAppendResult(
                        batch=existing,
                        draft=draft,
                        created=False,
                    )
                else:
                    await self._assert_draft_accepts_batch(conn, draft, batch)
                    history, records_by_id = await self._validate_bounded_command_history_base(
                        conn,
                        draft=draft,
                        base_history_checkpoint=base_history_checkpoint,
                        base_tail_batches=base_tail_batches,
                        base_journal_prefix_hash=base_journal_prefix_hash,
                    )
                    await self._assert_command_history_accepts_batch(
                        conn,
                        history,
                        batch,
                        records_by_id,
                    )
                    await self._insert_command_batch(conn, batch)
                    cursor = await conn.execute(
                        """
                        UPDATE prototype_drafts
                        SET head_sequence_no = ?, head_document_hash = ?, updated_at = ?
                        WHERE id = ?
                          AND status = 'active'
                          AND head_sequence_no = ?
                          AND head_document_hash = ?
                        """,
                        (
                            batch.result_sequence_no,
                            batch.result_document_hash,
                            batch.created_at.isoformat(),
                            batch.draft_id,
                            batch.base_sequence_no,
                            batch.base_document_hash,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise StructuredPrototypeStoreError(
                            "draft_conflict",
                            "prototype draft head changed before command commit",
                        )
                    await self._register_object_tx(conn, replay_descriptor)
                    await self._insert_object_reference(conn, replay_reference)
                    await self._apply_operation_transition(
                        conn,
                        completed_operation,
                        completion_step,
                        completion_event,
                    )
                    updated_draft = await self._require_draft(conn, batch.draft_id)
                    result = PrototypeCommandAppendResult(
                        batch=batch,
                        draft=updated_draft,
                        created=True,
                    )
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return result

    async def register_draft_checkpoint(
        self,
        *,
        descriptor: PrototypeObjectDescriptor,
        reference: PrototypeObjectReference,
        history_descriptor: PrototypeObjectDescriptor,
        history_reference: PrototypeObjectReference,
        history_checkpoint: PrototypeCommandHistoryCheckpoint,
        checkpoint: PrototypeCheckpointRecord,
        completed_operation: PrototypeOperation,
        completion_step: PrototypeOperationStep,
        completion_event: PrototypeOperationEvent,
        replay_descriptor: PrototypeObjectDescriptor,
        replay_reference: PrototypeObjectReference,
    ) -> PrototypeDraftRecord:
        self._validate_checkpoint_registration(
            descriptor,
            reference,
            history_descriptor,
            history_reference,
            history_checkpoint,
            checkpoint,
            completed_operation,
            completion_step,
            completion_event,
        )
        self._validate_replay_manifest_registration(
            descriptor=replay_descriptor,
            reference=replay_reference,
            operation=completed_operation,
            step=completion_step,
            event=completion_event,
        )
        if checkpoint.draft_id is None:
            raise StructuredPrototypeStoreError(
                "checkpoint_identity_mismatch",
                "draft checkpoint must reference a draft",
            )
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                draft = await self._require_draft(conn, checkpoint.draft_id)
                if draft.status not in {"active", "publishing"}:
                    raise StructuredPrototypeStoreError(
                        "checkpoint_head_conflict",
                        "prototype draft does not accept checkpoints in its current state",
                    )
                if (
                    draft.head_sequence_no != checkpoint.checkpoint_sequence_no
                    or draft.head_document_hash != checkpoint.document_hash
                ):
                    raise StructuredPrototypeStoreError(
                        "checkpoint_head_conflict",
                        "prototype checkpoint does not match the current draft head",
                    )
                await self._register_object_tx(conn, descriptor)
                await self._register_object_tx(conn, history_descriptor)
                await self._register_object_tx(conn, replay_descriptor)
                await self._insert_checkpoint(conn, checkpoint)
                await self._insert_object_reference(conn, reference)
                await self._insert_object_reference(conn, history_reference)
                await self._insert_object_reference(conn, replay_reference)
                cursor = await conn.execute(
                    """
                    UPDATE prototype_drafts
                    SET latest_checkpoint_id = ?, updated_at = ?
                    WHERE id = ? AND head_sequence_no = ? AND head_document_hash = ?
                    """,
                    (
                        checkpoint.id,
                        checkpoint.created_at.isoformat(),
                        draft.id,
                        checkpoint.checkpoint_sequence_no,
                        checkpoint.document_hash,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StructuredPrototypeStoreError(
                        "checkpoint_head_conflict",
                        "prototype draft head changed before checkpoint commit",
                    )
                await self._apply_operation_transition(
                    conn,
                    completed_operation,
                    completion_step,
                    completion_event,
                )
                result = await self._require_draft(conn, draft.id)
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return result

    async def next_revision_no(self, document_id: str) -> int:
        await self.initialize()
        conn = await self._get_conn()
        async with conn.execute(
            "SELECT COALESCE(MAX(revision_no), 0) + 1 FROM prototype_revisions WHERE document_id = ?",
            (document_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise StructuredPrototypeStoreError(
                "revision_sequence_corrupt",
                "prototype revision sequence could not be read",
            )
        return _required_positive_int(row[0], "revision.next_no")

    async def load_revision(self, revision_id: str) -> PrototypeRevisionRecord | None:
        await self.initialize()
        conn = await self._get_conn()
        row = await self._load_revision_row(conn, revision_id)
        return self._revision_from_row(row) if row is not None else None

    async def load_revision_by_no(
        self,
        document_id: str,
        revision_no: int,
    ) -> PrototypeRevisionRecord | None:
        await self.initialize()
        conn = await self._get_conn()
        row = await self._load_revision_by_no_row(conn, document_id, revision_no)
        return self._revision_from_row(row) if row is not None else None

    async def load_render_run(self, render_run_id: str) -> PrototypeRenderRunRecord | None:
        await self.initialize()
        conn = await self._get_conn()
        row = await self._load_render_run_row(conn, render_run_id)
        return self._render_run_from_row(row) if row is not None else None

    async def load_render_run_by_operation(
        self,
        operation_id: str,
    ) -> PrototypeRenderRunRecord | None:
        await self.initialize()
        conn = await self._get_conn()
        async with conn.execute(
            """
            SELECT
                id, document_id, kind, revision_id, ai_edit_run_id, status,
                renderer_version, renderer_environment_version, runtime_core_version,
                runtime_core_source_hash, runtime_core_bundle_hash,
                state_machine_kernel_version, render_runtime_image_hash, browser_version,
                font_pack_hash, viewport_profile_hash, sandbox_policy_version,
                input_manifest_hash, document_object_hash, document_hash, operation_id,
                attempt, artifact_id, output_manifest_hash, error_code, error_message,
                started_at, completed_at, created_at, updated_at
            FROM prototype_render_runs
            WHERE operation_id = ?
            """,
            (operation_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return self._render_run_from_row(row) if row is not None else None

    async def load_render_artifact(
        self,
        artifact_id: str,
    ) -> PrototypeRenderArtifactRecord | None:
        await self.initialize()
        conn = await self._get_conn()
        row = await self._load_render_artifact_row(conn, artifact_id)
        return self._render_artifact_from_row(row) if row is not None else None

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
    ) -> PrototypePublicationFreezeResult:
        if (
            revision.document_id != render_run.document_id
            or revision.id != render_run.revision_id
            or revision.checkpoint_id != revision_checkpoint.id
            or revision_checkpoint.revision_id != revision.id
            or revision_checkpoint.draft_id is not None
            or revision.document_object_hash != document_descriptor.content_hash
            or revision.document_hash != expected_document_hash
            or revision_checkpoint.document_object_hash != expected_document_hash
            or render_run.document_object_hash != expected_document_hash
            or input_descriptor.content_hash != render_run.input_manifest_hash
        ):
            raise StructuredPrototypeStoreError(
                "publication_identity_mismatch",
                "prototype publication freeze identities are inconsistent",
            )
        if (
            revision_reference.owner_kind != "checkpoint"
            or revision_reference.owner_id != revision_checkpoint.id
            or revision_reference.content_hash != document_descriptor.content_hash
            or input_reference.owner_kind != "render_run"
            or input_reference.owner_id != render_run.id
            or input_reference.content_hash != input_descriptor.content_hash
        ):
            raise StructuredPrototypeStoreError(
                "publication_reference_mismatch",
                "prototype publication object references are inconsistent",
            )
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                draft = await self._require_draft(conn, expected_draft_id)
                document = await self._require_document(conn, revision.document_id)
                if (
                    document.active_draft_id != draft.id
                    or draft.status != "active"
                    or draft.head_sequence_no != expected_head_sequence_no
                    or draft.head_document_hash != expected_document_hash
                    or draft.latest_checkpoint_id is None
                ):
                    raise StructuredPrototypeStoreError(
                        "draft_conflict",
                        "prototype draft head changed before publication freeze",
                    )
                draft_checkpoint = await self._require_checkpoint(
                    conn,
                    draft.latest_checkpoint_id,
                )
                if (
                    draft_checkpoint.checkpoint_sequence_no != expected_head_sequence_no
                    or draft_checkpoint.document_hash != expected_document_hash
                    or draft_checkpoint.document_object_hash != document_descriptor.content_hash
                ):
                    raise StructuredPrototypeStoreError(
                        "publication_checkpoint_mismatch",
                        "prototype publication checkpoint does not match the draft head",
                    )
                async with conn.execute(
                    "SELECT COALESCE(MAX(revision_no), 0) + 1 FROM prototype_revisions WHERE document_id = ?",
                    (revision.document_id,),
                ) as cursor:
                    next_row = await cursor.fetchone()
                if next_row is None or revision.revision_no != _required_positive_int(
                    next_row[0], "revision.next_no"
                ):
                    raise StructuredPrototypeStoreError(
                        "revision_sequence_conflict",
                        "prototype revision number is no longer available",
                    )
                await self._register_object_tx(conn, document_descriptor)
                await self._register_object_tx(conn, input_descriptor)
                await self._insert_checkpoint(conn, revision_checkpoint)
                await self._insert_object_reference(conn, revision_reference)
                await self._insert_revision(conn, revision)
                await self._insert_object_reference(conn, input_reference)
                await self._insert_render_run(conn, render_run)
                cursor = await conn.execute(
                    """
                    UPDATE prototype_drafts
                    SET status = 'publishing', publish_revision_no = ?, updated_at = ?
                    WHERE id = ?
                      AND status = 'active'
                      AND head_sequence_no = ?
                      AND head_document_hash = ?
                    """,
                    (
                        revision.revision_no,
                        render_run.created_at.isoformat(),
                        draft.id,
                        expected_head_sequence_no,
                        expected_document_hash,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StructuredPrototypeStoreError(
                        "draft_conflict",
                        "prototype draft changed before publication freeze commit",
                    )
                await self._apply_operation_transition(
                    conn,
                    running_operation,
                    completed_step,
                    completion_event,
                )
                updated_draft = await self._require_draft(conn, draft.id)
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return PrototypePublicationFreezeResult(
            revision=revision,
            revision_checkpoint=revision_checkpoint,
            draft=updated_draft,
            render_run=render_run,
        )

    async def mark_publication_rendering(
        self,
        *,
        render_run_id: str,
        started_at: datetime,
        running_operation: PrototypeOperation,
        running_step: PrototypeOperationStep,
        started_event: PrototypeOperationEvent,
    ) -> PrototypeRenderRunRecord:
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                run = await self._require_render_run(conn, render_run_id)
                if run.kind != "publication" or run.status != "queued":
                    raise StructuredPrototypeStoreError(
                        "render_run_conflict",
                        "prototype publication render run is not queued",
                    )
                cursor = await conn.execute(
                    """
                    UPDATE prototype_render_runs
                    SET status = 'rendering', started_at = ?, updated_at = ?
                    WHERE id = ? AND status = 'queued'
                    """,
                    (started_at.isoformat(), started_at.isoformat(), render_run_id),
                )
                if cursor.rowcount != 1:
                    raise StructuredPrototypeStoreError(
                        "render_run_conflict",
                        "prototype publication render run changed before start",
                    )
                await self._apply_operation_transition(
                    conn,
                    running_operation,
                    running_step,
                    started_event,
                )
                updated = await self._require_render_run(conn, render_run_id)
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return updated

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
    ) -> None:
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                run = await self._require_render_run(conn, render_run_id)
                draft = await self._require_draft(conn, draft_id)
                if run.status not in {"queued", "rendering"}:
                    raise StructuredPrototypeStoreError(
                        "render_run_conflict",
                        "prototype publication render run is already terminal",
                    )
                if draft.status != "publishing" or draft.publish_revision_no is None:
                    raise StructuredPrototypeStoreError(
                        "publication_state_conflict",
                        "prototype publishing draft is no longer recoverable",
                    )
                await conn.execute(
                    """
                    UPDATE prototype_render_runs
                    SET status = 'failed', error_code = ?, error_message = ?,
                        completed_at = ?, updated_at = ?
                    WHERE id = ? AND status IN ('queued', 'rendering')
                    """,
                    (
                        error_code,
                        error_message[:1000],
                        failed_at.isoformat(),
                        failed_at.isoformat(),
                        run.id,
                    ),
                )
                await conn.execute(
                    """
                    UPDATE prototype_drafts
                    SET status = 'active', publish_revision_no = NULL, updated_at = ?
                    WHERE id = ? AND status = 'publishing'
                    """,
                    (failed_at.isoformat(), draft.id),
                )
                await self._apply_operation_transition(
                    conn,
                    failed_operation,
                    failed_step,
                    failed_event,
                )
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()

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
    ) -> PrototypePublicationCompletionResult:
        self._validate_history_checkpoint_artifact(
            descriptor=active_history_descriptor,
            reference=active_history_reference,
            history_checkpoint=active_history_checkpoint,
            checkpoint=active_checkpoint,
        )
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                run = await self._require_render_run(conn, artifact.render_run_id)
                revision = await self._require_revision(conn, artifact.revision_id or "")
                publishing_draft = await self._require_draft(conn, publishing_draft_id)
                document = await self._require_document(conn, artifact.document_id)
                if (
                    run.status != "rendering"
                    or run.kind != "publication"
                    or run.revision_id != revision.id
                    or publishing_draft.status != "publishing"
                    or publishing_draft.publish_revision_no != revision.revision_no
                    or document.active_draft_id != publishing_draft.id
                    or artifact.document_hash != revision.document_hash
                    or artifact.output_manifest_hash != output_descriptor.content_hash
                    or artifact.visual_preflight_report_hash != preflight_descriptor.content_hash
                    or active_draft.document_id != document.id
                    or active_draft.base_revision_no != revision.revision_no
                    or active_draft.status != "active"
                    or active_draft.head_document_hash != revision.document_hash
                    or active_checkpoint.draft_id != active_draft.id
                    or active_checkpoint.document_hash != revision.document_hash
                ):
                    raise StructuredPrototypeStoreError(
                        "publication_completion_mismatch",
                        "prototype publication completion identities are inconsistent",
                    )
                for descriptor in (
                    output_descriptor,
                    preflight_descriptor,
                    replay_descriptor,
                ):
                    await self._register_object_tx(conn, descriptor)
                for reference in (
                    output_reference,
                    preflight_reference,
                    replay_reference,
                ):
                    await self._insert_object_reference(conn, reference)
                await self._insert_render_artifact(conn, artifact)
                cursor = await conn.execute(
                    """
                    UPDATE prototype_render_runs
                    SET status = 'ready', artifact_id = ?, output_manifest_hash = ?,
                        completed_at = ?, updated_at = ?
                    WHERE id = ? AND status = 'rendering' AND revision_id = ?
                    """,
                    (
                        artifact.id,
                        artifact.output_manifest_hash,
                        artifact.created_at.isoformat(),
                        artifact.created_at.isoformat(),
                        run.id,
                        revision.id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StructuredPrototypeStoreError(
                        "render_run_conflict",
                        "prototype render run changed before publication completion",
                    )
                cursor = await conn.execute(
                    """
                    UPDATE prototype_drafts
                    SET status = 'closed', closed_at = ?, updated_at = ?
                    WHERE id = ? AND status = 'publishing' AND publish_revision_no = ?
                    """,
                    (
                        artifact.created_at.isoformat(),
                        artifact.created_at.isoformat(),
                        publishing_draft.id,
                        revision.revision_no,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StructuredPrototypeStoreError(
                        "publication_state_conflict",
                        "prototype publishing draft changed before completion",
                    )
                await conn.execute(
                    """
                    INSERT INTO prototype_drafts (
                        id, document_id, base_revision_no, status, head_sequence_no,
                        head_document_hash, latest_checkpoint_id, publish_revision_no,
                        created_at, updated_at, closed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
                    """,
                    self._initial_draft_params(active_draft),
                )
                await self._insert_checkpoint(conn, active_checkpoint)
                await self._insert_object_reference(conn, active_checkpoint_reference)
                await self._register_object_tx(conn, active_history_descriptor)
                await self._insert_object_reference(conn, active_history_reference)
                await conn.execute(
                    "UPDATE prototype_drafts SET latest_checkpoint_id = ? WHERE id = ?",
                    (active_checkpoint.id, active_draft.id),
                )
                cursor = await conn.execute(
                    """
                    UPDATE prototype_documents
                    SET published_revision_no = ?, active_draft_id = ?, updated_at = ?
                    WHERE id = ? AND active_draft_id = ?
                    """,
                    (
                        revision.revision_no,
                        active_draft.id,
                        artifact.created_at.isoformat(),
                        document.id,
                        publishing_draft.id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StructuredPrototypeStoreError(
                        "publication_state_conflict",
                        "prototype public pointer changed before completion",
                    )
                await self._apply_operation_transition(
                    conn,
                    completed_operation,
                    completed_step,
                    completion_event,
                )
                updated_document = await self._require_document(conn, document.id)
                closed_draft = await self._require_draft(conn, publishing_draft.id)
                opened_draft = await self._require_draft(conn, active_draft.id)
                opened_checkpoint = await self._require_checkpoint(conn, active_checkpoint.id)
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return PrototypePublicationCompletionResult(
            document=updated_document,
            revision=revision,
            artifact=artifact,
            closed_draft=closed_draft,
            active_draft=opened_draft,
            active_checkpoint=opened_checkpoint,
        )

    async def load_published_record(self, document_id: str) -> PrototypePublishedRecord | None:
        await self.initialize()
        conn = await self._get_conn()
        document = await self.load_document(document_id)
        if document is None or document.published_revision_no is None:
            return None
        revision = await self.load_revision_by_no(document_id, document.published_revision_no)
        if revision is None:
            raise StructuredPrototypeStoreError(
                "published_revision_corrupt",
                "prototype public pointer references a missing revision",
            )
        run_row = await self._load_ready_publication_run_row(conn, revision.id)
        if run_row is None:
            raise StructuredPrototypeStoreError(
                "published_render_corrupt",
                "prototype public revision has no ready render run",
            )
        run = self._render_run_from_row(run_row)
        if run.artifact_id is None:
            raise StructuredPrototypeStoreError(
                "published_render_corrupt",
                "prototype ready render run has no artifact",
            )
        artifact = await self.load_render_artifact(run.artifact_id)
        if artifact is None:
            raise StructuredPrototypeStoreError(
                "published_artifact_corrupt",
                "prototype public render artifact is missing",
            )
        return PrototypePublishedRecord(
            document=document,
            revision=revision,
            render_run=run,
            artifact=artifact,
        )

    async def list_published_revisions(
        self,
        document_id: str,
    ) -> tuple[PrototypeRevisionHistoryEntry, ...]:
        await self.initialize()
        conn = await self._get_conn()
        async with conn.execute(
            """
            SELECT
                r.id, r.document_id, r.revision_no, r.schema_version, r.checkpoint_id,
                r.document_object_hash, r.document_hash, r.summary, r.source, r.created_at,
                run.id, run.document_id, run.kind, run.revision_id, run.ai_edit_run_id,
                run.status, run.renderer_version, run.renderer_environment_version,
                run.runtime_core_version, run.runtime_core_source_hash,
                run.runtime_core_bundle_hash, run.state_machine_kernel_version,
                run.render_runtime_image_hash, run.browser_version, run.font_pack_hash,
                run.viewport_profile_hash, run.sandbox_policy_version,
                run.input_manifest_hash, run.document_object_hash, run.document_hash,
                run.operation_id, run.attempt, run.artifact_id, run.output_manifest_hash,
                run.error_code, run.error_message, run.started_at, run.completed_at,
                run.created_at, run.updated_at,
                a.id, a.render_run_id, a.document_id, a.revision_id, a.renderer_version,
                a.document_hash, a.output_hash, a.output_manifest_hash, a.storage_key,
                a.entrypoint, a.visual_preflight_report_hash, a.created_at
            FROM prototype_revisions AS r
            JOIN prototype_render_runs AS run
                ON run.revision_id = r.id
                AND run.kind = 'publication'
                AND run.status = 'ready'
            JOIN prototype_render_artifacts AS a
                ON a.id = run.artifact_id
            WHERE r.document_id = ?
            ORDER BY r.revision_no DESC, run.attempt DESC
            """,
            (document_id,),
        ) as cursor:
            rows = list(await cursor.fetchall())
        entries: list[PrototypeRevisionHistoryEntry] = []
        seen_revision_ids: set[str] = set()
        for row in rows:
            values = tuple(row)
            revision = self._revision_from_row(values[:10])
            if revision.id in seen_revision_ids:
                continue
            seen_revision_ids.add(revision.id)
            entries.append(
                PrototypeRevisionHistoryEntry(
                    revision=revision,
                    render_run=self._render_run_from_row(values[10:40]),
                    artifact=self._render_artifact_from_row(values[40:52]),
                )
            )
        return tuple(entries)

    async def list_publication_rollbacks(
        self,
        document_id: str,
    ) -> tuple[PrototypeRollbackEventRecord, ...]:
        await self.initialize()
        conn = await self._get_conn()
        async with conn.execute(
            """
            SELECT step.completion_evidence_ref, operation.completed_at, operation.id
            FROM prototype_operations AS operation
            JOIN prototype_operation_steps AS step
                ON step.operation_id = operation.id
                AND step.status = 'succeeded'
                AND step.completion_evidence_kind = 'publication_rolled_back'
            WHERE operation.operation_kind = 'rollback_publication'
              AND operation.resource_kind = 'publication'
              AND operation.resource_id = ?
              AND operation.status = 'succeeded'
            ORDER BY operation.completed_at DESC, operation.id DESC
            """,
            (document_id,),
        ) as cursor:
            rows = list(await cursor.fetchall())
        events: list[PrototypeRollbackEventRecord] = []
        for row in rows:
            evidence_ref = _required_str(row[0], "rollback.evidence_ref")
            prefix, _, revision_part = evidence_ref.rpartition(":")
            if prefix != document_id or not revision_part.isdigit():
                raise StructuredPrototypeStoreError(
                    "rollback_evidence_corrupt",
                    "prototype rollback evidence reference is malformed",
                )
            events.append(
                PrototypeRollbackEventRecord(
                    operation_id=_required_str(row[2], "rollback.operation_id"),
                    target_revision_no=_required_positive_int(
                        int(revision_part),
                        "rollback.target_revision_no",
                    ),
                    occurred_at=_datetime(row[1], "rollback.completed_at"),
                )
            )
        return tuple(events)

    async def load_ready_revision_publication(
        self,
        document_id: str,
        revision_no: int,
    ) -> PrototypePublishedRecord | None:
        await self.initialize()
        conn = await self._get_conn()
        document = await self.load_document(document_id)
        revision = await self.load_revision_by_no(document_id, revision_no)
        if document is None or revision is None:
            return None
        run_row = await self._load_ready_publication_run_row(conn, revision.id)
        if run_row is None:
            return None
        run = self._render_run_from_row(run_row)
        if run.artifact_id is None:
            return None
        artifact = await self.load_render_artifact(run.artifact_id)
        if artifact is None:
            return None
        return PrototypePublishedRecord(
            document=document,
            revision=revision,
            render_run=run,
            artifact=artifact,
        )

    async def rollback_publication(
        self,
        *,
        document_id: str,
        target_revision_no: int,
        expected_current_revision_no: int,
        rolled_back_at: datetime,
        completed_operation: PrototypeOperation,
        completed_step: PrototypeOperationStep,
        completion_event: PrototypeOperationEvent,
        replay_descriptor: PrototypeObjectDescriptor,
        replay_reference: PrototypeObjectReference,
    ) -> PrototypePublishedRecord:
        self._validate_operation_transition_payload(
            completed_operation,
            completed_step,
            completion_event,
        )
        if (
            completed_operation.operation_kind != "rollback_publication"
            or completed_operation.resource_kind != "publication"
            or completed_operation.resource_id != document_id
            or completed_operation.status != "succeeded"
            or completed_step.completion_evidence_kind != "publication_rolled_back"
            or completed_step.completion_evidence_ref != f"{document_id}:{target_revision_no}"
        ):
            raise StructuredPrototypeStoreError(
                "rollback_identity_mismatch",
                "prototype publication rollback operation identity is inconsistent",
            )
        self._validate_replay_manifest_registration(
            descriptor=replay_descriptor,
            reference=replay_reference,
            operation=completed_operation,
            step=completed_step,
            event=completion_event,
        )
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                operation_row = await self._load_operation_row(conn, completed_operation.id)
                if operation_row is None:
                    raise StructuredPrototypeStoreError(
                        "operation_missing",
                        "prototype publication rollback operation does not exist",
                    )
                current_operation = self._operation_from_row(operation_row)
                if (
                    current_operation.operation_kind != "rollback_publication"
                    or current_operation.status != "running"
                ):
                    raise StructuredPrototypeStoreError(
                        "rollback_conflict",
                        "prototype publication rollback operation is not running",
                    )
                document = await self._require_document(conn, document_id)
                if document.published_revision_no != expected_current_revision_no:
                    raise StructuredPrototypeStoreError(
                        "publication_state_conflict",
                        "prototype publication pointer changed before rollback",
                    )
                revision_row = await self._load_revision_by_no_row(
                    conn,
                    document_id,
                    target_revision_no,
                )
                if revision_row is None:
                    raise StructuredPrototypeStoreError(
                        "revision_missing",
                        "prototype rollback target revision does not exist",
                    )
                revision = self._revision_from_row(revision_row)
                run_row = await self._load_ready_publication_run_row(conn, revision.id)
                if run_row is None:
                    raise StructuredPrototypeStoreError(
                        "revision_missing",
                        "prototype rollback target revision has no ready publication",
                    )
                run = self._render_run_from_row(run_row)
                if run.artifact_id is None:
                    raise StructuredPrototypeStoreError(
                        "published_render_corrupt",
                        "prototype ready render run has no artifact",
                    )
                artifact_row = await self._load_render_artifact_row(conn, run.artifact_id)
                if artifact_row is None:
                    raise StructuredPrototypeStoreError(
                        "published_artifact_corrupt",
                        "prototype rollback target render artifact is missing",
                    )
                artifact = self._render_artifact_from_row(artifact_row)
                cursor = await conn.execute(
                    """
                    UPDATE prototype_documents
                    SET published_revision_no = ?, updated_at = ?
                    WHERE id = ? AND published_revision_no = ?
                    """,
                    (
                        target_revision_no,
                        rolled_back_at.isoformat(),
                        document_id,
                        expected_current_revision_no,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StructuredPrototypeStoreError(
                        "publication_state_conflict",
                        "prototype publication pointer changed before rollback",
                    )
                await self._register_object_tx(conn, replay_descriptor)
                await self._insert_object_reference(conn, replay_reference)
                await self._apply_operation_transition(
                    conn,
                    completed_operation,
                    completed_step,
                    completion_event,
                )
                updated_document = await self._require_document(conn, document_id)
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return PrototypePublishedRecord(
            document=updated_document,
            revision=revision,
            render_run=run,
            artifact=artifact,
        )

    async def load_ready_publication(
        self,
        document_id: str,
        revision_no: int,
        artifact_id: str,
    ) -> PrototypePublishedRecord | None:
        await self.initialize()
        conn = await self._get_conn()
        document = await self.load_document(document_id)
        revision = await self.load_revision_by_no(document_id, revision_no)
        artifact = await self.load_render_artifact(artifact_id)
        if document is None or revision is None or artifact is None:
            return None
        if artifact.document_id != document_id or artifact.revision_id != revision.id:
            return None
        async with conn.execute(
            """
            SELECT
                id, document_id, kind, revision_id, ai_edit_run_id, status,
                renderer_version, renderer_environment_version, runtime_core_version,
                runtime_core_source_hash, runtime_core_bundle_hash,
                state_machine_kernel_version, render_runtime_image_hash, browser_version,
                font_pack_hash, viewport_profile_hash, sandbox_policy_version,
                input_manifest_hash, document_object_hash, document_hash, operation_id,
                attempt, artifact_id, output_manifest_hash, error_code, error_message,
                started_at, completed_at, created_at, updated_at
            FROM prototype_render_runs
            WHERE id = ? AND revision_id = ? AND artifact_id = ? AND status = 'ready'
            """,
            (artifact.render_run_id, revision.id, artifact.id),
        ) as cursor:
            run_row = await cursor.fetchone()
        if run_row is None:
            return None
        return PrototypePublishedRecord(
            document=document,
            revision=revision,
            render_run=self._render_run_from_row(run_row),
            artifact=artifact,
        )

    async def recover_interrupted_publications(self, recovered_at: datetime) -> int:
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                async with conn.execute(
                    """
                    SELECT
                        id, document_id, kind, revision_id, ai_edit_run_id, status,
                        renderer_version, renderer_environment_version, runtime_core_version,
                        runtime_core_source_hash, runtime_core_bundle_hash,
                        state_machine_kernel_version, render_runtime_image_hash, browser_version,
                        font_pack_hash, viewport_profile_hash, sandbox_policy_version,
                        input_manifest_hash, document_object_hash, document_hash, operation_id,
                        attempt, artifact_id, output_manifest_hash, error_code, error_message,
                        started_at, completed_at, created_at, updated_at
                    FROM prototype_render_runs
                    WHERE kind = 'publication' AND status IN ('queued', 'rendering')
                    ORDER BY created_at, id
                    """
                ) as cursor:
                    rows = list(await cursor.fetchall())
                for row in rows:
                    run = self._render_run_from_row(row)
                    if run.revision_id is None:
                        raise StructuredPrototypeStoreError(
                            "publication_state_corrupt",
                            "prototype publication render run has no revision",
                        )
                    revision = await self._require_revision(conn, run.revision_id)
                    await conn.execute(
                        """
                        UPDATE prototype_render_runs
                        SET status = 'interrupted', error_code = 'service_restart',
                            error_message = 'render interrupted by service restart',
                            completed_at = ?, updated_at = ?
                        WHERE id = ? AND status IN ('queued', 'rendering')
                        """,
                        (recovered_at.isoformat(), recovered_at.isoformat(), run.id),
                    )
                    await conn.execute(
                        """
                        UPDATE prototype_drafts
                        SET status = 'active', publish_revision_no = NULL, updated_at = ?
                        WHERE document_id = ? AND status = 'publishing' AND publish_revision_no = ?
                        """,
                        (
                            recovered_at.isoformat(),
                            run.document_id,
                            revision.revision_no,
                        ),
                    )
                    operation_row = await self._load_operation_row(conn, run.operation_id)
                    if operation_row is None:
                        raise StructuredPrototypeStoreError(
                            "operation_missing",
                            "prototype interrupted publication operation is missing",
                        )
                    operation = self._operation_from_row(operation_row)
                    if operation.status not in {"queued", "running"}:
                        continue
                    failure_hash = (
                        "sha256:"
                        + hashlib.sha256(
                            f"{operation.id}:service_restart:{run.id}".encode()
                        ).hexdigest()
                    )
                    async with conn.execute(
                        """
                        SELECT
                            id, operation_id, parent_step_id, step_kind, step_ordinal,
                            attempt, status, phase, input_manifest_hash, config_manifest_hash,
                            output_manifest_hash, completion_evidence_kind,
                            completion_evidence_ref, error_code, started_at, completed_at
                        FROM prototype_operation_steps
                        WHERE operation_id = ?
                        ORDER BY step_ordinal DESC, attempt DESC
                        LIMIT 1
                        """,
                        (operation.id,),
                    ) as cursor:
                        step_row = await cursor.fetchone()
                    next_event_no = await self._next_operation_event_no(conn, operation.id)
                    if step_row is not None and step_row[6] == "running":
                        step_id = _required_str(step_row[0], "step.id")
                        await conn.execute(
                            """
                            UPDATE prototype_operation_steps
                            SET status = 'interrupted', phase = 'service_restart_recovery',
                                output_manifest_hash = ?,
                                completion_evidence_kind = 'failure_manifest_hash',
                                completion_evidence_ref = ?, error_code = 'service_restart',
                                completed_at = ?
                            WHERE id = ? AND status = 'running'
                            """,
                            (
                                failure_hash,
                                failure_hash,
                                recovered_at.isoformat(),
                                step_id,
                            ),
                        )
                    else:
                        step_ordinal = (
                            _required_non_negative_int(step_row[4], "step.step_ordinal") + 1
                            if step_row is not None
                            else 0
                        )
                        step_id = f"{operation.id}:restart:{step_ordinal}"
                        await conn.execute(
                            """
                            INSERT INTO prototype_operation_steps (
                                id, operation_id, parent_step_id, step_kind, step_ordinal,
                                attempt, status, phase, input_manifest_hash,
                                config_manifest_hash, output_manifest_hash,
                                completion_evidence_kind, completion_evidence_ref,
                                error_code, started_at, completed_at
                            ) VALUES (?, ?, NULL, 'service_restart_recovery', ?, 1,
                                'interrupted', 'service_restart_recovery', ?, ?, ?,
                                'failure_manifest_hash', ?, 'service_restart', ?, ?)
                            """,
                            (
                                step_id,
                                operation.id,
                                step_ordinal,
                                operation.request_manifest_hash,
                                operation.config_manifest_hash,
                                failure_hash,
                                failure_hash,
                                recovered_at.isoformat(),
                                recovered_at.isoformat(),
                            ),
                        )
                    await conn.execute(
                        """
                        UPDATE prototype_operations
                        SET status = 'interrupted', phase = 'service_restart_recovery',
                            failure_evidence_hash = ?, error_code = 'service_restart',
                            completed_at = ?
                        WHERE id = ? AND status IN ('queued', 'running')
                        """,
                        (failure_hash, recovered_at.isoformat(), operation.id),
                    )
                    await conn.execute(
                        """
                        INSERT INTO prototype_operation_events (
                            operation_id, event_no, step_id, event_kind, status, phase,
                            input_hash, output_hash, evidence_hash, error_code, occurred_at
                        ) VALUES (?, ?, ?, 'publication_interrupted', 'interrupted',
                            'service_restart_recovery', ?, NULL, ?, 'service_restart', ?)
                        """,
                        (
                            operation.id,
                            next_event_no,
                            step_id,
                            operation.request_manifest_hash,
                            failure_hash,
                            recovered_at.isoformat(),
                        ),
                    )
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return len(rows)

    async def mark_draft_corrupt(
        self,
        *,
        draft_id: str,
        expected_head_sequence_no: int,
        expected_document_hash: str,
        failed_operation: PrototypeOperation,
        failed_step: PrototypeOperationStep,
        failure_event: PrototypeOperationEvent,
    ) -> PrototypeDraftRecord:
        self._validate_operation_transition_payload(
            failed_operation,
            failed_step,
            failure_event,
        )
        if (
            failed_operation.operation_kind
            not in {"recover_draft", "apply_command_batch", "undo", "redo"}
            or failed_operation.resource_kind != "draft"
            or failed_operation.resource_id != draft_id
            or failed_operation.status != "failed"
            or failed_step.status != "failed"
            or failed_operation.error_code is None
            or failed_step.error_code != failed_operation.error_code
            or failure_event.error_code != failed_operation.error_code
        ):
            raise StructuredPrototypeStoreError(
                "draft_corruption_evidence_invalid",
                "prototype draft corruption evidence is invalid",
            )
        _required_hash(expected_document_hash, "draft.expected_document_hash")
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                draft = await self._require_draft(conn, draft_id)
                if (
                    draft.head_sequence_no != expected_head_sequence_no
                    or draft.head_document_hash != expected_document_hash
                ):
                    raise StructuredPrototypeStoreError(
                        "draft_conflict",
                        "prototype draft head changed before corruption was recorded",
                    )
                if draft.status not in {"active", "publishing"}:
                    raise StructuredPrototypeStoreError(
                        "draft_not_active",
                        "prototype draft cannot be marked corrupt in its current state",
                    )
                cursor = await conn.execute(
                    """
                    UPDATE prototype_drafts
                    SET status = 'corrupt', updated_at = ?
                    WHERE id = ?
                      AND status IN ('active', 'publishing')
                      AND head_sequence_no = ?
                      AND head_document_hash = ?
                    """,
                    (
                        failed_operation.completed_at.isoformat()
                        if failed_operation.completed_at is not None
                        else failure_event.occurred_at.isoformat(),
                        draft_id,
                        expected_head_sequence_no,
                        expected_document_hash,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StructuredPrototypeStoreError(
                        "draft_conflict",
                        "prototype draft changed before corruption was recorded",
                    )
                await self._apply_operation_transition(
                    conn,
                    failed_operation,
                    failed_step,
                    failure_event,
                )
                result = await self._require_draft(conn, draft_id)
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return result

    async def load_draft_recovery_bundle(
        self,
        draft_id: str,
    ) -> PrototypeDraftRecoveryBundle:
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN")
            try:
                draft = await self._require_draft(conn, draft_id)
                if draft.latest_checkpoint_id is None:
                    raise StructuredPrototypeStoreError(
                        "draft_corrupt",
                        "prototype draft has no latest checkpoint",
                    )
                document = await self._require_document(conn, draft.document_id)
                checkpoint = await self._require_checkpoint(conn, draft.latest_checkpoint_id)
                if (
                    checkpoint.history_snapshot_object_hash is None
                    or checkpoint.history_snapshot_schema_version is None
                    or checkpoint.journal_prefix_hash is None
                ):
                    raise StructuredPrototypeStoreError(
                        "command_history_checkpoint_missing",
                        "prototype draft checkpoint has no command history seal",
                    )
                descriptor_row = await self._load_object_row(
                    conn,
                    document.project_id,
                    checkpoint.document_object_hash,
                )
                if descriptor_row is None:
                    raise StructuredPrototypeStoreError(
                        "object_missing",
                        "prototype checkpoint object descriptor is missing",
                    )
                descriptor = self._descriptor_from_row(descriptor_row)
                history_descriptor_row = await self._load_object_row(
                    conn,
                    document.project_id,
                    checkpoint.history_snapshot_object_hash,
                )
                if history_descriptor_row is None:
                    raise StructuredPrototypeStoreError(
                        "object_missing",
                        "prototype command history checkpoint object descriptor is missing",
                    )
                history_descriptor = self._descriptor_from_row(history_descriptor_row)
                async with conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM prototype_object_references
                    WHERE project_id = ? AND owner_kind = 'checkpoint' AND owner_id = ?
                      AND role = 'command-history-checkpoint' AND content_hash = ?
                      AND payload_type = 'prototype_command_history_checkpoint'
                      AND schema_version = ?
                    """,
                    (
                        document.project_id,
                        checkpoint.id,
                        checkpoint.history_snapshot_object_hash,
                        checkpoint.history_snapshot_schema_version,
                    ),
                ) as cursor:
                    reference_row = await cursor.fetchone()
                if reference_row is None or int(reference_row[0]) != 1:
                    raise StructuredPrototypeStoreError(
                        "command_history_checkpoint_missing",
                        "prototype command history checkpoint reference is missing",
                    )
                batches = await self._list_command_batches_after(
                    conn,
                    draft.id,
                    checkpoint.checkpoint_sequence_no,
                )
                self._validate_recovery_chain(draft, checkpoint, batches)
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return PrototypeDraftRecoveryBundle(
            document=document,
            draft=draft,
            checkpoint=checkpoint,
            object_descriptor=descriptor,
            history_object_descriptor=history_descriptor,
            command_batches=tuple(batches),
        )

    async def load_runtime_session(
        self,
        session_id: str,
    ) -> PrototypeRuntimeSessionRecord | None:
        await self.initialize()
        conn = await self._get_conn()
        row = await self._load_runtime_session_row(conn, session_id)
        return self._runtime_session_from_row(row) if row is not None else None

    async def load_runtime_event_batch_by_request(
        self,
        session_id: str,
        client_event_id: str,
    ) -> PrototypeRuntimeEventBatchRecord | None:
        await self.initialize()
        conn = await self._get_conn()
        row = await self._load_runtime_event_batch_by_request_row(
            conn,
            session_id,
            client_event_id,
        )
        return self._runtime_event_batch_from_row(row) if row is not None else None

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
    ) -> None:
        self._validate_runtime_initial_checkpoint(
            descriptor=descriptor,
            reference=reference,
            session=session,
            checkpoint=checkpoint,
            operation=completed_operation,
            step=completion_step,
            event=completion_event,
        )
        self._validate_replay_manifest_registration(
            descriptor=replay_descriptor,
            reference=replay_reference,
            operation=completed_operation,
            step=completion_step,
            event=completion_event,
        )
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                document = await self._require_document(conn, session.document_id)
                if document.project_id != session.project_id:
                    raise StructuredPrototypeStoreError(
                        "runtime_session_identity_mismatch",
                        "prototype runtime session document belongs to another project",
                    )
                pinned_document = await self._load_object_row(
                    conn,
                    session.project_id,
                    session.pinned_document_object_hash,
                )
                if pinned_document is None:
                    raise StructuredPrototypeStoreError(
                        "object_missing",
                        "prototype runtime pinned document object is not registered",
                    )
                await self._register_object_tx(conn, descriptor)
                await self._register_object_tx(conn, replay_descriptor)
                await self._insert_runtime_session(conn, session, latest_checkpoint_id=None)
                await self._insert_runtime_checkpoint(conn, checkpoint)
                await self._insert_object_reference(conn, reference)
                await self._insert_object_reference(conn, replay_reference)
                cursor = await conn.execute(
                    "UPDATE prototype_runtime_sessions SET latest_checkpoint_id = ? WHERE id = ?",
                    (checkpoint.id, session.id),
                )
                if cursor.rowcount != 1:
                    raise StructuredPrototypeStoreError(
                        "runtime_session_conflict",
                        "prototype runtime session disappeared before checkpoint commit",
                    )
                await self._apply_operation_transition(
                    conn,
                    completed_operation,
                    completion_step,
                    completion_event,
                )
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()

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
    ) -> PrototypeRuntimeSessionRecord:
        self._validate_runtime_reset(
            state_descriptor=state_descriptor,
            state_reference=state_reference,
            reset_manifest_descriptor=reset_manifest_descriptor,
            old_reset_reference=old_reset_reference,
            new_reset_reference=new_reset_reference,
            session=session,
            checkpoint=checkpoint,
            operation=completed_operation,
            step=completion_step,
            event=completion_event,
        )
        self._validate_replay_manifest_registration(
            descriptor=replay_descriptor,
            reference=replay_reference,
            operation=completed_operation,
            step=completion_step,
            event=completion_event,
        )
        _required_hash(expected_old_state_hash, "runtime_reset.expected_old_state_hash")
        _required_hash(
            expected_old_view_model_hash,
            "runtime_reset.expected_old_view_model_hash",
        )
        _required_hash(
            expected_old_runtime_core_bundle_hash,
            "runtime_reset.expected_old_runtime_core_bundle_hash",
        )
        _required_hash(
            expected_target_document_hash,
            "runtime_reset.expected_target_document_hash",
        )
        old_session_id = session.replaces_session_id
        if old_session_id is None:
            raise StructuredPrototypeStoreError(
                "runtime_reset_identity_mismatch",
                "prototype runtime reset session has no replaced-session identity",
            )
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                old_session = await self._require_runtime_session(conn, old_session_id)
                if (
                    old_session.recording_kind != "studio_preview"
                    or old_session.source_kind != "draft"
                ):
                    raise StructuredPrototypeStoreError(
                        "runtime_session_reset_not_allowed",
                        "only draft-backed Studio preview sessions can be reset",
                    )
                if (
                    old_session.status != expected_old_status
                    or old_session.latest_checkpoint_id != expected_old_latest_checkpoint_id
                    or old_session.head_sequence_no != expected_old_head_sequence_no
                    or old_session.head_state_hash != expected_old_state_hash
                    or old_session.head_view_model_hash != expected_old_view_model_hash
                    or old_session.runtime_core_bundle_hash != expected_old_runtime_core_bundle_hash
                ):
                    raise StructuredPrototypeStoreError(
                        "runtime_session_conflict",
                        "prototype runtime reset source changed before commit",
                    )
                target_draft = await self._require_draft(conn, target_draft_id)
                if (
                    target_draft.status != "active"
                    or target_draft.head_sequence_no != expected_target_head_sequence_no
                    or target_draft.head_document_hash != expected_target_document_hash
                ):
                    raise StructuredPrototypeStoreError(
                        "draft_conflict",
                        "prototype runtime reset target changed before commit",
                    )
                target_document = await self._require_document(conn, target_draft.document_id)
                if (
                    target_document.project_id != old_session.project_id
                    or target_document.id != old_session.document_id
                    or session.project_id != old_session.project_id
                    or session.document_id != old_session.document_id
                    or session.source_id != target_draft.id
                    or session.pinned_document_object_hash != expected_target_document_hash
                ):
                    raise StructuredPrototypeStoreError(
                        "runtime_session_reset_target_mismatch",
                        "prototype runtime reset target belongs to another document",
                    )
                await self._register_object_tx(conn, state_descriptor)
                await self._register_object_tx(conn, reset_manifest_descriptor)
                await self._register_object_tx(conn, replay_descriptor)
                try:
                    await self._insert_runtime_session(
                        conn,
                        session,
                        latest_checkpoint_id=None,
                    )
                except aiosqlite.IntegrityError as exc:
                    raise StructuredPrototypeStoreError(
                        "runtime_session_conflict",
                        "prototype runtime session was already reset",
                    ) from exc
                await self._insert_runtime_checkpoint(conn, checkpoint)
                for reference in (
                    state_reference,
                    old_reset_reference,
                    new_reset_reference,
                    replay_reference,
                ):
                    await self._insert_object_reference(conn, reference)
                cursor = await conn.execute(
                    "UPDATE prototype_runtime_sessions SET latest_checkpoint_id = ? WHERE id = ?",
                    (checkpoint.id, session.id),
                )
                if cursor.rowcount != 1:
                    raise StructuredPrototypeStoreError(
                        "runtime_session_conflict",
                        "prototype runtime reset checkpoint could not be attached",
                    )
                if old_session.status == "active":
                    completed_at = completed_operation.completed_at
                    if completed_at is None:
                        raise StructuredPrototypeStoreError(
                            "runtime_reset_evidence_invalid",
                            "prototype runtime reset operation has no completion time",
                        )
                    cursor = await conn.execute(
                        """
                        UPDATE prototype_runtime_sessions
                        SET status = 'completed', updated_at = ?, completed_at = ?
                        WHERE id = ?
                          AND status = 'active'
                          AND head_sequence_no = ?
                          AND head_state_hash = ?
                          AND head_view_model_hash = ?
                          AND runtime_core_bundle_hash = ?
                          AND latest_checkpoint_id IS ?
                        """,
                        (
                            completed_at.isoformat(),
                            completed_at.isoformat(),
                            old_session.id,
                            expected_old_head_sequence_no,
                            expected_old_state_hash,
                            expected_old_view_model_hash,
                            expected_old_runtime_core_bundle_hash,
                            expected_old_latest_checkpoint_id,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise StructuredPrototypeStoreError(
                            "runtime_session_conflict",
                            "prototype runtime reset source changed before close",
                        )
                await self._apply_operation_transition(
                    conn,
                    completed_operation,
                    completion_step,
                    completion_event,
                )
                result = await self._require_runtime_session(conn, session.id)
                await conn.commit()
            except asyncio.CancelledError:
                await conn.rollback()
                raise
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
        return result

    async def append_runtime_event_batch(
        self,
        *,
        event_batch: PrototypeRuntimeEventBatchRecord,
        replay_descriptor: PrototypeObjectDescriptor,
        replay_reference: PrototypeObjectReference,
        completed_operation: PrototypeOperation,
        completion_step: PrototypeOperationStep,
        completion_event: PrototypeOperationEvent,
    ) -> PrototypeRuntimeEventAppendResult:
        self._validate_runtime_event_append(
            event_batch,
            completed_operation,
            completion_step,
            completion_event,
        )
        self._validate_replay_manifest_registration(
            descriptor=replay_descriptor,
            reference=replay_reference,
            operation=completed_operation,
            step=completion_step,
            event=completion_event,
        )
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                existing_row = await self._load_runtime_event_batch_by_request_row(
                    conn,
                    event_batch.session_id,
                    event_batch.client_event_id,
                )
                if existing_row is not None:
                    existing = self._runtime_event_batch_from_row(existing_row)
                    self._assert_idempotent_runtime_event_batch(existing, event_batch)
                    session = await self._require_runtime_session(conn, event_batch.session_id)
                    result = PrototypeRuntimeEventAppendResult(
                        event_batch=existing,
                        session=session,
                        created=False,
                    )
                else:
                    session = await self._require_runtime_session(conn, event_batch.session_id)
                    if completed_operation.project_id != session.project_id:
                        raise StructuredPrototypeStoreError(
                            "runtime_session_identity_mismatch",
                            "prototype runtime event operation belongs to another project",
                        )
                    await self._assert_runtime_session_accepts_event(conn, session, event_batch)
                    await self._insert_runtime_event_batch(conn, event_batch)
                    await self._register_object_tx(conn, replay_descriptor)
                    await self._insert_object_reference(conn, replay_reference)
                    cursor = await conn.execute(
                        """
                        UPDATE prototype_runtime_sessions
                        SET head_sequence_no = ?,
                            head_state_hash = ?,
                            head_view_model_hash = ?,
                            updated_at = ?
                        WHERE id = ?
                          AND status = 'active'
                          AND head_sequence_no = ?
                          AND head_state_hash = ?
                        """,
                        (
                            event_batch.result_sequence_no,
                            event_batch.result_state_hash,
                            event_batch.result_view_model_hash,
                            event_batch.created_at.isoformat(),
                            event_batch.session_id,
                            event_batch.base_sequence_no,
                            event_batch.base_state_hash,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise StructuredPrototypeStoreError(
                            "runtime_session_conflict",
                            "prototype runtime session head changed before event commit",
                        )
                    await self._apply_operation_transition(
                        conn,
                        completed_operation,
                        completion_step,
                        completion_event,
                    )
                    updated = await self._require_runtime_session(conn, event_batch.session_id)
                    result = PrototypeRuntimeEventAppendResult(
                        event_batch=event_batch,
                        session=updated,
                        created=True,
                    )
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return result

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
    ) -> PrototypeRuntimeSessionRecord:
        self._validate_runtime_checkpoint_registration(
            descriptor,
            reference,
            checkpoint,
            completed_operation,
            completion_step,
            completion_event,
        )
        self._validate_replay_manifest_registration(
            descriptor=replay_descriptor,
            reference=replay_reference,
            operation=completed_operation,
            step=completion_step,
            event=completion_event,
        )
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                session = await self._require_runtime_session(conn, checkpoint.session_id)
                if completed_operation.project_id != session.project_id:
                    raise StructuredPrototypeStoreError(
                        "runtime_session_identity_mismatch",
                        "prototype runtime checkpoint operation belongs to another project",
                    )
                if session.status != "active":
                    raise StructuredPrototypeStoreError(
                        "runtime_session_not_active",
                        "prototype runtime session does not accept checkpoints",
                    )
                if (
                    session.head_sequence_no != checkpoint.checkpoint_sequence_no
                    or session.head_state_hash != checkpoint.state_hash
                    or session.head_view_model_hash != checkpoint.view_model_hash
                ):
                    raise StructuredPrototypeStoreError(
                        "runtime_checkpoint_head_conflict",
                        "prototype runtime checkpoint does not match the session head",
                    )
                await self._register_object_tx(conn, descriptor)
                await self._register_object_tx(conn, replay_descriptor)
                await self._insert_runtime_checkpoint(conn, checkpoint)
                await self._insert_object_reference(conn, reference)
                await self._insert_object_reference(conn, replay_reference)
                cursor = await conn.execute(
                    """
                    UPDATE prototype_runtime_sessions
                    SET latest_checkpoint_id = ?, updated_at = ?
                    WHERE id = ?
                      AND head_sequence_no = ?
                      AND head_state_hash = ?
                      AND head_view_model_hash = ?
                    """,
                    (
                        checkpoint.id,
                        checkpoint.created_at.isoformat(),
                        session.id,
                        checkpoint.checkpoint_sequence_no,
                        checkpoint.state_hash,
                        checkpoint.view_model_hash,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StructuredPrototypeStoreError(
                        "runtime_checkpoint_head_conflict",
                        "prototype runtime session changed before checkpoint commit",
                    )
                await self._apply_operation_transition(
                    conn,
                    completed_operation,
                    completion_step,
                    completion_event,
                )
                result = await self._require_runtime_session(conn, session.id)
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return result

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
    ) -> PrototypeRuntimeSessionRecord:
        self._validate_operation_transition_payload(
            failed_operation,
            failed_step,
            failure_event,
        )
        if (
            failed_operation.operation_kind != "replay_runtime_session"
            or failed_operation.resource_kind != "runtime_session"
            or failed_operation.resource_id != session_id
            or failed_operation.status != "failed"
            or failed_step.status != "failed"
            or failed_operation.error_code is None
            or failed_step.error_code != failed_operation.error_code
            or failure_event.error_code != failed_operation.error_code
        ):
            raise StructuredPrototypeStoreError(
                "runtime_corruption_evidence_invalid",
                "prototype runtime corruption evidence is invalid",
            )
        _required_hash(expected_state_hash, "runtime_session.expected_state_hash")
        _required_hash(
            expected_view_model_hash,
            "runtime_session.expected_view_model_hash",
        )
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                session = await self._require_runtime_session(conn, session_id)
                if failed_operation.project_id != session.project_id:
                    raise StructuredPrototypeStoreError(
                        "runtime_session_identity_mismatch",
                        "prototype runtime recovery operation belongs to another project",
                    )
                if (
                    session.head_sequence_no != expected_head_sequence_no
                    or session.head_state_hash != expected_state_hash
                    or session.head_view_model_hash != expected_view_model_hash
                ):
                    raise StructuredPrototypeStoreError(
                        "runtime_session_conflict",
                        "prototype runtime head changed before corruption was recorded",
                    )
                if session.status not in {"active", "interrupted"}:
                    raise StructuredPrototypeStoreError(
                        "runtime_session_not_active",
                        "prototype runtime session cannot be marked corrupt in its current state",
                    )
                occurred_at = (
                    failed_operation.completed_at
                    if failed_operation.completed_at is not None
                    else failure_event.occurred_at
                )
                cursor = await conn.execute(
                    """
                    UPDATE prototype_runtime_sessions
                    SET status = 'corrupt', updated_at = ?, completed_at = ?
                    WHERE id = ?
                      AND status IN ('active', 'interrupted')
                      AND head_sequence_no = ?
                      AND head_state_hash = ?
                      AND head_view_model_hash = ?
                    """,
                    (
                        occurred_at.isoformat(),
                        occurred_at.isoformat(),
                        session_id,
                        expected_head_sequence_no,
                        expected_state_hash,
                        expected_view_model_hash,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StructuredPrototypeStoreError(
                        "runtime_session_conflict",
                        "prototype runtime session changed before corruption was recorded",
                    )
                await self._apply_operation_transition(
                    conn,
                    failed_operation,
                    failed_step,
                    failure_event,
                )
                result = await self._require_runtime_session(conn, session_id)
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return result

    async def load_runtime_recovery_bundle(
        self,
        session_id: str,
    ) -> PrototypeRuntimeRecoveryBundle:
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN")
            try:
                session = await self._require_runtime_session(conn, session_id)
                if session.latest_checkpoint_id is None:
                    raise StructuredPrototypeStoreError(
                        "runtime_session_corrupt",
                        "prototype runtime session has no checkpoint",
                    )
                checkpoint = await self._require_runtime_checkpoint(
                    conn,
                    session.latest_checkpoint_id,
                )
                descriptor_row = await self._load_object_row(
                    conn,
                    session.project_id,
                    checkpoint.state_object_hash,
                )
                if descriptor_row is None:
                    raise StructuredPrototypeStoreError(
                        "object_missing",
                        "prototype runtime checkpoint object descriptor is missing",
                    )
                descriptor = self._descriptor_from_row(descriptor_row)
                event_batches = await self._list_runtime_event_batches_after(
                    conn,
                    session.id,
                    checkpoint.checkpoint_sequence_no,
                )
                self._validate_runtime_recovery_chain(session, checkpoint, event_batches)
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()
        return PrototypeRuntimeRecoveryBundle(
            session=session,
            checkpoint=checkpoint,
            object_descriptor=descriptor,
            event_batches=tuple(event_batches),
        )

    async def register_object_reference(
        self,
        descriptor: PrototypeObjectDescriptor,
        reference: PrototypeObjectReference,
    ) -> None:
        self._validate_registration(descriptor, reference)
        await self.initialize()
        conn = await self._get_conn()
        async with self._transaction_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                existing = await self._load_object_row(
                    conn, descriptor.project_id, descriptor.content_hash
                )
                if existing is None:
                    await conn.execute(
                        """
                        INSERT INTO prototype_objects (
                            project_id,
                            content_hash,
                            media_type,
                            storage_codec,
                            storage_codec_version,
                            canonical_byte_size,
                            stored_byte_size,
                            storage_hash,
                            storage_key,
                            created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        self._descriptor_params(descriptor),
                    )
                else:
                    self._assert_descriptor_matches(existing, descriptor)
                await conn.execute(
                    """
                    INSERT OR IGNORE INTO prototype_object_references (
                        project_id,
                        owner_kind,
                        owner_id,
                        role,
                        content_hash,
                        payload_type,
                        schema_version,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        reference.project_id,
                        reference.owner_kind,
                        reference.owner_id,
                        reference.role,
                        reference.content_hash,
                        reference.payload_type,
                        reference.schema_version,
                        reference.created_at.isoformat(),
                    ),
                )
            except (aiosqlite.Error, StructuredPrototypeStoreError):
                await conn.rollback()
                raise
            await conn.commit()

    async def load_object(
        self,
        project_id: str,
        content_hash: str,
    ) -> PrototypeObjectDescriptor | None:
        await self.initialize()
        conn = await self._get_conn()
        row = await self._load_object_row(conn, project_id, content_hash)
        return self._descriptor_from_row(row) if row is not None else None

    async def list_object_references(
        self,
        project_id: str,
        owner_kind: str,
        owner_id: str,
    ) -> list[PrototypeObjectReference]:
        await self.initialize()
        conn = await self._get_conn()
        async with conn.execute(
            """
            SELECT
                project_id,
                owner_kind,
                owner_id,
                role,
                content_hash,
                payload_type,
                schema_version,
                created_at
            FROM prototype_object_references
            WHERE project_id = ? AND owner_kind = ? AND owner_id = ?
            ORDER BY role, content_hash, payload_type, schema_version
            """,
            (project_id, owner_kind, owner_id),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            PrototypeObjectReference(
                project_id=_required_str(row[0], "reference.project_id"),
                owner_kind=_owner_kind(row[1]),
                owner_id=_required_str(row[2], "reference.owner_id"),
                role=_required_str(row[3], "reference.role"),
                content_hash=_required_str(row[4], "reference.content_hash"),
                payload_type=_payload_type(row[5]),
                schema_version=_required_positive_int(row[6], "reference.schema_version"),
                created_at=_datetime(row[7], "reference.created_at"),
            )
            for row in rows
        ]

    @staticmethod
    def _validate_new_operation(
        operation: PrototypeOperation,
        event: PrototypeOperationEvent,
    ) -> None:
        if operation.status != "queued" or operation.attempt <= 0:
            raise StructuredPrototypeStoreError(
                "operation_invalid",
                "new prototype operation must start queued with a positive attempt",
            )
        if (
            operation.result_manifest_hash is not None
            or operation.failure_evidence_hash is not None
            or operation.error_code is not None
            or operation.started_at is not None
            or operation.completed_at is not None
        ):
            raise StructuredPrototypeStoreError(
                "operation_invalid",
                "new prototype operation contains terminal fields",
            )
        _required_hash(operation.request_manifest_hash, "operation.request_manifest_hash")
        _required_hash(operation.config_manifest_hash, "operation.config_manifest_hash")
        if (
            event.operation_id != operation.id
            or event.event_no != 0
            or event.step_id is not None
            or event.status != "queued"
            or event.phase != operation.phase
        ):
            raise StructuredPrototypeStoreError(
                "operation_event_invalid",
                "new prototype operation requires matching event zero",
            )

    @staticmethod
    def _validate_operation_transition_payload(
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        event: PrototypeOperationEvent,
    ) -> None:
        if step.operation_id != operation.id or event.operation_id != operation.id:
            raise StructuredPrototypeStoreError(
                "operation_event_invalid",
                "prototype operation, step, and event identities do not match",
            )
        if event.step_id != step.id or event.status != step.status:
            raise StructuredPrototypeStoreError(
                "operation_event_invalid",
                "prototype operation event does not describe its step state",
            )
        if event.phase != step.phase or operation.phase != step.phase:
            raise StructuredPrototypeStoreError(
                "operation_event_invalid",
                "prototype operation phase does not match its step event",
            )
        if step.step_ordinal < 0 or step.attempt <= 0 or event.event_no <= 0:
            raise StructuredPrototypeStoreError(
                "operation_event_invalid",
                "prototype operation ordinals and attempts are invalid",
            )
        _required_hash(operation.request_manifest_hash, "operation.request_manifest_hash")
        _required_hash(operation.config_manifest_hash, "operation.config_manifest_hash")
        _required_hash(step.input_manifest_hash, "step.input_manifest_hash")
        _required_hash(step.config_manifest_hash, "step.config_manifest_hash")
        if step.output_manifest_hash is not None:
            _required_hash(step.output_manifest_hash, "step.output_manifest_hash")
        for value, field in (
            (event.input_hash, "event.input_hash"),
            (event.output_hash, "event.output_hash"),
            (event.evidence_hash, "event.evidence_hash"),
        ):
            if value is not None:
                _required_hash(value, field)
        if operation.status == "succeeded":
            if operation.result_manifest_hash is None or operation.completed_at is None:
                raise StructuredPrototypeStoreError(
                    "operation_invalid",
                    "successful prototype operation requires result evidence and completion time",
                )
            _required_hash(operation.result_manifest_hash, "operation.result_manifest_hash")
        if operation.status == "failed":
            if (
                operation.failure_evidence_hash is None
                or operation.error_code is None
                or operation.completed_at is None
            ):
                raise StructuredPrototypeStoreError(
                    "operation_invalid",
                    "failed prototype operation requires failure evidence and error code",
                )
            _required_hash(
                operation.failure_evidence_hash,
                "operation.failure_evidence_hash",
            )
        if step.status == "succeeded" and (
            step.output_manifest_hash is None
            or step.completion_evidence_kind is None
            or step.completion_evidence_ref is None
            or step.completed_at is None
        ):
            raise StructuredPrototypeStoreError(
                "operation_step_invalid",
                "successful prototype step requires output and completion evidence",
            )
        if step.status == "failed" and (step.error_code is None or step.completed_at is None):
            raise StructuredPrototypeStoreError(
                "operation_step_invalid",
                "failed prototype step requires error code and completion time",
            )

    @classmethod
    def _validate_replay_manifest_registration(
        cls,
        *,
        descriptor: PrototypeObjectDescriptor,
        reference: PrototypeObjectReference,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        event: PrototypeOperationEvent,
    ) -> None:
        cls._validate_registration(descriptor, reference)
        cls._validate_operation_transition_payload(operation, step, event)
        if (
            operation.status != "succeeded"
            or operation.result_manifest_hash != descriptor.content_hash
            or step.status != "succeeded"
            or step.output_manifest_hash != descriptor.content_hash
            or event.output_hash != descriptor.content_hash
            or event.evidence_hash != descriptor.content_hash
            or reference.owner_kind != "replay_manifest"
            or reference.owner_id != operation.id
            or reference.role != "operation-replay-manifest"
            or reference.payload_type != "replay_manifest"
            or reference.schema_version != 1
        ):
            raise StructuredPrototypeStoreError(
                "replay_manifest_registration_invalid",
                "prototype replay manifest completion identity is inconsistent",
            )

    @classmethod
    def _validate_generation_failure_evidence_registration(
        cls,
        *,
        descriptor: PrototypeObjectDescriptor,
        reference: PrototypeObjectReference,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        event: PrototypeOperationEvent,
    ) -> None:
        cls._validate_registration(descriptor, reference)
        cls._validate_operation_transition_payload(operation, step, event)
        if (
            operation.status != "failed"
            or operation.failure_evidence_hash != descriptor.content_hash
            or step.status != "failed"
            or step.output_manifest_hash != descriptor.content_hash
            or step.completion_evidence_kind != "generation_evidence_manifest"
            or step.completion_evidence_ref != descriptor.content_hash
            or event.output_hash != descriptor.content_hash
            or event.evidence_hash != descriptor.content_hash
            or reference.owner_kind != "replay_manifest"
            or reference.owner_id != operation.id
            or reference.role != "operation-failure-evidence"
            or reference.payload_type != "generation_evidence_manifest"
            or reference.schema_version != 1
        ):
            raise StructuredPrototypeStoreError(
                "generation_failure_evidence_invalid",
                "generation failure evidence does not seal its owning operation",
            )

    @classmethod
    def _validate_history_checkpoint_artifact(
        cls,
        *,
        descriptor: PrototypeObjectDescriptor,
        reference: PrototypeObjectReference,
        history_checkpoint: PrototypeCommandHistoryCheckpoint,
        checkpoint: PrototypeCheckpointRecord,
    ) -> None:
        cls._validate_registration(descriptor, reference)
        canonical_hash = (
            "sha256:"
            + hashlib.sha256(canonical_json_bytes(history_checkpoint.to_payload())).hexdigest()
        )
        if (
            checkpoint.draft_id is None
            or checkpoint.history_snapshot_object_hash is None
            or checkpoint.history_snapshot_schema_version is None
            or checkpoint.journal_prefix_hash is None
            or descriptor.content_hash != canonical_hash
            or descriptor.content_hash != history_checkpoint.snapshot_object_hash
            or descriptor.content_hash != checkpoint.history_snapshot_object_hash
            or history_checkpoint.snapshot_schema_version
            != checkpoint.history_snapshot_schema_version
            or history_checkpoint.draft_id != checkpoint.draft_id
            or history_checkpoint.checkpoint_sequence_no != checkpoint.checkpoint_sequence_no
            or history_checkpoint.checkpoint_document_hash != checkpoint.document_hash
            or history_checkpoint.journal_prefix_hash != checkpoint.journal_prefix_hash
            or reference.owner_kind != "checkpoint"
            or reference.owner_id != checkpoint.id
            or reference.role != "command-history-checkpoint"
            or reference.content_hash != descriptor.content_hash
            or reference.payload_type != "prototype_command_history_checkpoint"
            or reference.schema_version != history_checkpoint.snapshot_schema_version
        ):
            raise StructuredPrototypeStoreError(
                "command_history_checkpoint_identity_mismatch",
                "prototype command history checkpoint artifact identity is inconsistent",
            )

    @classmethod
    def _validate_initial_checkpoint(
        cls,
        *,
        descriptor: PrototypeObjectDescriptor,
        reference: PrototypeObjectReference,
        history_descriptor: PrototypeObjectDescriptor,
        history_reference: PrototypeObjectReference,
        history_checkpoint: PrototypeCommandHistoryCheckpoint,
        document: PrototypeDocumentRecord,
        draft: PrototypeDraftRecord,
        checkpoint: PrototypeCheckpointRecord,
        completed_operation: PrototypeOperation,
        completion_step: PrototypeOperationStep,
        completion_event: PrototypeOperationEvent,
    ) -> None:
        cls._validate_registration(descriptor, reference)
        cls._validate_history_checkpoint_artifact(
            descriptor=history_descriptor,
            reference=history_reference,
            history_checkpoint=history_checkpoint,
            checkpoint=checkpoint,
        )
        cls._validate_operation_transition_payload(
            completed_operation,
            completion_step,
            completion_event,
        )
        if (
            document.project_id != descriptor.project_id
            or document.active_draft_id != draft.id
            or draft.document_id != document.id
            or draft.status != "active"
            or draft.head_sequence_no != 0
            or draft.head_document_hash != descriptor.content_hash
            or draft.latest_checkpoint_id != checkpoint.id
        ):
            raise StructuredPrototypeStoreError(
                "initial_checkpoint_invalid",
                "prototype document and initial draft identities do not match",
            )
        if (
            checkpoint.document_id != document.id
            or checkpoint.draft_id != draft.id
            or checkpoint.revision_id is not None
            or checkpoint.checkpoint_kind not in {"draft", "generation_accept"}
            or checkpoint.checkpoint_sequence_no != 0
            or checkpoint.document_object_hash != descriptor.content_hash
            or checkpoint.document_hash != descriptor.content_hash
            or checkpoint.created_by_operation_id != completed_operation.id
            or history_checkpoint.history.undo_stack
            or history_checkpoint.history.redo_stack
            or checkpoint.journal_prefix_hash != _initial_journal_prefix_hash(draft.id)
        ):
            raise StructuredPrototypeStoreError(
                "initial_checkpoint_invalid",
                "prototype initial checkpoint does not match its object and draft",
            )
        if (
            reference.owner_kind != "checkpoint"
            or reference.owner_id != checkpoint.id
            or reference.payload_type != "prototype_document"
            or reference.schema_version != checkpoint.document_schema_version
        ):
            raise StructuredPrototypeStoreError(
                "initial_checkpoint_invalid",
                "prototype initial checkpoint object reference is invalid",
            )
        if (
            completed_operation.operation_kind != "create_document"
            or completed_operation.project_id != document.project_id
            or completed_operation.resource_kind != "document"
            or completed_operation.resource_id != document.id
            or completed_operation.status != "succeeded"
            or completion_step.status != "succeeded"
            or completion_step.completion_evidence_ref != checkpoint.id
        ):
            raise StructuredPrototypeStoreError(
                "initial_checkpoint_invalid",
                "prototype create-document completion evidence is invalid",
            )

    @classmethod
    def _validate_command_append(
        cls,
        batch: PrototypeCommandBatchRecord,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        event: PrototypeOperationEvent,
    ) -> None:
        cls._validate_operation_transition_payload(operation, step, event)
        if batch.result_sequence_no != batch.base_sequence_no + 1:
            raise StructuredPrototypeStoreError(
                "command_batch_invalid",
                "prototype command result sequence must follow its base",
            )
        if not batch.commands_json or not batch.inverse_commands_json:
            raise StructuredPrototypeStoreError(
                "command_batch_invalid",
                "prototype command payload is empty",
            )
        if (
            batch.operation_kind == "forward"
            and len(batch.commands_json.encode("utf-8")) > PROTOTYPE_FORWARD_COMMAND_BATCH_MAX_BYTES
        ):
            raise StructuredPrototypeStoreError(
                "command_batch_invalid",
                "prototype forward command payload exceeds 256 KiB",
            )
        for value, field in (
            (batch.command_batch_hash, "batch.command_batch_hash"),
            (batch.base_document_hash, "batch.base_document_hash"),
            (batch.result_document_hash, "batch.result_document_hash"),
        ):
            _required_hash(value, field)
        expected_operation_kind = {
            "forward": "apply_command_batch",
            "undo": "undo",
            "redo": "redo",
        }[batch.operation_kind]
        if (
            batch.operation_id != operation.id
            or operation.operation_kind != expected_operation_kind
            or operation.resource_kind != "draft"
            or operation.resource_id != batch.draft_id
            or operation.status != "succeeded"
            or step.status != "succeeded"
            or step.completion_evidence_ref != batch.id
        ):
            raise StructuredPrototypeStoreError(
                "command_batch_invalid",
                "prototype command completion evidence is invalid",
            )
        if (batch.operation_kind == "forward") != (batch.target_batch_id is None):
            raise StructuredPrototypeStoreError(
                "command_batch_invalid",
                "prototype command target does not match its operation kind",
            )

    @classmethod
    def _validate_checkpoint_registration(
        cls,
        descriptor: PrototypeObjectDescriptor,
        reference: PrototypeObjectReference,
        history_descriptor: PrototypeObjectDescriptor,
        history_reference: PrototypeObjectReference,
        history_checkpoint: PrototypeCommandHistoryCheckpoint,
        checkpoint: PrototypeCheckpointRecord,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        event: PrototypeOperationEvent,
    ) -> None:
        cls._validate_registration(descriptor, reference)
        cls._validate_history_checkpoint_artifact(
            descriptor=history_descriptor,
            reference=history_reference,
            history_checkpoint=history_checkpoint,
            checkpoint=checkpoint,
        )
        cls._validate_operation_transition_payload(operation, step, event)
        if (
            checkpoint.document_object_hash != descriptor.content_hash
            or checkpoint.document_hash != descriptor.content_hash
            or checkpoint.created_by_operation_id != operation.id
            or checkpoint.revision_id is not None
            or reference.owner_kind != "checkpoint"
            or reference.owner_id != checkpoint.id
            or reference.payload_type != "prototype_document"
            or reference.schema_version != checkpoint.document_schema_version
        ):
            raise StructuredPrototypeStoreError(
                "checkpoint_identity_mismatch",
                "prototype checkpoint does not match its object reference",
            )
        if (
            operation.operation_kind != "create_checkpoint"
            or operation.resource_kind != "draft"
            or operation.resource_id != checkpoint.draft_id
            or operation.status != "succeeded"
            or step.status != "succeeded"
            or step.completion_evidence_ref != checkpoint.id
        ):
            raise StructuredPrototypeStoreError(
                "checkpoint_identity_mismatch",
                "prototype checkpoint completion evidence is invalid",
            )

    @classmethod
    def _validate_runtime_initial_checkpoint(
        cls,
        *,
        descriptor: PrototypeObjectDescriptor,
        reference: PrototypeObjectReference,
        session: PrototypeRuntimeSessionRecord,
        checkpoint: PrototypeRuntimeCheckpointRecord,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        event: PrototypeOperationEvent,
    ) -> None:
        cls._validate_registration(descriptor, reference)
        cls._validate_operation_transition_payload(operation, step, event)
        for value, field in (
            (session.pinned_document_object_hash, "runtime_session.pinned_document_object_hash"),
            (session.runtime_core_bundle_hash, "runtime_session.runtime_core_bundle_hash"),
            (session.scenario_hash, "runtime_session.scenario_hash"),
            (session.head_state_hash, "runtime_session.head_state_hash"),
            (session.head_view_model_hash, "runtime_session.head_view_model_hash"),
        ):
            _required_hash(value, field)
        for value, field in (
            (session.id, "runtime_session.id"),
            (session.project_id, "runtime_session.project_id"),
            (session.document_id, "runtime_session.document_id"),
            (session.source_id, "runtime_session.source_id"),
            (session.runtime_core_version, "runtime_session.runtime_core_version"),
            (
                session.state_machine_kernel_version,
                "runtime_session.state_machine_kernel_version",
            ),
            (session.scenario_id, "runtime_session.scenario_id"),
        ):
            _required_str(value, field)
        if (
            session.status != "active"
            or session.head_sequence_no != 0
            or session.completed_at is not None
            or session.latest_checkpoint_id != checkpoint.id
            or checkpoint.session_id != session.id
            or checkpoint.checkpoint_sequence_no != 0
            or checkpoint.state_object_hash != descriptor.content_hash
            or checkpoint.state_hash != descriptor.content_hash
            or checkpoint.state_hash != session.head_state_hash
            or checkpoint.view_model_hash != session.head_view_model_hash
            or checkpoint.created_by_operation_id != operation.id
            or checkpoint.runtime_state_schema_version <= 0
            or checkpoint.runtime_event_contract_version <= 0
        ):
            raise StructuredPrototypeStoreError(
                "runtime_initial_checkpoint_invalid",
                "prototype runtime initial checkpoint does not match its session",
            )
        if (
            reference.owner_kind != "runtime_checkpoint"
            or reference.owner_id != checkpoint.id
            or reference.payload_type != "prototype_runtime_state"
            or reference.schema_version != checkpoint.runtime_state_schema_version
        ):
            raise StructuredPrototypeStoreError(
                "runtime_initial_checkpoint_invalid",
                "prototype runtime initial checkpoint object reference is invalid",
            )
        if (
            operation.operation_kind != "create_runtime_session"
            or operation.project_id != session.project_id
            or operation.resource_kind != "runtime_session"
            or operation.resource_id != session.id
            or operation.status != "succeeded"
            or step.status != "succeeded"
            or step.completion_evidence_ref != checkpoint.id
        ):
            raise StructuredPrototypeStoreError(
                "runtime_initial_checkpoint_invalid",
                "prototype runtime create-session evidence is invalid",
            )

    @classmethod
    def _validate_runtime_reset(
        cls,
        *,
        state_descriptor: PrototypeObjectDescriptor,
        state_reference: PrototypeObjectReference,
        reset_manifest_descriptor: PrototypeObjectDescriptor,
        old_reset_reference: PrototypeObjectReference,
        new_reset_reference: PrototypeObjectReference,
        session: PrototypeRuntimeSessionRecord,
        checkpoint: PrototypeRuntimeCheckpointRecord,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        event: PrototypeOperationEvent,
    ) -> None:
        cls._validate_registration(state_descriptor, state_reference)
        cls._validate_registration(reset_manifest_descriptor, old_reset_reference)
        cls._validate_registration(reset_manifest_descriptor, new_reset_reference)
        cls._validate_operation_transition_payload(operation, step, event)
        old_session_id = session.replaces_session_id
        if old_session_id is None:
            raise StructuredPrototypeStoreError(
                "runtime_reset_identity_mismatch",
                "prototype runtime reset session has no replaced-session identity",
            )
        for value, field in (
            (session.pinned_document_object_hash, "runtime_session.pinned_document_object_hash"),
            (session.runtime_core_bundle_hash, "runtime_session.runtime_core_bundle_hash"),
            (session.scenario_hash, "runtime_session.scenario_hash"),
            (session.head_state_hash, "runtime_session.head_state_hash"),
            (session.head_view_model_hash, "runtime_session.head_view_model_hash"),
        ):
            _required_hash(value, field)
        if (
            session.status != "active"
            or session.source_kind != "draft"
            or session.recording_kind != "studio_preview"
            or session.head_sequence_no != 0
            or session.completed_at is not None
            or session.latest_checkpoint_id != checkpoint.id
            or checkpoint.session_id != session.id
            or checkpoint.checkpoint_sequence_no != 0
            or checkpoint.state_object_hash != state_descriptor.content_hash
            or checkpoint.state_hash != state_descriptor.content_hash
            or checkpoint.state_hash != session.head_state_hash
            or checkpoint.view_model_hash != session.head_view_model_hash
            or checkpoint.created_by_operation_id != operation.id
            or state_reference.owner_kind != "runtime_checkpoint"
            or state_reference.owner_id != checkpoint.id
            or state_reference.payload_type != "prototype_runtime_state"
            or state_reference.schema_version != checkpoint.runtime_state_schema_version
        ):
            raise StructuredPrototypeStoreError(
                "runtime_reset_identity_mismatch",
                "prototype runtime reset checkpoint does not match the new session",
            )
        if (
            old_reset_reference.owner_kind != "runtime_session"
            or old_reset_reference.owner_id != old_session_id
            or new_reset_reference.owner_kind != "runtime_session"
            or new_reset_reference.owner_id != session.id
            or old_reset_reference.role != "runtime-session-reset-manifest"
            or new_reset_reference.role != "runtime-session-reset-manifest"
            or old_reset_reference.payload_type != "runtime_session_reset_manifest"
            or new_reset_reference.payload_type != "runtime_session_reset_manifest"
            or old_reset_reference.schema_version != 1
            or new_reset_reference.schema_version != 1
        ):
            raise StructuredPrototypeStoreError(
                "runtime_reset_identity_mismatch",
                "prototype runtime reset manifest references are invalid",
            )
        if (
            operation.operation_kind != "reset_runtime_session"
            or operation.project_id != session.project_id
            or operation.resource_kind != "runtime_session"
            or operation.resource_id != session.id
            or operation.status != "succeeded"
            or step.status != "succeeded"
            or step.completion_evidence_kind != "runtime_session_reset_manifest"
            or step.completion_evidence_ref != reset_manifest_descriptor.content_hash
        ):
            raise StructuredPrototypeStoreError(
                "runtime_reset_evidence_invalid",
                "prototype runtime reset completion evidence is invalid",
            )

    @classmethod
    def _validate_runtime_event_append(
        cls,
        event_batch: PrototypeRuntimeEventBatchRecord,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        event: PrototypeOperationEvent,
    ) -> None:
        cls._validate_operation_transition_payload(operation, step, event)
        if event_batch.result_sequence_no != event_batch.base_sequence_no + 1:
            raise StructuredPrototypeStoreError(
                "runtime_event_batch_invalid",
                "prototype runtime event sequence must follow its base",
            )
        if (
            not event_batch.events_json
            or not event_batch.matched_rule_ids_json
            or len(event_batch.events_json.encode("utf-8"))
            + len(event_batch.matched_rule_ids_json.encode("utf-8"))
            > 131_072
        ):
            raise StructuredPrototypeStoreError(
                "runtime_event_batch_invalid",
                "prototype runtime event payload is empty or exceeds 128 KiB",
            )
        for value, field in (
            (event_batch.event_batch_hash, "runtime_event.event_batch_hash"),
            (event_batch.guard_report_hash, "runtime_event.guard_report_hash"),
            (event_batch.effect_report_hash, "runtime_event.effect_report_hash"),
            (event_batch.base_state_hash, "runtime_event.base_state_hash"),
            (event_batch.result_state_hash, "runtime_event.result_state_hash"),
            (event_batch.result_view_model_hash, "runtime_event.result_view_model_hash"),
            (event_batch.runtime_core_bundle_hash, "runtime_event.runtime_core_bundle_hash"),
        ):
            _required_hash(value, field)
        for value, field in (
            (event_batch.id, "runtime_event.id"),
            (event_batch.session_id, "runtime_event.session_id"),
            (event_batch.client_event_id, "runtime_event.client_event_id"),
            (event_batch.runtime_core_version, "runtime_event.runtime_core_version"),
            (
                event_batch.state_machine_kernel_version,
                "runtime_event.state_machine_kernel_version",
            ),
        ):
            _required_str(value, field)
        if (
            event_batch.operation_id != operation.id
            or operation.operation_kind != "apply_runtime_event"
            or operation.resource_kind != "runtime_session"
            or operation.resource_id != event_batch.session_id
            or operation.status != "succeeded"
            or step.status != "succeeded"
            or step.completion_evidence_ref != event_batch.id
        ):
            raise StructuredPrototypeStoreError(
                "runtime_event_batch_invalid",
                "prototype runtime event completion evidence is invalid",
            )

    @classmethod
    def _validate_runtime_checkpoint_registration(
        cls,
        descriptor: PrototypeObjectDescriptor,
        reference: PrototypeObjectReference,
        checkpoint: PrototypeRuntimeCheckpointRecord,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        event: PrototypeOperationEvent,
    ) -> None:
        cls._validate_registration(descriptor, reference)
        cls._validate_operation_transition_payload(operation, step, event)
        if (
            checkpoint.state_object_hash != descriptor.content_hash
            or checkpoint.state_hash != descriptor.content_hash
            or checkpoint.created_by_operation_id != operation.id
            or reference.owner_kind != "runtime_checkpoint"
            or reference.owner_id != checkpoint.id
            or reference.payload_type != "prototype_runtime_state"
            or reference.schema_version != checkpoint.runtime_state_schema_version
            or checkpoint.runtime_state_schema_version <= 0
            or checkpoint.runtime_event_contract_version <= 0
        ):
            raise StructuredPrototypeStoreError(
                "runtime_checkpoint_identity_mismatch",
                "prototype runtime checkpoint does not match its object reference",
            )
        if (
            operation.operation_kind != "create_checkpoint"
            or operation.resource_kind != "runtime_session"
            or operation.resource_id != checkpoint.session_id
            or operation.status != "succeeded"
            or step.status != "succeeded"
            or step.completion_evidence_ref != checkpoint.id
        ):
            raise StructuredPrototypeStoreError(
                "runtime_checkpoint_identity_mismatch",
                "prototype runtime checkpoint completion evidence is invalid",
            )

    async def _get_conn(self) -> aiosqlite.Connection:
        async with self._conn_lock:
            return await self._connect_locked()

    async def _connect_locked(self) -> aiosqlite.Connection:
        if self._conn is None:
            self._conn = await aiosqlite.connect(self.db_path, timeout=30.0)
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA synchronous=NORMAL")
            await self._conn.execute("PRAGMA busy_timeout=30000")
            await self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    async def _apply_operation_transition(
        self,
        conn: aiosqlite.Connection,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        event: PrototypeOperationEvent,
    ) -> None:
        existing_operation_row = await self._load_operation_row(conn, operation.id)
        if existing_operation_row is None:
            raise StructuredPrototypeStoreError(
                "operation_missing",
                "prototype operation does not exist",
            )
        existing_operation = self._operation_from_row(existing_operation_row)
        self._assert_operation_identity(existing_operation, operation)
        self._assert_operation_status_transition(existing_operation.status, operation.status)
        expected_event_no = await self._next_operation_event_no(conn, operation.id)
        if event.event_no != expected_event_no:
            raise StructuredPrototypeStoreError(
                "operation_event_sequence_conflict",
                "prototype operation event number is not the next durable event",
            )
        existing_step_row = await self._load_operation_step_row(conn, step.id)
        if existing_step_row is None:
            self._assert_new_step_status(step.status)
            await self._insert_operation_step(conn, step)
        else:
            existing_step = self._operation_step_from_row(existing_step_row)
            self._assert_step_identity(existing_step, step)
            self._assert_step_status_transition(existing_step.status, step.status)
            await self._update_operation_step(conn, step)
        await self._update_operation(conn, operation)
        await self._insert_operation_event(conn, event)

    @staticmethod
    def _assert_operation_identity(
        existing: PrototypeOperation,
        incoming: PrototypeOperation,
    ) -> None:
        existing_identity = (
            existing.id,
            existing.operation_kind,
            existing.project_id,
            existing.resource_kind,
            existing.resource_id,
            existing.client_request_id,
            existing.correlation_id,
            existing.parent_operation_id,
            existing.attempt,
            existing.request_manifest_hash,
            existing.config_manifest_hash,
            existing.created_at,
        )
        incoming_identity = (
            incoming.id,
            incoming.operation_kind,
            incoming.project_id,
            incoming.resource_kind,
            incoming.resource_id,
            incoming.client_request_id,
            incoming.correlation_id,
            incoming.parent_operation_id,
            incoming.attempt,
            incoming.request_manifest_hash,
            incoming.config_manifest_hash,
            incoming.created_at,
        )
        if existing_identity != incoming_identity:
            raise StructuredPrototypeStoreError(
                "operation_identity_conflict",
                "prototype operation immutable identity changed",
            )

    @classmethod
    def _assert_idempotent_operation(
        cls,
        existing: PrototypeOperation,
        incoming: PrototypeOperation,
    ) -> None:
        if (
            existing.operation_kind,
            existing.project_id,
            existing.resource_kind,
            existing.resource_id,
            existing.client_request_id,
            existing.parent_operation_id,
            existing.attempt,
            existing.request_manifest_hash,
            existing.config_manifest_hash,
        ) != (
            incoming.operation_kind,
            incoming.project_id,
            incoming.resource_kind,
            incoming.resource_id,
            incoming.client_request_id,
            incoming.parent_operation_id,
            incoming.attempt,
            incoming.request_manifest_hash,
            incoming.config_manifest_hash,
        ):
            raise StructuredPrototypeStoreError(
                "operation_idempotency_conflict",
                "prototype client request was retried with different inputs",
            )

    @staticmethod
    def _assert_operation_status_transition(
        existing: PrototypeOperationStatus,
        incoming: PrototypeOperationStatus,
    ) -> None:
        allowed: dict[PrototypeOperationStatus, set[PrototypeOperationStatus]] = {
            "queued": {"running", "failed", "cancelled"},
            "running": {"running", "succeeded", "failed", "interrupted", "cancelled"},
            "succeeded": set(),
            "failed": set(),
            "interrupted": set(),
            "cancelled": set(),
        }
        if incoming not in allowed[existing]:
            raise StructuredPrototypeStoreError(
                "operation_transition_invalid",
                f"prototype operation cannot transition from {existing} to {incoming}",
            )

    @staticmethod
    def _assert_new_step_status(status: PrototypeOperationStepStatus) -> None:
        if status not in {"pending", "running", "failed", "skipped"}:
            raise StructuredPrototypeStoreError(
                "operation_step_transition_invalid",
                f"prototype operation step cannot start as {status}",
            )

    @staticmethod
    def _assert_step_status_transition(
        existing: PrototypeOperationStepStatus,
        incoming: PrototypeOperationStepStatus,
    ) -> None:
        allowed: dict[PrototypeOperationStepStatus, set[PrototypeOperationStepStatus]] = {
            "pending": {"running", "failed", "skipped", "interrupted"},
            "running": {"succeeded", "failed", "interrupted"},
            "succeeded": set(),
            "failed": set(),
            "skipped": set(),
            "interrupted": set(),
        }
        if incoming not in allowed[existing]:
            raise StructuredPrototypeStoreError(
                "operation_step_transition_invalid",
                f"prototype operation step cannot transition from {existing} to {incoming}",
            )

    @staticmethod
    def _assert_step_identity(
        existing: PrototypeOperationStep,
        incoming: PrototypeOperationStep,
    ) -> None:
        if (
            existing.id,
            existing.operation_id,
            existing.parent_step_id,
            existing.step_kind,
            existing.step_ordinal,
            existing.attempt,
            existing.input_manifest_hash,
            existing.config_manifest_hash,
        ) != (
            incoming.id,
            incoming.operation_id,
            incoming.parent_step_id,
            incoming.step_kind,
            incoming.step_ordinal,
            incoming.attempt,
            incoming.input_manifest_hash,
            incoming.config_manifest_hash,
        ):
            raise StructuredPrototypeStoreError(
                "operation_step_identity_conflict",
                "prototype operation step immutable identity changed",
            )

    @staticmethod
    async def _next_operation_event_no(conn: aiosqlite.Connection, operation_id: str) -> int:
        async with conn.execute(
            """
            SELECT COUNT(*), COALESCE(MAX(event_no), -1) + 1
            FROM prototype_operation_events
            WHERE operation_id = ?
            """,
            (operation_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise StructuredPrototypeStoreError(
                "operation_event_corrupt",
                "prototype operation event sequence could not be read",
            )
        event_count = _required_non_negative_int(row[0], "operation_event.count")
        next_event_no = _required_non_negative_int(row[1], "operation_event.next_no")
        if event_count != next_event_no:
            raise StructuredPrototypeStoreError(
                "operation_event_corrupt",
                "prototype operation event history is not gap-free",
            )
        return next_event_no

    @staticmethod
    async def _insert_operation(conn: aiosqlite.Connection, operation: PrototypeOperation) -> None:
        await conn.execute(
            """
            INSERT INTO prototype_operations (
                id,
                operation_kind,
                project_id,
                resource_kind,
                resource_id,
                client_request_id,
                correlation_id,
                parent_operation_id,
                status,
                phase,
                attempt,
                request_manifest_hash,
                config_manifest_hash,
                result_manifest_hash,
                failure_evidence_hash,
                error_code,
                created_at,
                started_at,
                completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            AsyncStructuredPrototypeStore._operation_params(operation),
        )

    @staticmethod
    async def _update_operation(conn: aiosqlite.Connection, operation: PrototypeOperation) -> None:
        await conn.execute(
            """
            UPDATE prototype_operations
            SET status = ?,
                phase = ?,
                result_manifest_hash = ?,
                failure_evidence_hash = ?,
                error_code = ?,
                started_at = ?,
                completed_at = ?
            WHERE id = ?
            """,
            (
                operation.status,
                operation.phase,
                operation.result_manifest_hash,
                operation.failure_evidence_hash,
                operation.error_code,
                operation.started_at.isoformat() if operation.started_at else None,
                operation.completed_at.isoformat() if operation.completed_at else None,
                operation.id,
            ),
        )

    @staticmethod
    async def _insert_operation_step(
        conn: aiosqlite.Connection,
        step: PrototypeOperationStep,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO prototype_operation_steps (
                id,
                operation_id,
                parent_step_id,
                step_kind,
                step_ordinal,
                attempt,
                status,
                phase,
                input_manifest_hash,
                config_manifest_hash,
                output_manifest_hash,
                completion_evidence_kind,
                completion_evidence_ref,
                error_code,
                started_at,
                completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            AsyncStructuredPrototypeStore._operation_step_params(step),
        )

    @staticmethod
    async def _update_operation_step(
        conn: aiosqlite.Connection,
        step: PrototypeOperationStep,
    ) -> None:
        await conn.execute(
            """
            UPDATE prototype_operation_steps
            SET status = ?,
                phase = ?,
                output_manifest_hash = ?,
                completion_evidence_kind = ?,
                completion_evidence_ref = ?,
                error_code = ?,
                started_at = ?,
                completed_at = ?
            WHERE id = ?
            """,
            (
                step.status,
                step.phase,
                step.output_manifest_hash,
                step.completion_evidence_kind,
                step.completion_evidence_ref,
                step.error_code,
                step.started_at.isoformat() if step.started_at else None,
                step.completed_at.isoformat() if step.completed_at else None,
                step.id,
            ),
        )

    @staticmethod
    async def _insert_operation_event(
        conn: aiosqlite.Connection,
        event: PrototypeOperationEvent,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO prototype_operation_events (
                operation_id,
                event_no,
                step_id,
                event_kind,
                status,
                phase,
                input_hash,
                output_hash,
                evidence_hash,
                error_code,
                occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.operation_id,
                event.event_no,
                event.step_id,
                event.event_kind,
                event.status,
                event.phase,
                event.input_hash,
                event.output_hash,
                event.evidence_hash,
                event.error_code,
                event.occurred_at.isoformat(),
            ),
        )

    async def _register_object_tx(
        self,
        conn: aiosqlite.Connection,
        descriptor: PrototypeObjectDescriptor,
    ) -> None:
        existing = await self._load_object_row(
            conn,
            descriptor.project_id,
            descriptor.content_hash,
        )
        if existing is None:
            await conn.execute(
                """
                INSERT INTO prototype_objects (
                    project_id,
                    content_hash,
                    media_type,
                    storage_codec,
                    storage_codec_version,
                    canonical_byte_size,
                    stored_byte_size,
                    storage_hash,
                    storage_key,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._descriptor_params(descriptor),
            )
        else:
            self._assert_descriptor_matches(existing, descriptor)

    @staticmethod
    async def _insert_object_reference(
        conn: aiosqlite.Connection,
        reference: PrototypeObjectReference,
    ) -> None:
        await conn.execute(
            """
            INSERT OR IGNORE INTO prototype_object_references (
                project_id,
                owner_kind,
                owner_id,
                role,
                content_hash,
                payload_type,
                schema_version,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reference.project_id,
                reference.owner_kind,
                reference.owner_id,
                reference.role,
                reference.content_hash,
                reference.payload_type,
                reference.schema_version,
                reference.created_at.isoformat(),
            ),
        )

    @staticmethod
    async def _insert_checkpoint(
        conn: aiosqlite.Connection,
        checkpoint: PrototypeCheckpointRecord,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO prototype_checkpoints (
                id,
                document_id,
                draft_id,
                revision_id,
                checkpoint_kind,
                checkpoint_sequence_no,
                document_object_hash,
                document_schema_version,
                command_contract_version,
                document_hash,
                history_snapshot_object_hash,
                history_snapshot_schema_version,
                journal_prefix_hash,
                created_by_operation_id,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                checkpoint.id,
                checkpoint.document_id,
                checkpoint.draft_id,
                checkpoint.revision_id,
                checkpoint.checkpoint_kind,
                checkpoint.checkpoint_sequence_no,
                checkpoint.document_object_hash,
                checkpoint.document_schema_version,
                checkpoint.command_contract_version,
                checkpoint.document_hash,
                checkpoint.history_snapshot_object_hash,
                checkpoint.history_snapshot_schema_version,
                checkpoint.journal_prefix_hash,
                checkpoint.created_by_operation_id,
                checkpoint.created_at.isoformat(),
            ),
        )

    @staticmethod
    async def _insert_command_batch(
        conn: aiosqlite.Connection,
        batch: PrototypeCommandBatchRecord,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO prototype_command_batches (
                id,
                draft_id,
                base_sequence_no,
                result_sequence_no,
                client_request_id,
                origin,
                operation_kind,
                target_batch_id,
                command_contract_version,
                commands_json,
                inverse_commands_json,
                command_batch_hash,
                base_document_hash,
                result_document_hash,
                operation_id,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            AsyncStructuredPrototypeStore._command_batch_params(batch),
        )

    @staticmethod
    async def _insert_revision(
        conn: aiosqlite.Connection,
        revision: PrototypeRevisionRecord,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO prototype_revisions (
                id, document_id, revision_no, schema_version, checkpoint_id,
                document_object_hash, document_hash, summary, source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision.id,
                revision.document_id,
                revision.revision_no,
                revision.schema_version,
                revision.checkpoint_id,
                revision.document_object_hash,
                revision.document_hash,
                revision.summary,
                revision.source,
                revision.created_at.isoformat(),
            ),
        )

    @staticmethod
    async def _insert_ai_message(
        conn: aiosqlite.Connection,
        message: PrototypeAiMessageRecord,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO prototype_ai_messages (
                id, thread_id, client_message_id, role, kind, content, run_id,
                command_batch_id, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            AsyncStructuredPrototypeStore._ai_message_params(message),
        )

    @staticmethod
    async def _insert_ai_edit_run(
        conn: aiosqlite.Connection,
        run: PrototypeAiEditRunRecord,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO prototype_ai_edit_runs (
                id, thread_id, user_message_id, assistant_message_id, document_id,
                draft_id, operation_id, retry_of_run_id, status, scope_json,
                base_head_sequence_no, base_document_hash, context_object_hash,
                outcome_object_hash, submission_id, submission_request_hash,
                submission_accepted_at, replay_manifest_object_hash,
                proposed_command_batch_json,
                proposed_command_batch_hash, candidate_object_hash,
                preview_render_run_id, preview_artifact_id, summary,
                affected_entity_ids_json, task_id, execution_process_id, error_code,
                error_message, created_at, updated_at, completed_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            AsyncStructuredPrototypeStore._ai_edit_run_params(run),
        )

    @staticmethod
    async def _update_ai_edit_run(
        conn: aiosqlite.Connection,
        run: PrototypeAiEditRunRecord,
    ) -> None:
        cursor = await conn.execute(
            """
            UPDATE prototype_ai_edit_runs
            SET assistant_message_id = ?, status = ?, context_object_hash = ?,
                outcome_object_hash = ?, submission_id = ?, submission_request_hash = ?,
                submission_accepted_at = ?, replay_manifest_object_hash = ?,
                proposed_command_batch_json = ?,
                proposed_command_batch_hash = ?, candidate_object_hash = ?,
                preview_render_run_id = ?, preview_artifact_id = ?, summary = ?,
                affected_entity_ids_json = ?, task_id = ?, execution_process_id = ?,
                error_code = ?, error_message = ?, updated_at = ?, completed_at = ?
            WHERE id = ?
            """,
            (
                run.assistant_message_id,
                run.status,
                run.context_object_hash,
                run.outcome_object_hash,
                run.submission_id,
                run.submission_request_hash,
                run.submission_accepted_at.isoformat()
                if run.submission_accepted_at is not None
                else None,
                run.replay_manifest_object_hash,
                run.proposed_command_batch_json,
                run.proposed_command_batch_hash,
                run.candidate_object_hash,
                run.preview_render_run_id,
                run.preview_artifact_id,
                run.summary,
                run.affected_entity_ids_json,
                run.task_id,
                run.execution_process_id,
                run.error_code,
                run.error_message,
                run.updated_at.isoformat(),
                run.completed_at.isoformat() if run.completed_at is not None else None,
                run.id,
            ),
        )
        if cursor.rowcount != 1:
            raise StructuredPrototypeStoreError(
                "ai_run_missing",
                "prototype AI edit run disappeared during transition",
            )

    @staticmethod
    async def _insert_generation_job(
        conn: aiosqlite.Connection,
        job: PrototypeDocumentGenerationJobRecord,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO prototype_document_generation_jobs (
                id, project_id, client_request_id, status, operation_id,
                request_manifest_object_hash, request_hash, context_manifest_object_hash,
                source_policy, source_snapshot_object_hash, source_fingerprint,
                source_snapshot_ref, repository_object_format, worktree_base_commit,
                repository_project_prefix, repository_tree_object_id, working_tree_dirty,
                excluded_tracked_change_count, excluded_untracked_count,
                source_file_exclusion_policy, excluded_sensitive_file_count,
                excluded_status_hash,
                blueprint_object_hash, blueprint_version, blueprint_hash,
                candidate_object_hash, candidate_document_hash, preview_render_run_id,
                preview_artifact_id, preview_renderer_version, preview_storage_key,
                preview_output_hash, preview_output_manifest_hash,
                preview_visual_preflight_report_hash, replay_manifest_object_hash,
                document_id, error_code, error_message, created_at, updated_at, completed_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            AsyncStructuredPrototypeStore._generation_job_params(job),
        )

    @staticmethod
    async def _update_generation_job(
        conn: aiosqlite.Connection,
        job: PrototypeDocumentGenerationJobRecord,
    ) -> None:
        cursor = await conn.execute(
            """
            UPDATE prototype_document_generation_jobs
            SET status = ?, blueprint_object_hash = ?, blueprint_version = ?,
                blueprint_hash = ?, candidate_object_hash = ?, candidate_document_hash = ?,
                preview_render_run_id = ?, preview_artifact_id = ?,
                preview_renderer_version = ?, preview_storage_key = ?,
                preview_output_hash = ?, preview_output_manifest_hash = ?,
                preview_visual_preflight_report_hash = ?, replay_manifest_object_hash = ?,
                document_id = ?, error_code = ?, error_message = ?, updated_at = ?,
                completed_at = ?
            WHERE id = ?
            """,
            (
                job.status,
                job.blueprint_object_hash,
                job.blueprint_version,
                job.blueprint_hash,
                job.candidate_object_hash,
                job.candidate_document_hash,
                job.preview_render_run_id,
                job.preview_artifact_id,
                job.preview_renderer_version,
                job.preview_storage_key,
                job.preview_output_hash,
                job.preview_output_manifest_hash,
                job.preview_visual_preflight_report_hash,
                job.replay_manifest_object_hash,
                job.document_id,
                job.error_code,
                job.error_message,
                job.updated_at.isoformat(),
                job.completed_at.isoformat() if job.completed_at is not None else None,
                job.id,
            ),
        )
        if cursor.rowcount != 1:
            raise StructuredPrototypeStoreError(
                "generation_job_missing",
                "structured prototype generation job disappeared during transition",
            )

    @staticmethod
    async def _insert_generation_run(
        conn: aiosqlite.Connection,
        run: PrototypeDocumentGenerationRunRecord,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO prototype_document_generation_runs (
                id, job_id, status, blueprint_hash, total, processed, succeeded,
                failed, running, pending, error_code, error_message, created_at,
                updated_at, started_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            AsyncStructuredPrototypeStore._generation_run_params(run),
        )

    @staticmethod
    async def _update_generation_run(
        conn: aiosqlite.Connection,
        run: PrototypeDocumentGenerationRunRecord,
    ) -> None:
        cursor = await conn.execute(
            """
            UPDATE prototype_document_generation_runs
            SET status = ?, blueprint_hash = ?, total = ?, processed = ?,
                succeeded = ?, failed = ?, running = ?, pending = ?, error_code = ?,
                error_message = ?, updated_at = ?, started_at = ?, completed_at = ?
            WHERE id = ?
            """,
            (
                run.status,
                run.blueprint_hash,
                run.total,
                run.processed,
                run.succeeded,
                run.failed,
                run.running,
                run.pending,
                run.error_code,
                run.error_message,
                run.updated_at.isoformat(),
                run.started_at.isoformat() if run.started_at is not None else None,
                run.completed_at.isoformat() if run.completed_at is not None else None,
                run.id,
            ),
        )
        if cursor.rowcount != 1:
            raise StructuredPrototypeStoreError(
                "generation_run_missing",
                "structured prototype generation run disappeared during transition",
            )

    @staticmethod
    async def _insert_generation_item(
        conn: aiosqlite.Connection,
        item: PrototypeDocumentGenerationItemRecord,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO prototype_document_generation_run_items (
                id, job_id, run_id, kind, item_key, page_key, item_ordinal, status, phase,
                attempt, task_kind, operation_id, context_object_hash, submission_id,
                submission_request_hash, submission_normalized_fields_json,
                submission_accepted_at, output_object_hash,
                task_id, execution_process_id, error_code, error_message, created_at,
                updated_at, completed_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            AsyncStructuredPrototypeStore._generation_item_params(item),
        )

    @staticmethod
    async def _update_generation_item(
        conn: aiosqlite.Connection,
        item: PrototypeDocumentGenerationItemRecord,
    ) -> None:
        cursor = await conn.execute(
            """
            UPDATE prototype_document_generation_run_items
            SET status = ?, phase = ?, submission_id = ?, submission_request_hash = ?,
                submission_normalized_fields_json = ?, submission_accepted_at = ?,
                output_object_hash = ?, task_id = ?,
                execution_process_id = ?, error_code = ?, error_message = ?,
                updated_at = ?, completed_at = ?
            WHERE id = ?
            """,
            (
                item.status,
                item.phase,
                item.submission_id,
                item.submission_request_hash,
                json.dumps(
                    list(item.submission_normalized_fields),
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
                item.submission_accepted_at.isoformat()
                if item.submission_accepted_at is not None
                else None,
                item.output_object_hash,
                item.task_id,
                item.execution_process_id,
                item.error_code,
                item.error_message,
                item.updated_at.isoformat(),
                item.completed_at.isoformat() if item.completed_at is not None else None,
                item.id,
            ),
        )
        if cursor.rowcount != 1:
            raise StructuredPrototypeStoreError(
                "generation_item_missing",
                "structured prototype generation item disappeared during transition",
            )

    @staticmethod
    async def _insert_render_run(
        conn: aiosqlite.Connection,
        run: PrototypeRenderRunRecord,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO prototype_render_runs (
                id, document_id, kind, revision_id, ai_edit_run_id, status,
                renderer_version, renderer_environment_version, runtime_core_version,
                runtime_core_source_hash, runtime_core_bundle_hash,
                state_machine_kernel_version, render_runtime_image_hash, browser_version,
                font_pack_hash, viewport_profile_hash, sandbox_policy_version,
                input_manifest_hash, document_object_hash, document_hash, operation_id,
                attempt, artifact_id, output_manifest_hash, error_code, error_message,
                started_at, completed_at, created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?
            )
            """,
            (
                run.id,
                run.document_id,
                run.kind,
                run.revision_id,
                run.ai_edit_run_id,
                run.status,
                run.renderer_version,
                run.renderer_environment_version,
                run.runtime_core_version,
                run.runtime_core_source_hash,
                run.runtime_core_bundle_hash,
                run.state_machine_kernel_version,
                run.render_runtime_image_hash,
                run.browser_version,
                run.font_pack_hash,
                run.viewport_profile_hash,
                run.sandbox_policy_version,
                run.input_manifest_hash,
                run.document_object_hash,
                run.document_hash,
                run.operation_id,
                run.attempt,
                run.artifact_id,
                run.output_manifest_hash,
                run.error_code,
                run.error_message,
                run.started_at.isoformat() if run.started_at is not None else None,
                run.completed_at.isoformat() if run.completed_at is not None else None,
                run.created_at.isoformat(),
                run.updated_at.isoformat(),
            ),
        )

    @staticmethod
    async def _insert_render_artifact(
        conn: aiosqlite.Connection,
        artifact: PrototypeRenderArtifactRecord,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO prototype_render_artifacts (
                id, render_run_id, document_id, revision_id, renderer_version,
                document_hash, output_hash, output_manifest_hash, storage_key,
                entrypoint, visual_preflight_report_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.id,
                artifact.render_run_id,
                artifact.document_id,
                artifact.revision_id,
                artifact.renderer_version,
                artifact.document_hash,
                artifact.output_hash,
                artifact.output_manifest_hash,
                artifact.storage_key,
                artifact.entrypoint,
                artifact.visual_preflight_report_hash,
                artifact.created_at.isoformat(),
            ),
        )

    @staticmethod
    async def _insert_runtime_session(
        conn: aiosqlite.Connection,
        session: PrototypeRuntimeSessionRecord,
        *,
        latest_checkpoint_id: str | None,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO prototype_runtime_sessions (
                id,
                project_id,
                document_id,
                source_kind,
                source_id,
                pinned_document_object_hash,
                runtime_core_version,
                runtime_core_bundle_hash,
                state_machine_kernel_version,
                scenario_id,
                scenario_hash,
                status,
                head_sequence_no,
                head_state_hash,
                head_view_model_hash,
                latest_checkpoint_id,
                recording_kind,
                allow_simulated_role_switch,
                actor_subject_id,
                replaces_session_id,
                created_at,
                updated_at,
                completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.id,
                session.project_id,
                session.document_id,
                session.source_kind,
                session.source_id,
                session.pinned_document_object_hash,
                session.runtime_core_version,
                session.runtime_core_bundle_hash,
                session.state_machine_kernel_version,
                session.scenario_id,
                session.scenario_hash,
                session.status,
                session.head_sequence_no,
                session.head_state_hash,
                session.head_view_model_hash,
                latest_checkpoint_id,
                session.recording_kind,
                1 if session.allow_simulated_role_switch else 0,
                session.actor_subject_id,
                session.replaces_session_id,
                session.created_at.isoformat(),
                session.updated_at.isoformat(),
                session.completed_at.isoformat() if session.completed_at else None,
            ),
        )

    @staticmethod
    async def _insert_runtime_event_batch(
        conn: aiosqlite.Connection,
        event_batch: PrototypeRuntimeEventBatchRecord,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO prototype_runtime_event_batches (
                id,
                session_id,
                client_event_id,
                base_sequence_no,
                result_sequence_no,
                events_json,
                event_batch_hash,
                matched_rule_ids_json,
                guard_report_hash,
                effect_report_hash,
                outcome,
                base_state_hash,
                result_state_hash,
                result_view_model_hash,
                runtime_core_version,
                runtime_core_bundle_hash,
                state_machine_kernel_version,
                operation_id,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_batch.id,
                event_batch.session_id,
                event_batch.client_event_id,
                event_batch.base_sequence_no,
                event_batch.result_sequence_no,
                event_batch.events_json,
                event_batch.event_batch_hash,
                event_batch.matched_rule_ids_json,
                event_batch.guard_report_hash,
                event_batch.effect_report_hash,
                event_batch.outcome,
                event_batch.base_state_hash,
                event_batch.result_state_hash,
                event_batch.result_view_model_hash,
                event_batch.runtime_core_version,
                event_batch.runtime_core_bundle_hash,
                event_batch.state_machine_kernel_version,
                event_batch.operation_id,
                event_batch.created_at.isoformat(),
            ),
        )

    @staticmethod
    async def _insert_runtime_checkpoint(
        conn: aiosqlite.Connection,
        checkpoint: PrototypeRuntimeCheckpointRecord,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO prototype_runtime_checkpoints (
                id,
                session_id,
                checkpoint_sequence_no,
                state_object_hash,
                runtime_state_schema_version,
                runtime_event_contract_version,
                state_hash,
                view_model_hash,
                created_by_operation_id,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                checkpoint.id,
                checkpoint.session_id,
                checkpoint.checkpoint_sequence_no,
                checkpoint.state_object_hash,
                checkpoint.runtime_state_schema_version,
                checkpoint.runtime_event_contract_version,
                checkpoint.state_hash,
                checkpoint.view_model_hash,
                checkpoint.created_by_operation_id,
                checkpoint.created_at.isoformat(),
            ),
        )

    @staticmethod
    async def _load_object_row(
        conn: aiosqlite.Connection,
        project_id: str,
        content_hash: str,
    ) -> aiosqlite.Row | tuple[object, ...] | None:
        async with conn.execute(
            """
            SELECT
                project_id,
                content_hash,
                media_type,
                storage_codec,
                storage_codec_version,
                canonical_byte_size,
                stored_byte_size,
                storage_hash,
                storage_key,
                created_at
            FROM prototype_objects
            WHERE project_id = ? AND content_hash = ?
            """,
            (project_id, content_hash),
        ) as cursor:
            return await cursor.fetchone()

    @staticmethod
    async def _load_operation_row(
        conn: aiosqlite.Connection,
        operation_id: str,
    ) -> aiosqlite.Row | tuple[object, ...] | None:
        async with conn.execute(
            """
            SELECT
                id,
                operation_kind,
                project_id,
                resource_kind,
                resource_id,
                client_request_id,
                correlation_id,
                parent_operation_id,
                status,
                phase,
                attempt,
                request_manifest_hash,
                config_manifest_hash,
                result_manifest_hash,
                failure_evidence_hash,
                error_code,
                created_at,
                started_at,
                completed_at
            FROM prototype_operations
            WHERE id = ?
            """,
            (operation_id,),
        ) as cursor:
            return await cursor.fetchone()

    @staticmethod
    async def _load_operation_by_request_row(
        conn: aiosqlite.Connection,
        project_id: str,
        operation_kind: PrototypeOperationKind,
        client_request_id: str,
    ) -> aiosqlite.Row | tuple[object, ...] | None:
        async with conn.execute(
            """
            SELECT
                id,
                operation_kind,
                project_id,
                resource_kind,
                resource_id,
                client_request_id,
                correlation_id,
                parent_operation_id,
                status,
                phase,
                attempt,
                request_manifest_hash,
                config_manifest_hash,
                result_manifest_hash,
                failure_evidence_hash,
                error_code,
                created_at,
                started_at,
                completed_at
            FROM prototype_operations
            WHERE project_id = ? AND operation_kind = ? AND client_request_id = ?
            """,
            (project_id, operation_kind, client_request_id),
        ) as cursor:
            return await cursor.fetchone()

    @staticmethod
    async def _load_operation_step_row(
        conn: aiosqlite.Connection,
        step_id: str,
    ) -> aiosqlite.Row | tuple[object, ...] | None:
        async with conn.execute(
            """
            SELECT
                id,
                operation_id,
                parent_step_id,
                step_kind,
                step_ordinal,
                attempt,
                status,
                phase,
                input_manifest_hash,
                config_manifest_hash,
                output_manifest_hash,
                completion_evidence_kind,
                completion_evidence_ref,
                error_code,
                started_at,
                completed_at
            FROM prototype_operation_steps
            WHERE id = ?
            """,
            (step_id,),
        ) as cursor:
            return await cursor.fetchone()

    @staticmethod
    async def _load_command_batch_row(
        conn: aiosqlite.Connection,
        draft_id: str,
        batch_id: str,
    ) -> aiosqlite.Row | tuple[object, ...] | None:
        async with conn.execute(
            """
            SELECT
                id, draft_id, base_sequence_no, result_sequence_no,
                client_request_id, origin, operation_kind, target_batch_id,
                command_contract_version, commands_json, inverse_commands_json,
                command_batch_hash, base_document_hash, result_document_hash,
                operation_id, created_at
            FROM prototype_command_batches
            WHERE draft_id = ? AND id = ?
            """,
            (draft_id, batch_id),
        ) as cursor:
            return await cursor.fetchone()

    @staticmethod
    async def _load_command_batch_by_request_row(
        conn: aiosqlite.Connection,
        draft_id: str,
        client_request_id: str,
    ) -> aiosqlite.Row | tuple[object, ...] | None:
        async with conn.execute(
            """
            SELECT
                id,
                draft_id,
                base_sequence_no,
                result_sequence_no,
                client_request_id,
                origin,
                operation_kind,
                target_batch_id,
                command_contract_version,
                commands_json,
                inverse_commands_json,
                command_batch_hash,
                base_document_hash,
                result_document_hash,
                operation_id,
                created_at
            FROM prototype_command_batches
            WHERE draft_id = ? AND client_request_id = ?
            """,
            (draft_id, client_request_id),
        ) as cursor:
            return await cursor.fetchone()

    @staticmethod
    async def _load_ai_thread_row(
        conn: aiosqlite.Connection,
        thread_id: str,
    ) -> aiosqlite.Row | None:
        async with conn.execute(
            """
            SELECT id, document_id, title, status, summary_json,
                   summary_through_message_id, created_at, updated_at
            FROM prototype_ai_threads
            WHERE id = ?
            """,
            (thread_id,),
        ) as cursor:
            return await cursor.fetchone()

    @staticmethod
    async def _load_ai_message_by_request_row(
        conn: aiosqlite.Connection,
        thread_id: str,
        client_message_id: str | None,
    ) -> aiosqlite.Row | None:
        if client_message_id is None:
            return None
        async with conn.execute(
            """
            SELECT id, thread_id, client_message_id, role, kind, content,
                   run_id, command_batch_id, status, created_at, updated_at
            FROM prototype_ai_messages
            WHERE thread_id = ? AND client_message_id = ?
            """,
            (thread_id, client_message_id),
        ) as cursor:
            return await cursor.fetchone()

    @classmethod
    async def _load_ai_edit_run_row(
        cls,
        conn: aiosqlite.Connection,
        run_id: str,
    ) -> aiosqlite.Row | None:
        async with conn.execute(
            f"""
            SELECT {cls._AI_EDIT_RUN_COLUMNS}
            FROM prototype_ai_edit_runs
            WHERE id = ?
            """,
            (run_id,),
        ) as cursor:
            return await cursor.fetchone()

    @classmethod
    async def _load_generation_job_row(
        cls,
        conn: aiosqlite.Connection,
        job_id: str,
    ) -> aiosqlite.Row | tuple[object, ...] | None:
        async with conn.execute(
            f"""
            SELECT {cls._GENERATION_JOB_COLUMNS}
            FROM prototype_document_generation_jobs
            WHERE id = ?
            """,
            (job_id,),
        ) as cursor:
            return await cursor.fetchone()

    @classmethod
    async def _load_generation_job_by_request_row(
        cls,
        conn: aiosqlite.Connection,
        project_id: str,
        client_request_id: str,
    ) -> aiosqlite.Row | tuple[object, ...] | None:
        async with conn.execute(
            f"""
            SELECT {cls._GENERATION_JOB_COLUMNS}
            FROM prototype_document_generation_jobs
            WHERE project_id = ? AND client_request_id = ?
            """,
            (project_id, client_request_id),
        ) as cursor:
            return await cursor.fetchone()

    @classmethod
    async def _load_generation_run_row(
        cls,
        conn: aiosqlite.Connection,
        run_id: str,
    ) -> aiosqlite.Row | tuple[object, ...] | None:
        async with conn.execute(
            f"""
            SELECT {cls._GENERATION_RUN_COLUMNS}
            FROM prototype_document_generation_runs
            WHERE id = ?
            """,
            (run_id,),
        ) as cursor:
            return await cursor.fetchone()

    @classmethod
    async def _load_generation_item_row(
        cls,
        conn: aiosqlite.Connection,
        item_id: str,
    ) -> aiosqlite.Row | tuple[object, ...] | None:
        async with conn.execute(
            f"""
            SELECT {cls._GENERATION_ITEM_COLUMNS}
            FROM prototype_document_generation_run_items
            WHERE id = ?
            """,
            (item_id,),
        ) as cursor:
            return await cursor.fetchone()

    @classmethod
    async def _load_generation_snapshot_tx(
        cls,
        conn: aiosqlite.Connection,
        job_id: str,
    ) -> PrototypeDocumentGenerationSnapshot:
        job_row = await cls._load_generation_job_row(conn, job_id)
        if job_row is None:
            raise StructuredPrototypeStoreError(
                "generation_job_missing",
                "structured prototype generation job does not exist",
            )
        async with conn.execute(
            f"""
            SELECT {cls._GENERATION_RUN_COLUMNS}
            FROM prototype_document_generation_runs
            WHERE job_id = ?
            ORDER BY rowid DESC
            LIMIT 1
            """,
            (job_id,),
        ) as cursor:
            run_row = await cursor.fetchone()
        if run_row is None:
            return PrototypeDocumentGenerationSnapshot(
                job=cls._generation_job_from_row(job_row),
                latest_run=None,
                items=(),
            )
        run = cls._generation_run_from_row(run_row)
        async with conn.execute(
            f"""
            SELECT {cls._GENERATION_ITEM_COLUMNS}
            FROM prototype_document_generation_run_items
            WHERE run_id = ?
            ORDER BY item_ordinal
            """,
            (run.id,),
        ) as cursor:
            item_rows = await cursor.fetchall()
        return PrototypeDocumentGenerationSnapshot(
            job=cls._generation_job_from_row(job_row),
            latest_run=run,
            items=tuple(cls._generation_item_from_row(row) for row in item_rows),
        )

    @staticmethod
    async def _load_runtime_session_row(
        conn: aiosqlite.Connection,
        session_id: str,
    ) -> aiosqlite.Row | tuple[object, ...] | None:
        async with conn.execute(
            """
            SELECT
                id,
                project_id,
                document_id,
                source_kind,
                source_id,
                pinned_document_object_hash,
                runtime_core_version,
                runtime_core_bundle_hash,
                state_machine_kernel_version,
                scenario_id,
                scenario_hash,
                status,
                head_sequence_no,
                head_state_hash,
                head_view_model_hash,
                latest_checkpoint_id,
                recording_kind,
                allow_simulated_role_switch,
                actor_subject_id,
                replaces_session_id,
                created_at,
                updated_at,
                completed_at
            FROM prototype_runtime_sessions
            WHERE id = ?
            """,
            (session_id,),
        ) as cursor:
            return await cursor.fetchone()

    @staticmethod
    async def _load_runtime_event_batch_by_request_row(
        conn: aiosqlite.Connection,
        session_id: str,
        client_event_id: str,
    ) -> aiosqlite.Row | tuple[object, ...] | None:
        async with conn.execute(
            """
            SELECT
                id,
                session_id,
                client_event_id,
                base_sequence_no,
                result_sequence_no,
                events_json,
                event_batch_hash,
                matched_rule_ids_json,
                guard_report_hash,
                effect_report_hash,
                outcome,
                base_state_hash,
                result_state_hash,
                result_view_model_hash,
                runtime_core_version,
                runtime_core_bundle_hash,
                state_machine_kernel_version,
                operation_id,
                created_at
            FROM prototype_runtime_event_batches
            WHERE session_id = ? AND client_event_id = ?
            """,
            (session_id, client_event_id),
        ) as cursor:
            return await cursor.fetchone()

    @staticmethod
    async def _load_revision_row(
        conn: aiosqlite.Connection,
        revision_id: str,
    ) -> aiosqlite.Row | None:
        async with conn.execute(
            """
            SELECT
                id, document_id, revision_no, schema_version, checkpoint_id,
                document_object_hash, document_hash, summary, source, created_at
            FROM prototype_revisions
            WHERE id = ?
            """,
            (revision_id,),
        ) as cursor:
            return await cursor.fetchone()

    @staticmethod
    async def _load_revision_by_no_row(
        conn: aiosqlite.Connection,
        document_id: str,
        revision_no: int,
    ) -> aiosqlite.Row | None:
        async with conn.execute(
            """
            SELECT
                id, document_id, revision_no, schema_version, checkpoint_id,
                document_object_hash, document_hash, summary, source, created_at
            FROM prototype_revisions
            WHERE document_id = ? AND revision_no = ?
            """,
            (document_id, revision_no),
        ) as cursor:
            return await cursor.fetchone()

    @staticmethod
    async def _load_render_run_row(
        conn: aiosqlite.Connection,
        render_run_id: str,
    ) -> aiosqlite.Row | None:
        async with conn.execute(
            """
            SELECT
                id, document_id, kind, revision_id, ai_edit_run_id, status,
                renderer_version, renderer_environment_version, runtime_core_version,
                runtime_core_source_hash, runtime_core_bundle_hash,
                state_machine_kernel_version, render_runtime_image_hash, browser_version,
                font_pack_hash, viewport_profile_hash, sandbox_policy_version,
                input_manifest_hash, document_object_hash, document_hash, operation_id,
                attempt, artifact_id, output_manifest_hash, error_code, error_message,
                started_at, completed_at, created_at, updated_at
            FROM prototype_render_runs
            WHERE id = ?
            """,
            (render_run_id,),
        ) as cursor:
            return await cursor.fetchone()

    @staticmethod
    async def _load_ready_publication_run_row(
        conn: aiosqlite.Connection,
        revision_id: str,
    ) -> aiosqlite.Row | None:
        async with conn.execute(
            """
            SELECT
                id, document_id, kind, revision_id, ai_edit_run_id, status,
                renderer_version, renderer_environment_version, runtime_core_version,
                runtime_core_source_hash, runtime_core_bundle_hash,
                state_machine_kernel_version, render_runtime_image_hash, browser_version,
                font_pack_hash, viewport_profile_hash, sandbox_policy_version,
                input_manifest_hash, document_object_hash, document_hash, operation_id,
                attempt, artifact_id, output_manifest_hash, error_code, error_message,
                started_at, completed_at, created_at, updated_at
            FROM prototype_render_runs
            WHERE revision_id = ? AND status = 'ready'
            ORDER BY attempt DESC
            LIMIT 1
            """,
            (revision_id,),
        ) as cursor:
            return await cursor.fetchone()

    @staticmethod
    async def _load_render_artifact_row(
        conn: aiosqlite.Connection,
        artifact_id: str,
    ) -> aiosqlite.Row | None:
        async with conn.execute(
            """
            SELECT
                id, render_run_id, document_id, revision_id, renderer_version,
                document_hash, output_hash, output_manifest_hash, storage_key,
                entrypoint, visual_preflight_report_hash, created_at
            FROM prototype_render_artifacts
            WHERE id = ?
            """,
            (artifact_id,),
        ) as cursor:
            return await cursor.fetchone()

    @staticmethod
    async def _load_document_row(
        conn: aiosqlite.Connection,
        document_id: str,
    ) -> aiosqlite.Row | tuple[object, ...] | None:
        async with conn.execute(
            """
            SELECT
                id,
                project_id,
                title,
                published_revision_no,
                active_draft_id,
                created_at,
                updated_at
            FROM prototype_documents
            WHERE id = ?
            """,
            (document_id,),
        ) as cursor:
            return await cursor.fetchone()

    @staticmethod
    async def _load_draft_row(
        conn: aiosqlite.Connection,
        draft_id: str,
    ) -> aiosqlite.Row | tuple[object, ...] | None:
        async with conn.execute(
            """
            SELECT
                id,
                document_id,
                base_revision_no,
                status,
                head_sequence_no,
                head_document_hash,
                latest_checkpoint_id,
                publish_revision_no,
                created_at,
                updated_at,
                closed_at
            FROM prototype_drafts
            WHERE id = ?
            """,
            (draft_id,),
        ) as cursor:
            return await cursor.fetchone()

    @staticmethod
    async def _load_checkpoint_row(
        conn: aiosqlite.Connection,
        checkpoint_id: str,
    ) -> aiosqlite.Row | tuple[object, ...] | None:
        async with conn.execute(
            """
            SELECT
                id,
                document_id,
                draft_id,
                revision_id,
                checkpoint_kind,
                checkpoint_sequence_no,
                document_object_hash,
                document_schema_version,
                command_contract_version,
                document_hash,
                history_snapshot_object_hash,
                history_snapshot_schema_version,
                journal_prefix_hash,
                created_by_operation_id,
                created_at
            FROM prototype_checkpoints
            WHERE id = ?
            """,
            (checkpoint_id,),
        ) as cursor:
            return await cursor.fetchone()

    @staticmethod
    async def _load_runtime_checkpoint_row(
        conn: aiosqlite.Connection,
        checkpoint_id: str,
    ) -> aiosqlite.Row | tuple[object, ...] | None:
        async with conn.execute(
            """
            SELECT
                id,
                session_id,
                checkpoint_sequence_no,
                state_object_hash,
                runtime_state_schema_version,
                runtime_event_contract_version,
                state_hash,
                view_model_hash,
                created_by_operation_id,
                created_at
            FROM prototype_runtime_checkpoints
            WHERE id = ?
            """,
            (checkpoint_id,),
        ) as cursor:
            return await cursor.fetchone()

    async def _require_document(
        self,
        conn: aiosqlite.Connection,
        document_id: str,
    ) -> PrototypeDocumentRecord:
        row = await self._load_document_row(conn, document_id)
        if row is None:
            raise StructuredPrototypeStoreError(
                "document_missing",
                "prototype document does not exist",
            )
        return self._document_from_row(row)

    async def _require_draft(
        self,
        conn: aiosqlite.Connection,
        draft_id: str,
    ) -> PrototypeDraftRecord:
        row = await self._load_draft_row(conn, draft_id)
        if row is None:
            raise StructuredPrototypeStoreError(
                "draft_missing",
                "prototype draft does not exist",
            )
        return self._draft_from_row(row)

    async def _require_checkpoint(
        self,
        conn: aiosqlite.Connection,
        checkpoint_id: str,
    ) -> PrototypeCheckpointRecord:
        row = await self._load_checkpoint_row(conn, checkpoint_id)
        if row is None:
            raise StructuredPrototypeStoreError(
                "checkpoint_missing",
                "prototype checkpoint does not exist",
            )
        return self._checkpoint_from_row(row)

    async def _require_revision(
        self,
        conn: aiosqlite.Connection,
        revision_id: str,
    ) -> PrototypeRevisionRecord:
        row = await self._load_revision_row(conn, revision_id)
        if row is None:
            raise StructuredPrototypeStoreError(
                "revision_missing",
                "prototype revision does not exist",
            )
        return self._revision_from_row(row)

    async def _require_render_run(
        self,
        conn: aiosqlite.Connection,
        render_run_id: str,
    ) -> PrototypeRenderRunRecord:
        row = await self._load_render_run_row(conn, render_run_id)
        if row is None:
            raise StructuredPrototypeStoreError(
                "render_run_missing",
                "prototype render run does not exist",
            )
        return self._render_run_from_row(row)

    async def _require_runtime_session(
        self,
        conn: aiosqlite.Connection,
        session_id: str,
    ) -> PrototypeRuntimeSessionRecord:
        row = await self._load_runtime_session_row(conn, session_id)
        if row is None:
            raise StructuredPrototypeStoreError(
                "runtime_session_missing",
                "prototype runtime session does not exist",
            )
        return self._runtime_session_from_row(row)

    async def _require_runtime_checkpoint(
        self,
        conn: aiosqlite.Connection,
        checkpoint_id: str,
    ) -> PrototypeRuntimeCheckpointRecord:
        row = await self._load_runtime_checkpoint_row(conn, checkpoint_id)
        if row is None:
            raise StructuredPrototypeStoreError(
                "runtime_checkpoint_missing",
                "prototype runtime checkpoint does not exist",
            )
        return self._runtime_checkpoint_from_row(row)

    @staticmethod
    async def _list_command_batches_after(
        conn: aiosqlite.Connection,
        draft_id: str,
        checkpoint_sequence_no: int,
    ) -> list[PrototypeCommandBatchRecord]:
        async with conn.execute(
            """
            SELECT
                id,
                draft_id,
                base_sequence_no,
                result_sequence_no,
                client_request_id,
                origin,
                operation_kind,
                target_batch_id,
                command_contract_version,
                commands_json,
                inverse_commands_json,
                command_batch_hash,
                base_document_hash,
                result_document_hash,
                operation_id,
                created_at
            FROM prototype_command_batches
            WHERE draft_id = ? AND result_sequence_no > ?
            ORDER BY result_sequence_no
            LIMIT ?
            """,
            (
                draft_id,
                checkpoint_sequence_no,
                MAX_REPLAY_TAIL_BATCHES + 1,
            ),
        ) as cursor:
            rows = await cursor.fetchall()
        return [AsyncStructuredPrototypeStore._command_batch_from_row(row) for row in rows]

    @staticmethod
    async def _list_runtime_event_batches_after(
        conn: aiosqlite.Connection,
        session_id: str,
        checkpoint_sequence_no: int,
    ) -> list[PrototypeRuntimeEventBatchRecord]:
        async with conn.execute(
            """
            SELECT
                id,
                session_id,
                client_event_id,
                base_sequence_no,
                result_sequence_no,
                events_json,
                event_batch_hash,
                matched_rule_ids_json,
                guard_report_hash,
                effect_report_hash,
                outcome,
                base_state_hash,
                result_state_hash,
                result_view_model_hash,
                runtime_core_version,
                runtime_core_bundle_hash,
                state_machine_kernel_version,
                operation_id,
                created_at
            FROM prototype_runtime_event_batches
            WHERE session_id = ? AND result_sequence_no > ?
            ORDER BY result_sequence_no
            """,
            (session_id, checkpoint_sequence_no),
        ) as cursor:
            rows = await cursor.fetchall()
        return [AsyncStructuredPrototypeStore._runtime_event_batch_from_row(row) for row in rows]

    async def _assert_draft_accepts_batch(
        self,
        conn: aiosqlite.Connection,
        draft: PrototypeDraftRecord,
        batch: PrototypeCommandBatchRecord,
    ) -> None:
        if draft.status != "active":
            raise StructuredPrototypeStoreError(
                "draft_not_active",
                "prototype draft does not accept commands in its current state",
            )
        if (
            draft.head_sequence_no != batch.base_sequence_no
            or draft.head_document_hash != batch.base_document_hash
        ):
            raise StructuredPrototypeStoreError(
                "draft_conflict",
                "prototype command base does not match the current draft head",
            )
        if draft.latest_checkpoint_id is None:
            raise StructuredPrototypeStoreError(
                "draft_corrupt",
                "prototype draft has no checkpoint",
            )
        checkpoint = await self._require_checkpoint(conn, draft.latest_checkpoint_id)
        if draft.head_sequence_no - checkpoint.checkpoint_sequence_no >= MAX_REPLAY_TAIL_BATCHES:
            raise StructuredPrototypeStoreError(
                "checkpoint_required_unavailable",
                "prototype command requires a checkpoint before the replay tail can grow",
            )

    async def _validate_bounded_command_history_base(
        self,
        conn: aiosqlite.Connection,
        *,
        draft: PrototypeDraftRecord,
        base_history_checkpoint: PrototypeCommandHistoryCheckpoint,
        base_tail_batches: tuple[PrototypeCommandBatchRecord, ...],
        base_journal_prefix_hash: str,
    ) -> tuple[PrototypeCommandHistory, dict[str, PrototypeCommandBatchRecord]]:
        if draft.latest_checkpoint_id is None:
            raise StructuredPrototypeStoreError(
                "command_history_checkpoint_missing",
                "prototype draft has no command history checkpoint",
            )
        checkpoint = await self._require_checkpoint(conn, draft.latest_checkpoint_id)
        if (
            checkpoint.draft_id != draft.id
            or checkpoint.document_id != draft.document_id
            or checkpoint.history_snapshot_object_hash is None
            or checkpoint.history_snapshot_schema_version is None
            or checkpoint.journal_prefix_hash is None
            or base_history_checkpoint.draft_id != draft.id
            or base_history_checkpoint.checkpoint_sequence_no != checkpoint.checkpoint_sequence_no
            or base_history_checkpoint.checkpoint_document_hash != checkpoint.document_hash
            or base_history_checkpoint.journal_prefix_hash != checkpoint.journal_prefix_hash
            or base_history_checkpoint.snapshot_object_hash
            != checkpoint.history_snapshot_object_hash
            or base_history_checkpoint.snapshot_schema_version
            != checkpoint.history_snapshot_schema_version
        ):
            raise StructuredPrototypeStoreError(
                "command_history_checkpoint_identity_mismatch",
                "prototype command history base does not match the latest checkpoint",
            )
        if (
            _hash_canonical_json(base_history_checkpoint.to_payload())
            != base_history_checkpoint.snapshot_object_hash
        ):
            raise StructuredPrototypeStoreError(
                "command_history_checkpoint_hash_mismatch",
                "prototype command history checkpoint canonical hash is invalid",
            )
        document = await self._require_document(conn, draft.document_id)
        descriptor_row = await self._load_object_row(
            conn,
            document.project_id,
            base_history_checkpoint.snapshot_object_hash,
        )
        if descriptor_row is None:
            raise StructuredPrototypeStoreError(
                "object_missing",
                "prototype command history checkpoint object descriptor is missing",
            )
        descriptor = self._descriptor_from_row(descriptor_row)
        if descriptor.content_hash != base_history_checkpoint.snapshot_object_hash:
            raise StructuredPrototypeStoreError(
                "command_history_checkpoint_hash_mismatch",
                "prototype command history checkpoint descriptor hash is invalid",
            )
        async with conn.execute(
            """
            SELECT COUNT(*)
            FROM prototype_object_references
            WHERE project_id = ? AND owner_kind = 'checkpoint' AND owner_id = ?
              AND role = 'command-history-checkpoint' AND content_hash = ?
              AND payload_type = 'prototype_command_history_checkpoint'
              AND schema_version = ?
            """,
            (
                document.project_id,
                checkpoint.id,
                base_history_checkpoint.snapshot_object_hash,
                base_history_checkpoint.snapshot_schema_version,
            ),
        ) as cursor:
            reference_row = await cursor.fetchone()
        if reference_row is None or int(reference_row[0]) != 1:
            raise StructuredPrototypeStoreError(
                "command_history_checkpoint_missing",
                "prototype command history checkpoint reference is missing",
            )
        tail = await self._list_command_batches_after(
            conn,
            draft.id,
            checkpoint.checkpoint_sequence_no,
        )
        if len(tail) > MAX_REPLAY_TAIL_BATCHES:
            raise StructuredPrototypeStoreError(
                "replay_tail_limit_exceeded",
                "prototype command replay tail exceeds the hard limit",
            )
        if tuple(tail) != base_tail_batches:
            raise StructuredPrototypeStoreError(
                "command_history_conflict",
                "prototype command tail changed after service validation",
            )
        history = base_history_checkpoint.history
        prefix_hash = base_history_checkpoint.journal_prefix_hash
        expected_sequence_no = checkpoint.checkpoint_sequence_no
        expected_document_hash = checkpoint.document_hash
        records_by_id: dict[str, PrototypeCommandBatchRecord] = {}
        try:
            for stored in tail:
                if (
                    stored.draft_id != draft.id
                    or stored.base_sequence_no != expected_sequence_no
                    or stored.result_sequence_no != expected_sequence_no + 1
                    or stored.base_document_hash != expected_document_hash
                ):
                    raise StructuredPrototypeStoreError(
                        "replay_sequence_gap",
                        "prototype command tail is not continuous from its checkpoint",
                    )
                if stored.operation_kind != "forward":
                    stack = (
                        history.undo_stack
                        if stored.operation_kind == "undo"
                        else history.redo_stack
                    )
                    if not stack or stored.target_batch_id != stack[-1].batch_id:
                        raise StructuredPrototypeStoreError(
                            "command_history_corrupt",
                            "prototype history command does not target the sealed stack top",
                        )
                    target_entry = stack[-1]
                    target = records_by_id.get(target_entry.batch_id)
                    if target is None:
                        target_row = await self._load_command_batch_row(
                            conn,
                            draft.id,
                            target_entry.batch_id,
                        )
                        if target_row is None:
                            raise StructuredPrototypeStoreError(
                                "command_history_entry_missing",
                                "prototype sealed history target batch is missing",
                            )
                        target = self._command_batch_from_row(target_row)
                    if target.command_batch_hash != target_entry.command_batch_hash:
                        raise StructuredPrototypeStoreError(
                            "command_history_entry_hash_mismatch",
                            "prototype sealed history target hash does not match its batch",
                        )
                    if (
                        stored.commands_json != target.inverse_commands_json
                        or stored.base_document_hash != target.result_document_hash
                        or stored.result_document_hash != target.base_document_hash
                    ):
                        raise StructuredPrototypeStoreError(
                            "command_history_corrupt",
                            "prototype history command does not exactly invert its target",
                        )
                history = advance_prototype_command_history(history, stored)
                prefix_hash = _advance_journal_prefix_hash(prefix_hash, stored)
                records_by_id[stored.id] = stored
                expected_sequence_no = stored.result_sequence_no
                expected_document_hash = stored.result_document_hash
        except PrototypeCommandHistoryError as exc:
            raise StructuredPrototypeStoreError(
                "command_history_corrupt",
                "prototype command tail cannot be folded from its checkpoint",
            ) from exc
        if (
            expected_sequence_no != draft.head_sequence_no
            or expected_document_hash != draft.head_document_hash
            or prefix_hash != base_journal_prefix_hash
        ):
            raise StructuredPrototypeStoreError(
                "journal_prefix_hash_mismatch",
                "prototype command tail does not match the durable draft head",
            )
        return history, records_by_id

    async def _assert_command_history_accepts_batch(
        self,
        conn: aiosqlite.Connection,
        history: PrototypeCommandHistory,
        batch: PrototypeCommandBatchRecord,
        records_by_id: dict[str, PrototypeCommandBatchRecord],
    ) -> None:
        if batch.operation_kind == "forward":
            return
        stack = history.undo_stack if batch.operation_kind == "undo" else history.redo_stack
        if not stack or batch.target_batch_id != stack[-1].batch_id:
            raise StructuredPrototypeStoreError(
                "command_history_conflict",
                "prototype history target is no longer the legal stack top",
            )
        target = records_by_id.get(stack[-1].batch_id)
        if target is None:
            target_row = await self._load_command_batch_row(
                conn,
                batch.draft_id,
                stack[-1].batch_id,
            )
            if target_row is None:
                raise StructuredPrototypeStoreError(
                    "command_history_entry_missing",
                    "prototype sealed history target batch is missing",
                )
            target = self._command_batch_from_row(target_row)
        if (
            target.command_batch_hash != stack[-1].command_batch_hash
            or batch.commands_json != target.inverse_commands_json
            or batch.base_document_hash != target.result_document_hash
            or batch.result_document_hash != target.base_document_hash
        ):
            raise StructuredPrototypeStoreError(
                "command_batch_invalid",
                "prototype history command does not exactly invert its target batch",
            )

    async def _assert_runtime_session_accepts_event(
        self,
        conn: aiosqlite.Connection,
        session: PrototypeRuntimeSessionRecord,
        event_batch: PrototypeRuntimeEventBatchRecord,
    ) -> None:
        if session.status != "active":
            raise StructuredPrototypeStoreError(
                "runtime_session_not_active",
                "prototype runtime session does not accept events",
            )
        if (
            session.head_sequence_no != event_batch.base_sequence_no
            or session.head_state_hash != event_batch.base_state_hash
        ):
            raise StructuredPrototypeStoreError(
                "runtime_session_conflict",
                "prototype runtime event base does not match the current session head",
            )
        if (
            event_batch.runtime_core_version != session.runtime_core_version
            or event_batch.runtime_core_bundle_hash != session.runtime_core_bundle_hash
            or event_batch.state_machine_kernel_version != session.state_machine_kernel_version
        ):
            raise StructuredPrototypeStoreError(
                "runtime_version_mismatch",
                "prototype runtime event versions do not match the pinned session",
            )
        if session.latest_checkpoint_id is None:
            raise StructuredPrototypeStoreError(
                "runtime_session_corrupt",
                "prototype runtime session has no checkpoint",
            )
        checkpoint = await self._require_runtime_checkpoint(conn, session.latest_checkpoint_id)
        if checkpoint.session_id != session.id:
            raise StructuredPrototypeStoreError(
                "runtime_session_corrupt",
                "prototype runtime checkpoint belongs to another session",
            )
        if session.head_sequence_no - checkpoint.checkpoint_sequence_no >= MAX_REPLAY_TAIL_BATCHES:
            raise StructuredPrototypeStoreError(
                "runtime_checkpoint_required_unavailable",
                "prototype runtime event requires a checkpoint before the replay tail can grow",
            )

    @staticmethod
    def _validate_recovery_chain(
        draft: PrototypeDraftRecord,
        checkpoint: PrototypeCheckpointRecord,
        batches: list[PrototypeCommandBatchRecord],
    ) -> None:
        if (
            checkpoint.draft_id != draft.id
            or checkpoint.document_id != draft.document_id
            or checkpoint.checkpoint_sequence_no > draft.head_sequence_no
        ):
            raise StructuredPrototypeStoreError(
                "draft_corrupt",
                "prototype checkpoint does not belong to the draft head",
            )
        if len(batches) > MAX_REPLAY_TAIL_BATCHES:
            raise StructuredPrototypeStoreError(
                "replay_tail_limit_exceeded",
                "prototype replay tail exceeds the hard limit",
            )
        expected_sequence = checkpoint.checkpoint_sequence_no
        expected_hash = checkpoint.document_hash
        for batch in batches:
            if (
                batch.draft_id != draft.id
                or batch.base_sequence_no != expected_sequence
                or batch.result_sequence_no != expected_sequence + 1
            ):
                raise StructuredPrototypeStoreError(
                    "replay_sequence_gap",
                    "prototype command replay sequence is not continuous",
                )
            if batch.base_document_hash != expected_hash:
                raise StructuredPrototypeStoreError(
                    "replay_document_hash_mismatch",
                    "prototype command replay base hash does not match",
                )
            expected_sequence = batch.result_sequence_no
            expected_hash = batch.result_document_hash
        if expected_sequence != draft.head_sequence_no or expected_hash != draft.head_document_hash:
            raise StructuredPrototypeStoreError(
                "replay_document_hash_mismatch",
                "prototype replay result does not match the durable draft head",
            )

    @staticmethod
    def _validate_runtime_recovery_chain(
        session: PrototypeRuntimeSessionRecord,
        checkpoint: PrototypeRuntimeCheckpointRecord,
        event_batches: list[PrototypeRuntimeEventBatchRecord],
    ) -> None:
        if (
            checkpoint.session_id != session.id
            or checkpoint.checkpoint_sequence_no > session.head_sequence_no
            or checkpoint.state_object_hash != checkpoint.state_hash
        ):
            raise StructuredPrototypeStoreError(
                "runtime_session_corrupt",
                "prototype runtime checkpoint does not belong to the session head",
            )
        if len(event_batches) > MAX_REPLAY_TAIL_BATCHES:
            raise StructuredPrototypeStoreError(
                "runtime_replay_tail_limit_exceeded",
                "prototype runtime replay tail exceeds the hard limit",
            )
        expected_sequence = checkpoint.checkpoint_sequence_no
        expected_state_hash = checkpoint.state_hash
        expected_view_model_hash = checkpoint.view_model_hash
        for event_batch in event_batches:
            if (
                event_batch.session_id != session.id
                or event_batch.base_sequence_no != expected_sequence
                or event_batch.result_sequence_no != expected_sequence + 1
            ):
                raise StructuredPrototypeStoreError(
                    "runtime_replay_sequence_gap",
                    "prototype runtime event replay sequence is not continuous",
                )
            if event_batch.base_state_hash != expected_state_hash:
                raise StructuredPrototypeStoreError(
                    "runtime_replay_state_hash_mismatch",
                    "prototype runtime event replay base state hash does not match",
                )
            if (
                event_batch.runtime_core_version != session.runtime_core_version
                or event_batch.runtime_core_bundle_hash != session.runtime_core_bundle_hash
                or event_batch.state_machine_kernel_version != session.state_machine_kernel_version
            ):
                raise StructuredPrototypeStoreError(
                    "runtime_replay_version_mismatch",
                    "prototype runtime event replay version does not match the session",
                )
            expected_sequence = event_batch.result_sequence_no
            expected_state_hash = event_batch.result_state_hash
            expected_view_model_hash = event_batch.result_view_model_hash
        if (
            expected_sequence != session.head_sequence_no
            or expected_state_hash != session.head_state_hash
            or expected_view_model_hash != session.head_view_model_hash
        ):
            raise StructuredPrototypeStoreError(
                "runtime_replay_state_hash_mismatch",
                "prototype runtime replay result does not match the durable session head",
            )

    @staticmethod
    def _operation_params(operation: PrototypeOperation) -> tuple[object, ...]:
        return (
            operation.id,
            operation.operation_kind,
            operation.project_id,
            operation.resource_kind,
            operation.resource_id,
            operation.client_request_id,
            operation.correlation_id,
            operation.parent_operation_id,
            operation.status,
            operation.phase,
            operation.attempt,
            operation.request_manifest_hash,
            operation.config_manifest_hash,
            operation.result_manifest_hash,
            operation.failure_evidence_hash,
            operation.error_code,
            operation.created_at.isoformat(),
            operation.started_at.isoformat() if operation.started_at else None,
            operation.completed_at.isoformat() if operation.completed_at else None,
        )

    @staticmethod
    def _operation_step_params(step: PrototypeOperationStep) -> tuple[object, ...]:
        return (
            step.id,
            step.operation_id,
            step.parent_step_id,
            step.step_kind,
            step.step_ordinal,
            step.attempt,
            step.status,
            step.phase,
            step.input_manifest_hash,
            step.config_manifest_hash,
            step.output_manifest_hash,
            step.completion_evidence_kind,
            step.completion_evidence_ref,
            step.error_code,
            step.started_at.isoformat() if step.started_at else None,
            step.completed_at.isoformat() if step.completed_at else None,
        )

    @staticmethod
    def _generation_job_params(job: PrototypeDocumentGenerationJobRecord) -> tuple[object, ...]:
        return (
            job.id,
            job.project_id,
            job.client_request_id,
            job.status,
            job.operation_id,
            job.request_manifest_object_hash,
            job.request_hash,
            job.context_manifest_object_hash,
            job.source_policy,
            job.source_snapshot_object_hash,
            job.source_fingerprint,
            job.source_snapshot_ref,
            job.repository_object_format,
            job.worktree_base_commit,
            job.repository_project_prefix,
            job.repository_tree_object_id,
            int(job.working_tree_dirty) if job.working_tree_dirty is not None else None,
            job.excluded_tracked_change_count,
            job.excluded_untracked_count,
            job.source_file_exclusion_policy,
            job.excluded_sensitive_file_count,
            job.excluded_status_hash,
            job.blueprint_object_hash,
            job.blueprint_version,
            job.blueprint_hash,
            job.candidate_object_hash,
            job.candidate_document_hash,
            job.preview_render_run_id,
            job.preview_artifact_id,
            job.preview_renderer_version,
            job.preview_storage_key,
            job.preview_output_hash,
            job.preview_output_manifest_hash,
            job.preview_visual_preflight_report_hash,
            job.replay_manifest_object_hash,
            job.document_id,
            job.error_code,
            job.error_message,
            job.created_at.isoformat(),
            job.updated_at.isoformat(),
            job.completed_at.isoformat() if job.completed_at is not None else None,
        )

    @staticmethod
    def _generation_run_params(run: PrototypeDocumentGenerationRunRecord) -> tuple[object, ...]:
        return (
            run.id,
            run.job_id,
            run.status,
            run.blueprint_hash,
            run.total,
            run.processed,
            run.succeeded,
            run.failed,
            run.running,
            run.pending,
            run.error_code,
            run.error_message,
            run.created_at.isoformat(),
            run.updated_at.isoformat(),
            run.started_at.isoformat() if run.started_at is not None else None,
            run.completed_at.isoformat() if run.completed_at is not None else None,
        )

    @staticmethod
    def _generation_item_params(item: PrototypeDocumentGenerationItemRecord) -> tuple[object, ...]:
        return (
            item.id,
            item.job_id,
            item.run_id,
            item.kind,
            item.item_key,
            item.page_key,
            item.item_ordinal,
            item.status,
            item.phase,
            item.attempt,
            item.task_kind,
            item.operation_id,
            item.context_object_hash,
            item.submission_id,
            item.submission_request_hash,
            json.dumps(
                list(item.submission_normalized_fields),
                ensure_ascii=True,
                separators=(",", ":"),
            ),
            item.submission_accepted_at.isoformat()
            if item.submission_accepted_at is not None
            else None,
            item.output_object_hash,
            item.task_id,
            item.execution_process_id,
            item.error_code,
            item.error_message,
            item.created_at.isoformat(),
            item.updated_at.isoformat(),
            item.completed_at.isoformat() if item.completed_at is not None else None,
        )

    @staticmethod
    def _draft_params(draft: PrototypeDraftRecord) -> tuple[object, ...]:
        return (
            draft.id,
            draft.document_id,
            draft.base_revision_no,
            draft.status,
            draft.head_sequence_no,
            draft.head_document_hash,
            draft.latest_checkpoint_id,
            draft.publish_revision_no,
            draft.created_at.isoformat(),
            draft.updated_at.isoformat(),
            draft.closed_at.isoformat() if draft.closed_at else None,
        )

    @staticmethod
    def _initial_draft_params(draft: PrototypeDraftRecord) -> tuple[object, ...]:
        return (
            draft.id,
            draft.document_id,
            draft.base_revision_no,
            draft.status,
            draft.head_sequence_no,
            draft.head_document_hash,
            draft.publish_revision_no,
            draft.created_at.isoformat(),
            draft.updated_at.isoformat(),
            draft.closed_at.isoformat() if draft.closed_at else None,
        )

    @staticmethod
    def _ai_thread_params(thread: PrototypeAiThreadRecord) -> tuple[object, ...]:
        return (
            thread.id,
            thread.document_id,
            thread.title,
            thread.status,
            thread.summary_json,
            thread.summary_through_message_id,
            thread.created_at.isoformat(),
            thread.updated_at.isoformat(),
        )

    @staticmethod
    def _ai_message_params(message: PrototypeAiMessageRecord) -> tuple[object, ...]:
        return (
            message.id,
            message.thread_id,
            message.client_message_id,
            message.role,
            message.kind,
            message.content,
            message.run_id,
            message.command_batch_id,
            message.status,
            message.created_at.isoformat(),
            message.updated_at.isoformat(),
        )

    @staticmethod
    def _ai_edit_run_params(run: PrototypeAiEditRunRecord) -> tuple[object, ...]:
        return (
            run.id,
            run.thread_id,
            run.user_message_id,
            run.assistant_message_id,
            run.document_id,
            run.draft_id,
            run.operation_id,
            run.retry_of_run_id,
            run.status,
            run.scope_json,
            run.base_head_sequence_no,
            run.base_document_hash,
            run.context_object_hash,
            run.outcome_object_hash,
            run.submission_id,
            run.submission_request_hash,
            run.submission_accepted_at.isoformat()
            if run.submission_accepted_at is not None
            else None,
            run.replay_manifest_object_hash,
            run.proposed_command_batch_json,
            run.proposed_command_batch_hash,
            run.candidate_object_hash,
            run.preview_render_run_id,
            run.preview_artifact_id,
            run.summary,
            run.affected_entity_ids_json,
            run.task_id,
            run.execution_process_id,
            run.error_code,
            run.error_message,
            run.created_at.isoformat(),
            run.updated_at.isoformat(),
            run.completed_at.isoformat() if run.completed_at else None,
        )

    @staticmethod
    def _command_batch_params(batch: PrototypeCommandBatchRecord) -> tuple[object, ...]:
        return (
            batch.id,
            batch.draft_id,
            batch.base_sequence_no,
            batch.result_sequence_no,
            batch.client_request_id,
            batch.origin,
            batch.operation_kind,
            batch.target_batch_id,
            batch.command_contract_version,
            batch.commands_json,
            batch.inverse_commands_json,
            batch.command_batch_hash,
            batch.base_document_hash,
            batch.result_document_hash,
            batch.operation_id,
            batch.created_at.isoformat(),
        )

    @staticmethod
    def _operation_from_row(
        row: aiosqlite.Row | tuple[object, ...],
    ) -> PrototypeOperation:
        return PrototypeOperation(
            id=_required_str(row[0], "operation.id"),
            operation_kind=_literal(
                row[1],
                (
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
                ),
                "operation.operation_kind",
            ),
            project_id=_required_str(row[2], "operation.project_id"),
            resource_kind=_required_str(row[3], "operation.resource_kind"),
            resource_id=_optional_str(row[4], "operation.resource_id"),
            client_request_id=_required_str(row[5], "operation.client_request_id"),
            correlation_id=_required_str(row[6], "operation.correlation_id"),
            parent_operation_id=_optional_str(row[7], "operation.parent_operation_id"),
            status=_literal(
                row[8],
                ("queued", "running", "succeeded", "failed", "interrupted", "cancelled"),
                "operation.status",
            ),
            phase=_required_str(row[9], "operation.phase"),
            attempt=_required_positive_int(row[10], "operation.attempt"),
            request_manifest_hash=_required_hash(row[11], "operation.request_manifest_hash"),
            config_manifest_hash=_required_hash(row[12], "operation.config_manifest_hash"),
            result_manifest_hash=_optional_hash(row[13], "operation.result_manifest_hash"),
            failure_evidence_hash=_optional_hash(row[14], "operation.failure_evidence_hash"),
            error_code=_optional_str(row[15], "operation.error_code"),
            created_at=_datetime(row[16], "operation.created_at"),
            started_at=_optional_datetime(row[17], "operation.started_at"),
            completed_at=_optional_datetime(row[18], "operation.completed_at"),
        )

    @staticmethod
    def _operation_step_from_row(
        row: aiosqlite.Row | tuple[object, ...],
    ) -> PrototypeOperationStep:
        return PrototypeOperationStep(
            id=_required_str(row[0], "step.id"),
            operation_id=_required_str(row[1], "step.operation_id"),
            parent_step_id=_optional_str(row[2], "step.parent_step_id"),
            step_kind=_required_str(row[3], "step.step_kind"),
            step_ordinal=_required_non_negative_int(row[4], "step.step_ordinal"),
            attempt=_required_positive_int(row[5], "step.attempt"),
            status=_literal(
                row[6],
                ("pending", "running", "succeeded", "failed", "skipped", "interrupted"),
                "step.status",
            ),
            phase=_required_str(row[7], "step.phase"),
            input_manifest_hash=_required_hash(row[8], "step.input_manifest_hash"),
            config_manifest_hash=_required_hash(row[9], "step.config_manifest_hash"),
            output_manifest_hash=_optional_hash(row[10], "step.output_manifest_hash"),
            completion_evidence_kind=_optional_str(row[11], "step.completion_evidence_kind"),
            completion_evidence_ref=_optional_str(row[12], "step.completion_evidence_ref"),
            error_code=_optional_str(row[13], "step.error_code"),
            started_at=_optional_datetime(row[14], "step.started_at"),
            completed_at=_optional_datetime(row[15], "step.completed_at"),
        )

    @staticmethod
    def _operation_event_from_row(
        row: aiosqlite.Row | tuple[object, ...],
    ) -> PrototypeOperationEvent:
        return PrototypeOperationEvent(
            operation_id=_required_str(row[0], "event.operation_id"),
            event_no=_required_non_negative_int(row[1], "event.event_no"),
            step_id=_optional_str(row[2], "event.step_id"),
            event_kind=_required_str(row[3], "event.event_kind"),
            status=_literal(
                row[4],
                (
                    "queued",
                    "pending",
                    "running",
                    "succeeded",
                    "failed",
                    "skipped",
                    "interrupted",
                    "cancelled",
                ),
                "event.status",
            ),
            phase=_required_str(row[5], "event.phase"),
            input_hash=_optional_hash(row[6], "event.input_hash"),
            output_hash=_optional_hash(row[7], "event.output_hash"),
            evidence_hash=_optional_hash(row[8], "event.evidence_hash"),
            error_code=_optional_str(row[9], "event.error_code"),
            occurred_at=_datetime(row[10], "event.occurred_at"),
        )

    @staticmethod
    def _generation_job_from_row(
        row: aiosqlite.Row | tuple[object, ...],
    ) -> PrototypeDocumentGenerationJobRecord:
        return PrototypeDocumentGenerationJobRecord(
            id=_required_str(row[0], "generation_job.id"),
            project_id=_required_str(row[1], "generation_job.project_id"),
            client_request_id=_required_str(row[2], "generation_job.client_request_id"),
            status=_literal(
                row[3],
                (
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
                ),
                "generation_job.status",
            ),
            operation_id=_required_str(row[4], "generation_job.operation_id"),
            request_manifest_object_hash=_required_hash(
                row[5], "generation_job.request_manifest_object_hash"
            ),
            request_hash=_required_hash(row[6], "generation_job.request_hash"),
            context_manifest_object_hash=_required_hash(
                row[7], "generation_job.context_manifest_object_hash"
            ),
            source_policy=_generation_source_policy(row[8]),
            source_snapshot_object_hash=_optional_hash(
                row[9], "generation_job.source_snapshot_object_hash"
            ),
            source_fingerprint=_optional_hash(row[10], "generation_job.source_fingerprint"),
            source_snapshot_ref=_optional_str(row[11], "generation_job.source_snapshot_ref"),
            repository_object_format=_optional_str(
                row[12], "generation_job.repository_object_format"
            ),
            worktree_base_commit=_optional_str(row[13], "generation_job.worktree_base_commit"),
            repository_project_prefix=_optional_text(
                row[14], "generation_job.repository_project_prefix"
            ),
            repository_tree_object_id=_optional_str(
                row[15], "generation_job.repository_tree_object_id"
            ),
            working_tree_dirty=_optional_sqlite_bool(row[16], "generation_job.working_tree_dirty"),
            excluded_tracked_change_count=_optional_non_negative_int(
                row[17], "generation_job.excluded_tracked_change_count"
            ),
            excluded_untracked_count=_optional_non_negative_int(
                row[18], "generation_job.excluded_untracked_count"
            ),
            source_file_exclusion_policy=_generation_source_file_exclusion_policy(row[19]),
            excluded_sensitive_file_count=_optional_non_negative_int(
                row[20], "generation_job.excluded_sensitive_file_count"
            ),
            excluded_status_hash=_optional_hash(row[21], "generation_job.excluded_status_hash"),
            blueprint_object_hash=_optional_hash(row[22], "generation_job.blueprint_object_hash"),
            blueprint_version=_required_non_negative_int(
                row[23], "generation_job.blueprint_version"
            ),
            blueprint_hash=_optional_hash(row[24], "generation_job.blueprint_hash"),
            candidate_object_hash=_optional_hash(row[25], "generation_job.candidate_object_hash"),
            candidate_document_hash=_optional_hash(
                row[26], "generation_job.candidate_document_hash"
            ),
            preview_render_run_id=_optional_str(row[27], "generation_job.preview_render_run_id"),
            preview_artifact_id=_optional_str(row[28], "generation_job.preview_artifact_id"),
            preview_renderer_version=_optional_str(
                row[29], "generation_job.preview_renderer_version"
            ),
            preview_storage_key=_optional_str(row[30], "generation_job.preview_storage_key"),
            preview_output_hash=_optional_hash(row[31], "generation_job.preview_output_hash"),
            preview_output_manifest_hash=_optional_hash(
                row[32], "generation_job.preview_output_manifest_hash"
            ),
            preview_visual_preflight_report_hash=_optional_hash(
                row[33], "generation_job.preview_visual_preflight_report_hash"
            ),
            replay_manifest_object_hash=_optional_hash(
                row[34], "generation_job.replay_manifest_object_hash"
            ),
            document_id=_optional_str(row[35], "generation_job.document_id"),
            error_code=_optional_str(row[36], "generation_job.error_code"),
            error_message=_optional_str(row[37], "generation_job.error_message"),
            created_at=_datetime(row[38], "generation_job.created_at"),
            updated_at=_datetime(row[39], "generation_job.updated_at"),
            completed_at=_optional_datetime(row[40], "generation_job.completed_at"),
        )

    @staticmethod
    def _generation_run_from_row(
        row: aiosqlite.Row | tuple[object, ...],
    ) -> PrototypeDocumentGenerationRunRecord:
        return PrototypeDocumentGenerationRunRecord(
            id=_required_str(row[0], "generation_run.id"),
            job_id=_required_str(row[1], "generation_run.job_id"),
            status=_literal(
                row[2],
                ("queued", "running", "completed", "failed", "interrupted", "cancelled"),
                "generation_run.status",
            ),
            blueprint_hash=_optional_hash(row[3], "generation_run.blueprint_hash"),
            total=_required_positive_int(row[4], "generation_run.total"),
            processed=_required_non_negative_int(row[5], "generation_run.processed"),
            succeeded=_required_non_negative_int(row[6], "generation_run.succeeded"),
            failed=_required_non_negative_int(row[7], "generation_run.failed"),
            running=_required_non_negative_int(row[8], "generation_run.running"),
            pending=_required_non_negative_int(row[9], "generation_run.pending"),
            error_code=_optional_str(row[10], "generation_run.error_code"),
            error_message=_optional_str(row[11], "generation_run.error_message"),
            created_at=_datetime(row[12], "generation_run.created_at"),
            updated_at=_datetime(row[13], "generation_run.updated_at"),
            started_at=_optional_datetime(row[14], "generation_run.started_at"),
            completed_at=_optional_datetime(row[15], "generation_run.completed_at"),
        )

    @staticmethod
    def _generation_item_from_row(
        row: aiosqlite.Row | tuple[object, ...],
    ) -> PrototypeDocumentGenerationItemRecord:
        return PrototypeDocumentGenerationItemRecord(
            id=_required_str(row[0], "generation_item.id"),
            job_id=_required_str(row[1], "generation_item.job_id"),
            run_id=_required_str(row[2], "generation_item.run_id"),
            kind=_literal(row[3], ("blueprint", "foundation", "page"), "generation_item.kind"),
            item_key=_required_str(row[4], "generation_item.item_key"),
            page_key=_optional_str(row[5], "generation_item.page_key"),
            item_ordinal=_required_non_negative_int(row[6], "generation_item.item_ordinal"),
            status=_literal(
                row[7],
                ("pending", "generating", "validating", "done", "failed", "interrupted"),
                "generation_item.status",
            ),
            phase=_required_str(row[8], "generation_item.phase"),
            attempt=_required_positive_int(row[9], "generation_item.attempt"),
            task_kind=_required_str(row[10], "generation_item.task_kind"),
            operation_id=_required_str(row[11], "generation_item.operation_id"),
            context_object_hash=_required_hash(row[12], "generation_item.context_object_hash"),
            submission_id=_optional_str(row[13], "generation_item.submission_id"),
            submission_request_hash=_optional_hash(
                row[14], "generation_item.submission_request_hash"
            ),
            submission_normalized_fields=_string_tuple_from_json(
                row[15], "generation_item.submission_normalized_fields_json"
            ),
            submission_accepted_at=_optional_datetime(
                row[16], "generation_item.submission_accepted_at"
            ),
            output_object_hash=_optional_hash(row[17], "generation_item.output_object_hash"),
            task_id=_optional_str(row[18], "generation_item.task_id"),
            execution_process_id=_optional_str(row[19], "generation_item.execution_process_id"),
            error_code=_optional_str(row[20], "generation_item.error_code"),
            error_message=_optional_str(row[21], "generation_item.error_message"),
            created_at=_datetime(row[22], "generation_item.created_at"),
            updated_at=_datetime(row[23], "generation_item.updated_at"),
            completed_at=_optional_datetime(row[24], "generation_item.completed_at"),
        )

    @staticmethod
    def _document_from_row(
        row: aiosqlite.Row | tuple[object, ...],
    ) -> PrototypeDocumentRecord:
        return PrototypeDocumentRecord(
            id=_required_str(row[0], "document.id"),
            project_id=_required_str(row[1], "document.project_id"),
            title=_required_str(row[2], "document.title"),
            published_revision_no=_optional_positive_int(row[3], "document.published_revision_no"),
            active_draft_id=_optional_str(row[4], "document.active_draft_id"),
            created_at=_datetime(row[5], "document.created_at"),
            updated_at=_datetime(row[6], "document.updated_at"),
        )

    @staticmethod
    def _draft_from_row(
        row: aiosqlite.Row | tuple[object, ...],
    ) -> PrototypeDraftRecord:
        return PrototypeDraftRecord(
            id=_required_str(row[0], "draft.id"),
            document_id=_required_str(row[1], "draft.document_id"),
            base_revision_no=_optional_positive_int(row[2], "draft.base_revision_no"),
            status=_literal(
                row[3],
                ("active", "publishing", "closed", "corrupt"),
                "draft.status",
            ),
            head_sequence_no=_required_non_negative_int(row[4], "draft.head_sequence_no"),
            head_document_hash=_required_hash(row[5], "draft.head_document_hash"),
            latest_checkpoint_id=_optional_str(row[6], "draft.latest_checkpoint_id"),
            publish_revision_no=_optional_positive_int(row[7], "draft.publish_revision_no"),
            created_at=_datetime(row[8], "draft.created_at"),
            updated_at=_datetime(row[9], "draft.updated_at"),
            closed_at=_optional_datetime(row[10], "draft.closed_at"),
        )

    @staticmethod
    def _checkpoint_from_row(
        row: aiosqlite.Row | tuple[object, ...],
    ) -> PrototypeCheckpointRecord:
        return PrototypeCheckpointRecord(
            id=_required_str(row[0], "checkpoint.id"),
            document_id=_required_str(row[1], "checkpoint.document_id"),
            draft_id=_optional_str(row[2], "checkpoint.draft_id"),
            revision_id=_optional_str(row[3], "checkpoint.revision_id"),
            checkpoint_kind=_literal(
                row[4],
                ("draft", "revision", "generation_accept", "ai_apply"),
                "checkpoint.checkpoint_kind",
            ),
            checkpoint_sequence_no=_required_non_negative_int(
                row[5], "checkpoint.checkpoint_sequence_no"
            ),
            document_object_hash=_required_hash(row[6], "checkpoint.document_object_hash"),
            document_schema_version=_required_positive_int(
                row[7], "checkpoint.document_schema_version"
            ),
            command_contract_version=_required_positive_int(
                row[8], "checkpoint.command_contract_version"
            ),
            document_hash=_required_hash(row[9], "checkpoint.document_hash"),
            history_snapshot_object_hash=_optional_hash(
                row[10], "checkpoint.history_snapshot_object_hash"
            ),
            history_snapshot_schema_version=_optional_positive_int(
                row[11], "checkpoint.history_snapshot_schema_version"
            ),
            journal_prefix_hash=_optional_hash(row[12], "checkpoint.journal_prefix_hash"),
            created_by_operation_id=_required_str(row[13], "checkpoint.created_by_operation_id"),
            created_at=_datetime(row[14], "checkpoint.created_at"),
        )

    @staticmethod
    def _revision_from_row(
        row: aiosqlite.Row | tuple[object, ...],
    ) -> PrototypeRevisionRecord:
        return PrototypeRevisionRecord(
            id=_required_str(row[0], "revision.id"),
            document_id=_required_str(row[1], "revision.document_id"),
            revision_no=_required_positive_int(row[2], "revision.revision_no"),
            schema_version=_required_positive_int(row[3], "revision.schema_version"),
            checkpoint_id=_required_str(row[4], "revision.checkpoint_id"),
            document_object_hash=_required_hash(row[5], "revision.document_object_hash"),
            document_hash=_required_hash(row[6], "revision.document_hash"),
            summary=_required_str(row[7], "revision.summary"),
            source=_literal(
                row[8],
                ("user", "ai", "initial_generation"),
                "revision.source",
            ),
            created_at=_datetime(row[9], "revision.created_at"),
        )

    @staticmethod
    def _render_run_from_row(
        row: aiosqlite.Row | tuple[object, ...],
    ) -> PrototypeRenderRunRecord:
        return PrototypeRenderRunRecord(
            id=_required_str(row[0], "render_run.id"),
            document_id=_required_str(row[1], "render_run.document_id"),
            kind=_literal(row[2], ("ai_preview", "publication"), "render_run.kind"),
            revision_id=_optional_str(row[3], "render_run.revision_id"),
            ai_edit_run_id=_optional_str(row[4], "render_run.ai_edit_run_id"),
            status=_literal(
                row[5],
                ("queued", "rendering", "ready", "failed", "interrupted"),
                "render_run.status",
            ),
            renderer_version=_required_str(row[6], "render_run.renderer_version"),
            renderer_environment_version=_required_str(
                row[7], "render_run.renderer_environment_version"
            ),
            runtime_core_version=_required_str(row[8], "render_run.runtime_core_version"),
            runtime_core_source_hash=_required_hash(row[9], "render_run.runtime_core_source_hash"),
            runtime_core_bundle_hash=_required_hash(row[10], "render_run.runtime_core_bundle_hash"),
            state_machine_kernel_version=_required_str(
                row[11], "render_run.state_machine_kernel_version"
            ),
            render_runtime_image_hash=_required_hash(
                row[12], "render_run.render_runtime_image_hash"
            ),
            browser_version=_required_str(row[13], "render_run.browser_version"),
            font_pack_hash=_required_hash(row[14], "render_run.font_pack_hash"),
            viewport_profile_hash=_required_hash(row[15], "render_run.viewport_profile_hash"),
            sandbox_policy_version=_required_str(row[16], "render_run.sandbox_policy_version"),
            input_manifest_hash=_required_hash(row[17], "render_run.input_manifest_hash"),
            document_object_hash=_required_hash(row[18], "render_run.document_object_hash"),
            document_hash=_required_hash(row[19], "render_run.document_hash"),
            operation_id=_required_str(row[20], "render_run.operation_id"),
            attempt=_required_positive_int(row[21], "render_run.attempt"),
            artifact_id=_optional_str(row[22], "render_run.artifact_id"),
            output_manifest_hash=_optional_hash(row[23], "render_run.output_manifest_hash"),
            error_code=_optional_str(row[24], "render_run.error_code"),
            error_message=_optional_str(row[25], "render_run.error_message"),
            started_at=_optional_datetime(row[26], "render_run.started_at"),
            completed_at=_optional_datetime(row[27], "render_run.completed_at"),
            created_at=_datetime(row[28], "render_run.created_at"),
            updated_at=_datetime(row[29], "render_run.updated_at"),
        )

    @staticmethod
    def _render_artifact_from_row(
        row: aiosqlite.Row | tuple[object, ...],
    ) -> PrototypeRenderArtifactRecord:
        return PrototypeRenderArtifactRecord(
            id=_required_str(row[0], "render_artifact.id"),
            render_run_id=_required_str(row[1], "render_artifact.render_run_id"),
            document_id=_required_str(row[2], "render_artifact.document_id"),
            revision_id=_optional_str(row[3], "render_artifact.revision_id"),
            renderer_version=_required_str(row[4], "render_artifact.renderer_version"),
            document_hash=_required_hash(row[5], "render_artifact.document_hash"),
            output_hash=_required_hash(row[6], "render_artifact.output_hash"),
            output_manifest_hash=_required_hash(row[7], "render_artifact.output_manifest_hash"),
            storage_key=_required_str(row[8], "render_artifact.storage_key"),
            entrypoint=_required_str(row[9], "render_artifact.entrypoint"),
            visual_preflight_report_hash=_required_hash(
                row[10], "render_artifact.visual_preflight_report_hash"
            ),
            created_at=_datetime(row[11], "render_artifact.created_at"),
        )

    @staticmethod
    def _ai_thread_from_row(
        row: aiosqlite.Row | tuple[object, ...],
    ) -> PrototypeAiThreadRecord:
        return PrototypeAiThreadRecord(
            id=_required_str(row[0], "ai_thread.id"),
            document_id=_required_str(row[1], "ai_thread.document_id"),
            title=_required_str(row[2], "ai_thread.title"),
            status=_literal(row[3], ("active", "archived"), "ai_thread.status"),
            summary_json=_optional_str(row[4], "ai_thread.summary_json"),
            summary_through_message_id=_optional_str(
                row[5], "ai_thread.summary_through_message_id"
            ),
            created_at=_datetime(row[6], "ai_thread.created_at"),
            updated_at=_datetime(row[7], "ai_thread.updated_at"),
        )

    @staticmethod
    def _ai_message_from_row(
        row: aiosqlite.Row | tuple[object, ...],
    ) -> PrototypeAiMessageRecord:
        return PrototypeAiMessageRecord(
            id=_required_str(row[0], "ai_message.id"),
            thread_id=_required_str(row[1], "ai_message.thread_id"),
            client_message_id=_optional_str(row[2], "ai_message.client_message_id"),
            role=_literal(row[3], ("user", "assistant"), "ai_message.role"),
            kind=_literal(
                row[4],
                ("instruction", "answer", "clarification", "proposal", "error"),
                "ai_message.kind",
            ),
            content=_required_str(row[5], "ai_message.content"),
            run_id=_optional_str(row[6], "ai_message.run_id"),
            command_batch_id=_optional_str(row[7], "ai_message.command_batch_id"),
            status=_literal(
                row[8],
                ("pending", "completed", "failed", "rejected", "applied"),
                "ai_message.status",
            ),
            created_at=_datetime(row[9], "ai_message.created_at"),
            updated_at=_datetime(row[10], "ai_message.updated_at"),
        )

    @staticmethod
    def _ai_edit_run_from_row(
        row: aiosqlite.Row | tuple[object, ...],
    ) -> PrototypeAiEditRunRecord:
        return PrototypeAiEditRunRecord(
            id=_required_str(row[0], "ai_run.id"),
            thread_id=_required_str(row[1], "ai_run.thread_id"),
            user_message_id=_required_str(row[2], "ai_run.user_message_id"),
            assistant_message_id=_optional_str(row[3], "ai_run.assistant_message_id"),
            document_id=_required_str(row[4], "ai_run.document_id"),
            draft_id=_required_str(row[5], "ai_run.draft_id"),
            operation_id=_required_str(row[6], "ai_run.operation_id"),
            retry_of_run_id=_optional_str(row[7], "ai_run.retry_of_run_id"),
            status=_literal(
                row[8],
                (
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
                ),
                "ai_run.status",
            ),
            scope_json=_required_str(row[9], "ai_run.scope_json"),
            base_head_sequence_no=_required_non_negative_int(
                row[10], "ai_run.base_head_sequence_no"
            ),
            base_document_hash=_required_hash(row[11], "ai_run.base_document_hash"),
            context_object_hash=_optional_hash(row[12], "ai_run.context_object_hash"),
            outcome_object_hash=_optional_hash(row[13], "ai_run.outcome_object_hash"),
            submission_id=_optional_str(row[14], "ai_run.submission_id"),
            submission_request_hash=_optional_hash(row[15], "ai_run.submission_request_hash"),
            submission_accepted_at=_optional_datetime(row[16], "ai_run.submission_accepted_at"),
            replay_manifest_object_hash=_optional_hash(
                row[17], "ai_run.replay_manifest_object_hash"
            ),
            proposed_command_batch_json=_optional_str(
                row[18], "ai_run.proposed_command_batch_json"
            ),
            proposed_command_batch_hash=_optional_hash(
                row[19], "ai_run.proposed_command_batch_hash"
            ),
            candidate_object_hash=_optional_hash(row[20], "ai_run.candidate_object_hash"),
            preview_render_run_id=_optional_str(row[21], "ai_run.preview_render_run_id"),
            preview_artifact_id=_optional_str(row[22], "ai_run.preview_artifact_id"),
            summary=_optional_str(row[23], "ai_run.summary"),
            affected_entity_ids_json=_optional_str(row[24], "ai_run.affected_entity_ids_json"),
            task_id=_optional_str(row[25], "ai_run.task_id"),
            execution_process_id=_optional_str(row[26], "ai_run.execution_process_id"),
            error_code=_optional_str(row[27], "ai_run.error_code"),
            error_message=_optional_str(row[28], "ai_run.error_message"),
            created_at=_datetime(row[29], "ai_run.created_at"),
            updated_at=_datetime(row[30], "ai_run.updated_at"),
            completed_at=_optional_datetime(row[31], "ai_run.completed_at"),
        )

    @staticmethod
    def _command_batch_from_row(
        row: aiosqlite.Row | tuple[object, ...],
    ) -> PrototypeCommandBatchRecord:
        return PrototypeCommandBatchRecord(
            id=_required_str(row[0], "batch.id"),
            draft_id=_required_str(row[1], "batch.draft_id"),
            base_sequence_no=_required_non_negative_int(row[2], "batch.base_sequence_no"),
            result_sequence_no=_required_positive_int(row[3], "batch.result_sequence_no"),
            client_request_id=_required_str(row[4], "batch.client_request_id"),
            origin=_literal(row[5], ("user", "ai", "system"), "batch.origin"),
            operation_kind=_literal(
                row[6],
                ("forward", "undo", "redo"),
                "batch.operation_kind",
            ),
            target_batch_id=_optional_str(row[7], "batch.target_batch_id"),
            command_contract_version=_required_positive_int(
                row[8], "batch.command_contract_version"
            ),
            commands_json=_required_str(row[9], "batch.commands_json"),
            inverse_commands_json=_required_str(row[10], "batch.inverse_commands_json"),
            command_batch_hash=_required_hash(row[11], "batch.command_batch_hash"),
            base_document_hash=_required_hash(row[12], "batch.base_document_hash"),
            result_document_hash=_required_hash(row[13], "batch.result_document_hash"),
            operation_id=_required_str(row[14], "batch.operation_id"),
            created_at=_datetime(row[15], "batch.created_at"),
        )

    @staticmethod
    def _runtime_session_from_row(
        row: aiosqlite.Row | tuple[object, ...],
    ) -> PrototypeRuntimeSessionRecord:
        return PrototypeRuntimeSessionRecord(
            id=_required_str(row[0], "runtime_session.id"),
            project_id=_required_str(row[1], "runtime_session.project_id"),
            document_id=_required_str(row[2], "runtime_session.document_id"),
            source_kind=_literal(
                row[3],
                ("draft", "ai_preview", "published_revision"),
                "runtime_session.source_kind",
            ),
            source_id=_required_str(row[4], "runtime_session.source_id"),
            pinned_document_object_hash=_required_hash(
                row[5], "runtime_session.pinned_document_object_hash"
            ),
            runtime_core_version=_required_str(row[6], "runtime_session.runtime_core_version"),
            runtime_core_bundle_hash=_required_hash(
                row[7], "runtime_session.runtime_core_bundle_hash"
            ),
            state_machine_kernel_version=_required_str(
                row[8], "runtime_session.state_machine_kernel_version"
            ),
            scenario_id=_required_str(row[9], "runtime_session.scenario_id"),
            scenario_hash=_required_hash(row[10], "runtime_session.scenario_hash"),
            status=_literal(
                row[11],
                ("active", "completed", "interrupted", "corrupt"),
                "runtime_session.status",
            ),
            head_sequence_no=_required_non_negative_int(
                row[12], "runtime_session.head_sequence_no"
            ),
            head_state_hash=_required_hash(row[13], "runtime_session.head_state_hash"),
            head_view_model_hash=_required_hash(row[14], "runtime_session.head_view_model_hash"),
            latest_checkpoint_id=_optional_str(row[15], "runtime_session.latest_checkpoint_id"),
            recording_kind=_literal(
                row[16],
                ("studio_preview", "recorded_review", "shared_preview"),
                "runtime_session.recording_kind",
            ),
            allow_simulated_role_switch=_required_sqlite_bool(
                row[17], "runtime_session.allow_simulated_role_switch"
            ),
            actor_subject_id=_optional_str(row[18], "runtime_session.actor_subject_id"),
            replaces_session_id=_optional_str(row[19], "runtime_session.replaces_session_id"),
            created_at=_datetime(row[20], "runtime_session.created_at"),
            updated_at=_datetime(row[21], "runtime_session.updated_at"),
            completed_at=_optional_datetime(row[22], "runtime_session.completed_at"),
        )

    @staticmethod
    def _runtime_event_batch_from_row(
        row: aiosqlite.Row | tuple[object, ...],
    ) -> PrototypeRuntimeEventBatchRecord:
        return PrototypeRuntimeEventBatchRecord(
            id=_required_str(row[0], "runtime_event.id"),
            session_id=_required_str(row[1], "runtime_event.session_id"),
            client_event_id=_required_str(row[2], "runtime_event.client_event_id"),
            base_sequence_no=_required_non_negative_int(row[3], "runtime_event.base_sequence_no"),
            result_sequence_no=_required_positive_int(row[4], "runtime_event.result_sequence_no"),
            events_json=_required_str(row[5], "runtime_event.events_json"),
            event_batch_hash=_required_hash(row[6], "runtime_event.event_batch_hash"),
            matched_rule_ids_json=_required_str(row[7], "runtime_event.matched_rule_ids_json"),
            guard_report_hash=_required_hash(row[8], "runtime_event.guard_report_hash"),
            effect_report_hash=_required_hash(row[9], "runtime_event.effect_report_hash"),
            outcome=_literal(
                row[10],
                ("applied", "guard_false", "validation_failed"),
                "runtime_event.outcome",
            ),
            base_state_hash=_required_hash(row[11], "runtime_event.base_state_hash"),
            result_state_hash=_required_hash(row[12], "runtime_event.result_state_hash"),
            result_view_model_hash=_required_hash(row[13], "runtime_event.result_view_model_hash"),
            runtime_core_version=_required_str(row[14], "runtime_event.runtime_core_version"),
            runtime_core_bundle_hash=_required_hash(
                row[15], "runtime_event.runtime_core_bundle_hash"
            ),
            state_machine_kernel_version=_required_str(
                row[16], "runtime_event.state_machine_kernel_version"
            ),
            operation_id=_required_str(row[17], "runtime_event.operation_id"),
            created_at=_datetime(row[18], "runtime_event.created_at"),
        )

    @staticmethod
    def _runtime_checkpoint_from_row(
        row: aiosqlite.Row | tuple[object, ...],
    ) -> PrototypeRuntimeCheckpointRecord:
        return PrototypeRuntimeCheckpointRecord(
            id=_required_str(row[0], "runtime_checkpoint.id"),
            session_id=_required_str(row[1], "runtime_checkpoint.session_id"),
            checkpoint_sequence_no=_required_non_negative_int(
                row[2], "runtime_checkpoint.checkpoint_sequence_no"
            ),
            state_object_hash=_required_hash(row[3], "runtime_checkpoint.state_object_hash"),
            runtime_state_schema_version=_required_positive_int(
                row[4], "runtime_checkpoint.runtime_state_schema_version"
            ),
            runtime_event_contract_version=_required_positive_int(
                row[5], "runtime_checkpoint.runtime_event_contract_version"
            ),
            state_hash=_required_hash(row[6], "runtime_checkpoint.state_hash"),
            view_model_hash=_required_hash(row[7], "runtime_checkpoint.view_model_hash"),
            created_by_operation_id=_required_str(
                row[8], "runtime_checkpoint.created_by_operation_id"
            ),
            created_at=_datetime(row[9], "runtime_checkpoint.created_at"),
        )

    @staticmethod
    def _assert_idempotent_runtime_event_batch(
        existing: PrototypeRuntimeEventBatchRecord,
        incoming: PrototypeRuntimeEventBatchRecord,
    ) -> None:
        if (
            existing.session_id,
            existing.client_event_id,
            existing.base_sequence_no,
            existing.result_sequence_no,
            existing.events_json,
            existing.event_batch_hash,
            existing.matched_rule_ids_json,
            existing.guard_report_hash,
            existing.effect_report_hash,
            existing.outcome,
            existing.base_state_hash,
            existing.result_state_hash,
            existing.result_view_model_hash,
            existing.runtime_core_version,
            existing.runtime_core_bundle_hash,
            existing.state_machine_kernel_version,
            existing.operation_id,
        ) != (
            incoming.session_id,
            incoming.client_event_id,
            incoming.base_sequence_no,
            incoming.result_sequence_no,
            incoming.events_json,
            incoming.event_batch_hash,
            incoming.matched_rule_ids_json,
            incoming.guard_report_hash,
            incoming.effect_report_hash,
            incoming.outcome,
            incoming.base_state_hash,
            incoming.result_state_hash,
            incoming.result_view_model_hash,
            incoming.runtime_core_version,
            incoming.runtime_core_bundle_hash,
            incoming.state_machine_kernel_version,
            incoming.operation_id,
        ):
            raise StructuredPrototypeStoreError(
                "runtime_event_idempotency_conflict",
                "prototype runtime event request was retried with different inputs",
            )

    @staticmethod
    def _assert_idempotent_command_batch(
        existing: PrototypeCommandBatchRecord,
        incoming: PrototypeCommandBatchRecord,
    ) -> None:
        if (
            existing.draft_id,
            existing.base_sequence_no,
            existing.result_sequence_no,
            existing.client_request_id,
            existing.origin,
            existing.operation_kind,
            existing.target_batch_id,
            existing.command_contract_version,
            existing.commands_json,
            existing.inverse_commands_json,
            existing.command_batch_hash,
            existing.base_document_hash,
            existing.result_document_hash,
            existing.operation_id,
        ) != (
            incoming.draft_id,
            incoming.base_sequence_no,
            incoming.result_sequence_no,
            incoming.client_request_id,
            incoming.origin,
            incoming.operation_kind,
            incoming.target_batch_id,
            incoming.command_contract_version,
            incoming.commands_json,
            incoming.inverse_commands_json,
            incoming.command_batch_hash,
            incoming.base_document_hash,
            incoming.result_document_hash,
            incoming.operation_id,
        ):
            raise StructuredPrototypeStoreError(
                "command_idempotency_conflict",
                "prototype command request was retried with different inputs",
            )

    @staticmethod
    def _assert_ai_message_idempotent(
        existing: PrototypeAiMessageRecord,
        incoming: PrototypeAiMessageRecord,
    ) -> None:
        if (
            existing.id,
            existing.thread_id,
            existing.client_message_id,
            existing.role,
            existing.kind,
            existing.content,
            existing.run_id,
        ) != (
            incoming.id,
            incoming.thread_id,
            incoming.client_message_id,
            incoming.role,
            incoming.kind,
            incoming.content,
            incoming.run_id,
        ):
            raise StructuredPrototypeStoreError(
                "ai_message_idempotency_conflict",
                "prototype AI message was retried with different inputs",
            )

    @staticmethod
    def _assert_ai_edit_run_immutable_identity(
        existing: PrototypeAiEditRunRecord,
        incoming: PrototypeAiEditRunRecord,
    ) -> None:
        if (
            existing.id,
            existing.thread_id,
            existing.user_message_id,
            existing.document_id,
            existing.draft_id,
            existing.operation_id,
            existing.retry_of_run_id,
            existing.scope_json,
            existing.base_head_sequence_no,
            existing.base_document_hash,
            existing.created_at,
        ) != (
            incoming.id,
            incoming.thread_id,
            incoming.user_message_id,
            incoming.document_id,
            incoming.draft_id,
            incoming.operation_id,
            incoming.retry_of_run_id,
            incoming.scope_json,
            incoming.base_head_sequence_no,
            incoming.base_document_hash,
            incoming.created_at,
        ):
            raise StructuredPrototypeStoreError(
                "ai_run_identity_mismatch",
                "prototype AI edit run immutable identity changed",
            )

    @classmethod
    def _assert_ai_edit_run_idempotent(
        cls,
        existing: PrototypeAiEditRunRecord,
        incoming: PrototypeAiEditRunRecord,
    ) -> None:
        cls._assert_ai_edit_run_immutable_identity(existing, incoming)
        if existing.status != incoming.status:
            raise StructuredPrototypeStoreError(
                "ai_run_idempotency_conflict",
                "prototype AI edit run retry resolved to a different lifecycle state",
            )

    @classmethod
    def _validate_generation_job_create(
        cls,
        *,
        job_operation: PrototypeOperation,
        item_operation: PrototypeOperation,
        job: PrototypeDocumentGenerationJobRecord,
        run: PrototypeDocumentGenerationRunRecord,
        item: PrototypeDocumentGenerationItemRecord,
    ) -> None:
        for value, field in (
            (job.request_manifest_object_hash, "generation_job.request_manifest_object_hash"),
            (job.request_hash, "generation_job.request_hash"),
            (job.context_manifest_object_hash, "generation_job.context_manifest_object_hash"),
            (job.source_snapshot_object_hash, "generation_job.source_snapshot_object_hash"),
            (job.source_fingerprint, "generation_job.source_fingerprint"),
            (job.excluded_status_hash, "generation_job.excluded_status_hash"),
            (item.context_object_hash, "generation_item.context_object_hash"),
        ):
            _required_hash(value, field)
        if (
            job.status != "queued"
            or job.source_policy != "committed_head_v1"
            or job.source_snapshot_ref != f"refs/agent-collab/prototype-generation/{job.id}"
            or job.repository_object_format not in {"sha1", "sha256"}
            or job.worktree_base_commit is None
            or GIT_OBJECT_ID_RE.fullmatch(job.worktree_base_commit) is None
            or job.repository_project_prefix is None
            or job.repository_tree_object_id is None
            or GIT_OBJECT_ID_RE.fullmatch(job.repository_tree_object_id) is None
            or job.working_tree_dirty is None
            or job.excluded_tracked_change_count is None
            or job.excluded_tracked_change_count < 0
            or job.excluded_untracked_count is None
            or job.excluded_untracked_count < 0
            or job.source_file_exclusion_policy != "dotenv_checkout_filter_v1"
            or job.excluded_sensitive_file_count is None
            or job.excluded_sensitive_file_count < 0
            or job.blueprint_version != 0
            or job.blueprint_object_hash is not None
            or job.blueprint_hash is not None
            or job.candidate_object_hash is not None
            or job.candidate_document_hash is not None
            or job.preview_render_run_id is not None
            or job.preview_artifact_id is not None
            or job.preview_renderer_version is not None
            or job.preview_storage_key is not None
            or job.preview_output_hash is not None
            or job.preview_output_manifest_hash is not None
            or job.preview_visual_preflight_report_hash is not None
            or job.replay_manifest_object_hash is not None
            or job.document_id is not None
            or job.error_code is not None
            or job.error_message is not None
            or job.completed_at is not None
            or run.status != "queued"
            or run.blueprint_hash is not None
            or run.job_id != job.id
            or item.job_id != job.id
            or item.run_id != run.id
            or item.kind != "blueprint"
            or item.item_key != "blueprint"
            or item.page_key is not None
            or item.status != "pending"
            or item.task_kind != "generation_blueprint"
            or item.context_object_hash != job.context_manifest_object_hash
            or item.submission_id is not None
            or item.submission_request_hash is not None
            or item.submission_normalized_fields
            or item.submission_accepted_at is not None
            or item.output_object_hash is not None
            or item.task_id is None
            or item.execution_process_id is not None
            or item.error_code is not None
            or item.error_message is not None
            or item.completed_at is not None
        ):
            raise StructuredPrototypeStoreError(
                "generation_job_invalid",
                "new structured prototype generation records are inconsistent",
            )
        if (
            job.operation_id != job_operation.id
            or job_operation.operation_kind != "generation_job"
            or job_operation.project_id != job.project_id
            or job_operation.resource_kind != "generation_job"
            or job_operation.resource_id != job.id
            or job_operation.status != "queued"
            or item.operation_id != item_operation.id
            or item_operation.operation_kind != "generation_item"
            or item_operation.project_id != job.project_id
            or item_operation.resource_kind != "generation_item"
            or item_operation.resource_id != item.id
            or item_operation.parent_operation_id != job_operation.id
            or item_operation.status != "queued"
        ):
            raise StructuredPrototypeStoreError(
                "generation_operation_identity_mismatch",
                "generation job and item operation identities are inconsistent",
            )

    @staticmethod
    def _validate_generation_run_counts(
        run: PrototypeDocumentGenerationRunRecord,
        items: tuple[PrototypeDocumentGenerationItemRecord, ...],
    ) -> None:
        if not items or any(item.run_id != run.id or item.job_id != run.job_id for item in items):
            raise StructuredPrototypeStoreError(
                "generation_run_invalid",
                "generation run items do not belong to the supplied run",
            )
        if sorted(item.item_ordinal for item in items) != list(range(len(items))):
            raise StructuredPrototypeStoreError(
                "generation_run_invalid",
                "generation run item ordinals must be unique and contiguous",
            )
        succeeded = sum(item.status == "done" for item in items)
        failed = sum(item.status in {"failed", "interrupted"} for item in items)
        running = sum(item.status in {"generating", "validating"} for item in items)
        pending = sum(item.status == "pending" for item in items)
        processed = succeeded + failed
        if (
            run.total != len(items)
            or run.processed != processed
            or run.succeeded != succeeded
            or run.failed != failed
            or run.running != running
            or run.pending != pending
            or processed + running + pending != run.total
        ):
            raise StructuredPrototypeStoreError(
                "generation_run_invalid",
                "generation run counters do not match its durable items",
            )
        if run.status == "completed" and succeeded != run.total:
            raise StructuredPrototypeStoreError(
                "generation_run_invalid",
                "completed generation run must have only successful items",
            )

    @staticmethod
    def _validate_generation_run_create(
        operation: PrototypeOperation,
        job: PrototypeDocumentGenerationJobRecord,
        run: PrototypeDocumentGenerationRunRecord,
        item_operations: tuple[
            tuple[
                PrototypeDocumentGenerationItemRecord,
                PrototypeOperation,
                PrototypeOperationEvent,
            ],
            ...,
        ],
    ) -> None:
        items = tuple(item for item, _, _ in item_operations)
        if (
            job.status != "generating"
            or job.blueprint_version <= 0
            or job.blueprint_hash is None
            or job.blueprint_object_hash != job.blueprint_hash
            or run.job_id != job.id
            or run.status != "queued"
            or run.blueprint_hash != job.blueprint_hash
            or operation.operation_kind != "generation_job"
            or operation.project_id != job.project_id
            or operation.resource_kind != "generation_job"
            or operation.resource_id != job.id
            or operation.parent_operation_id != job.operation_id
            or operation.status not in {"queued", "running"}
        ):
            raise StructuredPrototypeStoreError(
                "generation_run_invalid",
                "scheduled generation run does not match its confirmed job",
            )
        if sorted(item.item_ordinal for item in items) != list(range(len(items))):
            raise StructuredPrototypeStoreError(
                "generation_run_invalid",
                "generation run item ordinals must be unique and contiguous",
            )
        item_kinds = {item.kind for item in items}
        if item_kinds == {"foundation"}:
            if len(items) != 1 or items[0].item_key != "foundation":
                raise StructuredPrototypeStoreError(
                    "generation_run_invalid",
                    "foundation generation run must contain exactly one foundation item",
                )
        elif item_kinds == {"page"}:
            if (
                not items
                or any(item.page_key is None or item.item_key != item.page_key for item in items)
                or len({item.page_key for item in items}) != len(items)
            ):
                raise StructuredPrototypeStoreError(
                    "generation_run_invalid",
                    "page generation run must contain unique page items",
                )
        else:
            raise StructuredPrototypeStoreError(
                "generation_run_invalid",
                "generation run must contain only one supported phase kind",
            )
        for item, item_operation, _ in item_operations:
            expected_task_kind = f"generation_{item.kind}"
            if (
                item.status != "pending"
                or item.phase != "queued"
                or item.task_kind != expected_task_kind
                or item.task_id is None
                or item.submission_id is not None
                or item.submission_request_hash is not None
                or item.submission_normalized_fields
                or item.submission_accepted_at is not None
                or item.output_object_hash is not None
                or item.execution_process_id is not None
                or item.error_code is not None
                or item.error_message is not None
                or item.completed_at is not None
                or item.operation_id != item_operation.id
                or item_operation.operation_kind != "generation_item"
                or item_operation.project_id != job.project_id
                or item_operation.resource_kind != "generation_item"
                or item_operation.resource_id != item.id
                or item_operation.parent_operation_id != operation.id
                or item_operation.status != "queued"
            ):
                raise StructuredPrototypeStoreError(
                    "generation_item_invalid",
                    "scheduled generation item or operation identity is inconsistent",
                )

    @staticmethod
    def _assert_generation_job_identity(
        existing: PrototypeDocumentGenerationJobRecord,
        incoming: PrototypeDocumentGenerationJobRecord,
    ) -> None:
        if (
            existing.id,
            existing.project_id,
            existing.client_request_id,
            existing.operation_id,
            existing.request_manifest_object_hash,
            existing.request_hash,
            existing.context_manifest_object_hash,
            existing.source_policy,
            existing.source_snapshot_object_hash,
            existing.source_fingerprint,
            existing.source_snapshot_ref,
            existing.repository_object_format,
            existing.worktree_base_commit,
            existing.repository_project_prefix,
            existing.repository_tree_object_id,
            existing.working_tree_dirty,
            existing.excluded_tracked_change_count,
            existing.excluded_untracked_count,
            existing.source_file_exclusion_policy,
            existing.excluded_sensitive_file_count,
            existing.excluded_status_hash,
            existing.created_at,
        ) != (
            incoming.id,
            incoming.project_id,
            incoming.client_request_id,
            incoming.operation_id,
            incoming.request_manifest_object_hash,
            incoming.request_hash,
            incoming.context_manifest_object_hash,
            incoming.source_policy,
            incoming.source_snapshot_object_hash,
            incoming.source_fingerprint,
            incoming.source_snapshot_ref,
            incoming.repository_object_format,
            incoming.worktree_base_commit,
            incoming.repository_project_prefix,
            incoming.repository_tree_object_id,
            incoming.working_tree_dirty,
            incoming.excluded_tracked_change_count,
            incoming.excluded_untracked_count,
            incoming.source_file_exclusion_policy,
            incoming.excluded_sensitive_file_count,
            incoming.excluded_status_hash,
            incoming.created_at,
        ):
            raise StructuredPrototypeStoreError(
                "generation_job_identity_mismatch",
                "structured prototype generation job immutable identity changed",
            )

    @classmethod
    def _assert_generation_job_idempotent(
        cls,
        existing: PrototypeDocumentGenerationJobRecord,
        incoming: PrototypeDocumentGenerationJobRecord,
    ) -> None:
        del cls
        if (
            existing.id != incoming.id
            or existing.project_id != incoming.project_id
            or existing.client_request_id != incoming.client_request_id
            or existing.request_manifest_object_hash != incoming.request_manifest_object_hash
            or existing.request_hash != incoming.request_hash
        ):
            raise StructuredPrototypeStoreError(
                "generation_job_idempotency_conflict",
                "generation job request was retried with different requirements",
            )

    @staticmethod
    def _assert_generation_run_identity(
        existing: PrototypeDocumentGenerationRunRecord,
        incoming: PrototypeDocumentGenerationRunRecord,
    ) -> None:
        if (existing.id, existing.job_id, existing.created_at) != (
            incoming.id,
            incoming.job_id,
            incoming.created_at,
        ) or (
            existing.blueprint_hash is not None
            and existing.blueprint_hash != incoming.blueprint_hash
        ):
            raise StructuredPrototypeStoreError(
                "generation_run_identity_mismatch",
                "structured prototype generation run immutable identity changed",
            )

    @staticmethod
    def _assert_generation_run_schedule_idempotent(
        existing: PrototypeDocumentGenerationRunRecord,
        incoming: PrototypeDocumentGenerationRunRecord,
    ) -> None:
        if (
            existing.id,
            existing.job_id,
            existing.blueprint_hash,
        ) != (
            incoming.id,
            incoming.job_id,
            incoming.blueprint_hash,
        ):
            raise StructuredPrototypeStoreError(
                "generation_run_identity_mismatch",
                "structured prototype generation run retry changed its scheduling identity",
            )

    @staticmethod
    def _assert_generation_item_identity(
        existing: PrototypeDocumentGenerationItemRecord,
        incoming: PrototypeDocumentGenerationItemRecord,
    ) -> None:
        if (
            existing.id,
            existing.job_id,
            existing.run_id,
            existing.kind,
            existing.item_key,
            existing.page_key,
            existing.item_ordinal,
            existing.attempt,
            existing.task_kind,
            existing.operation_id,
            existing.context_object_hash,
            existing.created_at,
        ) != (
            incoming.id,
            incoming.job_id,
            incoming.run_id,
            incoming.kind,
            incoming.item_key,
            incoming.page_key,
            incoming.item_ordinal,
            incoming.attempt,
            incoming.task_kind,
            incoming.operation_id,
            incoming.context_object_hash,
            incoming.created_at,
        ):
            raise StructuredPrototypeStoreError(
                "generation_item_identity_mismatch",
                "structured prototype generation item immutable identity changed",
            )

    @staticmethod
    def _assert_generation_job_status_transition(existing: str, incoming: str) -> None:
        allowed = {
            "queued": {"planning", "failed", "interrupted", "cancelled"},
            "planning": {"awaiting_confirmation", "failed", "interrupted", "cancelled"},
            "awaiting_confirmation": {"generating", "failed", "cancelled"},
            "generating": {"assembling", "failed", "interrupted", "cancelled"},
            "assembling": {"validating", "failed", "interrupted", "cancelled"},
            "validating": {"rendering_preview", "failed", "interrupted", "cancelled"},
            "rendering_preview": {"ready", "failed", "interrupted", "cancelled"},
            "ready": {"accepted", "failed", "cancelled"},
            "accepted": set(),
            "failed": set(),
            "interrupted": set(),
            "cancelled": set(),
        }
        if incoming != existing and incoming not in allowed[existing]:
            raise StructuredPrototypeStoreError(
                "generation_job_transition_invalid",
                f"generation job cannot transition from {existing} to {incoming}",
            )

    @staticmethod
    def _assert_generation_run_status_transition(existing: str, incoming: str) -> None:
        allowed = {
            "queued": {"running", "failed", "interrupted", "cancelled"},
            "running": {"completed", "failed", "interrupted", "cancelled"},
            "completed": set(),
            "failed": set(),
            "interrupted": set(),
            "cancelled": set(),
        }
        if incoming != existing and incoming not in allowed[existing]:
            raise StructuredPrototypeStoreError(
                "generation_run_transition_invalid",
                f"generation run cannot transition from {existing} to {incoming}",
            )

    @staticmethod
    def _assert_generation_item_status_transition(existing: str, incoming: str) -> None:
        allowed = {
            "pending": {"generating", "failed", "interrupted"},
            "generating": {"validating", "failed", "interrupted"},
            "validating": {"done", "failed", "interrupted"},
            "done": set(),
            "failed": set(),
            "interrupted": set(),
        }
        if incoming != existing and incoming not in allowed[existing]:
            raise StructuredPrototypeStoreError(
                "generation_item_transition_invalid",
                f"generation item cannot transition from {existing} to {incoming}",
            )

    @classmethod
    async def _load_generation_restart_recovery_scope_tx(
        cls,
        conn: aiosqlite.Connection,
    ) -> PrototypeGenerationRestartRecoveryScope:
        async with conn.execute(
            """
            WITH RECURSIVE generation_tree(id, root_id) AS (
                SELECT id, id
                FROM prototype_operations
                WHERE operation_kind = 'generation_job'
                  AND resource_kind = 'generation_job'
                  AND parent_operation_id IS NULL
                UNION ALL
                SELECT child.id, generation_tree.root_id
                FROM prototype_operations AS child
                JOIN generation_tree ON child.parent_operation_id = generation_tree.id
            )
            SELECT generation_tree.root_id, operation.id
            FROM generation_tree
            JOIN prototype_operations AS operation ON operation.id = generation_tree.id
            WHERE operation.status IN ('queued', 'running')
              AND NOT (
                  operation.id = generation_tree.root_id
                  AND EXISTS (
                      SELECT 1
                      FROM prototype_document_generation_jobs AS job
                      WHERE job.operation_id = operation.id
                        AND job.status = 'awaiting_confirmation'
                  )
              )
            ORDER BY operation.created_at, operation.id
            """
        ) as cursor:
            operation_rows = list(await cursor.fetchall())

        targets: list[PrototypeGenerationRestartOperationTarget] = []
        root_ids: set[str] = set()
        for root_id_value, operation_id_value in operation_rows:
            root_id = _required_str(root_id_value, "generation_recovery.root_operation_id")
            operation_id = _required_str(
                operation_id_value,
                "generation_recovery.operation_id",
            )
            operation_row = await cls._load_operation_row(conn, operation_id)
            if operation_row is None:
                raise StructuredPrototypeStoreError(
                    "generation_recovery_corrupt",
                    "generation restart operation disappeared while loading its scope",
                )
            operation = cls._operation_from_row(operation_row)
            async with conn.execute(
                """
                SELECT
                    id, operation_id, parent_step_id, step_kind, step_ordinal,
                    attempt, status, phase, input_manifest_hash, config_manifest_hash,
                    output_manifest_hash, completion_evidence_kind,
                    completion_evidence_ref, error_code, started_at, completed_at
                FROM prototype_operation_steps
                WHERE operation_id = ? AND status IN ('pending', 'running')
                ORDER BY step_ordinal, attempt
                """,
                (operation.id,),
            ) as cursor:
                active_step_rows = list(await cursor.fetchall())
            if len(active_step_rows) > 1:
                raise StructuredPrototypeStoreError(
                    "generation_recovery_corrupt",
                    "generation operation has multiple active steps",
                )
            active_step = (
                cls._operation_step_from_row(active_step_rows[0]) if active_step_rows else None
            )
            if (
                operation.status == "queued"
                and active_step is not None
                and active_step.status == "running"
            ):
                raise StructuredPrototypeStoreError(
                    "generation_recovery_corrupt",
                    "queued generation operation has a running step",
                )
            async with conn.execute(
                """
                SELECT COALESCE(MAX(step_ordinal), -1) + 1
                FROM prototype_operation_steps
                WHERE operation_id = ?
                """,
                (operation.id,),
            ) as cursor:
                ordinal_row = await cursor.fetchone()
            if ordinal_row is None:
                raise StructuredPrototypeStoreError(
                    "generation_recovery_corrupt",
                    "generation recovery step ordinal could not be loaded",
                )
            targets.append(
                PrototypeGenerationRestartOperationTarget(
                    operation=operation,
                    active_step=active_step,
                    next_step_ordinal=_required_non_negative_int(
                        ordinal_row[0],
                        "generation_recovery.next_step_ordinal",
                    ),
                    next_event_no=await cls._next_operation_event_no(conn, operation.id),
                )
            )
            root_ids.add(root_id)

        async with conn.execute(
            """
            SELECT id, status, operation_id, updated_at
            FROM prototype_document_generation_jobs
            WHERE status IN (
                'queued', 'planning', 'generating', 'assembling',
                'validating', 'rendering_preview'
            )
            ORDER BY id
            """
        ) as cursor:
            job_rows = list(await cursor.fetchall())
        async with conn.execute(
            """
            SELECT id, job_id, status, total, processed, succeeded, failed,
                   running, pending, updated_at
            FROM prototype_document_generation_runs
            WHERE status IN ('queued', 'running')
            ORDER BY id
            """
        ) as cursor:
            run_rows = list(await cursor.fetchall())
        async with conn.execute(
            """
            SELECT id, job_id, run_id, status, phase, operation_id, updated_at
            FROM prototype_document_generation_run_items
            WHERE status IN ('pending', 'generating', 'validating')
            ORDER BY id
            """
        ) as cursor:
            item_rows = list(await cursor.fetchall())

        target_operation_ids = {target.operation.id for target in targets}
        active_job_ids: set[str] = set()
        for row in job_rows:
            job_id = _required_str(row[0], "generation_recovery.job_id")
            operation_id = _required_str(row[2], "generation_recovery.job_operation_id")
            if operation_id not in target_operation_ids:
                raise StructuredPrototypeStoreError(
                    "generation_recovery_corrupt",
                    "active generation job has no active root operation",
                )
            active_job_ids.add(job_id)
        active_run_ids: set[str] = set()
        for row in run_rows:
            run_id = _required_str(row[0], "generation_recovery.run_id")
            job_id = _required_str(row[1], "generation_recovery.run_job_id")
            if job_id not in active_job_ids:
                raise StructuredPrototypeStoreError(
                    "generation_recovery_corrupt",
                    "active generation run has no active job",
                )
            active_run_ids.add(run_id)
        for row in item_rows:
            if (
                _required_str(row[1], "generation_recovery.item_job_id") not in active_job_ids
                or _required_str(row[2], "generation_recovery.item_run_id") not in active_run_ids
                or _required_str(row[5], "generation_recovery.item_operation_id")
                not in target_operation_ids
            ):
                raise StructuredPrototypeStoreError(
                    "generation_recovery_corrupt",
                    "active generation item has inconsistent restart lineage",
                )

        operation_payloads: list[dict[str, object]] = []
        for target in targets:
            operation = target.operation
            step = target.active_step
            operation_payloads.append(
                {
                    "id": operation.id,
                    "projectId": operation.project_id,
                    "operationKind": operation.operation_kind,
                    "resourceKind": operation.resource_kind,
                    "resourceId": operation.resource_id,
                    "parentOperationId": operation.parent_operation_id,
                    "status": operation.status,
                    "phase": operation.phase,
                    "requestManifestHash": operation.request_manifest_hash,
                    "configManifestHash": operation.config_manifest_hash,
                    "activeStep": None
                    if step is None
                    else {
                        "id": step.id,
                        "stepKind": step.step_kind,
                        "stepOrdinal": step.step_ordinal,
                        "attempt": step.attempt,
                        "status": step.status,
                        "phase": step.phase,
                        "inputManifestHash": step.input_manifest_hash,
                        "configManifestHash": step.config_manifest_hash,
                    },
                    "nextStepOrdinal": target.next_step_ordinal,
                    "nextEventNo": target.next_event_no,
                }
            )
        fingerprint = _hash_canonical_json(
            {
                "operations": operation_payloads,
                "jobs": [list(row) for row in job_rows],
                "runs": [list(row) for row in run_rows],
                "items": [list(row) for row in item_rows],
            }
        )
        return PrototypeGenerationRestartRecoveryScope(
            fingerprint=fingerprint,
            operations=tuple(targets),
            affected_root_count=len(root_ids),
            active_job_count=len(job_rows),
            active_run_count=len(run_rows),
            active_item_count=len(item_rows),
        )

    async def _interrupt_generation_operation(
        self,
        conn: aiosqlite.Connection,
        target: PrototypeGenerationRestartOperationTarget,
        *,
        evidence_hash: str,
        interrupted_at: datetime,
    ) -> None:
        _required_hash(evidence_hash, "generation_recovery.evidence_hash")
        operation = target.operation
        step = target.active_step
        event_no = target.next_event_no
        recovery_phase = "service_restart_recovery"
        if step is None or step.status == "pending":
            running_operation = replace(
                operation,
                status="running",
                phase=recovery_phase,
                started_at=operation.started_at or interrupted_at,
            )
            running_step = (
                replace(
                    step,
                    status="running",
                    phase=recovery_phase,
                    started_at=step.started_at or interrupted_at,
                )
                if step is not None
                else PrototypeOperationStep(
                    id=f"{operation.id}:restart-recovery:{target.next_step_ordinal}",
                    operation_id=operation.id,
                    parent_step_id=None,
                    step_kind="service_restart_recovery",
                    step_ordinal=target.next_step_ordinal,
                    attempt=1,
                    status="running",
                    phase=recovery_phase,
                    input_manifest_hash=operation.request_manifest_hash,
                    config_manifest_hash=operation.config_manifest_hash,
                    output_manifest_hash=None,
                    completion_evidence_kind=None,
                    completion_evidence_ref=None,
                    error_code=None,
                    started_at=interrupted_at,
                    completed_at=None,
                )
            )
            await self._apply_operation_transition(
                conn,
                running_operation,
                running_step,
                PrototypeOperationEvent(
                    operation_id=operation.id,
                    event_no=event_no,
                    step_id=running_step.id,
                    event_kind="recovery_step_started",
                    status="running",
                    phase=recovery_phase,
                    input_hash=running_step.input_manifest_hash,
                    output_hash=None,
                    evidence_hash=None,
                    error_code=None,
                    occurred_at=interrupted_at,
                ),
            )
            operation = running_operation
            step = running_step
            event_no += 1
        if step is None or step.status != "running":
            raise StructuredPrototypeStoreError(
                "generation_recovery_corrupt",
                "generation operation has no running step to interrupt",
            )
        interrupted_operation = replace(
            operation,
            status="interrupted",
            phase=recovery_phase,
            failure_evidence_hash=evidence_hash,
            error_code="restart_interrupted",
            completed_at=interrupted_at,
        )
        interrupted_step = replace(
            step,
            status="interrupted",
            phase=recovery_phase,
            output_manifest_hash=evidence_hash,
            completion_evidence_kind="generation_evidence_manifest",
            completion_evidence_ref=evidence_hash,
            error_code="restart_interrupted",
            completed_at=interrupted_at,
        )
        await self._apply_operation_transition(
            conn,
            interrupted_operation,
            interrupted_step,
            PrototypeOperationEvent(
                operation_id=operation.id,
                event_no=event_no,
                step_id=interrupted_step.id,
                event_kind="operation_interrupted",
                status="interrupted",
                phase=recovery_phase,
                input_hash=interrupted_step.input_manifest_hash,
                output_hash=evidence_hash,
                evidence_hash=evidence_hash,
                error_code="restart_interrupted",
                occurred_at=interrupted_at,
            ),
        )

    @staticmethod
    def _validate_registration(
        descriptor: PrototypeObjectDescriptor,
        reference: PrototypeObjectReference,
    ) -> None:
        if descriptor.project_id != reference.project_id:
            raise StructuredPrototypeStoreError(
                "object_reference_identity_mismatch",
                "prototype object reference project does not match its descriptor",
            )
        if descriptor.content_hash != reference.content_hash:
            raise StructuredPrototypeStoreError(
                "object_reference_identity_mismatch",
                "prototype object reference hash does not match its descriptor",
            )
        if not reference.owner_id or not reference.role:
            raise StructuredPrototypeStoreError(
                "object_reference_invalid",
                "prototype object reference owner and role must not be empty",
            )
        if reference.schema_version <= 0:
            raise StructuredPrototypeStoreError(
                "object_reference_invalid",
                "prototype object reference schema version must be positive",
            )

    @staticmethod
    def _descriptor_params(descriptor: PrototypeObjectDescriptor) -> tuple[object, ...]:
        return (
            descriptor.project_id,
            descriptor.content_hash,
            descriptor.media_type,
            descriptor.storage_codec,
            descriptor.storage_codec_version,
            descriptor.canonical_byte_size,
            descriptor.stored_byte_size,
            descriptor.storage_hash,
            descriptor.storage_key,
            descriptor.created_at.isoformat(),
        )

    @staticmethod
    def _assert_descriptor_matches(
        row: aiosqlite.Row | tuple[object, ...],
        descriptor: PrototypeObjectDescriptor,
    ) -> None:
        stored = AsyncStructuredPrototypeStore._descriptor_from_row(row)
        stored_identity = AsyncStructuredPrototypeStore._descriptor_params(stored)[:9]
        incoming_identity = AsyncStructuredPrototypeStore._descriptor_params(descriptor)[:9]
        if stored_identity != incoming_identity:
            raise StructuredPrototypeStoreError(
                "object_descriptor_conflict",
                "prototype object descriptor conflicts with the registered object",
            )

    @staticmethod
    def _descriptor_from_row(
        row: aiosqlite.Row | tuple[object, ...],
    ) -> PrototypeObjectDescriptor:
        return PrototypeObjectDescriptor(
            project_id=_required_str(row[0], "descriptor.project_id"),
            content_hash=_required_str(row[1], "descriptor.content_hash"),
            media_type=_media_type(row[2]),
            storage_codec=_storage_codec(row[3]),
            storage_codec_version=_required_str(row[4], "descriptor.storage_codec_version"),
            canonical_byte_size=_required_non_negative_int(
                row[5], "descriptor.canonical_byte_size"
            ),
            stored_byte_size=_required_non_negative_int(row[6], "descriptor.stored_byte_size"),
            storage_hash=_required_str(row[7], "descriptor.storage_hash"),
            storage_key=_required_str(row[8], "descriptor.storage_key"),
            created_at=_datetime(row[9], "descriptor.created_at"),
        )
