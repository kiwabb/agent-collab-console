from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_structured_prototype_generation_service import (
    _ControlledGenerationRuntime,
    _ProjectStore,
)

import app.interfaces.structured_prototype_generation_api as generation_api
from app.adapters.prototype_object_store import PrototypeObjectStore
from app.adapters.prototype_render_artifact_store import PrototypeRenderArtifactStore
from app.adapters.prototype_renderer_worker import PrototypeRendererWorker
from app.adapters.prototype_runtime_worker import PrototypeRuntimeWorker
from app.adapters.structured_prototype_store import AsyncStructuredPrototypeStore
from app.application.structured_prototype_generation_service import (
    StructuredPrototypeGenerationService,
)
from app.domain.models import Project

NOW = datetime(2026, 7, 13, 18, 0, tzinfo=UTC)


def test_generation_api_exposes_plan_review_preview_and_atomic_accept(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "managed")
    project = Project(
        id="project-1",
        name="Procurement",
        repo_path=str(tmp_path),
        default_branch="main",
    )
    service = StructuredPrototypeGenerationService(
        store=store,
        project_store=_ProjectStore(project),
        object_store=object_store,
        runtime=_ControlledGenerationRuntime(object_store),
        runtime_worker=PrototypeRuntimeWorker(),
        renderer=PrototypeRendererWorker(),
        artifact_store=PrototypeRenderArtifactStore(tmp_path / "managed"),
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
                "brief": "生成采购申请提交和审批原型",
            },
        )
        assert create_response.status_code == 202
        job_id = create_response.json()["id"]
        planned = client.portal.call(service.wait_for_job, job_id)
        planned_response = client.get(f"/api/prototype-document-generation-jobs/{job_id}")
        current_response = client.get(
            f"/api/projects/{project.id}/prototype-document-generation-jobs/current"
        )

        assert planned_response.status_code == 200
        planned_body = planned_response.json()
        assert current_response.status_code == 200
        assert current_response.json()["id"] == job_id
        assert planned_body["status"] == "awaiting_confirmation"
        assert [page["pageKey"] for page in planned_body["blueprint"]["pages"]] == [
            "purchase-list",
            "purchase-create",
            "purchase-detail",
        ]
        assert planned_body["canConfirm"] is True

        stale_confirm = client.post(
            f"/api/prototype-document-generation-jobs/{job_id}/confirm",
            json={
                "contractVersion": 1,
                "clientRequestId": "91f7d8a6-915c-599d-b410-6291e0128aa1",
                "expectedBlueprintHash": "sha256:" + "0" * 64,
            },
        )
        assert stale_confirm.status_code == 409
        assert stale_confirm.json()["error"]["code"] == "blueprint_conflict"

        confirm_response = client.post(
            f"/api/prototype-document-generation-jobs/{job_id}/confirm",
            json={
                "contractVersion": 1,
                "clientRequestId": "43a34e04-3caa-5d85-be4c-5fdd57f6745f",
                "expectedBlueprintHash": planned.job.blueprint_hash,
            },
        )
        assert confirm_response.status_code == 202
        ready = client.portal.call(service.wait_for_job, job_id)
        ready_response = client.get(f"/api/prototype-document-generation-jobs/{job_id}")
        ready_body = ready_response.json()

        assert ready_body["status"] == "ready"
        assert ready_body["canAccept"] is True
        assert [item["submissionNormalizedFields"] for item in ready_body["items"]] == [
            ["payload.root.gap"],
            ["payload.root.gap"],
            ["payload.root.gap"],
        ]
        assert ready_body["previewPath"].endswith("/preview/index.html")
        preview_response = client.get(ready_body["previewPath"])
        assert preview_response.status_code == 200
        assert "<!doctype html>" in preview_response.text.lower()

        accept_response = client.post(
            f"/api/prototype-document-generation-jobs/{job_id}/accept",
            json={
                "contractVersion": 1,
                "clientRequestId": "aff9a166-c13e-5e0e-8535-c3f8003b5ca1",
                "expectedCandidateObjectHash": ready.job.candidate_object_hash,
                "expectedPreviewOutputHash": ready.job.preview_output_hash,
            },
        )

        assert accept_response.status_code == 200
        accepted = accept_response.json()
        assert accepted["job"]["status"] == "accepted"
        assert accepted["documentId"] == accepted["job"]["documentId"]
        assert accepted["headSequenceNo"] == 0
        client.portal.call(store.close)
