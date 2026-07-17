from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID, uuid5

from pydantic import ValidationError

from app.adapters.prototype_object_store import (
    CANONICALIZER_VERSION,
    PrototypeObjectStoreError,
    canonical_json_bytes,
)
from app.adapters.prototype_render_artifact_store import PrototypeRenderArtifactStoreError
from app.adapters.prototype_renderer_worker import PrototypeRendererWorkerError
from app.adapters.prototype_runtime_worker import PrototypeRuntimeWorkerError
from app.adapters.structured_prototype_store import StructuredPrototypeStoreError
from app.application import timeouts
from app.application.git_service import GitError
from app.application.prototype_ui_engineer_runner import (
    PrototypeUiEngineerActivity,
    PrototypeUiEngineerActivityCallback,
)
from app.application.structured_prototype_contracts import (
    COMMAND_CONTRACT_VERSION,
    COMMAND_HISTORY_CHECKPOINT_SCHEMA_VERSION,
    DOCUMENT_SCHEMA_VERSION,
    CommandHistoryCheckpointV1,
    PrototypeDocumentV1,
    StructuredPrototypeContractError,
    canonical_command_history_checkpoint_json,
    command_history_checkpoint_payload,
    command_history_checkpoint_to_domain,
    document_hash,
    document_payload,
    initial_journal_prefix_hash,
    parse_command_history_checkpoint_json,
    parse_prototype_document_json,
)
from app.application.structured_prototype_generation_assembler import (
    GENERATION_ASSEMBLER_VERSION,
    GenerationScenarioValidationCase,
    StructuredPrototypeGenerationAssemblyError,
    assemble_generation_candidate,
    generation_document_id,
    generation_validation_cases,
    validate_generation_blueprint,
    validate_generation_foundation,
)
from app.application.structured_prototype_generation_contracts import (
    GENERATION_CONTRACT_VERSION,
    GeneratedPageV1,
    GenerationArtifactEnvelopeV1,
    GenerationBlueprintEnvelopeV1,
    GenerationBlueprintV1,
    GenerationFoundationEnvelopeV1,
    GenerationFoundationV1,
    GenerationPageEnvelopeV1,
    GenerationTaskKind,
    generation_artifact_payload,
    parse_generation_artifact,
)
from app.application.structured_prototype_generation_runtime import (
    GENERATION_PROMPT_VERSION,
    GenerationMcpSubmissionEvidence,
    GenerationProcessStartedEvidence,
    GenerationProcessTerminalEvidence,
    GenerationTaskCreatedEvidence,
    GenerationWireInputEvidence,
    StructuredPrototypeGenerationEvidenceCallback,
    StructuredPrototypeGenerationExecutionEvidence,
    StructuredPrototypeGenerationRuntimeError,
    StructuredPrototypeGenerationRuntimeGovernance,
    StructuredPrototypeGenerationTaskRequest,
    StructuredPrototypeGenerationTaskResult,
)
from app.application.task_statuses import is_task_success_status
from app.application.worktree_manager import WorktreeError
from app.domain.models import Project
from app.domain.structured_prototype import (
    REPLAY_MANIFEST_SCHEMA_VERSION,
    PrototypeCheckpointRecord,
    PrototypeCommandHistoryCheckpoint,
    PrototypeDocumentRecord,
    PrototypeDraftRecord,
    PrototypeObjectDescriptor,
    PrototypeObjectOwnerKind,
    PrototypeObjectPayloadType,
    PrototypeObjectReference,
    PrototypeOperation,
    PrototypeOperationCreateResult,
    PrototypeOperationEvent,
    PrototypeOperationKind,
    PrototypeOperationStep,
    PrototypeRenderBundleDescriptor,
    PrototypeRendererWorkerIdentity,
    PrototypeRendererWorkerResult,
    PrototypeReplayManifestError,
    PrototypeReplayManifestV1,
    PrototypeReplayManifestVersionsV1,
    PrototypeRuntimeWorkerIdentity,
    PrototypeRuntimeWorkerReplayResult,
    PrototypeRuntimeWorkerStateResult,
)
from app.domain.structured_prototype_generation import (
    PrototypeDocumentGenerationAcceptResult,
    PrototypeDocumentGenerationConfirmResult,
    PrototypeDocumentGenerationCreateResult,
    PrototypeDocumentGenerationItemKind,
    PrototypeDocumentGenerationItemRecord,
    PrototypeDocumentGenerationJobRecord,
    PrototypeDocumentGenerationRunCreateResult,
    PrototypeDocumentGenerationRunRecord,
    PrototypeDocumentGenerationSnapshot,
    PrototypeGenerationCommittedHeadCapture,
    PrototypeGenerationRestartRecoveryScope,
    PrototypeGenerationSourceSnapshot,
)
from app.json_safety import parse_json_object

logger = logging.getLogger(__name__)

GENERATION_SERVICE_NAMESPACE = UUID("cd941172-9105-5806-b528-938dd18c5662")
GENERATION_CONFIG_VERSION = "structured-prototype-generation-service/v1"
GENERATION_EVIDENCE_MANIFEST_VERSION = 1
GENERATION_GOVERNANCE_POLICY_VERSION = "structured-prototype-generation-governance/v1"
GENERATION_RUNTIME_STATE_SCHEMA_VERSION = 1
GENERATION_RUNTIME_EVENT_CONTRACT_VERSION = 1
_PREVIEW_BUNDLE_FILES = ("document.json", "index.html", "runtime.js", "styles.css")


def _generation_content_policy() -> dict[str, object]:
    return {
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


class StructuredPrototypeGenerationPersistence(Protocol):
    async def create_operation(
        self,
        operation: PrototypeOperation,
        initial_event: PrototypeOperationEvent,
    ) -> PrototypeOperationCreateResult: ...

    async def record_operation_transition(
        self,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        event: PrototypeOperationEvent,
    ) -> None: ...

    async def register_generation_failure_evidence_and_transition(
        self,
        *,
        descriptor: PrototypeObjectDescriptor,
        reference: PrototypeObjectReference,
        failed_operation: PrototypeOperation,
        failed_step: PrototypeOperationStep,
        failed_event: PrototypeOperationEvent,
    ) -> None: ...

    async def create_generation_job(
        self,
        *,
        job_operation: PrototypeOperation,
        job_event: PrototypeOperationEvent | None,
        item_operation: PrototypeOperation,
        item_event: PrototypeOperationEvent,
        job: PrototypeDocumentGenerationJobRecord,
        run: PrototypeDocumentGenerationRunRecord,
        item: PrototypeDocumentGenerationItemRecord,
        descriptors_and_references: tuple[
            tuple[PrototypeObjectDescriptor, PrototypeObjectReference], ...
        ],
        operation_transitions: tuple[
            tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent], ...
        ] = (),
    ) -> PrototypeDocumentGenerationCreateResult: ...

    async def create_generation_run(
        self,
        *,
        operation: PrototypeOperation,
        initial_event: PrototypeOperationEvent | None,
        job: PrototypeDocumentGenerationJobRecord,
        run: PrototypeDocumentGenerationRunRecord,
        item_operations: tuple[
            tuple[
                PrototypeDocumentGenerationItemRecord,
                PrototypeOperation,
                PrototypeOperationEvent,
            ],
            ...,
        ],
        expected_job_statuses: tuple[str, ...],
        expected_blueprint_version: int,
        expected_blueprint_hash: str,
        descriptors_and_references: tuple[
            tuple[PrototypeObjectDescriptor, PrototypeObjectReference], ...
        ] = (),
        operation_transitions: tuple[
            tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent], ...
        ] = (),
    ) -> PrototypeDocumentGenerationRunCreateResult: ...

    async def load_generation_job(
        self,
        job_id: str,
    ) -> PrototypeDocumentGenerationSnapshot | None: ...

    async def load_latest_project_generation_job(
        self,
        project_id: str,
    ) -> PrototypeDocumentGenerationSnapshot | None: ...

    async def load_generation_confirm_result(
        self,
        *,
        job_id: str,
        client_request_id: str,
        request_hash: str,
        expected_operation_id: str,
        expected_run_id: str,
        expected_blueprint_hash: str,
    ) -> PrototypeDocumentGenerationConfirmResult | None: ...

    async def bind_generation_item_execution_process(
        self,
        *,
        item_id: str,
        task_id: str,
        execution_process_id: str,
        bound_at: datetime,
    ) -> PrototypeDocumentGenerationItemRecord: ...

    async def transition_generation_records(
        self,
        *,
        job: PrototypeDocumentGenerationJobRecord,
        run: PrototypeDocumentGenerationRunRecord,
        items: tuple[PrototypeDocumentGenerationItemRecord, ...],
        expected_job_statuses: tuple[str, ...],
        expected_run_statuses: tuple[str, ...],
        expected_item_statuses: tuple[str, ...],
        descriptors_and_references: tuple[
            tuple[PrototypeObjectDescriptor, PrototypeObjectReference], ...
        ] = (),
        operation_transitions: tuple[
            tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent], ...
        ] = (),
    ) -> PrototypeDocumentGenerationSnapshot: ...

    async def load_operation(self, operation_id: str) -> PrototypeOperation | None: ...

    async def load_generation_accept_result(
        self,
        *,
        job_id: str,
        client_request_id: str,
        request_hash: str,
    ) -> PrototypeDocumentGenerationAcceptResult | None: ...

    async def list_operation_steps(self, operation_id: str) -> list[PrototypeOperationStep]: ...

    async def list_operation_events(self, operation_id: str) -> list[PrototypeOperationEvent]: ...

    async def load_object(
        self,
        project_id: str,
        content_hash: str,
    ) -> PrototypeObjectDescriptor | None: ...

    async def accept_generation_candidate(
        self,
        *,
        descriptor: PrototypeObjectDescriptor,
        checkpoint_reference: PrototypeObjectReference,
        history_descriptor: PrototypeObjectDescriptor,
        history_reference: PrototypeObjectReference,
        history_checkpoint: PrototypeCommandHistoryCheckpoint,
        accept_replay_descriptor: PrototypeObjectDescriptor,
        accept_replay_reference: PrototypeObjectReference,
        job: PrototypeDocumentGenerationJobRecord,
        document: PrototypeDocumentRecord,
        draft: PrototypeDraftRecord,
        checkpoint: PrototypeCheckpointRecord,
        expected_candidate_object_hash: str,
        expected_preview_output_hash: str,
        expected_source_fingerprint: str,
        completed_transition: tuple[
            PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent
        ],
    ) -> PrototypeDocumentGenerationAcceptResult: ...

    async def load_generation_restart_recovery_scope(
        self,
    ) -> PrototypeGenerationRestartRecoveryScope: ...

    async def interrupt_active_generation_jobs(
        self,
        *,
        expected_scope_fingerprint: str,
        descriptors_and_references: tuple[
            tuple[PrototypeObjectDescriptor, PrototypeObjectReference], ...
        ],
        interrupted_at: datetime,
    ) -> int: ...

    async def list_generation_job_ids(self) -> tuple[str, ...]: ...


class GenerationProjectStore(Protocol):
    async def load_project(self, project_id: str) -> Project | None: ...

    async def list_projects(self) -> list[Project]: ...


class GenerationSourceControl(Protocol):
    async def capture_committed_head_snapshot(
        self,
        repo_path: str,
        job_id: str,
    ) -> PrototypeGenerationCommittedHeadCapture: ...


class GenerationResourceCleaner(Protocol):
    async def cleanup_stale_prototype_generation_resources(
        self,
        project: Project,
        *,
        owned_snapshot_job_ids: frozenset[str],
    ) -> None: ...


class GenerationObjectStorage(Protocol):
    def write_json(self, project_id: str, value: object) -> PrototypeObjectDescriptor: ...

    def read_canonical_bytes(self, descriptor: PrototypeObjectDescriptor) -> bytes: ...


class GenerationRuntimeExecution(Protocol):
    async def evaluate_runtime_governance(
        self,
        request: StructuredPrototypeGenerationTaskRequest,
    ) -> StructuredPrototypeGenerationRuntimeGovernance: ...

    async def execute(
        self,
        request: StructuredPrototypeGenerationTaskRequest,
        *,
        activity_callback: PrototypeUiEngineerActivityCallback | None = None,
        evidence_callback: StructuredPrototypeGenerationEvidenceCallback | None = None,
    ) -> StructuredPrototypeGenerationTaskResult: ...


class GenerationRuntimeWorker(Protocol):
    @property
    def identity(self) -> PrototypeRuntimeWorkerIdentity: ...

    async def initialize_state(
        self,
        *,
        request_id: str,
        definition: dict[str, object],
        scenario_id: str,
        session_id: str,
    ) -> PrototypeRuntimeWorkerStateResult: ...

    async def replay_event_batches(
        self,
        *,
        request_id: str,
        definition: dict[str, object],
        state_json: str,
        batches: list[dict[str, object]],
    ) -> PrototypeRuntimeWorkerReplayResult: ...


class GenerationRenderer(Protocol):
    identity: PrototypeRendererWorkerIdentity

    async def render(
        self,
        *,
        request_id: str,
        artifact_id: str,
        input_manifest: dict[str, object],
        document: dict[str, object],
    ) -> PrototypeRendererWorkerResult: ...


class GenerationArtifactStorage(Protocol):
    def write_bundle(
        self,
        *,
        project_id: str,
        document_id: str,
        artifact_id: str,
        result: PrototypeRendererWorkerResult,
    ) -> PrototypeRenderBundleDescriptor: ...

    def read_file(
        self,
        descriptor: PrototypeRenderBundleDescriptor,
        relative_path: str,
    ) -> bytes: ...


class StructuredPrototypeGenerationServiceError(RuntimeError):
    def __init__(self, code: str, message: str, *, job_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.job_id = job_id


@dataclass(frozen=True, slots=True)
class _GenerationRuntimeValidationResult:
    primary: PrototypeRuntimeWorkerReplayResult
    scenario_evidence: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class _GenerationReplayManifestArtifact:
    manifest: PrototypeReplayManifestV1
    descriptor: PrototypeObjectDescriptor
    reference: PrototypeObjectReference


@dataclass(frozen=True, slots=True)
class _GenerationFailureArtifact:
    descriptor: PrototypeObjectDescriptor
    reference: PrototypeObjectReference
    transition: tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _stable_id(*parts: str) -> str:
    return str(uuid5(GENERATION_SERVICE_NAMESPACE, "\x1f".join(parts)))


def _manifest_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _with_generation_run_counts(
    run: PrototypeDocumentGenerationRunRecord,
    items: tuple[PrototypeDocumentGenerationItemRecord, ...],
    now: datetime,
) -> PrototypeDocumentGenerationRunRecord:
    succeeded = sum(item.status == "done" for item in items)
    failed = sum(item.status in {"failed", "interrupted"} for item in items)
    running = sum(item.status in {"generating", "validating"} for item in items)
    pending = sum(item.status == "pending" for item in items)
    return replace(
        run,
        processed=succeeded + failed,
        succeeded=succeeded,
        failed=failed,
        running=running,
        pending=pending,
        updated_at=now,
    )


def _require_uuid(value: str, code: str) -> None:
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise StructuredPrototypeGenerationServiceError(code, "request ID must be a UUID") from exc
    if str(parsed) != value:
        raise StructuredPrototypeGenerationServiceError(
            code, "request ID must use canonical lowercase UUID form"
        )


class StructuredPrototypeGenerationService:
    def __init__(
        self,
        *,
        store: StructuredPrototypeGenerationPersistence,
        project_store: GenerationProjectStore,
        object_store: GenerationObjectStorage,
        runtime: GenerationRuntimeExecution,
        runtime_worker: GenerationRuntimeWorker,
        renderer: GenerationRenderer,
        artifact_store: GenerationArtifactStorage,
        source_control: GenerationSourceControl,
        resource_cleaner: GenerationResourceCleaner,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._store = store
        self._project_store = project_store
        self._object_store = object_store
        self._runtime = runtime
        self._runtime_worker = runtime_worker
        self._renderer = renderer
        self._artifact_store = artifact_store
        self._source_control = source_control
        self._resource_cleaner = resource_cleaner
        self._clock = clock
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._project_creation_locks: dict[str, asyncio.Lock] = {}
        self._page_generation_semaphore = asyncio.Semaphore(
            timeouts.structured_prototype_page_generation_concurrency()
        )

    async def create_requirements_job(
        self,
        *,
        project_id: str,
        client_request_id: str,
        brief: str,
    ) -> PrototypeDocumentGenerationSnapshot:
        _require_uuid(client_request_id, "client_request_id_invalid")
        normalized_brief = brief.strip()
        if not normalized_brief or len(normalized_brief) > 8_000:
            raise StructuredPrototypeGenerationServiceError(
                "generation_request_invalid",
                "generation brief must contain between 1 and 8000 characters",
            )
        request_payload = {
            "contractVersion": 1,
            "mode": "requirements",
            "projectId": project_id,
            "brief": normalized_brief,
        }
        job_id = _stable_id(project_id, client_request_id, "generation-job")
        request_hash = _manifest_hash(request_payload)
        existing = await self._store.load_generation_job(job_id)
        if existing is not None:
            return self._reuse_generation_request(
                existing,
                project_id=project_id,
                client_request_id=client_request_id,
                request_hash=request_hash,
            )

        creation_lock = self._project_creation_locks.setdefault(project_id, asyncio.Lock())
        async with creation_lock:
            existing = await self._store.load_generation_job(job_id)
            if existing is not None:
                return self._reuse_generation_request(
                    existing,
                    project_id=project_id,
                    client_request_id=client_request_id,
                    request_hash=request_hash,
                )
            project = await self._project_store.load_project(project_id)
            if project is None:
                raise StructuredPrototypeGenerationServiceError(
                    "project_missing", "project does not exist"
                )
            now = self._now()
            job_operation = self._queued_operation(
                operation_id=_stable_id(job_id, "operation"),
                operation_kind="generation_job",
                project_id=project_id,
                resource_kind="generation_job",
                resource_id=job_id,
                client_request_id=client_request_id,
                request_hash=request_hash,
                parent_operation_id=None,
            )
            try:
                operation_created = await self._store.create_operation(
                    job_operation,
                    self._queued_event(job_operation),
                )
            except StructuredPrototypeStoreError as exc:
                raise StructuredPrototypeGenerationServiceError(
                    exc.code,
                    str(exc),
                    job_id=job_id,
                ) from exc
            if not operation_created.created:
                raced = await self._store.load_generation_job(job_id)
                if raced is not None:
                    return self._reuse_generation_request(
                        raced,
                        project_id=project_id,
                        client_request_id=client_request_id,
                        request_hash=request_hash,
                    )
                existing_operation = operation_created.operation
                if existing_operation.status in {"failed", "interrupted", "cancelled"}:
                    raise StructuredPrototypeGenerationServiceError(
                        existing_operation.error_code or "generation_creation_failed",
                        "generation creation previously failed before the job was registered",
                        job_id=job_id,
                    )
                raise StructuredPrototypeGenerationServiceError(
                    "generation_creation_in_progress",
                    "generation creation is already running before the job was registered",
                    job_id=job_id,
                )
            try:
                source_capture_started = await self._start_step(
                    job_operation.id,
                    "source_capture",
                )
                await self._store.record_operation_transition(*source_capture_started)
            except (
                StructuredPrototypeGenerationServiceError,
                StructuredPrototypeStoreError,
            ) as exc:
                raise StructuredPrototypeGenerationServiceError(
                    "observability_unavailable",
                    "generation source capture could not record its durable start evidence",
                    job_id=job_id,
                ) from exc
            try:
                source_capture = await self._source_control.capture_committed_head_snapshot(
                    project.repo_path,
                    job_id,
                )
            except GitError as exc:
                await self._persist_pre_job_failure(
                    job_operation.id,
                    "generation_source_snapshot_failed",
                    job_id=job_id,
                )
                raise StructuredPrototypeGenerationServiceError(
                    "generation_source_snapshot_failed",
                    str(exc),
                    job_id=job_id,
                ) from exc

            source_identity_payload = self._source_capture_payload(source_capture)
            source_fingerprint = _manifest_hash(source_identity_payload)
            source_manifest = {
                "manifestVersion": 1,
                "jobId": job_id,
                **source_identity_payload,
                "sourceFingerprint": source_fingerprint,
                "capturedAt": now.isoformat(),
            }
            context_payload = {
                "contractVersion": GENERATION_CONTRACT_VERSION,
                "taskKind": "generation_blueprint",
                "projectId": project_id,
                "projectName": project.name,
                "brief": normalized_brief,
                "contentPolicy": _generation_content_policy(),
                "generationPolicy": {
                    "sourceAuthority": "project-repository",
                    "scopeAuthority": "confirmed-blueprint",
                    "pageLimit": 20,
                    "businessIntentsOptional": True,
                    "requireRepositoryEvidence": True,
                    "forbidPresetBusinessDomains": True,
                },
            }
            try:
                request_descriptor, context_descriptor, source_descriptor = await asyncio.gather(
                    asyncio.to_thread(self._object_store.write_json, project_id, request_payload),
                    asyncio.to_thread(self._object_store.write_json, project_id, context_payload),
                    asyncio.to_thread(self._object_store.write_json, project_id, source_manifest),
                )
            except PrototypeObjectStoreError as exc:
                await self._persist_pre_job_failure(job_operation.id, exc.code, job_id=job_id)
                raise StructuredPrototypeGenerationServiceError(
                    exc.code,
                    str(exc),
                    job_id=job_id,
                ) from exc
            if request_descriptor.content_hash != request_hash:
                await self._persist_pre_job_failure(
                    job_operation.id,
                    "object_hash_mismatch",
                    job_id=job_id,
                )
                raise StructuredPrototypeGenerationServiceError(
                    "object_hash_mismatch",
                    "generation request object hash is inconsistent",
                    job_id=job_id,
                )

            run_id = _stable_id(job_id, "blueprint-run", "1")
            item_id = _stable_id(run_id, "blueprint")
            item_operation = self._queued_operation(
                operation_id=_stable_id(item_id, "operation"),
                operation_kind="generation_item",
                project_id=project_id,
                resource_kind="generation_item",
                resource_id=item_id,
                client_request_id=_stable_id(client_request_id, "blueprint-item"),
                request_hash=context_descriptor.content_hash,
                parent_operation_id=job_operation.id,
            )
            job = PrototypeDocumentGenerationJobRecord(
                id=job_id,
                project_id=project_id,
                client_request_id=client_request_id,
                status="queued",
                operation_id=job_operation.id,
                request_manifest_object_hash=request_hash,
                request_hash=request_hash,
                context_manifest_object_hash=context_descriptor.content_hash,
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
                created_at=now,
                updated_at=now,
                completed_at=None,
                source_policy="committed_head_v1",
                source_snapshot_object_hash=source_descriptor.content_hash,
                source_fingerprint=source_fingerprint,
                source_snapshot_ref=source_capture.snapshot_ref,
                repository_object_format=source_capture.repository_object_format,
                worktree_base_commit=source_capture.worktree_base_commit,
                repository_project_prefix=source_capture.repository_project_prefix,
                repository_tree_object_id=source_capture.repository_tree_object_id,
                source_file_exclusion_policy=(source_capture.source_file_exclusion_policy),
                working_tree_dirty=source_capture.working_tree_dirty,
                excluded_tracked_change_count=(source_capture.excluded_tracked_change_count),
                excluded_untracked_count=source_capture.excluded_untracked_count,
                excluded_sensitive_file_count=(source_capture.excluded_sensitive_file_count),
                excluded_status_hash=source_capture.excluded_status_hash,
            )
            run = PrototypeDocumentGenerationRunRecord(
                id=run_id,
                job_id=job_id,
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
                created_at=now,
                updated_at=now,
                started_at=None,
                completed_at=None,
            )
            item = self._pending_item(
                item_id=item_id,
                job_id=job_id,
                run_id=run_id,
                kind="blueprint",
                item_key="blueprint",
                page_key=None,
                item_ordinal=0,
                operation_id=item_operation.id,
                context_object_hash=context_descriptor.content_hash,
                task_id=_stable_id(item_id, "claude-task"),
                now=now,
            )
            try:
                item_created_descriptor = await asyncio.to_thread(
                    self._object_store.write_json,
                    project_id,
                    self._item_created_evidence_manifest(
                        item=item,
                        operation=item_operation,
                        context_object_hash=context_descriptor.content_hash,
                        created_at=now,
                    ),
                )
            except PrototypeObjectStoreError as exc:
                await self._persist_pre_job_failure(job_operation.id, exc.code, job_id=job_id)
                raise StructuredPrototypeGenerationServiceError(
                    exc.code,
                    str(exc),
                    job_id=job_id,
                ) from exc
            source_completed = await self._complete_step_keep_running(
                job_operation.id,
                output_hash=source_descriptor.content_hash,
                evidence_kind="generation_source_snapshot_manifest",
                evidence_ref=source_descriptor.content_hash,
            )
            item_creation_transitions = self._initial_item_step_transitions(
                operation=item_operation,
                item_created_evidence_hash=item_created_descriptor.content_hash,
                context_object_hash=context_descriptor.content_hash,
            )
            try:
                created = await self._store.create_generation_job(
                    job_operation=job_operation,
                    job_event=None,
                    item_operation=item_operation,
                    item_event=self._queued_event(item_operation),
                    job=job,
                    run=run,
                    item=item,
                    descriptors_and_references=(
                        (
                            request_descriptor,
                            self._reference(
                                job,
                                request_descriptor,
                                owner_kind="generation_job",
                                owner_id=job.id,
                                role="request-manifest",
                                payload_type="generation_request_manifest",
                            ),
                        ),
                        (
                            context_descriptor,
                            self._reference(
                                job,
                                context_descriptor,
                                owner_kind="generation_job",
                                owner_id=job.id,
                                role="context-manifest",
                                payload_type="generation_context_manifest",
                            ),
                        ),
                        (
                            source_descriptor,
                            self._reference(
                                job,
                                source_descriptor,
                                owner_kind="generation_job",
                                owner_id=job.id,
                                role="source-snapshot-manifest",
                                payload_type="generation_source_snapshot_manifest",
                            ),
                        ),
                        (
                            item_created_descriptor,
                            self._reference(
                                job,
                                item_created_descriptor,
                                owner_kind="generation_job",
                                owner_id=job.id,
                                role="blueprint-item-created-evidence",
                                payload_type="generation_evidence_manifest",
                            ),
                        ),
                    ),
                    operation_transitions=(source_completed, *item_creation_transitions),
                )
            except StructuredPrototypeStoreError as exc:
                await self._persist_pre_job_failure(job_operation.id, exc.code, job_id=job_id)
                raise StructuredPrototypeGenerationServiceError(
                    exc.code,
                    str(exc),
                    job_id=job_id,
                ) from exc
            if created.created:
                self._schedule(job.id, self._run_blueprint(job.id, project, context_payload))
            return created.snapshot

    async def get_job(self, job_id: str) -> PrototypeDocumentGenerationSnapshot:
        snapshot = await self._store.load_generation_job(job_id)
        if snapshot is None:
            raise StructuredPrototypeGenerationServiceError(
                "generation_job_missing", "generation job does not exist", job_id=job_id
            )
        return snapshot

    async def get_latest_project_job(
        self,
        project_id: str,
    ) -> PrototypeDocumentGenerationSnapshot | None:
        return await self._store.load_latest_project_generation_job(project_id)

    async def get_blueprint(self, job_id: str) -> GenerationBlueprintV1 | None:
        job = (await self.get_job(job_id)).job
        if job.blueprint_object_hash is None:
            return None
        return await self._load_blueprint(job)

    async def recover_interrupted_jobs(self) -> int:
        interrupted_at = self._now()
        scope = await self._store.load_generation_restart_recovery_scope()
        evidence_pairs: list[tuple[PrototypeObjectDescriptor, PrototypeObjectReference]] = []
        for target in scope.operations:
            operation = target.operation
            active_step = target.active_step
            payload = {
                "manifestVersion": GENERATION_EVIDENCE_MANIFEST_VERSION,
                "evidenceKind": "generation_restart_interruption",
                "scopeFingerprint": scope.fingerprint,
                "operationId": operation.id,
                "operationKind": operation.operation_kind,
                "projectId": operation.project_id,
                "resourceKind": operation.resource_kind,
                "resourceId": operation.resource_id,
                "parentOperationId": operation.parent_operation_id,
                "priorStatus": operation.status,
                "priorPhase": operation.phase,
                "activeStep": None
                if active_step is None
                else {
                    "id": active_step.id,
                    "stepKind": active_step.step_kind,
                    "stepOrdinal": active_step.step_ordinal,
                    "attempt": active_step.attempt,
                    "status": active_step.status,
                    "phase": active_step.phase,
                    "inputManifestHash": active_step.input_manifest_hash,
                    "configManifestHash": active_step.config_manifest_hash,
                },
                "errorCode": "restart_interrupted",
                "interruptedAt": interrupted_at.isoformat(),
            }
            try:
                descriptor = await asyncio.to_thread(
                    self._object_store.write_json,
                    operation.project_id,
                    payload,
                )
                canonical_bytes = await asyncio.to_thread(
                    self._object_store.read_canonical_bytes,
                    descriptor,
                )
            except PrototypeObjectStoreError as exc:
                raise StructuredPrototypeGenerationServiceError(
                    exc.code,
                    "generation restart evidence could not be persisted",
                ) from exc
            if parse_json_object(canonical_bytes) != payload:
                raise StructuredPrototypeGenerationServiceError(
                    "generation_recovery_evidence_corrupt",
                    "generation restart evidence changed during durable read-back",
                )
            evidence_pairs.append(
                (
                    descriptor,
                    PrototypeObjectReference(
                        project_id=operation.project_id,
                        owner_kind="replay_manifest",
                        owner_id=operation.id,
                        role="operation-interruption-evidence",
                        content_hash=descriptor.content_hash,
                        payload_type="generation_evidence_manifest",
                        schema_version=GENERATION_EVIDENCE_MANIFEST_VERSION,
                        created_at=interrupted_at,
                    ),
                )
            )
        try:
            interrupted = await self._store.interrupt_active_generation_jobs(
                expected_scope_fingerprint=scope.fingerprint,
                descriptors_and_references=tuple(evidence_pairs),
                interrupted_at=interrupted_at,
            )
        except StructuredPrototypeStoreError as exc:
            raise StructuredPrototypeGenerationServiceError(exc.code, str(exc)) from exc
        owned_snapshot_job_ids = frozenset(await self._store.list_generation_job_ids())
        projects = await self._project_store.list_projects()
        for project in projects:
            try:
                await self._resource_cleaner.cleanup_stale_prototype_generation_resources(
                    project,
                    owned_snapshot_job_ids=owned_snapshot_job_ids,
                )
            except (GitError, OSError, WorktreeError):
                logger.warning(
                    "Structured prototype generation resource cleanup failed: project_id=%s",
                    project.id,
                    exc_info=True,
                )
        return interrupted

    async def wait_for_job(self, job_id: str) -> PrototypeDocumentGenerationSnapshot:
        task = self._tasks.get(job_id)
        if task is not None:
            await task
        return await self.get_job(job_id)

    async def confirm_blueprint(
        self,
        *,
        job_id: str,
        client_request_id: str,
        expected_blueprint_version: int,
        expected_blueprint_hash: str,
    ) -> PrototypeDocumentGenerationConfirmResult:
        _require_uuid(client_request_id, "client_request_id_invalid")
        request_hash = _manifest_hash(
            {
                "jobId": job_id,
                "expectedBlueprintVersion": expected_blueprint_version,
                "expectedBlueprintHash": expected_blueprint_hash,
            }
        )
        run_id = _stable_id(job_id, client_request_id, "foundation-run")
        operation_id = _stable_id(run_id, "schedule-operation")
        try:
            existing = await self._store.load_generation_confirm_result(
                job_id=job_id,
                client_request_id=client_request_id,
                request_hash=request_hash,
                expected_operation_id=operation_id,
                expected_run_id=run_id,
                expected_blueprint_hash=expected_blueprint_hash,
            )
        except StructuredPrototypeStoreError as exc:
            raise StructuredPrototypeGenerationServiceError(
                exc.code,
                str(exc),
                job_id=job_id,
            ) from exc
        if existing is not None:
            return existing
        snapshot = await self.get_job(job_id)
        job = snapshot.job
        if job.status != "awaiting_confirmation" or job.blueprint_hash is None:
            raise StructuredPrototypeGenerationServiceError(
                "generation_job_conflict", "generation blueprint is not awaiting confirmation"
            )
        if (
            job.blueprint_version != expected_blueprint_version
            or job.blueprint_hash != expected_blueprint_hash
        ):
            raise StructuredPrototypeGenerationServiceError(
                "blueprint_conflict", "generation blueprint changed before confirmation"
            )
        project = await self._project_store.load_project(job.project_id)
        if project is None:
            raise StructuredPrototypeGenerationServiceError(
                "project_missing", "project does not exist", job_id=job.id
            )
        blueprint = await self._load_blueprint(job)
        foundation_context = {
            "contractVersion": GENERATION_CONTRACT_VERSION,
            "taskKind": "generation_foundation",
            "projectId": job.project_id,
            "blueprint": blueprint.model_dump(mode="json", by_alias=True),
            "contentPolicy": _generation_content_policy(),
            "requiredComponentTypes": [
                "Stack",
                "Grid",
                "Form",
                "Text",
                "Input",
                "Button",
                "Table",
            ],
            "tokenPolicy": {
                "deriveFromProject": True,
                "minimumColorTokens": 2,
                "minimumSpacingTokens": 1,
            },
        }
        now = self._now()
        item_id = _stable_id(run_id, "foundation")
        operation = self._queued_operation(
            operation_id=operation_id,
            operation_kind="generation_job",
            project_id=job.project_id,
            resource_kind="generation_job",
            resource_id=job.id,
            client_request_id=client_request_id,
            request_hash=request_hash,
            parent_operation_id=job.operation_id,
        )
        try:
            created_operation = await self._store.create_operation(
                operation,
                self._queued_event(operation),
            )
        except StructuredPrototypeStoreError as exc:
            raise StructuredPrototypeGenerationServiceError(
                exc.code,
                str(exc),
                job_id=job.id,
            ) from exc
        if not created_operation.created:
            try:
                retried = await self._store.load_generation_confirm_result(
                    job_id=job.id,
                    client_request_id=client_request_id,
                    request_hash=request_hash,
                    expected_operation_id=operation_id,
                    expected_run_id=run_id,
                    expected_blueprint_hash=expected_blueprint_hash,
                )
            except StructuredPrototypeStoreError as exc:
                raise StructuredPrototypeGenerationServiceError(
                    exc.code,
                    str(exc),
                    job_id=job.id,
                ) from exc
            if retried is not None:
                return retried
            raise StructuredPrototypeGenerationServiceError(
                "generation_confirm_in_progress",
                "generation blueprint confirmation is already freezing its context",
                job_id=job.id,
            )
        context_started = await self._start_step(operation.id, "freeze_context")
        try:
            await self._store.record_operation_transition(*context_started)
            context_descriptor = await asyncio.to_thread(
                self._object_store.write_json,
                job.project_id,
                foundation_context,
            )
        except (PrototypeObjectStoreError, StructuredPrototypeStoreError) as exc:
            code = exc.code
            await self._record_operation_failure(operation.id, code)
            raise StructuredPrototypeGenerationServiceError(
                code,
                str(exc),
                job_id=job.id,
            ) from exc
        operation = context_started[0]
        item_operation = self._queued_operation(
            operation_id=_stable_id(item_id, "operation"),
            operation_kind="generation_item",
            project_id=job.project_id,
            resource_kind="generation_item",
            resource_id=item_id,
            client_request_id=_stable_id(client_request_id, "foundation-item"),
            request_hash=context_descriptor.content_hash,
            parent_operation_id=operation.id,
        )
        generating_job = replace(job, status="generating", updated_at=now)
        run = PrototypeDocumentGenerationRunRecord(
            id=run_id,
            job_id=job.id,
            status="queued",
            blueprint_hash=job.blueprint_hash,
            total=1,
            processed=0,
            succeeded=0,
            failed=0,
            running=0,
            pending=1,
            error_code=None,
            error_message=None,
            created_at=now,
            updated_at=now,
            started_at=None,
            completed_at=None,
        )
        item = self._pending_item(
            item_id=item_id,
            job_id=job.id,
            run_id=run.id,
            kind="foundation",
            item_key="foundation",
            page_key=None,
            item_ordinal=0,
            operation_id=item_operation.id,
            context_object_hash=context_descriptor.content_hash,
            task_id=_stable_id(item_id, "claude-task"),
            now=now,
        )
        try:
            item_created_descriptor = await asyncio.to_thread(
                self._object_store.write_json,
                job.project_id,
                self._item_created_evidence_manifest(
                    item=item,
                    operation=item_operation,
                    context_object_hash=context_descriptor.content_hash,
                    created_at=now,
                ),
            )
        except PrototypeObjectStoreError as exc:
            await self._record_operation_failure(operation.id, exc.code)
            raise StructuredPrototypeGenerationServiceError(
                exc.code,
                str(exc),
                job_id=job.id,
            ) from exc
        item_creation_transitions = self._initial_item_step_transitions(
            operation=item_operation,
            item_created_evidence_hash=item_created_descriptor.content_hash,
            context_object_hash=context_descriptor.content_hash,
        )
        context_completed = await self._complete_step_keep_running(
            operation.id,
            output_hash=context_descriptor.content_hash,
            evidence_kind="generation_context_manifest",
            evidence_ref=context_descriptor.content_hash,
        )
        try:
            created = await self._store.create_generation_run(
                operation=operation,
                initial_event=None,
                job=generating_job,
                run=run,
                item_operations=((item, item_operation, self._queued_event(item_operation)),),
                expected_job_statuses=("awaiting_confirmation",),
                expected_blueprint_version=expected_blueprint_version,
                expected_blueprint_hash=expected_blueprint_hash,
                descriptors_and_references=(
                    (
                        context_descriptor,
                        self._reference(
                            job,
                            context_descriptor,
                            owner_kind="generation_item",
                            owner_id=item.id,
                            role="frozen-context",
                            payload_type="generation_context_manifest",
                        ),
                    ),
                    (
                        item_created_descriptor,
                        self._reference(
                            job,
                            item_created_descriptor,
                            owner_kind="generation_item",
                            owner_id=item.id,
                            role="item-created-evidence",
                            payload_type="generation_evidence_manifest",
                        ),
                    ),
                ),
                operation_transitions=(context_completed, *item_creation_transitions),
            )
        except StructuredPrototypeStoreError as exc:
            code = (
                "generation_confirm_idempotency_conflict"
                if exc.code == "operation_idempotency_conflict"
                else exc.code
            )
            await self._record_operation_failure(operation.id, code)
            raise StructuredPrototypeGenerationServiceError(code, str(exc), job_id=job.id) from exc
        if not created.created:
            try:
                retried = await self._store.load_generation_confirm_result(
                    job_id=job.id,
                    client_request_id=client_request_id,
                    request_hash=request_hash,
                    expected_operation_id=operation_id,
                    expected_run_id=run_id,
                    expected_blueprint_hash=expected_blueprint_hash,
                )
            except StructuredPrototypeStoreError as exc:
                raise StructuredPrototypeGenerationServiceError(
                    exc.code,
                    str(exc),
                    job_id=job.id,
                ) from exc
            if retried is not None:
                return retried
            raise StructuredPrototypeGenerationServiceError(
                "generation_confirm_conflict",
                "generation blueprint confirmation could not be resumed",
                job_id=job.id,
            )
        self._schedule(
            job.id,
            self._run_generation(job.id, project, foundation_context, operation.id),
        )
        return PrototypeDocumentGenerationConfirmResult(
            operation_id=operation.id,
            correlation_id=operation.correlation_id,
            snapshot=created.snapshot,
        )

    async def read_preview_file(self, job_id: str, relative_path: str) -> bytes:
        job = (await self.get_job(job_id)).job
        descriptor = self._preview_descriptor(job)
        try:
            return await asyncio.to_thread(
                self._artifact_store.read_file,
                descriptor,
                relative_path,
            )
        except PrototypeRenderArtifactStoreError as exc:
            raise StructuredPrototypeGenerationServiceError(
                exc.code, str(exc), job_id=job.id
            ) from exc

    def _preview_descriptor(
        self,
        job: PrototypeDocumentGenerationJobRecord,
    ) -> PrototypeRenderBundleDescriptor:
        if (
            job.status not in {"ready", "accepted"}
            or job.preview_artifact_id is None
            or job.preview_storage_key is None
            or job.preview_output_hash is None
            or job.preview_output_manifest_hash is None
            or job.preview_visual_preflight_report_hash is None
        ):
            raise StructuredPrototypeGenerationServiceError(
                "generation_preview_missing", "generation preview is not ready", job_id=job.id
            )
        preview_document_id = self._candidate_document_id(job.id)
        return PrototypeRenderBundleDescriptor(
            project_id=job.project_id,
            document_id=preview_document_id,
            artifact_id=job.preview_artifact_id,
            storage_key=job.preview_storage_key,
            entrypoint="index.html",
            output_hash=job.preview_output_hash,
            output_manifest_hash=job.preview_output_manifest_hash,
            visual_preflight_report_hash=job.preview_visual_preflight_report_hash,
            file_count=len(_PREVIEW_BUNDLE_FILES),
        )

    async def _read_preview_bundle(
        self,
        job: PrototypeDocumentGenerationJobRecord,
    ) -> dict[str, bytes]:
        descriptor = self._preview_descriptor(job)

        def read_files() -> tuple[bytes, ...]:
            return tuple(
                self._artifact_store.read_file(descriptor, relative_path)
                for relative_path in _PREVIEW_BUNDLE_FILES
            )

        try:
            contents = await asyncio.to_thread(read_files)
        except PrototypeRenderArtifactStoreError as exc:
            raise StructuredPrototypeGenerationServiceError(
                exc.code, str(exc), job_id=job.id
            ) from exc
        return dict(zip(_PREVIEW_BUNDLE_FILES, contents, strict=True))

    async def _validate_ready_preview_manifest(
        self,
        job: PrototypeDocumentGenerationJobRecord,
    ) -> None:
        if (
            job.replay_manifest_object_hash is None
            or job.candidate_object_hash is None
            or job.preview_renderer_version is None
            or job.preview_output_hash is None
            or job.preview_output_manifest_hash is None
        ):
            raise StructuredPrototypeGenerationServiceError(
                "generation_preview_manifest_missing",
                "generation preview has no complete replay manifest identity",
                job_id=job.id,
            )
        descriptor = await self._store.load_object(
            job.project_id,
            job.replay_manifest_object_hash,
        )
        if descriptor is None:
            raise StructuredPrototypeGenerationServiceError(
                "generation_preview_manifest_missing",
                "generation preview replay manifest descriptor is missing",
                job_id=job.id,
            )
        try:
            raw = await asyncio.to_thread(self._object_store.read_canonical_bytes, descriptor)
        except PrototypeObjectStoreError as exc:
            raise StructuredPrototypeGenerationServiceError(
                exc.code,
                str(exc),
                job_id=job.id,
            ) from exc
        try:
            manifest = PrototypeReplayManifestV1.from_canonical_json(raw)
        except PrototypeReplayManifestError as exc:
            raise StructuredPrototypeGenerationServiceError(
                "generation_preview_manifest_corrupt",
                "generation preview replay manifest is not a strict replay manifest",
                job_id=job.id,
            ) from exc
        operation = await self._store.load_operation(job.operation_id)
        if (
            operation is None
            or operation.status != "succeeded"
            or operation.result_manifest_hash != descriptor.content_hash
            or manifest.operation_id != job.operation_id
            or manifest.operation_kind != "generation_job"
            or manifest.context_manifest_hash != job.context_manifest_object_hash
            or job.candidate_object_hash not in manifest.ordered_input_object_hashes
            or manifest.versions.renderer_version != job.preview_renderer_version
            or manifest.renderer_output_hash != job.preview_output_hash
            or manifest.runtime_final_state_hash is None
            or manifest.runtime_final_view_model_hash is None
        ):
            raise StructuredPrototypeGenerationServiceError(
                "generation_preview_manifest_corrupt",
                "generation preview replay manifest does not match the ready candidate",
                job_id=job.id,
            )

    async def accept_candidate(
        self,
        *,
        job_id: str,
        client_request_id: str,
        expected_candidate_object_hash: str,
        expected_preview_output_hash: str,
        expected_source_fingerprint: str,
    ) -> PrototypeDocumentGenerationAcceptResult:
        _require_uuid(client_request_id, "client_request_id_invalid")
        request_hash = _manifest_hash(
            {
                "jobId": job_id,
                "candidateObjectHash": expected_candidate_object_hash,
                "previewOutputHash": expected_preview_output_hash,
                "sourceFingerprint": expected_source_fingerprint,
            }
        )
        try:
            existing = await self._store.load_generation_accept_result(
                job_id=job_id,
                client_request_id=client_request_id,
                request_hash=request_hash,
            )
        except StructuredPrototypeStoreError as exc:
            raise StructuredPrototypeGenerationServiceError(
                exc.code,
                str(exc),
                job_id=job_id,
            ) from exc
        if existing is not None:
            return existing
        snapshot = await self.get_job(job_id)
        job = snapshot.job
        if job.status != "ready":
            raise StructuredPrototypeGenerationServiceError(
                "generation_job_conflict",
                "generation candidate is not ready to accept",
                job_id=job.id,
            )
        if (
            job.candidate_object_hash != expected_candidate_object_hash
            or job.preview_output_hash != expected_preview_output_hash
            or job.source_fingerprint != expected_source_fingerprint
        ):
            raise StructuredPrototypeGenerationServiceError(
                "generation_candidate_conflict",
                "generation candidate or preview changed before accept",
                job_id=job.id,
            )
        if snapshot.latest_run is None:
            raise StructuredPrototypeGenerationServiceError(
                "generation_run_missing",
                "generation candidate has no completed run",
                job_id=job.id,
            )
        await self._load_source_snapshot(job)
        candidate_descriptor = await self._store.load_object(
            job.project_id,
            expected_candidate_object_hash,
        )
        if candidate_descriptor is None:
            raise StructuredPrototypeGenerationServiceError(
                "object_missing",
                "generation candidate object descriptor is missing",
                job_id=job.id,
            )
        candidate_bytes = await asyncio.to_thread(
            self._object_store.read_canonical_bytes,
            candidate_descriptor,
        )
        document = parse_prototype_document_json(candidate_bytes)
        if (
            document.id != self._candidate_document_id(job.id)
            or document_hash(document) != expected_candidate_object_hash
        ):
            raise StructuredPrototypeGenerationServiceError(
                "generation_candidate_corrupt",
                "generation candidate object does not match its reserved identity",
                job_id=job.id,
            )
        await self._validate_ready_preview_manifest(job)
        preview_files = await self._read_preview_bundle(job)
        if preview_files["document.json"] != candidate_bytes:
            raise StructuredPrototypeGenerationServiceError(
                "generation_preview_document_mismatch",
                "generation preview document does not match the candidate object",
                job_id=job.id,
            )
        operation = self._queued_operation(
            operation_id=_stable_id(job.id, client_request_id, "accept-operation"),
            operation_kind="create_document",
            project_id=job.project_id,
            resource_kind="document",
            resource_id=document.id,
            client_request_id=client_request_id,
            request_hash=request_hash,
            parent_operation_id=job.operation_id,
        )
        accept_operation_available = False
        try:
            created = await self._store.create_operation(operation, self._queued_event(operation))
            if not created.created:
                retried = await self._store.load_generation_accept_result(
                    job_id=job.id,
                    client_request_id=client_request_id,
                    request_hash=request_hash,
                )
                if retried is not None:
                    return retried
                if created.operation.status != "queued":
                    raise StructuredPrototypeGenerationServiceError(
                        "generation_accept_conflict",
                        "generation accept request could not be resumed",
                        job_id=job.id,
                    )
            accept_operation_available = True
            accept_running = await self._start_step(operation.id, "accept_candidate")
            await self._store.record_operation_transition(*accept_running)
            now = self._now()
            draft_id = _stable_id(operation.id, "draft")
            checkpoint_id = _stable_id(operation.id, "checkpoint", "0")
            journal_prefix_hash = initial_journal_prefix_hash(draft_id=draft_id)
            history_snapshot = CommandHistoryCheckpointV1(
                schema_version=COMMAND_HISTORY_CHECKPOINT_SCHEMA_VERSION,
                draft_id=draft_id,
                checkpoint_sequence_no=0,
                checkpoint_document_hash=expected_candidate_object_hash,
                journal_prefix_hash=journal_prefix_hash,
                undo_stack=[],
                redo_stack=[],
            )
            history_descriptor = await asyncio.to_thread(
                self._object_store.write_json,
                job.project_id,
                command_history_checkpoint_payload(history_snapshot),
            )
            history_bytes = await asyncio.to_thread(
                self._object_store.read_canonical_bytes,
                history_descriptor,
            )
            parsed_history = parse_command_history_checkpoint_json(history_bytes)
            if (
                canonical_command_history_checkpoint_json(parsed_history).encode("utf-8")
                != history_bytes
            ):
                raise StructuredPrototypeGenerationServiceError(
                    "command_history_checkpoint_hash_mismatch",
                    "generation command history checkpoint is not canonical after read-back",
                    job_id=job.id,
                )
            history_checkpoint = command_history_checkpoint_to_domain(
                parsed_history,
                snapshot_object_hash=history_descriptor.content_hash,
            )
            document_record = PrototypeDocumentRecord(
                id=document.id,
                project_id=job.project_id,
                title=document.title,
                published_revision_no=None,
                active_draft_id=draft_id,
                created_at=now,
                updated_at=now,
            )
            draft = PrototypeDraftRecord(
                id=draft_id,
                document_id=document.id,
                base_revision_no=None,
                status="active",
                head_sequence_no=0,
                head_document_hash=expected_candidate_object_hash,
                latest_checkpoint_id=checkpoint_id,
                publish_revision_no=None,
                created_at=now,
                updated_at=now,
                closed_at=None,
            )
            checkpoint = PrototypeCheckpointRecord(
                id=checkpoint_id,
                document_id=document.id,
                draft_id=draft_id,
                revision_id=None,
                checkpoint_kind="generation_accept",
                checkpoint_sequence_no=0,
                document_object_hash=expected_candidate_object_hash,
                document_schema_version=DOCUMENT_SCHEMA_VERSION,
                command_contract_version=COMMAND_CONTRACT_VERSION,
                document_hash=expected_candidate_object_hash,
                history_snapshot_object_hash=history_descriptor.content_hash,
                history_snapshot_schema_version=COMMAND_HISTORY_CHECKPOINT_SCHEMA_VERSION,
                journal_prefix_hash=journal_prefix_hash,
                created_by_operation_id=operation.id,
                created_at=now,
            )
            if job.replay_manifest_object_hash is None:
                raise StructuredPrototypeGenerationServiceError(
                    "generation_preview_manifest_missing",
                    "generation candidate has no ready replay evidence",
                    job_id=job.id,
                )
            accept_replay = await self._write_generation_replay_manifest(
                operation=accept_running[0],
                context_manifest_hash=job.context_manifest_object_hash,
                ordered_input_object_hashes=(
                    expected_candidate_object_hash,
                    history_descriptor.content_hash,
                    job.replay_manifest_object_hash,
                ),
                result_checkpoint_hash=expected_candidate_object_hash,
                result_sequence_no=0,
                renderer_output_hash=expected_preview_output_hash,
                include_renderer_identity=True,
            )
            accept_completed = self._complete_pending_step(
                accept_running,
                output_hash=accept_replay.descriptor.content_hash,
                evidence_kind="checkpoint",
                evidence_ref=checkpoint.id,
            )
            accepted_job = replace(
                job,
                status="accepted",
                document_id=document.id,
                updated_at=now,
                completed_at=now,
            )
            checkpoint_reference = self._reference(
                job,
                candidate_descriptor,
                owner_kind="checkpoint",
                owner_id=checkpoint.id,
                role="generation-accept",
                payload_type="prototype_document",
            )
            history_reference = self._reference(
                job,
                history_descriptor,
                owner_kind="checkpoint",
                owner_id=checkpoint.id,
                role="command-history-checkpoint",
                payload_type="prototype_command_history_checkpoint",
            )
            return await self._store.accept_generation_candidate(
                descriptor=candidate_descriptor,
                checkpoint_reference=checkpoint_reference,
                history_descriptor=history_descriptor,
                history_reference=history_reference,
                history_checkpoint=history_checkpoint,
                accept_replay_descriptor=accept_replay.descriptor,
                accept_replay_reference=accept_replay.reference,
                job=accepted_job,
                document=document_record,
                draft=draft,
                checkpoint=checkpoint,
                expected_candidate_object_hash=expected_candidate_object_hash,
                expected_preview_output_hash=expected_preview_output_hash,
                expected_source_fingerprint=expected_source_fingerprint,
                completed_transition=accept_completed,
            )
        except StructuredPrototypeGenerationServiceError as exc:
            if accept_operation_available:
                await self._record_operation_failure(operation.id, exc.code)
            raise
        except (
            PrototypeObjectStoreError,
            StructuredPrototypeContractError,
            StructuredPrototypeStoreError,
        ) as exc:
            if isinstance(exc, StructuredPrototypeStoreError) and exc.code in {
                "generation_job_conflict",
                "generation_candidate_conflict",
                "generation_accept_conflict",
            }:
                try:
                    retried = await self._store.load_generation_accept_result(
                        job_id=job.id,
                        client_request_id=client_request_id,
                        request_hash=request_hash,
                    )
                except StructuredPrototypeStoreError:
                    logger.warning(
                        "generation accept result could not be reloaded after conflict: %s",
                        job.id,
                        exc_info=True,
                    )
                else:
                    if retried is not None:
                        return retried
            if accept_operation_available:
                await self._record_operation_failure(operation.id, exc.code)
            raise StructuredPrototypeGenerationServiceError(
                exc.code,
                str(exc),
                job_id=job.id,
            ) from exc

    async def _run_blueprint(
        self,
        job_id: str,
        project: Project,
        context: dict[str, object],
    ) -> None:
        try:
            snapshot = await self.get_job(job_id)
            assert snapshot.latest_run is not None and len(snapshot.items) == 1
            job = snapshot.job
            source_snapshot = await self._load_source_snapshot(job)
            run = snapshot.latest_run
            item = snapshot.items[0]
            now = self._now()
            start_transitions = (await self._start_step(job.operation_id, "blueprint_planning"),)
            job = replace(job, status="planning", updated_at=now)
            run = replace(
                run,
                status="running",
                started_at=now,
                updated_at=now,
            )
            item = replace(item, phase="governance_decision", updated_at=now)
            await self._store.transition_generation_records(
                job=job,
                run=run,
                items=(item,),
                expected_job_statuses=("queued",),
                expected_run_statuses=("queued",),
                expected_item_statuses=("pending",),
                operation_transitions=start_transitions,
            )
            request = StructuredPrototypeGenerationTaskRequest(
                project=project,
                operation_id=item.operation_id,
                job_id=job.id,
                run_id=run.id,
                item_id=item.id,
                task_id=cast(str, item.task_id),
                task_kind="generation_blueprint",
                context_object_hash=item.context_object_hash,
                frozen_context=context,
                source_snapshot=source_snapshot,
            )
            item, governance = await self._authorize_item_execution(
                request=request,
                job=job,
                run=run,
                item=item,
                all_items=(item,),
            )
            result = await self._runtime.execute(
                request,
                evidence_callback=self._item_execution_evidence_callback(
                    job_id=job.id,
                    run_id=run.id,
                    item_id=item.id,
                ),
            )
            item = await self._mark_item_validating(job, run, item, result, "generation_blueprint")
            item, parsed_envelope, strict_report = await self._strict_validate_item_artifact(
                job,
                run,
                item,
                result,
            )
            if not isinstance(parsed_envelope, GenerationBlueprintEnvelopeV1):
                raise AssertionError("strict blueprint validation returned the wrong envelope type")
            envelope = parsed_envelope
            self._validate_envelope_scope(job, run, item, envelope)
            validate_generation_blueprint(envelope.payload)
            semantic_report = await self._semantic_validation_report(
                job=job,
                item=item,
                artifact_object_hash=result.artifact_descriptor.content_hash,
                scope_hash=cast(str, job.source_fingerprint),
            )
            item_replay = await self._write_item_replay_manifest(
                job=job,
                item=item,
                result=result,
                governance=governance,
                strict_validation_report_hash=strict_report.content_hash,
                semantic_validation_report_hash=semantic_report.content_hash,
            )
            now = self._now()
            item_transition = await self._complete_operation(
                item.operation_id,
                output_hash=semantic_report.content_hash,
                evidence_kind="validation_report",
                evidence_ref=semantic_report.content_hash,
                result_manifest_hash=item_replay.descriptor.content_hash,
            )
            job_transition = await self._complete_step_keep_running(
                job.operation_id,
                output_hash=result.artifact_descriptor.content_hash,
                evidence_kind="generation_blueprint",
                evidence_ref=result.artifact_descriptor.content_hash,
            )
            ready_job = replace(
                job,
                status="awaiting_confirmation",
                blueprint_object_hash=result.artifact_descriptor.content_hash,
                blueprint_version=1,
                blueprint_hash=result.artifact_descriptor.content_hash,
                updated_at=now,
            )
            completed_run = replace(
                run,
                status="completed",
                blueprint_hash=result.artifact_descriptor.content_hash,
                processed=1,
                succeeded=1,
                running=0,
                pending=0,
                updated_at=now,
                completed_at=now,
            )
            done_item = replace(
                item,
                status="done",
                phase="done",
                output_object_hash=result.artifact_descriptor.content_hash,
                updated_at=now,
                completed_at=now,
            )
            await self._store.transition_generation_records(
                job=ready_job,
                run=completed_run,
                items=(done_item,),
                expected_job_statuses=("planning",),
                expected_run_statuses=("running",),
                expected_item_statuses=("validating",),
                descriptors_and_references=(
                    (
                        semantic_report,
                        self._reference(
                            job,
                            semantic_report,
                            owner_kind="generation_item",
                            owner_id=item.id,
                            role="semantic-validation-report",
                            payload_type="validation_report",
                        ),
                    ),
                    (item_replay.descriptor, item_replay.reference),
                ),
                operation_transitions=(item_transition, job_transition),
            )
        except asyncio.CancelledError:
            raise
        except (
            PrototypeObjectStoreError,
            StructuredPrototypeStoreError,
            StructuredPrototypeGenerationRuntimeError,
            StructuredPrototypeGenerationAssemblyError,
            StructuredPrototypeGenerationServiceError,
        ) as exc:
            await self._mark_failed(job_id, exc.code, str(exc))

    async def _run_generation(
        self,
        job_id: str,
        project: Project,
        foundation_context: dict[str, object],
        phase_operation_id: str,
    ) -> None:
        active_phase_operation_id: str | None = phase_operation_id
        try:
            snapshot = await self.get_job(job_id)
            assert snapshot.latest_run is not None and len(snapshot.items) == 1
            job = snapshot.job
            source_snapshot = await self._load_source_snapshot(job)
            run = snapshot.latest_run
            item = snapshot.items[0]
            now = self._now()
            transitions = (await self._start_step(phase_operation_id, "generate_foundation"),)
            run = replace(
                run,
                status="running",
                started_at=now,
                updated_at=now,
            )
            item = replace(item, phase="governance_decision", updated_at=now)
            await self._store.transition_generation_records(
                job=job,
                run=run,
                items=(item,),
                expected_job_statuses=("generating",),
                expected_run_statuses=("queued",),
                expected_item_statuses=("pending",),
                operation_transitions=transitions,
            )
            request = StructuredPrototypeGenerationTaskRequest(
                project=project,
                operation_id=item.operation_id,
                job_id=job.id,
                run_id=run.id,
                item_id=item.id,
                task_id=cast(str, item.task_id),
                task_kind="generation_foundation",
                context_object_hash=item.context_object_hash,
                frozen_context=foundation_context,
                source_snapshot=source_snapshot,
            )
            item, governance = await self._authorize_item_execution(
                request=request,
                job=job,
                run=run,
                item=item,
                all_items=(item,),
            )
            result = await self._runtime.execute(
                request,
                evidence_callback=self._item_execution_evidence_callback(
                    job_id=job.id,
                    run_id=run.id,
                    item_id=item.id,
                ),
            )
            item = await self._mark_item_validating(job, run, item, result, "generation_foundation")
            item, parsed_envelope, strict_report = await self._strict_validate_item_artifact(
                job,
                run,
                item,
                result,
            )
            if not isinstance(parsed_envelope, GenerationFoundationEnvelopeV1):
                raise AssertionError(
                    "strict foundation validation returned the wrong envelope type"
                )
            envelope = parsed_envelope
            self._validate_envelope_scope(job, run, item, envelope)
            validate_generation_foundation(envelope.payload)
            semantic_report = await self._semantic_validation_report(
                job=job,
                item=item,
                artifact_object_hash=result.artifact_descriptor.content_hash,
                scope_hash=cast(str, job.blueprint_hash),
            )
            item_replay = await self._write_item_replay_manifest(
                job=job,
                item=item,
                result=result,
                governance=governance,
                strict_validation_report_hash=strict_report.content_hash,
                semantic_validation_report_hash=semantic_report.content_hash,
            )
            phase_operation, _, _ = await self._operation_state(phase_operation_id)
            phase_replay = await self._write_generation_replay_manifest(
                operation=phase_operation,
                context_manifest_hash=item.context_object_hash,
                ordered_input_object_hashes=(
                    item_replay.descriptor.content_hash,
                    result.artifact_descriptor.content_hash,
                ),
                agent_task_identity=item_replay.manifest.agent_task_identity,
                submission_hash=result.submission.envelope_hash,
                validation_report_hashes=(
                    strict_report.content_hash,
                    semantic_report.content_hash,
                ),
            )
            now = self._now()
            completed_item_transition = await self._complete_operation(
                item.operation_id,
                output_hash=semantic_report.content_hash,
                evidence_kind="validation_report",
                evidence_ref=semantic_report.content_hash,
                result_manifest_hash=item_replay.descriptor.content_hash,
            )
            completed_phase_transition = await self._complete_operation(
                phase_operation_id,
                output_hash=phase_replay.descriptor.content_hash,
                evidence_kind="replay_manifest",
                evidence_ref=phase_replay.descriptor.content_hash,
            )
            done_item = replace(
                item,
                status="done",
                phase="done",
                output_object_hash=result.artifact_descriptor.content_hash,
                updated_at=now,
                completed_at=now,
            )
            completed_run = replace(
                run,
                status="completed",
                processed=1,
                succeeded=1,
                running=0,
                pending=0,
                updated_at=now,
                completed_at=now,
            )
            await self._store.transition_generation_records(
                job=job,
                run=completed_run,
                items=(done_item,),
                expected_job_statuses=("generating",),
                expected_run_statuses=("running",),
                expected_item_statuses=("validating",),
                descriptors_and_references=(
                    (
                        semantic_report,
                        self._reference(
                            job,
                            semantic_report,
                            owner_kind="generation_item",
                            owner_id=item.id,
                            role="semantic-validation-report",
                            payload_type="validation_report",
                        ),
                    ),
                    (item_replay.descriptor, item_replay.reference),
                    (phase_replay.descriptor, phase_replay.reference),
                ),
                operation_transitions=(completed_item_transition, completed_phase_transition),
            )
            active_phase_operation_id = None
            page_snapshot, page_contexts, page_phase_operation_id = await self._create_page_run(
                job,
                envelope.payload,
            )
            active_phase_operation_id = page_phase_operation_id
            pages = await self._run_pages(
                project,
                page_snapshot,
                page_contexts,
                page_phase_operation_id,
                source_snapshot,
            )
            active_phase_operation_id = None
            await self._assemble_validate_render(
                project,
                page_snapshot.job,
                envelope.payload,
                result.artifact_descriptor.content_hash,
                pages,
                replay_operation_ids=(
                    _stable_id(
                        _stable_id(_stable_id(job.id, "blueprint-run", "1"), "blueprint"),
                        "operation",
                    ),
                    phase_operation_id,
                    page_phase_operation_id,
                ),
            )
        except asyncio.CancelledError:
            raise
        except (
            PrototypeObjectStoreError,
            PrototypeRenderArtifactStoreError,
            PrototypeRendererWorkerError,
            PrototypeRuntimeWorkerError,
            StructuredPrototypeStoreError,
            StructuredPrototypeGenerationRuntimeError,
            StructuredPrototypeGenerationAssemblyError,
            StructuredPrototypeGenerationServiceError,
        ) as exc:
            await self._mark_failed(
                job_id,
                exc.code,
                str(exc),
                active_phase_operation_id=active_phase_operation_id,
            )

    async def _create_page_run(
        self,
        job: PrototypeDocumentGenerationJobRecord,
        foundation: GenerationFoundationV1,
    ) -> tuple[PrototypeDocumentGenerationSnapshot, dict[str, dict[str, object]], str]:
        blueprint = await self._load_blueprint(job)
        page_contexts: dict[str, dict[str, object]] = {}
        context_descriptors: dict[str, PrototypeObjectDescriptor] = {}
        for page in blueprint.pages:
            page_flows = [
                flow.model_dump(mode="json", by_alias=True)
                for flow in blueprint.flow_intents
                if flow.source_page_key == page.page_key
            ]
            page_forms = [
                item.model_dump(mode="json", by_alias=True)
                for item in blueprint.form_intents
                if item.page_key == page.page_key
            ]
            page_view_bindings = [
                item.model_dump(mode="json", by_alias=True)
                for item in blueprint.view_binding_intents
                if item.page_key == page.page_key
            ]
            page_behaviors = [
                item.model_dump(mode="json", by_alias=True)
                for item in blueprint.behavior_intents
                if item.source_page_key == page.page_key
            ]
            context = {
                "contractVersion": GENERATION_CONTRACT_VERSION,
                "taskKind": "generation_page",
                "projectId": job.project_id,
                "page": page.model_dump(mode="json", by_alias=True),
                "foundation": foundation.model_dump(mode="json", by_alias=True),
                "contentPolicy": _generation_content_policy(),
                "confirmedIntents": {
                    "flows": page_flows,
                    "forms": page_forms,
                    "entities": [
                        item.model_dump(mode="json", by_alias=True)
                        for item in blueprint.entity_intents
                    ],
                    "viewBindings": page_view_bindings,
                    "behaviors": page_behaviors,
                },
                "nodePolicy": {
                    "rootType": "Stack",
                    "allowedTypes": [
                        "Stack",
                        "Grid",
                        "Form",
                        "Text",
                        "Input",
                        "Button",
                        "Table",
                    ],
                    "maxTextCharacters": 240,
                    "requireFlowSourceNodes": bool(page_flows),
                    "requireBehaviorSourceNodes": bool(page_behaviors),
                    "deriveContentFromProject": True,
                },
            }
            page_contexts[page.page_key] = context
            context_descriptors[page.page_key] = await asyncio.to_thread(
                self._object_store.write_json,
                job.project_id,
                context,
            )
        now = self._now()
        run_id = _stable_id(job.id, job.blueprint_hash or "", "page-run")
        phase_operation = self._queued_operation(
            operation_id=_stable_id(run_id, "schedule-operation"),
            operation_kind="generation_job",
            project_id=job.project_id,
            resource_kind="generation_job",
            resource_id=job.id,
            client_request_id=_stable_id(job.id, "page-run-request"),
            request_hash=_manifest_hash(foundation.model_dump(mode="json", by_alias=True)),
            parent_operation_id=job.operation_id,
        )
        item_operations: list[
            tuple[
                PrototypeDocumentGenerationItemRecord,
                PrototypeOperation,
                PrototypeOperationEvent,
            ]
        ] = []
        descriptor_references: list[tuple[PrototypeObjectDescriptor, PrototypeObjectReference]] = []
        item_creation_transitions: list[
            tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent]
        ] = []
        for item_ordinal, page in enumerate(blueprint.pages):
            page_key = page.page_key
            item_id = _stable_id(run_id, page_key)
            descriptor = context_descriptors[page_key]
            item_operation = self._queued_operation(
                operation_id=_stable_id(item_id, "operation"),
                operation_kind="generation_item",
                project_id=job.project_id,
                resource_kind="generation_item",
                resource_id=item_id,
                client_request_id=_stable_id(item_id, "request"),
                request_hash=descriptor.content_hash,
                parent_operation_id=phase_operation.id,
            )
            item = self._pending_item(
                item_id=item_id,
                job_id=job.id,
                run_id=run_id,
                kind="page",
                item_key=page_key,
                page_key=page_key,
                item_ordinal=item_ordinal,
                operation_id=item_operation.id,
                context_object_hash=descriptor.content_hash,
                task_id=_stable_id(item_id, "claude-task"),
                now=now,
            )
            item_created_descriptor = await asyncio.to_thread(
                self._object_store.write_json,
                job.project_id,
                self._item_created_evidence_manifest(
                    item=item,
                    operation=item_operation,
                    context_object_hash=descriptor.content_hash,
                    created_at=now,
                ),
            )
            item_operations.append((item, item_operation, self._queued_event(item_operation)))
            item_creation_transitions.extend(
                self._initial_item_step_transitions(
                    operation=item_operation,
                    item_created_evidence_hash=item_created_descriptor.content_hash,
                    context_object_hash=descriptor.content_hash,
                )
            )
            descriptor_references.append(
                (
                    descriptor,
                    self._reference(
                        job,
                        descriptor,
                        owner_kind="generation_item",
                        owner_id=item.id,
                        role="frozen-context",
                        payload_type="generation_context_manifest",
                    ),
                )
            )
            descriptor_references.append(
                (
                    item_created_descriptor,
                    self._reference(
                        job,
                        item_created_descriptor,
                        owner_kind="generation_item",
                        owner_id=item.id,
                        role="item-created-evidence",
                        payload_type="generation_evidence_manifest",
                    ),
                )
            )
        run = PrototypeDocumentGenerationRunRecord(
            id=run_id,
            job_id=job.id,
            status="queued",
            blueprint_hash=job.blueprint_hash,
            total=len(blueprint.pages),
            processed=0,
            succeeded=0,
            failed=0,
            running=0,
            pending=len(blueprint.pages),
            error_code=None,
            error_message=None,
            created_at=now,
            updated_at=now,
            started_at=None,
            completed_at=None,
        )
        result = await self._store.create_generation_run(
            operation=phase_operation,
            initial_event=self._queued_event(phase_operation),
            job=replace(job, updated_at=now),
            run=run,
            item_operations=tuple(item_operations),
            expected_job_statuses=("generating",),
            expected_blueprint_version=job.blueprint_version,
            expected_blueprint_hash=cast(str, job.blueprint_hash),
            descriptors_and_references=tuple(descriptor_references),
            operation_transitions=tuple(item_creation_transitions),
        )
        return result.snapshot, page_contexts, phase_operation.id

    async def _run_pages(
        self,
        project: Project,
        snapshot: PrototypeDocumentGenerationSnapshot,
        contexts: dict[str, dict[str, object]],
        phase_operation_id: str,
        source_snapshot: PrototypeGenerationSourceSnapshot,
    ) -> tuple[GeneratedPageV1, ...]:
        assert snapshot.latest_run is not None
        job = snapshot.job
        run = snapshot.latest_run
        ordered_items = tuple(sorted(snapshot.items, key=lambda item: item.item_ordinal))
        phase_transition = await self._start_step(phase_operation_id, "generate_pages")
        await self._store.transition_generation_records(
            job=job,
            run=run,
            items=ordered_items,
            expected_job_statuses=("generating",),
            expected_run_statuses=("queued",),
            expected_item_statuses=("pending",),
            operation_transitions=(phase_transition,),
        )

        state_lock = asyncio.Lock()
        tasks = [
            asyncio.create_task(
                self._run_page_item(
                    project=project,
                    job_id=job.id,
                    run_id=run.id,
                    item=item,
                    context=contexts[item.item_key],
                    source_snapshot=source_snapshot,
                    state_lock=state_lock,
                )
            )
            for item in ordered_items
        ]
        try:
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        pages: list[GeneratedPageV1] = []
        for outcome in outcomes:
            if isinstance(outcome, StructuredPrototypeGenerationServiceError):
                raise outcome
            if isinstance(outcome, BaseException):
                raise StructuredPrototypeGenerationServiceError(
                    "generation_internal_error",
                    "structured prototype page generation failed unexpectedly",
                    job_id=job.id,
                )
            pages.append(outcome)

        async with state_lock:
            completed_snapshot = await self._page_run_snapshot(job.id, run.id)
            assert completed_snapshot.latest_run is not None
            if any(item.status != "done" for item in completed_snapshot.items):
                raise StructuredPrototypeGenerationServiceError(
                    "generation_item_conflict",
                    "page generation completed without terminal item evidence",
                    job_id=job.id,
                )
            now = self._now()
            item_replay_hashes: list[str] = []
            item_output_hashes: list[str] = []
            for completed_item in completed_snapshot.items:
                item_operation = await self._store.load_operation(completed_item.operation_id)
                if (
                    item_operation is None
                    or item_operation.status != "succeeded"
                    or item_operation.result_manifest_hash is None
                    or completed_item.output_object_hash is None
                ):
                    raise StructuredPrototypeGenerationServiceError(
                        "generation_evidence_conflict",
                        "page phase cannot seal without terminal item replay evidence",
                        job_id=job.id,
                    )
                item_replay_hashes.append(item_operation.result_manifest_hash)
                item_output_hashes.append(completed_item.output_object_hash)
            phase_operation, _, _ = await self._operation_state(phase_operation_id)
            phase_replay = await self._write_generation_replay_manifest(
                operation=phase_operation,
                context_manifest_hash=completed_snapshot.job.context_manifest_object_hash,
                ordered_input_object_hashes=tuple(item_output_hashes + item_replay_hashes),
            )
            phase_completion = await self._complete_operation(
                phase_operation_id,
                output_hash=phase_replay.descriptor.content_hash,
                evidence_kind="replay_manifest",
                evidence_ref=phase_replay.descriptor.content_hash,
            )
            assemble_started = await self._start_step(job.operation_id, "assemble_candidate")
            completed_run = replace(
                _with_generation_run_counts(
                    completed_snapshot.latest_run,
                    completed_snapshot.items,
                    now,
                ),
                status="completed",
                completed_at=now,
            )
            assembling_job = replace(completed_snapshot.job, status="assembling", updated_at=now)
            await self._store.transition_generation_records(
                job=assembling_job,
                run=completed_run,
                items=completed_snapshot.items,
                expected_job_statuses=("generating",),
                expected_run_statuses=("running",),
                expected_item_statuses=("done",),
                descriptors_and_references=((phase_replay.descriptor, phase_replay.reference),),
                operation_transitions=(phase_completion, assemble_started),
            )
        return tuple(pages)

    async def _run_page_item(
        self,
        *,
        project: Project,
        job_id: str,
        run_id: str,
        item: PrototypeDocumentGenerationItemRecord,
        context: dict[str, object],
        source_snapshot: PrototypeGenerationSourceSnapshot,
        state_lock: asyncio.Lock,
    ) -> GeneratedPageV1 | StructuredPrototypeGenerationServiceError:
        try:
            async with self._page_generation_semaphore:
                async with state_lock:
                    active_snapshot = await self._page_run_snapshot(job_id, run_id)
                    assert active_snapshot.latest_run is not None
                    current_item = self._snapshot_item(active_snapshot, item.id)
                    if current_item.status != "pending":
                        raise StructuredPrototypeGenerationServiceError(
                            "generation_item_conflict",
                            "page generation item is not pending",
                            job_id=job_id,
                        )
                    request = StructuredPrototypeGenerationTaskRequest(
                        project=project,
                        operation_id=current_item.operation_id,
                        job_id=job_id,
                        run_id=run_id,
                        item_id=current_item.id,
                        task_id=cast(str, current_item.task_id),
                        task_kind="generation_page",
                        context_object_hash=current_item.context_object_hash,
                        frozen_context=context,
                        source_snapshot=source_snapshot,
                    )
                    item, governance = await self._authorize_item_execution(
                        request=request,
                        job=active_snapshot.job,
                        run=active_snapshot.latest_run,
                        item=current_item,
                        all_items=active_snapshot.items,
                    )

                result = await self._runtime.execute(
                    request,
                    evidence_callback=self._item_execution_evidence_callback(
                        job_id=job_id,
                        run_id=run_id,
                        item_id=item.id,
                        state_lock=state_lock,
                    ),
                )

                async with state_lock:
                    validating_snapshot = await self._page_run_snapshot(job_id, run_id)
                    assert validating_snapshot.latest_run is not None
                    current_item = self._snapshot_item(validating_snapshot, item.id)
                    validating_item = await self._mark_item_validating(
                        validating_snapshot.job,
                        validating_snapshot.latest_run,
                        current_item,
                        result,
                        "generation_page",
                        all_items=validating_snapshot.items,
                    )
                    (
                        validating_item,
                        parsed_envelope,
                        strict_report,
                    ) = await self._strict_validate_item_artifact(
                        validating_snapshot.job,
                        validating_snapshot.latest_run,
                        validating_item,
                        result,
                        all_items=validating_snapshot.items,
                    )
                    if not isinstance(parsed_envelope, GenerationPageEnvelopeV1):
                        raise AssertionError(
                            "strict page validation returned the wrong envelope type"
                        )
                    envelope = parsed_envelope
                    self._validate_envelope_scope(
                        validating_snapshot.job,
                        validating_snapshot.latest_run,
                        validating_item,
                        envelope,
                    )
                    if envelope.payload.page_key != item.page_key:
                        raise StructuredPrototypeGenerationServiceError(
                            "generation_semantic_invalid",
                            "Claude page key does not match its run item",
                            job_id=job_id,
                        )
                    semantic_report = await self._semantic_validation_report(
                        job=validating_snapshot.job,
                        item=validating_item,
                        artifact_object_hash=result.artifact_descriptor.content_hash,
                        scope_hash=cast(str, validating_snapshot.job.blueprint_hash),
                    )
                    item_replay = await self._write_item_replay_manifest(
                        job=validating_snapshot.job,
                        item=validating_item,
                        result=result,
                        governance=governance,
                        strict_validation_report_hash=strict_report.content_hash,
                        semantic_validation_report_hash=semantic_report.content_hash,
                    )
                    now = self._now()
                    before_completion_items = tuple(
                        validating_item if candidate.id == item.id else candidate
                        for candidate in validating_snapshot.items
                    )
                    done_item = replace(
                        validating_item,
                        status="done",
                        phase="done",
                        output_object_hash=result.artifact_descriptor.content_hash,
                        updated_at=now,
                        completed_at=now,
                    )
                    completed_items = tuple(
                        done_item if candidate.id == item.id else candidate
                        for candidate in before_completion_items
                    )
                    completed_run = _with_generation_run_counts(
                        validating_snapshot.latest_run,
                        completed_items,
                        now,
                    )
                    item_completed = await self._complete_operation(
                        item.operation_id,
                        output_hash=semantic_report.content_hash,
                        evidence_kind="validation_report",
                        evidence_ref=semantic_report.content_hash,
                        result_manifest_hash=item_replay.descriptor.content_hash,
                    )
                    await self._store.transition_generation_records(
                        job=validating_snapshot.job,
                        run=completed_run,
                        items=completed_items,
                        expected_job_statuses=("generating",),
                        expected_run_statuses=(validating_snapshot.latest_run.status,),
                        expected_item_statuses=tuple(
                            sorted({candidate.status for candidate in before_completion_items})
                        ),
                        descriptors_and_references=(
                            (
                                semantic_report,
                                self._reference(
                                    validating_snapshot.job,
                                    semantic_report,
                                    owner_kind="generation_item",
                                    owner_id=item.id,
                                    role="semantic-validation-report",
                                    payload_type="validation_report",
                                ),
                            ),
                            (item_replay.descriptor, item_replay.reference),
                        ),
                        operation_transitions=(item_completed,),
                    )
                return envelope.payload
        except asyncio.CancelledError:
            raise
        except (
            PrototypeObjectStoreError,
            StructuredPrototypeStoreError,
            StructuredPrototypeGenerationRuntimeError,
            StructuredPrototypeGenerationAssemblyError,
            StructuredPrototypeGenerationServiceError,
        ) as exc:
            error = (
                exc
                if isinstance(exc, StructuredPrototypeGenerationServiceError)
                else StructuredPrototypeGenerationServiceError(exc.code, str(exc), job_id=job_id)
            )
            async with state_lock:
                await self._mark_page_item_failed(job_id, run_id, item.id, error)
            return error

    async def _mark_page_item_failed(
        self,
        job_id: str,
        run_id: str,
        item_id: str,
        error: StructuredPrototypeGenerationServiceError,
    ) -> None:
        snapshot = await self._page_run_snapshot(job_id, run_id)
        assert snapshot.latest_run is not None
        current_item = self._snapshot_item(snapshot, item_id)
        if current_item.status in {"done", "failed", "interrupted"}:
            return
        now = self._now()
        failed_item = replace(
            current_item,
            status="failed",
            phase="failed",
            error_code=error.code,
            error_message=str(error)[:500],
            updated_at=now,
            completed_at=now,
        )
        failed_items = tuple(
            failed_item if candidate.id == item_id else candidate for candidate in snapshot.items
        )
        failed_run = _with_generation_run_counts(snapshot.latest_run, failed_items, now)
        item_failure = await self._fail_operation(current_item.operation_id, error.code)
        await self._store.transition_generation_records(
            job=snapshot.job,
            run=failed_run,
            items=failed_items,
            expected_job_statuses=(snapshot.job.status,),
            expected_run_statuses=(snapshot.latest_run.status,),
            expected_item_statuses=tuple(
                sorted({candidate.status for candidate in snapshot.items})
            ),
            descriptors_and_references=((item_failure.descriptor, item_failure.reference),),
            operation_transitions=(item_failure.transition,),
        )

    async def _page_run_snapshot(
        self,
        job_id: str,
        run_id: str,
    ) -> PrototypeDocumentGenerationSnapshot:
        snapshot = await self.get_job(job_id)
        if snapshot.latest_run is None or snapshot.latest_run.id != run_id:
            raise StructuredPrototypeGenerationServiceError(
                "generation_run_conflict",
                "page generation run is no longer current",
                job_id=job_id,
            )
        return snapshot

    @staticmethod
    def _snapshot_item(
        snapshot: PrototypeDocumentGenerationSnapshot,
        item_id: str,
    ) -> PrototypeDocumentGenerationItemRecord:
        item = next((candidate for candidate in snapshot.items if candidate.id == item_id), None)
        if item is None:
            raise StructuredPrototypeGenerationServiceError(
                "generation_item_missing",
                "page generation item does not exist",
                job_id=snapshot.job.id,
            )
        return item

    async def _assemble_validate_render(
        self,
        project: Project,
        job: PrototypeDocumentGenerationJobRecord,
        foundation: GenerationFoundationV1,
        foundation_object_hash: str,
        pages: tuple[GeneratedPageV1, ...],
        *,
        replay_operation_ids: tuple[str, ...],
    ) -> None:
        snapshot = await self.get_job(job.id)
        assert snapshot.latest_run is not None
        job = snapshot.job
        source_snapshot = await self._load_source_snapshot(job)
        run = snapshot.latest_run
        items = snapshot.items
        blueprint = await self._load_blueprint(job)
        ordered_input_object_hashes = (
            job.blueprint_object_hash,
            foundation_object_hash,
            *(item.output_object_hash for item in items),
        )
        if any(content_hash is None for content_hash in ordered_input_object_hashes):
            raise StructuredPrototypeGenerationServiceError(
                "completion_evidence_missing",
                "generation replay manifest inputs are incomplete",
                job_id=job.id,
            )
        document_id = self._candidate_document_id(job.id)
        document = assemble_generation_candidate(
            document_id=document_id,
            blueprint=blueprint,
            foundation=foundation,
            pages=pages,
        )
        candidate_hash = document_hash(document)
        candidate_descriptor = await asyncio.to_thread(
            self._object_store.write_json,
            job.project_id,
            document_payload(document),
        )
        if candidate_descriptor.content_hash != candidate_hash:
            raise StructuredPrototypeGenerationServiceError(
                "object_hash_mismatch", "assembled candidate object hash is inconsistent"
            )
        now = self._now()
        validation_transitions = await self._advance_step(
            job.operation_id,
            next_step_kind="validate_runtime",
            output_hash=candidate_hash,
            evidence_kind="prototype_document",
            evidence_ref=candidate_hash,
        )
        job = replace(
            job,
            status="validating",
            candidate_object_hash=candidate_hash,
            candidate_document_hash=candidate_hash,
            updated_at=now,
        )
        await self._store.transition_generation_records(
            job=job,
            run=run,
            items=items,
            expected_job_statuses=("assembling",),
            expected_run_statuses=("completed",),
            expected_item_statuses=("done",),
            descriptors_and_references=(
                (
                    candidate_descriptor,
                    self._reference(
                        job,
                        candidate_descriptor,
                        owner_kind="generation_job",
                        owner_id=job.id,
                        role="candidate-document",
                        payload_type="prototype_document",
                    ),
                ),
            ),
            operation_transitions=validation_transitions,
        )
        runtime_validation = await self._validate_runtime(
            job,
            document,
            blueprint,
            pages,
        )
        runtime_replay = runtime_validation.primary
        render_transitions = await self._advance_step(
            job.operation_id,
            next_step_kind="render_preview",
            output_hash=runtime_replay.final.state_hash,
            evidence_kind="runtime_replay",
            evidence_ref=runtime_replay.final.state_hash,
        )
        now = self._now()
        render_run_id = _stable_id(job.id, "preview-render-run")
        artifact_id = _stable_id(job.id, "preview-artifact")
        job = replace(
            job,
            status="rendering_preview",
            preview_render_run_id=render_run_id,
            preview_artifact_id=artifact_id,
            updated_at=now,
        )
        await self._store.transition_generation_records(
            job=job,
            run=run,
            items=items,
            expected_job_statuses=("validating",),
            expected_run_statuses=("completed",),
            expected_item_statuses=("done",),
            operation_transitions=render_transitions,
        )
        input_manifest = self._renderer_input_manifest(
            self._renderer.identity,
            document_object_hash=candidate_hash,
            output_locale=document.locale,
        )
        rendered = await self._renderer.render(
            request_id=render_run_id,
            artifact_id=artifact_id,
            input_manifest=input_manifest,
            document=document_payload(document),
        )
        bundle = await asyncio.to_thread(
            self._artifact_store.write_bundle,
            project_id=job.project_id,
            document_id=document_id,
            artifact_id=artifact_id,
            result=rendered,
        )
        root_input_hashes = [
            cast(str, content_hash) for content_hash in ordered_input_object_hashes
        ]
        root_input_hashes.extend(
            (
                job.request_manifest_object_hash,
                job.context_manifest_object_hash,
                source_snapshot.source_snapshot_object_hash,
                candidate_hash,
            )
        )
        for replay_operation_id in replay_operation_ids:
            replay_operation = await self._store.load_operation(replay_operation_id)
            if (
                replay_operation is None
                or replay_operation.status != "succeeded"
                or replay_operation.result_manifest_hash is None
            ):
                raise StructuredPrototypeGenerationServiceError(
                    "generation_evidence_conflict",
                    "generation root cannot seal without its ordered child replay evidence",
                    job_id=job.id,
                )
            root_input_hashes.append(replay_operation.result_manifest_hash)
        for generation_item in items:
            item_operation = await self._store.load_operation(generation_item.operation_id)
            if (
                item_operation is None
                or item_operation.status != "succeeded"
                or item_operation.result_manifest_hash is None
            ):
                raise StructuredPrototypeGenerationServiceError(
                    "generation_evidence_conflict",
                    "generation root cannot seal without terminal item replay evidence",
                    job_id=job.id,
                )
            root_input_hashes.append(item_operation.result_manifest_hash)
        root_operation, _, _ = await self._operation_state(job.operation_id)
        root_replay = await self._write_generation_replay_manifest(
            operation=root_operation,
            context_manifest_hash=job.context_manifest_object_hash,
            ordered_input_object_hashes=tuple(root_input_hashes),
            renderer_input_hash=_manifest_hash(input_manifest),
            renderer_output_hash=bundle.output_hash,
            runtime_final_state_hash=runtime_replay.final.state_hash,
            runtime_final_view_model_hash=runtime_replay.final.view_model_hash,
            include_renderer_identity=True,
        )
        completion_transition = await self._complete_operation(
            job.operation_id,
            output_hash=root_replay.descriptor.content_hash,
            evidence_kind="replay_manifest",
            evidence_ref=root_replay.descriptor.content_hash,
        )
        now = self._now()
        ready = replace(
            job,
            status="ready",
            preview_renderer_version=self._renderer.identity.renderer_version,
            preview_storage_key=bundle.storage_key,
            preview_output_hash=bundle.output_hash,
            preview_output_manifest_hash=bundle.output_manifest_hash,
            preview_visual_preflight_report_hash=bundle.visual_preflight_report_hash,
            replay_manifest_object_hash=root_replay.descriptor.content_hash,
            updated_at=now,
        )
        await self._store.transition_generation_records(
            job=ready,
            run=run,
            items=items,
            expected_job_statuses=("rendering_preview",),
            expected_run_statuses=("completed",),
            expected_item_statuses=("done",),
            descriptors_and_references=(
                (
                    root_replay.descriptor,
                    root_replay.reference,
                ),
            ),
            operation_transitions=(completion_transition,),
        )

    def _item_activity_callback(
        self,
        item: PrototypeDocumentGenerationItemRecord,
        *,
        state_lock: asyncio.Lock | None = None,
    ) -> PrototypeUiEngineerActivityCallback:
        task_id = item.task_id
        if task_id is None:
            raise StructuredPrototypeGenerationServiceError(
                "generation_execution_identity_mismatch",
                "generation item has no Claude task identity",
            )

        async def persist(activity: PrototypeUiEngineerActivity) -> None:
            if activity.task_id != task_id or activity.execution_process_id is None:
                raise StructuredPrototypeGenerationServiceError(
                    "generation_execution_identity_mismatch",
                    "generation activity does not match its durable item",
                )
            if state_lock is None:
                await self._store.bind_generation_item_execution_process(
                    item_id=item.id,
                    task_id=task_id,
                    execution_process_id=activity.execution_process_id,
                    bound_at=activity.occurred_at,
                )
                return
            async with state_lock:
                await self._store.bind_generation_item_execution_process(
                    item_id=item.id,
                    task_id=task_id,
                    execution_process_id=activity.execution_process_id,
                    bound_at=activity.occurred_at,
                )

        return persist

    async def _authorize_item_execution(
        self,
        *,
        request: StructuredPrototypeGenerationTaskRequest,
        job: PrototypeDocumentGenerationJobRecord,
        run: PrototypeDocumentGenerationRunRecord,
        item: PrototypeDocumentGenerationItemRecord,
        all_items: tuple[PrototypeDocumentGenerationItemRecord, ...],
    ) -> tuple[
        PrototypeDocumentGenerationItemRecord,
        StructuredPrototypeGenerationRuntimeGovernance,
    ]:
        try:
            governance = await self._runtime.evaluate_runtime_governance(request)
        except StructuredPrototypeGenerationRuntimeError as exc:
            raise StructuredPrototypeGenerationServiceError(
                exc.code, str(exc), job_id=job.id
            ) from exc
        decision = {
            "manifestVersion": GENERATION_EVIDENCE_MANIFEST_VERSION,
            "stepKind": "governance_decision",
            "operationId": item.operation_id,
            "decision": "allow" if governance.runtime_available else "deny",
            "reasonCode": governance.reason_code,
            "policyVersion": GENERATION_GOVERNANCE_POLICY_VERSION,
            "agentRole": "prototype_ui_engineer",
            "executor": governance.executor,
            "runtime": {
                "available": governance.runtime_available,
                "profileId": governance.runtime_profile_id,
                "profileHash": governance.runtime_profile_hash,
                "binary": governance.runtime_binary,
                "binaryHash": governance.runtime_binary_hash,
                "executorAdapterVersion": governance.executor_adapter_version,
                "claudeCodeVersion": governance.claude_code_version,
            },
            "budget": {
                "mode": "unconfigured",
                "estimatedCostUsd": None,
                "limitUsd": None,
            },
            "concurrency": {
                "pageLimit": timeouts.structured_prototype_page_generation_concurrency(),
                "itemKind": item.kind,
            },
            "inputHashes": [item.context_object_hash],
            "createdAt": self._now().isoformat(),
        }
        decision_descriptor = await asyncio.to_thread(
            self._object_store.write_json,
            job.project_id,
            decision,
        )
        if not governance.runtime_available:
            error_code = governance.reason_code or "prototype_ui_engineer_runtime_unavailable"
            denied_transition = await self._fail_active_step_with_evidence(
                item.operation_id,
                error_code=error_code,
                evidence_hash=decision_descriptor.content_hash,
                evidence_kind="generation_evidence_manifest",
            )
            now = self._now()
            denied_item = replace(
                item,
                status="failed",
                phase="failed",
                error_code=error_code,
                error_message="prototype UI engineer governance denied execution",
                updated_at=now,
                completed_at=now,
            )
            items = tuple(
                denied_item if candidate.id == item.id else candidate for candidate in all_items
            )
            await self._store.transition_generation_records(
                job=job,
                run=_with_generation_run_counts(run, items, now),
                items=items,
                expected_job_statuses=(job.status,),
                expected_run_statuses=(run.status,),
                expected_item_statuses=tuple(sorted({candidate.status for candidate in all_items})),
                descriptors_and_references=(
                    (
                        decision_descriptor,
                        self._reference(
                            job,
                            decision_descriptor,
                            owner_kind="generation_item",
                            owner_id=item.id,
                            role="governance-decision",
                            payload_type="generation_evidence_manifest",
                        ),
                    ),
                    (
                        decision_descriptor,
                        PrototypeObjectReference(
                            project_id=job.project_id,
                            owner_kind="replay_manifest",
                            owner_id=item.operation_id,
                            role="operation-failure-evidence",
                            content_hash=decision_descriptor.content_hash,
                            payload_type="generation_evidence_manifest",
                            schema_version=GENERATION_EVIDENCE_MANIFEST_VERSION,
                            created_at=now,
                        ),
                    ),
                ),
                operation_transitions=(denied_transition,),
            )
            raise StructuredPrototypeGenerationServiceError(
                error_code,
                "prototype UI engineer governance denied execution",
                job_id=job.id,
            )
        transitions = await self._advance_step(
            item.operation_id,
            next_step_kind="claude_task_created",
            output_hash=decision_descriptor.content_hash,
            evidence_kind="generation_evidence_manifest",
            evidence_ref=decision_descriptor.content_hash,
        )
        now = self._now()
        authorized_item = replace(
            item,
            status="generating",
            phase="claude_task_created",
            updated_at=now,
        )
        items = tuple(
            authorized_item if candidate.id == item.id else candidate for candidate in all_items
        )
        await self._store.transition_generation_records(
            job=job,
            run=replace(
                _with_generation_run_counts(run, items, now),
                status="running",
                started_at=run.started_at or now,
            ),
            items=items,
            expected_job_statuses=(job.status,),
            expected_run_statuses=(run.status,),
            expected_item_statuses=tuple(sorted({candidate.status for candidate in all_items})),
            descriptors_and_references=(
                (
                    decision_descriptor,
                    self._reference(
                        job,
                        decision_descriptor,
                        owner_kind="generation_item",
                        owner_id=item.id,
                        role="governance-decision",
                        payload_type="generation_evidence_manifest",
                    ),
                ),
            ),
            operation_transitions=transitions,
        )
        return authorized_item, governance

    def _item_execution_evidence_callback(
        self,
        *,
        job_id: str,
        run_id: str,
        item_id: str,
        state_lock: asyncio.Lock | None = None,
    ) -> StructuredPrototypeGenerationEvidenceCallback:
        async def persist(evidence: StructuredPrototypeGenerationExecutionEvidence) -> None:
            if state_lock is None:
                await self._persist_item_execution_evidence(
                    job_id=job_id,
                    run_id=run_id,
                    item_id=item_id,
                    evidence=evidence,
                )
                return
            async with state_lock:
                await self._persist_item_execution_evidence(
                    job_id=job_id,
                    run_id=run_id,
                    item_id=item_id,
                    evidence=evidence,
                )

        return persist

    async def _persist_item_execution_evidence(
        self,
        *,
        job_id: str,
        run_id: str,
        item_id: str,
        evidence: StructuredPrototypeGenerationExecutionEvidence,
    ) -> None:
        snapshot = await self._page_run_snapshot(job_id, run_id)
        assert snapshot.latest_run is not None
        item = self._snapshot_item(snapshot, item_id)
        if item.status != "generating" or item.task_id is None:
            raise StructuredPrototypeGenerationServiceError(
                "generation_evidence_conflict",
                "runtime evidence does not belong to a generating item",
                job_id=job_id,
            )
        self._validate_runtime_evidence_scope(snapshot.job, snapshot.latest_run, item, evidence)
        step_kind, next_step_kind, terminal_failure = self._runtime_evidence_step_transition(
            evidence
        )
        _, steps, _ = await self._operation_state(item.operation_id)
        active = next((step for step in reversed(steps) if step.status == "running"), None)
        if active is None or active.step_kind != step_kind:
            raise StructuredPrototypeGenerationServiceError(
                "generation_evidence_order_invalid",
                "runtime evidence does not match the active durable generation step",
                job_id=job_id,
            )
        evidence_payload = self._runtime_evidence_manifest(item, evidence, step_kind)
        evidence_descriptor = await asyncio.to_thread(
            self._object_store.write_json,
            snapshot.job.project_id,
            evidence_payload,
        )
        transitions: tuple[
            tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent],
            ...,
        ]
        if terminal_failure:
            transition = await self._complete_step_keep_running(
                item.operation_id,
                output_hash=evidence_descriptor.content_hash,
                evidence_kind="generation_evidence_manifest",
                evidence_ref=evidence_descriptor.content_hash,
            )
            updated_item = replace(
                item,
                phase="claude_process_terminal",
                updated_at=self._now(),
            )
            transitions = (transition,)
        elif next_step_kind is None:
            transition = await self._complete_step_keep_running(
                item.operation_id,
                output_hash=evidence_descriptor.content_hash,
                evidence_kind="generation_evidence_manifest",
                evidence_ref=evidence_descriptor.content_hash,
            )
            updated_item = replace(item, updated_at=self._now())
            transitions = (transition,)
        else:
            transitions = await self._advance_step(
                item.operation_id,
                next_step_kind=next_step_kind,
                output_hash=evidence_descriptor.content_hash,
                evidence_kind="generation_evidence_manifest",
                evidence_ref=evidence_descriptor.content_hash,
            )
            updated_item = replace(item, phase=next_step_kind, updated_at=self._now())
        if isinstance(evidence, GenerationProcessStartedEvidence):
            updated_item = replace(
                updated_item,
                execution_process_id=evidence.process.id,
            )
        items = tuple(
            updated_item if candidate.id == item.id else candidate for candidate in snapshot.items
        )
        await self._store.transition_generation_records(
            job=snapshot.job,
            run=_with_generation_run_counts(snapshot.latest_run, items, self._now()),
            items=items,
            expected_job_statuses=(snapshot.job.status,),
            expected_run_statuses=(snapshot.latest_run.status,),
            expected_item_statuses=tuple(
                sorted({candidate.status for candidate in snapshot.items})
            ),
            descriptors_and_references=(
                (
                    evidence_descriptor,
                    self._reference(
                        snapshot.job,
                        evidence_descriptor,
                        owner_kind="generation_item",
                        owner_id=item.id,
                        role=f"{step_kind}-evidence",
                        payload_type="generation_evidence_manifest",
                    ),
                ),
            ),
            operation_transitions=transitions,
        )

    @staticmethod
    def _runtime_evidence_step_transition(
        evidence: StructuredPrototypeGenerationExecutionEvidence,
    ) -> tuple[str, str | None, bool]:
        if isinstance(evidence, GenerationTaskCreatedEvidence):
            return "claude_task_created", "claude_process_started", False
        if isinstance(evidence, GenerationProcessStartedEvidence):
            return "claude_process_started", "runtime_wire_input", False
        if isinstance(evidence, GenerationWireInputEvidence):
            return "runtime_wire_input", "mcp_submission", False
        if isinstance(evidence, GenerationMcpSubmissionEvidence):
            return "mcp_submission", "claude_process_terminal", False
        if isinstance(evidence, GenerationProcessTerminalEvidence):
            return (
                "claude_process_terminal",
                "artifact_object_registered"
                if is_task_success_status(evidence.task_status)
                else None,
                not is_task_success_status(evidence.task_status),
            )
        raise AssertionError("structured prototype runtime evidence union is exhaustive")

    @staticmethod
    def _runtime_evidence_manifest(
        item: PrototypeDocumentGenerationItemRecord,
        evidence: StructuredPrototypeGenerationExecutionEvidence,
        step_kind: str,
    ) -> dict[str, object]:
        identity = {
            "itemId": item.id,
            "taskId": item.task_id,
            "stepKind": step_kind,
        }
        if isinstance(evidence, GenerationTaskCreatedEvidence):
            details: dict[str, object] = {
                "task": {
                    "id": evidence.task.id,
                    "workspaceId": evidence.workspace_id,
                    "projectId": evidence.task.project_id,
                    "role": evidence.task.role,
                    "executor": evidence.task.executor,
                    "taskKind": evidence.task.task_kind,
                },
                "worktree": {
                    "path": evidence.worktree_path,
                    "repositoryRoot": evidence.repository_root,
                    "contained": evidence.worktree_path_contained,
                    "baseCommit": evidence.worktree_base_commit,
                    "sourceSnapshotRef": evidence.source_snapshot_ref,
                    "sourceFingerprint": evidence.source_fingerprint,
                },
                "runtime": {
                    "executor": evidence.executor,
                    "profileId": evidence.runtime_profile_id,
                    "profileHash": evidence.runtime_profile_hash,
                    "binary": evidence.runtime_binary,
                    "binaryHash": evidence.runtime_binary_hash,
                    "adapterConfigHash": evidence.adapter_config_hash,
                    "adapterVersion": evidence.executor_adapter_version,
                },
            }
        elif isinstance(evidence, GenerationProcessStartedEvidence):
            details = {
                "process": {
                    "id": evidence.process.id,
                    "status": evidence.process.status,
                    "executor": evidence.process.executor,
                    "provider": evidence.process.provider,
                    "model": evidence.process.model,
                    "startedAt": evidence.process.started_at.isoformat()
                    if evidence.process.started_at is not None
                    else None,
                },
            }
        elif isinstance(evidence, GenerationWireInputEvidence):
            details = {
                "executionProcessId": evidence.execution_process_id,
                "finalRuntimeWireInputHash": evidence.final_runtime_wire_input_hash,
                "wireInputSize": evidence.wire_input_size,
                "framing": evidence.framing,
                "runtime": {
                    "profileId": evidence.runtime_profile_id,
                    "profileHash": evidence.runtime_profile_hash,
                    "configHash": evidence.runtime_config_hash,
                    "binary": evidence.runtime_binary,
                    "binaryHash": evidence.runtime_binary_hash,
                    "adapterConfigHash": evidence.adapter_config_hash,
                    "adapterVersion": evidence.executor_adapter_version,
                    "claudeCodeVersion": evidence.claude_code_version,
                },
            }
        elif isinstance(evidence, GenerationMcpSubmissionEvidence):
            details = {
                "executionProcessId": evidence.execution_process_id,
                "submissionId": evidence.submission_id,
                "requestHash": evidence.request_hash,
                "normalizedRequestHash": evidence.normalized_request_hash,
                "wireInputHash": evidence.wire_input_hash,
                "scopeFingerprint": evidence.scope_fingerprint,
                "acceptedAt": datetime.fromtimestamp(
                    evidence.accepted_at,
                    tz=UTC,
                ).isoformat(),
                "envelopeHash": evidence.envelope_hash,
                "envelopeSize": evidence.envelope_size,
                "repositoryRoot": evidence.repository_root,
                "resolvedPath": evidence.resolved_path,
                "pathContained": evidence.path_contained,
                "normalizedFields": list(evidence.normalized_fields),
            }
        elif isinstance(evidence, GenerationProcessTerminalEvidence):
            details = {
                "process": {
                    "id": evidence.process.id,
                    "status": evidence.process.status,
                    "exitCode": evidence.process.exit_code,
                    "completedAt": evidence.process.completed_at.isoformat()
                    if evidence.process.completed_at is not None
                    else None,
                },
                "taskStatus": evidence.task_status,
                "resultHash": evidence.result_hash,
                "resultSize": evidence.result_size,
                "usage": {
                    "inputTokens": evidence.input_tokens,
                    "outputTokens": evidence.output_tokens,
                    "cacheReadTokens": evidence.cache_read_tokens,
                    "totalCostUsd": (
                        str(evidence.total_cost_usd)
                        if evidence.total_cost_usd is not None
                        else None
                    ),
                },
            }
        else:
            raise AssertionError("structured prototype runtime evidence union is exhaustive")
        return {
            "manifestVersion": GENERATION_EVIDENCE_MANIFEST_VERSION,
            "stepKind": step_kind,
            "operationId": item.operation_id,
            "identities": identity,
            "details": details,
        }

    @staticmethod
    def _validate_runtime_evidence_scope(
        job: PrototypeDocumentGenerationJobRecord,
        run: PrototypeDocumentGenerationRunRecord,
        item: PrototypeDocumentGenerationItemRecord,
        evidence: StructuredPrototypeGenerationExecutionEvidence,
    ) -> None:
        if evidence.task_id != item.task_id:
            raise StructuredPrototypeGenerationServiceError(
                "generation_execution_identity_mismatch",
                "runtime evidence task identity does not match the generation item",
                job_id=job.id,
            )
        if isinstance(evidence, GenerationMcpSubmissionEvidence) and (
            evidence.project_id != job.project_id
            or evidence.job_id != job.id
            or evidence.run_id != run.id
            or evidence.item_id != item.id
            or evidence.task_kind != item.task_kind
            or evidence.context_object_hash != item.context_object_hash
            or not evidence.path_contained
        ):
            raise StructuredPrototypeGenerationServiceError(
                "submission_scope_violation",
                "MCP submission evidence is outside the frozen generation item scope",
                job_id=job.id,
            )
        if (
            isinstance(
                evidence,
                (GenerationProcessStartedEvidence, GenerationProcessTerminalEvidence),
            )
            and evidence.process.task_id != item.task_id
        ):
            raise StructuredPrototypeGenerationServiceError(
                "generation_execution_identity_mismatch",
                "runtime process identity does not match the generation item",
                job_id=job.id,
            )
        if (
            isinstance(evidence, GenerationWireInputEvidence)
            and item.execution_process_id is not None
            and evidence.execution_process_id != item.execution_process_id
        ):
            raise StructuredPrototypeGenerationServiceError(
                "generation_execution_identity_mismatch",
                "runtime wire input process does not match the generation item",
                job_id=job.id,
            )

    async def _fail_active_step_with_evidence(
        self,
        operation_id: str,
        *,
        error_code: str,
        evidence_hash: str,
        evidence_kind: str,
    ) -> tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent]:
        operation, steps, events = await self._operation_state(operation_id)
        active = next((step for step in reversed(steps) if step.status == "running"), None)
        if operation.status != "running" or active is None:
            raise StructuredPrototypeGenerationServiceError(
                "generation_evidence_conflict",
                "operation has no active step for durable failure evidence",
            )
        now = self._now()
        failed_step = replace(
            active,
            status="failed",
            phase="failed",
            output_manifest_hash=evidence_hash,
            completion_evidence_kind=evidence_kind,
            completion_evidence_ref=evidence_hash,
            error_code=error_code,
            completed_at=now,
        )
        failed_operation = replace(
            operation,
            status="failed",
            phase="failed",
            failure_evidence_hash=evidence_hash,
            error_code=error_code,
            completed_at=now,
        )
        return (
            failed_operation,
            failed_step,
            self._step_event(failed_operation, failed_step, len(events), "step_failed"),
        )

    async def _mark_item_validating(
        self,
        job: PrototypeDocumentGenerationJobRecord,
        run: PrototypeDocumentGenerationRunRecord,
        item: PrototypeDocumentGenerationItemRecord,
        result: StructuredPrototypeGenerationTaskResult,
        payload_type: PrototypeObjectPayloadType,
        *,
        all_items: tuple[PrototypeDocumentGenerationItemRecord, ...] | None = None,
    ) -> PrototypeDocumentGenerationItemRecord:
        transitions = await self._advance_step(
            item.operation_id,
            next_step_kind="strict_schema_validation",
            output_hash=result.artifact_descriptor.content_hash,
            evidence_kind=payload_type,
            evidence_ref=result.artifact_descriptor.content_hash,
        )
        now = self._now()
        validating = replace(
            item,
            status="validating",
            phase="strict_schema_validation",
            submission_id=result.submission.submission_id,
            submission_request_hash=result.submission.request_hash,
            submission_normalized_fields=result.submission.normalized_fields,
            submission_accepted_at=datetime.fromtimestamp(
                result.submission.accepted_at,
                tz=UTC,
            ),
            execution_process_id=result.execution_process_id,
            updated_at=now,
        )
        items = list(all_items or (item,))
        item_index = next(index for index, candidate in enumerate(items) if candidate.id == item.id)
        items[item_index] = validating
        current_run = _with_generation_run_counts(run, tuple(items), now)
        await self._store.transition_generation_records(
            job=job,
            run=current_run,
            items=tuple(items),
            expected_job_statuses=(job.status,),
            expected_run_statuses=(run.status,),
            expected_item_statuses=(
                "generating",
                "pending",
                "done",
                "failed",
                "interrupted",
            ),
            descriptors_and_references=(
                (
                    result.artifact_descriptor,
                    self._reference(
                        job,
                        result.artifact_descriptor,
                        owner_kind="generation_item",
                        owner_id=item.id,
                        role="submitted-artifact",
                        payload_type=payload_type,
                    ),
                ),
            ),
            operation_transitions=transitions,
        )
        return validating

    async def _strict_validate_item_artifact(
        self,
        job: PrototypeDocumentGenerationJobRecord,
        run: PrototypeDocumentGenerationRunRecord,
        item: PrototypeDocumentGenerationItemRecord,
        result: StructuredPrototypeGenerationTaskResult,
        *,
        all_items: tuple[PrototypeDocumentGenerationItemRecord, ...] | None = None,
    ) -> tuple[
        PrototypeDocumentGenerationItemRecord,
        GenerationArtifactEnvelopeV1,
        PrototypeObjectDescriptor,
    ]:
        try:
            canonical_bytes = await asyncio.to_thread(
                self._object_store.read_canonical_bytes,
                result.artifact_descriptor,
            )
            envelope = parse_generation_artifact(
                cast(GenerationTaskKind, item.task_kind),
                canonical_bytes,
            )
        except (PrototypeObjectStoreError, StructuredPrototypeContractError) as exc:
            code = (
                exc.code
                if isinstance(exc, PrototypeObjectStoreError)
                else "generation_schema_invalid"
            )
            raise StructuredPrototypeGenerationServiceError(code, str(exc), job_id=job.id) from exc
        expected_type = {
            "generation_blueprint": GenerationBlueprintEnvelopeV1,
            "generation_foundation": GenerationFoundationEnvelopeV1,
            "generation_page": GenerationPageEnvelopeV1,
        }[item.task_kind]
        if not isinstance(envelope, expected_type):
            raise StructuredPrototypeGenerationServiceError(
                "generation_contract_mismatch",
                "Claude returned the wrong generation artifact contract",
                job_id=job.id,
            )
        if generation_artifact_payload(envelope) != generation_artifact_payload(result.envelope):
            raise StructuredPrototypeGenerationServiceError(
                "generation_artifact_identity_mismatch",
                "registered generation artifact differs from the runtime result",
                job_id=job.id,
            )
        report = {
            "manifestVersion": GENERATION_EVIDENCE_MANIFEST_VERSION,
            "stepKind": "strict_schema_validation",
            "operationId": item.operation_id,
            "inputObjectHash": result.artifact_descriptor.content_hash,
            "generationContractVersion": GENERATION_CONTRACT_VERSION,
            "taskKind": item.task_kind,
            "valid": True,
            "validatedEnvelopeHash": _manifest_hash(generation_artifact_payload(envelope)),
            "createdAt": self._now().isoformat(),
        }
        report_descriptor = await asyncio.to_thread(
            self._object_store.write_json,
            job.project_id,
            report,
        )
        transitions = await self._advance_step(
            item.operation_id,
            next_step_kind="semantic_validation",
            output_hash=report_descriptor.content_hash,
            evidence_kind="validation_report",
            evidence_ref=report_descriptor.content_hash,
        )
        now = self._now()
        validated = replace(item, phase="semantic_validation", updated_at=now)
        items = list(all_items or (item,))
        item_index = next(index for index, candidate in enumerate(items) if candidate.id == item.id)
        items[item_index] = validated
        await self._store.transition_generation_records(
            job=job,
            run=_with_generation_run_counts(run, tuple(items), now),
            items=tuple(items),
            expected_job_statuses=(job.status,),
            expected_run_statuses=(run.status,),
            expected_item_statuses=(
                "generating",
                "validating",
                "pending",
                "done",
                "failed",
                "interrupted",
            ),
            descriptors_and_references=(
                (
                    report_descriptor,
                    self._reference(
                        job,
                        report_descriptor,
                        owner_kind="generation_item",
                        owner_id=item.id,
                        role="strict-schema-validation-report",
                        payload_type="validation_report",
                    ),
                ),
            ),
            operation_transitions=transitions,
        )
        return validated, envelope, report_descriptor

    async def _semantic_validation_report(
        self,
        *,
        job: PrototypeDocumentGenerationJobRecord,
        item: PrototypeDocumentGenerationItemRecord,
        artifact_object_hash: str,
        scope_hash: str,
    ) -> PrototypeObjectDescriptor:
        return await asyncio.to_thread(
            self._object_store.write_json,
            job.project_id,
            {
                "manifestVersion": GENERATION_EVIDENCE_MANIFEST_VERSION,
                "stepKind": "semantic_validation",
                "operationId": item.operation_id,
                "inputObjectHash": artifact_object_hash,
                "contextObjectHash": item.context_object_hash,
                "scopeHash": scope_hash,
                "generationContractVersion": GENERATION_CONTRACT_VERSION,
                "taskKind": item.task_kind,
                "valid": True,
                "createdAt": self._now().isoformat(),
            },
        )

    async def _write_item_replay_manifest(
        self,
        *,
        job: PrototypeDocumentGenerationJobRecord,
        item: PrototypeDocumentGenerationItemRecord,
        result: StructuredPrototypeGenerationTaskResult,
        governance: StructuredPrototypeGenerationRuntimeGovernance,
        strict_validation_report_hash: str,
        semantic_validation_report_hash: str,
    ) -> _GenerationReplayManifestArtifact:
        operation, _, _ = await self._operation_state(item.operation_id)
        if (
            item.task_id is None
            or item.execution_process_id is None
            or result.task_id != item.task_id
            or result.execution_process_id != item.execution_process_id
            or result.submission.envelope_hash != result.artifact_descriptor.content_hash
        ):
            raise StructuredPrototypeGenerationServiceError(
                "generation_execution_identity_mismatch",
                "generation replay evidence does not match its durable item execution",
                job_id=job.id,
            )
        agent_task_identity = {
            "taskId": item.task_id,
            "executionProcessId": item.execution_process_id,
            "taskKind": item.task_kind,
            "agentRole": "prototype_ui_engineer",
            "executor": governance.executor,
            "runtimeProfileId": governance.runtime_profile_id,
            "runtimeProfileHash": governance.runtime_profile_hash,
            "runtimeBinaryHash": governance.runtime_binary_hash,
            "executorAdapterVersion": governance.executor_adapter_version,
            "generationContractVersion": str(GENERATION_CONTRACT_VERSION),
            "generationPromptVersion": GENERATION_PROMPT_VERSION,
            "assemblerVersion": GENERATION_ASSEMBLER_VERSION,
            "canonicalizerVersion": CANONICALIZER_VERSION,
            "governancePolicyVersion": GENERATION_GOVERNANCE_POLICY_VERSION,
            "finalRuntimeWireInputHash": result.submission.wire_input_hash,
            "submissionId": result.submission.submission_id,
        }
        if governance.claude_code_version is not None:
            agent_task_identity["claudeCodeVersion"] = governance.claude_code_version
        return await self._write_generation_replay_manifest(
            operation=operation,
            context_manifest_hash=item.context_object_hash,
            ordered_input_object_hashes=(
                item.context_object_hash,
                result.artifact_descriptor.content_hash,
            ),
            agent_task_identity=agent_task_identity,
            submission_hash=result.submission.envelope_hash,
            validation_report_hashes=(
                strict_validation_report_hash,
                semantic_validation_report_hash,
            ),
        )

    async def _write_generation_replay_manifest(
        self,
        *,
        operation: PrototypeOperation,
        context_manifest_hash: str | None,
        ordered_input_object_hashes: tuple[str, ...],
        agent_task_identity: dict[str, str] | None = None,
        submission_hash: str | None = None,
        result_checkpoint_hash: str | None = None,
        result_sequence_no: int | None = None,
        renderer_input_hash: str | None = None,
        renderer_output_hash: str | None = None,
        runtime_final_state_hash: str | None = None,
        runtime_final_view_model_hash: str | None = None,
        validation_report_hashes: tuple[str, ...] = (),
        include_renderer_identity: bool = False,
    ) -> _GenerationReplayManifestArtifact:
        runtime_identity = self._runtime_worker.identity
        renderer_identity = self._renderer.identity if include_renderer_identity else None
        versions = PrototypeReplayManifestVersionsV1(
            service_version=GENERATION_CONFIG_VERSION,
            document_schema_version=DOCUMENT_SCHEMA_VERSION,
            command_contract_version=COMMAND_CONTRACT_VERSION,
            runtime_state_schema_version=GENERATION_RUNTIME_STATE_SCHEMA_VERSION,
            runtime_event_contract_version=GENERATION_RUNTIME_EVENT_CONTRACT_VERSION,
            runtime_core_version=runtime_identity.runtime_core_version,
            runtime_core_bundle_hash=runtime_identity.runtime_core_bundle_hash,
            state_machine_kernel_version=runtime_identity.state_machine_kernel_version,
            renderer_version=(
                renderer_identity.renderer_version if renderer_identity is not None else None
            ),
            renderer_environment_version=(
                renderer_identity.renderer_environment_version
                if renderer_identity is not None
                else None
            ),
        )
        manifest = PrototypeReplayManifestV1(
            operation_id=operation.id,
            operation_kind=operation.operation_kind,
            parent_operation_id=operation.parent_operation_id,
            request_manifest_hash=operation.request_manifest_hash,
            context_manifest_hash=context_manifest_hash,
            ordered_input_object_hashes=ordered_input_object_hashes,
            versions=versions,
            agent_task_identity=agent_task_identity,
            submission_hash=submission_hash,
            ordered_command_batch_hashes=(),
            base_checkpoint_hash=None,
            base_sequence_no=None,
            result_checkpoint_hash=result_checkpoint_hash,
            result_sequence_no=result_sequence_no,
            renderer_input_hash=renderer_input_hash,
            renderer_output_hash=renderer_output_hash,
            runtime_session_id=None,
            runtime_core_bundle_hash=versions.runtime_core_bundle_hash,
            ordered_runtime_event_hashes=(),
            runtime_final_state_hash=runtime_final_state_hash,
            runtime_final_view_model_hash=runtime_final_view_model_hash,
            validation_report_hashes=validation_report_hashes,
            terminal_status="succeeded",
            error_code=None,
        )
        descriptor = await asyncio.to_thread(
            self._object_store.write_json,
            operation.project_id,
            manifest.to_payload(),
        )
        canonical_bytes = await asyncio.to_thread(
            self._object_store.read_canonical_bytes,
            descriptor,
        )
        try:
            read_back = PrototypeReplayManifestV1.from_canonical_json(canonical_bytes)
        except PrototypeReplayManifestError as exc:
            raise StructuredPrototypeGenerationServiceError(
                "generation_replay_manifest_readback_invalid",
                "generation replay manifest failed strict read-back validation",
            ) from exc
        if read_back != manifest or read_back.to_payload() != manifest.to_payload():
            raise StructuredPrototypeGenerationServiceError(
                "generation_replay_manifest_readback_invalid",
                "generation replay manifest changed during durable read-back",
            )
        return _GenerationReplayManifestArtifact(
            manifest=manifest,
            descriptor=descriptor,
            reference=PrototypeObjectReference(
                project_id=operation.project_id,
                owner_kind="replay_manifest",
                owner_id=operation.id,
                role="operation-replay-manifest",
                content_hash=descriptor.content_hash,
                payload_type="replay_manifest",
                schema_version=REPLAY_MANIFEST_SCHEMA_VERSION,
                created_at=self._now(),
            ),
        )

    @staticmethod
    def _validate_envelope_scope(
        job: PrototypeDocumentGenerationJobRecord,
        run: PrototypeDocumentGenerationRunRecord,
        item: PrototypeDocumentGenerationItemRecord,
        envelope: GenerationArtifactEnvelopeV1,
    ) -> None:
        if (
            envelope.job_id != job.id
            or envelope.run_id != run.id
            or envelope.item_id != item.id
            or envelope.task_kind != item.task_kind
            or envelope.context_object_hash != item.context_object_hash
        ):
            raise StructuredPrototypeGenerationServiceError(
                "submission_scope_violation",
                "generation artifact identity is outside its frozen item scope",
                job_id=job.id,
            )

    async def _validate_runtime(
        self,
        job: PrototypeDocumentGenerationJobRecord,
        document: PrototypeDocumentV1,
        blueprint: GenerationBlueprintV1,
        pages: tuple[GeneratedPageV1, ...],
    ) -> _GenerationRuntimeValidationResult:
        definition = document.runtime.model_dump(mode="json", by_alias=True)
        cases = generation_validation_cases(
            document_id=document.id,
            blueprint=blueprint,
            pages=pages,
        )
        primary: PrototypeRuntimeWorkerReplayResult | None = None
        evidence: list[dict[str, object]] = []
        for case in cases:
            initial = await self._runtime_worker.initialize_state(
                request_id=_stable_id(job.id, case.scenario_key, "runtime-initialize"),
                definition=definition,
                scenario_id=case.scenario_id,
                session_id=_stable_id(job.id, case.scenario_key, "runtime-validation-session"),
            )
            replay = await self._runtime_worker.replay_event_batches(
                request_id=_stable_id(job.id, case.scenario_key, "runtime-replay"),
                definition=definition,
                state_json=initial.state_json,
                batches=list(case.batches),
            )
            outcomes = tuple(transition.outcome for transition in replay.transitions)
            if outcomes != case.expected_outcomes:
                raise StructuredPrototypeGenerationServiceError(
                    "runtime_scenario_failed",
                    f"generated runtime scenario {case.scenario_key} produced unexpected outcomes",
                )
            self._validate_runtime_milestones(case, initial, replay)
            evidence.append(
                {
                    "scenarioKey": case.scenario_key,
                    "scenarioId": case.scenario_id,
                    "initialStateHash": initial.state_hash,
                    "initialViewModelHash": initial.view_model_hash,
                    "eventBatchHashes": [
                        transition.event_batch_hash for transition in replay.transitions
                    ],
                    "transitionGuardReportHashes": [
                        transition.guard_report_hash for transition in replay.transitions
                    ],
                    "transitionEffectReportHashes": [
                        transition.effect_report_hash for transition in replay.transitions
                    ],
                    "outcomes": list(outcomes),
                    "milestoneCount": len(case.milestones),
                    "finalStateHash": replay.final.state_hash,
                    "finalViewModelHash": replay.final.view_model_hash,
                }
            )
            if primary is None:
                primary = replay
        assert primary is not None
        return _GenerationRuntimeValidationResult(
            primary=primary,
            scenario_evidence=tuple(evidence),
        )

    @staticmethod
    def _validate_runtime_milestones(
        case: GenerationScenarioValidationCase,
        initial: PrototypeRuntimeWorkerStateResult,
        replay: PrototypeRuntimeWorkerReplayResult,
    ) -> None:
        milestones = case.milestones
        states = [initial.state_json, *(transition.state_json for transition in replay.transitions)]
        for milestone in milestones:
            state = parse_json_object(states[milestone["afterStep"]])
            if state is None:
                raise StructuredPrototypeGenerationServiceError(
                    "runtime_scenario_failed",
                    "generated runtime milestone state is invalid",
                )
            current_page_id = milestone["currentPageId"]
            if current_page_id is not None and state.get("currentPageId") != current_page_id:
                raise StructuredPrototypeGenerationServiceError(
                    "runtime_scenario_failed",
                    "generated runtime milestone did not reach its expected page",
                )
            variable_values = state.get("variableValues")
            entity_sets = state.get("entitySets")
            if not isinstance(variable_values, list) or not isinstance(entity_sets, list):
                raise StructuredPrototypeGenerationServiceError(
                    "runtime_scenario_failed",
                    "generated runtime milestone state is incomplete",
                )
            for variable_expectation in milestone["variableValues"]:
                actual = next(
                    (
                        item.get("value")
                        for item in variable_values
                        if isinstance(item, dict)
                        and item.get("variableId") == variable_expectation["variableId"]
                    ),
                    None,
                )
                if actual != variable_expectation["value"]:
                    raise StructuredPrototypeGenerationServiceError(
                        "runtime_scenario_failed",
                        "generated runtime milestone variable value does not match",
                    )
            for entity_expectation in milestone["entityFieldValues"]:
                actual = None
                for entity_set in entity_sets:
                    if (
                        not isinstance(entity_set, dict)
                        or entity_set.get("schemaId") != entity_expectation["schemaId"]
                    ):
                        continue
                    entities = entity_set.get("entities")
                    if not isinstance(entities, list):
                        continue
                    for entity in entities:
                        if (
                            not isinstance(entity, dict)
                            or entity.get("id") != entity_expectation["entityId"]
                        ):
                            continue
                        fields = entity.get("fields")
                        if not isinstance(fields, list):
                            continue
                        actual = next(
                            (
                                field.get("value")
                                for field in fields
                                if isinstance(field, dict)
                                and field.get("fieldId") == entity_expectation["fieldId"]
                            ),
                            None,
                        )
                if actual != entity_expectation["value"]:
                    raise StructuredPrototypeGenerationServiceError(
                        "runtime_scenario_failed",
                        "generated runtime milestone entity field value does not match",
                    )

    @staticmethod
    def _reuse_generation_request(
        snapshot: PrototypeDocumentGenerationSnapshot,
        *,
        project_id: str,
        client_request_id: str,
        request_hash: str,
    ) -> PrototypeDocumentGenerationSnapshot:
        job = snapshot.job
        if (
            job.project_id != project_id
            or job.client_request_id != client_request_id
            or job.request_manifest_object_hash != request_hash
            or job.request_hash != request_hash
        ):
            raise StructuredPrototypeGenerationServiceError(
                "generation_job_idempotency_conflict",
                "generation request ID is already bound to different requirements",
                job_id=job.id,
            )
        return snapshot

    @staticmethod
    def _source_capture_payload(
        capture: PrototypeGenerationCommittedHeadCapture,
    ) -> dict[str, object]:
        return {
            "sourcePolicy": "committed_head_v1",
            "snapshotRef": capture.snapshot_ref,
            "repositoryObjectFormat": capture.repository_object_format,
            "worktreeBaseCommit": capture.worktree_base_commit,
            "repositoryProjectPrefix": capture.repository_project_prefix,
            "repositoryTreeObjectId": capture.repository_tree_object_id,
            "sourceFileExclusionPolicy": capture.source_file_exclusion_policy,
            "workingTreeDirty": capture.working_tree_dirty,
            "excludedTrackedChangeCount": capture.excluded_tracked_change_count,
            "excludedUntrackedCount": capture.excluded_untracked_count,
            "excludedSensitiveFileCount": capture.excluded_sensitive_file_count,
            "excludedStatusHash": capture.excluded_status_hash,
        }

    @staticmethod
    def _source_snapshot_git_payload(
        snapshot: PrototypeGenerationSourceSnapshot,
    ) -> dict[str, object]:
        return {
            "sourcePolicy": snapshot.source_policy,
            "snapshotRef": snapshot.source_snapshot_ref,
            "repositoryObjectFormat": snapshot.repository_object_format,
            "worktreeBaseCommit": snapshot.worktree_base_commit,
            "repositoryProjectPrefix": snapshot.repository_project_prefix,
            "repositoryTreeObjectId": snapshot.repository_tree_object_id,
            "sourceFileExclusionPolicy": snapshot.source_file_exclusion_policy,
            "workingTreeDirty": snapshot.working_tree_dirty,
            "excludedTrackedChangeCount": snapshot.excluded_tracked_change_count,
            "excludedUntrackedCount": snapshot.excluded_untracked_count,
            "excludedSensitiveFileCount": snapshot.excluded_sensitive_file_count,
            "excludedStatusHash": snapshot.excluded_status_hash,
        }

    @classmethod
    def _source_snapshot_payload(
        cls,
        snapshot: PrototypeGenerationSourceSnapshot,
    ) -> dict[str, object]:
        return {
            **cls._source_snapshot_git_payload(snapshot),
            "sourceSnapshotObjectHash": snapshot.source_snapshot_object_hash,
            "sourceFingerprint": snapshot.source_fingerprint,
        }

    async def _load_source_snapshot(
        self,
        job: PrototypeDocumentGenerationJobRecord,
    ) -> PrototypeGenerationSourceSnapshot:
        if (
            job.source_policy != "committed_head_v1"
            or job.source_snapshot_object_hash is None
            or job.source_fingerprint is None
            or job.source_snapshot_ref is None
            or job.repository_object_format is None
            or job.worktree_base_commit is None
            or job.repository_project_prefix is None
            or job.repository_tree_object_id is None
            or job.source_file_exclusion_policy != "dotenv_checkout_filter_v1"
            or job.working_tree_dirty is None
            or job.excluded_tracked_change_count is None
            or job.excluded_untracked_count is None
            or job.excluded_sensitive_file_count is None
            or job.excluded_status_hash is None
        ):
            raise StructuredPrototypeGenerationServiceError(
                "generation_source_snapshot_missing",
                "generation job has no complete committed source snapshot",
                job_id=job.id,
            )
        snapshot = PrototypeGenerationSourceSnapshot(
            source_policy=job.source_policy,
            source_snapshot_object_hash=job.source_snapshot_object_hash,
            source_fingerprint=job.source_fingerprint,
            source_snapshot_ref=job.source_snapshot_ref,
            repository_object_format=job.repository_object_format,
            worktree_base_commit=job.worktree_base_commit,
            repository_project_prefix=job.repository_project_prefix,
            repository_tree_object_id=job.repository_tree_object_id,
            source_file_exclusion_policy=job.source_file_exclusion_policy,
            working_tree_dirty=job.working_tree_dirty,
            excluded_tracked_change_count=job.excluded_tracked_change_count,
            excluded_untracked_count=job.excluded_untracked_count,
            excluded_sensitive_file_count=job.excluded_sensitive_file_count,
            excluded_status_hash=job.excluded_status_hash,
        )
        source_git_payload = self._source_snapshot_git_payload(snapshot)
        if (
            snapshot.source_snapshot_ref != f"refs/agent-collab/prototype-generation/{job.id}"
            or _manifest_hash(source_git_payload) != snapshot.source_fingerprint
        ):
            raise StructuredPrototypeGenerationServiceError(
                "generation_source_snapshot_corrupt",
                "generation source snapshot identity is inconsistent",
                job_id=job.id,
            )
        descriptor = await self._store.load_object(
            job.project_id,
            snapshot.source_snapshot_object_hash,
        )
        if descriptor is None:
            raise StructuredPrototypeGenerationServiceError(
                "generation_source_snapshot_missing",
                "generation source snapshot manifest descriptor is missing",
                job_id=job.id,
            )
        raw = await asyncio.to_thread(self._object_store.read_canonical_bytes, descriptor)
        manifest = parse_json_object(raw)
        expected_fields = {
            "manifestVersion": 1,
            "jobId": job.id,
            **source_git_payload,
            "sourceFingerprint": snapshot.source_fingerprint,
        }
        if (
            manifest is None
            or any(manifest.get(key) != value for key, value in expected_fields.items())
            or not isinstance(manifest.get("capturedAt"), str)
            or not manifest["capturedAt"]
        ):
            raise StructuredPrototypeGenerationServiceError(
                "generation_source_snapshot_corrupt",
                "generation source snapshot manifest does not match its job",
                job_id=job.id,
            )
        return snapshot

    async def _load_blueprint(
        self,
        job: PrototypeDocumentGenerationJobRecord,
    ) -> GenerationBlueprintV1:
        if job.blueprint_object_hash is None:
            raise StructuredPrototypeGenerationServiceError(
                "blueprint_missing", "generation blueprint object is missing", job_id=job.id
            )
        descriptor = await self._store.load_object(job.project_id, job.blueprint_object_hash)
        if descriptor is None:
            raise StructuredPrototypeGenerationServiceError(
                "object_missing", "generation blueprint descriptor is missing", job_id=job.id
            )
        raw = await asyncio.to_thread(self._object_store.read_canonical_bytes, descriptor)
        payload = parse_json_object(raw)
        if payload is None:
            raise StructuredPrototypeGenerationServiceError(
                "object_corrupt", "generation blueprint object is invalid", job_id=job.id
            )
        try:
            envelope = GenerationBlueprintEnvelopeV1.model_validate(
                payload,
                strict=True,
                by_alias=True,
                by_name=False,
            )
        except ValidationError as exc:
            raise StructuredPrototypeGenerationServiceError(
                "object_corrupt",
                "generation blueprint object does not satisfy its stored contract",
                job_id=job.id,
            ) from exc
        validate_generation_blueprint(envelope.payload)
        return envelope.payload

    async def _mark_failed(
        self,
        job_id: str,
        code: str,
        message: str,
        *,
        active_phase_operation_id: str | None = None,
    ) -> None:
        try:
            snapshot = await self.get_job(job_id)
            if snapshot.latest_run is None or snapshot.job.status in {
                "ready",
                "accepted",
                "failed",
                "interrupted",
                "cancelled",
            }:
                return
            now = self._now()
            items = tuple(
                replace(
                    item,
                    status="failed"
                    if item.status not in {"done", "failed", "interrupted"}
                    else item.status,
                    phase="failed"
                    if item.status not in {"done", "failed", "interrupted"}
                    else item.phase,
                    error_code=code
                    if item.status not in {"done", "failed", "interrupted"}
                    else item.error_code,
                    error_message=message[:500]
                    if item.status not in {"done", "failed", "interrupted"}
                    else item.error_message,
                    updated_at=now,
                    completed_at=now
                    if item.status not in {"done", "failed", "interrupted"}
                    else item.completed_at,
                )
                for item in snapshot.items
            )
            failures: list[_GenerationFailureArtifact] = []
            failures.append(await self._fail_operation(snapshot.job.operation_id, code))
            if active_phase_operation_id is not None:
                phase_operation = await self._store.load_operation(active_phase_operation_id)
                if phase_operation is not None and phase_operation.status in {"queued", "running"}:
                    failures.append(await self._fail_operation(active_phase_operation_id, code))
            for before, after in zip(snapshot.items, items, strict=True):
                if before.status != after.status:
                    failures.append(await self._fail_operation(before.operation_id, code))
            succeeded = sum(item.status == "done" for item in items)
            failed = sum(item.status in {"failed", "interrupted"} for item in items)
            if snapshot.latest_run.status == "completed":
                run = replace(snapshot.latest_run, updated_at=now)
            else:
                run = replace(
                    snapshot.latest_run,
                    status="failed",
                    processed=succeeded + failed,
                    succeeded=succeeded,
                    failed=failed,
                    running=0,
                    pending=0,
                    error_code=code,
                    error_message=message[:500],
                    updated_at=now,
                    completed_at=now,
                )
            job = replace(
                snapshot.job,
                status="failed",
                error_code=code,
                error_message=message[:500],
                updated_at=now,
                completed_at=now,
            )
            await self._store.transition_generation_records(
                job=job,
                run=run,
                items=items,
                expected_job_statuses=(snapshot.job.status,),
                expected_run_statuses=(snapshot.latest_run.status,),
                expected_item_statuses=tuple({item.status for item in snapshot.items}),
                descriptors_and_references=tuple(
                    (failure.descriptor, failure.reference) for failure in failures
                ),
                operation_transitions=tuple(failure.transition for failure in failures),
            )
        except (StructuredPrototypeGenerationServiceError, StructuredPrototypeStoreError) as exc:
            logger.exception(
                "failed to persist structured prototype generation failure: %s", job_id
            )
            raise StructuredPrototypeGenerationServiceError(
                "observability_unavailable",
                "structured prototype generation failure evidence could not be persisted",
                job_id=job_id,
            ) from exc

    def _schedule(self, job_id: str, coroutine: Coroutine[object, object, None]) -> None:
        task = asyncio.create_task(self._supervise(job_id, coroutine))
        self._tasks[job_id] = task
        task.add_done_callback(lambda completed: self._task_finished(job_id, completed))

    async def _supervise(
        self,
        job_id: str,
        coroutine: Coroutine[object, object, None],
    ) -> None:
        """Persist terminal evidence for failures outside the typed runtime boundary."""
        try:
            await coroutine
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "structured prototype generation task failed unexpectedly: job_id=%s",
                job_id,
            )
            try:
                await self._mark_failed(
                    job_id,
                    "generation_internal_error",
                    "structured prototype generation failed unexpectedly",
                )
            except Exception:
                logger.exception(
                    "structured prototype generation failure evidence could not be persisted: "
                    "job_id=%s",
                    job_id,
                )

    def _task_finished(self, job_id: str, task: asyncio.Task[None]) -> None:
        if self._tasks.get(job_id) is task:
            self._tasks.pop(job_id, None)
        try:
            task.result()
        except asyncio.CancelledError:
            logger.debug(
                "structured prototype generation task cancelled: job_id=%s",
                job_id,
            )
        except Exception:
            logger.exception(
                "structured prototype generation supervisor failed: job_id=%s",
                job_id,
            )

    async def _start_step(
        self,
        operation_id: str,
        step_kind: str,
    ) -> tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent]:
        operation, steps, events = await self._operation_state(operation_id)
        if operation.status not in {"queued", "running"} or any(
            step.status == "running" for step in steps
        ):
            raise StructuredPrototypeGenerationServiceError(
                "generation_evidence_conflict", "operation cannot start another generation step"
            )
        now = self._now()
        ordinal = max((step.step_ordinal for step in steps), default=-1) + 1
        running = replace(
            operation,
            status="running",
            phase=step_kind,
            started_at=operation.started_at or now,
        )
        step = PrototypeOperationStep(
            id=_stable_id(operation.id, "step", str(ordinal)),
            operation_id=operation.id,
            parent_step_id=None,
            step_kind=step_kind,
            step_ordinal=ordinal,
            attempt=1,
            status="running",
            phase=step_kind,
            input_manifest_hash=operation.request_manifest_hash,
            config_manifest_hash=operation.config_manifest_hash,
            output_manifest_hash=None,
            completion_evidence_kind=None,
            completion_evidence_ref=None,
            error_code=None,
            started_at=now,
            completed_at=None,
        )
        return running, step, self._step_event(running, step, len(events), "step_started")

    def _complete_pending_step(
        self,
        running_transition: tuple[
            PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent
        ],
        *,
        output_hash: str,
        evidence_kind: str,
        evidence_ref: str,
    ) -> tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent]:
        running, running_step, running_event = running_transition
        now = self._now()
        completed = replace(
            running,
            status="succeeded",
            result_manifest_hash=output_hash,
            completed_at=now,
        )
        completed_step = replace(
            running_step,
            status="succeeded",
            output_manifest_hash=output_hash,
            completion_evidence_kind=evidence_kind,
            completion_evidence_ref=evidence_ref,
            completed_at=now,
        )
        return (
            completed,
            completed_step,
            self._step_event(
                completed,
                completed_step,
                running_event.event_no + 1,
                "step_succeeded",
            ),
        )

    async def _advance_step(
        self,
        operation_id: str,
        *,
        next_step_kind: str,
        output_hash: str,
        evidence_kind: str,
        evidence_ref: str,
    ) -> tuple[
        tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent],
        tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent],
    ]:
        operation, steps, events = await self._operation_state(operation_id)
        active = next((step for step in reversed(steps) if step.status == "running"), None)
        if operation.status != "running" or active is None:
            raise StructuredPrototypeGenerationServiceError(
                "generation_evidence_conflict", "operation has no active generation step"
            )
        now = self._now()
        completed_step = replace(
            active,
            status="succeeded",
            output_manifest_hash=output_hash,
            completion_evidence_kind=evidence_kind,
            completion_evidence_ref=evidence_ref,
            completed_at=now,
        )
        intermediate = replace(operation, phase=active.phase)
        completed_transition = (
            intermediate,
            completed_step,
            self._step_event(intermediate, completed_step, len(events), "step_succeeded"),
        )
        next_step = PrototypeOperationStep(
            id=_stable_id(operation.id, "step", str(active.step_ordinal + 1)),
            operation_id=operation.id,
            parent_step_id=None,
            step_kind=next_step_kind,
            step_ordinal=active.step_ordinal + 1,
            attempt=1,
            status="running",
            phase=next_step_kind,
            input_manifest_hash=output_hash,
            config_manifest_hash=operation.config_manifest_hash,
            output_manifest_hash=None,
            completion_evidence_kind=None,
            completion_evidence_ref=None,
            error_code=None,
            started_at=now,
            completed_at=None,
        )
        advanced = replace(operation, phase=next_step_kind)
        next_transition = (
            advanced,
            next_step,
            self._step_event(advanced, next_step, len(events) + 1, "step_started"),
        )
        return completed_transition, next_transition

    async def _complete_operation(
        self,
        operation_id: str,
        *,
        output_hash: str,
        evidence_kind: str,
        evidence_ref: str,
        result_manifest_hash: str | None = None,
    ) -> tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent]:
        operation, steps, events = await self._operation_state(operation_id)
        active = next((step for step in reversed(steps) if step.status == "running"), None)
        if operation.status != "running" or active is None:
            raise StructuredPrototypeGenerationServiceError(
                "generation_evidence_conflict", "operation has no active generation step"
            )
        now = self._now()
        completed = replace(
            operation,
            status="succeeded",
            result_manifest_hash=result_manifest_hash or output_hash,
            completed_at=now,
        )
        step = replace(
            active,
            status="succeeded",
            output_manifest_hash=output_hash,
            completion_evidence_kind=evidence_kind,
            completion_evidence_ref=evidence_ref,
            completed_at=now,
        )
        return completed, step, self._step_event(completed, step, len(events), "step_succeeded")

    async def _complete_step_keep_running(
        self,
        operation_id: str,
        *,
        output_hash: str,
        evidence_kind: str,
        evidence_ref: str,
    ) -> tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent]:
        operation, steps, events = await self._operation_state(operation_id)
        active = next((step for step in reversed(steps) if step.status == "running"), None)
        if operation.status != "running" or active is None:
            raise StructuredPrototypeGenerationServiceError(
                "generation_evidence_conflict", "operation has no active generation step"
            )
        now = self._now()
        step = replace(
            active,
            status="succeeded",
            output_manifest_hash=output_hash,
            completion_evidence_kind=evidence_kind,
            completion_evidence_ref=evidence_ref,
            completed_at=now,
        )
        return operation, step, self._step_event(operation, step, len(events), "step_succeeded")

    async def _fail_operation(
        self,
        operation_id: str,
        error_code: str,
    ) -> _GenerationFailureArtifact:
        operation, steps, events = await self._operation_state(operation_id)
        now = self._now()
        prior_active = next((step for step in reversed(steps) if step.status == "running"), None)
        if prior_active is None:
            ordinal = max((step.step_ordinal for step in steps), default=-1) + 1
            failure_step = PrototypeOperationStep(
                id=_stable_id(operation.id, "step", str(ordinal)),
                operation_id=operation.id,
                parent_step_id=None,
                step_kind="generation_failed",
                step_ordinal=ordinal,
                attempt=1,
                status="failed",
                phase="failed",
                input_manifest_hash=operation.request_manifest_hash,
                config_manifest_hash=operation.config_manifest_hash,
                output_manifest_hash=None,
                completion_evidence_kind=None,
                completion_evidence_ref=None,
                error_code=error_code,
                started_at=now,
                completed_at=now,
            )
        else:
            failure_step = replace(
                prior_active,
                status="failed",
                phase="failed",
                error_code=error_code,
                completed_at=now,
            )
        payload = {
            "manifestVersion": GENERATION_EVIDENCE_MANIFEST_VERSION,
            "evidenceKind": "generation_operation_failure",
            "operationId": operation.id,
            "operationKind": operation.operation_kind,
            "projectId": operation.project_id,
            "resourceKind": operation.resource_kind,
            "resourceId": operation.resource_id,
            "parentOperationId": operation.parent_operation_id,
            "priorStatus": operation.status,
            "priorPhase": operation.phase,
            "requestManifestHash": operation.request_manifest_hash,
            "configManifestHash": operation.config_manifest_hash,
            "step": {
                "id": failure_step.id,
                "stepKind": failure_step.step_kind,
                "stepOrdinal": failure_step.step_ordinal,
                "attempt": failure_step.attempt,
                "priorStatus": prior_active.status if prior_active is not None else None,
                "priorPhase": prior_active.phase if prior_active is not None else None,
                "inputManifestHash": failure_step.input_manifest_hash,
                "configManifestHash": failure_step.config_manifest_hash,
                "priorOutputManifestHash": failure_step.output_manifest_hash,
                "priorCompletionEvidenceKind": failure_step.completion_evidence_kind,
                "priorCompletionEvidenceRef": failure_step.completion_evidence_ref,
            },
            "errorCode": error_code,
            "failedAt": now.isoformat(),
        }
        try:
            descriptor = await asyncio.to_thread(
                self._object_store.write_json,
                operation.project_id,
                payload,
            )
            canonical_bytes = await asyncio.to_thread(
                self._object_store.read_canonical_bytes,
                descriptor,
            )
        except PrototypeObjectStoreError as exc:
            raise StructuredPrototypeGenerationServiceError(
                exc.code,
                "generation failure evidence could not be persisted",
            ) from exc
        if parse_json_object(canonical_bytes) != payload:
            raise StructuredPrototypeGenerationServiceError(
                "generation_failure_evidence_corrupt",
                "generation failure evidence changed during durable read-back",
            )
        failure_step = replace(
            failure_step,
            output_manifest_hash=descriptor.content_hash,
            completion_evidence_kind="generation_evidence_manifest",
            completion_evidence_ref=descriptor.content_hash,
        )
        failed = replace(
            operation,
            status="failed",
            phase="failed",
            failure_evidence_hash=descriptor.content_hash,
            error_code=error_code,
            completed_at=now,
        )
        return _GenerationFailureArtifact(
            descriptor=descriptor,
            reference=PrototypeObjectReference(
                project_id=operation.project_id,
                owner_kind="replay_manifest",
                owner_id=operation.id,
                role="operation-failure-evidence",
                content_hash=descriptor.content_hash,
                payload_type="generation_evidence_manifest",
                schema_version=GENERATION_EVIDENCE_MANIFEST_VERSION,
                created_at=now,
            ),
            transition=(
                failed,
                failure_step,
                self._step_event(failed, failure_step, len(events), "step_failed"),
            ),
        )

    async def _record_operation_failure(self, operation_id: str, error_code: str) -> None:
        try:
            failure = await self._fail_operation(operation_id, error_code)
            await self._store.register_generation_failure_evidence_and_transition(
                descriptor=failure.descriptor,
                reference=failure.reference,
                failed_operation=failure.transition[0],
                failed_step=failure.transition[1],
                failed_event=failure.transition[2],
            )
        except (
            StructuredPrototypeGenerationServiceError,
            StructuredPrototypeStoreError,
        ) as exc:
            logger.warning(
                "generation operation failure evidence could not be persisted: %s",
                operation_id,
                exc_info=True,
            )
            raise StructuredPrototypeGenerationServiceError(
                "observability_unavailable",
                "generation operation failure evidence could not be persisted",
            ) from exc

    async def _persist_pre_job_failure(
        self,
        operation_id: str,
        error_code: str,
        *,
        job_id: str,
    ) -> None:
        """Fail the root operation before a generation job row can exist."""
        try:
            failure = await self._fail_operation(operation_id, error_code)
            await self._store.register_generation_failure_evidence_and_transition(
                descriptor=failure.descriptor,
                reference=failure.reference,
                failed_operation=failure.transition[0],
                failed_step=failure.transition[1],
                failed_event=failure.transition[2],
            )
        except (StructuredPrototypeGenerationServiceError, StructuredPrototypeStoreError) as exc:
            raise StructuredPrototypeGenerationServiceError(
                "observability_unavailable",
                "generation failure evidence could not be persisted",
                job_id=job_id,
            ) from exc

    async def _operation_state(
        self,
        operation_id: str,
    ) -> tuple[PrototypeOperation, list[PrototypeOperationStep], list[PrototypeOperationEvent]]:
        operation, steps, events = await asyncio.gather(
            self._store.load_operation(operation_id),
            self._store.list_operation_steps(operation_id),
            self._store.list_operation_events(operation_id),
        )
        if operation is None:
            raise StructuredPrototypeGenerationServiceError(
                "operation_missing", "generation operation does not exist"
            )
        return operation, steps, events

    def _queued_operation(
        self,
        *,
        operation_id: str,
        operation_kind: PrototypeOperationKind,
        project_id: str,
        resource_kind: str,
        resource_id: str,
        client_request_id: str,
        request_hash: str,
        parent_operation_id: str | None,
    ) -> PrototypeOperation:
        return PrototypeOperation(
            id=operation_id,
            operation_kind=operation_kind,
            project_id=project_id,
            resource_kind=resource_kind,
            resource_id=resource_id,
            client_request_id=client_request_id,
            correlation_id=_stable_id(operation_id, "correlation"),
            parent_operation_id=parent_operation_id,
            status="queued",
            phase="queued",
            attempt=1,
            request_manifest_hash=request_hash,
            config_manifest_hash=_manifest_hash(
                {
                    "generationConfigVersion": GENERATION_CONFIG_VERSION,
                    "generationContractVersion": GENERATION_CONTRACT_VERSION,
                    "promptVersion": GENERATION_PROMPT_VERSION,
                    "assemblerVersion": GENERATION_ASSEMBLER_VERSION,
                }
            ),
            result_manifest_hash=None,
            failure_evidence_hash=None,
            error_code=None,
            created_at=self._now(),
            started_at=None,
            completed_at=None,
        )

    def _queued_event(self, operation: PrototypeOperation) -> PrototypeOperationEvent:
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
            occurred_at=operation.created_at,
        )

    def _step_event(
        self,
        operation: PrototypeOperation,
        step: PrototypeOperationStep,
        event_no: int,
        event_kind: str,
    ) -> PrototypeOperationEvent:
        return PrototypeOperationEvent(
            operation_id=operation.id,
            event_no=event_no,
            step_id=step.id,
            event_kind=event_kind,
            status=step.status,
            phase=step.phase,
            input_hash=step.input_manifest_hash,
            output_hash=step.output_manifest_hash,
            evidence_hash=step.output_manifest_hash,
            error_code=step.error_code,
            occurred_at=self._now(),
        )

    def _pending_item(
        self,
        *,
        item_id: str,
        job_id: str,
        run_id: str,
        kind: PrototypeDocumentGenerationItemKind,
        item_key: str,
        page_key: str | None,
        item_ordinal: int,
        operation_id: str,
        context_object_hash: str,
        task_id: str,
        now: datetime,
    ) -> PrototypeDocumentGenerationItemRecord:
        return PrototypeDocumentGenerationItemRecord(
            id=item_id,
            job_id=job_id,
            run_id=run_id,
            kind=kind,
            item_key=item_key,
            page_key=page_key,
            item_ordinal=item_ordinal,
            status="pending",
            phase="queued",
            attempt=1,
            task_kind=f"generation_{kind}",
            operation_id=operation_id,
            context_object_hash=context_object_hash,
            submission_id=None,
            submission_request_hash=None,
            submission_normalized_fields=(),
            submission_accepted_at=None,
            output_object_hash=None,
            task_id=task_id,
            execution_process_id=None,
            error_code=None,
            error_message=None,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )

    def _item_created_evidence_manifest(
        self,
        *,
        item: PrototypeDocumentGenerationItemRecord,
        operation: PrototypeOperation,
        context_object_hash: str,
        created_at: datetime,
    ) -> dict[str, object]:
        return {
            "manifestVersion": GENERATION_EVIDENCE_MANIFEST_VERSION,
            "stepKind": "job_run_item_created",
            "operationId": operation.id,
            "inputHashes": [operation.request_manifest_hash],
            "outputHashes": [context_object_hash],
            "versions": {
                "generationConfigVersion": GENERATION_CONFIG_VERSION,
                "generationContractVersion": GENERATION_CONTRACT_VERSION,
                "promptVersion": GENERATION_PROMPT_VERSION,
            },
            "identities": {
                "jobId": item.job_id,
                "runId": item.run_id,
                "itemId": item.id,
                "itemKey": item.item_key,
                "itemKind": item.kind,
                "taskId": item.task_id,
            },
            "createdAt": created_at.isoformat(),
        }

    def _initial_item_step_transitions(
        self,
        *,
        operation: PrototypeOperation,
        item_created_evidence_hash: str,
        context_object_hash: str,
    ) -> tuple[
        tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent],
        ...,
    ]:
        """Create the immutable item-create/context-freeze evidence chain before dispatch."""
        now = self._now()
        created_step = PrototypeOperationStep(
            id=_stable_id(operation.id, "step", "0"),
            operation_id=operation.id,
            parent_step_id=None,
            step_kind="job_run_item_created",
            step_ordinal=0,
            attempt=1,
            status="running",
            phase="job_run_item_created",
            input_manifest_hash=operation.request_manifest_hash,
            config_manifest_hash=operation.config_manifest_hash,
            output_manifest_hash=None,
            completion_evidence_kind=None,
            completion_evidence_ref=None,
            error_code=None,
            started_at=now,
            completed_at=None,
        )
        created_running = replace(
            operation,
            status="running",
            phase=created_step.step_kind,
            started_at=operation.started_at or now,
        )
        created_started = (
            created_running,
            created_step,
            self._step_event(created_running, created_step, 1, "step_started"),
        )
        created_completed_step = replace(
            created_step,
            status="succeeded",
            output_manifest_hash=item_created_evidence_hash,
            completion_evidence_kind="generation_evidence_manifest",
            completion_evidence_ref=item_created_evidence_hash,
            completed_at=now,
        )
        created_completed = (
            created_running,
            created_completed_step,
            self._step_event(created_running, created_completed_step, 2, "step_succeeded"),
        )
        context_step = PrototypeOperationStep(
            id=_stable_id(operation.id, "step", "1"),
            operation_id=operation.id,
            parent_step_id=None,
            step_kind="context_freeze",
            step_ordinal=1,
            attempt=1,
            status="running",
            phase="context_freeze",
            input_manifest_hash=item_created_evidence_hash,
            config_manifest_hash=operation.config_manifest_hash,
            output_manifest_hash=None,
            completion_evidence_kind=None,
            completion_evidence_ref=None,
            error_code=None,
            started_at=now,
            completed_at=None,
        )
        context_running_operation = replace(created_running, phase=context_step.step_kind)
        context_started = (
            context_running_operation,
            context_step,
            self._step_event(context_running_operation, context_step, 3, "step_started"),
        )
        context_completed_step = replace(
            context_step,
            status="succeeded",
            output_manifest_hash=context_object_hash,
            completion_evidence_kind="generation_context_manifest",
            completion_evidence_ref=context_object_hash,
            completed_at=now,
        )
        context_completed = (
            context_running_operation,
            context_completed_step,
            self._step_event(
                context_running_operation, context_completed_step, 4, "step_succeeded"
            ),
        )
        governance_step = PrototypeOperationStep(
            id=_stable_id(operation.id, "step", "2"),
            operation_id=operation.id,
            parent_step_id=None,
            step_kind="governance_decision",
            step_ordinal=2,
            attempt=1,
            status="running",
            phase="governance_decision",
            input_manifest_hash=context_object_hash,
            config_manifest_hash=operation.config_manifest_hash,
            output_manifest_hash=None,
            completion_evidence_kind=None,
            completion_evidence_ref=None,
            error_code=None,
            started_at=now,
            completed_at=None,
        )
        governance_running = replace(context_running_operation, phase=governance_step.step_kind)
        governance_started = (
            governance_running,
            governance_step,
            self._step_event(governance_running, governance_step, 5, "step_started"),
        )
        return (
            created_started,
            created_completed,
            context_started,
            context_completed,
            governance_started,
        )

    def _reference(
        self,
        job: PrototypeDocumentGenerationJobRecord,
        descriptor: PrototypeObjectDescriptor,
        *,
        owner_kind: PrototypeObjectOwnerKind,
        owner_id: str,
        role: str,
        payload_type: PrototypeObjectPayloadType,
    ) -> PrototypeObjectReference:
        return PrototypeObjectReference(
            project_id=job.project_id,
            owner_kind=owner_kind,
            owner_id=owner_id,
            role=role,
            content_hash=descriptor.content_hash,
            payload_type=payload_type,
            schema_version=1,
            created_at=self._now(),
        )

    @staticmethod
    def _renderer_input_manifest(
        identity: PrototypeRendererWorkerIdentity,
        *,
        document_object_hash: str,
        output_locale: str,
    ) -> dict[str, object]:
        return {
            "rendererVersion": identity.renderer_version,
            "rendererEnvironmentVersion": identity.renderer_environment_version,
            "runtimeCoreVersion": identity.runtime_core_version,
            "runtimeCoreSourceHash": identity.runtime_core_source_hash,
            "runtimeCoreBundleHash": identity.runtime_core_bundle_hash,
            "stateMachineKernelVersion": identity.state_machine_kernel_version,
            "renderRuntimeImageHash": identity.render_runtime_image_hash,
            "browserVersion": identity.browser_version,
            "fontPackHash": identity.font_pack_hash,
            "viewportProfileHash": identity.viewport_profile_hash,
            "documentObjectHash": document_object_hash,
            "documentSchemaVersion": DOCUMENT_SCHEMA_VERSION,
            "assetObjectHashes": [],
            "sandboxPolicyVersion": identity.sandbox_policy_version,
            "outputLocale": output_locale,
        }

    @staticmethod
    def _candidate_document_id(job_id: str) -> str:
        return generation_document_id(job_id)

    def _now(self) -> datetime:
        now = self._clock()
        if now.utcoffset() is None:
            raise StructuredPrototypeGenerationServiceError(
                "clock_invalid", "generation clock must return a timezone-aware datetime"
            )
        return now
