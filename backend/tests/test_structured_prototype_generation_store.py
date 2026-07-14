from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
import pytest

from app.adapters.prototype_object_store import PrototypeObjectStore
from app.adapters.structured_prototype_store import (
    AsyncStructuredPrototypeStore,
    StructuredPrototypeStoreError,
)
from app.domain.structured_prototype import (
    PrototypeObjectDescriptor,
    PrototypeObjectPayloadType,
    PrototypeObjectReference,
    PrototypeOperation,
    PrototypeOperationEvent,
    PrototypeOperationKind,
)
from app.domain.structured_prototype_generation import (
    PrototypeDocumentGenerationItemRecord,
    PrototypeDocumentGenerationJobRecord,
    PrototypeDocumentGenerationRunRecord,
)

NOW = datetime(2026, 7, 13, 15, 0, tzinfo=UTC)


def _hash(character: str) -> str:
    return "sha256:" + character * 64


def _operation(
    operation_id: str,
    kind: PrototypeOperationKind,
    resource_kind: str,
    resource_id: str,
    client_request_id: str,
    *,
    parent_operation_id: str | None = None,
) -> PrototypeOperation:
    return PrototypeOperation(
        id=operation_id,
        operation_kind=kind,
        project_id="project-1",
        resource_kind=resource_kind,
        resource_id=resource_id,
        client_request_id=client_request_id,
        correlation_id="correlation-generation-1",
        parent_operation_id=parent_operation_id,
        status="queued",
        phase="queued",
        attempt=1,
        request_manifest_hash=_hash("a"),
        config_manifest_hash=_hash("b"),
        result_manifest_hash=None,
        failure_evidence_hash=None,
        error_code=None,
        created_at=NOW,
        started_at=None,
        completed_at=None,
    )


def _event(operation: PrototypeOperation) -> PrototypeOperationEvent:
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
        occurred_at=NOW,
    )


def _reference(
    descriptor: PrototypeObjectDescriptor,
    role: str,
    payload_type: PrototypeObjectPayloadType,
) -> PrototypeObjectReference:
    return PrototypeObjectReference(
        project_id="project-1",
        owner_kind="generation_job",
        owner_id="generation-job-1",
        role=role,
        content_hash=descriptor.content_hash,
        payload_type=payload_type,
        schema_version=1,
        created_at=NOW,
    )


def _records(
    request_hash: str,
    context_hash: str,
) -> tuple[
    PrototypeDocumentGenerationJobRecord,
    PrototypeDocumentGenerationRunRecord,
    PrototypeDocumentGenerationItemRecord,
]:
    job = PrototypeDocumentGenerationJobRecord(
        id="generation-job-1",
        project_id="project-1",
        client_request_id="generation-request-1",
        status="queued",
        operation_id="generation-job-operation-1",
        request_manifest_object_hash=request_hash,
        request_hash=request_hash,
        context_manifest_object_hash=context_hash,
        blueprint_object_hash=None,
        blueprint_version=0,
        blueprint_hash=None,
        candidate_object_hash=None,
        candidate_document_hash=None,
        preview_render_run_id=None,
        preview_artifact_id=None,
        preview_renderer_version=None,
        preview_storage_key=None,
        preview_output_hash=None,
        preview_output_manifest_hash=None,
        preview_visual_preflight_report_hash=None,
        replay_manifest_object_hash=None,
        document_id=None,
        error_code=None,
        error_message=None,
        created_at=NOW,
        updated_at=NOW,
        completed_at=None,
    )
    run = PrototypeDocumentGenerationRunRecord(
        id="generation-run-1",
        job_id=job.id,
        status="queued",
        blueprint_hash=None,
        total=1,
        processed=0,
        succeeded=0,
        failed=0,
        running=0,
        pending=1,
        error_code=None,
        error_message=None,
        created_at=NOW,
        updated_at=NOW,
        started_at=None,
        completed_at=None,
    )
    item = PrototypeDocumentGenerationItemRecord(
        id="generation-item-blueprint-1",
        job_id=job.id,
        run_id=run.id,
        kind="blueprint",
        item_key="blueprint",
        page_key=None,
        status="pending",
        phase="queued",
        attempt=1,
        task_kind="generation_blueprint",
        operation_id="generation-item-operation-1",
        context_object_hash=context_hash,
        submission_id=None,
        submission_request_hash=None,
        submission_normalized_fields=(),
        submission_accepted_at=None,
        output_object_hash=None,
        task_id="prototype-generation-task-1",
        execution_process_id=None,
        error_code=None,
        error_message=None,
        created_at=NOW,
        updated_at=NOW,
        completed_at=None,
    )
    return job, run, item


async def _create(store: AsyncStructuredPrototypeStore, tmp_path: Path):
    object_store = PrototypeObjectStore(tmp_path / "objects")
    request = object_store.write_json("project-1", {"brief": "生成采购原型"})
    context = object_store.write_json("project-1", {"requestHash": request.content_hash})
    job, run, item = _records(request.content_hash, context.content_hash)
    job_operation = _operation(
        job.operation_id,
        "generation_job",
        "generation_job",
        job.id,
        job.client_request_id,
    )
    item_operation = _operation(
        item.operation_id,
        "generation_item",
        "generation_item",
        item.id,
        "generation-blueprint-item-request-1",
        parent_operation_id=job.operation_id,
    )
    result = await store.create_generation_job(
        job_operation=job_operation,
        job_event=_event(job_operation),
        item_operation=item_operation,
        item_event=_event(item_operation),
        job=job,
        run=run,
        item=item,
        descriptors_and_references=(
            (request, _reference(request, "request", "generation_request_manifest")),
            (context, _reference(context, "context", "generation_context_manifest")),
        ),
    )
    return result, job_operation, item_operation


@pytest.mark.asyncio
async def test_generation_job_create_is_atomic_idempotent_and_stores_only_object_refs(
    tmp_path: Path,
) -> None:
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    try:
        created, _, _ = await _create(store, tmp_path)
        retried, _, _ = await _create(store, tmp_path)

        assert created.created is True
        assert retried.created is False
        assert retried.snapshot == created.snapshot
        assert created.snapshot.latest_run is not None
        assert created.snapshot.items[0].task_kind == "generation_blueprint"
        assert created.snapshot.items[0].submission_normalized_fields == ()
        loaded = await store.load_generation_job("generation-job-1")
        assert loaded == created.snapshot
        async with (
            aiosqlite.connect(tmp_path / "console.db") as conn,
            conn.execute("PRAGMA table_info(prototype_document_generation_jobs)") as cursor,
        ):
            columns = {str(row[1]) for row in await cursor.fetchall()}
        assert "blueprint_json" not in columns
        assert "candidate_json" not in columns
        assert "request_json" not in columns
        async with (
            aiosqlite.connect(tmp_path / "console.db") as conn,
            conn.execute(
                "PRAGMA table_info(prototype_document_generation_run_items)"
            ) as cursor,
        ):
            item_columns = {str(row[1]) for row in await cursor.fetchall()}
        assert "submission_normalized_fields_json" in item_columns
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_generation_job_refuses_a_second_open_job_for_the_project(tmp_path: Path) -> None:
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    try:
        created, job_operation, item_operation = await _create(store, tmp_path)
        job = replace(
            created.snapshot.job,
            id="generation-job-2",
            client_request_id="generation-request-2",
            operation_id="generation-job-operation-2",
        )
        assert created.snapshot.latest_run is not None
        run = replace(created.snapshot.latest_run, id="generation-run-2", job_id=job.id)
        item = replace(
            created.snapshot.items[0],
            id="generation-item-blueprint-2",
            job_id=job.id,
            run_id=run.id,
            operation_id="generation-item-operation-2",
            task_id="prototype-generation-task-2",
        )
        second_job_operation = replace(
            job_operation,
            id=job.operation_id,
            resource_id=job.id,
            client_request_id=job.client_request_id,
        )
        second_item_operation = replace(
            item_operation,
            id=item.operation_id,
            resource_id=item.id,
            client_request_id="generation-blueprint-item-request-2",
            parent_operation_id=job.operation_id,
        )
        references = await store.list_object_references(
            "project-1", "generation_job", "generation-job-1"
        )
        descriptor_pairs = []
        for reference in references:
            descriptor = await store.load_object("project-1", reference.content_hash)
            assert descriptor is not None
            descriptor_pairs.append(
                (
                    descriptor,
                    replace(reference, owner_id=job.id),
                )
            )

        with pytest.raises(StructuredPrototypeStoreError) as error:
            await store.create_generation_job(
                job_operation=second_job_operation,
                job_event=_event(second_job_operation),
                item_operation=second_item_operation,
                item_event=_event(second_item_operation),
                job=job,
                run=run,
                item=item,
                descriptors_and_references=tuple(descriptor_pairs),
            )
        assert error.value.code == "generation_job_conflict"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_generation_store_migrates_normalization_evidence_for_existing_rows(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "console.db"
    original_store = AsyncStructuredPrototypeStore(db_path)
    try:
        await _create(original_store, tmp_path)
    finally:
        await original_store.close()
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "ALTER TABLE prototype_document_generation_run_items "
            "DROP COLUMN submission_normalized_fields_json"
        )
        await conn.commit()
    store = AsyncStructuredPrototypeStore(db_path)
    try:
        await store.initialize()
        async with (
            aiosqlite.connect(db_path) as conn,
            conn.execute(
                "SELECT submission_normalized_fields_json "
                "FROM prototype_document_generation_run_items WHERE id = ?",
                ("generation-item-blueprint-1",),
            ) as cursor,
        ):
            row = await cursor.fetchone()
        assert row == ("[]",)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_startup_interrupts_active_generation_records_and_operations(tmp_path: Path) -> None:
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    try:
        created, job_operation, item_operation = await _create(store, tmp_path)
        interrupted_at = NOW.replace(hour=16)

        count = await store.interrupt_active_generation_jobs(interrupted_at)

        assert count == 1
        snapshot = await store.load_generation_job(created.snapshot.job.id)
        assert snapshot is not None
        assert snapshot.job.status == "interrupted"
        assert snapshot.latest_run is not None
        assert snapshot.latest_run.status == "interrupted"
        assert snapshot.items[0].status == "interrupted"
        loaded_job_operation = await store.load_operation(job_operation.id)
        loaded_item_operation = await store.load_operation(item_operation.id)
        assert loaded_job_operation is not None
        assert loaded_item_operation is not None
        assert loaded_job_operation.status == "interrupted"
        assert loaded_item_operation.status == "interrupted"
        job_events = await store.list_operation_events(job_operation.id)
        assert [event.event_no for event in job_events] == [0, 1]
        assert job_events[-1].error_code == "restart_interrupted"
    finally:
        await store.close()
