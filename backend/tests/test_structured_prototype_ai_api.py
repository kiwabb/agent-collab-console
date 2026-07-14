from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structured_prototype_fixtures import fixture_id, procurement_document_payload

import app.interfaces.structured_prototype_ai_api as ai_api
from app.adapters.prototype_object_store import PrototypeObjectStore
from app.adapters.prototype_render_artifact_store import PrototypeRenderArtifactStore
from app.adapters.prototype_renderer_worker import PrototypeRendererWorker
from app.adapters.structured_prototype_store import AsyncStructuredPrototypeStore
from app.application.structured_prototype_ai_contracts import (
    PrototypeAssistantOutcomeEnvelopeV1,
)
from app.application.structured_prototype_ai_mcp import PrototypeAiSubmissionReceipt
from app.application.structured_prototype_ai_runtime import (
    PrototypeUiEngineerTaskRequest,
    PrototypeUiEngineerTaskResult,
)
from app.application.structured_prototype_ai_service import StructuredPrototypeAiService
from app.application.structured_prototype_contracts import NewPrototypeDocumentV1
from app.application.structured_prototype_service import StructuredPrototypeService
from app.domain.models import Project

FIXED_NOW = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)


class _ProjectStore:
    def __init__(self, project: Project) -> None:
        self.project = project

    async def load_project(self, project_id: str) -> Project | None:
        return self.project if project_id == self.project.id else None


class _AnswerRuntime:
    async def execute(
        self,
        request: PrototypeUiEngineerTaskRequest,
    ) -> PrototypeUiEngineerTaskResult:
        outcome = PrototypeAssistantOutcomeEnvelopeV1.model_validate(
            {
                "outcome": {
                    "contractVersion": 1,
                    "kind": "answer",
                    "message": "列表页包含采购申请标题和表格。",
                }
            },
            strict=True,
            by_alias=True,
            by_name=False,
        ).outcome
        return PrototypeUiEngineerTaskResult(
            task_id=request.task_id,
            execution_process_id="process-api-1",
            outcome=outcome,
            submission=PrototypeAiSubmissionReceipt(
                submission_id="submission-api-1",
                request_hash="sha256:" + "a" * 64,
                accepted_at=1.0,
            ),
        )


def _new_document() -> NewPrototypeDocumentV1:
    payload = procurement_document_payload()
    payload.pop("id")
    return NewPrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )


def test_ai_thread_and_message_routes_return_recoverable_snapshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "managed")
    renderer = PrototypeRendererWorker()
    structured = StructuredPrototypeService(
        store=store,
        object_store=object_store,
        renderer_worker=renderer,
        artifact_store=PrototypeRenderArtifactStore(tmp_path / "managed"),
        clock=lambda: FIXED_NOW,
    )
    ai_service = StructuredPrototypeAiService(
        store=store,
        project_store=_ProjectStore(
            Project(id="project-1", name="Procurement", repo_path=str(tmp_path))
        ),
        object_store=object_store,
        structured_service=structured,
        runtime=_AnswerRuntime(),
        renderer_worker=renderer,
        artifact_store=PrototypeRenderArtifactStore(tmp_path / "managed"),
        clock=lambda: FIXED_NOW,
    )
    monkeypatch.setattr(ai_api, "structured_prototype_ai_service", ai_service)
    app = FastAPI()
    app.include_router(ai_api.router)

    with TestClient(app) as client:
        assert client.portal is not None
        created = client.portal.call(
            lambda: structured.create_document(
                project_id="project-1",
                client_request_id=fixture_id("ai-api-document"),
                document=_new_document(),
            )
        )
        thread_response = client.post(
            f"/api/prototype-documents/{created.state.document_record.id}/ai-threads",
            json={
                "contractVersion": 1,
                "clientRequestId": fixture_id("ai-api-thread"),
                "title": "采购调整",
            },
        )
        assert thread_response.status_code == 201
        thread = thread_response.json()
        assert thread["documentId"] == created.state.document_record.id

        message_response = client.post(
            f"/api/prototype-ai-threads/{thread['id']}/messages",
            json={
                "contractVersion": 1,
                "clientMessageId": fixture_id("ai-api-message"),
                "draftId": created.state.draft.id,
                "expectedHeadSequenceNo": 0,
                "expectedDocumentHash": created.state.draft.head_document_hash,
                "content": "当前列表页有什么?",
                "selection": {
                    "scope": "page",
                    "pageId": fixture_id("page-list"),
                    "selectedNodeIds": [],
                    "flowId": None,
                    "viewport": "desktop",
                },
            },
        )
        assert message_response.status_code == 202
        run_id = message_response.json()["id"]
        completed = client.portal.call(ai_service.wait_for_run, run_id)
        assert completed.status == "completed_answer"

        snapshot_response = client.get(f"/api/prototype-ai-threads/{thread['id']}")
        assert snapshot_response.status_code == 200
        snapshot = snapshot_response.json()
        assert snapshot["latestRun"]["status"] == "completed_answer"
        assert snapshot["latestRun"]["contextObjectHash"].startswith("sha256:")
        assert snapshot["latestRun"]["submissionId"] == "submission-api-1"
        assert snapshot["latestRun"]["submissionRequestHash"].startswith("sha256:")
        assert snapshot["latestRun"]["submissionAcceptedAt"] is not None
        assert snapshot["latestRun"]["replayManifestObjectHash"].startswith("sha256:")
        assert [message["kind"] for message in snapshot["messages"]] == [
            "instruction",
            "answer",
        ]

        invalid = client.post(
            f"/api/prototype-ai-threads/{thread['id']}/messages",
            json={
                "contract_version": 1,
                "client_message_id": fixture_id("ai-api-invalid"),
            },
        )
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "request_invalid"
        client.portal.call(store.close)
