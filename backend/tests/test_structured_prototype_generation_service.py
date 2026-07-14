from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_structured_prototype_generation_assembler import (
    _complete_blueprint_payload,
    _create_page_payload,
    _detail_page_payload,
    _list_page_payload,
)
from test_structured_prototype_generation_contracts import foundation_payload

from app.adapters.prototype_object_store import PrototypeObjectStore
from app.adapters.prototype_render_artifact_store import PrototypeRenderArtifactStore
from app.adapters.prototype_renderer_worker import PrototypeRendererWorker
from app.adapters.prototype_runtime_worker import PrototypeRuntimeWorker
from app.adapters.structured_prototype_store import AsyncStructuredPrototypeStore
from app.application.structured_prototype_generation_contracts import (
    GeneratedPageV1,
    GenerationArtifactEnvelopeV1,
    GenerationBlueprintEnvelopeV1,
    GenerationBlueprintV1,
    GenerationFoundationEnvelopeV1,
    GenerationFoundationV1,
    GenerationPageEnvelopeV1,
    generation_artifact_payload,
)
from app.application.structured_prototype_generation_mcp import GenerationSubmissionReceipt
from app.application.structured_prototype_generation_runtime import (
    StructuredPrototypeGenerationRuntimeError,
    StructuredPrototypeGenerationTaskRequest,
    StructuredPrototypeGenerationTaskResult,
)
from app.application.structured_prototype_generation_service import (
    StructuredPrototypeGenerationService,
)
from app.domain.models import Project

NOW = datetime(2026, 7, 13, 17, 0, tzinfo=UTC)


class _ProjectStore:
    def __init__(self, project: Project) -> None:
        self.project = project

    async def load_project(self, project_id: str) -> Project | None:
        return self.project if self.project.id == project_id else None


class _ControlledGenerationRuntime:
    def __init__(self, object_store: PrototypeObjectStore) -> None:
        self.object_store = object_store
        self.requests: list[StructuredPrototypeGenerationTaskRequest] = []

    async def execute(
        self,
        request: StructuredPrototypeGenerationTaskRequest,
    ) -> StructuredPrototypeGenerationTaskResult:
        self.requests.append(request)
        artifact: GenerationArtifactEnvelopeV1
        identity = {
            "generationContractVersion": 1,
            "jobId": request.job_id,
            "runId": request.run_id,
            "itemId": request.item_id,
            "taskKind": request.task_kind,
            "contextObjectHash": request.context_object_hash,
        }
        if request.task_kind == "generation_blueprint":
            artifact = GenerationBlueprintEnvelopeV1.model_validate(
                {
                    **identity,
                    "payload": GenerationBlueprintV1.model_validate(
                        _complete_blueprint_payload(), strict=True
                    ).model_dump(mode="json", by_alias=True),
                },
                strict=True,
            )
        elif request.task_kind == "generation_foundation":
            artifact = GenerationFoundationEnvelopeV1.model_validate(
                {
                    **identity,
                    "payload": GenerationFoundationV1.model_validate(
                        foundation_payload(), strict=True
                    ).model_dump(mode="json", by_alias=True),
                },
                strict=True,
            )
        else:
            page_context = request.frozen_context["page"]
            assert isinstance(page_context, dict)
            page_key = page_context["pageKey"]
            page_payload = {
                "purchase-list": _list_page_payload,
                "purchase-create": _create_page_payload,
                "purchase-detail": _detail_page_payload,
            }[page_key]()
            artifact = GenerationPageEnvelopeV1.model_validate(
                {
                    **identity,
                    "payload": GeneratedPageV1.model_validate(page_payload, strict=True).model_dump(
                        mode="json", by_alias=True
                    ),
                },
                strict=True,
            )
        descriptor = self.object_store.write_json(
            request.project.id,
            generation_artifact_payload(artifact),
        )
        return StructuredPrototypeGenerationTaskResult(
            task_id=request.task_id,
            execution_process_id=f"process-{request.item_id}",
            submission=GenerationSubmissionReceipt(
                submission_id=f"submission-{request.item_id}",
                request_hash="sha256:" + "a" * 64,
                accepted_at=NOW.timestamp(),
                normalized_fields=("payload.root.gap",)
                if request.task_kind == "generation_page"
                else (),
            ),
            artifact_descriptor=descriptor,
            envelope=artifact,
        )


class _FailingGenerationRuntime:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def execute(
        self,
        request: StructuredPrototypeGenerationTaskRequest,
    ) -> StructuredPrototypeGenerationTaskResult:
        del request
        raise self.error


@pytest.mark.asyncio
async def test_plan_first_generation_reaches_replayable_rendered_candidate(tmp_path: Path) -> None:
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "managed")
    runtime = _ControlledGenerationRuntime(object_store)
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
        runtime=runtime,
        runtime_worker=PrototypeRuntimeWorker(),
        renderer=PrototypeRendererWorker(),
        artifact_store=PrototypeRenderArtifactStore(tmp_path / "managed"),
        clock=lambda: NOW,
    )
    try:
        created = await service.create_requirements_job(
            project_id=project.id,
            client_request_id="ba5cff3a-d2cf-54fb-94a2-d21cfe7f64bc",
            brief="生成一个采购申请、主管审批并同步状态的三页原型",
        )
        planned = await service.wait_for_job(created.job.id)

        assert planned.job.status == "awaiting_confirmation"
        assert planned.job.blueprint_hash is not None
        assert [request.task_kind for request in runtime.requests] == ["generation_blueprint"]
        required_blueprint = runtime.requests[0].frozen_context["requiredBlueprintContract"]
        assert isinstance(required_blueprint, dict)
        assert required_blueprint["pages"] == [
            {
                "pageKey": "purchase-list",
                "route": "/purchases",
            },
            {
                "pageKey": "purchase-create",
                "route": "/purchases/new",
            },
            {
                "pageKey": "purchase-detail",
                "route": "/purchases/detail",
            },
        ]
        assert required_blueprint["startPageKeys"] == ["purchase-create"]

        await service.confirm_blueprint(
            job_id=planned.job.id,
            client_request_id="1a775189-500d-5676-8716-64d51f96f5ad",
            expected_blueprint_hash=planned.job.blueprint_hash,
        )
        ready = await service.wait_for_job(planned.job.id)

        assert ready.job.status == "ready"
        assert ready.job.candidate_object_hash == ready.job.candidate_document_hash
        assert ready.job.replay_manifest_object_hash is not None
        assert ready.job.preview_renderer_version == "structured-prototype-renderer/0.1.0"
        assert ready.latest_run is not None
        assert ready.latest_run.status == "completed"
        assert [item.item_key for item in ready.items] == [
            "purchase-list",
            "purchase-create",
            "purchase-detail",
        ]
        assert all(item.output_object_hash is not None for item in ready.items)
        assert all(
            item.submission_normalized_fields == ("payload.root.gap",)
            for item in ready.items
        )
        replay_descriptor = await store.load_object(
            project.id,
            ready.job.replay_manifest_object_hash,
        )
        assert replay_descriptor is not None
        replay_manifest = json.loads(object_store.read_canonical_bytes(replay_descriptor))
        assert replay_manifest["submissionNormalizations"] == [
            {
                "itemId": item.id,
                "requestHash": item.submission_request_hash,
                "normalizedFields": ["payload.root.gap"],
            }
            for item in ready.items
        ]
        assert [request.task_kind for request in runtime.requests] == [
            "generation_blueprint",
            "generation_foundation",
            "generation_page",
            "generation_page",
            "generation_page",
        ]
        assert runtime.requests[1].frozen_context["requiredTokenKeys"] == {
            "colors": ["primary", "surface"],
            "spacing": ["panel-gap"],
        }
        list_context = runtime.requests[2].frozen_context
        assert list_context["requiredNodes"] == {
            "list-title": "Text",
            "request-table": "Table",
        }
        assert list_context["requiredTableColumns"] == ["title", "amount", "status"]
        assert runtime.requests[3].frozen_context["requiredNodes"] == {
            "create-form": "Form",
            "title-input": "Input",
            "amount-input": "Input",
            "submit-request": "Button",
        }
        create_skeleton = runtime.requests[3].frozen_context["requiredPageSkeleton"]
        assert isinstance(create_skeleton, dict)
        create_root = create_skeleton["root"]
        assert isinstance(create_root, dict)
        assert create_root["gap"] == 16
        assert create_root["padding"] == 24
        assert isinstance(create_root["children"], list)
        assert runtime.requests[4].frozen_context["requiredNodes"] == {
            "detail-heading": "Text",
            "detail-title": "Text",
            "detail-status": "Text",
            "approve-request": "Button",
        }
        preview = await service.read_preview_file(ready.job.id, "index.html")
        assert b"<!doctype html>" in preview.lower()
        operation = await store.load_operation(ready.job.operation_id)
        assert operation is not None
        assert operation.status == "running"
        events = await store.list_operation_events(operation.id)
        assert [event.event_no for event in events] == list(range(len(events)))
        assert events[-1].event_kind == "step_succeeded"
        assert ready.job.candidate_object_hash is not None
        assert ready.job.preview_output_hash is not None

        accepted = await service.accept_candidate(
            job_id=ready.job.id,
            client_request_id="ba077cb6-2635-574d-b199-51d12c570ae9",
            expected_candidate_object_hash=ready.job.candidate_object_hash,
            expected_preview_output_hash=ready.job.preview_output_hash,
        )

        assert accepted.snapshot.job.status == "accepted"
        assert accepted.snapshot.job.document_id == accepted.document.id
        assert accepted.draft.status == "active"
        assert accepted.draft.head_sequence_no == 0
        assert accepted.checkpoint.checkpoint_kind == "generation_accept"
        root_operation = await store.load_operation(ready.job.operation_id)
        assert root_operation is not None
        assert root_operation.status == "succeeded"
        assert root_operation.result_manifest_hash == accepted.snapshot.job.replay_manifest_object_hash
        recovery = await store.load_draft_recovery_bundle(accepted.draft.id)
        assert recovery.checkpoint.id == accepted.checkpoint.id
        assert recovery.object_descriptor.content_hash == ready.job.candidate_object_hash
    finally:
        await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (
            StructuredPrototypeGenerationRuntimeError(
                "generation_worktree_failed",
                "worktree unavailable",
            ),
            "generation_worktree_failed",
        ),
        (RuntimeError("unexpected startup failure"), "generation_internal_error"),
    ],
)
async def test_generation_startup_failure_persists_terminal_evidence(
    tmp_path: Path,
    error: Exception,
    expected_code: str,
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
        runtime=_FailingGenerationRuntime(error),
        runtime_worker=PrototypeRuntimeWorker(),
        renderer=PrototypeRendererWorker(),
        artifact_store=PrototypeRenderArtifactStore(tmp_path / "managed"),
        clock=lambda: NOW,
    )
    try:
        created = await service.create_requirements_job(
            project_id=project.id,
            client_request_id="bab163ea-e8f0-5f01-9139-58bbdbe62743",
            brief="生成采购审批原型",
        )

        failed = await service.wait_for_job(created.job.id)

        assert failed.job.status == "failed"
        assert failed.job.error_code == expected_code
        assert failed.latest_run is not None
        assert failed.latest_run.status == "failed"
        assert failed.latest_run.running == 0
        assert failed.latest_run.pending == 0
        assert [item.status for item in failed.items] == ["failed"]
        assert [item.error_code for item in failed.items] == [expected_code]
        root_operation = await store.load_operation(failed.job.operation_id)
        item_operation = await store.load_operation(failed.items[0].operation_id)
        assert root_operation is not None and root_operation.status == "failed"
        assert item_operation is not None and item_operation.status == "failed"
    finally:
        await store.close()
