from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
import pytest
from structured_prototype_fixtures import (
    fixture_id,
    procurement_document_payload,
    text_insert_batch_payload,
)

from app.adapters.prototype_object_store import PrototypeObjectStore
from app.adapters.prototype_render_artifact_store import PrototypeRenderArtifactStore
from app.adapters.prototype_renderer_worker import PrototypeRendererWorker
from app.adapters.prototype_runtime_worker import PrototypeRuntimeWorker
from app.adapters.structured_prototype_store import (
    AsyncStructuredPrototypeStore,
    StructuredPrototypeStoreError,
)
from app.application.structured_prototype_contracts import (
    DomainCommandBatchV1,
    NewPrototypeDocumentV1,
)
from app.application.structured_prototype_service import (
    StructuredPrototypeService,
    StructuredPrototypeServiceError,
)
from app.domain.structured_prototype import (
    PrototypeObjectDescriptor,
    PrototypeObjectReference,
    PrototypeOperation,
    PrototypeReplayManifestV1,
)

FIXED_NOW = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)


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


class _ReplayReferenceFailingStore(AsyncStructuredPrototypeStore):
    fail_replay_operation_kind: str | None = None

    async def _insert_object_reference(
        self,
        conn: aiosqlite.Connection,
        reference: PrototypeObjectReference,
    ) -> None:
        if (
            self.fail_replay_operation_kind is not None
            and reference.owner_kind == "replay_manifest"
        ):
            row = await (
                await conn.execute(
                    "SELECT operation_kind FROM prototype_operations WHERE id = ?",
                    (reference.owner_id,),
                )
            ).fetchone()
            if row is not None and row[0] == self.fail_replay_operation_kind:
                raise StructuredPrototypeStoreError(
                    "replay_manifest_registration_failed",
                    "test replay manifest registration failure",
                )
        await super()._insert_object_reference(conn, reference)


def _service(
    tmp_path: Path,
    *,
    store: AsyncStructuredPrototypeStore | None = None,
) -> tuple[AsyncStructuredPrototypeStore, PrototypeObjectStore, StructuredPrototypeService]:
    resolved_store = store or AsyncStructuredPrototypeStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "managed-data")
    service = StructuredPrototypeService(
        store=resolved_store,
        object_store=object_store,
        clock=lambda: FIXED_NOW,
    )
    return resolved_store, object_store, service


def _runtime_service(
    tmp_path: Path,
    *,
    store: AsyncStructuredPrototypeStore | None = None,
) -> tuple[AsyncStructuredPrototypeStore, PrototypeObjectStore, StructuredPrototypeService]:
    resolved_store = store or AsyncStructuredPrototypeStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "managed-data")
    service = StructuredPrototypeService(
        store=resolved_store,
        object_store=object_store,
        runtime_worker=PrototypeRuntimeWorker(),
        clock=lambda: FIXED_NOW,
    )
    return resolved_store, object_store, service


async def _load_operation_manifest_reference(
    *,
    store: AsyncStructuredPrototypeStore,
    project_id: str,
    operation_id: str,
) -> tuple[PrototypeOperation, PrototypeObjectDescriptor, PrototypeObjectReference]:
    operation = await store.load_operation(operation_id)
    assert operation is not None
    assert operation.status == "succeeded"
    assert operation.result_manifest_hash is not None
    references = await store.list_object_references(
        project_id,
        "replay_manifest",
        operation_id,
    )
    assert len(references) == 1
    reference = references[0]
    assert reference.payload_type == "replay_manifest"
    descriptor = await store.load_object(project_id, reference.content_hash)
    assert descriptor is not None
    assert operation.result_manifest_hash == descriptor.content_hash == reference.content_hash
    return operation, descriptor, reference


async def _assert_operation_replay_manifest(
    *,
    store: AsyncStructuredPrototypeStore,
    object_store: PrototypeObjectStore,
    project_id: str,
    operation_id: str,
) -> PrototypeReplayManifestV1:
    operation, descriptor, reference = await _load_operation_manifest_reference(
        store=store,
        project_id=project_id,
        operation_id=operation_id,
    )
    assert reference.role == "operation-replay-manifest"
    manifest = PrototypeReplayManifestV1.from_canonical_json(
        object_store.read_canonical_bytes(descriptor)
    )
    assert manifest.operation_id == operation_id
    assert manifest.operation_kind == operation.operation_kind
    assert manifest.terminal_status == "succeeded"
    assert manifest.error_code is None
    return manifest


@pytest.mark.asyncio
async def test_create_and_apply_commit_a_strict_replay_manifest_in_the_business_transaction(
    tmp_path: Path,
) -> None:
    store, object_store, service = _service(tmp_path)
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("replay-manifest-create"),
            document=_new_document(),
        )
        create_manifest = await _assert_operation_replay_manifest(
            store=store,
            object_store=object_store,
            project_id="project-1",
            operation_id=created.operation_id,
        )
        assert create_manifest.result_sequence_no == 0
        assert create_manifest.result_checkpoint_hash == created.state.draft.head_document_hash

        applied = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("replay-manifest-apply"),
            expected_head_sequence_no=created.state.draft.head_sequence_no,
            expected_document_hash=created.state.draft.head_document_hash,
            batch=_text_insert_batch(),
        )
        apply_manifest = await _assert_operation_replay_manifest(
            store=store,
            object_store=object_store,
            project_id="project-1",
            operation_id=applied.operation_id,
        )
        assert apply_manifest.ordered_command_batch_hashes
        assert apply_manifest.base_sequence_no == 0
        assert apply_manifest.result_sequence_no == 1
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_replay_reference_registration_failure_rolls_back_command_head(
    tmp_path: Path,
) -> None:
    store = _ReplayReferenceFailingStore(tmp_path / "console.db")
    store, _, service = _service(tmp_path, store=store)
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("replay-manifest-failure-create"),
            document=_new_document(),
        )
        original_draft = created.state.draft
        store.fail_replay_operation_kind = "apply_command_batch"

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.apply_command_batch(
                draft_id=original_draft.id,
                client_request_id=fixture_id("replay-manifest-failure-apply"),
                expected_head_sequence_no=original_draft.head_sequence_no,
                expected_document_hash=original_draft.head_document_hash,
                batch=_text_insert_batch(),
            )

        assert error.value.code == "replay_manifest_registration_failed"
        persisted = await store.load_draft(original_draft.id)
        assert persisted == original_draft
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_draft_history_checkpoint_recovery_and_delete_operations_have_replay_manifests(
    tmp_path: Path,
) -> None:
    store, object_store, service = _service(tmp_path)
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("replay-groups-create"),
            document=_new_document(),
        )
        recovered = await service.recover_draft(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("replay-groups-recover"),
        )
        applied = await service.apply_command_batch(
            draft_id=recovered.state.draft.id,
            client_request_id=fixture_id("replay-groups-apply"),
            expected_head_sequence_no=recovered.state.draft.head_sequence_no,
            expected_document_hash=recovered.state.draft.head_document_hash,
            batch=_text_insert_batch(),
        )
        undone = await service.undo(
            draft_id=applied.state.draft.id,
            client_request_id=fixture_id("replay-groups-undo"),
            expected_head_sequence_no=applied.state.draft.head_sequence_no,
            expected_document_hash=applied.state.draft.head_document_hash,
        )
        redone = await service.redo(
            draft_id=undone.state.draft.id,
            client_request_id=fixture_id("replay-groups-redo"),
            expected_head_sequence_no=undone.state.draft.head_sequence_no,
            expected_document_hash=undone.state.draft.head_document_hash,
        )
        checkpointed = await service.checkpoint_draft(
            draft_id=redone.state.draft.id,
            client_request_id=fixture_id("replay-groups-checkpoint"),
        )
        no_op_checkpoint = await service.checkpoint_draft(
            draft_id=checkpointed.state.draft.id,
            client_request_id=fixture_id("replay-groups-checkpoint-no-op"),
        )

        conn = await store._get_conn()
        rows = await (
            await conn.execute(
                """
                SELECT id, operation_kind
                FROM prototype_operations
                WHERE project_id = ? AND status = 'succeeded'
                ORDER BY rowid
                """,
                ("project-1",),
            )
        ).fetchall()
        operation_kinds = {str(row[1]) for row in rows}
        assert {
            "create_document",
            "recover_draft",
            "apply_command_batch",
            "undo",
            "redo",
            "create_checkpoint",
        } <= operation_kinds
        for row in rows:
            await _assert_operation_replay_manifest(
                store=store,
                object_store=object_store,
                project_id="project-1",
                operation_id=str(row[0]),
            )

        assert no_op_checkpoint.state.draft.head_sequence_no == 3
        deleted = await service.delete_project_prototype(
            project_id="project-1",
            client_request_id=fixture_id("replay-groups-delete"),
        )
        delete_manifest = await _assert_operation_replay_manifest(
            store=store,
            object_store=object_store,
            project_id="project-1",
            operation_id=deleted.operation_id,
        )
        assert delete_manifest.operation_kind == "delete_project_prototype"
        assert await store.load_draft(created.state.draft.id) is None
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_runtime_operation_groups_have_shared_replay_manifests_and_keep_reset_manifest(
    tmp_path: Path,
) -> None:
    store, object_store, service = _runtime_service(tmp_path)
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("runtime-replay-create"),
            document=_new_document(),
        )
        runtime = await service.create_runtime_session(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("runtime-replay-session"),
            scenario_id=fixture_id("scenario-happy-path"),
            recording_kind="studio_preview",
            actor_subject_id="product-manager-1",
        )
        event_request_id = fixture_id("runtime-replay-event")
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
                        "kind": "fieldValueCommitted",
                        "nodeId": fixture_id("input-title"),
                        "formId": fixture_id("form-create"),
                        "fieldId": fixture_id("form-field-title"),
                        "value": {"type": "string", "value": "采购办公设备"},
                    }
                ],
            },
        )
        checkpointed = await service.checkpoint_runtime_session(
            session_id=runtime.state.session.id,
            client_request_id=fixture_id("runtime-replay-checkpoint"),
        )
        no_op_checkpoint = await service.checkpoint_runtime_session(
            session_id=runtime.state.session.id,
            client_request_id=fixture_id("runtime-replay-checkpoint-no-op"),
        )
        recovered = await service.recover_runtime_session(
            session_id=runtime.state.session.id,
            client_request_id=fixture_id("runtime-replay-recover"),
        )
        reset = await service.reset_runtime_session(
            session_id=runtime.state.session.id,
            client_request_id=fixture_id("runtime-replay-reset"),
            cause_operation_id=None,
            expected_old_head_sequence_no=recovered.state.session.head_sequence_no,
            expected_old_state_hash=recovered.state.session.head_state_hash,
            expected_old_view_model_hash=recovered.state.session.head_view_model_hash,
            expected_old_runtime_core_bundle_hash=(
                recovered.state.session.runtime_core_bundle_hash
            ),
            target_draft_id=created.state.draft.id,
            expected_target_head_sequence_no=created.state.draft.head_sequence_no,
            expected_target_document_hash=created.state.draft.head_document_hash,
            scenario_id=fixture_id("scenario-happy-path"),
        )

        assert applied.state.session.head_sequence_no == 1
        assert checkpointed.state.loaded_checkpoint_sequence_no == 1
        assert no_op_checkpoint.checkpoint_id == checkpointed.checkpoint_id
        assert recovered.state.session.head_state_hash == applied.state.session.head_state_hash
        reset_references = await store.list_object_references(
            "project-1",
            "runtime_session",
            reset.state.session.id,
        )
        assert [reference.content_hash for reference in reset_references] == [
            reset.reset_manifest_hash
        ]

        conn = await store._get_conn()
        rows = await (
            await conn.execute(
                """
                SELECT id, operation_kind
                FROM prototype_operations
                WHERE project_id = ? AND status = 'succeeded'
                ORDER BY rowid
                """,
                ("project-1",),
            )
        ).fetchall()
        operation_kinds = {str(row[1]) for row in rows}
        assert {
            "create_runtime_session",
            "apply_runtime_event",
            "replay_runtime_session",
            "reset_runtime_session",
        } <= operation_kinds
        for row in rows:
            manifest = await _assert_operation_replay_manifest(
                store=store,
                object_store=object_store,
                project_id="project-1",
                operation_id=str(row[0]),
            )
            if manifest.operation_kind in {
                "create_runtime_session",
                "apply_runtime_event",
                "replay_runtime_session",
                "reset_runtime_session",
            }:
                assert manifest.runtime_session_id is not None
                assert manifest.runtime_core_bundle_hash is not None
                assert manifest.runtime_final_state_hash is not None
                assert manifest.runtime_final_view_model_hash is not None
        reset_operation = await store.load_operation(reset.operation_id)
        assert reset_operation is not None
        assert reset_operation.result_manifest_hash != reset.reset_manifest_hash
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_runtime_replay_reference_failure_rolls_back_session_head(
    tmp_path: Path,
) -> None:
    store = _ReplayReferenceFailingStore(tmp_path / "console.db")
    store, _, service = _runtime_service(tmp_path, store=store)
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("runtime-replay-failure-create"),
            document=_new_document(),
        )
        runtime = await service.create_runtime_session(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("runtime-replay-failure-session"),
            scenario_id=fixture_id("scenario-happy-path"),
            recording_kind="studio_preview",
            actor_subject_id=None,
        )
        event_request_id = fixture_id("runtime-replay-failure-event")
        store.fail_replay_operation_kind = "apply_runtime_event"

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.apply_runtime_event_batch(
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

        assert error.value.code == "replay_manifest_registration_failed"
        persisted = await store.load_runtime_session(runtime.state.session.id)
        assert persisted == runtime.state.session
        assert (
            await store.load_runtime_event_batch_by_request(
                runtime.state.session.id,
                event_request_id,
            )
            is None
        )
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_publish_replay_reference_failure_preserves_public_pointer(
    tmp_path: Path,
) -> None:
    store = _ReplayReferenceFailingStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "managed-data")
    service = StructuredPrototypeService(
        store=store,
        object_store=object_store,
        runtime_worker=PrototypeRuntimeWorker(),
        renderer_worker=PrototypeRendererWorker(),
        artifact_store=PrototypeRenderArtifactStore(tmp_path / "render-artifacts"),
        clock=lambda: FIXED_NOW,
    )
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("publish-replay-create"),
            document=_new_document(),
        )
        published = await service.publish_draft(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("publish-replay-first"),
            expected_head_sequence_no=created.state.draft.head_sequence_no,
            expected_document_hash=created.state.draft.head_document_hash,
        )
        _, _, publish_reference = await _load_operation_manifest_reference(
            store=store,
            project_id="project-1",
            operation_id=published.operation_id,
        )
        assert publish_reference.role == "publish-replay-manifest"

        baseline_draft = published.state.draft
        store.fail_replay_operation_kind = "publish"
        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.publish_draft(
                draft_id=baseline_draft.id,
                client_request_id=fixture_id("publish-replay-failure"),
                expected_head_sequence_no=baseline_draft.head_sequence_no,
                expected_document_hash=baseline_draft.head_document_hash,
            )

        assert error.value.code == "replay_manifest_registration_failed"
        current = await store.load_published_record(created.state.document_record.id)
        assert current is not None
        assert current.revision.id == published.publication.revision_id
        persisted_draft = await store.load_draft(baseline_draft.id)
        assert persisted_draft is not None
        assert persisted_draft.status == "active"
        assert persisted_draft.head_sequence_no == baseline_draft.head_sequence_no
        assert persisted_draft.head_document_hash == baseline_draft.head_document_hash
    finally:
        await store.close()
