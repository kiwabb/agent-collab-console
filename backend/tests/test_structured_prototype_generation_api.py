from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_structured_prototype_generation_service import (
    _ControlledGenerationRuntime,
    _ProjectStore,
    _ResourceCleaner,
    _SourceControl,
)

import app.interfaces.structured_prototype_api as structured_api
import app.interfaces.structured_prototype_generation_api as generation_api
from app.adapters.prototype_object_store import PrototypeObjectStore
from app.adapters.prototype_render_artifact_store import PrototypeRenderArtifactStore
from app.adapters.prototype_renderer_worker import PrototypeRendererWorker
from app.adapters.prototype_runtime_worker import PrototypeRuntimeWorker
from app.adapters.structured_prototype_store import AsyncStructuredPrototypeStore
from app.application.structured_prototype_generation_service import (
    StructuredPrototypeGenerationService,
)
from app.application.structured_prototype_service import StructuredPrototypeService
from app.domain.models import Project
from app.domain.structured_prototype import PrototypeObjectReference

NOW = datetime(2026, 7, 13, 18, 0, tzinfo=UTC)


class _PreviewService:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []

    async def read_preview_file(self, job_id: str, relative_path: str) -> bytes:
        self.requests.append((job_id, relative_path))
        return {
            "document.json": b'{"schemaVersion":1}',
            "index.html": b"<!doctype html>",
            "runtime.js": b"void 0;",
            "styles.css": b"html{}",
        }[relative_path]


def test_generation_preview_route_serves_only_renderer_bundle_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _PreviewService()
    monkeypatch.setattr(generation_api, "_require_service", lambda: service)
    app = FastAPI()
    app.include_router(generation_api.router)
    allowed_files = {
        "document.json": ("application/json; charset=utf-8", b'{"schemaVersion":1}'),
        "index.html": ("text/html; charset=utf-8", b"<!doctype html>"),
        "runtime.js": ("text/javascript; charset=utf-8", b"void 0;"),
        "styles.css": ("text/css; charset=utf-8", b"html{}"),
    }

    with TestClient(app) as client:
        for relative_path, (media_type, content) in allowed_files.items():
            response = client.get(
                f"/api/prototype-document-generation-jobs/job-1/preview/{relative_path}"
            )

            assert response.status_code == 200
            assert response.headers["content-type"] == media_type
            assert response.content == content

        unavailable = client.get(
            "/api/prototype-document-generation-jobs/job-1/preview/manifest.json"
        )

    assert unavailable.status_code == 404
    assert unavailable.json()["error"]["code"] == "preview_file_missing"
    assert service.requests == [("job-1", relative_path) for relative_path in allowed_files]


def test_generation_api_exposes_plan_review_preview_and_atomic_accept(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "managed")
    project = Project(
        id="project-1",
        name="admin-demo",
        repo_path=str(tmp_path),
        default_branch="main",
    )
    service = StructuredPrototypeGenerationService(
        store=store,
        project_store=_ProjectStore(project),
        object_store=object_store,
        runtime=_ControlledGenerationRuntime(object_store),
        runtime_worker=PrototypeRuntimeWorker(timeout_s=30),
        renderer=PrototypeRendererWorker(),
        artifact_store=PrototypeRenderArtifactStore(tmp_path / "managed"),
        source_control=_SourceControl(),
        resource_cleaner=_ResourceCleaner(),
        clock=lambda: NOW,
    )
    monkeypatch.setattr(
        generation_api,
        "structured_prototype_generation_service",
        service,
    )
    monkeypatch.setattr(
        structured_api,
        "structured_prototype_service",
        StructuredPrototypeService(
            store=store,
            object_store=object_store,
            runtime_worker=PrototypeRuntimeWorker(timeout_s=30),
            renderer_worker=PrototypeRendererWorker(),
            artifact_store=PrototypeRenderArtifactStore(tmp_path / "managed"),
            clock=lambda: NOW,
        ),
    )
    app = FastAPI()
    app.include_router(generation_api.router)
    app.include_router(structured_api.router)

    with TestClient(app) as client:
        portal = client.portal
        assert portal is not None
        empty_current_response = client.get(
            f"/api/projects/{project.id}/prototype-document-generation-jobs/current"
        )
        assert empty_current_response.status_code == 200
        assert empty_current_response.json() is None

        create_response = client.post(
            f"/api/projects/{project.id}/prototype-document-generation-jobs",
            json={
                "contractVersion": 1,
                "clientRequestId": "73455211-3ec3-53d1-b97f-185d831f4194",
                "mode": "requirements",
                "brief": "基于项目源码生成仪表盘、用户管理和订单管理的可编辑原型",
            },
        )
        assert create_response.status_code == 202
        job_id = create_response.json()["id"]
        planned = portal.call(service.wait_for_job, job_id)
        planned_response = client.get(f"/api/prototype-document-generation-jobs/{job_id}")
        current_response = client.get(
            f"/api/projects/{project.id}/prototype-document-generation-jobs/current"
        )

        assert planned_response.status_code == 200
        planned_body = planned_response.json()
        assert current_response.status_code == 200
        assert current_response.json()["id"] == job_id
        assert planned_body["status"] == "awaiting_confirmation"
        assert planned_body["sourcePolicy"] == "committed_head_v1"
        assert planned_body["sourceSnapshotObjectHash"] == planned.job.source_snapshot_object_hash
        assert planned_body["sourceFingerprint"] == planned.job.source_fingerprint
        assert planned_body["sourceSnapshotRef"] == (
            f"refs/agent-collab/prototype-generation/{job_id}"
        )
        assert planned_body["repositoryObjectFormat"] == "sha1"
        assert planned_body["worktreeBaseCommit"] == "a" * 40
        assert planned_body["repositoryProjectPrefix"] == ""
        assert planned_body["repositoryTreeObjectId"] == "b" * 40
        assert planned_body["workingTreeDirty"] is True
        assert planned_body["excludedTrackedChangeCount"] == 2
        assert planned_body["excludedUntrackedCount"] == 1
        assert planned_body["sourceFileExclusionPolicy"] == "dotenv_checkout_filter_v1"
        assert planned_body["excludedSensitiveFileCount"] == 1
        assert planned_body["excludedStatusHash"] == "sha256:" + "c" * 64
        assert planned_body["blueprint"]["contractVersion"] == 3
        assert [page["pageKey"] for page in planned_body["blueprint"]["pages"]] == [
            "dashboard",
            "users",
            "orders",
        ]
        assert [
            (binding["key"], binding["pageKey"])
            for binding in planned_body["blueprint"]["viewBindingIntents"]
        ] == [
            ("users-table-rows", "users"),
            ("orders-table-rows", "orders"),
        ]
        assert [
            (behavior["key"], behavior["sourcePageKey"])
            for behavior in planned_body["blueprint"]["behaviorIntents"]
        ] == [("open-users", "dashboard")]
        assert planned_body["canConfirm"] is True

        def operation_detail(operation_id: str) -> dict[str, Any]:
            response = client.get(f"/api/prototype-operations/{operation_id}")
            if response.status_code != 200:
                portal.call(store.close)
                pytest.fail(response.text)
            events_response = client.get(f"/api/prototype-operations/{operation_id}/events")
            if events_response.status_code != 200:
                portal.call(store.close)
                pytest.fail(events_response.text)
            events = events_response.json()["events"]
            assert [event["eventNo"] for event in events] == list(range(len(events)))
            payload: object = response.json()
            assert isinstance(payload, dict)
            result: dict[str, Any] = {}
            for key, item in payload.items():
                assert isinstance(key, str)
                result[key] = item
            return result

        planned_root_detail = operation_detail(planned.job.operation_id)
        assert planned_root_detail["operation"]["status"] == "running"
        assert planned_root_detail["replayManifest"] is None
        assert planned_root_detail["childOperationIds"]

        assert planned.job.blueprint_object_hash is not None
        blueprint_descriptor = portal.call(
            store.load_object,
            project.id,
            planned.job.blueprint_object_hash,
        )
        assert blueprint_descriptor is not None
        legacy_envelope = json.loads(object_store.read_canonical_bytes(blueprint_descriptor))
        assert isinstance(legacy_envelope, dict)
        legacy_payload = legacy_envelope["payload"]
        assert isinstance(legacy_payload, dict)
        legacy_payload["contractVersion"] = 2
        legacy_descriptor = object_store.write_json(project.id, legacy_envelope)
        portal.call(
            store.register_object_reference,
            legacy_descriptor,
            PrototypeObjectReference(
                project_id=project.id,
                owner_kind="generation_job",
                owner_id=job_id,
                role="legacy-blueprint-regression",
                content_hash=legacy_descriptor.content_hash,
                payload_type="generation_blueprint",
                schema_version=1,
                created_at=NOW,
            ),
        )

        async def point_job_at_blueprint(content_hash: str) -> None:
            async with aiosqlite.connect(tmp_path / "console.db") as conn:
                await conn.execute(
                    """
                    UPDATE prototype_document_generation_jobs
                    SET blueprint_object_hash = ?, blueprint_hash = ?
                    WHERE id = ?
                    """,
                    (content_hash, content_hash, job_id),
                )
                await conn.commit()

        portal.call(point_job_at_blueprint, legacy_descriptor.content_hash)
        corrupt_current = client.get(
            f"/api/projects/{project.id}/prototype-document-generation-jobs/current"
        )
        assert corrupt_current.status_code == 500
        assert corrupt_current.json()["error"]["code"] == "object_corrupt"
        portal.call(point_job_at_blueprint, planned.job.blueprint_object_hash)

        stale_confirm = client.post(
            f"/api/prototype-document-generation-jobs/{job_id}/confirm",
            json={
                "contractVersion": 1,
                "clientRequestId": "91f7d8a6-915c-599d-b410-6291e0128aa1",
                "expectedBlueprintVersion": planned.job.blueprint_version,
                "expectedBlueprintHash": "sha256:" + "0" * 64,
            },
        )
        assert stale_confirm.status_code == 409
        assert stale_confirm.json()["error"]["code"] == "blueprint_conflict"

        stale_version = client.post(
            f"/api/prototype-document-generation-jobs/{job_id}/confirm",
            json={
                "contractVersion": 1,
                "clientRequestId": "d3b111ee-80d0-5aba-b915-78573e86ec7f",
                "expectedBlueprintVersion": planned.job.blueprint_version + 1,
                "expectedBlueprintHash": planned.job.blueprint_hash,
            },
        )
        assert stale_version.status_code == 409
        assert stale_version.json()["error"]["code"] == "blueprint_conflict"

        confirm_request = {
            "contractVersion": 1,
            "clientRequestId": "43a34e04-3caa-5d85-be4c-5fdd57f6745f",
            "expectedBlueprintVersion": planned.job.blueprint_version,
            "expectedBlueprintHash": planned.job.blueprint_hash,
        }
        confirm_response = client.post(
            f"/api/prototype-document-generation-jobs/{job_id}/confirm",
            json=confirm_request,
        )
        assert confirm_response.status_code == 202
        confirm_receipt = confirm_response.json()
        confirm_operation = portal.call(
            store.load_operation,
            confirm_receipt["operationId"],
        )
        assert confirm_operation is not None
        assert confirm_receipt["contractVersion"] == 1
        assert confirm_receipt["operationId"] == confirm_operation.id
        assert confirm_receipt["correlationId"] == confirm_operation.correlation_id
        assert confirm_receipt["operationId"] != confirm_receipt["job"]["operationId"]
        assert confirm_receipt["job"]["operationId"] == planned.job.operation_id
        ready = portal.call(service.wait_for_job, job_id)
        ready_response = client.get(f"/api/prototype-document-generation-jobs/{job_id}")
        ready_body = ready_response.json()

        if ready_body["status"] != "ready":
            portal.call(store.close)
            pytest.fail(f"{ready_body['errorCode']}: {ready_body['errorMessage']}")
        assert ready_body["canAccept"] is True
        assert [item["itemOrdinal"] for item in ready_body["items"]] == [0, 1, 2]
        assert [item["submissionNormalizedFields"] for item in ready_body["items"]] == [
            ["payload.root.gap"],
            ["payload.root.gap"],
            ["payload.root.gap"],
        ]
        assert ready_body["previewPath"].endswith("/preview/index.html")
        ready_root_detail = operation_detail(planned.job.operation_id)
        discovered: dict[str, dict[str, Any]] = {}
        pending_operation_ids = list(ready_root_detail["childOperationIds"])
        while pending_operation_ids:
            operation_id = pending_operation_ids.pop()
            if operation_id in discovered:
                continue
            child_detail = operation_detail(operation_id)
            discovered[operation_id] = child_detail
            pending_operation_ids.extend(child_detail["childOperationIds"])
        assert confirm_receipt["operationId"] in discovered
        assert {item["operationId"] for item in ready_body["items"]}.issubset(discovered)
        phase_step_kinds = {
            tuple(step["stepKind"] for step in detail["steps"])
            for detail in discovered.values()
            if detail["operation"]["operationKind"] == "generation_job"
        }
        assert ("freeze_context", "generate_foundation") in phase_step_kinds
        assert ("generate_pages",) in phase_step_kinds
        retried_confirm = client.post(
            f"/api/prototype-document-generation-jobs/{job_id}/confirm",
            json=confirm_request,
        )
        assert retried_confirm.status_code == 202
        retried_confirm_receipt = retried_confirm.json()
        assert retried_confirm_receipt["operationId"] == confirm_receipt["operationId"]
        assert retried_confirm_receipt["correlationId"] == confirm_receipt["correlationId"]
        assert retried_confirm_receipt["job"] == ready_body
        conflicting_confirm = client.post(
            f"/api/prototype-document-generation-jobs/{job_id}/confirm",
            json={
                **confirm_request,
                "expectedBlueprintVersion": planned.job.blueprint_version + 1,
            },
        )
        assert conflicting_confirm.status_code == 409
        assert conflicting_confirm.json()["error"]["code"] == (
            "generation_confirm_idempotency_conflict"
        )
        preview_response = client.get(ready_body["previewPath"])
        assert preview_response.status_code == 200
        assert "<!doctype html>" in preview_response.text.lower()

        accept_request = {
            "contractVersion": 1,
            "clientRequestId": "aff9a166-c13e-5e0e-8535-c3f8003b5ca1",
            "expectedCandidateObjectHash": ready.job.candidate_object_hash,
            "expectedPreviewOutputHash": ready.job.preview_output_hash,
            "expectedSourceFingerprint": ready.job.source_fingerprint,
        }
        accept_response = client.post(
            f"/api/prototype-document-generation-jobs/{job_id}/accept",
            json=accept_request,
        )

        assert accept_response.status_code == 200
        accepted = accept_response.json()
        assert accepted["job"]["status"] == "accepted"
        accept_operation = portal.call(store.load_operation, accepted["operationId"])
        assert accept_operation is not None
        assert accepted["operationId"] == accept_operation.id
        assert accepted["correlationId"] == accept_operation.correlation_id
        assert accepted["operationId"] != accepted["job"]["operationId"]
        assert accepted["documentId"] == accepted["job"]["documentId"]
        assert accepted["headSequenceNo"] == 0
        accepted_root_detail = operation_detail(planned.job.operation_id)
        assert accepted_root_detail["operation"]["status"] == "succeeded"
        assert accepted_root_detail["replayManifest"]["operationId"] == (planned.job.operation_id)
        assert accepted["operationId"] in accepted_root_detail["childOperationIds"]
        accepted_detail = operation_detail(accepted["operationId"])
        assert accepted_detail["operation"]["operationKind"] == "create_document"
        assert accepted_detail["operation"]["parentOperationId"] == planned.job.operation_id

        retried_accept = client.post(
            f"/api/prototype-document-generation-jobs/{job_id}/accept",
            json=accept_request,
        )
        assert retried_accept.status_code == 200
        assert retried_accept.json() == accepted

        conflicting_accept = client.post(
            f"/api/prototype-document-generation-jobs/{job_id}/accept",
            json={
                **accept_request,
                "expectedCandidateObjectHash": "sha256:" + "0" * 64,
            },
        )
        assert conflicting_accept.status_code == 409
        assert conflicting_accept.json()["error"]["code"] == (
            "generation_accept_idempotency_conflict"
        )
        portal.call(store.close)


def test_generation_api_exposes_execution_process_while_claude_is_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "managed")
    runtime = _ControlledGenerationRuntime(object_store, pause_after_activity=True)
    project = Project(
        id="project-1",
        name="admin-demo",
        repo_path=str(tmp_path),
        default_branch="main",
    )
    service = StructuredPrototypeGenerationService(
        store=store,
        project_store=_ProjectStore(project),
        object_store=object_store,
        runtime=runtime,
        runtime_worker=PrototypeRuntimeWorker(),
        renderer=PrototypeRendererWorker(),
        artifact_store=PrototypeRenderArtifactStore(tmp_path / "managed"),
        source_control=_SourceControl(),
        resource_cleaner=_ResourceCleaner(),
        clock=lambda: NOW,
    )
    monkeypatch.setattr(
        generation_api,
        "structured_prototype_generation_service",
        service,
    )
    app = FastAPI()
    app.include_router(generation_api.router)

    with TestClient(app) as client:
        assert client.portal is not None
        create_response = client.post(
            f"/api/projects/{project.id}/prototype-document-generation-jobs",
            json={
                "contractVersion": 1,
                "clientRequestId": "f3dacaf2-a88d-5a68-8e3b-fb3f8056bba3",
                "mode": "requirements",
                "brief": "基于项目源码生成可编辑原型",
            },
        )
        assert create_response.status_code == 202
        job_id = create_response.json()["id"]
        try:
            client.portal.call(runtime.activity_started.wait)
            active_response = client.get(f"/api/prototype-document-generation-jobs/{job_id}")

            assert active_response.status_code == 200
            active = active_response.json()
            assert active["status"] == "planning"
            assert active["items"][0]["status"] == "generating"
            assert active["items"][0]["executionProcessId"] == (
                f"process-{active['items'][0]['id']}"
            )
        finally:
            client.portal.call(runtime.release.set)
            client.portal.call(service.wait_for_job, job_id)
            client.portal.call(store.close)
