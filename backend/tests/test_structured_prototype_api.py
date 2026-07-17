from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structured_prototype_fixtures import (
    fixture_id,
    procurement_document_payload,
    text_insert_batch_payload,
)

import app.interfaces.structured_prototype_api as structured_api
from app.adapters.prototype_object_store import PrototypeObjectStore
from app.adapters.prototype_render_artifact_store import PrototypeRenderArtifactStore
from app.adapters.prototype_renderer_worker import PrototypeRendererWorker
from app.adapters.prototype_runtime_worker import PrototypeRuntimeWorker
from app.adapters.structured_prototype_store import (
    AsyncStructuredPrototypeStore,
    StructuredPrototypeStoreError,
)
from app.application.structured_prototype_contracts import freeform_grid_list_hash
from app.application.structured_prototype_service import (
    SNAP_WORKER_INFRASTRUCTURE_ERROR_CODES,
    StructuredPrototypeService,
)
from app.domain.structured_prototype import PrototypeOperation, PrototypeOperationEvent


def _client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, AsyncStructuredPrototypeStore]:
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    monkeypatch.setattr(
        structured_api,
        "structured_prototype_service",
        StructuredPrototypeService(
            store=store,
            object_store=PrototypeObjectStore(tmp_path / "managed-data"),
            runtime_worker=PrototypeRuntimeWorker(),
            renderer_worker=PrototypeRendererWorker(),
            artifact_store=PrototypeRenderArtifactStore(tmp_path / "managed-data"),
            clock=lambda: datetime(2026, 7, 13, 8, 0, tzinfo=UTC),
        ),
    )
    app = FastAPI()
    app.include_router(structured_api.router)
    return TestClient(app), store


def _create_body(request_id: str) -> dict[str, object]:
    document = procurement_document_payload()
    document.pop("id")
    return {
        "contractVersion": 1,
        "clientRequestId": request_id,
        "document": document,
    }


@pytest.mark.parametrize(
    "code",
    [
        "command_evidence_mismatch",
        "command_target_in_use",
        "command_result_invalid",
        "command_value_invalid",
    ],
)
def test_command_semantic_errors_map_to_unprocessable_entity(code: str) -> None:
    assert structured_api._status_for_error(code) == 422


@pytest.mark.parametrize("code", sorted(SNAP_WORKER_INFRASTRUCTURE_ERROR_CODES))
def test_snap_worker_infrastructure_errors_map_to_service_unavailable(code: str) -> None:
    assert structured_api._status_for_error(code) == 503


def test_freeform_move_evidence_context_mismatch_returns_422_with_durable_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    request_id = fixture_id("api-move-evidence-mismatch")
    with client:
        created_response = client.post(
            "/api/projects/project-1/structured-prototype-documents",
            json=_create_body(fixture_id("api-move-evidence-mismatch-create")),
        )
        assert created_response.status_code == 201
        created = created_response.json()
        response = client.post(
            f"/api/structured-prototype-drafts/{created['draftId']}/commands",
            json={
                "contractVersion": 1,
                "clientRequestId": request_id,
                "expectedHeadSequenceNo": 0,
                "expectedDocumentHash": created["documentHash"],
                "batch": {
                    "commandContractVersion": 1,
                    "summary": "移动自由布局组件",
                    "commands": [
                        {
                            "kind": "moveNode",
                            "node": {
                                "kind": "existing",
                                "nodeId": fixture_id("title-list"),
                            },
                            "targetParent": {
                                "kind": "existing",
                                "nodeId": fixture_id("root-list"),
                            },
                            "targetSlot": None,
                            "targetIndex": 0,
                            "targetPosition": {"x": "40", "y": "52"},
                        }
                    ],
                    "evidence": {
                        "evidenceVersion": 2,
                        "kind": "freeformMove",
                        "snapSolverVersion": "structured-prototype-freeform-snap/v1",
                        "snapSolverSourceHash": "sha256:" + "f" * 64,
                        "documentId": created["documentId"],
                        "draftId": created["draftId"],
                        "freeformId": fixture_id("root-list"),
                        "baseHeadSequenceNo": 0,
                        "baseDocumentHash": created["documentHash"],
                        "selectedNodeIds": [fixture_id("title-list")],
                        "grids": [],
                        "gridListHash": freeform_grid_list_hash(()),
                        "gridSnappingEnabled": True,
                        "previewScale": "1",
                        "clientThreshold": "6",
                        "selectionBounds": {
                            "x": "32",
                            "y": "48",
                            "width": "300",
                            "height": "40",
                        },
                        "directSiblings": [],
                        "containerSize": {"width": "1200", "height": "800"},
                        "requestedDelta": {"x": "8", "y": "4"},
                        "rawPosition": {"x": "40", "y": "52"},
                        "finalPosition": {"x": "40", "y": "52"},
                        "correction": {"x": "0", "y": "0"},
                        "bypassSnapping": True,
                        "axisWinners": {"x": "raw", "y": "raw"},
                        "candidates": [],
                        "terminalReason": "pointerup",
                    },
                },
            },
        )

        assert response.status_code == 422
        failure = response.json()
        assert failure["error"]["code"] == "command_evidence_mismatch"
        assert failure["error"]["retryable"] is False
        assert failure["error"]["currentHeadSequenceNo"] == 0
        assert failure["error"]["currentDocumentHash"] == created["documentHash"]
        assert failure["operationId"] is not None
        assert client.portal is not None
        operation = client.portal.call(store.load_operation, failure["operationId"])
        assert operation is not None
        assert operation.status == "failed"
        assert operation.error_code == "command_evidence_mismatch"
        assert operation.failure_evidence_hash is not None
        stored_batch = client.portal.call(
            store.load_command_batch_by_request,
            created["draftId"],
            request_id,
        )
        assert stored_batch is None
        client.portal.call(store.close)


def test_runtime_worker_identity_mismatch_is_service_unavailable_not_reset_conflict() -> None:
    assert structured_api._runtime_status_for_error("runtime_worker_identity_mismatch") == 503


def test_operation_outcome_reports_terminal_nonterminal_unknown_and_project_isolation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    create_request_id = fixture_id("api-operation-outcome-create")
    queued_request_id = fixture_id("api-operation-outcome-queued")
    hash_a = "sha256:" + "a" * 64
    hash_b = "sha256:" + "b" * 64
    queued = PrototypeOperation(
        id=fixture_id("api-operation-outcome-queued-operation"),
        operation_kind="ai_edit",
        project_id="project-1",
        resource_kind="ai_edit_run",
        resource_id=fixture_id("api-operation-outcome-ai-run"),
        client_request_id=queued_request_id,
        correlation_id=fixture_id("api-operation-outcome-correlation"),
        parent_operation_id=None,
        status="queued",
        phase="queued",
        attempt=1,
        request_manifest_hash=hash_a,
        config_manifest_hash=hash_b,
        result_manifest_hash=None,
        failure_evidence_hash=None,
        error_code=None,
        created_at=datetime(2026, 7, 13, 8, 1, tzinfo=UTC),
        started_at=None,
        completed_at=None,
    )
    queued_event = PrototypeOperationEvent(
        operation_id=queued.id,
        event_no=0,
        step_id=None,
        event_kind="operation_queued",
        status="queued",
        phase="queued",
        input_hash=queued.request_manifest_hash,
        output_hash=None,
        evidence_hash=None,
        error_code=None,
        occurred_at=queued.created_at,
    )
    with client:
        created_response = client.post(
            "/api/projects/project-1/structured-prototype-documents",
            json=_create_body(create_request_id),
        )
        assert created_response.status_code == 201
        created = created_response.json()

        terminal_response = client.get(
            "/api/projects/project-1/structured-prototype-operations/outcome",
            params={
                "operationKind": "create_document",
                "clientRequestId": create_request_id,
            },
        )
        assert terminal_response.status_code == 200
        terminal = terminal_response.json()
        assert terminal["contractVersion"] == 1
        assert terminal["known"] is True
        assert terminal["terminal"] is True
        assert terminal["operationId"] == created["operationId"]
        assert terminal["operationKind"] == "create_document"
        assert terminal["projectId"] == "project-1"
        assert terminal["resourceKind"] == "document"
        assert terminal["resourceId"] == created["documentId"]
        assert terminal["status"] == "succeeded"
        assert terminal["resultManifestHash"].startswith("sha256:")
        assert terminal["completedAt"] is not None

        assert client.portal is not None
        client.portal.call(store.create_operation, queued, queued_event)
        nonterminal_response = client.get(
            "/api/projects/project-1/structured-prototype-operations/outcome",
            params={
                "operationKind": "ai_edit",
                "clientRequestId": queued_request_id,
            },
        )
        assert nonterminal_response.status_code == 200
        nonterminal = nonterminal_response.json()
        assert nonterminal["known"] is True
        assert nonterminal["terminal"] is False
        assert nonterminal["status"] == "queued"
        assert nonterminal["resourceKind"] == "ai_edit_run"
        assert nonterminal["resourceId"] == queued.resource_id
        assert nonterminal["resultManifestHash"] is None
        assert nonterminal["completedAt"] is None

        isolated_response = client.get(
            "/api/projects/project-2/structured-prototype-operations/outcome",
            params={
                "operationKind": "create_document",
                "clientRequestId": create_request_id,
            },
        )
        assert isolated_response.status_code == 404
        isolated = isolated_response.json()
        assert isolated["error"]["code"] == "operation_outcome_unknown"
        assert isolated["error"]["retryable"] is True
        assert isolated["operationId"] is None

        unknown_response = client.get(
            "/api/projects/project-1/structured-prototype-operations/outcome",
            params={
                "operationKind": "publish",
                "clientRequestId": fixture_id("api-operation-outcome-unknown"),
            },
        )
        assert unknown_response.status_code == 404
        assert unknown_response.json()["error"]["code"] == "operation_outcome_unknown"

        invalid_kind_response = client.get(
            "/api/projects/project-1/structured-prototype-operations/outcome",
            params={
                "operationKind": "not-a-real-operation",
                "clientRequestId": create_request_id,
            },
        )
        assert invalid_kind_response.status_code == 422
        assert invalid_kind_response.json()["error"]["code"] == "request_invalid"

        client.portal.call(store.close)


def test_operation_detail_and_events_expose_replay_lineage_and_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    project_id = fixture_id("api-operation-detail-project")
    create_request_id = fixture_id("api-operation-detail-create")
    with client:
        created_response = client.post(
            f"/api/projects/{project_id}/structured-prototype-documents",
            json=_create_body(create_request_id),
        )
        assert created_response.status_code == 201
        created = created_response.json()
        operation_id = created["operationId"]

        detail_response = client.get(f"/api/prototype-operations/{operation_id}")
        assert detail_response.status_code == 200, detail_response.text
        detail = detail_response.json()
        assert detail["contractVersion"] == 1
        assert detail["operation"]["operationId"] == operation_id
        assert detail["operation"]["projectId"] == project_id
        assert detail["operation"]["status"] == "succeeded"
        assert detail["childOperationIds"] == []
        assert [step["status"] for step in detail["steps"]] == ["succeeded"]
        assert detail["replayManifest"]["operationId"] == operation_id
        assert detail["replayManifest"]["operationKind"] == "create_document"
        assert (
            detail["replayManifest"]["requestManifestHash"]
            == detail["operation"]["requestManifestHash"]
        )
        assert detail["replayManifest"]["versions"]["replayManifestVersion"] == 1

        events_response = client.get(f"/api/prototype-operations/{operation_id}/events")
        assert events_response.status_code == 200
        events = events_response.json()
        assert events["operationId"] == operation_id
        assert [event["eventNo"] for event in events["events"]] == [0, 1, 2]
        assert [event["status"] for event in events["events"]] == [
            "queued",
            "running",
            "succeeded",
        ]

        assert client.portal is not None
        parent = client.portal.call(store.load_operation, operation_id)
        assert parent is not None
        child_ids = [
            fixture_id("api-operation-detail-child-a"),
            fixture_id("api-operation-detail-child-b"),
        ]
        for index, child_id in enumerate(reversed(child_ids), start=1):
            child = PrototypeOperation(
                id=child_id,
                operation_kind="ai_edit",
                project_id=project_id,
                resource_kind="ai_edit_run",
                resource_id=fixture_id(f"api-operation-detail-run-{index}"),
                client_request_id=fixture_id(f"api-operation-detail-request-{index}"),
                correlation_id=fixture_id(f"api-operation-detail-correlation-{index}"),
                parent_operation_id=operation_id,
                status="queued",
                phase="queued",
                attempt=1,
                request_manifest_hash="sha256:" + "a" * 64,
                config_manifest_hash="sha256:" + "b" * 64,
                result_manifest_hash=None,
                failure_evidence_hash=None,
                error_code=None,
                created_at=parent.created_at + timedelta(seconds=1),
                started_at=None,
                completed_at=None,
            )
            child_event = PrototypeOperationEvent(
                operation_id=child.id,
                event_no=0,
                step_id=None,
                event_kind="operation_queued",
                status="queued",
                phase="queued",
                input_hash=child.request_manifest_hash,
                output_hash=None,
                evidence_hash=None,
                error_code=None,
                occurred_at=child.created_at,
            )
            client.portal.call(store.create_operation, child, child_event)

        lineage_response = client.get(f"/api/prototype-operations/{operation_id}")
        assert lineage_response.status_code == 200
        assert lineage_response.json()["childOperationIds"] == sorted(child_ids)
        child_response = client.get(f"/api/prototype-operations/{child_ids[0]}")
        assert child_response.status_code == 200
        assert child_response.json()["operation"]["parentOperationId"] == operation_id
        assert child_response.json()["replayManifest"] is None

        unknown_id = fixture_id("api-operation-detail-missing")
        unknown_response = client.get(f"/api/prototype-operations/{unknown_id}")
        assert unknown_response.status_code == 404
        assert unknown_response.json()["error"]["code"] == "operation_missing"
        invalid_response = client.get("/api/prototype-operations/NOT-A-CANONICAL-UUID")
        assert invalid_response.status_code == 422
        assert invalid_response.json()["error"]["code"] == "operation_id_invalid"

        original_load_object = store.load_object

        async def fail_replay_descriptor_read(
            project_id: str,
            content_hash: str,
        ) -> None:
            del project_id, content_hash
            raise StructuredPrototypeStoreError(
                "object_corrupt",
                "test replay descriptor corruption",
            )

        monkeypatch.setattr(store, "load_object", fail_replay_descriptor_read)
        store_failure_response = client.get(f"/api/prototype-operations/{operation_id}")
        assert store_failure_response.status_code == 500
        assert store_failure_response.json()["error"]["code"] == ("operation_observability_corrupt")
        monkeypatch.setattr(store, "load_object", original_load_object)

        async def corrupt_replay_reference() -> None:
            conn = await store._get_conn()
            await conn.execute(
                "UPDATE prototype_operations SET result_manifest_hash = ? WHERE id = ?",
                ("sha256:" + "f" * 64, operation_id),
            )
            await conn.commit()

        client.portal.call(corrupt_replay_reference)
        corrupt_response = client.get(f"/api/prototype-operations/{operation_id}")
        assert corrupt_response.status_code == 500
        assert corrupt_response.json()["error"]["code"] == "operation_replay_manifest_missing"

        client.portal.call(store.close)


def test_create_get_apply_and_conflict_use_typed_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    with client:
        empty_current_response = client.get(
            "/api/projects/project-1/structured-prototype-documents/current",
            params={"clientRequestId": fixture_id("api-empty-current")},
        )
        assert empty_current_response.status_code == 200
        assert empty_current_response.json() is None

        created_response = client.post(
            "/api/projects/project-1/structured-prototype-documents",
            json=_create_body(fixture_id("api-create-request")),
        )
        assert created_response.status_code == 201
        created = created_response.json()
        assert created["contractVersion"] == 1
        assert created["headSequenceNo"] == 0
        assert created["canUndo"] is False
        assert created["canRedo"] is False
        assert created["document"]["schemaVersion"] == 1
        assert "schema_version" not in created["document"]

        current_response = client.get(
            "/api/projects/project-1/structured-prototype-documents/current",
            params={"clientRequestId": fixture_id("api-current-document")},
        )
        assert current_response.status_code == 200
        current = current_response.json()
        assert current["documentId"] == created["documentId"]
        assert current["draftId"] == created["draftId"]
        assert current["operationId"] != created["operationId"]

        recovered_response = client.get(
            f"/api/structured-prototype-drafts/{created['draftId']}",
            params={"clientRequestId": fixture_id("api-get-request")},
        )
        assert recovered_response.status_code == 200
        recovered = recovered_response.json()
        assert recovered["documentHash"] == created["documentHash"]
        assert recovered["operationId"] != created["operationId"]

        apply_body = {
            "contractVersion": 1,
            "clientRequestId": fixture_id("api-apply-request"),
            "expectedHeadSequenceNo": 0,
            "expectedDocumentHash": created["documentHash"],
            "batch": text_insert_batch_payload(),
        }
        applied_response = client.post(
            f"/api/structured-prototype-drafts/{created['draftId']}/commands",
            json=apply_body,
        )
        assert applied_response.status_code == 200
        applied = applied_response.json()
        assert applied["headSequenceNo"] == 1
        assert applied["canUndo"] is True
        assert applied["canRedo"] is False
        assert applied["allocatedEntityIds"][0]["newNodeKey"] == "approval-note"

        stale_body = dict(apply_body)
        stale_body["clientRequestId"] = fixture_id("api-stale-request")
        stale_response = client.post(
            f"/api/structured-prototype-drafts/{created['draftId']}/commands",
            json=stale_body,
        )
        assert stale_response.status_code == 409
        stale = stale_response.json()
        assert stale["error"]["code"] == "draft_conflict"
        assert stale["error"]["retryable"] is True
        assert stale["error"]["currentHeadSequenceNo"] == 1
        assert stale["operationId"] is not None
        assert stale["correlationId"]

        history_body = {
            "contractVersion": 1,
            "clientRequestId": fixture_id("api-undo-request"),
            "expectedHeadSequenceNo": 1,
            "expectedDocumentHash": applied["documentHash"],
        }
        invalid_history_response = client.post(
            f"/api/structured-prototype-drafts/{created['draftId']}/undo",
            json={**history_body, "batch": text_insert_batch_payload()},
        )
        assert invalid_history_response.status_code == 422
        assert invalid_history_response.json()["error"]["code"] == "request_invalid"

        undo_response = client.post(
            f"/api/structured-prototype-drafts/{created['draftId']}/undo",
            json=history_body,
        )
        assert undo_response.status_code == 200
        undone = undo_response.json()
        assert undone["headSequenceNo"] == 2
        assert undone["documentHash"] == created["documentHash"]
        assert undone["allocatedEntityIds"] == []
        assert undone["canUndo"] is False
        assert undone["canRedo"] is True

        idempotency_conflict_response = client.post(
            f"/api/structured-prototype-drafts/{created['draftId']}/undo",
            json={
                **history_body,
                "expectedHeadSequenceNo": 2,
                "expectedDocumentHash": undone["documentHash"],
            },
        )
        assert idempotency_conflict_response.status_code == 409
        idempotency_conflict = idempotency_conflict_response.json()
        assert idempotency_conflict["error"]["code"] == "operation_idempotency_conflict"
        assert idempotency_conflict["error"]["retryable"] is False

        redo_response = client.post(
            f"/api/structured-prototype-drafts/{created['draftId']}/redo",
            json={
                "contractVersion": 1,
                "clientRequestId": fixture_id("api-redo-request"),
                "expectedHeadSequenceNo": 2,
                "expectedDocumentHash": undone["documentHash"],
            },
        )
        assert redo_response.status_code == 200
        redone = redo_response.json()
        assert redone["headSequenceNo"] == 3
        assert redone["documentHash"] == applied["documentHash"]
        assert redone["allocatedEntityIds"] == []
        assert redone["canUndo"] is True
        assert redone["canRedo"] is False
        assert client.portal is not None
        client.portal.call(store.close)


def test_delete_project_prototype_removes_editable_and_runtime_state_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    delete_request_id = fixture_id("api-delete-project-prototype")
    with client:
        created_response = client.post(
            "/api/projects/project-1/structured-prototype-documents",
            json=_create_body(fixture_id("api-delete-document")),
        )
        assert created_response.status_code == 201
        created = created_response.json()
        runtime_response = client.post(
            f"/api/structured-prototype-drafts/{created['draftId']}/runtime-sessions",
            json={
                "contractVersion": 1,
                "clientRequestId": fixture_id("api-delete-runtime-session"),
                "scenarioId": fixture_id("scenario-happy-path"),
                "recordingKind": "studio_preview",
                "actorSubjectId": None,
            },
        )
        assert runtime_response.status_code == 201
        runtime = runtime_response.json()
        publish_response = client.post(
            f"/api/structured-prototype-drafts/{created['draftId']}/publish",
            json={
                "contractVersion": 1,
                "clientRequestId": fixture_id("api-delete-publication"),
                "expectedHeadSequenceNo": 0,
                "expectedDocumentHash": created["documentHash"],
            },
        )
        assert publish_response.status_code == 201
        published = publish_response.json()

        deleted_response = client.delete(
            "/api/projects/project-1/structured-prototype-documents",
            params={"clientRequestId": delete_request_id},
        )
        assert deleted_response.status_code == 200, deleted_response.text
        deleted = deleted_response.json()
        assert deleted["contractVersion"] == 1
        assert deleted["deleted"] is True
        assert deleted["operationId"]
        assert deleted["correlationId"]

        repeated_response = client.delete(
            "/api/projects/project-1/structured-prototype-documents",
            params={"clientRequestId": delete_request_id},
        )
        assert repeated_response.status_code == 200
        assert repeated_response.json() == deleted

        current_response = client.get(
            "/api/projects/project-1/structured-prototype-documents/current",
            params={"clientRequestId": fixture_id("api-delete-current-check")},
        )
        assert current_response.status_code == 200
        assert current_response.json() is None

        draft_response = client.get(
            f"/api/structured-prototype-drafts/{created['draftId']}",
            params={"clientRequestId": fixture_id("api-delete-draft-check")},
        )
        assert draft_response.status_code == 404
        assert draft_response.json()["error"]["code"] == "draft_missing"

        runtime_recovery = client.get(
            f"/api/structured-prototype-runtime-sessions/{runtime['sessionId']}",
            params={"clientRequestId": fixture_id("api-delete-runtime-check")},
        )
        assert runtime_recovery.status_code == 404
        assert runtime_recovery.json()["error"]["code"] == "runtime_session_missing"

        publication_response = client.get(
            f"/api/structured-prototype-documents/{created['documentId']}/published"
        )
        assert publication_response.status_code == 200
        assert publication_response.json() is None
        artifact_response = client.get(published["artifactPath"])
        assert artifact_response.status_code == 404

        assert client.portal is not None
        operation_events = client.portal.call(
            store.list_operation_events,
            deleted["operationId"],
        )
        assert [event.status for event in operation_events] == [
            "queued",
            "running",
            "succeeded",
        ]
        client.portal.call(store.close)


def test_invalid_nested_alias_returns_versioned_error_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    body = _create_body(fixture_id("api-invalid-request"))
    document = body["document"]
    assert isinstance(document, dict)
    document["schema_version"] = document.pop("schemaVersion")

    with client:
        response = client.post(
            "/api/projects/project-1/structured-prototype-documents",
            json=body,
        )

        assert response.status_code == 422
        payload = response.json()
        assert payload["contractVersion"] == 1
        assert payload["operationId"] is None
        assert payload["error"] == {
            "code": "request_invalid",
            "message": "structured prototype request does not satisfy HTTP contract version 1",
            "retryable": False,
            "currentHeadSequenceNo": None,
            "currentDocumentHash": None,
            "resourceUrl": None,
        }
        assert client.portal is not None
        client.portal.call(store.close)


def test_runtime_session_event_and_recovery_use_versioned_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    with client:
        created_response = client.post(
            "/api/projects/project-1/structured-prototype-documents",
            json=_create_body(fixture_id("api-runtime-document")),
        )
        assert created_response.status_code == 201
        created = created_response.json()
        runtime_response = client.post(
            f"/api/structured-prototype-drafts/{created['draftId']}/runtime-sessions",
            json={
                "contractVersion": 1,
                "clientRequestId": fixture_id("api-runtime-session"),
                "scenarioId": fixture_id("scenario-happy-path"),
                "recordingKind": "studio_preview",
                "actorSubjectId": "product-manager-1",
            },
        )
        assert runtime_response.status_code == 201
        runtime = runtime_response.json()
        assert runtime["contractVersion"] == 1
        assert runtime["headSequenceNo"] == 0
        assert runtime["runtimeCoreVersion"] == "0.2.0-spike"
        assert runtime["stateMachineKernelVersion"] == "5.32.4"
        event_request_id = fixture_id("api-runtime-event")
        event_response = client.post(
            f"/api/structured-prototype-runtime-sessions/{runtime['sessionId']}/events",
            json={
                "contractVersion": 1,
                "clientRequestId": event_request_id,
                "expectedHeadSequenceNo": 0,
                "expectedStateHash": runtime["stateHash"],
                "batch": {
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
            },
        )
        assert event_response.status_code == 200
        event = event_response.json()
        assert event["headSequenceNo"] == 1
        assert event["outcome"] == "applied"
        assert event["eventBatchId"]
        checkpoint_response = client.post(
            f"/api/structured-prototype-runtime-sessions/{runtime['sessionId']}/checkpoint",
            json={
                "contractVersion": 1,
                "clientRequestId": fixture_id("api-runtime-checkpoint"),
            },
        )
        assert checkpoint_response.status_code == 200
        checkpoint = checkpoint_response.json()
        assert checkpoint["checkpointSequenceNo"] == 1
        assert checkpoint["replayedEventBatchIds"] == []
        recovered_response = client.get(
            f"/api/structured-prototype-runtime-sessions/{runtime['sessionId']}",
            params={"clientRequestId": fixture_id("api-runtime-recover")},
        )
        assert recovered_response.status_code == 200
        recovered = recovered_response.json()
        assert recovered["stateHash"] == event["stateHash"]
        assert recovered["viewModelHash"] == event["viewModelHash"]
        assert recovered["replayedEventBatchIds"] == []
        assert client.portal is not None
        client.portal.call(store.close)


def test_runtime_identity_error_exposes_reset_cas_and_reset_returns_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    reset_request_id = fixture_id("api-runtime-reset")
    with client:
        created_response = client.post(
            "/api/projects/project-1/structured-prototype-documents",
            json=_create_body(fixture_id("api-runtime-reset-document")),
        )
        assert created_response.status_code == 201
        created = created_response.json()
        runtime_response = client.post(
            f"/api/structured-prototype-drafts/{created['draftId']}/runtime-sessions",
            json={
                "contractVersion": 1,
                "clientRequestId": fixture_id("api-runtime-reset-old-session"),
                "scenarioId": fixture_id("scenario-happy-path"),
                "recordingKind": "studio_preview",
                "actorSubjectId": None,
            },
        )
        assert runtime_response.status_code == 201
        runtime = runtime_response.json()
        assert runtime["pinnedDocumentObjectHash"] == created["documentHash"]
        assert runtime["replacesSessionId"] is None
        assert runtime["resetManifestHash"] is None

        unavailable_bundle_hash = "sha256:" + "f" * 64
        assert client.portal is not None
        conn = client.portal.call(store._get_conn)
        client.portal.call(
            conn.execute,
            "UPDATE prototype_runtime_sessions SET runtime_core_bundle_hash = ? WHERE id = ?",
            (unavailable_bundle_hash, runtime["sessionId"]),
        )
        client.portal.call(conn.commit)
        recovery_response = client.get(
            f"/api/structured-prototype-runtime-sessions/{runtime['sessionId']}",
            params={"clientRequestId": fixture_id("api-runtime-reset-recovery")},
        )
        assert recovery_response.status_code == 409
        recovery_payload = recovery_response.json()
        recovery_error = recovery_payload["error"]
        cause_operation_id = recovery_payload["operationId"]
        assert isinstance(cause_operation_id, str)
        assert recovery_error == {
            "code": "runtime_replay_version_mismatch",
            "message": "prototype runtime worker identity does not match the pinned session",
            "retryable": False,
            "currentHeadSequenceNo": 0,
            "currentStateHash": runtime["stateHash"],
            "currentViewModelHash": runtime["viewModelHash"],
            "runtimeCoreBundleHash": unavailable_bundle_hash,
            "resourceUrl": (
                f"/api/structured-prototype-runtime-sessions/{runtime['sessionId']}/reset"
            ),
        }
        reset_body = {
            "contractVersion": 1,
            "clientRequestId": reset_request_id,
            "causeOperationId": cause_operation_id,
            "expectedOldHeadSequenceNo": recovery_error["currentHeadSequenceNo"],
            "expectedOldStateHash": recovery_error["currentStateHash"],
            "expectedOldViewModelHash": recovery_error["currentViewModelHash"],
            "expectedOldRuntimeCoreBundleHash": recovery_error["runtimeCoreBundleHash"],
            "targetDraftId": created["draftId"],
            "expectedTargetHeadSequenceNo": created["headSequenceNo"],
            "expectedTargetDocumentHash": created["documentHash"],
            "scenarioId": fixture_id("scenario-happy-path"),
        }
        invalid_cause_response = client.post(
            recovery_error["resourceUrl"],
            json={
                **reset_body,
                "clientRequestId": fixture_id("api-runtime-reset-invalid-cause"),
                "causeOperationId": created["operationId"],
            },
        )
        assert invalid_cause_response.status_code == 409
        assert invalid_cause_response.json()["error"]["code"] == ("runtime_reset_cause_invalid")
        invalid_response = client.post(
            recovery_error["resourceUrl"],
            json={
                **reset_body,
                "clientRequestId": fixture_id("api-runtime-reset-invalid"),
                "extra": True,
            },
        )
        assert invalid_response.status_code == 422
        assert invalid_response.json()["error"]["code"] == "request_invalid"

        reset_response = client.post(recovery_error["resourceUrl"], json=reset_body)
        retry_response = client.post(recovery_error["resourceUrl"], json=reset_body)
        assert reset_response.status_code == 201
        assert retry_response.status_code == 201
        reset = reset_response.json()
        retried = retry_response.json()
        assert reset["sessionId"] != runtime["sessionId"]
        assert reset["replacesSessionId"] == runtime["sessionId"]
        assert reset["pinnedDocumentObjectHash"] == created["documentHash"]
        assert reset["headSequenceNo"] == 0
        assert reset["replayedEventBatchIds"] == []
        assert reset["resetManifestHash"].startswith("sha256:")
        assert retried["sessionId"] == reset["sessionId"]
        assert retried["resetManifestHash"] == reset["resetManifestHash"]
        outcome_response = client.get(
            "/api/projects/project-1/structured-prototype-operations/outcome",
            params={
                "operationKind": "reset_runtime_session",
                "clientRequestId": reset_request_id,
            },
        )
        assert outcome_response.status_code == 200
        outcome = outcome_response.json()
        assert outcome["resourceKind"] == "runtime_session"
        assert outcome["resourceId"] == reset["sessionId"]
        assert outcome["parentOperationId"] == cause_operation_id
        assert outcome["resultManifestHash"] != reset["resetManifestHash"]
        detail_response = client.get(f"/api/prototype-operations/{outcome['operationId']}")
        assert detail_response.status_code == 200, detail_response.text
        replay_manifest = detail_response.json()["replayManifest"]
        assert replay_manifest["runtimeSessionId"] == reset["sessionId"]
        assert reset["resetManifestHash"] in replay_manifest["orderedInputObjectHashes"]
        client.portal.call(store.close)


def test_publish_and_public_artifact_routes_serve_only_verified_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    with client:
        created_response = client.post(
            "/api/projects/project-1/structured-prototype-documents",
            json=_create_body(fixture_id("api-publication-document")),
        )
        assert created_response.status_code == 201
        created = created_response.json()
        missing_before_publish = client.get(
            f"/api/structured-prototype-documents/{created['documentId']}/published"
        )
        assert missing_before_publish.status_code == 200
        assert missing_before_publish.json() is None

        publish_response = client.post(
            f"/api/structured-prototype-drafts/{created['draftId']}/publish",
            json={
                "contractVersion": 1,
                "clientRequestId": fixture_id("api-publication-request"),
                "expectedHeadSequenceNo": 0,
                "expectedDocumentHash": created["documentHash"],
            },
        )
        assert publish_response.status_code == 201
        published = publish_response.json()
        assert published["revisionNo"] == 1
        assert published["activeDraft"]["draftId"] != created["draftId"]
        assert published["sharePath"] == f"/prototype-share/{created['documentId']}"
        assert published["artifactPath"].endswith("/index.html")
        assert published["outputHash"].startswith("sha256:")

        current = client.get(
            f"/api/structured-prototype-documents/{created['documentId']}/published"
        )
        assert current.status_code == 200
        assert current.json()["artifactId"] == published["artifactId"]
        redirect = client.get(
            f"/api/structured-prototype-public/{created['documentId']}/current/index.html",
            follow_redirects=False,
        )
        assert redirect.status_code == 307
        assert redirect.headers["location"] == published["artifactPath"]

        artifact = client.get(published["artifactPath"])
        assert artifact.status_code == 200
        assert '<script src="./runtime.js" defer></script>' in artifact.text
        assert artifact.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert artifact.headers["etag"] == f'"{published["outputHash"][7:]}"'
        assert "default-src 'none'" in artifact.headers["content-security-policy"]
        missing_file = client.get(published["artifactPath"].replace("index.html", "missing.txt"))
        assert missing_file.status_code == 404

        assert client.portal is not None
        client.portal.call(store.close)
