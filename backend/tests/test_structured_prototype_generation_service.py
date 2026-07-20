from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import aiosqlite
import pytest
from test_structured_prototype_generation_assembler import (
    _complete_blueprint_payload,
    _create_page_payload,
    _detail_page_payload,
    _list_page_payload,
)
from test_structured_prototype_generation_contracts import foundation_payload

from app.adapters.prototype_object_store import PrototypeObjectStore, canonical_json_bytes
from app.adapters.prototype_render_artifact_store import PrototypeRenderArtifactStore
from app.adapters.prototype_renderer_worker import PrototypeRendererWorker
from app.adapters.prototype_runtime_worker import PrototypeRuntimeWorker
from app.adapters.structured_prototype_store import (
    AsyncStructuredPrototypeStore,
    StructuredPrototypeStoreError,
)
from app.application.git_service import GitError
from app.application.prototype_ui_engineer_runner import (
    PrototypeUiEngineerActivityCallback,
)
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
    GenerationMcpSubmissionEvidence,
    GenerationProcessStartedEvidence,
    GenerationProcessTerminalEvidence,
    GenerationTaskCreatedEvidence,
    GenerationWireInputEvidence,
    StructuredPrototypeGenerationEvidenceCallback,
    StructuredPrototypeGenerationRuntimeError,
    StructuredPrototypeGenerationRuntimeGovernance,
    StructuredPrototypeGenerationTaskRequest,
    StructuredPrototypeGenerationTaskResult,
)
from app.application.structured_prototype_generation_service import (
    StructuredPrototypeGenerationService,
    StructuredPrototypeGenerationServiceError,
)
from app.application.structured_prototype_service import StructuredPrototypeService
from app.domain.models import CodexTask, ExecutionProcess, Project
from app.domain.structured_prototype import (
    PrototypeObjectDescriptor,
    PrototypeObjectReference,
    PrototypeOperation,
    PrototypeReplayManifestV1,
)
from app.domain.structured_prototype_generation import (
    PrototypeDocumentGenerationItemRecord,
    PrototypeGenerationCommittedHeadCapture,
)

NOW = datetime(2026, 7, 13, 17, 0, tzinfo=UTC)
CONTENT_POLICY = {
    "version": 1,
    "precedence": [
        "frozen-task-scope",
        "repository-runtime-evidence",
        "generated-fallback",
    ],
    "evidenceScope": "target-runtime-dependency-chain",
    "copyMode": "verbatim",
    "valueMode": "semantic-exact",
    "fallbackMode": "structure-only-minimal",
    "subsetMode": "source-backed-only",
}
GENERATION_ITEM_STEP_KINDS = (
    "job_run_item_created",
    "context_freeze",
    "governance_decision",
    "claude_task_created",
    "claude_process_started",
    "runtime_wire_input",
    "mcp_submission",
    "claude_process_terminal",
    "artifact_object_registered",
    "strict_schema_validation",
    "semantic_validation",
)


def _record(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def _records(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    records: list[dict[str, object]] = []
    for item in value:
        assert isinstance(item, dict)
        records.append(item)
    return records


async def _assert_complete_generation_item_evidence(
    *,
    store: AsyncStructuredPrototypeStore,
    object_store: PrototypeObjectStore,
    project_id: str,
    item: PrototypeDocumentGenerationItemRecord,
) -> None:
    operation = await store.load_operation(item.operation_id)
    assert operation is not None and operation.status == "succeeded"
    assert operation.result_manifest_hash is not None
    steps = await store.list_operation_steps(item.operation_id)
    assert tuple(step.step_kind for step in steps) == GENERATION_ITEM_STEP_KINDS
    assert all(step.status == "succeeded" for step in steps)
    for step in steps:
        assert step.output_manifest_hash is not None
        assert step.completion_evidence_ref == step.output_manifest_hash
        descriptor = await store.load_object(project_id, step.output_manifest_hash)
        assert descriptor is not None
        assert object_store.read_canonical_bytes(descriptor)
    events = await store.list_operation_events(item.operation_id)
    assert [event.event_no for event in events] == list(range(len(events)))
    assert events[0].event_kind == "operation_queued"
    assert len(events) == 1 + (2 * len(GENERATION_ITEM_STEP_KINDS))
    mcp_step = next(step for step in steps if step.step_kind == "mcp_submission")
    assert mcp_step.output_manifest_hash is not None
    mcp_descriptor = await store.load_object(project_id, mcp_step.output_manifest_hash)
    assert mcp_descriptor is not None
    mcp_manifest = json.loads(object_store.read_canonical_bytes(mcp_descriptor))
    assert mcp_manifest["stepKind"] == "mcp_submission"
    details = mcp_manifest["details"]
    assert isinstance(details, dict)
    assert details["scopeFingerprint"] == "sha256:" + "c" * 64
    assert details["envelopeHash"] == item.output_object_hash
    assert details["pathContained"] is True
    replay_references = await store.list_object_references(
        project_id,
        "replay_manifest",
        item.operation_id,
    )
    assert len(replay_references) == 1
    replay_reference = replay_references[0]
    assert replay_reference.role == "operation-replay-manifest"
    assert replay_reference.content_hash == operation.result_manifest_hash
    replay_descriptor = await store.load_object(project_id, replay_reference.content_hash)
    assert replay_descriptor is not None
    replay_manifest = PrototypeReplayManifestV1.from_canonical_json(
        object_store.read_canonical_bytes(replay_descriptor)
    )
    strict_step = next(step for step in steps if step.step_kind == "strict_schema_validation")
    semantic_step = next(step for step in steps if step.step_kind == "semantic_validation")
    assert replay_manifest.operation_id == item.operation_id
    assert replay_manifest.operation_kind == "generation_item"
    assert replay_manifest.parent_operation_id == operation.parent_operation_id
    assert replay_manifest.request_manifest_hash == operation.request_manifest_hash
    assert replay_manifest.context_manifest_hash == item.context_object_hash
    assert item.output_object_hash in replay_manifest.ordered_input_object_hashes
    assert replay_manifest.submission_hash == item.output_object_hash
    assert replay_manifest.validation_report_hashes == (
        strict_step.output_manifest_hash,
        semantic_step.output_manifest_hash,
    )
    assert replay_manifest.agent_task_identity is not None
    assert replay_manifest.agent_task_identity["taskId"] == item.task_id
    assert replay_manifest.agent_task_identity["executionProcessId"] == item.execution_process_id
    assert replay_manifest.agent_task_identity["taskKind"] == item.task_kind
    assert replay_manifest.agent_task_identity["runtimeProfileId"] == "test-claude-profile"
    assert replay_manifest.agent_task_identity["runtimeProfileHash"] == "sha256:" + "1" * 64
    assert replay_manifest.agent_task_identity["generationPromptVersion"] == (
        "structured-prototype-generation/v13"
    )
    assert replay_manifest.terminal_status == "succeeded"


class _ProjectStore:
    def __init__(self, project: Project) -> None:
        self.project = project

    async def load_project(self, project_id: str) -> Project | None:
        return self.project if self.project.id == project_id else None

    async def list_projects(self) -> list[Project]:
        return [self.project]


class _MultiProjectStore:
    def __init__(self, projects: list[Project]) -> None:
        self.projects = projects

    async def load_project(self, project_id: str) -> Project | None:
        return next((project for project in self.projects if project.id == project_id), None)

    async def list_projects(self) -> list[Project]:
        return self.projects


class _SourceControl:
    def __init__(self) -> None:
        self.captures: list[tuple[str, str]] = []

    async def capture_committed_head_snapshot(
        self,
        repo_path: str,
        job_id: str,
    ) -> PrototypeGenerationCommittedHeadCapture:
        self.captures.append((repo_path, job_id))
        return PrototypeGenerationCommittedHeadCapture(
            snapshot_ref=f"refs/agent-collab/prototype-generation/{job_id}",
            repository_object_format="sha1",
            worktree_base_commit="a" * 40,
            repository_project_prefix="",
            repository_tree_object_id="b" * 40,
            source_file_exclusion_policy="dotenv_checkout_filter_v1",
            working_tree_dirty=True,
            excluded_tracked_change_count=2,
            excluded_untracked_count=1,
            excluded_sensitive_file_count=1,
            excluded_status_hash="sha256:" + "c" * 64,
        )


class _FailingSourceControl:
    async def capture_committed_head_snapshot(
        self,
        repo_path: str,
        job_id: str,
    ) -> PrototypeGenerationCommittedHeadCapture:
        del repo_path, job_id
        raise GitError("repository snapshot is unavailable")


class _PausingSourceControl:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def capture_committed_head_snapshot(
        self,
        repo_path: str,
        job_id: str,
    ) -> PrototypeGenerationCommittedHeadCapture:
        del repo_path, job_id
        self.started.set()
        await self.release.wait()
        raise AssertionError("paused source capture should be cancelled before release")


class _ResourceCleaner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, frozenset[str]]] = []

    async def cleanup_stale_prototype_generation_resources(
        self,
        project: Project,
        *,
        owned_snapshot_job_ids: frozenset[str],
    ) -> None:
        self.calls.append((project.id, owned_snapshot_job_ids))


class _ControlledGenerationRuntime:
    def __init__(
        self,
        object_store: PrototypeObjectStore,
        *,
        pause_after_activity: bool = False,
        page_release: asyncio.Event | None = None,
        failed_page_key: str | None = None,
        paused_task_kind: str | None = None,
    ) -> None:
        self.object_store = object_store
        self.requests: list[StructuredPrototypeGenerationTaskRequest] = []
        self.artifact_hashes: list[str] = []
        self.artifact_hashes_by_item_id: dict[str, str] = {}
        self.activity_started = asyncio.Event()
        self.release = asyncio.Event()
        self.page_release = page_release
        self.failed_page_key = failed_page_key
        self.paused_task_kind = paused_task_kind
        self.paused_task_started = asyncio.Event()
        self.paused_task_release = asyncio.Event()
        self.page_capacity_reached = asyncio.Event()
        self.active_page_executions = 0
        self.active_page_processes = 0
        self.max_active_page_executions = 0
        if not pause_after_activity:
            self.release.set()

    async def evaluate_runtime_governance(
        self,
        request: StructuredPrototypeGenerationTaskRequest,
    ) -> StructuredPrototypeGenerationRuntimeGovernance:
        del request
        return StructuredPrototypeGenerationRuntimeGovernance(
            runtime_available=True,
            runtime_profile_id="test-claude-profile",
            runtime_profile_hash="sha256:" + "1" * 64,
            executor="claude",
            executor_adapter_version="test-adapter/v1",
            runtime_binary="/usr/local/bin/claude",
            runtime_binary_hash="sha256:" + "2" * 64,
            claude_code_version="test-claude/1",
            reason_code=None,
        )

    async def execute(
        self,
        request: StructuredPrototypeGenerationTaskRequest,
        *,
        activity_callback: PrototypeUiEngineerActivityCallback | None = None,
        evidence_callback: StructuredPrototypeGenerationEvidenceCallback | None = None,
    ) -> StructuredPrototypeGenerationTaskResult:
        self.requests.append(request)
        is_page = request.task_kind == "generation_page"
        if is_page:
            self.active_page_executions += 1
            self.max_active_page_executions = max(
                self.max_active_page_executions,
                self.active_page_executions,
            )
        process_id = f"process-{request.item_id}"
        process_evidence_started = False
        try:
            del activity_callback
            assert evidence_callback is not None
            task = CodexTask(
                id=request.task_id,
                session_id=f"workspace-{request.project.id}",
                project_id=request.project.id,
                title=f"Generate structured prototype: {request.task_kind}",
                prompt="test generation prompt",
                role="prototype_ui_engineer",
                executor="claude",
                task_kind=request.task_kind,
                status="running",
                workspace_path=str(request.project.repo_path),
                git_worktree_path=str(request.project.repo_path),
            )
            await evidence_callback(
                GenerationTaskCreatedEvidence(
                    task=task,
                    task_id=task.id,
                    workspace_id=task.session_id,
                    worktree_path=str(request.project.repo_path),
                    repository_root=str(request.project.repo_path),
                    worktree_path_contained=True,
                    worktree_base_commit=request.source_snapshot.worktree_base_commit,
                    source_snapshot_ref=request.source_snapshot.source_snapshot_ref,
                    source_fingerprint=request.source_snapshot.source_fingerprint,
                    executor="claude",
                    runtime_profile_id="test-claude-profile",
                    runtime_profile_hash="sha256:" + "1" * 64,
                    runtime_binary="/usr/local/bin/claude",
                    runtime_binary_hash="sha256:" + "2" * 64,
                    adapter_config_hash="sha256:" + "3" * 64,
                    executor_adapter_version="test-adapter/v1",
                )
            )
            running_process = ExecutionProcess(
                id=process_id,
                task_id=task.id,
                session_id=task.session_id,
                status="Running",
                executor="claude",
                started_at=NOW,
            )
            await evidence_callback(
                GenerationProcessStartedEvidence(
                    task_id=task.id,
                    task=task,
                    process=running_process,
                )
            )
            if is_page:
                self.active_page_processes += 1
                process_evidence_started = True
                if self.active_page_processes >= 2:
                    self.page_capacity_reached.set()
            self.activity_started.set()
            if request.task_kind == self.paused_task_kind:
                self.paused_task_started.set()
                await self.paused_task_release.wait()
            if is_page and self.page_release is not None:
                await self.page_release.wait()
            await self.release.wait()
            await evidence_callback(
                GenerationWireInputEvidence(
                    task_id=task.id,
                    execution_process_id=process_id,
                    final_runtime_wire_input_hash="sha256:" + "4" * 64,
                    wire_input_size=128,
                    framing="test",
                    runtime_profile_id="test-claude-profile",
                    runtime_profile_hash="sha256:" + "1" * 64,
                    executor="claude",
                    executor_type="claude",
                    provider="test",
                    model="test-model",
                    runtime_config_hash="sha256:" + "5" * 64,
                    runtime_binary="/usr/local/bin/claude",
                    runtime_binary_hash="sha256:" + "2" * 64,
                    adapter_config_hash="sha256:" + "3" * 64,
                    executor_adapter_version="test-adapter/v1",
                    claude_code_version="test-claude/1",
                )
            )
            artifact: GenerationArtifactEnvelopeV1
            identity = {
                "generationContractVersion": 3,
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
                if page_key == self.failed_page_key:
                    raise StructuredPrototypeGenerationRuntimeError(
                        "generation_agent_failed",
                        f"page generation failed: {page_key}",
                    )
                page_payload = {
                    "dashboard": _list_page_payload,
                    "users": _create_page_payload,
                    "orders": _detail_page_payload,
                }[page_key]()
                artifact = GenerationPageEnvelopeV1.model_validate(
                    {
                        **identity,
                        "payload": GeneratedPageV1.model_validate(
                            page_payload,
                            strict=True,
                        ).model_dump(mode="json", by_alias=True),
                    },
                    strict=True,
                )
            artifact_payload = generation_artifact_payload(artifact)
            artifact_bytes = canonical_json_bytes(artifact_payload)
            artifact_hash = "sha256:" + hashlib.sha256(artifact_bytes).hexdigest()
            receipt = GenerationSubmissionReceipt(
                submission_id=f"submission-{request.item_id}",
                request_hash="sha256:" + "a" * 64,
                normalized_request_hash="sha256:" + "b" * 64,
                wire_input_hash="sha256:" + "4" * 64,
                scope_fingerprint="sha256:" + "c" * 64,
                envelope_hash=artifact_hash,
                envelope_size=len(artifact_bytes),
                accepted_at=NOW.timestamp(),
                repository_root=str(request.project.repo_path),
                resolved_path=str(Path(request.project.repo_path) / "staging.json"),
                path_contained=True,
                normalized_fields=("payload.root.gap",)
                if request.task_kind == "generation_page"
                else (),
            )
            await evidence_callback(
                GenerationMcpSubmissionEvidence(
                    project_id=request.project.id,
                    job_id=request.job_id,
                    run_id=request.run_id,
                    item_id=request.item_id,
                    task_id=task.id,
                    execution_process_id=process_id,
                    task_kind=request.task_kind,
                    context_object_hash=request.context_object_hash,
                    submission_id=receipt.submission_id,
                    request_hash=receipt.request_hash,
                    normalized_request_hash=receipt.normalized_request_hash,
                    wire_input_hash=receipt.wire_input_hash,
                    scope_fingerprint=receipt.scope_fingerprint,
                    accepted_at=receipt.accepted_at,
                    envelope_hash=receipt.envelope_hash,
                    envelope_size=receipt.envelope_size,
                    repository_root=receipt.repository_root,
                    resolved_path=receipt.resolved_path,
                    path_contained=True,
                    normalized_fields=receipt.normalized_fields,
                )
            )
            completed_process = running_process.model_copy(
                update={
                    "status": "Completed",
                    "exit_code": 0,
                    "input_tokens": 40,
                    "output_tokens": 60,
                    "total_cost_usd": 0.01,
                    "completed_at": NOW,
                }
            )
            await evidence_callback(
                GenerationProcessTerminalEvidence(
                    task_id=task.id,
                    process=completed_process,
                    task_status="done",
                    result_hash="sha256:" + "d" * 64,
                    result_size=256,
                    input_tokens=40,
                    output_tokens=60,
                    cache_read_tokens=None,
                    total_cost_usd=0.01,
                )
            )
            descriptor = self.object_store.write_json(request.project.id, artifact_payload)
            self.artifact_hashes.append(descriptor.content_hash)
            self.artifact_hashes_by_item_id[request.item_id] = descriptor.content_hash
            return StructuredPrototypeGenerationTaskResult(
                task_id=request.task_id,
                execution_process_id=process_id,
                submission=receipt,
                artifact_descriptor=descriptor,
                envelope=artifact,
            )
        finally:
            if is_page:
                self.active_page_executions -= 1
                if process_evidence_started:
                    self.active_page_processes -= 1


class _FailingGenerationRuntime:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def evaluate_runtime_governance(
        self,
        request: StructuredPrototypeGenerationTaskRequest,
    ) -> StructuredPrototypeGenerationRuntimeGovernance:
        del request
        return StructuredPrototypeGenerationRuntimeGovernance(
            runtime_available=True,
            runtime_profile_id="test-claude-profile",
            runtime_profile_hash="sha256:" + "1" * 64,
            executor="claude",
            executor_adapter_version="test-adapter/v1",
            runtime_binary="/usr/local/bin/claude",
            runtime_binary_hash="sha256:" + "2" * 64,
            claude_code_version="test-claude/1",
            reason_code=None,
        )

    async def execute(
        self,
        request: StructuredPrototypeGenerationTaskRequest,
        *,
        activity_callback: PrototypeUiEngineerActivityCallback | None = None,
        evidence_callback: StructuredPrototypeGenerationEvidenceCallback | None = None,
    ) -> StructuredPrototypeGenerationTaskResult:
        del request, activity_callback, evidence_callback
        raise self.error


class _EvidenceRegistrationFailingStore(AsyncStructuredPrototypeStore):
    failed_evidence_hash: str | None = None

    @staticmethod
    async def _insert_object_reference(
        conn: aiosqlite.Connection,
        reference: PrototypeObjectReference,
    ) -> None:
        if reference.role == "claude_task_created-evidence":
            _EvidenceRegistrationFailingStore.failed_evidence_hash = reference.content_hash
            raise StructuredPrototypeStoreError(
                "generation_evidence_registration_failed",
                "generation evidence object reference could not be registered",
            )
        await AsyncStructuredPrototypeStore._insert_object_reference(conn, reference)


class _ReplayRegistrationFailingStore(AsyncStructuredPrototypeStore):
    failed_replay_hash: str | None = None

    @staticmethod
    async def _insert_object_reference(
        conn: aiosqlite.Connection,
        reference: PrototypeObjectReference,
    ) -> None:
        if reference.role == "operation-replay-manifest":
            _ReplayRegistrationFailingStore.failed_replay_hash = reference.content_hash
            raise StructuredPrototypeStoreError(
                "generation_replay_registration_failed",
                "generation replay manifest reference could not be registered",
            )
        await AsyncStructuredPrototypeStore._insert_object_reference(conn, reference)


@pytest.mark.asyncio
async def test_plan_first_generation_reaches_replayable_rendered_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "managed")
    runtime = _ControlledGenerationRuntime(
        object_store,
        paused_task_kind="generation_foundation",
    )
    project = Project(
        id="project-1",
        name="admin-demo",
        repo_path=str(tmp_path),
        default_branch="main",
    )
    source_control = _SourceControl()
    service = StructuredPrototypeGenerationService(
        store=store,
        project_store=_ProjectStore(project),
        object_store=object_store,
        runtime=runtime,
        runtime_worker=PrototypeRuntimeWorker(),
        renderer=PrototypeRendererWorker(),
        artifact_store=PrototypeRenderArtifactStore(tmp_path / "managed"),
        source_control=source_control,
        resource_cleaner=_ResourceCleaner(),
        clock=lambda: NOW,
    )
    try:
        created = await service.create_requirements_job(
            project_id=project.id,
            client_request_id="ba5cff3a-d2cf-54fb-94a2-d21cfe7f64bc",
            brief="基于项目源码生成仪表盘、用户管理和订单管理的可编辑原型",
        )
        planned = await service.wait_for_job(created.job.id)

        assert planned.job.status == "awaiting_confirmation", planned.job.error_code
        assert planned.job.blueprint_hash is not None
        retried = await service.create_requirements_job(
            project_id=project.id,
            client_request_id="ba5cff3a-d2cf-54fb-94a2-d21cfe7f64bc",
            brief="基于项目源码生成仪表盘、用户管理和订单管理的可编辑原型",
        )
        assert retried == planned
        assert len(source_control.captures) == 1
        with pytest.raises(StructuredPrototypeGenerationServiceError) as conflict:
            await service.create_requirements_job(
                project_id=project.id,
                client_request_id="ba5cff3a-d2cf-54fb-94a2-d21cfe7f64bc",
                brief="different requirements",
            )
        assert conflict.value.code == "generation_job_idempotency_conflict"
        assert len(source_control.captures) == 1
        assert [request.task_kind for request in runtime.requests] == ["generation_blueprint"]
        blueprint_context = runtime.requests[0].frozen_context
        assert blueprint_context["projectName"] == "admin-demo"
        assert blueprint_context["contentPolicy"] == CONTENT_POLICY
        assert blueprint_context["generationPolicy"] == {
            "sourceAuthority": "project-repository",
            "scopeAuthority": "confirmed-blueprint",
            "pageLimit": 20,
            "businessIntentsOptional": True,
            "requireRepositoryEvidence": True,
            "forbidPresetBusinessDomains": True,
        }
        assert (await store.load_generation_restart_recovery_scope()).operations == ()
        assert await service.recover_interrupted_jobs() == 0
        still_planned = await service.get_job(planned.job.id)
        assert still_planned.job.status == "awaiting_confirmation"
        assert still_planned.job.operation_id == planned.job.operation_id

        confirm_started = await service.confirm_blueprint(
            job_id=planned.job.id,
            client_request_id="1a775189-500d-5676-8716-64d51f96f5ad",
            expected_blueprint_version=planned.job.blueprint_version,
            expected_blueprint_hash=planned.job.blueprint_hash,
        )
        confirm_operation = await store.load_operation(confirm_started.operation_id)
        assert confirm_operation is not None
        assert confirm_started.operation_id == confirm_operation.id
        assert confirm_started.correlation_id == confirm_operation.correlation_id
        assert confirm_started.operation_id != planned.job.operation_id
        assert confirm_operation.parent_operation_id == planned.job.operation_id
        assert confirm_started.snapshot.job.operation_id == planned.job.operation_id
        await asyncio.wait_for(runtime.paused_task_started.wait(), timeout=2)
        with pytest.raises(StructuredPrototypeGenerationServiceError) as confirm_in_progress:
            await service.confirm_blueprint(
                job_id=planned.job.id,
                client_request_id="1a775189-500d-5676-8716-64d51f96f5ad",
                expected_blueprint_version=planned.job.blueprint_version,
                expected_blueprint_hash=planned.job.blueprint_hash,
            )
        assert confirm_in_progress.value.code == "generation_confirm_in_progress"
        with pytest.raises(StructuredPrototypeGenerationServiceError) as confirm_conflict:
            await service.confirm_blueprint(
                job_id=planned.job.id,
                client_request_id="1a775189-500d-5676-8716-64d51f96f5ad",
                expected_blueprint_version=planned.job.blueprint_version + 1,
                expected_blueprint_hash=planned.job.blueprint_hash,
            )
        assert confirm_conflict.value.code == "generation_confirm_idempotency_conflict"
        runtime.paused_task_release.set()
        ready = await service.wait_for_job(planned.job.id)

        confirm_retried = await service.confirm_blueprint(
            job_id=planned.job.id,
            client_request_id="1a775189-500d-5676-8716-64d51f96f5ad",
            expected_blueprint_version=planned.job.blueprint_version,
            expected_blueprint_hash=planned.job.blueprint_hash,
        )

        assert ready.job.status == "ready", (ready.job.error_code, ready.job.error_message)
        await _assert_complete_generation_item_evidence(
            store=store,
            object_store=object_store,
            project_id=project.id,
            item=planned.items[0],
        )
        await _assert_complete_generation_item_evidence(
            store=store,
            object_store=object_store,
            project_id=project.id,
            item=ready.items[0],
        )
        root_steps = await store.list_operation_steps(ready.job.operation_id)
        assert root_steps[0].step_kind == "source_capture"
        assert root_steps[0].status == "succeeded"
        assert root_steps[0].output_manifest_hash == ready.job.source_snapshot_object_hash
        assert root_steps[0].completion_evidence_ref == ready.job.source_snapshot_object_hash
        assert confirm_retried.operation_id == confirm_started.operation_id
        assert confirm_retried.correlation_id == confirm_started.correlation_id
        assert confirm_retried.snapshot == ready
        assert ready.job.candidate_object_hash == ready.job.candidate_document_hash
        assert ready.job.replay_manifest_object_hash is not None
        assert ready.job.preview_renderer_version == "structured-prototype-renderer/0.2.0"
        assert ready.latest_run is not None
        assert ready.latest_run.status == "completed"
        assert [item.item_key for item in ready.items] == [
            "dashboard",
            "users",
            "orders",
        ]
        assert [item.item_ordinal for item in ready.items] == [0, 1, 2]
        assert all(item.output_object_hash is not None for item in ready.items)
        assert all(
            item.submission_normalized_fields == ("payload.root.gap",) for item in ready.items
        )
        replay_descriptor = await store.load_object(
            project.id,
            ready.job.replay_manifest_object_hash,
        )
        assert replay_descriptor is not None
        replay_manifest = PrototypeReplayManifestV1.from_canonical_json(
            object_store.read_canonical_bytes(replay_descriptor)
        )
        root_operation = await store.load_operation(ready.job.operation_id)
        assert root_operation is not None
        assert root_operation.status == "succeeded"
        assert root_operation.result_manifest_hash == replay_descriptor.content_hash
        assert replay_manifest.operation_id == ready.job.operation_id
        assert replay_manifest.operation_kind == "generation_job"
        assert replay_manifest.context_manifest_hash == ready.job.context_manifest_object_hash
        assert replay_manifest.versions.renderer_version == ("structured-prototype-renderer/0.2.0")
        assert replay_manifest.renderer_output_hash == ready.job.preview_output_hash
        assert replay_manifest.runtime_final_state_hash is not None
        assert replay_manifest.runtime_final_view_model_hash is not None
        conn = await store._get_conn()
        direct_child_rows = list(
            await (
                await conn.execute(
                    """
                    SELECT id, operation_kind, status, result_manifest_hash
                    FROM prototype_operations
                    WHERE parent_operation_id = ?
                    ORDER BY created_at, id
                    """,
                    (ready.job.operation_id,),
                )
            ).fetchall()
        )
        assert len(direct_child_rows) == 3
        assert sorted(str(row[1]) for row in direct_child_rows) == [
            "generation_item",
            "generation_job",
            "generation_job",
        ]
        child_replay_hashes: list[str] = []
        phase_step_kinds: list[tuple[str, ...]] = []
        for child_id, child_kind, child_status, child_result_hash in direct_child_rows:
            assert child_status == "succeeded"
            assert isinstance(child_result_hash, str)
            child_replay_hashes.append(child_result_hash)
            child_references = await store.list_object_references(
                project.id,
                "replay_manifest",
                str(child_id),
            )
            assert len(child_references) == 1
            child_descriptor = await store.load_object(
                project.id,
                child_references[0].content_hash,
            )
            assert child_descriptor is not None
            child_manifest = PrototypeReplayManifestV1.from_canonical_json(
                object_store.read_canonical_bytes(child_descriptor)
            )
            assert child_manifest.operation_id == child_id
            assert child_manifest.parent_operation_id == ready.job.operation_id
            if child_kind == "generation_job":
                phase_steps = await store.list_operation_steps(str(child_id))
                assert all(step.status == "succeeded" for step in phase_steps)
                phase_step_kinds.append(tuple(step.step_kind for step in phase_steps))
        assert ("freeze_context", "generate_foundation") in phase_step_kinds
        assert ("generate_pages",) in phase_step_kinds
        assert all(
            child_replay_hash in replay_manifest.ordered_input_object_hashes
            for child_replay_hash in child_replay_hashes
        )
        root_references = await store.list_object_references(
            project.id,
            "replay_manifest",
            ready.job.operation_id,
        )
        assert len(root_references) == 1
        assert root_references[0].role == "operation-replay-manifest"
        foundation_request = next(
            request for request in runtime.requests if request.task_kind == "generation_foundation"
        )
        assert replay_manifest.ordered_input_object_hashes[: 2 + len(ready.items)] == (
            ready.job.blueprint_object_hash,
            runtime.artifact_hashes_by_item_id[foundation_request.item_id],
            *(item.output_object_hash for item in ready.items),
        )
        assert ready.job.source_policy == "committed_head_v1"
        assert ready.job.source_snapshot_ref == planned.job.source_snapshot_ref
        assert ready.job.repository_object_format == "sha1"
        assert ready.job.worktree_base_commit == "a" * 40
        assert ready.job.source_file_exclusion_policy == "dotenv_checkout_filter_v1"
        assert ready.job.source_snapshot_object_hash in replay_manifest.ordered_input_object_hashes
        assert ready.job.candidate_object_hash in replay_manifest.ordered_input_object_hashes
        assert [request.task_kind for request in runtime.requests] == [
            "generation_blueprint",
            "generation_foundation",
            "generation_page",
            "generation_page",
            "generation_page",
        ]
        assert all(
            request.source_snapshot == runtime.requests[0].source_snapshot
            for request in runtime.requests
        )
        assert all(
            request.frozen_context["contentPolicy"] == CONTENT_POLICY
            for request in runtime.requests
        )
        assert runtime.requests[1].frozen_context["tokenPolicy"] == {
            "deriveFromProject": True,
            "minimumColorTokens": 2,
            "minimumSpacingTokens": 1,
        }
        assert runtime.requests[1].frozen_context["requiredComponentTypes"] == [
            "Stack",
            "Grid",
            "Form",
            "Text",
            "Input",
            "Button",
            "Table",
        ]
        dashboard_context = runtime.requests[2].frozen_context
        dashboard_page = _record(dashboard_context["page"])
        dashboard_policy = _record(dashboard_context["nodePolicy"])
        dashboard_intents = _record(dashboard_context["confirmedIntents"])
        assert dashboard_page["pageKey"] == "dashboard"
        assert dashboard_policy["deriveContentFromProject"] is True
        assert dashboard_policy["allowedTypes"] == [
            "Stack",
            "Grid",
            "Form",
            "Text",
            "Input",
            "Button",
            "Table",
        ]
        assert dashboard_intents["flows"] == [
            {
                "key": "dashboard-to-users",
                "sourcePageKey": "dashboard",
                "behaviorIntentKey": "open-users",
                "targetPageKey": "users",
            }
        ]
        assert dashboard_intents["viewBindings"] == []
        assert [item["key"] for item in _records(dashboard_intents["behaviors"])] == ["open-users"]
        assert dashboard_policy["requireFlowSourceNodes"] is True
        users_context = runtime.requests[3].frozen_context
        users_page = _record(users_context["page"])
        users_policy = _record(users_context["nodePolicy"])
        users_intents = _record(users_context["confirmedIntents"])
        assert users_page["pageKey"] == "users"
        assert [item["key"] for item in _records(users_intents["viewBindings"])] == [
            "users-table-rows"
        ]
        assert users_intents["behaviors"] == []
        assert users_policy["requireFlowSourceNodes"] is False
        orders_context = runtime.requests[4].frozen_context
        orders_page = _record(orders_context["page"])
        orders_intents = _record(orders_context["confirmedIntents"])
        assert orders_page["pageKey"] == "orders"
        assert [item["key"] for item in _records(orders_intents["viewBindings"])] == [
            "orders-table-rows"
        ]
        preview = await service.read_preview_file(ready.job.id, "index.html")
        assert b"<!doctype html>" in preview.lower()
        preview_document = await service.read_preview_file(ready.job.id, "document.json")
        assert ready.job.candidate_object_hash == (
            "sha256:" + hashlib.sha256(preview_document).hexdigest()
        )
        operation = await store.load_operation(ready.job.operation_id)
        assert operation is not None
        assert operation.status == "succeeded"
        events = await store.list_operation_events(operation.id)
        assert [event.event_no for event in events] == list(range(len(events)))
        assert events[-1].event_kind == "step_succeeded"
        assert ready.job.candidate_object_hash is not None
        assert ready.job.preview_output_hash is not None

        assert ready.job.preview_storage_key is not None
        styles_path = tmp_path / "managed" / ready.job.preview_storage_key / "styles.css"
        original_styles = styles_path.read_bytes()
        styles_path.write_bytes(b"tampered")
        try:
            with pytest.raises(StructuredPrototypeGenerationServiceError) as preview_error:
                await service.accept_candidate(
                    job_id=ready.job.id,
                    client_request_id="ba077cb6-2635-574d-b199-51d12c570ae9",
                    expected_candidate_object_hash=ready.job.candidate_object_hash,
                    expected_preview_output_hash=ready.job.preview_output_hash,
                    expected_source_fingerprint=cast(str, ready.job.source_fingerprint),
                )
        finally:
            styles_path.write_bytes(original_styles)
        assert preview_error.value.code == "render_artifact_hash_mismatch"
        assert (await service.get_job(ready.job.id)).job.status == "ready"

        failed_accept_request_id = "77e14173-b02e-5b13-bb14-5e9ee3657051"
        accept_candidate = store.accept_generation_candidate
        accept_running_observed = False

        async def fail_accept_candidate(**_kwargs: object) -> None:
            nonlocal accept_running_observed
            persisted_accept = await store.load_operation_by_request(
                project.id,
                "create_document",
                failed_accept_request_id,
            )
            assert persisted_accept is not None and persisted_accept.status == "running"
            persisted_steps = await store.list_operation_steps(persisted_accept.id)
            assert len(persisted_steps) == 1
            assert persisted_steps[0].step_kind == "accept_candidate"
            assert persisted_steps[0].status == "running"
            accept_running_observed = True
            raise StructuredPrototypeStoreError(
                "forced_accept_failure",
                "forced generation accept transaction failure",
            )

        monkeypatch.setattr(store, "accept_generation_candidate", fail_accept_candidate)
        with pytest.raises(StructuredPrototypeGenerationServiceError) as forced_accept_error:
            await service.accept_candidate(
                job_id=ready.job.id,
                client_request_id=failed_accept_request_id,
                expected_candidate_object_hash=ready.job.candidate_object_hash,
                expected_preview_output_hash=ready.job.preview_output_hash,
                expected_source_fingerprint=cast(str, ready.job.source_fingerprint),
            )
        assert forced_accept_error.value.code == "forced_accept_failure"
        assert accept_running_observed is True
        assert (await service.get_job(ready.job.id)).job.status == "ready"
        assert not any(
            step.status == "running"
            for step in await store.list_operation_steps(ready.job.operation_id)
        )
        conn = await store._get_conn()
        failed_accept_row = await (
            await conn.execute(
                "SELECT status, error_code FROM prototype_operations WHERE client_request_id = ?",
                (failed_accept_request_id,),
            )
        ).fetchone()
        assert failed_accept_row is not None
        assert tuple(failed_accept_row) == ("failed", "forced_accept_failure")
        with pytest.raises(StructuredPrototypeGenerationServiceError) as failed_retry:
            await service.accept_candidate(
                job_id=ready.job.id,
                client_request_id=failed_accept_request_id,
                expected_candidate_object_hash=ready.job.candidate_object_hash,
                expected_preview_output_hash=ready.job.preview_output_hash,
                expected_source_fingerprint=cast(str, ready.job.source_fingerprint),
            )
        assert failed_retry.value.code == "generation_accept_conflict"
        monkeypatch.setattr(store, "accept_generation_candidate", accept_candidate)

        accepted = await service.accept_candidate(
            job_id=ready.job.id,
            client_request_id="ba077cb6-2635-574d-b199-51d12c570ae9",
            expected_candidate_object_hash=ready.job.candidate_object_hash,
            expected_preview_output_hash=ready.job.preview_output_hash,
            expected_source_fingerprint=cast(str, ready.job.source_fingerprint),
        )

        assert accepted.snapshot.job.status == "accepted"
        assert accepted.snapshot.job.document_id == accepted.document.id
        assert accepted.draft.status == "active"
        assert accepted.draft.head_sequence_no == 0
        assert accepted.checkpoint.checkpoint_kind == "generation_accept"
        root_operation = await store.load_operation(ready.job.operation_id)
        assert root_operation is not None
        assert root_operation.status == "succeeded"
        assert (
            root_operation.result_manifest_hash == accepted.snapshot.job.replay_manifest_object_hash
        )
        accept_operation = await store.load_operation(accepted.checkpoint.created_by_operation_id)
        assert accept_operation is not None
        assert accepted.operation_id == accept_operation.id
        assert accepted.correlation_id == accept_operation.correlation_id
        assert accepted.operation_id != accepted.snapshot.job.operation_id
        assert accept_operation.status == "succeeded"
        assert accept_operation.result_manifest_hash is not None
        accept_references = await store.list_object_references(
            project.id,
            "replay_manifest",
            accept_operation.id,
        )
        assert len(accept_references) == 1
        accept_descriptor = await store.load_object(
            project.id,
            accept_references[0].content_hash,
        )
        assert accept_descriptor is not None
        accept_manifest = PrototypeReplayManifestV1.from_canonical_json(
            object_store.read_canonical_bytes(accept_descriptor)
        )
        assert accept_manifest.operation_id == accept_operation.id
        assert accept_manifest.operation_kind == "create_document"
        assert accept_manifest.parent_operation_id == root_operation.id
        assert accept_manifest.result_checkpoint_hash == ready.job.candidate_object_hash
        assert accept_manifest.result_sequence_no == 0
        recovery = await store.load_draft_recovery_bundle(accepted.draft.id)
        assert recovery.checkpoint.id == accepted.checkpoint.id
        assert recovery.object_descriptor.content_hash == ready.job.candidate_object_hash

        accept_retried = await service.accept_candidate(
            job_id=ready.job.id,
            client_request_id="ba077cb6-2635-574d-b199-51d12c570ae9",
            expected_candidate_object_hash=ready.job.candidate_object_hash,
            expected_preview_output_hash=ready.job.preview_output_hash,
            expected_source_fingerprint=cast(str, ready.job.source_fingerprint),
        )
        assert accept_retried == accepted
        assert accept_retried.operation_id == accept_operation.id
        assert accept_retried.correlation_id == accept_operation.correlation_id

        with pytest.raises(StructuredPrototypeGenerationServiceError) as accept_conflict:
            await service.accept_candidate(
                job_id=ready.job.id,
                client_request_id="ba077cb6-2635-574d-b199-51d12c570ae9",
                expected_candidate_object_hash="sha256:" + "0" * 64,
                expected_preview_output_hash=ready.job.preview_output_hash,
                expected_source_fingerprint=cast(str, ready.job.source_fingerprint),
            )
        assert accept_conflict.value.code == "generation_accept_idempotency_conflict"
    finally:
        runtime.paused_task_release.set()
        await store.close()


@pytest.mark.asyncio
async def test_page_generation_uses_bounded_parallel_slots_without_losing_process_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRUCTURED_PROTOTYPE_PAGE_GENERATION_CONCURRENCY", "2")
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "managed")
    page_release = asyncio.Event()
    runtime = _ControlledGenerationRuntime(object_store, page_release=page_release)
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
    job_id: str | None = None
    try:
        created = await service.create_requirements_job(
            project_id=project.id,
            client_request_id="ea5bb28b-b0d4-50f6-8f26-77482af1a8a7",
            brief="基于项目源码生成可编辑原型",
        )
        job_id = created.job.id
        planned = await service.wait_for_job(job_id)
        assert planned.job.blueprint_hash is not None
        await service.confirm_blueprint(
            job_id=job_id,
            client_request_id="e2c4b38b-684b-50d0-b7c9-50cffc1fb02c",
            expected_blueprint_version=planned.job.blueprint_version,
            expected_blueprint_hash=planned.job.blueprint_hash,
        )

        await asyncio.wait_for(runtime.page_capacity_reached.wait(), timeout=2)
        active = await service.get_job(job_id)

        assert active.latest_run is not None
        assert active.latest_run.status == "running"
        assert active.latest_run.running == 2
        assert active.latest_run.pending == 1
        generating = [item for item in active.items if item.status == "generating"]
        pending = [item for item in active.items if item.status == "pending"]
        assert len(generating) == 2
        assert len(pending) == 1
        assert len({item.execution_process_id for item in generating}) == 2
        assert all(item.execution_process_id is not None for item in generating)
        assert pending[0].execution_process_id is None

        page_release.set()
        ready = await service.wait_for_job(job_id)

        assert ready.job.status == "ready"
        assert ready.latest_run is not None
        assert ready.latest_run.status == "completed"
        assert [item.item_key for item in ready.items] == ["dashboard", "users", "orders"]
        assert all(item.status == "done" for item in ready.items)
        assert all(item.execution_process_id is not None for item in ready.items)
        assert runtime.max_active_page_executions == 2
    finally:
        page_release.set()
        if job_id is not None:
            await service.wait_for_job(job_id)
        await store.close()


@pytest.mark.asyncio
async def test_page_failure_preserves_successful_siblings_and_refuses_assembly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRUCTURED_PROTOTYPE_PAGE_GENERATION_CONCURRENCY", "2")
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "managed")
    runtime = _ControlledGenerationRuntime(object_store, failed_page_key="users")
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
    try:
        created = await service.create_requirements_job(
            project_id=project.id,
            client_request_id="d324bc62-1150-569e-91eb-2efd72dd4a8e",
            brief="基于项目源码生成可编辑原型",
        )
        planned = await service.wait_for_job(created.job.id)
        assert planned.job.blueprint_hash is not None
        await service.confirm_blueprint(
            job_id=created.job.id,
            client_request_id="d75271db-14a8-5ecf-b0f6-9c801015c8fc",
            expected_blueprint_version=planned.job.blueprint_version,
            expected_blueprint_hash=planned.job.blueprint_hash,
        )
        failed = await service.wait_for_job(created.job.id)

        assert failed.job.status == "failed"
        assert failed.job.error_code == "generation_agent_failed"
        assert failed.job.candidate_object_hash is None
        assert failed.job.preview_artifact_id is None
        assert failed.job.replay_manifest_object_hash is None
        assert failed.latest_run is not None
        assert failed.latest_run.status == "failed"
        assert failed.latest_run.processed == 3
        assert failed.latest_run.succeeded == 2
        assert failed.latest_run.failed == 1
        assert failed.latest_run.running == 0
        assert failed.latest_run.pending == 0
        assert [item.status for item in failed.items] == ["done", "failed", "done"]
        assert all(item.execution_process_id is not None for item in failed.items)
        assert failed.items[0].output_object_hash is not None
        assert failed.items[1].output_object_hash is None
        assert failed.items[2].output_object_hash is not None

        item_operations = [await store.load_operation(item.operation_id) for item in failed.items]
        assert all(operation is not None for operation in item_operations)
        assert [operation.status for operation in item_operations if operation is not None] == [
            "succeeded",
            "failed",
            "succeeded",
        ]
        phase_operation_ids = {
            operation.parent_operation_id for operation in item_operations if operation is not None
        }
        assert len(phase_operation_ids) == 1
        phase_operation_id = phase_operation_ids.pop()
        assert phase_operation_id is not None
        phase_operation = await store.load_operation(phase_operation_id)
        root_operation = await store.load_operation(failed.job.operation_id)
        assert phase_operation is not None and phase_operation.status == "failed"
        assert root_operation is not None and root_operation.status == "failed"
        failed_operations = [
            root_operation,
            phase_operation,
            cast(PrototypeOperation, item_operations[1]),
        ]
        for operation in failed_operations:
            assert operation.failure_evidence_hash is not None
            failure_references = await store.list_object_references(
                project.id,
                "replay_manifest",
                operation.id,
            )
            assert len(failure_references) == 1
            assert failure_references[0].role == "operation-failure-evidence"
            failure_descriptor = await store.load_object(
                project.id,
                operation.failure_evidence_hash,
            )
            assert failure_descriptor is not None
            failure_evidence = json.loads(object_store.read_canonical_bytes(failure_descriptor))
            assert failure_evidence["operationId"] == operation.id
            assert failure_evidence["errorCode"] == "generation_agent_failed"
        root_steps = await store.list_operation_steps(failed.job.operation_id)
        assert "assemble_candidate" not in {step.step_kind for step in root_steps}
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_startup_cleanup_receives_global_snapshot_owners_for_shared_repository(
    tmp_path: Path,
) -> None:
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "managed")
    projects = [
        Project(
            id="project-a",
            name="admin-a",
            repo_path=str(tmp_path / "monorepo" / "examples" / "a"),
            default_branch="main",
        ),
        Project(
            id="project-b",
            name="admin-b",
            repo_path=str(tmp_path / "monorepo" / "examples" / "b"),
            default_branch="main",
        ),
    ]
    cleaner = _ResourceCleaner()
    service = StructuredPrototypeGenerationService(
        store=store,
        project_store=_MultiProjectStore(projects),
        object_store=object_store,
        runtime=_ControlledGenerationRuntime(object_store),
        runtime_worker=PrototypeRuntimeWorker(),
        renderer=PrototypeRendererWorker(),
        artifact_store=PrototypeRenderArtifactStore(tmp_path / "managed"),
        source_control=_SourceControl(),
        resource_cleaner=cleaner,
        clock=lambda: NOW,
    )
    try:
        jobs = []
        for project, request_id in zip(
            projects,
            (
                "11111111-aaaa-5111-8111-111111111111",
                "22222222-bbbb-5222-8222-222222222222",
            ),
            strict=True,
        ):
            created = await service.create_requirements_job(
                project_id=project.id,
                client_request_id=request_id,
                brief="Generate an editable project prototype",
            )
            jobs.append((await service.wait_for_job(created.job.id)).job.id)

        await service.recover_interrupted_jobs()

        assert [project_id for project_id, _ in cleaner.calls] == ["project-a", "project-b"]
        assert all(owner_ids == frozenset(jobs) for _, owner_ids in cleaner.calls)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_generation_persists_execution_process_before_claude_completion(
    tmp_path: Path,
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
    try:
        created = await service.create_requirements_job(
            project_id=project.id,
            client_request_id="7bece5a5-d764-5986-987b-b98c1a7f74f2",
            brief="基于项目源码生成可编辑原型",
        )
        await asyncio.wait_for(runtime.activity_started.wait(), timeout=2)

        active = await service.get_job(created.job.id)
        assert active.job.status == "planning"
        assert active.items[0].status == "generating"
        process_id = f"process-{active.items[0].id}"
        assert active.items[0].execution_process_id == process_id
        events = await store.list_operation_events(active.items[0].operation_id)
        assert events[0].event_kind == "operation_queued"
        assert events[-1].event_kind == "step_started"
        assert all(event.event_kind != "execution_started" for event in events)
        active_steps = await store.list_operation_steps(active.items[0].operation_id)
        assert [step.step_kind for step in active_steps] == [
            "job_run_item_created",
            "context_freeze",
            "governance_decision",
            "claude_task_created",
            "claude_process_started",
            "runtime_wire_input",
        ]
        process_step = next(
            step for step in active_steps if step.step_kind == "claude_process_started"
        )
        process_events = [event for event in events if event.step_id == process_step.id]
        assert process_events[-1].evidence_hash == process_step.output_manifest_hash

        same = await store.bind_generation_item_execution_process(
            item_id=active.items[0].id,
            task_id=active.items[0].task_id or "",
            execution_process_id=process_id,
            bound_at=NOW,
        )
        assert same.execution_process_id == process_id
        assert len(await store.list_operation_events(active.items[0].operation_id)) == len(events)
        with pytest.raises(StructuredPrototypeStoreError) as error:
            await store.bind_generation_item_execution_process(
                item_id=active.items[0].id,
                task_id=active.items[0].task_id or "",
                execution_process_id="different-process",
                bound_at=NOW,
            )
        assert error.value.code == "generation_execution_identity_mismatch"

        runtime.release.set()
        planned = await service.wait_for_job(created.job.id)
        assert planned.job.status == "awaiting_confirmation"
    finally:
        runtime.release.set()
        await service.wait_for_job(created.job.id)
        await store.close()


@pytest.mark.asyncio
async def test_generation_callback_registration_failure_rolls_back_and_fails_closed(
    tmp_path: Path,
) -> None:
    store = _EvidenceRegistrationFailingStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "managed")
    runtime = _ControlledGenerationRuntime(object_store)
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
    try:
        created = await service.create_requirements_job(
            project_id=project.id,
            client_request_id="fe94b427-dc6a-577f-907e-a79854cd4ea2",
            brief="基于项目源码生成可编辑原型",
        )
        failed = await service.wait_for_job(created.job.id)

        assert failed.job.status == "failed"
        assert failed.job.error_code == "generation_evidence_registration_failed"
        assert failed.items[0].status == "failed"
        assert failed.items[0].execution_process_id is None
        assert runtime.artifact_hashes == []
        assert store.failed_evidence_hash is not None
        assert await store.load_object(project.id, store.failed_evidence_hash) is None
        steps = await store.list_operation_steps(failed.items[0].operation_id)
        assert [step.step_kind for step in steps] == [
            "job_run_item_created",
            "context_freeze",
            "governance_decision",
            "claude_task_created",
        ]
        assert steps[-1].status == "failed"
        assert not any(step.step_kind == "claude_process_started" for step in steps)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_generation_replay_registration_failure_rolls_back_item_success(
    tmp_path: Path,
) -> None:
    store = _ReplayRegistrationFailingStore(tmp_path / "console.db")
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
        runtime_worker=PrototypeRuntimeWorker(),
        renderer=PrototypeRendererWorker(),
        artifact_store=PrototypeRenderArtifactStore(tmp_path / "managed"),
        source_control=_SourceControl(),
        resource_cleaner=_ResourceCleaner(),
        clock=lambda: NOW,
    )
    try:
        created = await service.create_requirements_job(
            project_id=project.id,
            client_request_id="8cd64ef7-6347-5205-ad5e-3df08c3db80c",
            brief="基于项目源码生成可编辑原型",
        )
        failed = await service.wait_for_job(created.job.id)

        assert failed.job.status == "failed"
        assert failed.job.error_code == "generation_replay_registration_failed"
        assert failed.items[0].status == "failed"
        item_operation = await store.load_operation(failed.items[0].operation_id)
        assert item_operation is not None
        assert item_operation.status == "failed"
        assert item_operation.result_manifest_hash is None
        assert store.failed_replay_hash is not None
        assert await store.load_object(project.id, store.failed_replay_hash) is None
        failure_references = await store.list_object_references(
            project.id,
            "replay_manifest",
            item_operation.id,
        )
        assert len(failure_references) == 1
        assert failure_references[0].role == "operation-failure-evidence"
        assert failure_references[0].content_hash == item_operation.failure_evidence_hash
        failure_descriptor = await store.load_object(
            project.id,
            failure_references[0].content_hash,
        )
        assert failure_descriptor is not None
        failure_evidence = json.loads(object_store.read_canonical_bytes(failure_descriptor))
        assert failure_evidence["evidenceKind"] == "generation_operation_failure"
        assert failure_evidence["operationId"] == item_operation.id
        assert failure_evidence["errorCode"] == "generation_replay_registration_failed"
        steps = await store.list_operation_steps(item_operation.id)
        assert steps[-1].step_kind == "semantic_validation"
        assert steps[-1].status == "failed"
    finally:
        await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("target_status", ["awaiting_confirmation", "ready"])
async def test_delete_project_prototype_removes_quiescent_generation_job(
    tmp_path: Path,
    target_status: str,
) -> None:
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "managed")
    project = Project(
        id="project-1",
        name="admin-demo",
        repo_path=str(tmp_path),
        default_branch="main",
    )
    generation_service = StructuredPrototypeGenerationService(
        store=store,
        project_store=_ProjectStore(project),
        object_store=object_store,
        runtime=_ControlledGenerationRuntime(object_store),
        runtime_worker=PrototypeRuntimeWorker(),
        renderer=PrototypeRendererWorker(),
        artifact_store=PrototypeRenderArtifactStore(tmp_path / "managed"),
        source_control=_SourceControl(),
        resource_cleaner=_ResourceCleaner(),
        clock=lambda: NOW,
    )
    prototype_service = StructuredPrototypeService(
        store=store,
        object_store=object_store,
        clock=lambda: NOW,
    )
    try:
        created = await generation_service.create_requirements_job(
            project_id=project.id,
            client_request_id="38e52b67-ef7e-53ad-8f7f-325199c3675e",
            brief="基于项目源码生成可编辑后台原型",
        )
        snapshot = await generation_service.wait_for_job(created.job.id)
        if target_status == "ready":
            assert snapshot.job.blueprint_hash is not None
            await generation_service.confirm_blueprint(
                job_id=snapshot.job.id,
                client_request_id="b96b93b1-f928-5c6b-8eaa-e77eb3687631",
                expected_blueprint_version=snapshot.job.blueprint_version,
                expected_blueprint_hash=snapshot.job.blueprint_hash,
            )
            snapshot = await generation_service.wait_for_job(snapshot.job.id)
        assert snapshot.job.status == target_status

        deleted = await prototype_service.delete_project_prototype(
            project_id=project.id,
            client_request_id="c4555b7c-f91d-5358-88b8-dbe1b7bbeb94",
        )

        assert deleted.deleted is True
        assert await generation_service.get_latest_project_job(project.id) is None
        assert await store.load_operation(snapshot.job.operation_id) is None
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
        name="admin-demo",
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
        source_control=_SourceControl(),
        resource_cleaner=_ResourceCleaner(),
        clock=lambda: NOW,
    )
    try:
        created = await service.create_requirements_job(
            project_id=project.id,
            client_request_id="bab163ea-e8f0-5f01-9139-58bbdbe62743",
            brief="基于项目源码生成可编辑后台原型",
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


@pytest.mark.asyncio
async def test_source_capture_failure_leaves_a_durable_failed_root_operation(
    tmp_path: Path,
) -> None:
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "managed")
    project = Project(
        id="project-1",
        name="admin-demo",
        repo_path=str(tmp_path),
        default_branch="main",
    )
    request_id = "8b33b7e0-281e-5f65-ac96-90bfc7ff326c"
    service = StructuredPrototypeGenerationService(
        store=store,
        project_store=_ProjectStore(project),
        object_store=object_store,
        runtime=_ControlledGenerationRuntime(object_store),
        runtime_worker=PrototypeRuntimeWorker(),
        renderer=PrototypeRendererWorker(),
        artifact_store=PrototypeRenderArtifactStore(tmp_path / "managed"),
        source_control=_FailingSourceControl(),
        resource_cleaner=_ResourceCleaner(),
        clock=lambda: NOW,
    )
    try:
        with pytest.raises(StructuredPrototypeGenerationServiceError) as failure:
            await service.create_requirements_job(
                project_id=project.id,
                client_request_id=request_id,
                brief="基于项目源码生成可编辑后台原型",
            )

        assert failure.value.code == "generation_source_snapshot_failed"
        assert await service.get_latest_project_job(project.id) is None
        operation = await store.load_operation_by_request(
            project.id,
            "generation_job",
            request_id,
        )
        assert operation is not None
        assert operation.status == "failed"
        assert operation.error_code == "generation_source_snapshot_failed"
        assert operation.failure_evidence_hash is not None
        references = await store.list_object_references(
            project.id,
            "replay_manifest",
            operation.id,
        )
        assert len(references) == 1
        assert references[0].role == "operation-failure-evidence"
        descriptor = await store.load_object(project.id, operation.failure_evidence_hash)
        assert descriptor is not None
        evidence = json.loads(object_store.read_canonical_bytes(descriptor))
        assert evidence["operationId"] == operation.id
        assert evidence["step"]["stepKind"] == "source_capture"
        assert evidence["errorCode"] == "generation_source_snapshot_failed"
        steps = await store.list_operation_steps(operation.id)
        assert [step.step_kind for step in steps] == ["source_capture"]
        assert steps[0].status == "failed"
        events = await store.list_operation_events(operation.id)
        assert [event.event_kind for event in events] == [
            "operation_queued",
            "step_started",
            "step_failed",
        ]
        assert [event.event_no for event in events] == [0, 1, 2]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_restart_recovers_pre_job_source_capture_and_exact_retry_is_terminal(
    tmp_path: Path,
) -> None:
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "managed")
    project = Project(
        id="project-1",
        name="admin-demo",
        repo_path=str(tmp_path),
        default_branch="main",
    )
    request_id = "952d3709-fac6-560a-a791-3d83851a4138"
    source_control = _PausingSourceControl()
    service = StructuredPrototypeGenerationService(
        store=store,
        project_store=_ProjectStore(project),
        object_store=object_store,
        runtime=_ControlledGenerationRuntime(object_store),
        runtime_worker=PrototypeRuntimeWorker(),
        renderer=PrototypeRendererWorker(),
        artifact_store=PrototypeRenderArtifactStore(tmp_path / "managed"),
        source_control=source_control,
        resource_cleaner=_ResourceCleaner(),
        clock=lambda: NOW,
    )
    creation = asyncio.create_task(
        service.create_requirements_job(
            project_id=project.id,
            client_request_id=request_id,
            brief="Generate an editable project prototype",
        )
    )
    try:
        await source_control.started.wait()
        operation = await store.load_operation_by_request(
            project.id,
            "generation_job",
            request_id,
        )
        assert operation is not None and operation.status == "running"
        steps_before = await store.list_operation_steps(operation.id)
        assert len(steps_before) == 1 and steps_before[0].status == "running"
        creation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await creation
        assert await service.get_latest_project_job(project.id) is None

        assert await service.recover_interrupted_jobs() == 1

        recovered = await store.load_operation(operation.id)
        assert recovered is not None and recovered.status == "interrupted"
        assert recovered.failure_evidence_hash is not None
        recovered_steps = await store.list_operation_steps(operation.id)
        assert len(recovered_steps) == 1
        assert recovered_steps[0].status == "interrupted"
        events = await store.list_operation_events(operation.id)
        assert [event.event_no for event in events] == [0, 1, 2]
        assert events[-1].step_id == recovered_steps[0].id
        assert events[-1].evidence_hash == recovered.failure_evidence_hash
        references = await store.list_object_references(
            project.id,
            "replay_manifest",
            operation.id,
        )
        assert len(references) == 1
        assert references[0].role == "operation-interruption-evidence"
        descriptor = await store.load_object(project.id, recovered.failure_evidence_hash)
        assert descriptor is not None
        evidence = json.loads(object_store.read_canonical_bytes(descriptor))
        assert evidence["evidenceKind"] == "generation_restart_interruption"
        assert evidence["operationId"] == operation.id
        assert evidence["activeStep"]["id"] == recovered_steps[0].id
        assert evidence["errorCode"] == "restart_interrupted"

        with pytest.raises(StructuredPrototypeGenerationServiceError) as retry:
            await service.create_requirements_job(
                project_id=project.id,
                client_request_id=request_id,
                brief="Generate an editable project prototype",
            )
        assert retry.value.code == "restart_interrupted"
        assert retry.value.code != "generation_creation_in_progress"
        assert await service.recover_interrupted_jobs() == 0
    finally:
        if not creation.done():
            creation.cancel()
            with pytest.raises(asyncio.CancelledError):
                await creation
        await store.close()


@pytest.mark.asyncio
async def test_restart_interrupts_persisted_confirm_freeze_without_interrupting_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "console.db"
    store = AsyncStructuredPrototypeStore(db_path)
    reopened_store: AsyncStructuredPrototypeStore | None = None
    object_store = PrototypeObjectStore(tmp_path / "managed")
    project = Project(
        id="project-1",
        name="admin-demo",
        repo_path=str(tmp_path),
        default_branch="main",
    )
    runtime = _ControlledGenerationRuntime(object_store)
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
    confirm_request_id = "98ea72af-33d0-522f-925c-25f871a30dac"
    retry_request_id = "f39e66d6-15f7-5f03-a120-dc0028a0bd22"
    pause_next_write = False
    write_started = threading.Event()
    write_release = threading.Event()
    write_finished = threading.Event()
    original_write_json = object_store.write_json

    def write_json_with_confirm_crash(
        project_id: str,
        value: object,
    ) -> PrototypeObjectDescriptor:
        nonlocal pause_next_write
        if not pause_next_write:
            return original_write_json(project_id, value)
        pause_next_write = False
        write_started.set()
        try:
            if not write_release.wait(timeout=5):
                raise AssertionError("confirm context write was not released")
            return original_write_json(project_id, value)
        finally:
            write_finished.set()

    monkeypatch.setattr(object_store, "write_json", write_json_with_confirm_crash)
    confirm_task: asyncio.Task[object] | None = None
    try:
        created = await service.create_requirements_job(
            project_id=project.id,
            client_request_id="f4df3422-5c73-54ea-a938-a04465175663",
            brief="Generate an editable project prototype",
        )
        planned = await service.wait_for_job(created.job.id)
        assert planned.job.status == "awaiting_confirmation"
        assert planned.job.blueprint_hash is not None
        root_before = await store.load_operation(planned.job.operation_id)
        assert root_before is not None and root_before.status == "running"

        pause_next_write = True
        confirm_task = asyncio.create_task(
            service.confirm_blueprint(
                job_id=planned.job.id,
                client_request_id=confirm_request_id,
                expected_blueprint_version=planned.job.blueprint_version,
                expected_blueprint_hash=planned.job.blueprint_hash,
            )
        )
        assert await asyncio.to_thread(write_started.wait, 2)
        confirm_before = await store.load_operation_by_request(
            project.id,
            "generation_job",
            confirm_request_id,
        )
        assert confirm_before is not None and confirm_before.status == "running"
        confirm_steps_before = await store.list_operation_steps(confirm_before.id)
        assert len(confirm_steps_before) == 1
        assert confirm_steps_before[0].step_kind == "freeze_context"
        assert confirm_steps_before[0].status == "running"
        scope_before = await store.load_generation_restart_recovery_scope()
        assert [target.operation.id for target in scope_before.operations] == [confirm_before.id]
        assert scope_before.affected_root_count == 1
        assert scope_before.active_job_count == 0
        assert scope_before.active_run_count == 0
        assert scope_before.active_item_count == 0

        confirm_task.cancel()
        write_release.set()
        with pytest.raises(asyncio.CancelledError):
            await confirm_task
        assert await asyncio.to_thread(write_finished.wait, 2)
        await store.close()

        reopened_store = AsyncStructuredPrototypeStore(db_path)
        recovery_service = StructuredPrototypeGenerationService(
            store=reopened_store,
            project_store=_ProjectStore(project),
            object_store=object_store,
            runtime=_ControlledGenerationRuntime(object_store),
            runtime_worker=PrototypeRuntimeWorker(),
            renderer=PrototypeRendererWorker(),
            artifact_store=PrototypeRenderArtifactStore(tmp_path / "managed"),
            source_control=_SourceControl(),
            resource_cleaner=_ResourceCleaner(),
            clock=lambda: NOW,
        )
        reopened_scope = await reopened_store.load_generation_restart_recovery_scope()
        assert reopened_scope.fingerprint == scope_before.fingerprint
        assert await recovery_service.recover_interrupted_jobs() == 1

        recovered_snapshot = await recovery_service.get_job(planned.job.id)
        assert recovered_snapshot == planned
        root_after = await reopened_store.load_operation(planned.job.operation_id)
        assert root_after == root_before
        confirm_after = await reopened_store.load_operation(confirm_before.id)
        assert confirm_after is not None and confirm_after.status == "interrupted"
        assert confirm_after.client_request_id == confirm_before.client_request_id
        assert confirm_after.correlation_id == confirm_before.correlation_id
        assert confirm_after.parent_operation_id == confirm_before.parent_operation_id
        assert confirm_after.request_manifest_hash == confirm_before.request_manifest_hash
        assert confirm_after.failure_evidence_hash is not None
        confirm_steps_after = await reopened_store.list_operation_steps(confirm_after.id)
        assert len(confirm_steps_after) == 1
        assert confirm_steps_after[0].id == confirm_steps_before[0].id
        assert confirm_steps_after[0].step_kind == "freeze_context"
        assert confirm_steps_after[0].status == "interrupted"
        assert confirm_steps_after[0].completion_evidence_ref == confirm_after.failure_evidence_hash
        confirm_events = await reopened_store.list_operation_events(confirm_after.id)
        assert [event.status for event in confirm_events] == [
            "queued",
            "running",
            "interrupted",
        ]
        assert confirm_events[-1].evidence_hash == confirm_after.failure_evidence_hash
        references = await reopened_store.list_object_references(
            project.id,
            "replay_manifest",
            confirm_after.id,
        )
        assert len(references) == 1
        assert references[0].role == "operation-interruption-evidence"
        descriptor = await reopened_store.load_object(
            project.id,
            confirm_after.failure_evidence_hash,
        )
        assert descriptor is not None
        evidence = json.loads(object_store.read_canonical_bytes(descriptor))
        assert evidence["operationId"] == confirm_after.id
        assert evidence["priorStatus"] == "running"
        assert evidence["activeStep"]["id"] == confirm_steps_before[0].id
        assert evidence["activeStep"]["stepKind"] == "freeze_context"
        assert evidence["errorCode"] == "restart_interrupted"

        with pytest.raises(StructuredPrototypeGenerationServiceError) as exact_retry:
            await recovery_service.confirm_blueprint(
                job_id=planned.job.id,
                client_request_id=confirm_request_id,
                expected_blueprint_version=planned.job.blueprint_version,
                expected_blueprint_hash=planned.job.blueprint_hash,
            )
        assert exact_retry.value.code == "generation_confirm_conflict"
        still_planned = await recovery_service.get_job(planned.job.id)
        assert still_planned == planned

        retry = await recovery_service.confirm_blueprint(
            job_id=planned.job.id,
            client_request_id=retry_request_id,
            expected_blueprint_version=planned.job.blueprint_version,
            expected_blueprint_hash=planned.job.blueprint_hash,
        )
        assert retry.operation_id != confirm_after.id
        ready = await recovery_service.wait_for_job(planned.job.id)
        assert ready.job.status == "ready", (ready.job.error_code, ready.job.error_message)
    finally:
        write_release.set()
        if confirm_task is not None and not confirm_task.done():
            confirm_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await confirm_task
        if reopened_store is not None:
            await reopened_store.close()
        await store.close()
