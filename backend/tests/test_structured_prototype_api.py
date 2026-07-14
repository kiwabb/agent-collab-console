from __future__ import annotations

from datetime import UTC, datetime
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
from app.adapters.structured_prototype_store import AsyncStructuredPrototypeStore
from app.application.structured_prototype_service import StructuredPrototypeService


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
        assert client.portal is not None
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
        assert runtime["runtimeCoreVersion"] == "0.1.0-spike"
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
