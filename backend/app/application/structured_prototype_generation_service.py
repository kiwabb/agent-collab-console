from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable, Coroutine
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID, uuid5

from app.adapters.prototype_object_store import (
    PrototypeObjectStoreError,
    canonical_json_bytes,
)
from app.adapters.prototype_render_artifact_store import PrototypeRenderArtifactStoreError
from app.adapters.prototype_renderer_worker import PrototypeRendererWorkerError
from app.adapters.prototype_runtime_worker import PrototypeRuntimeWorkerError
from app.adapters.structured_prototype_store import StructuredPrototypeStoreError
from app.application.structured_prototype_contracts import (
    COMMAND_CONTRACT_VERSION,
    DOCUMENT_SCHEMA_VERSION,
    PrototypeDocumentV1,
    document_hash,
    document_payload,
    parse_prototype_document_json,
)
from app.application.structured_prototype_generation_assembler import (
    PROCUREMENT_ASSEMBLER_VERSION,
    PROCUREMENT_ENTITY_INTENTS,
    PROCUREMENT_ENTITY_NAMESPACE,
    PROCUREMENT_FLOW_INTENTS,
    PROCUREMENT_FORM_INTENTS,
    PROCUREMENT_PAGE_ROUTES,
    PROCUREMENT_REQUEST_TABLE_COLUMN_KEYS,
    PROCUREMENT_REQUIRED_COLOR_TOKEN_KEYS,
    PROCUREMENT_REQUIRED_NODE_TYPES,
    PROCUREMENT_REQUIRED_SPACING_TOKEN_KEYS,
    PROCUREMENT_ROLE_INTENTS,
    PROCUREMENT_ROOT_LOCAL_KEYS,
    PROCUREMENT_SCENARIO_INTENTS,
    PROCUREMENT_START_PAGE_KEYS,
    StructuredPrototypeGenerationAssemblyError,
    assemble_procurement_candidate,
    procurement_page_skeleton,
    validate_procurement_blueprint,
    validate_procurement_foundation,
)
from app.application.structured_prototype_generation_contracts import (
    GENERATION_CONTRACT_VERSION,
    GeneratedPageV1,
    GenerationBlueprintEnvelopeV1,
    GenerationBlueprintV1,
    GenerationFoundationEnvelopeV1,
    GenerationFoundationV1,
    GenerationPageEnvelopeV1,
)
from app.application.structured_prototype_generation_runtime import (
    GENERATION_PROMPT_VERSION,
    StructuredPrototypeGenerationRuntimeError,
    StructuredPrototypeGenerationTaskRequest,
    StructuredPrototypeGenerationTaskResult,
)
from app.domain.models import Project
from app.domain.structured_prototype import (
    PrototypeCheckpointRecord,
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
    PrototypeRuntimeWorkerIdentity,
    PrototypeRuntimeWorkerReplayResult,
    PrototypeRuntimeWorkerStateResult,
)
from app.domain.structured_prototype_generation import (
    PrototypeDocumentGenerationAcceptResult,
    PrototypeDocumentGenerationCreateResult,
    PrototypeDocumentGenerationItemKind,
    PrototypeDocumentGenerationItemRecord,
    PrototypeDocumentGenerationJobRecord,
    PrototypeDocumentGenerationRunCreateResult,
    PrototypeDocumentGenerationRunRecord,
    PrototypeDocumentGenerationSnapshot,
)
from app.json_safety import object_dict_or_none, parse_json_object

logger = logging.getLogger(__name__)

GENERATION_SERVICE_NAMESPACE = UUID("cd941172-9105-5806-b528-938dd18c5662")
GENERATION_CONFIG_VERSION = "structured-prototype-generation-service/v1"
GENERATION_REPLAY_MANIFEST_VERSION = 1


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

    async def create_generation_job(
        self,
        *,
        job_operation: PrototypeOperation,
        job_event: PrototypeOperationEvent,
        item_operation: PrototypeOperation,
        item_event: PrototypeOperationEvent,
        job: PrototypeDocumentGenerationJobRecord,
        run: PrototypeDocumentGenerationRunRecord,
        item: PrototypeDocumentGenerationItemRecord,
        descriptors_and_references: tuple[
            tuple[PrototypeObjectDescriptor, PrototypeObjectReference], ...
        ],
    ) -> PrototypeDocumentGenerationCreateResult: ...

    async def create_generation_run(
        self,
        *,
        operation: PrototypeOperation,
        initial_event: PrototypeOperationEvent,
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
        descriptors_and_references: tuple[
            tuple[PrototypeObjectDescriptor, PrototypeObjectReference], ...
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
        replay_descriptor: PrototypeObjectDescriptor,
        replay_references: tuple[PrototypeObjectReference, ...],
        job: PrototypeDocumentGenerationJobRecord,
        document: PrototypeDocumentRecord,
        draft: PrototypeDraftRecord,
        checkpoint: PrototypeCheckpointRecord,
        completed_transition: tuple[
            PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent
        ],
        job_completion_transition: tuple[
            PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent
        ],
    ) -> PrototypeDocumentGenerationAcceptResult: ...

    async def interrupt_active_generation_jobs(self, interrupted_at: datetime) -> int: ...


class GenerationProjectStore(Protocol):
    async def load_project(self, project_id: str) -> Project | None: ...


class GenerationObjectStorage(Protocol):
    def write_json(self, project_id: str, value: object) -> PrototypeObjectDescriptor: ...

    def read_canonical_bytes(self, descriptor: PrototypeObjectDescriptor) -> bytes: ...


class GenerationRuntimeExecution(Protocol):
    async def execute(
        self,
        request: StructuredPrototypeGenerationTaskRequest,
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


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _stable_id(*parts: str) -> str:
    return str(uuid5(GENERATION_SERVICE_NAMESPACE, "\x1f".join(parts)))


def _manifest_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


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
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._store = store
        self._project_store = project_store
        self._object_store = object_store
        self._runtime = runtime
        self._runtime_worker = runtime_worker
        self._renderer = renderer
        self._artifact_store = artifact_store
        self._clock = clock
        self._tasks: dict[str, asyncio.Task[None]] = {}

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
        project = await self._project_store.load_project(project_id)
        if project is None:
            raise StructuredPrototypeGenerationServiceError(
                "project_missing", "project does not exist"
            )
        request_payload = {
            "contractVersion": 1,
            "mode": "requirements",
            "projectId": project_id,
            "brief": normalized_brief,
        }
        context_payload = {
            "contractVersion": 1,
            "taskKind": "generation_blueprint",
            "projectId": project_id,
            "brief": normalized_brief,
            "mvp": {
                "pages": ["purchase-list", "purchase-create", "purchase-detail"],
                "roles": ["applicant", "manager"],
                "entity": "purchase-request",
                "scenario": "purchase-approval-happy-path",
            },
            "requiredBlueprintContract": {
                "pages": [
                    {
                        "pageKey": page_key,
                        "route": route,
                    }
                    for page_key, route in PROCUREMENT_PAGE_ROUTES
                ],
                "navigation": [
                    {"key": page_key, "targetPageKey": page_key}
                    for page_key, _ in PROCUREMENT_PAGE_ROUTES
                ],
                "flowIntents": [
                    {
                        "key": key,
                        "sourcePageKey": source_page_key,
                        "sourceNodeKey": source_node_key,
                        "event": event,
                        "targetPageKey": target_page_key,
                    }
                    for (
                        key,
                        source_page_key,
                        source_node_key,
                        event,
                        target_page_key,
                    ) in PROCUREMENT_FLOW_INTENTS
                ],
                "roleIntents": list(PROCUREMENT_ROLE_INTENTS),
                "entityIntents": list(PROCUREMENT_ENTITY_INTENTS),
                "formIntents": list(PROCUREMENT_FORM_INTENTS),
                "scenarioIntents": list(PROCUREMENT_SCENARIO_INTENTS),
                "startPageKeys": list(PROCUREMENT_START_PAGE_KEYS),
            },
        }
        request_descriptor = await asyncio.to_thread(
            self._object_store.write_json,
            project_id,
            request_payload,
        )
        context_descriptor = await asyncio.to_thread(
            self._object_store.write_json,
            project_id,
            context_payload,
        )
        now = self._now()
        job_id = _stable_id(project_id, client_request_id, "generation-job")
        run_id = _stable_id(job_id, "blueprint-run", "1")
        item_id = _stable_id(run_id, "blueprint")
        job_operation = self._queued_operation(
            operation_id=_stable_id(job_id, "operation"),
            operation_kind="generation_job",
            project_id=project_id,
            resource_kind="generation_job",
            resource_id=job_id,
            client_request_id=client_request_id,
            request_hash=request_descriptor.content_hash,
            parent_operation_id=None,
        )
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
            request_manifest_object_hash=request_descriptor.content_hash,
            request_hash=request_descriptor.content_hash,
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
            operation_id=item_operation.id,
            context_object_hash=context_descriptor.content_hash,
            task_id=_stable_id(item_id, "claude-task"),
            now=now,
        )
        try:
            created = await self._store.create_generation_job(
                job_operation=job_operation,
                job_event=self._queued_event(job_operation),
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
                ),
            )
        except StructuredPrototypeStoreError as exc:
            raise StructuredPrototypeGenerationServiceError(exc.code, str(exc)) from exc
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
        return await self._store.interrupt_active_generation_jobs(self._now())

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
        expected_blueprint_hash: str,
    ) -> PrototypeDocumentGenerationSnapshot:
        _require_uuid(client_request_id, "client_request_id_invalid")
        snapshot = await self.get_job(job_id)
        job = snapshot.job
        if job.status != "awaiting_confirmation" or job.blueprint_hash is None:
            raise StructuredPrototypeGenerationServiceError(
                "generation_job_conflict", "generation blueprint is not awaiting confirmation"
            )
        if job.blueprint_hash != expected_blueprint_hash:
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
            "contractVersion": 1,
            "taskKind": "generation_foundation",
            "projectId": job.project_id,
            "blueprint": blueprint.model_dump(mode="json", by_alias=True),
            "requiredComponentTypes": ["Stack", "Form", "Text", "Input", "Button", "Table"],
            "requiredTokenKeys": {
                "colors": list(PROCUREMENT_REQUIRED_COLOR_TOKEN_KEYS),
                "spacing": list(PROCUREMENT_REQUIRED_SPACING_TOKEN_KEYS),
            },
        }
        context_descriptor = await asyncio.to_thread(
            self._object_store.write_json,
            job.project_id,
            foundation_context,
        )
        now = self._now()
        run_id = _stable_id(job.id, client_request_id, "foundation-run")
        item_id = _stable_id(run_id, "foundation")
        operation = self._queued_operation(
            operation_id=_stable_id(run_id, "schedule-operation"),
            operation_kind="generation_job",
            project_id=job.project_id,
            resource_kind="generation_job",
            resource_id=job.id,
            client_request_id=client_request_id,
            request_hash=job.blueprint_hash,
            parent_operation_id=job.operation_id,
        )
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
            operation_id=item_operation.id,
            context_object_hash=context_descriptor.content_hash,
            task_id=_stable_id(item_id, "claude-task"),
            now=now,
        )
        try:
            created = await self._store.create_generation_run(
                operation=operation,
                initial_event=self._queued_event(operation),
                job=generating_job,
                run=run,
                item_operations=((item, item_operation, self._queued_event(item_operation)),),
                expected_job_statuses=("awaiting_confirmation",),
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
                ),
            )
        except StructuredPrototypeStoreError as exc:
            raise StructuredPrototypeGenerationServiceError(
                exc.code, str(exc), job_id=job.id
            ) from exc
        if created.created:
            self._schedule(
                job.id,
                self._run_generation(job.id, project, foundation_context, operation.id),
            )
        return created.snapshot

    async def read_preview_file(self, job_id: str, relative_path: str) -> bytes:
        job = (await self.get_job(job_id)).job
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
        descriptor = PrototypeRenderBundleDescriptor(
            project_id=job.project_id,
            document_id=preview_document_id,
            artifact_id=job.preview_artifact_id,
            storage_key=job.preview_storage_key,
            entrypoint="index.html",
            output_hash=job.preview_output_hash,
            output_manifest_hash=job.preview_output_manifest_hash,
            visual_preflight_report_hash=job.preview_visual_preflight_report_hash,
            file_count=3,
        )
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

    async def accept_candidate(
        self,
        *,
        job_id: str,
        client_request_id: str,
        expected_candidate_object_hash: str,
        expected_preview_output_hash: str,
    ) -> PrototypeDocumentGenerationAcceptResult:
        _require_uuid(client_request_id, "client_request_id_invalid")
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
        ):
            raise StructuredPrototypeGenerationServiceError(
                "generation_candidate_conflict",
                "generation candidate or preview changed before accept",
                job_id=job.id,
            )
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
        operation = self._queued_operation(
            operation_id=_stable_id(job.id, client_request_id, "accept-operation"),
            operation_kind="create_document",
            project_id=job.project_id,
            resource_kind="document",
            resource_id=document.id,
            client_request_id=client_request_id,
            request_hash=_manifest_hash(
                {
                    "jobId": job.id,
                    "candidateObjectHash": expected_candidate_object_hash,
                    "previewOutputHash": expected_preview_output_hash,
                }
            ),
            parent_operation_id=job.operation_id,
        )
        try:
            created = await self._store.create_operation(operation, self._queued_event(operation))
            if not created.created:
                raise StructuredPrototypeGenerationServiceError(
                    "generation_accept_conflict",
                    "generation accept request already exists",
                    job_id=job.id,
                )
            accept_running = await self._start_step(operation.id, "accept_candidate")
            await self._store.record_operation_transition(*accept_running)
            if snapshot.latest_run is None:
                raise StructuredPrototypeGenerationServiceError(
                    "generation_run_missing",
                    "generation candidate has no completed run",
                    job_id=job.id,
                )
            root_running = await self._start_step(job.operation_id, "accept_candidate")
            await self._store.transition_generation_records(
                job=job,
                run=snapshot.latest_run,
                items=snapshot.items,
                expected_job_statuses=("ready",),
                expected_run_statuses=("completed",),
                expected_item_statuses=("done",),
                operation_transitions=(root_running,),
            )
            replay_manifest = {
                "manifestVersion": GENERATION_REPLAY_MANIFEST_VERSION,
                "kind": "generation_accept",
                "jobId": job.id,
                "acceptOperationId": operation.id,
                "generationOperationId": job.operation_id,
                "candidateObjectHash": expected_candidate_object_hash,
                "previewOutputHash": expected_preview_output_hash,
                "documentId": document.id,
            }
            replay_descriptor = await asyncio.to_thread(
                self._object_store.write_json,
                job.project_id,
                replay_manifest,
            )
            now = self._now()
            draft_id = _stable_id(operation.id, "draft")
            checkpoint_id = _stable_id(operation.id, "checkpoint", "0")
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
                created_by_operation_id=operation.id,
                created_at=now,
            )
            accept_completed = await self._complete_operation(
                operation.id,
                output_hash=replay_descriptor.content_hash,
                evidence_kind="checkpoint",
                evidence_ref=checkpoint.id,
            )
            root_completed = await self._complete_operation(
                job.operation_id,
                output_hash=replay_descriptor.content_hash,
                evidence_kind="replay_manifest",
                evidence_ref=replay_descriptor.content_hash,
            )
            accepted_job = replace(
                job,
                status="accepted",
                replay_manifest_object_hash=replay_descriptor.content_hash,
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
            replay_references = tuple(
                self._reference(
                    job,
                    replay_descriptor,
                    owner_kind="replay_manifest",
                    owner_id=owner_id,
                    role=role,
                    payload_type="replay_manifest",
                )
                for owner_id, role in (
                    (operation.id, "generation-accept"),
                    (job.operation_id, "generation-complete"),
                )
            )
            return await self._store.accept_generation_candidate(
                descriptor=candidate_descriptor,
                checkpoint_reference=checkpoint_reference,
                replay_descriptor=replay_descriptor,
                replay_references=replay_references,
                job=accepted_job,
                document=document_record,
                draft=draft,
                checkpoint=checkpoint,
                completed_transition=accept_completed,
                job_completion_transition=root_completed,
            )
        except (PrototypeObjectStoreError, StructuredPrototypeStoreError) as exc:
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
            run = snapshot.latest_run
            item = snapshot.items[0]
            now = self._now()
            start_transitions = (
                await self._start_step(job.operation_id, "blueprint_planning"),
                await self._start_step(item.operation_id, "claude_generation"),
            )
            job = replace(job, status="planning", updated_at=now)
            run = replace(
                run,
                status="running",
                running=1,
                pending=0,
                started_at=now,
                updated_at=now,
            )
            item = replace(item, status="generating", phase="claude_generation", updated_at=now)
            await self._store.transition_generation_records(
                job=job,
                run=run,
                items=(item,),
                expected_job_statuses=("queued",),
                expected_run_statuses=("queued",),
                expected_item_statuses=("pending",),
                operation_transitions=start_transitions,
            )
            result = await self._runtime.execute(
                StructuredPrototypeGenerationTaskRequest(
                    project=project,
                    operation_id=item.operation_id,
                    job_id=job.id,
                    run_id=run.id,
                    item_id=item.id,
                    task_id=cast(str, item.task_id),
                    task_kind="generation_blueprint",
                    context_object_hash=item.context_object_hash,
                    frozen_context=context,
                )
            )
            envelope = result.envelope
            if not isinstance(envelope, GenerationBlueprintEnvelopeV1):
                raise StructuredPrototypeGenerationServiceError(
                    "generation_contract_mismatch", "Claude returned the wrong blueprint contract"
                )
            item = await self._mark_item_validating(job, run, item, result, "generation_blueprint")
            validate_procurement_blueprint(envelope.payload)
            now = self._now()
            item_transition = await self._complete_operation(
                item.operation_id,
                output_hash=result.artifact_descriptor.content_hash,
                evidence_kind="generation_blueprint",
                evidence_ref=result.artifact_descriptor.content_hash,
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
                updated_at=now,
                completed_at=now,
            )
            done_item = replace(item, status="done", phase="done", updated_at=now, completed_at=now)
            await self._store.transition_generation_records(
                job=ready_job,
                run=completed_run,
                items=(done_item,),
                expected_job_statuses=("planning",),
                expected_run_statuses=("running",),
                expected_item_statuses=("validating",),
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
        try:
            snapshot = await self.get_job(job_id)
            assert snapshot.latest_run is not None and len(snapshot.items) == 1
            job = snapshot.job
            run = snapshot.latest_run
            item = snapshot.items[0]
            now = self._now()
            transitions = (
                await self._start_step(phase_operation_id, "generate_foundation"),
                await self._start_step(item.operation_id, "claude_generation"),
            )
            run = replace(
                run,
                status="running",
                running=1,
                pending=0,
                started_at=now,
                updated_at=now,
            )
            item = replace(item, status="generating", phase="claude_generation", updated_at=now)
            await self._store.transition_generation_records(
                job=job,
                run=run,
                items=(item,),
                expected_job_statuses=("generating",),
                expected_run_statuses=("queued",),
                expected_item_statuses=("pending",),
                operation_transitions=transitions,
            )
            result = await self._runtime.execute(
                StructuredPrototypeGenerationTaskRequest(
                    project=project,
                    operation_id=item.operation_id,
                    job_id=job.id,
                    run_id=run.id,
                    item_id=item.id,
                    task_id=cast(str, item.task_id),
                    task_kind="generation_foundation",
                    context_object_hash=item.context_object_hash,
                    frozen_context=foundation_context,
                )
            )
            envelope = result.envelope
            if not isinstance(envelope, GenerationFoundationEnvelopeV1):
                raise StructuredPrototypeGenerationServiceError(
                    "generation_contract_mismatch", "Claude returned the wrong foundation contract"
                )
            item = await self._mark_item_validating(job, run, item, result, "generation_foundation")
            validate_procurement_foundation(envelope.payload)
            now = self._now()
            completed_item_transition = await self._complete_operation(
                item.operation_id,
                output_hash=result.artifact_descriptor.content_hash,
                evidence_kind="generation_foundation",
                evidence_ref=result.artifact_descriptor.content_hash,
            )
            completed_phase_transition = await self._complete_operation(
                phase_operation_id,
                output_hash=result.artifact_descriptor.content_hash,
                evidence_kind="generation_foundation",
                evidence_ref=result.artifact_descriptor.content_hash,
            )
            done_item = replace(item, status="done", phase="done", updated_at=now, completed_at=now)
            completed_run = replace(
                run,
                status="completed",
                processed=1,
                succeeded=1,
                running=0,
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
                operation_transitions=(completed_item_transition, completed_phase_transition),
            )
            page_snapshot, page_contexts, page_phase_operation_id = await self._create_page_run(
                job,
                envelope.payload,
            )
            pages = await self._run_pages(
                project,
                page_snapshot,
                page_contexts,
                page_phase_operation_id,
            )
            await self._assemble_validate_render(
                project,
                page_snapshot.job,
                envelope.payload,
                pages,
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
            await self._mark_failed(job_id, exc.code, str(exc))

    async def _create_page_run(
        self,
        job: PrototypeDocumentGenerationJobRecord,
        foundation: GenerationFoundationV1,
    ) -> tuple[PrototypeDocumentGenerationSnapshot, dict[str, dict[str, object]], str]:
        blueprint = await self._load_blueprint(job)
        page_contexts: dict[str, dict[str, object]] = {}
        context_descriptors: dict[str, PrototypeObjectDescriptor] = {}
        for page in blueprint.pages:
            context = {
                "contractVersion": 1,
                "taskKind": "generation_page",
                "projectId": job.project_id,
                "page": page.model_dump(mode="json", by_alias=True),
                "foundation": foundation.model_dump(mode="json", by_alias=True),
                "requiredNodes": PROCUREMENT_REQUIRED_NODE_TYPES[page.page_key],
                "requiredRootNode": {
                    "localKey": PROCUREMENT_ROOT_LOCAL_KEYS[page.page_key],
                    "type": "Stack",
                },
                "allowAdditionalNodes": False,
                "maxTextCharacters": 240,
                "requiredPageSkeleton": procurement_page_skeleton(
                    page.page_key,
                    page.title,
                    page.route,
                ),
                "requiredTableColumns": (
                    list(PROCUREMENT_REQUEST_TABLE_COLUMN_KEYS)
                    if page.page_key == "purchase-list"
                    else []
                ),
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
        for page_key in ("purchase-list", "purchase-create", "purchase-detail"):
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
                operation_id=item_operation.id,
                context_object_hash=descriptor.content_hash,
                task_id=_stable_id(item_id, "claude-task"),
                now=now,
            )
            item_operations.append((item, item_operation, self._queued_event(item_operation)))
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
        run = PrototypeDocumentGenerationRunRecord(
            id=run_id,
            job_id=job.id,
            status="queued",
            blueprint_hash=job.blueprint_hash,
            total=3,
            processed=0,
            succeeded=0,
            failed=0,
            running=0,
            pending=3,
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
            descriptors_and_references=tuple(descriptor_references),
        )
        return result.snapshot, page_contexts, phase_operation.id

    async def _run_pages(
        self,
        project: Project,
        snapshot: PrototypeDocumentGenerationSnapshot,
        contexts: dict[str, dict[str, object]],
        phase_operation_id: str,
    ) -> tuple[GeneratedPageV1, ...]:
        assert snapshot.latest_run is not None
        job = snapshot.job
        run = snapshot.latest_run
        items = list(snapshot.items)
        pages: list[GeneratedPageV1] = []
        phase_started = False
        for index, item in enumerate(items):
            now = self._now()
            operation_transitions = [await self._start_step(item.operation_id, "claude_generation")]
            if not phase_started:
                operation_transitions.insert(
                    0,
                    await self._start_step(phase_operation_id, "generate_pages"),
                )
                phase_started = True
            items[index] = replace(
                item,
                status="generating",
                phase="claude_generation",
                updated_at=now,
            )
            run = replace(
                run,
                status="running",
                processed=index,
                succeeded=index,
                running=1,
                pending=len(items) - index - 1,
                started_at=run.started_at or now,
                updated_at=now,
            )
            await self._store.transition_generation_records(
                job=job,
                run=run,
                items=tuple(items),
                expected_job_statuses=("generating",),
                expected_run_statuses=("queued", "running"),
                expected_item_statuses=("pending", "done"),
                operation_transitions=tuple(operation_transitions),
            )
            result = await self._runtime.execute(
                StructuredPrototypeGenerationTaskRequest(
                    project=project,
                    operation_id=item.operation_id,
                    job_id=job.id,
                    run_id=run.id,
                    item_id=item.id,
                    task_id=cast(str, item.task_id),
                    task_kind="generation_page",
                    context_object_hash=item.context_object_hash,
                    frozen_context=contexts[item.item_key],
                )
            )
            envelope = result.envelope
            if not isinstance(envelope, GenerationPageEnvelopeV1):
                raise StructuredPrototypeGenerationServiceError(
                    "generation_contract_mismatch", "Claude returned the wrong page contract"
                )
            validating_item = await self._mark_item_validating(
                job,
                run,
                items[index],
                result,
                "generation_page",
                all_items=tuple(items),
            )
            if envelope.payload.page_key != item.page_key:
                raise StructuredPrototypeGenerationServiceError(
                    "generation_semantic_invalid", "Claude page key does not match its run item"
                )
            pages.append(envelope.payload)
            now = self._now()
            items[index] = replace(
                validating_item,
                status="done",
                phase="done",
                updated_at=now,
                completed_at=now,
            )
            last = index == len(items) - 1
            transitions = [
                await self._complete_operation(
                    item.operation_id,
                    output_hash=result.artifact_descriptor.content_hash,
                    evidence_kind="generation_page",
                    evidence_ref=result.artifact_descriptor.content_hash,
                )
            ]
            if last:
                transitions.append(
                    await self._complete_operation(
                        phase_operation_id,
                        output_hash=_manifest_hash([page.page_key for page in pages]),
                        evidence_kind="generation_pages",
                        evidence_ref=run.id,
                    )
                )
                transitions.append(await self._start_step(job.operation_id, "assemble_candidate"))
            run = replace(
                run,
                status="completed" if last else "running",
                processed=index + 1,
                succeeded=index + 1,
                running=0,
                pending=len(items) - index - 1,
                updated_at=now,
                completed_at=now if last else None,
            )
            job = replace(job, status="assembling" if last else "generating", updated_at=now)
            await self._store.transition_generation_records(
                job=job,
                run=run,
                items=tuple(items),
                expected_job_statuses=("generating",),
                expected_run_statuses=("running",),
                expected_item_statuses=("done", "validating", "pending"),
                operation_transitions=tuple(transitions),
            )
        return tuple(pages)

    async def _assemble_validate_render(
        self,
        project: Project,
        job: PrototypeDocumentGenerationJobRecord,
        foundation: GenerationFoundationV1,
        pages: tuple[GeneratedPageV1, ...],
    ) -> None:
        snapshot = await self.get_job(job.id)
        assert snapshot.latest_run is not None
        job = snapshot.job
        run = snapshot.latest_run
        items = snapshot.items
        blueprint = await self._load_blueprint(job)
        document_id = self._candidate_document_id(job.id)
        document = assemble_procurement_candidate(
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
        runtime_replay = await self._validate_runtime(job, document)
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
        replay_manifest = {
            "manifestVersion": GENERATION_REPLAY_MANIFEST_VERSION,
            "jobId": job.id,
            "operationId": job.operation_id,
            "generationContractVersion": GENERATION_CONTRACT_VERSION,
            "generationPromptVersion": GENERATION_PROMPT_VERSION,
            "assemblerVersion": PROCUREMENT_ASSEMBLER_VERSION,
            "blueprintObjectHash": job.blueprint_object_hash,
            "orderedItemObjectHashes": [item.output_object_hash for item in items],
            "submissionNormalizations": [
                {
                    "itemId": item.id,
                    "requestHash": item.submission_request_hash,
                    "normalizedFields": list(item.submission_normalized_fields),
                }
                for item in items
            ],
            "candidateObjectHash": candidate_hash,
            "runtimeCoreVersion": self._runtime_worker.identity.runtime_core_version,
            "runtimeFinalStateHash": runtime_replay.final.state_hash,
            "runtimeFinalViewModelHash": runtime_replay.final.view_model_hash,
            "rendererVersion": self._renderer.identity.renderer_version,
            "previewOutputHash": bundle.output_hash,
            "previewOutputManifestHash": bundle.output_manifest_hash,
        }
        replay_descriptor = await asyncio.to_thread(
            self._object_store.write_json,
            job.project_id,
            replay_manifest,
        )
        completion_transition = await self._complete_step_keep_running(
            job.operation_id,
            output_hash=replay_descriptor.content_hash,
            evidence_kind="replay_manifest",
            evidence_ref=replay_descriptor.content_hash,
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
            replay_manifest_object_hash=replay_descriptor.content_hash,
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
                    replay_descriptor,
                    self._reference(
                        job,
                        replay_descriptor,
                        owner_kind="replay_manifest",
                        owner_id=job.operation_id,
                        role="generation-ready",
                        payload_type="replay_manifest",
                    ),
                ),
            ),
            operation_transitions=(completion_transition,),
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
            next_step_kind="validate_artifact",
            output_hash=result.artifact_descriptor.content_hash,
            evidence_kind="agent_submission",
            evidence_ref=result.submission.submission_id,
        )
        now = self._now()
        validating = replace(
            item,
            status="validating",
            phase="validate_artifact",
            submission_id=result.submission.submission_id,
            submission_request_hash=result.submission.request_hash,
            submission_normalized_fields=result.submission.normalized_fields,
            submission_accepted_at=datetime.fromtimestamp(
                result.submission.accepted_at,
                tz=UTC,
            ),
            output_object_hash=result.artifact_descriptor.content_hash,
            execution_process_id=result.execution_process_id,
            updated_at=now,
        )
        items = list(all_items or (item,))
        item_index = next(index for index, candidate in enumerate(items) if candidate.id == item.id)
        items[item_index] = validating
        running_count = sum(candidate.status in {"generating", "validating"} for candidate in items)
        pending_count = sum(candidate.status == "pending" for candidate in items)
        succeeded_count = sum(candidate.status == "done" for candidate in items)
        current_run = replace(
            run,
            processed=succeeded_count,
            succeeded=succeeded_count,
            running=running_count,
            pending=pending_count,
            updated_at=now,
        )
        await self._store.transition_generation_records(
            job=job,
            run=current_run,
            items=tuple(items),
            expected_job_statuses=(job.status,),
            expected_run_statuses=(run.status,),
            expected_item_statuses=("generating", "pending", "done"),
            descriptors_and_references=(
                (
                    result.artifact_descriptor,
                    self._reference(
                        job,
                        result.artifact_descriptor,
                        owner_kind="generation_item",
                        owner_id=item.id,
                        role="validated-submission",
                        payload_type=payload_type,
                    ),
                ),
            ),
            operation_transitions=transitions,
        )
        return validating

    async def _validate_runtime(
        self,
        job: PrototypeDocumentGenerationJobRecord,
        document: PrototypeDocumentV1,
    ) -> PrototypeRuntimeWorkerReplayResult:
        definition = document.runtime.model_dump(mode="json", by_alias=True)
        scenario_id = str(uuid5(PROCUREMENT_ENTITY_NAMESPACE, "scenario-happy-path"))
        initial = await self._runtime_worker.initialize_state(
            request_id=_stable_id(job.id, "runtime-initialize"),
            definition=definition,
            scenario_id=scenario_id,
            session_id=_stable_id(job.id, "runtime-validation-session"),
        )
        event_batches = self._procurement_event_batches()
        replay = await self._runtime_worker.replay_event_batches(
            request_id=_stable_id(job.id, "runtime-replay"),
            definition=definition,
            state_json=initial.state_json,
            batches=event_batches,
        )
        if [transition.outcome for transition in replay.transitions] != [
            "applied",
            "applied",
            "applied",
        ]:
            raise StructuredPrototypeGenerationServiceError(
                "runtime_scenario_failed", "procurement approval scenario did not fully apply"
            )
        final_state = parse_json_object(replay.final.state_json)
        if final_state is None or not self._state_contains_approved_request(final_state):
            raise StructuredPrototypeGenerationServiceError(
                "runtime_scenario_failed", "procurement approval scenario did not reach approved"
            )
        return replay

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
        envelope = GenerationBlueprintEnvelopeV1.model_validate(
            payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )
        validate_procurement_blueprint(envelope.payload)
        return envelope.payload

    async def _mark_failed(self, job_id: str, code: str, message: str) -> None:
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
            transitions: list[
                tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent]
            ] = []
            transitions.append(await self._fail_operation(snapshot.job.operation_id, code))
            for before, after in zip(snapshot.items, items, strict=True):
                if before.status != after.status:
                    transitions.append(await self._fail_operation(before.operation_id, code))
            succeeded = sum(item.status == "done" for item in items)
            failed = sum(item.status in {"failed", "interrupted"} for item in items)
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
                operation_transitions=tuple(transitions),
            )
        except StructuredPrototypeStoreError:
            logger.exception(
                "failed to persist structured prototype generation failure: %s", job_id
            )

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
            result_manifest_hash=output_hash,
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
    ) -> tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent]:
        operation, steps, events = await self._operation_state(operation_id)
        now = self._now()
        active = next((step for step in reversed(steps) if step.status == "running"), None)
        if active is None:
            ordinal = max((step.step_ordinal for step in steps), default=-1) + 1
            active = PrototypeOperationStep(
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
                completion_evidence_kind="error_code",
                completion_evidence_ref=error_code,
                error_code=error_code,
                started_at=now,
                completed_at=now,
            )
        else:
            active = replace(
                active,
                status="failed",
                completion_evidence_kind="error_code",
                completion_evidence_ref=error_code,
                error_code=error_code,
                completed_at=now,
            )
        failed = replace(
            operation,
            status="failed",
            phase="failed",
            failure_evidence_hash=_manifest_hash({"errorCode": error_code}),
            error_code=error_code,
            completed_at=now,
        )
        return failed, active, self._step_event(failed, active, len(events), "step_failed")

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
                    "assemblerVersion": PROCUREMENT_ASSEMBLER_VERSION,
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
        return str(uuid5(PROCUREMENT_ENTITY_NAMESPACE, f"generation-document:{job_id}"))

    @staticmethod
    def _procurement_event_batches() -> list[dict[str, object]]:
        def node(seed: str) -> str:
            return str(uuid5(PROCUREMENT_ENTITY_NAMESPACE, seed))

        return [
            {
                "clientEventId": "submit-request",
                "expectedSequenceNo": 0,
                "events": [
                    {
                        "kind": "fieldValueCommitted",
                        "nodeId": node("input-title"),
                        "formId": node("form-create"),
                        "fieldId": node("form-field-title"),
                        "value": {"type": "string", "value": "研发笔记本电脑"},
                    },
                    {
                        "kind": "fieldValueCommitted",
                        "nodeId": node("input-amount"),
                        "formId": node("form-create"),
                        "fieldId": node("form-field-amount"),
                        "value": {"type": "integer", "value": 12500},
                    },
                    {
                        "kind": "nodeActivated",
                        "nodeId": node("button-submit"),
                        "event": "submit",
                    },
                ],
            },
            {
                "clientEventId": "switch-manager",
                "expectedSequenceNo": 1,
                "events": [{"kind": "switchSimulatedRole", "roleId": node("role-manager")}],
            },
            {
                "clientEventId": "approve-request",
                "expectedSequenceNo": 2,
                "events": [
                    {
                        "kind": "nodeActivated",
                        "nodeId": node("button-approve"),
                        "event": "click",
                    }
                ],
            },
        ]

    @staticmethod
    def _state_contains_approved_request(state: dict[str, object]) -> bool:
        entity_sets = state.get("entitySets")
        if not isinstance(entity_sets, list):
            return False
        status_field_id = str(uuid5(PROCUREMENT_ENTITY_NAMESPACE, "schema-field-status"))
        for entity_set in entity_sets:
            entity_set_record = object_dict_or_none(entity_set)
            if entity_set_record is None:
                continue
            entities = entity_set_record.get("entities")
            if not isinstance(entities, list):
                continue
            for entity in entities:
                entity_record = object_dict_or_none(entity)
                if entity_record is None:
                    continue
                fields = entity_record.get("fields")
                if not isinstance(fields, list):
                    continue
                for field in fields:
                    field_record = object_dict_or_none(field)
                    if field_record is None or field_record.get("fieldId") != status_field_id:
                        continue
                    value = object_dict_or_none(field_record.get("value"))
                    if value == {"type": "enum", "value": "approved"}:
                        return True
        return False

    def _now(self) -> datetime:
        now = self._clock()
        if now.utcoffset() is None:
            raise StructuredPrototypeGenerationServiceError(
                "clock_invalid", "generation clock must return a timezone-aware datetime"
            )
        return now
