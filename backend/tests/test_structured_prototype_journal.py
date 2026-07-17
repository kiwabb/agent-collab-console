from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import aiosqlite
import pytest

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.adapters.prototype_object_store import PrototypeObjectStore
from app.adapters.sqlite_store import SQLiteStore
from app.adapters.structured_prototype_store import (
    MAX_REPLAY_TAIL_BATCHES,
    AsyncStructuredPrototypeStore,
    StructuredPrototypeStoreError,
)
from app.application.structured_prototype_contracts import (
    COMMAND_HISTORY_CHECKPOINT_SCHEMA_VERSION,
    command_history_checkpoint_to_domain,
    initial_journal_prefix_hash,
    parse_command_history_checkpoint_json,
)
from app.domain.structured_prototype import (
    PrototypeCheckpointRecord,
    PrototypeCommandAppendResult,
    PrototypeCommandBatchRecord,
    PrototypeCommandHistory,
    PrototypeCommandHistoryCheckpoint,
    PrototypeDocumentRecord,
    PrototypeDraftRecord,
    PrototypeObjectDescriptor,
    PrototypeObjectReference,
    PrototypeOperation,
    PrototypeOperationEvent,
    PrototypeOperationKind,
    PrototypeOperationStep,
    PrototypeReplayManifestV1,
    PrototypeReplayManifestVersionsV1,
    PrototypeRuntimeCheckpointRecord,
    PrototypeRuntimeEventAppendResult,
    PrototypeRuntimeEventBatchRecord,
    PrototypeRuntimeSessionRecord,
    advance_prototype_command_history,
    fold_prototype_command_history,
)

RUNTIME_CORE_VERSION = "0.1.0-spike"
RUNTIME_CORE_BUNDLE_HASH = "sha256:" + "8" * 64
STATE_MACHINE_KERNEL_VERSION = "5.32.4"
DRAFT_ID = "00000000-0000-0000-0000-000000000001"


def _hash(character: str) -> str:
    assert len(character) == 1 and character in "0123456789abcdef"
    return "sha256:" + character * 64


def _queued_operation(
    *,
    operation_id: str,
    operation_kind: PrototypeOperationKind,
    client_request_id: str,
    resource_kind: str,
    resource_id: str | None,
    now: datetime,
) -> PrototypeOperation:
    return PrototypeOperation(
        id=operation_id,
        operation_kind=operation_kind,
        project_id="project-1",
        resource_kind=resource_kind,
        resource_id=resource_id,
        client_request_id=client_request_id,
        correlation_id=f"correlation-{client_request_id}",
        parent_operation_id=None,
        status="queued",
        phase="queued",
        attempt=1,
        request_manifest_hash=_hash("a"),
        config_manifest_hash=_hash("b"),
        result_manifest_hash=None,
        failure_evidence_hash=None,
        error_code=None,
        created_at=now,
        started_at=None,
        completed_at=None,
    )


def _event_zero(operation: PrototypeOperation) -> PrototypeOperationEvent:
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


@pytest.mark.asyncio
async def test_operation_request_lookup_is_strictly_scoped_by_project_and_kind(
    tmp_path: Path,
) -> None:
    store = AsyncStructuredPrototypeStore(tmp_path / "operation-outcome.db")
    operation = _queued_operation(
        operation_id="operation-outcome-scope",
        operation_kind="apply_command_batch",
        client_request_id="request-operation-outcome-scope",
        resource_kind="draft",
        resource_id=DRAFT_ID,
        now=datetime.now(UTC),
    )
    try:
        await store.create_operation(operation, _event_zero(operation))

        assert (
            await store.load_operation_by_request(
                "project-1",
                "apply_command_batch",
                operation.client_request_id,
            )
            == operation
        )
        assert (
            await store.load_operation_by_request(
                "project-2",
                "apply_command_batch",
                operation.client_request_id,
            )
            is None
        )
        assert (
            await store.load_operation_by_request(
                "project-1",
                "undo",
                operation.client_request_id,
            )
            is None
        )
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_operation_observability_snapshot_is_atomic_and_child_order_is_stable(
    tmp_path: Path,
) -> None:
    store = AsyncStructuredPrototypeStore(tmp_path / "operation-observability.db")
    now = datetime.now(UTC)
    parent = _queued_operation(
        operation_id="operation-observability-parent",
        operation_kind="generation_job",
        client_request_id="request-operation-observability-parent",
        resource_kind="generation_job",
        resource_id="generation-job-observability",
        now=now,
    )
    child_b = replace(
        parent,
        id="operation-observability-child-b",
        operation_kind="generation_item",
        resource_kind="generation_item",
        resource_id="generation-item-observability-b",
        client_request_id="request-operation-observability-child-b",
        correlation_id="correlation-operation-observability-child-b",
        parent_operation_id=parent.id,
    )
    child_a = replace(
        child_b,
        id="operation-observability-child-a",
        resource_id="generation-item-observability-a",
        client_request_id="request-operation-observability-child-a",
        correlation_id="correlation-operation-observability-child-a",
    )
    try:
        await store.create_operation(parent, _event_zero(parent))
        await store.create_operation(child_b, _event_zero(child_b))
        await store.create_operation(child_a, _event_zero(child_a))

        snapshot = await store.load_operation_observability(parent.id)
        assert snapshot is not None
        assert snapshot.operation == parent
        assert snapshot.steps == ()
        assert snapshot.events == (_event_zero(parent),)
        assert [child.id for child in snapshot.child_operations] == [child_a.id, child_b.id]
        assert await store.load_operation_observability("operation-observability-missing") is None
    finally:
        await store.close()


async def _start_operation(
    store: AsyncStructuredPrototypeStore,
    operation: PrototypeOperation,
    *,
    step_id: str,
    step_kind: str,
    now: datetime,
) -> tuple[PrototypeOperation, PrototypeOperationStep]:
    created = await store.create_operation(operation, _event_zero(operation))
    assert created.created
    running_operation = replace(
        operation,
        status="running",
        phase=step_kind,
        started_at=now,
    )
    running_step = PrototypeOperationStep(
        id=step_id,
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
    await store.record_operation_transition(
        running_operation,
        running_step,
        PrototypeOperationEvent(
            operation_id=operation.id,
            event_no=1,
            step_id=step_id,
            event_kind="step_started",
            status="running",
            phase=step_kind,
            input_hash=running_step.input_manifest_hash,
            output_hash=None,
            evidence_hash=None,
            error_code=None,
            occurred_at=now,
        ),
    )
    return running_operation, running_step


def _complete_operation(
    operation: PrototypeOperation,
    step: PrototypeOperationStep,
    *,
    evidence_ref: str,
    event_no: int,
    now: datetime,
) -> tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent]:
    output_hash = _hash("c")
    completed_operation = replace(
        operation,
        status="succeeded",
        result_manifest_hash=output_hash,
        completed_at=now,
    )
    completed_step = replace(
        step,
        status="succeeded",
        output_manifest_hash=output_hash,
        completion_evidence_kind="sqlite_row",
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
    return completed_operation, completed_step, event


def _bind_strict_replay_manifest(
    object_store: PrototypeObjectStore,
    operation: PrototypeOperation,
    step: PrototypeOperationStep,
    event: PrototypeOperationEvent,
) -> tuple[
    PrototypeOperation,
    PrototypeOperationStep,
    PrototypeOperationEvent,
    PrototypeObjectDescriptor,
    PrototypeObjectReference,
]:
    assert operation.status == "succeeded"
    assert operation.completed_at is not None
    manifest = PrototypeReplayManifestV1(
        operation_id=operation.id,
        operation_kind=operation.operation_kind,
        parent_operation_id=operation.parent_operation_id,
        request_manifest_hash=operation.request_manifest_hash,
        context_manifest_hash=None,
        ordered_input_object_hashes=(),
        versions=PrototypeReplayManifestVersionsV1(
            service_version="structured-prototype-journal-test/1",
            document_schema_version=1,
            command_contract_version=1,
            runtime_state_schema_version=1,
            runtime_event_contract_version=1,
            runtime_core_version=None,
            runtime_core_bundle_hash=None,
            state_machine_kernel_version=None,
            renderer_version=None,
            renderer_environment_version=None,
        ),
        agent_task_identity=None,
        submission_hash=None,
        ordered_command_batch_hashes=(),
        base_checkpoint_hash=None,
        base_sequence_no=None,
        result_checkpoint_hash=None,
        result_sequence_no=None,
        renderer_input_hash=None,
        renderer_output_hash=None,
        runtime_session_id=None,
        runtime_core_bundle_hash=None,
        ordered_runtime_event_hashes=(),
        runtime_final_state_hash=None,
        runtime_final_view_model_hash=None,
        validation_report_hashes=(),
        terminal_status="succeeded",
        error_code=None,
    )
    descriptor = object_store.write_json(operation.project_id, manifest.to_payload())
    assert (
        PrototypeReplayManifestV1.from_canonical_json(object_store.read_canonical_bytes(descriptor))
        == manifest
    )
    reference = PrototypeObjectReference(
        project_id=operation.project_id,
        owner_kind="replay_manifest",
        owner_id=operation.id,
        role="operation-replay-manifest",
        content_hash=descriptor.content_hash,
        payload_type="replay_manifest",
        schema_version=1,
        created_at=operation.completed_at,
    )
    return (
        replace(operation, result_manifest_hash=descriptor.content_hash),
        replace(step, output_manifest_hash=descriptor.content_hash),
        replace(event, output_hash=descriptor.content_hash, evidence_hash=descriptor.content_hash),
        descriptor,
        reference,
    )


def _fail_operation(
    operation: PrototypeOperation,
    step: PrototypeOperationStep,
    *,
    error_code: str,
    now: datetime,
) -> tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent]:
    failure_hash = _hash("f")
    failed_operation = replace(
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
    return failed_operation, failed_step, event


def _reference(
    descriptor: PrototypeObjectDescriptor,
    checkpoint_id: str,
    now: datetime,
) -> PrototypeObjectReference:
    return PrototypeObjectReference(
        project_id=descriptor.project_id,
        owner_kind="checkpoint",
        owner_id=checkpoint_id,
        role="draft-checkpoint",
        content_hash=descriptor.content_hash,
        payload_type="prototype_document",
        schema_version=1,
        created_at=now,
    )


async def _create_initial_draft(
    tmp_path: Path,
    *,
    db_name: str = "structured.db",
) -> tuple[
    AsyncStructuredPrototypeStore,
    PrototypeObjectStore,
    PrototypeObjectDescriptor,
    PrototypeDocumentRecord,
    PrototypeDraftRecord,
]:
    now = datetime.now(UTC)
    object_store = PrototypeObjectStore(tmp_path / "managed-data")
    descriptor = object_store.write_json(
        "project-1",
        {"schemaVersion": 1, "id": "document-1", "pages": [{"id": "page-list"}]},
    )
    store = AsyncStructuredPrototypeStore(tmp_path / db_name)
    queued = _queued_operation(
        operation_id="operation-create-document",
        operation_kind="create_document",
        client_request_id="request-create-document",
        resource_kind="document",
        resource_id="document-1",
        now=now,
    )
    running, step = await _start_operation(
        store,
        queued,
        step_id="step-create-document",
        step_kind="persist_initial_checkpoint",
        now=now,
    )
    completed, completed_step, completed_event = _complete_operation(
        running,
        step,
        evidence_ref="checkpoint-0",
        event_no=2,
        now=now,
    )
    (
        completed,
        completed_step,
        completed_event,
        replay_descriptor,
        replay_reference,
    ) = _bind_strict_replay_manifest(
        object_store,
        completed,
        completed_step,
        completed_event,
    )
    document = PrototypeDocumentRecord(
        id="document-1",
        project_id="project-1",
        title="采购审批",
        published_revision_no=None,
        active_draft_id=DRAFT_ID,
        created_at=now,
        updated_at=now,
    )
    draft = PrototypeDraftRecord(
        id=DRAFT_ID,
        document_id=document.id,
        base_revision_no=None,
        status="active",
        head_sequence_no=0,
        head_document_hash=descriptor.content_hash,
        latest_checkpoint_id="checkpoint-0",
        publish_revision_no=None,
        created_at=now,
        updated_at=now,
        closed_at=None,
    )
    journal_prefix_hash = initial_journal_prefix_hash(draft_id=draft.id)
    history_payload = {
        "schemaVersion": COMMAND_HISTORY_CHECKPOINT_SCHEMA_VERSION,
        "draftId": draft.id,
        "checkpointSequenceNo": 0,
        "checkpointDocumentHash": descriptor.content_hash,
        "journalPrefixHash": journal_prefix_hash,
        "undoStack": [],
        "redoStack": [],
    }
    history_descriptor = object_store.write_json("project-1", history_payload)
    history_checkpoint = PrototypeCommandHistoryCheckpoint(
        draft_id=draft.id,
        checkpoint_sequence_no=0,
        checkpoint_document_hash=descriptor.content_hash,
        journal_prefix_hash=journal_prefix_hash,
        history=PrototypeCommandHistory(undo_stack=(), redo_stack=()),
        snapshot_object_hash=history_descriptor.content_hash,
        snapshot_schema_version=COMMAND_HISTORY_CHECKPOINT_SCHEMA_VERSION,
    )
    checkpoint = PrototypeCheckpointRecord(
        id="checkpoint-0",
        document_id=document.id,
        draft_id=draft.id,
        revision_id=None,
        checkpoint_kind="draft",
        checkpoint_sequence_no=0,
        document_object_hash=descriptor.content_hash,
        document_schema_version=1,
        command_contract_version=1,
        document_hash=descriptor.content_hash,
        history_snapshot_object_hash=history_descriptor.content_hash,
        history_snapshot_schema_version=COMMAND_HISTORY_CHECKPOINT_SCHEMA_VERSION,
        journal_prefix_hash=journal_prefix_hash,
        created_by_operation_id=completed.id,
        created_at=now,
    )
    history_reference = PrototypeObjectReference(
        project_id=history_descriptor.project_id,
        owner_kind="checkpoint",
        owner_id=checkpoint.id,
        role="command-history-checkpoint",
        content_hash=history_descriptor.content_hash,
        payload_type="prototype_command_history_checkpoint",
        schema_version=COMMAND_HISTORY_CHECKPOINT_SCHEMA_VERSION,
        created_at=now,
    )
    await store.create_document_with_initial_checkpoint(
        descriptor=descriptor,
        reference=_reference(descriptor, checkpoint.id, now),
        history_descriptor=history_descriptor,
        history_reference=history_reference,
        history_checkpoint=history_checkpoint,
        replay_descriptor=replay_descriptor,
        replay_reference=replay_reference,
        document=document,
        draft=draft,
        checkpoint=checkpoint,
        completed_operation=completed,
        completion_step=completed_step,
        completion_event=completed_event,
    )
    return store, object_store, descriptor, document, draft


async def _command_history_base(
    store: AsyncStructuredPrototypeStore,
    object_store: PrototypeObjectStore,
    draft_id: str,
) -> tuple[
    PrototypeCommandHistoryCheckpoint,
    tuple[PrototypeCommandBatchRecord, ...],
    str,
]:
    bundle = await store.load_draft_recovery_bundle(draft_id)
    payload = object_store.read_canonical_bytes(bundle.history_object_descriptor)
    history_checkpoint = command_history_checkpoint_to_domain(
        parse_command_history_checkpoint_json(payload),
        snapshot_object_hash=bundle.history_object_descriptor.content_hash,
    )
    prefix_hash = history_checkpoint.journal_prefix_hash
    for batch in bundle.command_batches:
        from app.adapters.structured_prototype_store import _advance_journal_prefix_hash

        prefix_hash = _advance_journal_prefix_hash(prefix_hash, batch)
    return history_checkpoint, bundle.command_batches, prefix_hash


async def _append_command(
    store: AsyncStructuredPrototypeStore,
    object_store: PrototypeObjectStore,
    *,
    batch: PrototypeCommandBatchRecord,
    completed_operation: PrototypeOperation,
    completion_step: PrototypeOperationStep,
    completion_event: PrototypeOperationEvent,
) -> PrototypeCommandAppendResult:
    history_checkpoint, tail, prefix_hash = await _command_history_base(
        store,
        object_store,
        batch.draft_id,
    )
    (
        completed_operation,
        completion_step,
        completion_event,
        replay_descriptor,
        replay_reference,
    ) = _bind_strict_replay_manifest(
        object_store,
        completed_operation,
        completion_step,
        completion_event,
    )
    return await store.append_command_batch(
        batch=batch,
        base_history_checkpoint=history_checkpoint,
        base_tail_batches=tail,
        base_journal_prefix_hash=prefix_hash,
        replay_descriptor=replay_descriptor,
        replay_reference=replay_reference,
        completed_operation=completed_operation,
        completion_step=completion_step,
        completion_event=completion_event,
    )


async def _materialize_history_checkpoint(
    store: AsyncStructuredPrototypeStore,
    object_store: PrototypeObjectStore,
    *,
    draft_id: str,
    checkpoint_id: str,
    checkpoint_sequence_no: int,
    checkpoint_document_hash: str,
    now: datetime,
) -> tuple[
    PrototypeObjectDescriptor,
    PrototypeObjectReference,
    PrototypeCommandHistoryCheckpoint,
]:
    base_history, tail, prefix_hash = await _command_history_base(
        store,
        object_store,
        draft_id,
    )
    history = fold_prototype_command_history(
        tail,
        initial_history=base_history.history,
        expected_base_sequence_no=base_history.checkpoint_sequence_no,
        expected_base_document_hash=base_history.checkpoint_document_hash,
    )
    payload = {
        "schemaVersion": COMMAND_HISTORY_CHECKPOINT_SCHEMA_VERSION,
        "draftId": draft_id,
        "checkpointSequenceNo": checkpoint_sequence_no,
        "checkpointDocumentHash": checkpoint_document_hash,
        "journalPrefixHash": prefix_hash,
        "undoStack": [entry.to_payload() for entry in history.undo_stack],
        "redoStack": [entry.to_payload() for entry in history.redo_stack],
    }
    descriptor = object_store.write_json("project-1", payload)
    checkpoint = PrototypeCommandHistoryCheckpoint(
        draft_id=draft_id,
        checkpoint_sequence_no=checkpoint_sequence_no,
        checkpoint_document_hash=checkpoint_document_hash,
        journal_prefix_hash=prefix_hash,
        history=history,
        snapshot_object_hash=descriptor.content_hash,
        snapshot_schema_version=COMMAND_HISTORY_CHECKPOINT_SCHEMA_VERSION,
    )
    reference = PrototypeObjectReference(
        project_id=descriptor.project_id,
        owner_kind="checkpoint",
        owner_id=checkpoint_id,
        role="command-history-checkpoint",
        content_hash=descriptor.content_hash,
        payload_type="prototype_command_history_checkpoint",
        schema_version=COMMAND_HISTORY_CHECKPOINT_SCHEMA_VERSION,
        created_at=now,
    )
    return descriptor, reference, checkpoint


async def _prepare_command(
    store: AsyncStructuredPrototypeStore,
    *,
    operation_id: str,
    client_request_id: str,
    batch_id: str,
    base_sequence_no: int,
    base_hash: str,
    result_hash: str,
    now: datetime,
) -> tuple[
    PrototypeCommandBatchRecord,
    PrototypeOperation,
    PrototypeOperationStep,
    PrototypeOperationEvent,
]:
    queued = _queued_operation(
        operation_id=operation_id,
        operation_kind="apply_command_batch",
        client_request_id=client_request_id,
        resource_kind="draft",
        resource_id=DRAFT_ID,
        now=now,
    )
    running, step = await _start_operation(
        store,
        queued,
        step_id=f"step-{operation_id}",
        step_kind="commit_command_batch",
        now=now,
    )
    completed, completed_step, completed_event = _complete_operation(
        running,
        step,
        evidence_ref=batch_id,
        event_no=2,
        now=now,
    )
    batch = PrototypeCommandBatchRecord(
        id=batch_id,
        draft_id=DRAFT_ID,
        base_sequence_no=base_sequence_no,
        result_sequence_no=base_sequence_no + 1,
        client_request_id=client_request_id,
        origin="user",
        operation_kind="forward",
        target_batch_id=None,
        command_contract_version=1,
        commands_json='{"commandContractVersion":1,"commands":[{"kind":"reorderPage"}]}',
        inverse_commands_json='{"commandContractVersion":1,"commands":[{"kind":"reorderPage"}]}',
        command_batch_hash=_hash("d"),
        base_document_hash=base_hash,
        result_document_hash=result_hash,
        operation_id=operation_id,
        created_at=now,
    )
    return batch, completed, completed_step, completed_event


async def _prepare_history_command(
    store: AsyncStructuredPrototypeStore,
    *,
    operation_kind: Literal["undo", "redo"],
    operation_id: str,
    client_request_id: str,
    batch_id: str,
    target_batch_id: str,
    base_sequence_no: int,
    commands_json: str,
    inverse_commands_json: str,
    base_hash: str,
    result_hash: str,
    now: datetime,
) -> tuple[
    PrototypeCommandBatchRecord,
    PrototypeOperation,
    PrototypeOperationStep,
    PrototypeOperationEvent,
]:
    queued = _queued_operation(
        operation_id=operation_id,
        operation_kind=operation_kind,
        client_request_id=client_request_id,
        resource_kind="draft",
        resource_id=DRAFT_ID,
        now=now,
    )
    running, step = await _start_operation(
        store,
        queued,
        step_id=f"step-{operation_id}",
        step_kind=f"commit_{operation_kind}_command_batch",
        now=now,
    )
    completed, completed_step, completed_event = _complete_operation(
        running,
        step,
        evidence_ref=batch_id,
        event_no=2,
        now=now,
    )
    batch = PrototypeCommandBatchRecord(
        id=batch_id,
        draft_id=DRAFT_ID,
        base_sequence_no=base_sequence_no,
        result_sequence_no=base_sequence_no + 1,
        client_request_id=client_request_id,
        origin="user",
        operation_kind=operation_kind,
        target_batch_id=target_batch_id,
        command_contract_version=1,
        commands_json=commands_json,
        inverse_commands_json=inverse_commands_json,
        command_batch_hash=_hash("d"),
        base_document_hash=base_hash,
        result_document_hash=result_hash,
        operation_id=operation_id,
        created_at=now,
    )
    return batch, completed, completed_step, completed_event


def _runtime_reference(
    descriptor: PrototypeObjectDescriptor,
    checkpoint_id: str,
    now: datetime,
) -> PrototypeObjectReference:
    return PrototypeObjectReference(
        project_id=descriptor.project_id,
        owner_kind="runtime_checkpoint",
        owner_id=checkpoint_id,
        role="runtime-state-checkpoint",
        content_hash=descriptor.content_hash,
        payload_type="prototype_runtime_state",
        schema_version=1,
        created_at=now,
    )


async def _create_initial_runtime_session(
    tmp_path: Path,
) -> tuple[
    AsyncStructuredPrototypeStore,
    PrototypeObjectStore,
    PrototypeObjectDescriptor,
    PrototypeRuntimeSessionRecord,
    PrototypeRuntimeCheckpointRecord,
]:
    store, object_store, document_descriptor, document, draft = await _create_initial_draft(
        tmp_path
    )
    now = datetime.now(UTC)
    state_descriptor = object_store.write_json(
        "project-1",
        {
            "runtimeStateSchemaVersion": 1,
            "runtimeCoreVersion": RUNTIME_CORE_VERSION,
            "sessionId": "runtime-session-1",
            "sequenceNo": 0,
        },
    )
    queued = _queued_operation(
        operation_id="operation-runtime-session-1",
        operation_kind="create_runtime_session",
        client_request_id="request-runtime-session-1",
        resource_kind="runtime_session",
        resource_id="runtime-session-1",
        now=now,
    )
    running, running_step = await _start_operation(
        store,
        queued,
        step_id="step-runtime-session-1",
        step_kind="persist_runtime_checkpoint",
        now=now,
    )
    completed, step, event = _complete_operation(
        running,
        running_step,
        evidence_ref="runtime-checkpoint-0",
        event_no=2,
        now=now,
    )
    completed, step, event, replay_descriptor, replay_reference = _bind_strict_replay_manifest(
        object_store,
        completed,
        step,
        event,
    )
    session = PrototypeRuntimeSessionRecord(
        id="runtime-session-1",
        project_id=document.project_id,
        document_id=document.id,
        source_kind="draft",
        source_id=draft.id,
        pinned_document_object_hash=document_descriptor.content_hash,
        runtime_core_version=RUNTIME_CORE_VERSION,
        runtime_core_bundle_hash=RUNTIME_CORE_BUNDLE_HASH,
        state_machine_kernel_version=STATE_MACHINE_KERNEL_VERSION,
        scenario_id="scenario-procurement-happy-path",
        scenario_hash=_hash("7"),
        status="active",
        head_sequence_no=0,
        head_state_hash=state_descriptor.content_hash,
        head_view_model_hash=_hash("9"),
        latest_checkpoint_id="runtime-checkpoint-0",
        recording_kind="studio_preview",
        allow_simulated_role_switch=True,
        actor_subject_id="product-manager-1",
        created_at=now,
        updated_at=now,
        completed_at=None,
    )
    checkpoint = PrototypeRuntimeCheckpointRecord(
        id="runtime-checkpoint-0",
        session_id=session.id,
        checkpoint_sequence_no=0,
        state_object_hash=state_descriptor.content_hash,
        runtime_state_schema_version=1,
        runtime_event_contract_version=1,
        state_hash=state_descriptor.content_hash,
        view_model_hash=session.head_view_model_hash,
        created_by_operation_id=completed.id,
        created_at=now,
    )
    await store.create_runtime_session_with_initial_checkpoint(
        descriptor=state_descriptor,
        reference=_runtime_reference(state_descriptor, checkpoint.id, now),
        replay_descriptor=replay_descriptor,
        replay_reference=replay_reference,
        session=session,
        checkpoint=checkpoint,
        completed_operation=completed,
        completion_step=step,
        completion_event=event,
    )
    return store, object_store, state_descriptor, session, checkpoint


async def _prepare_runtime_event(
    store: AsyncStructuredPrototypeStore,
    *,
    operation_id: str,
    client_event_id: str,
    event_batch_id: str,
    base_sequence_no: int,
    base_state_hash: str,
    result_state_hash: str,
    result_view_model_hash: str,
    now: datetime,
    runtime_core_version: str = RUNTIME_CORE_VERSION,
) -> tuple[
    PrototypeRuntimeEventBatchRecord,
    PrototypeOperation,
    PrototypeOperationStep,
    PrototypeOperationEvent,
]:
    queued = _queued_operation(
        operation_id=operation_id,
        operation_kind="apply_runtime_event",
        client_request_id=f"request-{client_event_id}",
        resource_kind="runtime_session",
        resource_id="runtime-session-1",
        now=now,
    )
    running, running_step = await _start_operation(
        store,
        queued,
        step_id=f"step-{operation_id}",
        step_kind="commit_runtime_event",
        now=now,
    )
    completed, step, event = _complete_operation(
        running,
        running_step,
        evidence_ref=event_batch_id,
        event_no=2,
        now=now,
    )
    event_batch = PrototypeRuntimeEventBatchRecord(
        id=event_batch_id,
        session_id="runtime-session-1",
        client_event_id=client_event_id,
        base_sequence_no=base_sequence_no,
        result_sequence_no=base_sequence_no + 1,
        events_json='[{"kind":"click","nodeId":"approve-button"}]',
        event_batch_hash=_hash("d"),
        matched_rule_ids_json='["approve-purchase"]',
        guard_report_hash=_hash("a"),
        effect_report_hash=_hash("b"),
        outcome="applied",
        base_state_hash=base_state_hash,
        result_state_hash=result_state_hash,
        result_view_model_hash=result_view_model_hash,
        runtime_core_version=runtime_core_version,
        runtime_core_bundle_hash=RUNTIME_CORE_BUNDLE_HASH,
        state_machine_kernel_version=STATE_MACHINE_KERNEL_VERSION,
        operation_id=operation_id,
        created_at=now,
    )
    return event_batch, completed, step, event


async def _prepare_runtime_checkpoint(
    store: AsyncStructuredPrototypeStore,
    *,
    descriptor: PrototypeObjectDescriptor,
    sequence_no: int,
    view_model_hash: str,
    now: datetime,
) -> tuple[
    PrototypeRuntimeCheckpointRecord,
    PrototypeObjectReference,
    PrototypeOperation,
    PrototypeOperationStep,
    PrototypeOperationEvent,
]:
    checkpoint_id = f"runtime-checkpoint-{sequence_no}"
    operation_id = f"operation-runtime-checkpoint-{sequence_no}"
    queued = _queued_operation(
        operation_id=operation_id,
        operation_kind="create_checkpoint",
        client_request_id=f"request-runtime-checkpoint-{sequence_no}",
        resource_kind="runtime_session",
        resource_id="runtime-session-1",
        now=now,
    )
    running, running_step = await _start_operation(
        store,
        queued,
        step_id=f"step-{operation_id}",
        step_kind="register_runtime_checkpoint",
        now=now,
    )
    completed, step, event = _complete_operation(
        running,
        running_step,
        evidence_ref=checkpoint_id,
        event_no=2,
        now=now,
    )
    checkpoint = PrototypeRuntimeCheckpointRecord(
        id=checkpoint_id,
        session_id="runtime-session-1",
        checkpoint_sequence_no=sequence_no,
        state_object_hash=descriptor.content_hash,
        runtime_state_schema_version=1,
        runtime_event_contract_version=1,
        state_hash=descriptor.content_hash,
        view_model_hash=view_model_hash,
        created_by_operation_id=completed.id,
        created_at=now,
    )
    return (
        checkpoint,
        _runtime_reference(descriptor, checkpoint_id, now),
        completed,
        step,
        event,
    )


async def _append_runtime_event(
    store: AsyncStructuredPrototypeStore,
    object_store: PrototypeObjectStore,
    *,
    event_batch: PrototypeRuntimeEventBatchRecord,
    completed_operation: PrototypeOperation,
    completion_step: PrototypeOperationStep,
    completion_event: PrototypeOperationEvent,
) -> PrototypeRuntimeEventAppendResult:
    (
        completed_operation,
        completion_step,
        completion_event,
        replay_descriptor,
        replay_reference,
    ) = _bind_strict_replay_manifest(
        object_store,
        completed_operation,
        completion_step,
        completion_event,
    )
    return await store.append_runtime_event_batch(
        event_batch=event_batch,
        replay_descriptor=replay_descriptor,
        replay_reference=replay_reference,
        completed_operation=completed_operation,
        completion_step=completion_step,
        completion_event=completion_event,
    )


async def _register_runtime_checkpoint(
    store: AsyncStructuredPrototypeStore,
    object_store: PrototypeObjectStore,
    *,
    descriptor: PrototypeObjectDescriptor,
    reference: PrototypeObjectReference,
    checkpoint: PrototypeRuntimeCheckpointRecord,
    completed_operation: PrototypeOperation,
    completion_step: PrototypeOperationStep,
    completion_event: PrototypeOperationEvent,
) -> PrototypeRuntimeSessionRecord:
    (
        completed_operation,
        completion_step,
        completion_event,
        replay_descriptor,
        replay_reference,
    ) = _bind_strict_replay_manifest(
        object_store,
        completed_operation,
        completion_step,
        completion_event,
    )
    return await store.register_runtime_checkpoint(
        descriptor=descriptor,
        reference=reference,
        checkpoint=checkpoint,
        replay_descriptor=replay_descriptor,
        replay_reference=replay_reference,
        completed_operation=completed_operation,
        completion_step=completion_step,
        completion_event=completion_event,
    )


def test_complete_command_history_folds_undo_redo_and_forward_branching() -> None:
    now = datetime.now(UTC)

    def record(
        batch_id: str,
        sequence_no: int,
        operation_kind: Literal["forward", "undo", "redo"],
        target_batch_id: str | None,
        base_hash: str,
        result_hash: str,
    ) -> PrototypeCommandBatchRecord:
        return PrototypeCommandBatchRecord(
            id=batch_id,
            draft_id=DRAFT_ID,
            base_sequence_no=sequence_no - 1,
            result_sequence_no=sequence_no,
            client_request_id=f"request-{batch_id}",
            origin="user",
            operation_kind=operation_kind,
            target_batch_id=target_batch_id,
            command_contract_version=1,
            commands_json="commands",
            inverse_commands_json="inverse",
            command_batch_hash=_hash("d"),
            base_document_hash=base_hash,
            result_document_hash=result_hash,
            operation_id=f"operation-{batch_id}",
            created_at=now,
        )

    first = record("first", 1, "forward", None, _hash("1"), _hash("2"))
    second = record("second", 2, "forward", None, _hash("2"), _hash("3"))
    undo_second = record("undo-second", 3, "undo", second.id, _hash("3"), _hash("2"))
    redo_second = record(
        "redo-second",
        4,
        "redo",
        undo_second.id,
        _hash("2"),
        _hash("3"),
    )

    undone = fold_prototype_command_history((first, second, undo_second))
    assert [entry.batch_id for entry in undone.undo_stack] == [first.id]
    assert [entry.batch_id for entry in undone.redo_stack] == [undo_second.id]

    redone = advance_prototype_command_history(undone, redo_second)
    assert [entry.batch_id for entry in redone.undo_stack] == [first.id, redo_second.id]
    assert redone.redo_stack == ()

    branch = record("branch", 4, "forward", None, _hash("2"), _hash("4"))
    branched = advance_prototype_command_history(undone, branch)
    assert [entry.batch_id for entry in branched.undo_stack] == [first.id, branch.id]
    assert branched.redo_stack == ()


@pytest.mark.asyncio
async def test_initial_checkpoint_and_command_recover_as_one_durable_chain(
    tmp_path: Path,
) -> None:
    store, object_store, initial, document, draft = await _create_initial_draft(tmp_path)
    now = datetime.now(UTC)
    updated = object_store.write_json(
        "project-1",
        {"schemaVersion": 1, "id": "document-1", "pages": [{"id": "page-create"}]},
    )
    batch, operation, step, event = await _prepare_command(
        store,
        operation_id="operation-command-1",
        client_request_id="request-command-1",
        batch_id="batch-1",
        base_sequence_no=0,
        base_hash=initial.content_hash,
        result_hash=updated.content_hash,
        now=now,
    )

    try:
        appended = await _append_command(
            store,
            object_store,
            batch=batch,
            completed_operation=operation,
            completion_step=step,
            completion_event=event,
        )
        recovered = await store.load_draft_recovery_bundle(draft.id)

        assert appended.created
        assert appended.draft.head_sequence_no == 1
        assert appended.draft.head_document_hash == updated.content_hash
        assert recovered.document == document
        assert recovered.checkpoint.document_object_hash == initial.content_hash
        assert recovered.object_descriptor == initial
        assert recovered.command_batches == (batch,)
        assert [item.event_no for item in await store.list_operation_events(operation.id)] == [
            0,
            1,
            2,
        ]
        persisted_operation = await store.load_operation(operation.id)
        assert persisted_operation is not None
        assert persisted_operation.status == "succeeded"
        replay_references = await store.list_object_references(
            "project-1",
            "replay_manifest",
            operation.id,
        )
        assert len(replay_references) == 1
        assert persisted_operation.result_manifest_hash == replay_references[0].content_hash
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_command_retry_returns_original_result_without_new_event(tmp_path: Path) -> None:
    store, object_store, initial, _, _ = await _create_initial_draft(tmp_path)
    updated = object_store.write_json("project-1", {"schemaVersion": 1, "revision": 1})
    now = datetime.now(UTC)
    batch, operation, step, event = await _prepare_command(
        store,
        operation_id="operation-command-retry",
        client_request_id="request-command-retry",
        batch_id="batch-retry",
        base_sequence_no=0,
        base_hash=initial.content_hash,
        result_hash=updated.content_hash,
        now=now,
    )

    try:
        first = await _append_command(
            store,
            object_store,
            batch=batch,
            completed_operation=operation,
            completion_step=step,
            completion_event=event,
        )
        second = await _append_command(
            store,
            object_store,
            batch=replace(batch, created_at=datetime.now(UTC)),
            completed_operation=operation,
            completion_step=step,
            completion_event=event,
        )

        assert first.created
        assert not second.created
        assert second.batch == batch
        assert (
            await store.load_command_batch_by_request(batch.draft_id, batch.client_request_id)
            == batch
        )
        assert len(await store.list_operation_events(operation.id)) == 3
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_recovery_failure_marks_the_same_draft_head_corrupt_with_evidence(
    tmp_path: Path,
) -> None:
    store, _, initial, _, draft = await _create_initial_draft(tmp_path)
    now = datetime.now(UTC)
    queued = _queued_operation(
        operation_id="operation-recovery-failed",
        operation_kind="recover_draft",
        client_request_id="request-recovery-failed",
        resource_kind="draft",
        resource_id=draft.id,
        now=now,
    )
    running, step = await _start_operation(
        store,
        queued,
        step_id="step-recovery-failed",
        step_kind="replay_command_tail",
        now=now,
    )
    failed, failed_step, event = _fail_operation(
        running,
        step,
        error_code="object_hash_mismatch",
        now=now,
    )

    try:
        corrupted = await store.mark_draft_corrupt(
            draft_id=draft.id,
            expected_head_sequence_no=0,
            expected_document_hash=initial.content_hash,
            failed_operation=failed,
            failed_step=failed_step,
            failure_event=event,
        )

        assert corrupted.status == "corrupt"
        assert [item.status for item in await store.list_operation_events(failed.id)] == [
            "queued",
            "running",
            "failed",
        ]
        persisted = await store.load_operation(failed.id)
        assert persisted is not None
        assert persisted.error_code == "object_hash_mismatch"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_two_connections_cannot_append_the_same_draft_head(tmp_path: Path) -> None:
    first_store, object_store, initial, _, _ = await _create_initial_draft(tmp_path)
    second_store = AsyncStructuredPrototypeStore(tmp_path / "structured.db")
    now = datetime.now(UTC)
    first_result = object_store.write_json("project-1", {"schemaVersion": 1, "winner": 1})
    second_result = object_store.write_json("project-1", {"schemaVersion": 1, "winner": 2})
    first = await _prepare_command(
        first_store,
        operation_id="operation-race-1",
        client_request_id="request-race-1",
        batch_id="batch-race-1",
        base_sequence_no=0,
        base_hash=initial.content_hash,
        result_hash=first_result.content_hash,
        now=now,
    )
    second = await _prepare_command(
        second_store,
        operation_id="operation-race-2",
        client_request_id="request-race-2",
        batch_id="batch-race-2",
        base_sequence_no=0,
        base_hash=initial.content_hash,
        result_hash=second_result.content_hash,
        now=now,
    )

    async def append(
        store: AsyncStructuredPrototypeStore,
        prepared: tuple[
            PrototypeCommandBatchRecord,
            PrototypeOperation,
            PrototypeOperationStep,
            PrototypeOperationEvent,
        ],
    ) -> str:
        batch, operation, step, event = prepared
        try:
            await _append_command(
                store,
                object_store,
                batch=batch,
                completed_operation=operation,
                completion_step=step,
                completion_event=event,
            )
        except StructuredPrototypeStoreError as error:
            return error.code
        return "created"

    try:
        outcomes = await asyncio.gather(
            append(first_store, first),
            append(second_store, second),
        )
        assert sorted(outcomes) == ["created", "draft_conflict"]
        persisted = await first_store.load_draft(DRAFT_ID)
        assert persisted is not None
        assert persisted.head_sequence_no == 1
    finally:
        await first_store.close()
        await second_store.close()


@pytest.mark.asyncio
async def test_store_rejects_an_undo_target_that_is_not_the_transactional_stack_top(
    tmp_path: Path,
) -> None:
    store, object_store, initial, _, draft = await _create_initial_draft(tmp_path)
    now = datetime.now(UTC)
    first_result = object_store.write_json("project-1", {"sequence": 1})
    second_result = object_store.write_json("project-1", {"sequence": 2})
    first = await _prepare_command(
        store,
        operation_id="operation-history-first",
        client_request_id="request-history-first",
        batch_id="batch-history-first",
        base_sequence_no=0,
        base_hash=initial.content_hash,
        result_hash=first_result.content_hash,
        now=now,
    )
    await _append_command(
        store,
        object_store,
        batch=first[0],
        completed_operation=first[1],
        completion_step=first[2],
        completion_event=first[3],
    )
    second = await _prepare_command(
        store,
        operation_id="operation-history-second",
        client_request_id="request-history-second",
        batch_id="batch-history-second",
        base_sequence_no=1,
        base_hash=first_result.content_hash,
        result_hash=second_result.content_hash,
        now=now,
    )
    await _append_command(
        store,
        object_store,
        batch=second[0],
        completed_operation=second[1],
        completion_step=second[2],
        completion_event=second[3],
    )
    stale = await _prepare_history_command(
        store,
        operation_kind="undo",
        operation_id="operation-history-stale-undo",
        client_request_id="request-history-stale-undo",
        batch_id="batch-history-stale-undo",
        target_batch_id=first[0].id,
        base_sequence_no=2,
        commands_json=first[0].inverse_commands_json,
        inverse_commands_json=first[0].commands_json,
        base_hash=second_result.content_hash,
        result_hash=initial.content_hash,
        now=now,
    )

    try:
        with pytest.raises(StructuredPrototypeStoreError) as error:
            await _append_command(
                store,
                object_store,
                batch=stale[0],
                completed_operation=stale[1],
                completion_step=stale[2],
                completion_event=stale[3],
            )

        assert error.value.code == "command_history_conflict"
        current = await store.load_draft(draft.id)
        assert current is not None
        assert current.head_sequence_no == 2
        assert current.head_document_hash == second_result.content_hash
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_replay_tail_limit_refuses_batch_before_the_201st_tail_entry(
    tmp_path: Path,
) -> None:
    store, object_store, initial, _, _ = await _create_initial_draft(tmp_path)
    base_history, base_tail, base_prefix_hash = await _command_history_base(
        store,
        object_store,
        DRAFT_ID,
    )
    conn = await store._get_conn()
    await conn.execute(
        "UPDATE prototype_drafts SET head_sequence_no = ?, head_document_hash = ? WHERE id = ?",
        (MAX_REPLAY_TAIL_BATCHES, _hash("e"), DRAFT_ID),
    )
    await conn.commit()
    batch, operation, step, event = await _prepare_command(
        store,
        operation_id="operation-tail-limit",
        client_request_id="request-tail-limit",
        batch_id="batch-tail-limit",
        base_sequence_no=MAX_REPLAY_TAIL_BATCHES,
        base_hash=_hash("e"),
        result_hash=_hash("f"),
        now=datetime.now(UTC),
    )
    assert initial.content_hash != _hash("e")
    operation, step, event, replay_descriptor, replay_reference = _bind_strict_replay_manifest(
        object_store,
        operation,
        step,
        event,
    )

    try:
        with pytest.raises(StructuredPrototypeStoreError) as error:
            await store.append_command_batch(
                batch=batch,
                base_history_checkpoint=base_history,
                base_tail_batches=base_tail,
                base_journal_prefix_hash=base_prefix_hash,
                replay_descriptor=replay_descriptor,
                replay_reference=replay_reference,
                completed_operation=operation,
                completion_step=step,
                completion_event=event,
            )

        assert error.value.code == "checkpoint_required_unavailable"
        events = await store.list_operation_events(operation.id)
        assert [item.event_no for item in events] == [0, 1]
        assert events[-1].status == "running"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_checkpoint_head_conflict_rolls_back_object_reference(tmp_path: Path) -> None:
    store, object_store, _, document, draft = await _create_initial_draft(tmp_path)
    descriptor = object_store.write_json("project-1", {"schemaVersion": 1, "stale": True})
    now = datetime.now(UTC)
    queued = _queued_operation(
        operation_id="operation-stale-checkpoint",
        operation_kind="create_checkpoint",
        client_request_id="request-stale-checkpoint",
        resource_kind="draft",
        resource_id=draft.id,
        now=now,
    )
    running, running_step = await _start_operation(
        store,
        queued,
        step_id="step-stale-checkpoint",
        step_kind="register_checkpoint",
        now=now,
    )
    completed, step, event = _complete_operation(
        running,
        running_step,
        evidence_ref="checkpoint-stale",
        event_no=2,
        now=now,
    )
    completed, step, event, replay_descriptor, replay_reference = _bind_strict_replay_manifest(
        object_store,
        completed,
        step,
        event,
    )
    (
        history_descriptor,
        history_reference,
        history_checkpoint,
    ) = await _materialize_history_checkpoint(
        store,
        object_store,
        draft_id=draft.id,
        checkpoint_id="checkpoint-stale",
        checkpoint_sequence_no=1,
        checkpoint_document_hash=descriptor.content_hash,
        now=now,
    )
    checkpoint = PrototypeCheckpointRecord(
        id="checkpoint-stale",
        document_id=document.id,
        draft_id=draft.id,
        revision_id=None,
        checkpoint_kind="draft",
        checkpoint_sequence_no=1,
        document_object_hash=descriptor.content_hash,
        document_schema_version=1,
        command_contract_version=1,
        document_hash=descriptor.content_hash,
        history_snapshot_object_hash=history_descriptor.content_hash,
        history_snapshot_schema_version=COMMAND_HISTORY_CHECKPOINT_SCHEMA_VERSION,
        journal_prefix_hash=history_checkpoint.journal_prefix_hash,
        created_by_operation_id=completed.id,
        created_at=now,
    )

    try:
        with pytest.raises(StructuredPrototypeStoreError) as error:
            await store.register_draft_checkpoint(
                descriptor=descriptor,
                reference=_reference(descriptor, checkpoint.id, now),
                history_descriptor=history_descriptor,
                history_reference=history_reference,
                history_checkpoint=history_checkpoint,
                checkpoint=checkpoint,
                replay_descriptor=replay_descriptor,
                replay_reference=replay_reference,
                completed_operation=completed,
                completion_step=step,
                completion_event=event,
            )

        assert error.value.code == "checkpoint_head_conflict"
        assert await store.load_object("project-1", descriptor.content_hash) is None
        assert await store.list_object_references("project-1", "checkpoint", checkpoint.id) == []
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_successful_checkpoint_resets_the_recovery_tail(tmp_path: Path) -> None:
    store, object_store, initial, document, draft = await _create_initial_draft(tmp_path)
    updated = object_store.write_json("project-1", {"schemaVersion": 1, "checkpoint": 1})
    now = datetime.now(UTC)
    batch, operation, step, event = await _prepare_command(
        store,
        operation_id="operation-before-checkpoint",
        client_request_id="request-before-checkpoint",
        batch_id="batch-before-checkpoint",
        base_sequence_no=0,
        base_hash=initial.content_hash,
        result_hash=updated.content_hash,
        now=now,
    )
    await _append_command(
        store,
        object_store,
        batch=batch,
        completed_operation=operation,
        completion_step=step,
        completion_event=event,
    )
    queued = _queued_operation(
        operation_id="operation-checkpoint-1",
        operation_kind="create_checkpoint",
        client_request_id="request-checkpoint-1",
        resource_kind="draft",
        resource_id=draft.id,
        now=now,
    )
    running, running_step = await _start_operation(
        store,
        queued,
        step_id="step-checkpoint-1",
        step_kind="register_checkpoint",
        now=now,
    )
    completed, checkpoint_step, checkpoint_event = _complete_operation(
        running,
        running_step,
        evidence_ref="checkpoint-1",
        event_no=2,
        now=now,
    )
    (
        completed,
        checkpoint_step,
        checkpoint_event,
        replay_descriptor,
        replay_reference,
    ) = _bind_strict_replay_manifest(
        object_store,
        completed,
        checkpoint_step,
        checkpoint_event,
    )
    (
        history_descriptor,
        history_reference,
        history_checkpoint,
    ) = await _materialize_history_checkpoint(
        store,
        object_store,
        draft_id=draft.id,
        checkpoint_id="checkpoint-1",
        checkpoint_sequence_no=1,
        checkpoint_document_hash=updated.content_hash,
        now=now,
    )
    checkpoint = PrototypeCheckpointRecord(
        id="checkpoint-1",
        document_id=document.id,
        draft_id=draft.id,
        revision_id=None,
        checkpoint_kind="draft",
        checkpoint_sequence_no=1,
        document_object_hash=updated.content_hash,
        document_schema_version=1,
        command_contract_version=1,
        document_hash=updated.content_hash,
        history_snapshot_object_hash=history_descriptor.content_hash,
        history_snapshot_schema_version=COMMAND_HISTORY_CHECKPOINT_SCHEMA_VERSION,
        journal_prefix_hash=history_checkpoint.journal_prefix_hash,
        created_by_operation_id=completed.id,
        created_at=now,
    )

    try:
        checkpointed = await store.register_draft_checkpoint(
            descriptor=updated,
            reference=_reference(updated, checkpoint.id, now),
            history_descriptor=history_descriptor,
            history_reference=history_reference,
            history_checkpoint=history_checkpoint,
            checkpoint=checkpoint,
            replay_descriptor=replay_descriptor,
            replay_reference=replay_reference,
            completed_operation=completed,
            completion_step=checkpoint_step,
            completion_event=checkpoint_event,
        )
        recovered = await store.load_draft_recovery_bundle(draft.id)

        assert checkpointed.latest_checkpoint_id == checkpoint.id
        assert recovered.checkpoint == checkpoint
        assert recovered.object_descriptor == updated
        assert recovered.command_batches == ()
        assert await store.list_object_references("project-1", "checkpoint", checkpoint.id) == [
            history_reference,
            _reference(updated, checkpoint.id, now),
        ]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_recovery_rejects_a_missing_middle_command_sequence(tmp_path: Path) -> None:
    store, object_store, initial, _, draft = await _create_initial_draft(tmp_path)
    now = datetime.now(UTC)
    first_result = object_store.write_json("project-1", {"schemaVersion": 1, "sequence": 1})
    second_result = object_store.write_json("project-1", {"schemaVersion": 1, "sequence": 2})
    first = await _prepare_command(
        store,
        operation_id="operation-gap-1",
        client_request_id="request-gap-1",
        batch_id="batch-gap-1",
        base_sequence_no=0,
        base_hash=initial.content_hash,
        result_hash=first_result.content_hash,
        now=now,
    )
    second = await _prepare_command(
        store,
        operation_id="operation-gap-2",
        client_request_id="request-gap-2",
        batch_id="batch-gap-2",
        base_sequence_no=1,
        base_hash=first_result.content_hash,
        result_hash=second_result.content_hash,
        now=now,
    )
    for prepared in (first, second):
        batch, operation, step, event = prepared
        await _append_command(
            store,
            object_store,
            batch=batch,
            completed_operation=operation,
            completion_step=step,
            completion_event=event,
        )
    conn = await store._get_conn()
    await conn.execute("DELETE FROM prototype_command_batches WHERE id = ?", ("batch-gap-1",))
    await conn.commit()

    try:
        with pytest.raises(StructuredPrototypeStoreError) as error:
            await store.load_draft_recovery_bundle(draft.id)

        assert error.value.code == "replay_sequence_gap"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_runtime_session_initial_checkpoint_is_one_recoverable_transaction(
    tmp_path: Path,
) -> None:
    store, _, state_descriptor, session, checkpoint = await _create_initial_runtime_session(
        tmp_path
    )

    try:
        loaded = await store.load_runtime_session(session.id)
        recovered = await store.load_runtime_recovery_bundle(session.id)

        assert loaded == session
        assert recovered.session == session
        assert recovered.checkpoint == checkpoint
        assert recovered.object_descriptor == state_descriptor
        assert recovered.event_batches == ()
        assert await store.list_object_references(
            "project-1", "runtime_checkpoint", checkpoint.id
        ) == [_runtime_reference(state_descriptor, checkpoint.id, checkpoint.created_at)]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_runtime_session_replacement_column_migrates_existing_row_before_index(
    tmp_path: Path,
) -> None:
    store, _, _, session, _ = await _create_initial_runtime_session(tmp_path)
    db_path = tmp_path / "structured.db"
    await store.close()
    with sqlite3.connect(db_path) as legacy_conn:
        legacy_conn.execute("DROP INDEX idx_prototype_runtime_sessions_replaces_session")
        legacy_conn.execute(
            "ALTER TABLE prototype_runtime_sessions DROP COLUMN replaces_session_id"
        )
        legacy_conn.commit()

    migrated = AsyncStructuredPrototypeStore(db_path)
    try:
        loaded = await migrated.load_runtime_session(session.id)
        migrated_conn = await migrated._get_conn()
        columns = {
            str(row[1])
            for row in await (
                await migrated_conn.execute("PRAGMA table_info(prototype_runtime_sessions)")
            ).fetchall()
        }
        index_row = await (
            await migrated_conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
                ("idx_prototype_runtime_sessions_replaces_session",),
            )
        ).fetchone()

        assert loaded is not None
        assert loaded.id == session.id
        assert loaded.head_state_hash == session.head_state_hash
        assert loaded.replaces_session_id is None
        assert "replaces_session_id" in columns
        assert index_row is not None
        assert "WHERE replaces_session_id IS NOT NULL" in str(index_row[0])
    finally:
        await migrated.close()


@pytest.mark.asyncio
async def test_runtime_initial_checkpoint_failure_rolls_back_session_and_object(
    tmp_path: Path,
) -> None:
    (
        store,
        object_store,
        _,
        existing_session,
        existing_checkpoint,
    ) = await _create_initial_runtime_session(tmp_path)
    now = datetime.now(UTC)
    state_descriptor = object_store.write_json(
        "project-1",
        {"runtimeStateSchemaVersion": 1, "sessionId": "runtime-session-2"},
    )
    queued = _queued_operation(
        operation_id="operation-runtime-session-rollback",
        operation_kind="create_runtime_session",
        client_request_id="request-runtime-session-rollback",
        resource_kind="runtime_session",
        resource_id="runtime-session-2",
        now=now,
    )
    running, running_step = await _start_operation(
        store,
        queued,
        step_id="step-runtime-session-rollback",
        step_kind="persist_runtime_checkpoint",
        now=now,
    )
    completed, step, event = _complete_operation(
        running,
        running_step,
        evidence_ref=existing_checkpoint.id,
        event_no=2,
        now=now,
    )
    completed, step, event, replay_descriptor, replay_reference = _bind_strict_replay_manifest(
        object_store,
        completed,
        step,
        event,
    )
    session = replace(
        existing_session,
        id="runtime-session-2",
        source_id=DRAFT_ID,
        head_state_hash=state_descriptor.content_hash,
        latest_checkpoint_id=existing_checkpoint.id,
        created_at=now,
        updated_at=now,
    )
    checkpoint = replace(
        existing_checkpoint,
        session_id=session.id,
        state_object_hash=state_descriptor.content_hash,
        state_hash=state_descriptor.content_hash,
        view_model_hash=session.head_view_model_hash,
        created_by_operation_id=completed.id,
        created_at=now,
    )

    try:
        with pytest.raises(aiosqlite.IntegrityError):
            await store.create_runtime_session_with_initial_checkpoint(
                descriptor=state_descriptor,
                reference=_runtime_reference(state_descriptor, checkpoint.id, now),
                replay_descriptor=replay_descriptor,
                replay_reference=replay_reference,
                session=session,
                checkpoint=checkpoint,
                completed_operation=completed,
                completion_step=step,
                completion_event=event,
            )

        assert await store.load_runtime_session(session.id) is None
        assert await store.load_object("project-1", state_descriptor.content_hash) is None
        references = await store.list_object_references(
            "project-1", "runtime_checkpoint", checkpoint.id
        )
        assert all(
            reference.content_hash != state_descriptor.content_hash for reference in references
        )
        persisted_operation = await store.load_operation(completed.id)
        assert persisted_operation is not None
        assert persisted_operation.status == "running"
    finally:
        await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_at", ("before_commit", "commit"))
async def test_runtime_reset_cancellation_rolls_back_and_releases_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancel_at: Literal["before_commit", "commit"],
) -> None:
    (
        store,
        object_store,
        _,
        old_session,
        old_checkpoint,
    ) = await _create_initial_runtime_session(tmp_path)
    now = datetime.now(UTC)
    new_session_id = "runtime-session-reset-cancelled"
    new_checkpoint_id = "runtime-checkpoint-reset-cancelled"
    state_descriptor = object_store.write_json(
        "project-1",
        {
            "runtimeStateSchemaVersion": 1,
            "sessionId": new_session_id,
            "sequenceNo": 0,
        },
    )
    reset_manifest_descriptor = object_store.write_json(
        "project-1",
        {
            "contractVersion": 1,
            "payloadType": "runtime_session_reset_manifest",
            "oldSessionId": old_session.id,
            "newSessionId": new_session_id,
        },
    )
    queued = _queued_operation(
        operation_id="operation-runtime-reset-cancelled",
        operation_kind="reset_runtime_session",
        client_request_id="request-runtime-reset-cancelled",
        resource_kind="runtime_session",
        resource_id=new_session_id,
        now=now,
    )
    running, running_step = await _start_operation(
        store,
        queued,
        step_id="step-runtime-reset-cancelled",
        step_kind="rebuild_runtime_session",
        now=now,
    )
    completed = replace(
        running,
        status="succeeded",
        result_manifest_hash=reset_manifest_descriptor.content_hash,
        completed_at=now,
    )
    completed_step = replace(
        running_step,
        status="succeeded",
        output_manifest_hash=reset_manifest_descriptor.content_hash,
        completion_evidence_kind="runtime_session_reset_manifest",
        completion_evidence_ref=reset_manifest_descriptor.content_hash,
        completed_at=now,
    )
    completion_event = PrototypeOperationEvent(
        operation_id=completed.id,
        event_no=2,
        step_id=completed_step.id,
        event_kind="step_succeeded",
        status="succeeded",
        phase=completed_step.phase,
        input_hash=completed_step.input_manifest_hash,
        output_hash=reset_manifest_descriptor.content_hash,
        evidence_hash=reset_manifest_descriptor.content_hash,
        error_code=None,
        occurred_at=now,
    )
    (
        completed,
        completed_step,
        completion_event,
        replay_descriptor,
        replay_reference,
    ) = _bind_strict_replay_manifest(
        object_store,
        completed,
        completed_step,
        completion_event,
    )
    new_session = replace(
        old_session,
        id=new_session_id,
        source_id=DRAFT_ID,
        head_state_hash=state_descriptor.content_hash,
        head_view_model_hash=_hash("6"),
        latest_checkpoint_id=new_checkpoint_id,
        created_at=now,
        updated_at=now,
        completed_at=None,
        replaces_session_id=old_session.id,
    )
    new_checkpoint = replace(
        old_checkpoint,
        id=new_checkpoint_id,
        session_id=new_session.id,
        state_object_hash=state_descriptor.content_hash,
        state_hash=state_descriptor.content_hash,
        view_model_hash=new_session.head_view_model_hash,
        created_by_operation_id=completed.id,
        created_at=now,
    )
    state_reference = _runtime_reference(state_descriptor, new_checkpoint.id, now)
    old_reset_reference = PrototypeObjectReference(
        project_id="project-1",
        owner_kind="runtime_session",
        owner_id=old_session.id,
        role="runtime-session-reset-manifest",
        content_hash=reset_manifest_descriptor.content_hash,
        payload_type="runtime_session_reset_manifest",
        schema_version=1,
        created_at=now,
    )
    new_reset_reference = replace(old_reset_reference, owner_id=new_session.id)
    if cancel_at == "before_commit":
        require_runtime_session = store._require_runtime_session

        async def cancel_before_commit(
            conn: aiosqlite.Connection,
            session_id: str,
        ) -> PrototypeRuntimeSessionRecord:
            if session_id == new_session.id:
                raise asyncio.CancelledError
            return await require_runtime_session(conn, session_id)

        monkeypatch.setattr(store, "_require_runtime_session", cancel_before_commit)
    else:
        conn = await store._get_conn()
        commit = conn.commit
        commit_cancelled = False

        async def cancel_first_commit() -> None:
            nonlocal commit_cancelled
            if not commit_cancelled:
                commit_cancelled = True
                raise asyncio.CancelledError
            await commit()

        monkeypatch.setattr(conn, "commit", cancel_first_commit)

    try:
        with pytest.raises(asyncio.CancelledError):
            await store.reset_runtime_session(
                expected_old_status=old_session.status,
                expected_old_latest_checkpoint_id=old_session.latest_checkpoint_id,
                expected_old_head_sequence_no=old_session.head_sequence_no,
                expected_old_state_hash=old_session.head_state_hash,
                expected_old_view_model_hash=old_session.head_view_model_hash,
                expected_old_runtime_core_bundle_hash=old_session.runtime_core_bundle_hash,
                target_draft_id=DRAFT_ID,
                expected_target_head_sequence_no=0,
                expected_target_document_hash=old_session.pinned_document_object_hash,
                state_descriptor=state_descriptor,
                state_reference=state_reference,
                reset_manifest_descriptor=reset_manifest_descriptor,
                old_reset_reference=old_reset_reference,
                new_reset_reference=new_reset_reference,
                replay_descriptor=replay_descriptor,
                replay_reference=replay_reference,
                session=new_session,
                checkpoint=new_checkpoint,
                completed_operation=completed,
                completion_step=completed_step,
                completion_event=completion_event,
            )

        persisted_old_session = await store.load_runtime_session(old_session.id)
        assert persisted_old_session == old_session
        assert await store.load_runtime_session(new_session.id) is None
        assert await store.load_object("project-1", state_descriptor.content_hash) is None
        assert await store.load_object("project-1", reset_manifest_descriptor.content_hash) is None
        assert (
            await store.list_object_references("project-1", "runtime_checkpoint", new_checkpoint.id)
            == []
        )
        assert (
            await store.list_object_references("project-1", "runtime_session", old_session.id) == []
        )
        assert (
            await store.list_object_references("project-1", "runtime_session", new_session.id) == []
        )
        conn = await store._get_conn()
        checkpoint_count = await (
            await conn.execute(
                "SELECT COUNT(*) FROM prototype_runtime_checkpoints WHERE id = ?",
                (new_checkpoint.id,),
            )
        ).fetchone()
        assert checkpoint_count == (0,)
        persisted_operation = await store.load_operation(completed.id)
        assert persisted_operation is not None
        assert persisted_operation.status == "running"
        assert [event.status for event in await store.list_operation_events(completed.id)] == [
            "queued",
            "running",
        ]
        steps = await store.list_operation_steps(completed.id)
        assert len(steps) == 1
        assert steps[0].status == "running"

        follow_up = _queued_operation(
            operation_id="operation-after-runtime-reset-cancellation",
            operation_kind="replay_runtime_session",
            client_request_id="request-after-runtime-reset-cancellation",
            resource_kind="runtime_session",
            resource_id=old_session.id,
            now=now,
        )
        created = await store.create_operation(follow_up, _event_zero(follow_up))
        assert created.created
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_runtime_event_append_is_optimistic_and_idempotent(tmp_path: Path) -> None:
    store, object_store, initial_state, session, _ = await _create_initial_runtime_session(tmp_path)
    now = datetime.now(UTC)
    prepared = await _prepare_runtime_event(
        store,
        operation_id="operation-runtime-event-1",
        client_event_id="runtime-event-request-1",
        event_batch_id="runtime-event-batch-1",
        base_sequence_no=0,
        base_state_hash=initial_state.content_hash,
        result_state_hash=_hash("1"),
        result_view_model_hash=_hash("2"),
        now=now,
    )
    event_batch, operation, step, event = prepared

    try:
        first = await _append_runtime_event(
            store,
            object_store,
            event_batch=event_batch,
            completed_operation=operation,
            completion_step=step,
            completion_event=event,
        )
        second = await _append_runtime_event(
            store,
            object_store,
            event_batch=replace(event_batch, created_at=datetime.now(UTC)),
            completed_operation=operation,
            completion_step=step,
            completion_event=event,
        )
        recovered = await store.load_runtime_recovery_bundle(session.id)

        assert first.created
        assert not second.created
        assert second.event_batch == event_batch
        assert second.session.head_sequence_no == 1
        assert second.session.head_state_hash == event_batch.result_state_hash
        assert second.session.head_view_model_hash == event_batch.result_view_model_hash
        assert recovered.event_batches == (event_batch,)
        assert len(await store.list_operation_events(operation.id)) == 3
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_two_connections_cannot_append_the_same_runtime_head(tmp_path: Path) -> None:
    first_store, object_store, initial_state, _, _ = await _create_initial_runtime_session(tmp_path)
    second_store = AsyncStructuredPrototypeStore(tmp_path / "structured.db")
    now = datetime.now(UTC)
    first = await _prepare_runtime_event(
        first_store,
        operation_id="operation-runtime-race-1",
        client_event_id="runtime-race-1",
        event_batch_id="runtime-race-batch-1",
        base_sequence_no=0,
        base_state_hash=initial_state.content_hash,
        result_state_hash=_hash("1"),
        result_view_model_hash=_hash("2"),
        now=now,
    )
    second = await _prepare_runtime_event(
        second_store,
        operation_id="operation-runtime-race-2",
        client_event_id="runtime-race-2",
        event_batch_id="runtime-race-batch-2",
        base_sequence_no=0,
        base_state_hash=initial_state.content_hash,
        result_state_hash=_hash("3"),
        result_view_model_hash=_hash("4"),
        now=now,
    )

    async def append(
        store: AsyncStructuredPrototypeStore,
        prepared: tuple[
            PrototypeRuntimeEventBatchRecord,
            PrototypeOperation,
            PrototypeOperationStep,
            PrototypeOperationEvent,
        ],
    ) -> str:
        event_batch, operation, step, event = prepared
        try:
            await _append_runtime_event(
                store,
                object_store,
                event_batch=event_batch,
                completed_operation=operation,
                completion_step=step,
                completion_event=event,
            )
        except StructuredPrototypeStoreError as error:
            return error.code
        return "created"

    try:
        outcomes = await asyncio.gather(
            append(first_store, first),
            append(second_store, second),
        )
        assert sorted(outcomes) == ["created", "runtime_session_conflict"]
        persisted = await first_store.load_runtime_session("runtime-session-1")
        assert persisted is not None
        assert persisted.head_sequence_no == 1
    finally:
        await first_store.close()
        await second_store.close()


@pytest.mark.asyncio
async def test_runtime_replay_tail_refuses_the_201st_event(tmp_path: Path) -> None:
    store, object_store, _, _, _ = await _create_initial_runtime_session(tmp_path)
    conn = await store._get_conn()
    await conn.execute(
        """
        UPDATE prototype_runtime_sessions
        SET head_sequence_no = ?, head_state_hash = ?
        WHERE id = ?
        """,
        (MAX_REPLAY_TAIL_BATCHES, _hash("e"), "runtime-session-1"),
    )
    await conn.commit()
    event_batch, operation, step, event = await _prepare_runtime_event(
        store,
        operation_id="operation-runtime-tail-limit",
        client_event_id="runtime-tail-limit",
        event_batch_id="runtime-tail-limit-batch",
        base_sequence_no=MAX_REPLAY_TAIL_BATCHES,
        base_state_hash=_hash("e"),
        result_state_hash=_hash("f"),
        result_view_model_hash=_hash("1"),
        now=datetime.now(UTC),
    )

    try:
        with pytest.raises(StructuredPrototypeStoreError) as error:
            await _append_runtime_event(
                store,
                object_store,
                event_batch=event_batch,
                completed_operation=operation,
                completion_step=step,
                completion_event=event,
            )

        assert error.value.code == "runtime_checkpoint_required_unavailable"
        assert [item.event_no for item in await store.list_operation_events(operation.id)] == [
            0,
            1,
        ]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_runtime_checkpoint_resets_the_replay_tail(tmp_path: Path) -> None:
    store, object_store, initial_state, session, _ = await _create_initial_runtime_session(tmp_path)
    now = datetime.now(UTC)
    next_state = object_store.write_json(
        "project-1",
        {
            "runtimeStateSchemaVersion": 1,
            "runtimeCoreVersion": RUNTIME_CORE_VERSION,
            "sessionId": session.id,
            "sequenceNo": 1,
        },
    )
    view_model_hash = _hash("2")
    event_batch, operation, step, event = await _prepare_runtime_event(
        store,
        operation_id="operation-runtime-before-checkpoint",
        client_event_id="runtime-before-checkpoint",
        event_batch_id="runtime-before-checkpoint-batch",
        base_sequence_no=0,
        base_state_hash=initial_state.content_hash,
        result_state_hash=next_state.content_hash,
        result_view_model_hash=view_model_hash,
        now=now,
    )
    await _append_runtime_event(
        store,
        object_store,
        event_batch=event_batch,
        completed_operation=operation,
        completion_step=step,
        completion_event=event,
    )
    (
        checkpoint,
        reference,
        checkpoint_operation,
        checkpoint_step,
        checkpoint_event,
    ) = await _prepare_runtime_checkpoint(
        store,
        descriptor=next_state,
        sequence_no=1,
        view_model_hash=view_model_hash,
        now=now,
    )

    try:
        checkpointed = await _register_runtime_checkpoint(
            store,
            object_store,
            descriptor=next_state,
            reference=reference,
            checkpoint=checkpoint,
            completed_operation=checkpoint_operation,
            completion_step=checkpoint_step,
            completion_event=checkpoint_event,
        )
        recovered = await store.load_runtime_recovery_bundle(session.id)

        assert checkpointed.latest_checkpoint_id == checkpoint.id
        assert recovered.checkpoint == checkpoint
        assert recovered.object_descriptor == next_state
        assert recovered.event_batches == ()
    finally:
        await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("corruption_kind", "expected_code"),
    [
        ("sequence_gap", "runtime_replay_sequence_gap"),
        ("state_hash", "runtime_replay_state_hash_mismatch"),
        ("runtime_version", "runtime_replay_version_mismatch"),
    ],
)
async def test_runtime_recovery_rejects_corrupt_event_chains(
    tmp_path: Path,
    corruption_kind: str,
    expected_code: str,
) -> None:
    store, object_store, initial_state, session, _ = await _create_initial_runtime_session(tmp_path)
    now = datetime.now(UTC)
    first = await _prepare_runtime_event(
        store,
        operation_id="operation-runtime-corruption-1",
        client_event_id="runtime-corruption-1",
        event_batch_id="runtime-corruption-batch-1",
        base_sequence_no=0,
        base_state_hash=initial_state.content_hash,
        result_state_hash=_hash("1"),
        result_view_model_hash=_hash("2"),
        now=now,
    )
    second = await _prepare_runtime_event(
        store,
        operation_id="operation-runtime-corruption-2",
        client_event_id="runtime-corruption-2",
        event_batch_id="runtime-corruption-batch-2",
        base_sequence_no=1,
        base_state_hash=_hash("1"),
        result_state_hash=_hash("3"),
        result_view_model_hash=_hash("4"),
        now=now,
    )
    for prepared in (first, second):
        event_batch, operation, step, event = prepared
        await _append_runtime_event(
            store,
            object_store,
            event_batch=event_batch,
            completed_operation=operation,
            completion_step=step,
            completion_event=event,
        )
    conn = await store._get_conn()
    if corruption_kind == "sequence_gap":
        await conn.execute(
            "DELETE FROM prototype_runtime_event_batches WHERE id = ?",
            ("runtime-corruption-batch-1",),
        )
    elif corruption_kind == "state_hash":
        await conn.execute(
            "UPDATE prototype_runtime_event_batches SET base_state_hash = ? WHERE id = ?",
            (_hash("5"), "runtime-corruption-batch-2"),
        )
    else:
        await conn.execute(
            "UPDATE prototype_runtime_event_batches SET runtime_core_version = ? WHERE id = ?",
            ("0.2.0-corrupt", "runtime-corruption-batch-1"),
        )
    await conn.commit()

    try:
        with pytest.raises(StructuredPrototypeStoreError) as error:
            await store.load_runtime_recovery_bundle(session.id)

        assert error.value.code == expected_code
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_runtime_recovery_failure_marks_the_same_session_head_corrupt(
    tmp_path: Path,
) -> None:
    store, object_store, initial_state, session, _ = await _create_initial_runtime_session(tmp_path)
    now = datetime.now(UTC)
    event_batch, operation, step, event = await _prepare_runtime_event(
        store,
        operation_id="operation-runtime-before-corruption",
        client_event_id="runtime-before-corruption",
        event_batch_id="runtime-before-corruption-batch",
        base_sequence_no=0,
        base_state_hash=initial_state.content_hash,
        result_state_hash=_hash("1"),
        result_view_model_hash=_hash("2"),
        now=now,
    )
    appended = await _append_runtime_event(
        store,
        object_store,
        event_batch=event_batch,
        completed_operation=operation,
        completion_step=step,
        completion_event=event,
    )
    conn = await store._get_conn()
    await conn.execute(
        "UPDATE prototype_runtime_event_batches SET effect_report_hash = ? WHERE id = ?",
        (_hash("3"), event_batch.id),
    )
    await conn.commit()
    queued = _queued_operation(
        operation_id="operation-runtime-recovery-failed",
        operation_kind="replay_runtime_session",
        client_request_id="request-runtime-recovery-failed",
        resource_kind="runtime_session",
        resource_id=session.id,
        now=now,
    )
    running, running_step = await _start_operation(
        store,
        queued,
        step_id="step-runtime-recovery-failed",
        step_kind="replay_runtime_event_tail",
        now=now,
    )
    failed, failed_step, failure_event = _fail_operation(
        running,
        running_step,
        error_code="runtime_effect_report_hash_mismatch",
        now=now,
    )

    try:
        corrupted = await store.mark_runtime_session_corrupt(
            session_id=session.id,
            expected_head_sequence_no=appended.session.head_sequence_no,
            expected_state_hash=appended.session.head_state_hash,
            expected_view_model_hash=appended.session.head_view_model_hash,
            failed_operation=failed,
            failed_step=failed_step,
            failure_event=failure_event,
        )

        assert corrupted.status == "corrupt"
        assert corrupted.completed_at == now
        assert [item.status for item in await store.list_operation_events(failed.id)] == [
            "queued",
            "running",
            "failed",
        ]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_main_async_store_migrates_structured_schema_to_version_15(tmp_path: Path) -> None:
    store = AsyncSQLiteStore(tmp_path / "main-async.db")
    try:
        await store._init_db()
        conn = await store._get_conn()
        version = await (
            await conn.execute("SELECT version FROM schema_version WHERE id = 1")
        ).fetchone()
        assert version == (15,)
        tables = {
            str(row[0])
            for row in await (
                await conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'prototype_%'"
                )
            ).fetchall()
        }
        assert {
            "prototype_operations",
            "prototype_operation_steps",
            "prototype_operation_events",
            "prototype_documents",
            "prototype_drafts",
            "prototype_checkpoints",
            "prototype_command_batches",
            "prototype_objects",
            "prototype_object_references",
            "prototype_runtime_sessions",
            "prototype_runtime_event_batches",
            "prototype_runtime_checkpoints",
        }.issubset(tables)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_schema_version_10_with_existing_document_migrates_runtime_tables(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy-v10.db"
    legacy_store = AsyncSQLiteStore(db_path)
    await legacy_store._init_db()
    legacy_conn = await legacy_store._get_conn()
    now = datetime.now(UTC).isoformat()
    await legacy_conn.execute(
        """
        INSERT INTO prototype_documents (
            id, project_id, title, published_revision_no, active_draft_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("legacy-document", "project-1", "历史采购原型", None, None, now, now),
    )
    await legacy_conn.execute("DROP TABLE prototype_runtime_event_batches")
    await legacy_conn.execute("DROP TABLE prototype_runtime_sessions")
    await legacy_conn.execute("DROP TABLE prototype_runtime_checkpoints")
    await legacy_conn.execute("UPDATE schema_version SET version = 10 WHERE id = 1")
    await legacy_conn.commit()
    await legacy_store.close()

    migrated_store = AsyncSQLiteStore(db_path)
    try:
        await migrated_store._init_db()
        migrated_conn = await migrated_store._get_conn()
        version = await (
            await migrated_conn.execute("SELECT version FROM schema_version WHERE id = 1")
        ).fetchone()
        document = await (
            await migrated_conn.execute(
                "SELECT id, title FROM prototype_documents WHERE id = ?",
                ("legacy-document",),
            )
        ).fetchone()
        tables = {
            str(row[0])
            for row in await (
                await migrated_conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table' AND name LIKE 'prototype_runtime_%'
                    """
                )
            ).fetchall()
        }

        assert version == (15,)
        assert document == ("legacy-document", "历史采购原型")
        assert tables == {
            "prototype_runtime_sessions",
            "prototype_runtime_event_batches",
            "prototype_runtime_checkpoints",
        }
    finally:
        await migrated_store.close()


def test_sync_store_uses_the_same_structured_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "main-sync.db"
    SQLiteStore(db_path)

    with sqlite3.connect(db_path) as conn:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'prototype_%'"
            ).fetchall()
        }
    assert {
        "prototype_command_batches",
        "prototype_runtime_sessions",
        "prototype_runtime_event_batches",
        "prototype_runtime_checkpoints",
    }.issubset(tables)
