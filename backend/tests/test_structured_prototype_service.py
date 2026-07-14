from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from structured_prototype_fixtures import (
    fixture_id,
    procurement_document_payload,
    text_insert_batch_payload,
)

from app.adapters.prototype_object_store import PrototypeObjectStore
from app.adapters.prototype_render_artifact_store import PrototypeRenderArtifactStore
from app.adapters.prototype_renderer_worker import (
    PrototypeRendererWorker,
    PrototypeRendererWorkerError,
)
from app.adapters.prototype_runtime_worker import PrototypeRuntimeWorker
from app.adapters.structured_prototype_store import AsyncStructuredPrototypeStore
from app.application.structured_prototype_contracts import (
    DomainCommandBatchV1,
    NewPrototypeDocumentV1,
    document_hash,
)
from app.application.structured_prototype_service import (
    StructuredPrototypeService,
    StructuredPrototypeServiceError,
)
from app.domain.structured_prototype import (
    PrototypeRendererWorkerIdentity,
    PrototypeRendererWorkerResult,
)

FIXED_NOW = datetime(2026, 7, 13, 8, 0, tzinfo=UTC)


def _new_document() -> NewPrototypeDocumentV1:
    payload = procurement_document_payload()
    payload.pop("id")
    return NewPrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _text_insert_batch() -> DomainCommandBatchV1:
    return DomainCommandBatchV1.model_validate(
        text_insert_batch_payload(),
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _service(
    db_path: Path,
    object_root: Path,
) -> tuple[AsyncStructuredPrototypeStore, StructuredPrototypeService]:
    store = AsyncStructuredPrototypeStore(db_path)
    service = StructuredPrototypeService(
        store=store,
        object_store=PrototypeObjectStore(object_root),
        clock=lambda: FIXED_NOW,
    )
    return store, service


def _runtime_service(
    db_path: Path,
    object_root: Path,
) -> tuple[AsyncStructuredPrototypeStore, StructuredPrototypeService]:
    store = AsyncStructuredPrototypeStore(db_path)
    service = StructuredPrototypeService(
        store=store,
        object_store=PrototypeObjectStore(object_root),
        runtime_worker=PrototypeRuntimeWorker(),
        clock=lambda: FIXED_NOW,
    )
    return store, service


class _FailingRenderer:
    def __init__(self, identity: PrototypeRendererWorkerIdentity) -> None:
        self.identity = identity

    async def render(
        self,
        *,
        request_id: str,
        artifact_id: str,
        input_manifest: dict[str, object],
        document: dict[str, object],
    ) -> PrototypeRendererWorkerResult:
        del request_id, artifact_id, input_manifest, document
        raise PrototypeRendererWorkerError(
            "renderer_intentional_failure",
            "intentional renderer failure",
        )


class _BlockingRenderer:
    def __init__(self, identity: PrototypeRendererWorkerIdentity) -> None:
        self.identity = identity
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def render(
        self,
        *,
        request_id: str,
        artifact_id: str,
        input_manifest: dict[str, object],
        document: dict[str, object],
    ) -> PrototypeRendererWorkerResult:
        del request_id, artifact_id, input_manifest, document
        self.started.set()
        await self.release.wait()
        raise AssertionError("blocking renderer must be cancelled by the test")


def _publication_service(
    db_path: Path,
    object_root: Path,
    artifact_root: Path,
    *,
    renderer: PrototypeRendererWorker | _FailingRenderer | _BlockingRenderer | None = None,
) -> tuple[AsyncStructuredPrototypeStore, StructuredPrototypeService, PrototypeRendererWorker]:
    store = AsyncStructuredPrototypeStore(db_path)
    real_renderer = PrototypeRendererWorker()
    service = StructuredPrototypeService(
        store=store,
        object_store=PrototypeObjectStore(object_root),
        runtime_worker=PrototypeRuntimeWorker(),
        renderer_worker=renderer or real_renderer,
        artifact_store=PrototypeRenderArtifactStore(artifact_root),
        clock=lambda: FIXED_NOW,
    )
    return store, service, real_renderer


@pytest.mark.asyncio
async def test_create_apply_retry_and_restart_recover_the_same_document_hash(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "console.db"
    object_root = tmp_path / "managed-data"
    store, service = _service(db_path, object_root)
    create_request_id = fixture_id("service-create-request")
    apply_request_id = fixture_id("service-apply-request")

    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=create_request_id,
            document=_new_document(),
        )
        applied = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=apply_request_id,
            expected_head_sequence_no=0,
            expected_document_hash=created.state.draft.head_document_hash,
            batch=_text_insert_batch(),
        )
        retried = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=apply_request_id,
            expected_head_sequence_no=0,
            expected_document_hash=created.state.draft.head_document_hash,
            batch=_text_insert_batch(),
        )

        assert applied.state.draft.head_sequence_no == 1
        assert applied.state.draft.head_document_hash == document_hash(applied.state.document)
        assert retried.operation_id == applied.operation_id
        assert retried.applied_batch_id == applied.applied_batch_id
        assert retried.allocated_entity_ids == applied.allocated_entity_ids
        assert len(await store.list_operation_events(applied.operation_id)) == 3
        expected_hash = applied.state.draft.head_document_hash
        draft_id = applied.state.draft.id
    finally:
        await store.close()

    reopened_store, reopened_service = _service(db_path, object_root)
    try:
        recovery = await reopened_service.recover_draft(
            draft_id=draft_id,
            client_request_id=fixture_id("service-restart-recovery"),
        )
        recovered = recovery.state

        assert recovered.draft.head_sequence_no == 1
        assert recovered.draft.head_document_hash == expected_hash
        assert document_hash(recovered.document) == expected_hash
        assert len(recovered.applied_tail_batch_ids) == 1
    finally:
        await reopened_store.close()


@pytest.mark.asyncio
async def test_create_retry_returns_the_existing_durable_draft(tmp_path: Path) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    request_id = fixture_id("service-create-idempotent")
    try:
        first = await service.create_document(
            project_id="project-1",
            client_request_id=request_id,
            document=_new_document(),
        )
        second = await service.create_document(
            project_id="project-1",
            client_request_id=request_id,
            document=_new_document(),
        )

        assert second.operation_id == first.operation_id
        assert second.state.draft.id == first.state.draft.id
        assert second.state.draft.head_document_hash == first.state.draft.head_document_hash
        assert len(await store.list_operation_events(first.operation_id)) == 3
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_corrupt_checkpoint_object_marks_draft_corrupt_with_failure_evidence(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "console.db"
    object_root = tmp_path / "managed-data"
    store, service = _service(db_path, object_root)
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-create-corrupt"),
            document=_new_document(),
        )
        recovery_request_id = fixture_id("service-corrupt-recovery")
        successful_recovery = await service.recover_draft(
            draft_id=created.state.draft.id,
            client_request_id=recovery_request_id,
        )
        bundle = await store.load_draft_recovery_bundle(created.state.draft.id)
        object_path = object_root / bundle.object_descriptor.storage_key
        payload = bytearray(object_path.read_bytes())
        payload[-1] ^= 0x01
        object_path.write_bytes(payload)

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.recover_draft(
                draft_id=created.state.draft.id,
                client_request_id=recovery_request_id,
            )

        assert error.value.code == "object_hash_mismatch"
        draft = await store.load_draft(created.state.draft.id)
        assert draft is not None
        assert draft.status == "corrupt"
        operation_id = error.value.operation_id
        assert operation_id is not None
        assert operation_id != successful_recovery.operation_id
        assert [item.status for item in await store.list_operation_events(operation_id)] == [
            "queued",
            "running",
            "failed",
        ]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_stale_apply_fails_with_current_head_and_durable_operation_evidence(
    tmp_path: Path,
) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-create-conflict"),
            document=_new_document(),
        )
        applied = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-first-command"),
            expected_head_sequence_no=0,
            expected_document_hash=created.state.draft.head_document_hash,
            batch=_text_insert_batch(),
        )

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.apply_command_batch(
                draft_id=created.state.draft.id,
                client_request_id=fixture_id("service-stale-command"),
                expected_head_sequence_no=0,
                expected_document_hash=created.state.draft.head_document_hash,
                batch=_text_insert_batch(),
            )

        assert error.value.code == "draft_conflict"
        assert error.value.current_head_sequence_no == 1
        assert error.value.current_document_hash == applied.state.draft.head_document_hash
        operation_id = error.value.operation_id
        assert operation_id is not None
        assert [item.status for item in await store.list_operation_events(operation_id)] == [
            "queued",
            "running",
            "failed",
        ]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_checkpoint_materializes_the_current_head_and_resets_replay_tail(
    tmp_path: Path,
) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-create-checkpoint"),
            document=_new_document(),
        )
        applied = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-command-before-checkpoint"),
            expected_head_sequence_no=0,
            expected_document_hash=created.state.draft.head_document_hash,
            batch=_text_insert_batch(),
        )
        checkpoint_request_id = fixture_id("service-checkpoint-head")
        checkpointed = await service.checkpoint_draft(
            draft_id=created.state.draft.id,
            client_request_id=checkpoint_request_id,
        )
        retried = await service.checkpoint_draft(
            draft_id=created.state.draft.id,
            client_request_id=checkpoint_request_id,
        )
        bundle = await store.load_draft_recovery_bundle(created.state.draft.id)

        assert checkpointed.state.draft.head_sequence_no == 1
        assert checkpointed.state.draft.head_document_hash == applied.state.draft.head_document_hash
        assert checkpointed.state.loaded_checkpoint_sequence_no == 1
        assert checkpointed.state.applied_tail_batch_ids == ()
        assert retried.checkpoint_id == checkpointed.checkpoint_id
        assert bundle.checkpoint.id == checkpointed.checkpoint_id
        assert bundle.checkpoint.checkpoint_sequence_no == 1
        assert bundle.command_batches == ()
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_runtime_session_apply_retry_and_recover_use_the_node_worker(
    tmp_path: Path,
) -> None:
    store, service = _runtime_service(tmp_path / "console.db", tmp_path / "managed-data")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("runtime-service-document"),
            document=_new_document(),
        )
        runtime = await service.create_runtime_session(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("runtime-service-session"),
            scenario_id=fixture_id("scenario-happy-path"),
            recording_kind="studio_preview",
            actor_subject_id="product-manager-1",
        )
        event_request_id = fixture_id("runtime-service-field-event")
        batch: dict[str, object] = {
            "clientEventId": event_request_id,
            "expectedSequenceNo": 0,
            "events": [
                {
                    "kind": "fieldValueCommitted",
                    "nodeId": fixture_id("input-title"),
                    "formId": fixture_id("form-create"),
                    "fieldId": fixture_id("form-field-title"),
                    "value": {"type": "string", "value": "采购办公设备"},
                }
            ],
        }
        applied = await service.apply_runtime_event_batch(
            session_id=runtime.state.session.id,
            client_request_id=event_request_id,
            expected_head_sequence_no=0,
            expected_state_hash=runtime.state.session.head_state_hash,
            batch=batch,
        )
        retried = await service.apply_runtime_event_batch(
            session_id=runtime.state.session.id,
            client_request_id=event_request_id,
            expected_head_sequence_no=0,
            expected_state_hash=runtime.state.session.head_state_hash,
            batch=batch,
        )
        checkpoint_request_id = fixture_id("runtime-service-checkpoint")
        checkpointed = await service.checkpoint_runtime_session(
            session_id=runtime.state.session.id,
            client_request_id=checkpoint_request_id,
        )
        checkpoint_retry = await service.checkpoint_runtime_session(
            session_id=runtime.state.session.id,
            client_request_id=checkpoint_request_id,
        )
        recovered = await service.recover_runtime_session(
            session_id=runtime.state.session.id,
            client_request_id=fixture_id("runtime-service-recover"),
        )

        assert runtime.state.session.runtime_core_version == "0.1.0-spike"
        assert runtime.state.session.state_machine_kernel_version == "5.32.4"
        assert applied.state.session.head_sequence_no == 1
        assert applied.outcome == "applied"
        assert retried.event_batch_id == applied.event_batch_id
        assert checkpointed.state.loaded_checkpoint_sequence_no == 1
        assert checkpoint_retry.checkpoint_id == checkpointed.checkpoint_id
        assert recovered.state.session.head_state_hash == applied.state.session.head_state_hash
        assert recovered.state.state_json == applied.state.state_json
        assert recovered.state.view_model_json == applied.state.view_model_json
        assert recovered.state.replayed_event_batch_ids == ()
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_runtime_replay_evidence_mismatch_marks_session_corrupt(
    tmp_path: Path,
) -> None:
    store, service = _runtime_service(tmp_path / "console.db", tmp_path / "managed-data")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("runtime-corrupt-document"),
            document=_new_document(),
        )
        runtime = await service.create_runtime_session(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("runtime-corrupt-session"),
            scenario_id=fixture_id("scenario-happy-path"),
            recording_kind="recorded_review",
            actor_subject_id=None,
        )
        event_request_id = fixture_id("runtime-corrupt-event")
        applied = await service.apply_runtime_event_batch(
            session_id=runtime.state.session.id,
            client_request_id=event_request_id,
            expected_head_sequence_no=0,
            expected_state_hash=runtime.state.session.head_state_hash,
            batch={
                "clientEventId": event_request_id,
                "expectedSequenceNo": 0,
                "events": [
                    {
                        "kind": "switchSimulatedRole",
                        "roleId": fixture_id("role-applicant"),
                    }
                ],
            },
        )
        conn = await store._get_conn()
        await conn.execute(
            "UPDATE prototype_runtime_event_batches SET guard_report_hash = ? WHERE id = ?",
            ("sha256:" + "f" * 64, applied.event_batch_id),
        )
        await conn.commit()

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.recover_runtime_session(
                session_id=runtime.state.session.id,
                client_request_id=fixture_id("runtime-corrupt-recovery"),
            )

        assert error.value.code == "runtime_replay_evidence_mismatch"
        persisted = await store.load_runtime_session(runtime.state.session.id)
        assert persisted is not None
        assert persisted.status == "corrupt"
        operation_id = error.value.operation_id
        assert operation_id is not None
        assert [item.status for item in await store.list_operation_events(operation_id)] == [
            "queued",
            "running",
            "failed",
        ]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_runtime_worker_unavailable_records_failed_operation(tmp_path: Path) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("runtime-unavailable-document"),
            document=_new_document(),
        )

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.create_runtime_session(
                draft_id=created.state.draft.id,
                client_request_id=fixture_id("runtime-unavailable-session"),
                scenario_id=fixture_id("scenario-happy-path"),
                recording_kind="studio_preview",
                actor_subject_id=None,
            )

        assert error.value.code == "runtime_worker_unavailable"
        operation_id = error.value.operation_id
        assert operation_id is not None
        assert [item.status for item in await store.list_operation_events(operation_id)] == [
            "queued",
            "running",
            "failed",
        ]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_publish_is_idempotent_observable_and_serves_verified_artifact(
    tmp_path: Path,
) -> None:
    store, service, _ = _publication_service(
        tmp_path / "console.db",
        tmp_path / "objects",
        tmp_path / "managed-data",
    )
    request_id = fixture_id("publication-success")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("publication-document"),
            document=_new_document(),
        )
        first = await service.publish_draft(
            draft_id=created.state.draft.id,
            client_request_id=request_id,
            expected_head_sequence_no=0,
            expected_document_hash=created.state.draft.head_document_hash,
        )
        retried = await service.publish_draft(
            draft_id=created.state.draft.id,
            client_request_id=request_id,
            expected_head_sequence_no=0,
            expected_document_hash=created.state.draft.head_document_hash,
        )
        current = await service.get_published_prototype(created.state.document_record.id)
        index = await service.read_published_file(
            document_id=created.state.document_record.id,
            revision_no=first.publication.revision_no,
            artifact_id=first.publication.artifact_id,
            relative_path="index.html",
        )

        assert retried.operation_id == first.operation_id
        assert retried.publication == first.publication
        assert retried.state.draft.id == first.state.draft.id
        assert first.publication.revision_no == 1
        assert first.state.draft.id != created.state.draft.id
        assert first.state.draft.base_revision_no == 1
        assert first.state.draft.head_sequence_no == 0
        assert current == first.publication
        assert b'<script src="./runtime.js" defer></script>' in index.content
        assert [event.status for event in await store.list_operation_events(first.operation_id)] == [
            "queued",
            "running",
            "succeeded",
            "running",
            "succeeded",
            "running",
            "succeeded",
        ]
        closed = await store.load_draft(created.state.draft.id)
        assert closed is not None
        assert closed.status == "closed"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_render_failure_restores_draft_and_preserves_previous_publication(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "console.db"
    object_root = tmp_path / "objects"
    artifact_root = tmp_path / "managed-data"
    store, service, real_renderer = _publication_service(db_path, object_root, artifact_root)
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("publication-failure-document"),
            document=_new_document(),
        )
        first = await service.publish_draft(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("publication-before-failure"),
            expected_head_sequence_no=0,
            expected_document_hash=created.state.draft.head_document_hash,
        )
        edited = await service.apply_command_batch(
            draft_id=first.state.draft.id,
            client_request_id=fixture_id("publication-edit-before-failure"),
            expected_head_sequence_no=0,
            expected_document_hash=first.state.draft.head_document_hash,
            batch=_text_insert_batch(),
        )
        failing_service = StructuredPrototypeService(
            store=store,
            object_store=PrototypeObjectStore(object_root),
            runtime_worker=PrototypeRuntimeWorker(),
            renderer_worker=_FailingRenderer(real_renderer.identity),
            artifact_store=PrototypeRenderArtifactStore(artifact_root),
            clock=lambda: FIXED_NOW,
        )

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await failing_service.publish_draft(
                draft_id=edited.state.draft.id,
                client_request_id=fixture_id("publication-render-failure"),
                expected_head_sequence_no=edited.state.draft.head_sequence_no,
                expected_document_hash=edited.state.draft.head_document_hash,
            )

        assert error.value.code == "renderer_intentional_failure"
        restored = await store.load_draft(edited.state.draft.id)
        assert restored is not None
        assert restored.status == "active"
        assert restored.head_document_hash == edited.state.draft.head_document_hash
        current = await service.get_published_prototype(created.state.document_record.id)
        assert current == first.publication
        assert error.value.operation_id is not None
        run = await store.load_render_run_by_operation(error.value.operation_id)
        assert run is not None
        assert run.status == "failed"
        assert run.error_code == "renderer_intentional_failure"
        events = await store.list_operation_events(error.value.operation_id)
        assert events[-1].status == "failed"
        assert events[-1].error_code == "renderer_intentional_failure"
        assert events[-1].evidence_hash is not None
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_startup_recovery_interrupts_render_and_reactivates_publishing_draft(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "console.db"
    object_root = tmp_path / "objects"
    artifact_root = tmp_path / "managed-data"
    real_renderer = PrototypeRendererWorker()
    blocking_renderer = _BlockingRenderer(real_renderer.identity)
    store, service, _ = _publication_service(
        db_path,
        object_root,
        artifact_root,
        renderer=blocking_renderer,
    )
    created = await service.create_document(
        project_id="project-1",
        client_request_id=fixture_id("publication-interrupted-document"),
        document=_new_document(),
    )
    publish_task = asyncio.create_task(
        service.publish_draft(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("publication-interrupted-render"),
            expected_head_sequence_no=0,
            expected_document_hash=created.state.draft.head_document_hash,
        )
    )
    await asyncio.wait_for(blocking_renderer.started.wait(), timeout=5)
    publishing = await store.load_draft(created.state.draft.id)
    assert publishing is not None
    assert publishing.status == "publishing"
    publish_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await publish_task
    await store.close()

    reopened_store = AsyncStructuredPrototypeStore(db_path)
    recovery_service = StructuredPrototypeService(
        store=reopened_store,
        object_store=PrototypeObjectStore(object_root),
        clock=lambda: FIXED_NOW,
    )
    try:
        recovered_count = await recovery_service.recover_interrupted_publications()
        restored = await reopened_store.load_draft(created.state.draft.id)
        conn = await reopened_store._get_conn()
        run_row = await (
            await conn.execute(
                "SELECT status, error_code, operation_id FROM prototype_render_runs"
            )
        ).fetchone()

        assert recovered_count == 1
        assert restored is not None
        assert restored.status == "active"
        assert run_row is not None
        assert tuple(run_row[:2]) == ("interrupted", "service_restart")
        operation = await reopened_store.load_operation(str(run_row[2]))
        assert operation is not None
        assert operation.status == "interrupted"
        assert operation.error_code == "service_restart"
        assert await recovery_service.get_published_prototype(
            created.state.document_record.id
        ) is None
    finally:
        await reopened_store.close()
