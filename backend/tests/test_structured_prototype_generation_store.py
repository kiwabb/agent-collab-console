from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

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
    PrototypeOperationStep,
)
from app.domain.structured_prototype_generation import (
    PrototypeDocumentGenerationItemRecord,
    PrototypeDocumentGenerationJobRecord,
    PrototypeDocumentGenerationRunRecord,
    PrototypeGenerationRestartRecoveryScope,
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
    correlation_id: str = "correlation-generation-1",
) -> PrototypeOperation:
    return PrototypeOperation(
        id=operation_id,
        operation_kind=kind,
        project_id="project-1",
        resource_kind=resource_kind,
        resource_id=resource_id,
        client_request_id=client_request_id,
        correlation_id=correlation_id,
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


def _running_transition(
    operation: PrototypeOperation,
) -> tuple[
    PrototypeOperation,
    PrototypeOperationStep,
    PrototypeOperationEvent,
]:
    running = replace(
        operation,
        status="running",
        phase="store-test",
        started_at=NOW,
    )
    step = PrototypeOperationStep(
        id=f"{operation.id}-step-0",
        operation_id=operation.id,
        parent_step_id=None,
        step_kind="store-test",
        step_ordinal=0,
        attempt=1,
        status="running",
        phase="store-test",
        input_manifest_hash=operation.request_manifest_hash,
        config_manifest_hash=operation.config_manifest_hash,
        output_manifest_hash=None,
        completion_evidence_kind=None,
        completion_evidence_ref=None,
        error_code=None,
        started_at=NOW,
        completed_at=None,
    )
    event = PrototypeOperationEvent(
        operation_id=operation.id,
        event_no=1,
        step_id=step.id,
        event_kind="step_started",
        status="running",
        phase=step.phase,
        input_hash=step.input_manifest_hash,
        output_hash=None,
        evidence_hash=None,
        error_code=None,
        occurred_at=NOW,
    )
    return running, step, event


def _completed_transition(
    running_transition: tuple[
        PrototypeOperation,
        PrototypeOperationStep,
        PrototypeOperationEvent,
    ],
    result_hash: str,
) -> tuple[
    PrototypeOperation,
    PrototypeOperationStep,
    PrototypeOperationEvent,
]:
    running, running_step, _ = running_transition
    completed = replace(
        running,
        status="succeeded",
        result_manifest_hash=result_hash,
        completed_at=NOW,
    )
    completed_step = replace(
        running_step,
        status="succeeded",
        output_manifest_hash=result_hash,
        completion_evidence_kind="replay_manifest",
        completion_evidence_ref=result_hash,
        completed_at=NOW,
    )
    event = PrototypeOperationEvent(
        operation_id=completed.id,
        event_no=2,
        step_id=completed_step.id,
        event_kind="step_succeeded",
        status="succeeded",
        phase=completed_step.phase,
        input_hash=completed_step.input_manifest_hash,
        output_hash=result_hash,
        evidence_hash=result_hash,
        error_code=None,
        occurred_at=NOW,
    )
    return completed, completed_step, event


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
    source_hash: str,
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
        source_policy="committed_head_v1",
        source_snapshot_object_hash=source_hash,
        source_fingerprint=_hash("d"),
        source_snapshot_ref=("refs/agent-collab/prototype-generation/generation-job-1"),
        repository_object_format="sha1",
        worktree_base_commit="1" * 40,
        repository_project_prefix="",
        repository_tree_object_id="2" * 40,
        working_tree_dirty=True,
        excluded_tracked_change_count=1,
        excluded_untracked_count=1,
        source_file_exclusion_policy="dotenv_checkout_filter_v1",
        excluded_sensitive_file_count=1,
        excluded_status_hash=_hash("e"),
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
        item_ordinal=0,
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


def _restart_evidence_pairs(
    object_store: PrototypeObjectStore,
    scope: PrototypeGenerationRestartRecoveryScope,
    interrupted_at: datetime,
) -> tuple[tuple[PrototypeObjectDescriptor, PrototypeObjectReference], ...]:
    pairs: list[tuple[PrototypeObjectDescriptor, PrototypeObjectReference]] = []
    for target in scope.operations:
        descriptor = object_store.write_json(
            target.operation.project_id,
            {
                "manifestVersion": 1,
                "evidenceKind": "generation_restart_interruption",
                "scopeFingerprint": scope.fingerprint,
                "operationId": target.operation.id,
                "errorCode": "restart_interrupted",
                "interruptedAt": interrupted_at.isoformat(),
            },
        )
        pairs.append(
            (
                descriptor,
                PrototypeObjectReference(
                    project_id=target.operation.project_id,
                    owner_kind="replay_manifest",
                    owner_id=target.operation.id,
                    role="operation-interruption-evidence",
                    content_hash=descriptor.content_hash,
                    payload_type="generation_evidence_manifest",
                    schema_version=1,
                    created_at=interrupted_at,
                ),
            )
        )
    return tuple(pairs)


async def _create(store: AsyncStructuredPrototypeStore, tmp_path: Path):
    object_store = PrototypeObjectStore(tmp_path / "objects")
    request = object_store.write_json(
        "project-1",
        {"brief": "基于 admin-demo 项目源码生成可编辑管理后台原型"},
    )
    context = object_store.write_json("project-1", {"requestHash": request.content_hash})
    source = object_store.write_json("project-1", {"sourcePolicy": "committed_head_v1"})
    job, run, item = _records(
        request.content_hash,
        context.content_hash,
        source.content_hash,
    )
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
            (
                source,
                _reference(
                    source,
                    "source-snapshot-manifest",
                    "generation_source_snapshot_manifest",
                ),
            ),
        ),
    )
    return result, job_operation, item_operation


async def _promote_job_for_page_generation(
    store: AsyncStructuredPrototypeStore,
    db_path: Path,
    job: PrototypeDocumentGenerationJobRecord,
) -> PrototypeDocumentGenerationJobRecord:
    blueprint_hash = _hash("c")
    async with aiosqlite.connect(db_path) as conn:
        cursor = await conn.execute(
            """
            UPDATE prototype_document_generation_jobs
            SET status = 'generating', blueprint_object_hash = ?, blueprint_version = 1,
                blueprint_hash = ?, updated_at = ?
            WHERE id = ?
            """,
            (blueprint_hash, blueprint_hash, NOW.isoformat(), job.id),
        )
        assert cursor.rowcount == 1
        await conn.commit()
    snapshot = await store.load_generation_job(job.id)
    assert snapshot is not None
    assert snapshot.job.status == "generating"
    return snapshot.job


def _page_run_records(
    job: PrototypeDocumentGenerationJobRecord,
    page_keys: tuple[str, ...],
    ordinals: tuple[int, ...] | None = None,
) -> tuple[
    PrototypeOperation,
    PrototypeDocumentGenerationRunRecord,
    tuple[
        tuple[
            PrototypeDocumentGenerationItemRecord,
            PrototypeOperation,
            PrototypeOperationEvent,
        ],
        ...,
    ],
]:
    run_id = "generation-page-run-1"
    operation = _operation(
        "generation-page-operation-1",
        "generation_job",
        "generation_job",
        job.id,
        "generation-page-request-1",
        parent_operation_id=job.operation_id,
    )
    run = PrototypeDocumentGenerationRunRecord(
        id=run_id,
        job_id=job.id,
        status="queued",
        blueprint_hash=job.blueprint_hash,
        total=len(page_keys),
        processed=0,
        succeeded=0,
        failed=0,
        running=0,
        pending=len(page_keys),
        error_code=None,
        error_message=None,
        created_at=NOW,
        updated_at=NOW,
        started_at=None,
        completed_at=None,
    )
    item_ordinals = ordinals if ordinals is not None else tuple(range(len(page_keys)))
    item_operations: list[
        tuple[
            PrototypeDocumentGenerationItemRecord,
            PrototypeOperation,
            PrototypeOperationEvent,
        ]
    ] = []
    for page_key, ordinal in zip(page_keys, item_ordinals, strict=True):
        item_id = f"generation-page-item-{page_key}"
        item_operation = _operation(
            f"generation-page-item-operation-{page_key}",
            "generation_item",
            "generation_item",
            item_id,
            f"generation-page-item-request-{page_key}",
            parent_operation_id=operation.id,
        )
        item = PrototypeDocumentGenerationItemRecord(
            id=item_id,
            job_id=job.id,
            run_id=run.id,
            kind="page",
            item_key=page_key,
            page_key=page_key,
            item_ordinal=ordinal,
            status="pending",
            phase="queued",
            attempt=1,
            task_kind="generation_page",
            operation_id=item_operation.id,
            context_object_hash=_hash("d"),
            submission_id=None,
            submission_request_hash=None,
            submission_normalized_fields=(),
            submission_accepted_at=None,
            output_object_hash=None,
            task_id=f"generation-page-task-{page_key}",
            execution_process_id=None,
            error_code=None,
            error_message=None,
            created_at=NOW,
            updated_at=NOW,
            completed_at=None,
        )
        item_operations.append((item, item_operation, _event(item_operation)))
    return operation, run, tuple(item_operations)


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
            conn.execute("PRAGMA table_info(prototype_document_generation_run_items)") as cursor,
        ):
            item_columns = {str(row[1]) for row in await cursor.fetchall()}
        assert "submission_normalized_fields_json" in item_columns
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_generation_confirm_loader_preserves_schedule_operation_receipt_across_restart(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "console.db"
    store = AsyncStructuredPrototypeStore(db_path)
    blueprint_hash = _hash("c")
    schedule_operation = _operation(
        "foundation-schedule-operation-1",
        "generation_job",
        "generation_job",
        "generation-job-1",
        "generation-confirm-request-1",
        parent_operation_id="generation-job-operation-1",
        correlation_id="correlation-foundation-schedule-1",
    )
    run = PrototypeDocumentGenerationRunRecord(
        id="foundation-run-1",
        job_id="generation-job-1",
        status="queued",
        blueprint_hash=blueprint_hash,
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
    foundation_item = PrototypeDocumentGenerationItemRecord(
        id="foundation-item-1",
        job_id=run.job_id,
        run_id=run.id,
        kind="foundation",
        item_key="foundation",
        page_key=None,
        item_ordinal=0,
        status="pending",
        phase="queued",
        attempt=1,
        task_kind="generation_foundation",
        operation_id="foundation-item-operation-1",
        context_object_hash=_hash("d"),
        submission_id=None,
        submission_request_hash=None,
        submission_normalized_fields=(),
        submission_accepted_at=None,
        output_object_hash=None,
        task_id="foundation-task-1",
        execution_process_id=None,
        error_code=None,
        error_message=None,
        created_at=NOW,
        updated_at=NOW,
        completed_at=None,
    )
    foundation_operation = _operation(
        foundation_item.operation_id,
        "generation_item",
        "generation_item",
        foundation_item.id,
        "foundation-item-request-1",
        parent_operation_id=schedule_operation.id,
    )
    try:
        created, _, _ = await _create(store, tmp_path)
        async with aiosqlite.connect(db_path) as conn:
            await conn.execute(
                """
                UPDATE prototype_document_generation_jobs
                SET status = 'awaiting_confirmation', blueprint_object_hash = ?,
                    blueprint_version = 1, blueprint_hash = ?, updated_at = ?
                WHERE id = ?
                """,
                (blueprint_hash, blueprint_hash, NOW.isoformat(), created.snapshot.job.id),
            )
            await conn.commit()
        awaiting = await store.load_generation_job(created.snapshot.job.id)
        assert awaiting is not None
        scheduled = await store.create_generation_run(
            operation=schedule_operation,
            initial_event=_event(schedule_operation),
            job=replace(awaiting.job, status="generating"),
            run=run,
            item_operations=(
                (foundation_item, foundation_operation, _event(foundation_operation)),
            ),
            expected_job_statuses=("awaiting_confirmation",),
            expected_blueprint_version=1,
            expected_blueprint_hash=blueprint_hash,
        )
        assert scheduled.created is True
        async with aiosqlite.connect(db_path) as conn:
            await conn.execute(
                """
                UPDATE prototype_operations
                SET status = 'succeeded', phase = 'completed', started_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (NOW.isoformat(), NOW.isoformat(), schedule_operation.id),
            )
            await conn.execute(
                """
                UPDATE prototype_document_generation_runs
                SET status = 'completed', processed = 1, succeeded = 1,
                    failed = 0, running = 0, pending = 0, completed_at = ?
                WHERE id = ?
                """,
                (NOW.isoformat(), run.id),
            )
            await conn.execute(
                """
                UPDATE prototype_document_generation_run_items
                SET status = 'done', phase = 'completed', completed_at = ?
                WHERE id = ?
                """,
                (NOW.isoformat(), foundation_item.id),
            )
            await conn.execute(
                """
                UPDATE prototype_document_generation_jobs
                SET status = 'ready', updated_at = ?
                WHERE id = ?
                """,
                (NOW.isoformat(), created.snapshot.job.id),
            )
            await conn.commit()

        receipt = await store.load_generation_confirm_result(
            job_id=created.snapshot.job.id,
            client_request_id=schedule_operation.client_request_id,
            request_hash=schedule_operation.request_manifest_hash,
            expected_operation_id=schedule_operation.id,
            expected_run_id=run.id,
            expected_blueprint_hash=blueprint_hash,
        )
        assert receipt is not None
        assert receipt.operation_id == schedule_operation.id
        assert receipt.correlation_id == schedule_operation.correlation_id
        assert receipt.operation_id != receipt.snapshot.job.operation_id
    finally:
        await store.close()

    reopened = AsyncStructuredPrototypeStore(db_path)
    try:
        retried = await reopened.load_generation_confirm_result(
            job_id="generation-job-1",
            client_request_id=schedule_operation.client_request_id,
            request_hash=schedule_operation.request_manifest_hash,
            expected_operation_id=schedule_operation.id,
            expected_run_id=run.id,
            expected_blueprint_hash=blueprint_hash,
        )
        assert retried is not None
        assert retried.operation_id == schedule_operation.id
        assert retried.correlation_id == schedule_operation.correlation_id
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_generation_store_loads_legacy_nullable_snapshot_but_rejects_new_incomplete_job(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "console.db"
    store = AsyncStructuredPrototypeStore(db_path)
    try:
        created, job_operation, item_operation = await _create(store, tmp_path)
        incomplete = replace(
            created.snapshot.job,
            source_policy=None,
            source_snapshot_object_hash=None,
            source_fingerprint=None,
            source_snapshot_ref=None,
            repository_object_format=None,
            worktree_base_commit=None,
            repository_project_prefix=None,
            repository_tree_object_id=None,
            working_tree_dirty=None,
            excluded_tracked_change_count=None,
            excluded_untracked_count=None,
            source_file_exclusion_policy=None,
            excluded_sensitive_file_count=None,
            excluded_status_hash=None,
        )
        assert created.snapshot.latest_run is not None
        with pytest.raises(StructuredPrototypeStoreError):
            store._validate_generation_job_create(
                job_operation=job_operation,
                item_operation=item_operation,
                job=incomplete,
                run=created.snapshot.latest_run,
                item=created.snapshot.items[0],
            )

        async with aiosqlite.connect(db_path) as conn:
            await conn.execute(
                """
                UPDATE prototype_document_generation_jobs
                SET source_policy = NULL, source_snapshot_object_hash = NULL,
                    source_fingerprint = NULL, source_snapshot_ref = NULL,
                    repository_object_format = NULL, worktree_base_commit = NULL,
                    repository_project_prefix = NULL, repository_tree_object_id = NULL,
                    working_tree_dirty = NULL, excluded_tracked_change_count = NULL,
                    excluded_untracked_count = NULL, source_file_exclusion_policy = NULL,
                    excluded_sensitive_file_count = NULL, excluded_status_hash = NULL
                WHERE id = ?
                """,
                (created.snapshot.job.id,),
            )
            await conn.commit()
        legacy = await store.load_generation_job(created.snapshot.job.id)
        assert legacy is not None
        assert legacy.job.source_policy is None
        assert legacy.job.source_snapshot_object_hash is None
        assert legacy.job.repository_project_prefix is None
        assert legacy.job.working_tree_dirty is None
        assert legacy.job.excluded_sensitive_file_count is None
    finally:
        await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "page_keys",
    [
        ("dashboard",),
        ("users", "dashboard"),
        ("settings", "dashboard", "orders", "users", "audit-log"),
    ],
)
async def test_generation_store_persists_dynamic_page_count_and_ordinal_order_across_restart(
    tmp_path: Path,
    page_keys: tuple[str, ...],
) -> None:
    db_path = tmp_path / "console.db"
    store = AsyncStructuredPrototypeStore(db_path)
    try:
        created, _, _ = await _create(store, tmp_path)
        generating_job = await _promote_job_for_page_generation(
            store,
            db_path,
            created.snapshot.job,
        )
        operation, run, item_operations = _page_run_records(generating_job, page_keys)

        scheduled = await store.create_generation_run(
            operation=operation,
            initial_event=_event(operation),
            job=generating_job,
            run=run,
            item_operations=tuple(reversed(item_operations)),
            expected_job_statuses=("generating",),
            expected_blueprint_version=generating_job.blueprint_version,
            expected_blueprint_hash=cast(str, generating_job.blueprint_hash),
        )

        assert scheduled.created is True
        assert scheduled.snapshot.latest_run is not None
        assert scheduled.snapshot.latest_run.total == len(page_keys)
        assert [item.item_key for item in scheduled.snapshot.items] == list(page_keys)
        assert [item.item_ordinal for item in scheduled.snapshot.items] == list(
            range(len(page_keys))
        )
    finally:
        await store.close()

    reopened = AsyncStructuredPrototypeStore(db_path)
    try:
        restored = await reopened.load_generation_job("generation-job-1")
        assert restored is not None
        assert restored.latest_run is not None
        assert restored.latest_run.total == len(page_keys)
        assert restored.latest_run.pending == len(page_keys)
        assert [item.item_key for item in restored.items] == list(page_keys)
        assert [item.item_ordinal for item in restored.items] == list(range(len(page_keys)))
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_generation_run_atomically_refuses_changed_blueprint_identity(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "console.db"
    store = AsyncStructuredPrototypeStore(db_path)
    try:
        created, _, _ = await _create(store, tmp_path)
        current_job = await _promote_job_for_page_generation(
            store,
            db_path,
            created.snapshot.job,
        )
        stale_job = replace(
            current_job,
            blueprint_version=current_job.blueprint_version + 1,
            blueprint_hash=_hash("f"),
            blueprint_object_hash=_hash("f"),
        )
        operation, run, item_operations = _page_run_records(stale_job, ("dashboard",))

        with pytest.raises(StructuredPrototypeStoreError) as error:
            await store.create_generation_run(
                operation=operation,
                initial_event=_event(operation),
                job=stale_job,
                run=run,
                item_operations=item_operations,
                expected_job_statuses=("generating",),
                expected_blueprint_version=stale_job.blueprint_version,
                expected_blueprint_hash=cast(str, stale_job.blueprint_hash),
            )

        assert error.value.code == "blueprint_conflict"
        restored = await store.load_generation_job(current_job.id)
        assert restored is not None
        assert restored.job.blueprint_version == current_job.blueprint_version
        assert restored.job.blueprint_hash == current_job.blueprint_hash
        assert restored.latest_run is not None
        assert restored.latest_run.id == "generation-run-1"
    finally:
        await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("ordinals", [(0, 0), (0, 2)])
async def test_generation_store_refuses_conflicting_or_non_contiguous_item_ordinals(
    tmp_path: Path,
    ordinals: tuple[int, int],
) -> None:
    db_path = tmp_path / "console.db"
    store = AsyncStructuredPrototypeStore(db_path)
    try:
        created, _, _ = await _create(store, tmp_path)
        generating_job = await _promote_job_for_page_generation(
            store,
            db_path,
            created.snapshot.job,
        )
        operation, run, item_operations = _page_run_records(
            generating_job,
            ("users", "orders"),
            ordinals,
        )

        with pytest.raises(StructuredPrototypeStoreError) as error:
            await store.create_generation_run(
                operation=operation,
                initial_event=_event(operation),
                job=generating_job,
                run=run,
                item_operations=item_operations,
                expected_job_statuses=("generating",),
                expected_blueprint_version=generating_job.blueprint_version,
                expected_blueprint_hash=cast(str, generating_job.blueprint_hash),
            )

        assert error.value.code == "generation_run_invalid"
        snapshot = await store.load_generation_job(generating_job.id)
        assert snapshot is not None
        assert snapshot.latest_run is not None
        assert snapshot.latest_run.id == "generation-run-1"
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
            source_snapshot_ref=("refs/agent-collab/prototype-generation/generation-job-2"),
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
    object_store = PrototypeObjectStore(tmp_path / "objects")
    try:
        created, job_operation, item_operation = await _create(store, tmp_path)
        interrupted_at = NOW.replace(hour=16)
        phase_operation = _operation(
            "generation-phase-operation-1",
            "generation_job",
            "generation_job",
            created.snapshot.job.id,
            "generation-phase-request-1",
            parent_operation_id=job_operation.id,
        )
        await store.create_operation(phase_operation, _event(phase_operation))
        phase_running = _running_transition(phase_operation)
        await store.record_operation_transition(*phase_running)
        phase_item_operation = _operation(
            "generation-phase-item-operation-1",
            "generation_item",
            "generation_item",
            "generation-phase-item-1",
            "generation-phase-item-request-1",
            parent_operation_id=phase_operation.id,
        )
        await store.create_operation(phase_item_operation, _event(phase_item_operation))
        scope = await store.load_generation_restart_recovery_scope()
        assert {target.operation.id for target in scope.operations} == {
            job_operation.id,
            item_operation.id,
            phase_operation.id,
            phase_item_operation.id,
        }

        count = await store.interrupt_active_generation_jobs(
            expected_scope_fingerprint=scope.fingerprint,
            descriptors_and_references=_restart_evidence_pairs(
                object_store,
                scope,
                interrupted_at,
            ),
            interrupted_at=interrupted_at,
        )

        assert count == 1
        snapshot = await store.load_generation_job(created.snapshot.job.id)
        assert snapshot is not None
        assert snapshot.job.status == "interrupted"
        assert snapshot.latest_run is not None
        assert snapshot.latest_run.status == "interrupted"
        assert snapshot.latest_run.total == 1
        assert snapshot.latest_run.processed == 1
        assert snapshot.latest_run.succeeded == 0
        assert snapshot.latest_run.failed == 1
        assert snapshot.latest_run.running == 0
        assert snapshot.latest_run.pending == 0
        assert snapshot.items[0].status == "interrupted"
        loaded_job_operation = await store.load_operation(job_operation.id)
        loaded_item_operation = await store.load_operation(item_operation.id)
        assert loaded_job_operation is not None
        assert loaded_item_operation is not None
        assert loaded_job_operation.status == "interrupted"
        assert loaded_item_operation.status == "interrupted"
        job_events = await store.list_operation_events(job_operation.id)
        assert [event.event_no for event in job_events] == [0, 1, 2]
        assert [event.status for event in job_events] == ["queued", "running", "interrupted"]
        assert job_events[-1].error_code == "restart_interrupted"
        assert job_events[-1].step_id is not None
        assert job_events[-1].evidence_hash == loaded_job_operation.failure_evidence_hash
        job_steps = await store.list_operation_steps(job_operation.id)
        assert len(job_steps) == 1
        assert job_steps[0].status == "interrupted"
        assert job_steps[0].completion_evidence_ref == job_events[-1].evidence_hash
        assert await store.load_object("project-1", cast(str, job_events[-1].evidence_hash))
        recovered_phase = await store.load_operation(phase_operation.id)
        assert recovered_phase is not None and recovered_phase.status == "interrupted"
        phase_steps = await store.list_operation_steps(phase_operation.id)
        assert len(phase_steps) == 1
        assert phase_steps[0].status == "interrupted"
        assert phase_steps[0].id == phase_running[1].id
        assert (await store.load_generation_restart_recovery_scope()).operations == ()
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_generation_restart_recovery_rejects_scope_drift_atomically(tmp_path: Path) -> None:
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "objects")
    try:
        _, job_operation, _ = await _create(store, tmp_path)
        interrupted_at = NOW.replace(hour=16)
        scope = await store.load_generation_restart_recovery_scope()
        evidence_pairs = _restart_evidence_pairs(object_store, scope, interrupted_at)
        child = _operation(
            "generation-late-child-operation",
            "generation_item",
            "generation_item",
            "generation-late-child",
            "generation-late-child-request",
            parent_operation_id=job_operation.id,
        )
        await store.create_operation(child, _event(child))

        with pytest.raises(StructuredPrototypeStoreError) as error:
            await store.interrupt_active_generation_jobs(
                expected_scope_fingerprint=scope.fingerprint,
                descriptors_and_references=evidence_pairs,
                interrupted_at=interrupted_at,
            )

        assert error.value.code == "generation_recovery_conflict"
        assert (await store.load_operation(job_operation.id)) == job_operation
        for descriptor, _ in evidence_pairs:
            assert await store.load_object("project-1", descriptor.content_hash) is None
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_restart_interrupts_accept_child_without_changing_ready_root(tmp_path: Path) -> None:
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "objects")
    try:
        created, job_operation, item_operation = await _create(store, tmp_path)
        root_manifest_hash = _hash("f")
        async with aiosqlite.connect(tmp_path / "console.db") as conn:
            await conn.execute(
                """
                UPDATE prototype_operations
                SET status = 'succeeded', phase = 'render_preview',
                    result_manifest_hash = ?, completed_at = ?
                WHERE id = ?
                """,
                (root_manifest_hash, NOW.isoformat(), job_operation.id),
            )
            await conn.execute(
                """
                UPDATE prototype_operations
                SET status = 'succeeded', phase = 'done',
                    result_manifest_hash = ?, completed_at = ?
                WHERE id = ?
                """,
                (_hash("e"), NOW.isoformat(), item_operation.id),
            )
            await conn.execute(
                """
                UPDATE prototype_document_generation_jobs
                SET status = 'ready', replay_manifest_object_hash = ?, updated_at = ?
                WHERE id = ?
                """,
                (root_manifest_hash, NOW.isoformat(), created.snapshot.job.id),
            )
            await conn.execute(
                """
                UPDATE prototype_document_generation_runs
                SET status = 'completed', processed = total, succeeded = total,
                    pending = 0, completed_at = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (NOW.isoformat(), NOW.isoformat(), created.snapshot.job.id),
            )
            await conn.execute(
                """
                UPDATE prototype_document_generation_run_items
                SET status = 'done', phase = 'done', completed_at = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (NOW.isoformat(), NOW.isoformat(), created.snapshot.job.id),
            )
            await conn.commit()
        accept_operation = _operation(
            "generation-accept-operation-1",
            "create_document",
            "document",
            "document-1",
            "generation-accept-request-1",
            parent_operation_id=job_operation.id,
        )
        await store.create_operation(accept_operation, _event(accept_operation))
        accept_running = _running_transition(accept_operation)
        await store.record_operation_transition(*accept_running)
        scope = await store.load_generation_restart_recovery_scope()
        assert [target.operation.id for target in scope.operations] == [accept_operation.id]
        assert scope.active_job_count == 0
        interrupted_at = NOW.replace(hour=16)

        assert (
            await store.interrupt_active_generation_jobs(
                expected_scope_fingerprint=scope.fingerprint,
                descriptors_and_references=_restart_evidence_pairs(
                    object_store,
                    scope,
                    interrupted_at,
                ),
                interrupted_at=interrupted_at,
            )
            == 1
        )

        ready = await store.load_generation_job(created.snapshot.job.id)
        assert ready is not None and ready.job.status == "ready"
        loaded_root = await store.load_operation(job_operation.id)
        loaded_accept = await store.load_operation(accept_operation.id)
        assert loaded_root is not None and loaded_root.status == "succeeded"
        assert loaded_accept is not None and loaded_accept.status == "interrupted"
        assert (await store.list_operation_steps(accept_operation.id))[0].status == "interrupted"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_generation_transition_scopes_replay_manifest_ownership_to_its_operations(
    tmp_path: Path,
) -> None:
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "objects")
    try:
        created, job_operation, item_operation = await _create(store, tmp_path)
        snapshot = created.snapshot
        assert snapshot.latest_run is not None
        item_running = _running_transition(item_operation)
        await store.transition_generation_records(
            job=snapshot.job,
            run=snapshot.latest_run,
            items=snapshot.items,
            expected_job_statuses=("queued",),
            expected_run_statuses=("queued",),
            expected_item_statuses=("pending",),
            operation_transitions=(item_running,),
        )

        with pytest.raises(StructuredPrototypeStoreError) as missing_replay_error:
            await store.transition_generation_records(
                job=snapshot.job,
                run=snapshot.latest_run,
                items=snapshot.items,
                expected_job_statuses=("queued",),
                expected_run_statuses=("queued",),
                expected_item_statuses=("pending",),
                operation_transitions=(
                    _completed_transition(item_running, _hash("missing-replay")),
                ),
            )
        assert missing_replay_error.value.code == (
            "generation_replay_manifest_registration_required"
        )
        assert await store.load_operation(item_operation.id) == item_running[0]

        replay_descriptor = object_store.write_json(
            "project-1",
            {"kind": "store-test-item-replay"},
        )
        replay_reference = PrototypeObjectReference(
            project_id="project-1",
            owner_kind="replay_manifest",
            owner_id=item_operation.id,
            role="operation-replay-manifest",
            content_hash=replay_descriptor.content_hash,
            payload_type="replay_manifest",
            schema_version=1,
            created_at=NOW,
        )
        await store.transition_generation_records(
            job=snapshot.job,
            run=snapshot.latest_run,
            items=snapshot.items,
            expected_job_statuses=("queued",),
            expected_run_statuses=("queued",),
            expected_item_statuses=("pending",),
            descriptors_and_references=((replay_descriptor, replay_reference),),
            operation_transitions=(
                _completed_transition(item_running, replay_descriptor.content_hash),
            ),
        )
        assert await store.list_object_references(
            "project-1",
            "replay_manifest",
            item_operation.id,
        ) == [replay_reference]

        root_running = _running_transition(job_operation)
        wrong_role_descriptor = object_store.write_json(
            "project-1",
            {"kind": "wrong-role-replay"},
        )
        wrong_role_reference = replace(
            replay_reference,
            owner_id=job_operation.id,
            role="generation-ready",
            content_hash=wrong_role_descriptor.content_hash,
        )
        with pytest.raises(StructuredPrototypeStoreError) as wrong_role_error:
            await store.transition_generation_records(
                job=snapshot.job,
                run=snapshot.latest_run,
                items=snapshot.items,
                expected_job_statuses=("queued",),
                expected_run_statuses=("queued",),
                expected_item_statuses=("pending",),
                descriptors_and_references=((wrong_role_descriptor, wrong_role_reference),),
                operation_transitions=(
                    _completed_transition(root_running, wrong_role_descriptor.content_hash),
                ),
            )
        assert wrong_role_error.value.code == "generation_replay_manifest_identity_mismatch"
        assert await store.load_operation(job_operation.id) == job_operation

        unrelated_descriptor = object_store.write_json(
            "project-1",
            {"kind": "unrelated-replay"},
        )
        unrelated_reference = replace(
            replay_reference,
            owner_id="unrelated-operation",
            content_hash=unrelated_descriptor.content_hash,
        )
        with pytest.raises(StructuredPrototypeStoreError) as error:
            await store.transition_generation_records(
                job=snapshot.job,
                run=snapshot.latest_run,
                items=snapshot.items,
                expected_job_statuses=("queued",),
                expected_run_statuses=("queued",),
                expected_item_statuses=("pending",),
                descriptors_and_references=((unrelated_descriptor, unrelated_reference),),
                operation_transitions=(root_running,),
            )
        assert error.value.code == "generation_object_identity_mismatch"
        assert await store.load_operation(job_operation.id) == job_operation
        assert await store.load_object("project-1", unrelated_descriptor.content_hash) is None
    finally:
        await store.close()
