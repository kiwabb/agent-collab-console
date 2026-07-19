from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID, uuid5

from app.adapters.prototype_object_store import (
    PrototypeObjectStoreError,
    canonical_json_bytes,
)
from app.adapters.prototype_render_artifact_store import PrototypeRenderArtifactStoreError
from app.adapters.prototype_renderer_worker import PrototypeRendererWorkerError
from app.adapters.structured_prototype_store import StructuredPrototypeStoreError
from app.application.prototype_ui_engineer_runner import PrototypeUiEngineerRunnerError
from app.application.structured_prototype_ai_contracts import (
    AI_EDIT_CONTEXT_CONTRACT_VERSION,
    PrototypeAiSelectionV1,
    PrototypeAssistantAnswerV1,
    PrototypeAssistantClarificationV1,
    PrototypeAssistantCommandProposalV1,
    assistant_outcome_payload,
)
from app.application.structured_prototype_ai_runtime import (
    AI_EDIT_PROMPT_VERSION,
    PrototypeUiEngineerRuntimeError,
    PrototypeUiEngineerTaskRequest,
    PrototypeUiEngineerTaskResult,
)
from app.application.structured_prototype_contracts import (
    COMMAND_CONTRACT_VERSION,
    COMMAND_HISTORY_CHECKPOINT_SCHEMA_VERSION,
    DOCUMENT_SCHEMA_VERSION,
    AddBehaviorRuleCommandV1,
    AddPageCommandV1,
    AllPredicateV1,
    ComparePredicateV1,
    CreateEntityEffectV1,
    DeletePageCommandV1,
    DomainCommandBatchV1,
    DomainCommandV1,
    DuplicatePageCommandV1,
    EntityFieldExpressionV1,
    EntityRefRuntimeValueV1,
    EventEntityRefExpressionV1,
    ExistingNodeRefV1,
    FormFieldExpressionV1,
    FormNodeV1,
    FormValidPredicateV1,
    FreeformNodeV1,
    GridNodeV1,
    InputNodeV1,
    InsertNodeCommandV1,
    LiteralExpressionV1,
    MoveNodeCommandV1,
    NavigateEffectV1,
    NotifyEffectV1,
    PrototypeDocumentV1,
    PrototypeFlowV1,
    PrototypePageV1,
    RemoveBehaviorRuleCommandV1,
    RemoveNodeCommandV1,
    RenamePageCommandV1,
    ReplaceBehaviorRuleCommandV1,
    RoleIsPredicateV1,
    RuntimeEffectV1,
    RuntimeEntitySchemaV1,
    RuntimeEntitySetV1,
    RuntimeExpressionV1,
    RuntimeFormV1,
    RuntimePredicateV1,
    RuntimeRoleV1,
    RuntimeRuleDefinitionV1,
    RuntimeRuleV1,
    RuntimeScenarioV1,
    RuntimeValueV1,
    RuntimeVariableV1,
    RuntimeViewBindingV1,
    SetNodeLayoutCommandV1,
    SetNodePropertyCommandV1,
    SetRuntimeEntityFieldCommandV1,
    SetVariableEffectV1,
    StackNodeV1,
    StructuredPrototypeContractError,
    TableRowsViewBindingV1,
    TextViewBindingV1,
    UINodeV1,
    UpdateEntityEffectV1,
    UpdateNodeNameCommandV1,
    ValidateFormEffectV1,
    VariableExpressionV1,
    VisibilityViewBindingV1,
    advance_journal_prefix_hash,
    canonical_model_json,
    command_batch_envelope_hash,
    command_batch_hash,
    document_payload,
    execute_command_batch,
)
from app.application.structured_prototype_service import (
    CORRUPTION_ERROR_CODES,
    PrototypeRenderArtifactStorage,
    PrototypeRendererExecution,
    RecoverStructuredPrototypeResult,
    StructuredPrototypeService,
    StructuredPrototypeServiceError,
)
from app.domain.models import Project
from app.domain.structured_prototype import (
    PrototypeCheckpointRecord,
    PrototypeCommandAppendResult,
    PrototypeCommandBatchRecord,
    PrototypeCommandHistoryCheckpoint,
    PrototypeDocumentRecord,
    PrototypeDraftRecord,
    PrototypeObjectDescriptor,
    PrototypeObjectOwnerKind,
    PrototypeObjectPayloadType,
    PrototypeObjectReference,
    PrototypeOperation,
    PrototypeOperationEvent,
    PrototypeOperationStep,
    PrototypeRenderArtifactRecord,
    PrototypeRenderBundleDescriptor,
    PrototypeRendererWorkerIdentity,
    PrototypeRenderRunRecord,
    PrototypeRenderStatus,
    advance_prototype_command_history,
)
from app.domain.structured_prototype_ai import (
    PrototypeAiEditRunRecord,
    PrototypeAiEditRunStatus,
    PrototypeAiMessageRecord,
    PrototypeAiMessageRunCreateResult,
    PrototypeAiThreadRecord,
    PrototypeAiThreadSnapshot,
)

logger = logging.getLogger(__name__)

AI_SERVICE_NAMESPACE = UUID("d2f72be1-71d7-5819-b14d-321b07dc4bda")
AI_EDIT_CONFIG_VERSION = "structured-prototype-ai/0.1.0"
AI_REPLAY_MANIFEST_VERSION = 1
TERMINAL_AI_RUN_STATUSES = frozenset(
    {
        "completed_answer",
        "completed_clarification",
        "applied",
        "rejected",
        "stale",
        "failed",
        "interrupted",
    }
)


class StructuredPrototypeAiPersistence(Protocol):
    async def load_document(self, document_id: str) -> PrototypeDocumentRecord | None: ...

    async def load_draft(self, draft_id: str) -> PrototypeDraftRecord | None: ...

    async def load_operation(self, operation_id: str) -> PrototypeOperation | None: ...

    async def list_operation_steps(
        self,
        operation_id: str,
    ) -> list[PrototypeOperationStep]: ...

    async def list_operation_events(
        self,
        operation_id: str,
    ) -> list[PrototypeOperationEvent]: ...

    async def load_object(
        self,
        project_id: str,
        content_hash: str,
    ) -> PrototypeObjectDescriptor | None: ...

    async def create_ai_thread(
        self,
        thread: PrototypeAiThreadRecord,
    ) -> PrototypeAiThreadRecord: ...

    async def list_ai_threads(self, document_id: str) -> list[PrototypeAiThreadRecord]: ...

    async def load_ai_thread_snapshot(
        self,
        thread_id: str,
    ) -> PrototypeAiThreadSnapshot | None: ...

    async def load_ai_edit_run(self, run_id: str) -> PrototypeAiEditRunRecord | None: ...

    async def create_ai_message_run(
        self,
        *,
        operation: PrototypeOperation,
        initial_event: PrototypeOperationEvent,
        message: PrototypeAiMessageRecord,
        run: PrototypeAiEditRunRecord,
    ) -> PrototypeAiMessageRunCreateResult: ...

    async def transition_ai_edit_run(
        self,
        *,
        run: PrototypeAiEditRunRecord,
        expected_statuses: tuple[str, ...],
        assistant_message: PrototypeAiMessageRecord | None = None,
        descriptors_and_references: tuple[
            tuple[PrototypeObjectDescriptor, PrototypeObjectReference], ...
        ] = (),
        operation_transitions: tuple[
            tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent], ...
        ] = (),
    ) -> PrototypeAiEditRunRecord: ...

    async def freeze_ai_preview(
        self,
        *,
        run: PrototypeAiEditRunRecord,
        render_run: PrototypeRenderRunRecord,
        descriptors_and_references: tuple[
            tuple[PrototypeObjectDescriptor, PrototypeObjectReference], ...
        ],
        operation_transitions: tuple[
            tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent], ...
        ],
    ) -> None: ...

    async def complete_ai_preview(
        self,
        *,
        run: PrototypeAiEditRunRecord,
        render_run: PrototypeRenderRunRecord,
        artifact: PrototypeRenderArtifactRecord,
        assistant_message: PrototypeAiMessageRecord,
        descriptors_and_references: tuple[
            tuple[PrototypeObjectDescriptor, PrototypeObjectReference], ...
        ],
        operation_transitions: tuple[
            tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent], ...
        ],
    ) -> None: ...

    async def load_render_run(self, render_run_id: str) -> PrototypeRenderRunRecord | None: ...

    async def load_render_artifact(
        self,
        artifact_id: str,
    ) -> PrototypeRenderArtifactRecord | None: ...

    async def interrupt_active_ai_edit_runs(self, interrupted_at: datetime) -> int: ...

    async def reject_ai_edit_run(
        self,
        *,
        queued_operation: PrototypeOperation,
        queued_event: PrototypeOperationEvent,
        running_transition: tuple[
            PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent
        ],
        replay_descriptor: PrototypeObjectDescriptor,
        replay_reference: PrototypeObjectReference,
        completed_transition: tuple[
            PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent
        ],
        run: PrototypeAiEditRunRecord,
        assistant_message: PrototypeAiMessageRecord,
    ) -> PrototypeAiEditRunRecord: ...

    async def apply_ai_edit_run(
        self,
        *,
        queued_operation: PrototypeOperation,
        queued_event: PrototypeOperationEvent,
        running_transition: tuple[
            PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent
        ],
        batch: PrototypeCommandBatchRecord,
        base_history_checkpoint: PrototypeCommandHistoryCheckpoint,
        base_tail_batches: tuple[PrototypeCommandBatchRecord, ...],
        base_journal_prefix_hash: str,
        descriptor: PrototypeObjectDescriptor,
        reference: PrototypeObjectReference,
        history_descriptor: PrototypeObjectDescriptor,
        history_reference: PrototypeObjectReference,
        history_checkpoint: PrototypeCommandHistoryCheckpoint,
        replay_descriptor: PrototypeObjectDescriptor,
        replay_reference: PrototypeObjectReference,
        checkpoint: PrototypeCheckpointRecord,
        completed_transition: tuple[
            PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent
        ],
        run: PrototypeAiEditRunRecord,
        assistant_message: PrototypeAiMessageRecord,
    ) -> PrototypeCommandAppendResult: ...


class PrototypeProjectStore(Protocol):
    async def load_project(self, project_id: str) -> Project | None: ...


class PrototypeObjectStorage(Protocol):
    def write_json(self, project_id: str, value: object) -> PrototypeObjectDescriptor: ...


class PrototypeUiEngineerExecution(Protocol):
    async def execute(
        self,
        request: PrototypeUiEngineerTaskRequest,
    ) -> PrototypeUiEngineerTaskResult: ...


@dataclass(frozen=True, slots=True)
class PrototypeAiPreviewFile:
    content: bytes
    media_type: str


@dataclass(frozen=True, slots=True)
class PrototypeAiApplyResult:
    run: PrototypeAiEditRunRecord
    draft_result: RecoverStructuredPrototypeResult
    command_batch_id: str


class StructuredPrototypeAiServiceError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        run_id: str | None = None,
        operation_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.run_id = run_id
        self.operation_id = operation_id


@dataclass(slots=True)
class _PipelineEvidence:
    operation: PrototypeOperation
    step: PrototypeOperationStep | None
    next_event_no: int
    next_step_ordinal: int


@dataclass(frozen=True, slots=True)
class _RuntimeScenarioScope:
    scenario: RuntimeScenarioV1
    entity_fixtures: tuple[RuntimeEntitySetV1, ...]


@dataclass(frozen=True, slots=True)
class _RuntimeScopeSlice:
    roles: tuple[RuntimeRoleV1, ...]
    variables: tuple[RuntimeVariableV1, ...]
    forms: tuple[RuntimeFormV1, ...]
    view_bindings: tuple[RuntimeViewBindingV1, ...]
    entity_schemas: tuple[RuntimeEntitySchemaV1, ...]
    rules: tuple[RuntimeRuleV1, ...]
    scenarios: tuple[_RuntimeScenarioScope, ...]


class StructuredPrototypeAiService:
    def __init__(
        self,
        *,
        store: StructuredPrototypeAiPersistence,
        project_store: PrototypeProjectStore,
        object_store: PrototypeObjectStorage,
        structured_service: StructuredPrototypeService,
        runtime: PrototypeUiEngineerExecution,
        renderer_worker: PrototypeRendererExecution,
        artifact_store: PrototypeRenderArtifactStorage,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._project_store = project_store
        self._object_store = object_store
        self._structured_service = structured_service
        self._runtime = runtime
        self._renderer_worker = renderer_worker
        self._artifact_store = artifact_store
        self._clock = clock
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def create_thread(
        self,
        *,
        document_id: str,
        client_request_id: str,
        title: str,
    ) -> PrototypeAiThreadRecord:
        _require_uuid(client_request_id, "client_request_id_invalid")
        document = await self._store.load_document(document_id)
        if document is None:
            raise StructuredPrototypeAiServiceError(
                "document_missing", "prototype document does not exist"
            )
        now = self._now()
        return await self._store.create_ai_thread(
            PrototypeAiThreadRecord(
                id=_stable_id(document_id, client_request_id, "ai-thread"),
                document_id=document_id,
                title=title,
                status="active",
                summary_json=None,
                summary_through_message_id=None,
                created_at=now,
                updated_at=now,
            )
        )

    async def list_threads(self, document_id: str) -> list[PrototypeAiThreadRecord]:
        document = await self._store.load_document(document_id)
        if document is None:
            raise StructuredPrototypeAiServiceError(
                "document_missing", "prototype document does not exist"
            )
        return await self._store.list_ai_threads(document_id)

    async def get_thread(self, thread_id: str) -> PrototypeAiThreadSnapshot:
        snapshot = await self._store.load_ai_thread_snapshot(thread_id)
        if snapshot is None:
            raise StructuredPrototypeAiServiceError(
                "ai_thread_missing", "prototype AI thread does not exist"
            )
        return snapshot

    async def get_run(self, run_id: str) -> PrototypeAiEditRunRecord:
        run = await self._store.load_ai_edit_run(run_id)
        if run is None:
            raise StructuredPrototypeAiServiceError(
                "ai_run_missing", "prototype AI edit run does not exist"
            )
        return run

    async def send_message(
        self,
        *,
        thread_id: str,
        client_message_id: str,
        draft_id: str,
        expected_head_sequence_no: int,
        expected_document_hash: str,
        content: str,
        selection: PrototypeAiSelectionV1,
    ) -> PrototypeAiEditRunRecord:
        _require_uuid(client_message_id, "client_message_id_invalid")
        snapshot = await self.get_thread(thread_id)
        if snapshot.thread.status != "active":
            raise StructuredPrototypeAiServiceError(
                "ai_thread_unavailable", "prototype AI thread is archived"
            )
        draft = await self._store.load_draft(draft_id)
        if draft is None or draft.document_id != snapshot.thread.document_id:
            raise StructuredPrototypeAiServiceError(
                "draft_missing", "prototype AI draft does not exist"
            )
        if (
            draft.status != "active"
            or draft.head_sequence_no != expected_head_sequence_no
            or draft.head_document_hash != expected_document_hash
        ):
            raise StructuredPrototypeAiServiceError(
                "draft_conflict", "prototype AI message base does not match the active draft"
            )
        recovered = await self._structured_service.recover_draft(
            draft_id=draft_id,
            client_request_id=_stable_id(
                thread_id,
                client_message_id,
                expected_document_hash,
                "ai-preflight-recovery",
            ),
        )
        self._validate_selection(recovered.state.document, selection)
        now = self._now()
        run_id = _stable_id(thread_id, client_message_id, "ai-edit-run")
        operation_id = _stable_id(run_id, "operation")
        request_hash = _hash_json(
            {
                "kind": "ai_edit",
                "threadId": thread_id,
                "clientMessageId": client_message_id,
                "draftId": draft_id,
                "baseHeadSequenceNo": expected_head_sequence_no,
                "baseDocumentHash": expected_document_hash,
                "selection": selection.model_dump(mode="json", by_alias=True),
                "instructionHash": _hash_text(content),
            }
        )
        operation = PrototypeOperation(
            id=operation_id,
            operation_kind="ai_edit",
            project_id=recovered.state.document_record.project_id,
            resource_kind="ai_edit_run",
            resource_id=run_id,
            client_request_id=client_message_id,
            correlation_id=_stable_id(operation_id, "correlation"),
            parent_operation_id=None,
            status="queued",
            phase="queued",
            attempt=1,
            request_manifest_hash=request_hash,
            config_manifest_hash=_hash_json(
                {
                    "serviceVersion": AI_EDIT_CONFIG_VERSION,
                    "promptVersion": AI_EDIT_PROMPT_VERSION,
                    "documentSchemaVersion": DOCUMENT_SCHEMA_VERSION,
                    "commandContractVersion": COMMAND_CONTRACT_VERSION,
                    "contextContractVersion": AI_EDIT_CONTEXT_CONTRACT_VERSION,
                    "rendererVersion": self._renderer_worker.identity.renderer_version,
                }
            ),
            result_manifest_hash=None,
            failure_evidence_hash=None,
            error_code=None,
            created_at=now,
            started_at=None,
            completed_at=None,
        )
        message = PrototypeAiMessageRecord(
            id=_stable_id(run_id, "user-message"),
            thread_id=thread_id,
            client_message_id=client_message_id,
            role="user",
            kind="instruction",
            content=content,
            run_id=run_id,
            command_batch_id=None,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        run = PrototypeAiEditRunRecord(
            id=run_id,
            thread_id=thread_id,
            user_message_id=message.id,
            assistant_message_id=None,
            document_id=snapshot.thread.document_id,
            draft_id=draft_id,
            operation_id=operation_id,
            retry_of_run_id=None,
            status="queued",
            scope_json=canonical_json_bytes(
                selection.model_dump(mode="json", by_alias=True)
            ).decode("utf-8"),
            base_head_sequence_no=expected_head_sequence_no,
            base_document_hash=expected_document_hash,
            context_object_hash=None,
            outcome_object_hash=None,
            submission_id=None,
            submission_request_hash=None,
            submission_accepted_at=None,
            replay_manifest_object_hash=None,
            proposed_command_batch_json=None,
            proposed_command_batch_hash=None,
            candidate_object_hash=None,
            preview_render_run_id=None,
            preview_artifact_id=None,
            summary=None,
            affected_entity_ids_json=None,
            task_id=None,
            execution_process_id=None,
            error_code=None,
            error_message=None,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )
        try:
            created = await self._store.create_ai_message_run(
                operation=operation,
                initial_event=PrototypeOperationEvent(
                    operation_id=operation.id,
                    event_no=0,
                    step_id=None,
                    event_kind="operation_queued",
                    status="queued",
                    phase="queued",
                    input_hash=request_hash,
                    output_hash=None,
                    evidence_hash=request_hash,
                    error_code=None,
                    occurred_at=now,
                ),
                message=message,
                run=run,
            )
        except StructuredPrototypeStoreError as exc:
            raise StructuredPrototypeAiServiceError(exc.code, str(exc)) from exc
        if created.created:
            task = asyncio.create_task(self._supervise_run(run.id))
            self._tasks[run.id] = task
            task.add_done_callback(lambda completed: self._task_finished(run.id, completed))
        return created.run

    async def submit_external_proposal(
        self,
        *,
        pairing_id: str,
        agent_kind: Literal["claude_code", "codex"],
        client_message_id: str,
        document_id: str,
        draft_id: str,
        expected_head_sequence_no: int,
        expected_document_hash: str,
        content: str,
        batch: DomainCommandBatchV1,
        affected_entity_ids: tuple[str, ...],
        request_hash: str,
    ) -> PrototypeAiEditRunRecord:
        """Persist an already-generated external proposal in the normal Studio pipeline."""
        _require_uuid(client_message_id, "client_message_id_invalid")
        document_record = await self._store.load_document(document_id)
        if document_record is None:
            raise StructuredPrototypeAiServiceError(
                "document_missing", "prototype document does not exist"
            )
        draft = await self._store.load_draft(draft_id)
        if draft is None or draft.document_id != document_id:
            raise StructuredPrototypeAiServiceError(
                "draft_missing", "prototype draft does not exist"
            )
        if (
            draft.status != "active"
            or draft.head_sequence_no != expected_head_sequence_no
            or draft.head_document_hash != expected_document_hash
        ):
            raise StructuredPrototypeAiServiceError(
                "draft_conflict", "external proposal base does not match the active draft"
            )
        recovered = await self._structured_service.recover_draft(
            draft_id=draft_id,
            client_request_id=_stable_id(
                pairing_id,
                client_message_id,
                expected_document_hash,
                "external-proposal-recovery",
            ),
        )
        selection = PrototypeAiSelectionV1(
            scope="document",
            page_id=None,
            selected_node_ids=[],
            flow_id=None,
            viewport="desktop",
        )
        outcome = PrototypeAssistantCommandProposalV1(
            contract_version=1,
            kind="commandProposal",
            message=content,
            summary=batch.summary,
            batch=batch,
            affected_entity_ids=list(affected_entity_ids),
        )
        self._validate_command_scope(recovered.state.document, batch, selection)
        execution = execute_command_batch(
            recovered.state.document,
            batch,
            draft_id=draft_id,
            client_request_id=client_message_id,
        )
        allocated_ids = {entity_id for _, entity_id in execution.allocated_entity_ids}
        actual_existing = set(execution.affected_entity_ids) - allocated_ids
        if set(affected_entity_ids) != actual_existing:
            raise StructuredPrototypeAiServiceError(
                "scope_violation",
                "external proposal affected entities do not match command execution",
            )
        project = await self._project_store.load_project(document_record.project_id)
        if project is None:
            raise StructuredPrototypeAiServiceError(
                "project_missing", "prototype project does not exist"
            )
        thread = await self.create_thread(
            document_id=document_id,
            client_request_id=_stable_id(
                document_id,
                pairing_id,
                "external-agent-thread-request",
            ),
            title=f"{agent_kind} external prototype proposals",
        )
        snapshot = await self.get_thread(thread.id)
        now = self._now()
        run_id = _stable_id(thread.id, client_message_id, "external-agent-edit-run")
        operation_id = _stable_id(run_id, "operation")
        operation = PrototypeOperation(
            id=operation_id,
            operation_kind="ai_edit",
            project_id=document_record.project_id,
            resource_kind="ai_edit_run",
            resource_id=run_id,
            client_request_id=client_message_id,
            correlation_id=_stable_id(operation_id, "correlation"),
            parent_operation_id=None,
            status="queued",
            phase="queued",
            attempt=1,
            request_manifest_hash=request_hash,
            config_manifest_hash=_hash_json(
                {
                    "serviceVersion": AI_EDIT_CONFIG_VERSION,
                    "source": "external_agent",
                    "agentKind": agent_kind,
                    "documentSchemaVersion": DOCUMENT_SCHEMA_VERSION,
                    "commandContractVersion": COMMAND_CONTRACT_VERSION,
                    "contextContractVersion": AI_EDIT_CONTEXT_CONTRACT_VERSION,
                    "rendererVersion": self._renderer_worker.identity.renderer_version,
                }
            ),
            result_manifest_hash=None,
            failure_evidence_hash=None,
            error_code=None,
            created_at=now,
            started_at=None,
            completed_at=None,
        )
        message = PrototypeAiMessageRecord(
            id=_stable_id(run_id, "user-message"),
            thread_id=thread.id,
            client_message_id=client_message_id,
            role="user",
            kind="instruction",
            content=content,
            run_id=run_id,
            command_batch_id=None,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        run = PrototypeAiEditRunRecord(
            id=run_id,
            thread_id=thread.id,
            user_message_id=message.id,
            assistant_message_id=None,
            document_id=document_id,
            draft_id=draft_id,
            operation_id=operation_id,
            retry_of_run_id=None,
            status="queued",
            scope_json=canonical_json_bytes(
                selection.model_dump(mode="json", by_alias=True)
            ).decode("utf-8"),
            base_head_sequence_no=expected_head_sequence_no,
            base_document_hash=expected_document_hash,
            context_object_hash=None,
            outcome_object_hash=None,
            submission_id=f"external-agent-submission-{client_message_id}",
            submission_request_hash=request_hash,
            submission_accepted_at=now,
            replay_manifest_object_hash=None,
            proposed_command_batch_json=None,
            proposed_command_batch_hash=None,
            candidate_object_hash=None,
            preview_render_run_id=None,
            preview_artifact_id=None,
            summary=None,
            affected_entity_ids_json=None,
            task_id=f"external-agent:{agent_kind}:{pairing_id}",
            execution_process_id=f"external-agent-submission:{client_message_id}",
            error_code=None,
            error_message=None,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )
        try:
            created = await self._store.create_ai_message_run(
                operation=operation,
                initial_event=PrototypeOperationEvent(
                    operation_id=operation.id,
                    event_no=0,
                    step_id=None,
                    event_kind="operation_queued",
                    status="queued",
                    phase="queued",
                    input_hash=request_hash,
                    output_hash=None,
                    evidence_hash=request_hash,
                    error_code=None,
                    occurred_at=now,
                ),
                message=message,
                run=run,
            )
        except StructuredPrototypeStoreError as exc:
            raise StructuredPrototypeAiServiceError(exc.code, str(exc)) from exc
        if not created.created:
            return created.run

        context = self._build_context(recovered.state.document, run, selection, snapshot)
        context_descriptor = await asyncio.to_thread(
            self._object_store.write_json,
            document_record.project_id,
            context,
        )
        outcome_descriptor = await asyncio.to_thread(
            self._object_store.write_json,
            document_record.project_id,
            assistant_outcome_payload(outcome),
        )
        evidence, transition = self._start_pipeline(operation, "validating")
        validating = replace(
            run,
            status="validating",
            context_object_hash=context_descriptor.content_hash,
            outcome_object_hash=outcome_descriptor.content_hash,
            updated_at=self._now(),
        )
        try:
            await self._store.transition_ai_edit_run(
                run=validating,
                expected_statuses=("queued",),
                descriptors_and_references=(
                    (
                        context_descriptor,
                        self._reference(
                            project_id=document_record.project_id,
                            owner_kind="ai_edit_run",
                            owner_id=run.id,
                            role="frozen-context",
                            descriptor=context_descriptor,
                            payload_type="ai_edit_context_manifest",
                            schema_version=AI_EDIT_CONTEXT_CONTRACT_VERSION,
                        ),
                    ),
                    (
                        outcome_descriptor,
                        self._reference(
                            project_id=document_record.project_id,
                            owner_kind="ai_edit_run",
                            owner_id=run.id,
                            role="agent-submission",
                            descriptor=outcome_descriptor,
                            payload_type="agent_submission",
                            schema_version=1,
                        ),
                    ),
                ),
                operation_transitions=(transition,),
            )
            await self._prepare_proposal_preview(
                run=validating,
                evidence=evidence,
                project=project,
                document=recovered.state.document,
                outcome=outcome,
            )
        except (
            PrototypeUiEngineerRunnerError,
            PrototypeObjectStoreError,
            PrototypeRenderArtifactStoreError,
            PrototypeRendererWorkerError,
            StructuredPrototypeAiServiceError,
            StructuredPrototypeContractError,
            StructuredPrototypeServiceError,
            StructuredPrototypeStoreError,
            ValueError,
        ) as exc:
            await self._fail_run(run.id, exc, evidence)
            if isinstance(exc, StructuredPrototypeAiServiceError):
                raise
            raise StructuredPrototypeAiServiceError(
                _error_code(exc),
                _safe_error_message(_error_code(exc)),
                run_id=run.id,
                operation_id=run.operation_id,
            ) from exc
        return await self.get_run(run.id)

    async def _supervise_run(self, run_id: str) -> None:
        try:
            await self._execute_run(run_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("prototype AI run failed unexpectedly: run_id=%s", run_id)
            await self._fail_run(run_id, exc, None)

    def _task_finished(self, run_id: str, task: asyncio.Task[None]) -> None:
        if self._tasks.get(run_id) is task:
            self._tasks.pop(run_id, None)
        try:
            task.result()
        except asyncio.CancelledError:
            logger.debug("prototype AI supervisor cancelled: run_id=%s", run_id)
        except Exception:
            logger.exception("prototype AI supervisor failed: run_id=%s", run_id)

    async def wait_for_run(self, run_id: str) -> PrototypeAiEditRunRecord:
        task = self._tasks.get(run_id)
        if task is not None:
            await task
        return await self.get_run(run_id)

    async def reject(
        self,
        *,
        run_id: str,
        client_request_id: str,
    ) -> PrototypeAiEditRunRecord:
        _require_uuid(client_request_id, "client_request_id_invalid")
        run = await self.get_run(run_id)
        if run.status == "rejected":
            return run
        if run.status != "preview_ready":
            raise StructuredPrototypeAiServiceError(
                "ai_run_conflict", "prototype AI proposal is not ready to reject", run_id=run.id
            )
        if (
            run.outcome_object_hash is None
            or run.proposed_command_batch_hash is None
            or run.candidate_object_hash is None
        ):
            raise StructuredPrototypeAiServiceError(
                "completion_evidence_missing",
                "prototype AI proposal evidence is incomplete",
                run_id=run.id,
            )
        now = self._now()
        rejected = replace(run, status="rejected", updated_at=now, completed_at=now)
        snapshot = await self.get_thread(run.thread_id)
        assistant = next(
            (message for message in snapshot.messages if message.id == run.assistant_message_id),
            None,
        )
        if assistant is None:
            raise StructuredPrototypeAiServiceError(
                "completion_evidence_missing",
                "prototype AI proposal message is missing",
                run_id=run.id,
            )
        document = await self._require_document(run.document_id)
        operation_id = _stable_id(run.id, client_request_id, "ai-reject-operation")
        request_hash = _hash_json(
            {
                "kind": "reject_ai_proposal",
                "runId": run.id,
                "clientRequestId": client_request_id,
                "candidateObjectHash": run.candidate_object_hash,
                "proposedCommandBatchHash": run.proposed_command_batch_hash,
            }
        )
        queued_operation = PrototypeOperation(
            id=operation_id,
            operation_kind="reject_ai_proposal",
            project_id=document.project_id,
            resource_kind="ai_edit_run",
            resource_id=run.id,
            client_request_id=client_request_id,
            correlation_id=_stable_id(operation_id, "correlation"),
            parent_operation_id=run.operation_id,
            status="queued",
            phase="queued",
            attempt=1,
            request_manifest_hash=request_hash,
            config_manifest_hash=_hash_json(
                {
                    "serviceVersion": AI_EDIT_CONFIG_VERSION,
                    "replayManifestVersion": AI_REPLAY_MANIFEST_VERSION,
                }
            ),
            result_manifest_hash=None,
            failure_evidence_hash=None,
            error_code=None,
            created_at=now,
            started_at=None,
            completed_at=None,
        )
        queued_event = PrototypeOperationEvent(
            operation_id=operation_id,
            event_no=0,
            step_id=None,
            event_kind="operation_queued",
            status="queued",
            phase="queued",
            input_hash=request_hash,
            output_hash=None,
            evidence_hash=request_hash,
            error_code=None,
            occurred_at=now,
        )
        running_operation = replace(
            queued_operation,
            status="running",
            phase="reject_proposal",
            started_at=now,
        )
        running_step = self._new_step(
            running_operation,
            ordinal=0,
            phase="reject_proposal",
            input_hash=request_hash,
        )
        running_event = self._step_event(
            running_step,
            event_no=1,
            event_kind="step_started",
        )
        replay_descriptor, replay_reference = await self._write_replay_manifest(
            operation=running_operation,
            context_manifest_hash=run.context_object_hash,
            ordered_input_object_hashes=(
                run.outcome_object_hash,
                run.candidate_object_hash,
            ),
            task_id=run.task_id,
            execution_process_id=run.execution_process_id,
            submission_id=run.submission_id,
            submission_hash=run.submission_request_hash,
            ordered_command_batch_hashes=(run.proposed_command_batch_hash,),
            base_checkpoint_hash=run.base_document_hash,
            base_sequence_no=run.base_head_sequence_no,
            result_checkpoint_hash=None,
            result_sequence_no=run.base_head_sequence_no,
            renderer_input_hash=None,
            renderer_output_hash=None,
            validation_report_hashes=(),
            terminal_status="succeeded",
        )
        completed_step = replace(
            running_step,
            status="succeeded",
            output_manifest_hash=replay_descriptor.content_hash,
            completion_evidence_kind="replay_manifest",
            completion_evidence_ref=replay_descriptor.content_hash,
            completed_at=now,
        )
        completed_operation = replace(
            running_operation,
            status="succeeded",
            result_manifest_hash=replay_descriptor.content_hash,
            completed_at=now,
        )
        completed_event = self._step_event(
            completed_step,
            event_no=2,
            event_kind="step_succeeded",
        )
        return await self._store.reject_ai_edit_run(
            queued_operation=queued_operation,
            queued_event=queued_event,
            running_transition=(running_operation, running_step, running_event),
            replay_descriptor=replay_descriptor,
            replay_reference=replay_reference,
            completed_transition=(completed_operation, completed_step, completed_event),
            run=rejected,
            assistant_message=replace(assistant, status="rejected", updated_at=now),
        )

    async def apply(
        self,
        *,
        run_id: str,
        client_request_id: str,
        expected_head_sequence_no: int,
        expected_document_hash: str,
    ) -> PrototypeAiApplyResult:
        _require_uuid(client_request_id, "client_request_id_invalid")
        run = await self.get_run(run_id)
        if run.status == "applied":
            snapshot = await self.get_thread(run.thread_id)
            message = next(
                (item for item in snapshot.messages if item.id == run.assistant_message_id),
                None,
            )
            if message is None or message.command_batch_id is None:
                raise StructuredPrototypeAiServiceError(
                    "completion_evidence_missing",
                    "prototype AI applied command evidence is missing",
                    run_id=run.id,
                )
            recovered_applied = await self._structured_service.recover_draft(
                draft_id=run.draft_id,
                client_request_id=_stable_id(run.id, "applied-response-recovery"),
            )
            return PrototypeAiApplyResult(
                run=run,
                draft_result=recovered_applied,
                command_batch_id=message.command_batch_id,
            )
        if run.status != "preview_ready":
            raise StructuredPrototypeAiServiceError(
                "ai_run_conflict", "prototype AI proposal is not ready to apply", run_id=run.id
            )
        if (
            run.base_head_sequence_no != expected_head_sequence_no
            or run.base_document_hash != expected_document_hash
        ):
            await self._mark_preview_stale(run)
            raise StructuredPrototypeAiServiceError(
                "draft_conflict",
                "prototype AI proposal base does not match the request",
                run_id=run.id,
            )
        draft = await self._store.load_draft(run.draft_id)
        if (
            draft is None
            or draft.status != "active"
            or draft.head_sequence_no != expected_head_sequence_no
            or draft.head_document_hash != expected_document_hash
        ):
            await self._mark_preview_stale(run)
            raise StructuredPrototypeAiServiceError(
                "draft_conflict", "prototype draft changed before AI proposal apply", run_id=run.id
            )
        if (
            run.proposed_command_batch_json is None
            or run.proposed_command_batch_hash is None
            or run.candidate_object_hash is None
            or run.assistant_message_id is None
        ):
            raise StructuredPrototypeAiServiceError(
                "completion_evidence_missing",
                "prototype AI proposal evidence is incomplete",
                run_id=run.id,
            )
        try:
            recovered = await self._structured_service.recover_draft(
                draft_id=run.draft_id,
                client_request_id=_stable_id(run.id, client_request_id, "ai-apply-recovery"),
            )
            base_state = await self._structured_service.ensure_mutation_checkpoint(
                state=recovered.state,
                client_request_id=client_request_id,
            )
        except StructuredPrototypeServiceError as exc:
            raise StructuredPrototypeAiServiceError(
                exc.code,
                str(exc),
                run_id=run.id,
            ) from exc
        from app.application.structured_prototype_contracts import parse_command_batch_json

        batch = parse_command_batch_json(run.proposed_command_batch_json)
        if command_batch_hash(batch) != run.proposed_command_batch_hash:
            raise StructuredPrototypeAiServiceError(
                "object_hash_mismatch",
                "prototype AI command proposal hash is corrupt",
                run_id=run.id,
            )
        execution = execute_command_batch(
            base_state.document,
            batch,
            draft_id=run.draft_id,
            client_request_id=run.id,
        )
        if (
            execution.base_document_hash != run.base_document_hash
            or execution.result_document_hash != run.candidate_object_hash
        ):
            raise StructuredPrototypeAiServiceError(
                "object_hash_mismatch",
                "prototype AI candidate cannot be reproduced from its command batch",
                run_id=run.id,
            )
        document_record = base_state.document_record
        descriptor = await self._store.load_object(
            document_record.project_id,
            run.candidate_object_hash,
        )
        if descriptor is None:
            raise StructuredPrototypeAiServiceError(
                "object_missing", "prototype AI candidate object is missing", run_id=run.id
            )
        snapshot = await self.get_thread(run.thread_id)
        current_message = next(
            (item for item in snapshot.messages if item.id == run.assistant_message_id),
            None,
        )
        if current_message is None or current_message.status != "completed":
            raise StructuredPrototypeAiServiceError(
                "ai_message_conflict", "prototype AI proposal message is unavailable", run_id=run.id
            )
        now = self._now()
        operation_id = _stable_id(run.id, client_request_id, "ai-apply-operation")
        request_hash = _hash_json(
            {
                "kind": "apply_command_batch",
                "runId": run.id,
                "draftId": run.draft_id,
                "clientRequestId": client_request_id,
                "baseHeadSequenceNo": expected_head_sequence_no,
                "baseDocumentHash": expected_document_hash,
                "commandBatchHash": run.proposed_command_batch_hash,
                "candidateObjectHash": run.candidate_object_hash,
            }
        )
        queued_operation = PrototypeOperation(
            id=operation_id,
            operation_kind="apply_command_batch",
            project_id=document_record.project_id,
            resource_kind="draft",
            resource_id=run.draft_id,
            client_request_id=client_request_id,
            correlation_id=_stable_id(operation_id, "correlation"),
            parent_operation_id=run.operation_id,
            status="queued",
            phase="queued",
            attempt=1,
            request_manifest_hash=request_hash,
            config_manifest_hash=_hash_json(
                {
                    "serviceVersion": AI_EDIT_CONFIG_VERSION,
                    "documentSchemaVersion": DOCUMENT_SCHEMA_VERSION,
                    "commandContractVersion": COMMAND_CONTRACT_VERSION,
                }
            ),
            result_manifest_hash=None,
            failure_evidence_hash=None,
            error_code=None,
            created_at=now,
            started_at=None,
            completed_at=None,
        )
        queued_event = PrototypeOperationEvent(
            operation_id=operation_id,
            event_no=0,
            step_id=None,
            event_kind="operation_queued",
            status="queued",
            phase="queued",
            input_hash=request_hash,
            output_hash=None,
            evidence_hash=request_hash,
            error_code=None,
            occurred_at=now,
        )
        running_operation = replace(
            queued_operation,
            status="running",
            phase="commit_ai_command_batch",
            started_at=now,
        )
        running_step = self._new_step(
            running_operation,
            ordinal=0,
            phase="commit_ai_command_batch",
            input_hash=request_hash,
        )
        running_event = self._step_event(
            running_step,
            event_no=1,
            event_kind="step_started",
        )
        command_batch_id = _stable_id(operation_id, "command-batch")
        inverse_commands_json = canonical_model_json(execution.inverse_commands)
        batch_record = PrototypeCommandBatchRecord(
            id=command_batch_id,
            draft_id=run.draft_id,
            base_sequence_no=expected_head_sequence_no,
            result_sequence_no=expected_head_sequence_no + 1,
            client_request_id=client_request_id,
            origin="ai",
            operation_kind="forward",
            target_batch_id=None,
            command_contract_version=COMMAND_CONTRACT_VERSION,
            commands_json=canonical_model_json(batch),
            inverse_commands_json=inverse_commands_json,
            command_batch_hash=command_batch_envelope_hash(
                draft_id=run.draft_id,
                base_sequence_no=expected_head_sequence_no,
                result_sequence_no=expected_head_sequence_no + 1,
                origin="ai",
                operation_kind="forward",
                target_batch_id=None,
                commands=batch,
                inverse_commands=execution.inverse_commands,
            ),
            base_document_hash=run.base_document_hash,
            result_document_hash=run.candidate_object_hash,
            operation_id=operation_id,
            created_at=now,
        )
        result_history = advance_prototype_command_history(
            base_state.command_history,
            batch_record,
        )
        result_prefix_hash = advance_journal_prefix_hash(
            previous_prefix_hash=base_state.journal_prefix_hash,
            batch_id=batch_record.id,
            base_sequence_no=batch_record.base_sequence_no,
            result_sequence_no=batch_record.result_sequence_no,
            command_batch_hash=batch_record.command_batch_hash,
            base_document_hash=batch_record.base_document_hash,
            result_document_hash=batch_record.result_document_hash,
        )
        checkpoint_id = _stable_id(operation_id, "ai-apply-checkpoint")
        try:
            history_artifact = (
                await self._structured_service.materialize_command_history_checkpoint(
                    project_id=document_record.project_id,
                    checkpoint_id=checkpoint_id,
                    draft_id=run.draft_id,
                    checkpoint_sequence_no=batch_record.result_sequence_no,
                    checkpoint_document_hash=run.candidate_object_hash,
                    journal_prefix_hash=result_prefix_hash,
                    history=result_history,
                    created_at=now,
                )
            )
        except (PrototypeObjectStoreError, StructuredPrototypeContractError) as exc:
            raise StructuredPrototypeAiServiceError(
                exc.code,
                str(exc),
                run_id=run.id,
            ) from exc
        checkpoint = PrototypeCheckpointRecord(
            id=checkpoint_id,
            document_id=run.document_id,
            draft_id=run.draft_id,
            revision_id=None,
            checkpoint_kind="ai_apply",
            checkpoint_sequence_no=batch_record.result_sequence_no,
            document_object_hash=run.candidate_object_hash,
            document_schema_version=DOCUMENT_SCHEMA_VERSION,
            command_contract_version=COMMAND_CONTRACT_VERSION,
            document_hash=run.candidate_object_hash,
            history_snapshot_object_hash=history_artifact.descriptor.content_hash,
            history_snapshot_schema_version=COMMAND_HISTORY_CHECKPOINT_SCHEMA_VERSION,
            journal_prefix_hash=result_prefix_hash,
            created_by_operation_id=operation_id,
            created_at=now,
        )
        replay_descriptor, replay_reference = await self._write_replay_manifest(
            operation=running_operation,
            context_manifest_hash=run.context_object_hash,
            ordered_input_object_hashes=(
                run.outcome_object_hash,
                run.candidate_object_hash,
                run.replay_manifest_object_hash,
            ),
            task_id=run.task_id,
            execution_process_id=run.execution_process_id,
            submission_id=run.submission_id,
            submission_hash=run.submission_request_hash,
            ordered_command_batch_hashes=(batch_record.command_batch_hash,),
            base_checkpoint_hash=run.base_document_hash,
            base_sequence_no=run.base_head_sequence_no,
            result_checkpoint_hash=run.candidate_object_hash,
            result_sequence_no=batch_record.result_sequence_no,
            renderer_input_hash=None,
            renderer_output_hash=None,
            validation_report_hashes=(run.candidate_object_hash,),
            terminal_status="succeeded",
        )
        result_hash = replay_descriptor.content_hash
        completed_step = replace(
            running_step,
            status="succeeded",
            output_manifest_hash=result_hash,
            completion_evidence_kind="command_batch",
            completion_evidence_ref=command_batch_id,
            completed_at=now,
        )
        completed_operation = replace(
            running_operation,
            status="succeeded",
            result_manifest_hash=result_hash,
            completed_at=now,
        )
        completed_event = self._step_event(
            completed_step,
            event_no=2,
            event_kind="step_succeeded",
        )
        applied_run = replace(run, status="applied", updated_at=now, completed_at=now)
        applied_message = replace(
            current_message,
            command_batch_id=command_batch_id,
            status="applied",
            updated_at=now,
        )
        try:
            committed = await self._store.apply_ai_edit_run(
                queued_operation=queued_operation,
                queued_event=queued_event,
                running_transition=(running_operation, running_step, running_event),
                batch=batch_record,
                base_history_checkpoint=base_state.history_checkpoint,
                base_tail_batches=base_state.validated_tail_batches,
                base_journal_prefix_hash=base_state.journal_prefix_hash,
                descriptor=descriptor,
                reference=self._reference(
                    project_id=document_record.project_id,
                    owner_kind="checkpoint",
                    owner_id=checkpoint_id,
                    role="ai-apply-document",
                    descriptor=descriptor,
                    payload_type="prototype_document",
                    schema_version=DOCUMENT_SCHEMA_VERSION,
                ),
                history_descriptor=history_artifact.descriptor,
                history_reference=history_artifact.reference,
                history_checkpoint=history_artifact.checkpoint,
                replay_descriptor=replay_descriptor,
                replay_reference=replay_reference,
                checkpoint=checkpoint,
                completed_transition=(completed_operation, completed_step, completed_event),
                run=applied_run,
                assistant_message=applied_message,
            )
        except StructuredPrototypeStoreError as exc:
            if exc.code in CORRUPTION_ERROR_CODES:
                try:
                    await self._structured_service.recover_draft(
                        draft_id=run.draft_id,
                        client_request_id=_stable_id(
                            operation_id,
                            exc.code,
                            "ai-apply-corruption-recovery",
                        ),
                    )
                except StructuredPrototypeServiceError as recovery_exc:
                    raise StructuredPrototypeAiServiceError(
                        recovery_exc.code,
                        str(recovery_exc),
                        run_id=run.id,
                    ) from exc
            raise StructuredPrototypeAiServiceError(
                exc.code,
                str(exc),
                run_id=run.id,
            ) from exc
        recovered_applied = await self._structured_service.recover_draft(
            draft_id=run.draft_id,
            client_request_id=_stable_id(
                run.id,
                client_request_id,
                str(committed.draft.head_sequence_no),
                "applied-response-recovery",
            ),
        )
        return PrototypeAiApplyResult(
            run=applied_run,
            draft_result=recovered_applied,
            command_batch_id=command_batch_id,
        )

    async def _mark_preview_stale(
        self,
        run: PrototypeAiEditRunRecord,
    ) -> PrototypeAiEditRunRecord:
        now = self._now()
        stale = replace(
            run,
            status="stale",
            error_code="draft_conflict",
            error_message="prototype draft changed before proposal apply",
            updated_at=now,
            completed_at=now,
        )
        return await self._store.transition_ai_edit_run(
            run=stale,
            expected_statuses=("preview_ready",),
        )

    async def recover_interrupted_runs(self) -> int:
        return await self._store.interrupt_active_ai_edit_runs(self._now())

    async def read_preview_file(
        self,
        *,
        run_id: str,
        relative_path: str,
    ) -> PrototypeAiPreviewFile:
        run = await self.get_run(run_id)
        if run.status not in {"preview_ready", "rejected", "applied"}:
            raise StructuredPrototypeAiServiceError(
                "ai_preview_missing", "prototype AI preview is unavailable", run_id=run.id
            )
        if run.preview_render_run_id is None or run.preview_artifact_id is None:
            raise StructuredPrototypeAiServiceError(
                "ai_preview_missing", "prototype AI preview evidence is incomplete", run_id=run.id
            )
        render_run = await self._store.load_render_run(run.preview_render_run_id)
        artifact = await self._store.load_render_artifact(run.preview_artifact_id)
        if (
            render_run is None
            or artifact is None
            or render_run.status != "ready"
            or render_run.artifact_id != artifact.id
            or artifact.render_run_id != render_run.id
        ):
            raise StructuredPrototypeAiServiceError(
                "ai_preview_missing", "prototype AI preview evidence is corrupt", run_id=run.id
            )
        descriptor = PrototypeRenderBundleDescriptor(
            project_id=(await self._require_document(run.document_id)).project_id,
            document_id=run.document_id,
            artifact_id=artifact.id,
            storage_key=artifact.storage_key,
            entrypoint=artifact.entrypoint,
            output_hash=artifact.output_hash,
            output_manifest_hash=artifact.output_manifest_hash,
            visual_preflight_report_hash=artifact.visual_preflight_report_hash,
            file_count=4,
        )
        try:
            content = await asyncio.to_thread(
                self._artifact_store.read_file,
                descriptor,
                relative_path,
            )
        except PrototypeRenderArtifactStoreError as exc:
            raise StructuredPrototypeAiServiceError(exc.code, str(exc), run_id=run.id) from exc
        media_type = {
            "index.html": "text/html; charset=utf-8",
            "styles.css": "text/css; charset=utf-8",
            "runtime.js": "text/javascript; charset=utf-8",
            "document.json": "application/json; charset=utf-8",
        }.get(relative_path)
        if media_type is None:
            raise StructuredPrototypeAiServiceError(
                "render_artifact_path_invalid", "prototype AI preview path is not allowed"
            )
        return PrototypeAiPreviewFile(content=content, media_type=media_type)

    async def _execute_run(self, run_id: str) -> None:
        evidence: _PipelineEvidence | None = None
        try:
            run = await self.get_run(run_id)
            operation = await self._store.load_operation(run.operation_id)
            if operation is None or operation.status != "queued":
                raise StructuredPrototypeAiServiceError(
                    "operation_missing",
                    "prototype AI operation is unavailable",
                    run_id=run.id,
                    operation_id=run.operation_id,
                )
            evidence, transition = self._start_pipeline(operation, "building_context")
            run = replace(run, status="building_context", updated_at=self._now())
            await self._store.transition_ai_edit_run(
                run=run,
                expected_statuses=("queued",),
                operation_transitions=(transition,),
            )

            recovered = await self._structured_service.recover_draft(
                draft_id=run.draft_id,
                client_request_id=_stable_id(run.id, run.base_document_hash, "ai-context-recovery"),
            )
            selection = PrototypeAiSelectionV1.model_validate_json(
                run.scope_json,
                strict=True,
                by_alias=True,
                by_name=False,
            )
            thread = await self.get_thread(run.thread_id)
            user_message = next(
                (message for message in thread.messages if message.id == run.user_message_id),
                None,
            )
            if user_message is None:
                raise StructuredPrototypeAiServiceError(
                    "ai_message_missing", "prototype AI user message does not exist", run_id=run.id
                )
            context = self._build_context(
                recovered.state.document,
                run,
                selection,
                thread,
            )
            context_descriptor = await asyncio.to_thread(
                self._object_store.write_json,
                recovered.state.document_record.project_id,
                context,
            )
            context_reference = self._reference(
                project_id=recovered.state.document_record.project_id,
                owner_kind="ai_edit_run",
                owner_id=run.id,
                role="frozen-context",
                descriptor=context_descriptor,
                payload_type="ai_edit_context_manifest",
                schema_version=AI_EDIT_CONTEXT_CONTRACT_VERSION,
            )
            evidence, context_transitions = self._advance_pipeline(
                evidence,
                next_phase="generating",
                completed_output_hash=context_descriptor.content_hash,
                evidence_kind="ai_edit_context_manifest",
                evidence_ref=context_descriptor.content_hash,
            )
            task_id = "prototype-ai-task-" + run.id.replace("-", "")
            run = replace(
                run,
                status="generating",
                context_object_hash=context_descriptor.content_hash,
                task_id=task_id,
                updated_at=self._now(),
            )
            await self._store.transition_ai_edit_run(
                run=run,
                expected_statuses=("building_context",),
                descriptors_and_references=((context_descriptor, context_reference),),
                operation_transitions=context_transitions,
            )

            project = await self._project_store.load_project(
                recovered.state.document_record.project_id
            )
            if project is None:
                raise StructuredPrototypeAiServiceError(
                    "project_missing", "prototype project does not exist", run_id=run.id
                )
            runtime_result = await self._runtime.execute(
                PrototypeUiEngineerTaskRequest(
                    project=project,
                    operation_id=run.operation_id,
                    edit_run_id=run.id,
                    task_id=task_id,
                    frozen_context_object_hash=context_descriptor.content_hash,
                    frozen_context=context,
                    user_instruction=user_message.content,
                )
            )
            evidence, submission_transitions = self._advance_pipeline(
                evidence,
                next_phase="storing_submission",
                completed_output_hash=runtime_result.submission.request_hash,
                evidence_kind="submission_receipt",
                evidence_ref=runtime_result.submission.submission_id,
            )
            run = replace(
                run,
                submission_id=runtime_result.submission.submission_id,
                submission_request_hash=runtime_result.submission.request_hash,
                submission_accepted_at=datetime.fromtimestamp(
                    runtime_result.submission.accepted_at,
                    tz=UTC,
                ),
                execution_process_id=runtime_result.execution_process_id,
                updated_at=self._now(),
            )
            await self._store.transition_ai_edit_run(
                run=run,
                expected_statuses=("generating",),
                operation_transitions=submission_transitions,
            )
            outcome_descriptor = await asyncio.to_thread(
                self._object_store.write_json,
                project.id,
                assistant_outcome_payload(runtime_result.outcome),
            )
            outcome_reference = self._reference(
                project_id=project.id,
                owner_kind="ai_edit_run",
                owner_id=run.id,
                role="agent-submission",
                descriptor=outcome_descriptor,
                payload_type="agent_submission",
                schema_version=1,
            )
            evidence, generation_transitions = self._advance_pipeline(
                evidence,
                next_phase="validating",
                completed_output_hash=outcome_descriptor.content_hash,
                evidence_kind="agent_submission",
                evidence_ref=runtime_result.submission.submission_id,
            )
            run = replace(
                run,
                status="validating",
                outcome_object_hash=outcome_descriptor.content_hash,
                updated_at=self._now(),
            )
            await self._store.transition_ai_edit_run(
                run=run,
                expected_statuses=("generating",),
                descriptors_and_references=((outcome_descriptor, outcome_reference),),
                operation_transitions=generation_transitions,
            )

            if isinstance(
                runtime_result.outcome,
                (PrototypeAssistantAnswerV1, PrototypeAssistantClarificationV1),
            ):
                await self._complete_text_outcome(run, evidence, runtime_result.outcome)
                return
            await self._prepare_proposal_preview(
                run=run,
                evidence=evidence,
                project=project,
                document=recovered.state.document,
                outcome=runtime_result.outcome,
            )
        except (
            PrototypeUiEngineerRunnerError,
            PrototypeObjectStoreError,
            PrototypeRenderArtifactStoreError,
            PrototypeRendererWorkerError,
            StructuredPrototypeAiServiceError,
            StructuredPrototypeContractError,
            StructuredPrototypeServiceError,
            StructuredPrototypeStoreError,
            ValueError,
            PrototypeUiEngineerRuntimeError,
        ) as exc:
            await self._fail_run(run_id, exc, evidence)

    async def _complete_text_outcome(
        self,
        run: PrototypeAiEditRunRecord,
        evidence: _PipelineEvidence,
        outcome: PrototypeAssistantAnswerV1 | PrototypeAssistantClarificationV1,
    ) -> None:
        kind = outcome.kind
        now = self._now()
        assistant_id = _stable_id(run.id, "assistant-message")
        result_hash = run.outcome_object_hash
        if result_hash is None:
            raise StructuredPrototypeAiServiceError(
                "completion_evidence_missing", "prototype assistant outcome hash is missing"
            )
        evidence, validation_transitions = self._advance_pipeline(
            evidence,
            next_phase="finalizing_evidence",
            completed_output_hash=result_hash,
            evidence_kind="agent_submission",
            evidence_ref=result_hash,
        )
        terminal_status: PrototypeAiEditRunStatus = (
            "completed_answer" if kind == "answer" else "completed_clarification"
        )
        replay_descriptor, replay_reference = await self._write_replay_manifest(
            operation=evidence.operation,
            context_manifest_hash=run.context_object_hash,
            ordered_input_object_hashes=(result_hash,),
            task_id=run.task_id,
            execution_process_id=run.execution_process_id,
            submission_id=run.submission_id,
            submission_hash=run.submission_request_hash,
            ordered_command_batch_hashes=(),
            base_checkpoint_hash=run.base_document_hash,
            base_sequence_no=run.base_head_sequence_no,
            result_checkpoint_hash=None,
            result_sequence_no=run.base_head_sequence_no,
            renderer_input_hash=None,
            renderer_output_hash=None,
            validation_report_hashes=(result_hash,),
            terminal_status=terminal_status,
        )
        completed_evidence, transition = self._finish_pipeline(
            evidence,
            output_hash=replay_descriptor.content_hash,
            evidence_kind="replay_manifest",
            evidence_ref=replay_descriptor.content_hash,
        )
        completed = replace(
            run,
            assistant_message_id=assistant_id,
            status=terminal_status,
            summary=outcome.message,
            replay_manifest_object_hash=replay_descriptor.content_hash,
            updated_at=now,
            completed_at=now,
        )
        message = PrototypeAiMessageRecord(
            id=assistant_id,
            thread_id=run.thread_id,
            client_message_id=None,
            role="assistant",
            kind=kind,
            content=outcome.message,
            run_id=run.id,
            command_batch_id=None,
            status="completed",
            created_at=now,
            updated_at=now,
        )
        await self._store.transition_ai_edit_run(
            run=completed,
            expected_statuses=("validating",),
            assistant_message=message,
            descriptors_and_references=((replay_descriptor, replay_reference),),
            operation_transitions=(*validation_transitions, transition),
        )
        evidence.operation = completed_evidence.operation
        evidence.step = completed_evidence.step

    async def _prepare_proposal_preview(
        self,
        *,
        run: PrototypeAiEditRunRecord,
        evidence: _PipelineEvidence,
        project: Project,
        document: PrototypeDocumentV1,
        outcome: PrototypeAssistantCommandProposalV1,
    ) -> None:
        caller_evidence = evidence
        selection = PrototypeAiSelectionV1.model_validate_json(
            run.scope_json,
            strict=True,
            by_alias=True,
            by_name=False,
        )
        batch = outcome.command_batch()
        self._validate_command_scope(document, batch, selection)
        execution = execute_command_batch(
            document,
            batch,
            draft_id=run.draft_id,
            client_request_id=run.id,
        )
        allocated_ids = {entity_id for _, entity_id in execution.allocated_entity_ids}
        declared_existing = set(outcome.affected_entity_ids)
        actual_existing = set(execution.affected_entity_ids) - allocated_ids
        if declared_existing != actual_existing:
            raise StructuredPrototypeAiServiceError(
                "scope_violation",
                "prototype AI declared affected entities do not match command execution",
                run_id=run.id,
            )
        current_draft = await self._store.load_draft(run.draft_id)
        if (
            current_draft is None
            or current_draft.status != "active"
            or current_draft.head_sequence_no != run.base_head_sequence_no
            or current_draft.head_document_hash != run.base_document_hash
        ):
            await self._complete_stale_proposal(run, evidence, outcome)
            return
        candidate_descriptor = await asyncio.to_thread(
            self._object_store.write_json,
            project.id,
            document_payload(execution.document),
        )
        if candidate_descriptor.content_hash != execution.result_document_hash:
            raise StructuredPrototypeAiServiceError(
                "object_hash_mismatch", "prototype AI candidate object hash is inconsistent"
            )
        render_run_id = _stable_id(run.id, "preview-render-run")
        artifact_id = _stable_id(run.id, "preview-artifact")
        input_manifest = _renderer_input_manifest(
            self._renderer_worker.identity,
            document_object_hash=candidate_descriptor.content_hash,
            output_locale=execution.document.locale,
            asset_object_hashes=[asset.content_hash for asset in execution.document.asset_refs],
        )
        input_descriptor = await asyncio.to_thread(
            self._object_store.write_json,
            project.id,
            input_manifest,
        )
        now = self._now()
        candidate_reference = self._reference(
            project_id=project.id,
            owner_kind="ai_edit_run",
            owner_id=run.id,
            role="candidate-document",
            descriptor=candidate_descriptor,
            payload_type="prototype_document",
            schema_version=DOCUMENT_SCHEMA_VERSION,
        )
        input_reference = self._reference(
            project_id=project.id,
            owner_kind="render_run",
            owner_id=render_run_id,
            role="renderer-input-manifest",
            descriptor=input_descriptor,
            payload_type="renderer_input_manifest",
            schema_version=1,
        )
        evidence, preview_transitions = self._advance_pipeline(
            evidence,
            next_phase="rendering_preview",
            completed_output_hash=candidate_descriptor.content_hash,
            evidence_kind="prototype_document",
            evidence_ref=candidate_descriptor.content_hash,
        )
        rendering_run = replace(
            run,
            status="rendering_preview",
            proposed_command_batch_json=canonical_model_json(batch),
            proposed_command_batch_hash=command_batch_hash(batch),
            candidate_object_hash=candidate_descriptor.content_hash,
            preview_render_run_id=render_run_id,
            summary=outcome.summary,
            affected_entity_ids_json=canonical_json_bytes(
                list(execution.affected_entity_ids)
            ).decode("utf-8"),
            updated_at=now,
        )
        render_run = _render_run(
            identity=self._renderer_worker.identity,
            run=rendering_run,
            render_run_id=render_run_id,
            input_manifest_hash=input_descriptor.content_hash,
            artifact_id=None,
            status="rendering",
            now=now,
        )
        await self._store.freeze_ai_preview(
            run=rendering_run,
            render_run=render_run,
            descriptors_and_references=(
                (candidate_descriptor, candidate_reference),
                (input_descriptor, input_reference),
            ),
            operation_transitions=preview_transitions,
        )
        caller_evidence.operation = evidence.operation
        caller_evidence.step = evidence.step
        caller_evidence.next_event_no = evidence.next_event_no
        caller_evidence.next_step_ordinal = evidence.next_step_ordinal

        render_result = await self._renderer_worker.render(
            request_id=run.operation_id,
            artifact_id=artifact_id,
            input_manifest=input_manifest,
            document=document_payload(execution.document),
        )
        if render_result.input_manifest_hash != input_descriptor.content_hash:
            raise StructuredPrototypeAiServiceError(
                "renderer_input_manifest_mismatch",
                "prototype AI renderer did not use the frozen input manifest",
            )
        bundle = await asyncio.to_thread(
            self._artifact_store.write_bundle,
            project_id=project.id,
            document_id=run.document_id,
            artifact_id=artifact_id,
            result=render_result,
        )
        output_descriptor = await asyncio.to_thread(
            self._object_store.write_json,
            project.id,
            render_result.output_manifest,
        )
        preflight_descriptor = await asyncio.to_thread(
            self._object_store.write_json,
            project.id,
            render_result.visual_preflight_report,
        )
        if (
            output_descriptor.content_hash != render_result.output_manifest_hash
            or preflight_descriptor.content_hash != render_result.visual_preflight_report_hash
            or bundle.output_hash != render_result.bundle_hash
        ):
            raise StructuredPrototypeAiServiceError(
                "renderer_evidence_mismatch",
                "prototype AI renderer evidence is inconsistent",
            )
        evidence, render_transitions = self._advance_pipeline(
            evidence,
            next_phase="finalizing_evidence",
            completed_output_hash=render_result.output_manifest_hash,
            evidence_kind="renderer_output_manifest",
            evidence_ref=render_result.output_manifest_hash,
        )
        replay_descriptor, replay_reference = await self._write_replay_manifest(
            operation=evidence.operation,
            context_manifest_hash=run.context_object_hash,
            ordered_input_object_hashes=(
                run.outcome_object_hash,
                candidate_descriptor.content_hash,
                input_descriptor.content_hash,
                output_descriptor.content_hash,
                preflight_descriptor.content_hash,
            ),
            task_id=run.task_id,
            execution_process_id=run.execution_process_id,
            submission_id=run.submission_id,
            submission_hash=run.submission_request_hash,
            ordered_command_batch_hashes=(command_batch_hash(batch),),
            base_checkpoint_hash=run.base_document_hash,
            base_sequence_no=run.base_head_sequence_no,
            result_checkpoint_hash=candidate_descriptor.content_hash,
            result_sequence_no=run.base_head_sequence_no,
            renderer_input_hash=input_descriptor.content_hash,
            renderer_output_hash=render_result.output_manifest_hash,
            validation_report_hashes=(
                candidate_descriptor.content_hash,
                preflight_descriptor.content_hash,
            ),
            terminal_status="preview_ready",
        )
        completed_evidence, terminal_transition = self._finish_pipeline(
            evidence,
            output_hash=replay_descriptor.content_hash,
            evidence_kind="replay_manifest",
            evidence_ref=replay_descriptor.content_hash,
        )
        completed_at = self._now()
        assistant_id = _stable_id(run.id, "assistant-message")
        ready = replace(
            rendering_run,
            assistant_message_id=assistant_id,
            status="preview_ready",
            preview_artifact_id=artifact_id,
            replay_manifest_object_hash=replay_descriptor.content_hash,
            updated_at=completed_at,
        )
        ready_render_run = replace(
            render_run,
            status="ready",
            artifact_id=artifact_id,
            output_manifest_hash=render_result.output_manifest_hash,
            completed_at=completed_at,
            updated_at=completed_at,
        )
        artifact = PrototypeRenderArtifactRecord(
            id=artifact_id,
            render_run_id=render_run_id,
            document_id=run.document_id,
            revision_id=None,
            renderer_version=self._renderer_worker.identity.renderer_version,
            document_hash=candidate_descriptor.content_hash,
            output_hash=bundle.output_hash,
            output_manifest_hash=bundle.output_manifest_hash,
            storage_key=bundle.storage_key,
            entrypoint=bundle.entrypoint,
            visual_preflight_report_hash=bundle.visual_preflight_report_hash,
            created_at=completed_at,
        )
        assistant_message = PrototypeAiMessageRecord(
            id=assistant_id,
            thread_id=run.thread_id,
            client_message_id=None,
            role="assistant",
            kind="proposal",
            content=outcome.message,
            run_id=run.id,
            command_batch_id=None,
            status="completed",
            created_at=completed_at,
            updated_at=completed_at,
        )
        await self._store.complete_ai_preview(
            run=ready,
            render_run=ready_render_run,
            artifact=artifact,
            assistant_message=assistant_message,
            descriptors_and_references=(
                (
                    output_descriptor,
                    self._reference(
                        project_id=project.id,
                        owner_kind="render_run",
                        owner_id=render_run_id,
                        role="renderer-output-manifest",
                        descriptor=output_descriptor,
                        payload_type="renderer_output_manifest",
                        schema_version=1,
                    ),
                ),
                (
                    preflight_descriptor,
                    self._reference(
                        project_id=project.id,
                        owner_kind="render_run",
                        owner_id=render_run_id,
                        role="visual-preflight-report",
                        descriptor=preflight_descriptor,
                        payload_type="visual_preflight_report",
                        schema_version=1,
                    ),
                ),
                (replay_descriptor, replay_reference),
            ),
            operation_transitions=(*render_transitions, terminal_transition),
        )
        caller_evidence.operation = completed_evidence.operation
        caller_evidence.step = completed_evidence.step
        caller_evidence.next_event_no = completed_evidence.next_event_no
        caller_evidence.next_step_ordinal = completed_evidence.next_step_ordinal

    async def _complete_stale_proposal(
        self,
        run: PrototypeAiEditRunRecord,
        evidence: _PipelineEvidence,
        outcome: PrototypeAssistantCommandProposalV1,
    ) -> None:
        if run.outcome_object_hash is None:
            raise StructuredPrototypeAiServiceError(
                "completion_evidence_missing", "prototype AI outcome evidence is missing"
            )
        evidence, validation_transitions = self._advance_pipeline(
            evidence,
            next_phase="finalizing_evidence",
            completed_output_hash=run.outcome_object_hash,
            evidence_kind="agent_submission",
            evidence_ref=run.outcome_object_hash,
        )
        proposed_batch_hash = command_batch_hash(outcome.batch)
        replay_descriptor, replay_reference = await self._write_replay_manifest(
            operation=evidence.operation,
            context_manifest_hash=run.context_object_hash,
            ordered_input_object_hashes=(run.outcome_object_hash,),
            task_id=run.task_id,
            execution_process_id=run.execution_process_id,
            submission_id=run.submission_id,
            submission_hash=run.submission_request_hash,
            ordered_command_batch_hashes=(proposed_batch_hash,),
            base_checkpoint_hash=run.base_document_hash,
            base_sequence_no=run.base_head_sequence_no,
            result_checkpoint_hash=None,
            result_sequence_no=run.base_head_sequence_no,
            renderer_input_hash=None,
            renderer_output_hash=None,
            validation_report_hashes=(),
            terminal_status="stale",
            error_code="draft_conflict",
        )
        completed_evidence, transition = self._finish_pipeline(
            evidence,
            output_hash=replay_descriptor.content_hash,
            evidence_kind="replay_manifest",
            evidence_ref=replay_descriptor.content_hash,
        )
        now = self._now()
        assistant_id = _stable_id(run.id, "assistant-message")
        stale = replace(
            run,
            assistant_message_id=assistant_id,
            status="stale",
            proposed_command_batch_json=canonical_model_json(outcome.batch),
            proposed_command_batch_hash=proposed_batch_hash,
            summary=outcome.summary,
            replay_manifest_object_hash=replay_descriptor.content_hash,
            error_code="draft_conflict",
            error_message="prototype draft changed while the AI proposal was being prepared",
            updated_at=now,
            completed_at=now,
        )
        await self._store.transition_ai_edit_run(
            run=stale,
            expected_statuses=("validating",),
            assistant_message=PrototypeAiMessageRecord(
                id=assistant_id,
                thread_id=run.thread_id,
                client_message_id=None,
                role="assistant",
                kind="proposal",
                content=outcome.message,
                run_id=run.id,
                command_batch_id=None,
                status="failed",
                created_at=now,
                updated_at=now,
            ),
            descriptors_and_references=((replay_descriptor, replay_reference),),
            operation_transitions=(*validation_transitions, transition),
        )
        evidence.operation = completed_evidence.operation
        evidence.step = completed_evidence.step

    async def _fail_run(
        self,
        run_id: str,
        exc: BaseException,
        evidence: _PipelineEvidence | None,
    ) -> None:
        run = await self._store.load_ai_edit_run(run_id)
        if run is None or run.status in TERMINAL_AI_RUN_STATUSES or run.status == "preview_ready":
            return
        error_code = _error_code(exc)
        safe_message = _safe_error_message(error_code)
        now = self._now()
        operation = await self._store.load_operation(run.operation_id)
        if operation is None or operation.status in {"succeeded", "failed", "interrupted"}:
            logger.error(
                "prototype AI run failure could not update operation: run_id=%s code=%s",
                run.id,
                error_code,
            )
            return
        if evidence is None:
            steps, events = await asyncio.gather(
                self._store.list_operation_steps(run.operation_id),
                self._store.list_operation_events(run.operation_id),
            )
            running_steps = [step for step in steps if step.status == "running"]
            active_step = running_steps[-1] if running_steps else None
            evidence = _PipelineEvidence(
                operation=operation,
                step=active_step,
                next_event_no=max((event.event_no for event in events), default=-1) + 1,
                next_step_ordinal=max((step.step_ordinal for step in steps), default=-1) + 1,
            )
        failure_hash = _hash_json(
            {"runId": run.id, "operationId": run.operation_id, "errorCode": error_code}
        )
        failed_operation, failed_step, failed_event = self._failure_transition(
            evidence,
            error_code=error_code,
            failure_hash=failure_hash,
        )
        assistant_id = _stable_id(run.id, "assistant-message")
        failed_run = replace(
            run,
            assistant_message_id=assistant_id,
            status="failed",
            error_code=error_code,
            error_message=safe_message,
            updated_at=now,
            completed_at=now,
        )
        message = PrototypeAiMessageRecord(
            id=assistant_id,
            thread_id=run.thread_id,
            client_message_id=None,
            role="assistant",
            kind="error",
            content=safe_message,
            run_id=run.id,
            command_batch_id=None,
            status="failed",
            created_at=now,
            updated_at=now,
        )
        try:
            await self._store.transition_ai_edit_run(
                run=failed_run,
                expected_statuses=(run.status,),
                assistant_message=message,
                operation_transitions=((failed_operation, failed_step, failed_event),),
            )
        except StructuredPrototypeStoreError:
            logger.exception(
                "prototype AI failure persistence failed: run_id=%s code=%s",
                run.id,
                error_code,
            )

    def _build_context(
        self,
        document: PrototypeDocumentV1,
        run: PrototypeAiEditRunRecord,
        selection: PrototypeAiSelectionV1,
        thread: PrototypeAiThreadSnapshot,
    ) -> dict[str, object]:
        selected_page = next(
            (page for page in document.pages if page.id == selection.page_id),
            None,
        )
        context: dict[str, object] = {
            "contractVersion": AI_EDIT_CONTEXT_CONTRACT_VERSION,
            "documentSchemaVersion": DOCUMENT_SCHEMA_VERSION,
            "commandContractVersion": COMMAND_CONTRACT_VERSION,
            "promptVersion": AI_EDIT_PROMPT_VERSION,
            "documentId": document.id,
            "draftId": run.draft_id,
            "baseHeadSequenceNo": run.base_head_sequence_no,
            "baseDocumentHash": run.base_document_hash,
            "locale": document.locale,
            "selection": selection.model_dump(mode="json", by_alias=True),
            "tokens": document.tokens.model_dump(mode="json", by_alias=True),
            "componentDefinitions": [
                definition.model_dump(mode="json", by_alias=True)
                for definition in document.component_definitions
            ],
            "recentMessages": [
                {
                    "id": message.id,
                    "role": message.role,
                    "kind": message.kind,
                    "content": message.content,
                    "status": message.status,
                }
                for message in thread.messages[-20:]
                if message.id != run.user_message_id
            ],
        }
        if selection.scope == "flow":
            flow, rule, source_page, target_pages = _flow_scope_projection(document, selection)
            context["flow"] = flow.model_dump(mode="json", by_alias=True)
            context["rule"] = rule.model_dump(mode="json", by_alias=True)
            context["page"] = source_page.model_dump(mode="json", by_alias=True)
            context["targetPages"] = [
                page.model_dump(mode="json", by_alias=True) for page in target_pages
            ]
            context["runtime"] = _runtime_scope_payload(
                _runtime_scope_slice(document, {rule.trigger.node_id})
            )
        elif selection.scope == "document":
            context["document"] = document_payload(document)
        elif selected_page is not None:
            selected_page_node_ids = _node_ids(selected_page.root)
            context["page"] = selected_page.model_dump(mode="json", by_alias=True)
            context["navigation"] = document.navigation.model_dump(mode="json", by_alias=True)
            context["flows"] = [
                flow.model_dump(mode="json", by_alias=True)
                for flow in document.flows
                if flow.from_node_id in selected_page_node_ids
                or flow.to_page_id == selected_page.id
            ]
            if selection.scope in {"selection", "page"}:
                scoped_node_ids = _selection_node_ids(selected_page.root, selection)
                context["runtime"] = _runtime_scope_payload(
                    _runtime_scope_slice(document, scoped_node_ids)
                )
        return context

    @staticmethod
    def _validate_selection(
        document: PrototypeDocumentV1,
        selection: PrototypeAiSelectionV1,
    ) -> None:
        page = next((item for item in document.pages if item.id == selection.page_id), None)
        if selection.scope in {"selection", "page"} and page is None:
            raise StructuredPrototypeAiServiceError(
                "context_invalid", "prototype AI selection requires an existing page"
            )
        if selection.scope == "selection":
            if not selection.selected_node_ids or page is None:
                raise StructuredPrototypeAiServiceError(
                    "context_invalid", "prototype AI selection scope requires selected nodes"
                )
            page_ids = _node_ids(page.root)
            if not set(selection.selected_node_ids).issubset(page_ids):
                raise StructuredPrototypeAiServiceError(
                    "context_invalid", "prototype AI selection contains an unknown node"
                )
        if selection.scope == "flow" and (
            selection.flow_id is None
            or not any(flow.id == selection.flow_id for flow in document.flows)
        ):
            raise StructuredPrototypeAiServiceError(
                "context_invalid", "prototype AI flow scope requires an existing flow"
            )

    @staticmethod
    def _validate_command_scope(
        document: PrototypeDocumentV1,
        batch: DomainCommandBatchV1,
        selection: PrototypeAiSelectionV1,
    ) -> None:
        if selection.scope == "document":
            return
        if selection.scope == "flow":
            _, selected_rule, source_page, target_pages = _flow_scope_projection(
                document, selection
            )
            allowed_node_ids = _node_ids(source_page.root)
            for target_page in target_pages:
                allowed_node_ids.update(_node_ids(target_page.root))
            allowed = (
                allowed_node_ids
                | {source_page.id, *(page.id for page in target_pages)}
                | _runtime_scope_ids(
                    _runtime_scope_slice(document, {selected_rule.trigger.node_id})
                )
            )
            for command in batch.commands:
                if isinstance(command, AddBehaviorRuleCommandV1):
                    raise StructuredPrototypeAiServiceError(
                        "scope_violation",
                        "prototype AI flow scope cannot add an unrelated behavior rule",
                    )
                if not isinstance(
                    command,
                    (ReplaceBehaviorRuleCommandV1, RemoveBehaviorRuleCommandV1),
                ):
                    raise StructuredPrototypeAiServiceError(
                        "scope_violation",
                        "prototype AI flow scope only edits its selected behavior rule",
                    )
                if command.rule_id != selected_rule.id:
                    raise StructuredPrototypeAiServiceError(
                        "scope_violation",
                        "prototype AI flow command targets another behavior rule",
                    )
                if not _command_existing_ids(command).issubset(allowed):
                    raise StructuredPrototypeAiServiceError(
                        "scope_violation",
                        "prototype AI flow command references an entity outside scope",
                    )
            return
        page = next((item for item in document.pages if item.id == selection.page_id), None)
        if page is None:
            raise StructuredPrototypeAiServiceError(
                "context_invalid", "prototype AI command page does not exist"
            )
        allowed_node_ids = _selection_node_ids(page.root, selection)
        contextual_flows = [
            flow
            for flow in document.flows
            if flow.from_node_id in allowed_node_ids or flow.to_page_id == page.id
        ]
        allowed_page_ids = {
            page.id,
            *(item.target_page_id for item in document.navigation.items),
            *(flow.to_page_id for flow in contextual_flows if flow.to_page_id is not None),
        }
        allowed = (
            allowed_node_ids
            | allowed_page_ids
            | _runtime_scope_ids(_runtime_scope_slice(document, allowed_node_ids))
        )
        for command in batch.commands:
            if isinstance(command, AddPageCommandV1):
                if selection.scope != "page" or command.after_page_id != page.id:
                    raise StructuredPrototypeAiServiceError(
                        "scope_violation",
                        "prototype AI page add exceeds the selected scope",
                    )
                continue
            if isinstance(
                command,
                (DuplicatePageCommandV1, RenamePageCommandV1, DeletePageCommandV1),
            ):
                if selection.scope != "page" or command.page_id != page.id:
                    raise StructuredPrototypeAiServiceError(
                        "scope_violation",
                        "prototype AI page command exceeds the selected scope",
                    )
                continue
            if command.kind == "reorderPage":
                if selection.scope != "page" or command.page_id != page.id:
                    raise StructuredPrototypeAiServiceError(
                        "scope_violation", "prototype AI page reorder exceeds the selected scope"
                    )
                continue
            existing_ids = _command_existing_ids(command)
            if not existing_ids.issubset(allowed):
                raise StructuredPrototypeAiServiceError(
                    "scope_violation", "prototype AI command references an entity outside scope"
                )

    def _start_pipeline(
        self,
        operation: PrototypeOperation,
        phase: str,
    ) -> tuple[
        _PipelineEvidence,
        tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent],
    ]:
        now = self._now()
        running = replace(operation, status="running", phase=phase, started_at=now)
        step = self._new_step(
            running, ordinal=0, phase=phase, input_hash=operation.request_manifest_hash
        )
        event = self._step_event(step, event_no=1, event_kind="step_started")
        return (
            _PipelineEvidence(
                operation=running,
                step=step,
                next_event_no=2,
                next_step_ordinal=1,
            ),
            (running, step, event),
        )

    def _advance_pipeline(
        self,
        evidence: _PipelineEvidence,
        *,
        next_phase: str,
        completed_output_hash: str,
        evidence_kind: str,
        evidence_ref: str,
    ) -> tuple[
        _PipelineEvidence,
        tuple[
            tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent],
            tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent],
        ],
    ]:
        if evidence.step is None:
            raise StructuredPrototypeAiServiceError(
                "completion_evidence_missing", "prototype AI pipeline has no active step"
            )
        now = self._now()
        completed_step = replace(
            evidence.step,
            status="succeeded",
            output_manifest_hash=completed_output_hash,
            completion_evidence_kind=evidence_kind,
            completion_evidence_ref=evidence_ref,
            completed_at=now,
        )
        completed_operation = replace(evidence.operation, phase=evidence.step.phase)
        completed_event = self._step_event(
            completed_step,
            event_no=evidence.next_event_no,
            event_kind="step_succeeded",
        )
        running_operation = replace(completed_operation, phase=next_phase)
        next_step = self._new_step(
            running_operation,
            ordinal=evidence.next_step_ordinal,
            phase=next_phase,
            input_hash=completed_output_hash,
        )
        started_event = self._step_event(
            next_step,
            event_no=evidence.next_event_no + 1,
            event_kind="step_started",
        )
        return (
            _PipelineEvidence(
                operation=running_operation,
                step=next_step,
                next_event_no=evidence.next_event_no + 2,
                next_step_ordinal=evidence.next_step_ordinal + 1,
            ),
            (
                (completed_operation, completed_step, completed_event),
                (running_operation, next_step, started_event),
            ),
        )

    def _finish_pipeline(
        self,
        evidence: _PipelineEvidence,
        *,
        output_hash: str,
        evidence_kind: str,
        evidence_ref: str,
    ) -> tuple[
        _PipelineEvidence,
        tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent],
    ]:
        if evidence.step is None:
            raise StructuredPrototypeAiServiceError(
                "completion_evidence_missing", "prototype AI pipeline has no active step"
            )
        now = self._now()
        step = replace(
            evidence.step,
            status="succeeded",
            output_manifest_hash=output_hash,
            completion_evidence_kind=evidence_kind,
            completion_evidence_ref=evidence_ref,
            completed_at=now,
        )
        operation = replace(
            evidence.operation,
            status="succeeded",
            phase=step.phase,
            result_manifest_hash=output_hash,
            completed_at=now,
        )
        event = self._step_event(
            step,
            event_no=evidence.next_event_no,
            event_kind="step_succeeded",
        )
        return replace(evidence, operation=operation, step=step), (operation, step, event)

    def _failure_transition(
        self,
        evidence: _PipelineEvidence,
        *,
        error_code: str,
        failure_hash: str,
    ) -> tuple[PrototypeOperation, PrototypeOperationStep, PrototypeOperationEvent]:
        now = self._now()
        operation = replace(
            evidence.operation,
            status="failed",
            failure_evidence_hash=failure_hash,
            error_code=error_code,
            completed_at=now,
        )
        if evidence.step is None:
            step = PrototypeOperationStep(
                id=_stable_id(operation.id, "step", "0"),
                operation_id=operation.id,
                parent_step_id=None,
                step_kind=operation.phase,
                step_ordinal=0,
                attempt=1,
                status="failed",
                phase=operation.phase,
                input_manifest_hash=operation.request_manifest_hash,
                config_manifest_hash=operation.config_manifest_hash,
                output_manifest_hash=None,
                completion_evidence_kind=None,
                completion_evidence_ref=None,
                error_code=error_code,
                started_at=None,
                completed_at=now,
            )
        else:
            step = replace(
                evidence.step,
                status="failed",
                error_code=error_code,
                completed_at=now,
            )
        event = PrototypeOperationEvent(
            operation_id=operation.id,
            event_no=evidence.next_event_no,
            step_id=step.id,
            event_kind="step_failed",
            status="failed",
            phase=step.phase,
            input_hash=step.input_manifest_hash,
            output_hash=None,
            evidence_hash=failure_hash,
            error_code=error_code,
            occurred_at=now,
        )
        return operation, step, event

    def _new_step(
        self,
        operation: PrototypeOperation,
        *,
        ordinal: int,
        phase: str,
        input_hash: str,
    ) -> PrototypeOperationStep:
        now = self._now()
        return PrototypeOperationStep(
            id=_stable_id(operation.id, "step", str(ordinal)),
            operation_id=operation.id,
            parent_step_id=None,
            step_kind=phase,
            step_ordinal=ordinal,
            attempt=1,
            status="running",
            phase=phase,
            input_manifest_hash=input_hash,
            config_manifest_hash=operation.config_manifest_hash,
            output_manifest_hash=None,
            completion_evidence_kind=None,
            completion_evidence_ref=None,
            error_code=None,
            started_at=now,
            completed_at=None,
        )

    def _step_event(
        self,
        step: PrototypeOperationStep,
        *,
        event_no: int,
        event_kind: str,
    ) -> PrototypeOperationEvent:
        return PrototypeOperationEvent(
            operation_id=step.operation_id,
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

    async def _require_document(self, document_id: str) -> PrototypeDocumentRecord:
        document = await self._store.load_document(document_id)
        if document is None:
            raise StructuredPrototypeAiServiceError(
                "document_missing", "prototype document does not exist"
            )
        return document

    async def _write_replay_manifest(
        self,
        *,
        operation: PrototypeOperation,
        context_manifest_hash: str | None,
        ordered_input_object_hashes: tuple[str | None, ...],
        task_id: str | None,
        execution_process_id: str | None,
        submission_id: str | None,
        submission_hash: str | None,
        ordered_command_batch_hashes: tuple[str, ...],
        base_checkpoint_hash: str | None,
        base_sequence_no: int | None,
        result_checkpoint_hash: str | None,
        result_sequence_no: int | None,
        renderer_input_hash: str | None,
        renderer_output_hash: str | None,
        validation_report_hashes: tuple[str, ...],
        terminal_status: str,
        error_code: str | None = None,
    ) -> tuple[PrototypeObjectDescriptor, PrototypeObjectReference]:
        if (
            context_manifest_hash is None
            or task_id is None
            or execution_process_id is None
            or submission_id is None
            or submission_hash is None
            or any(content_hash is None for content_hash in ordered_input_object_hashes)
        ):
            raise StructuredPrototypeAiServiceError(
                "completion_evidence_missing",
                "prototype AI replay manifest inputs are incomplete",
                operation_id=operation.id,
            )
        identity = self._renderer_worker.identity
        agent_identity: dict[str, object]
        if task_id.startswith("external-agent:"):
            _, agent_kind, pairing_id = task_id.split(":", maxsplit=2)
            agent_identity = {
                "role": "external_prototype_agent",
                "executor": "claude" if agent_kind == "claude_code" else "codex",
                "agentKind": agent_kind,
                "pairingId": pairing_id,
                "taskId": task_id,
                "executionProcessId": execution_process_id,
            }
        else:
            agent_identity = {
                "role": "prototype_ui_engineer",
                "executor": "claude",
                "taskId": task_id,
                "executionProcessId": execution_process_id,
            }
        manifest = {
            "manifestVersion": AI_REPLAY_MANIFEST_VERSION,
            "operationId": operation.id,
            "operationKind": operation.operation_kind,
            "parentOperationId": operation.parent_operation_id,
            "requestManifestHash": operation.request_manifest_hash,
            "contextManifestHash": context_manifest_hash,
            "orderedInputObjectHashes": list(ordered_input_object_hashes),
            "versions": {
                "serviceVersion": AI_EDIT_CONFIG_VERSION,
                "promptVersion": AI_EDIT_PROMPT_VERSION,
                "documentSchemaVersion": DOCUMENT_SCHEMA_VERSION,
                "commandContractVersion": COMMAND_CONTRACT_VERSION,
                "contextBuilderVersion": AI_EDIT_CONTEXT_CONTRACT_VERSION,
                "replayManifestVersion": AI_REPLAY_MANIFEST_VERSION,
                "rendererVersion": identity.renderer_version,
                "rendererEnvironmentVersion": identity.renderer_environment_version,
                "runtimeCoreVersion": identity.runtime_core_version,
                "runtimeCoreBundleHash": identity.runtime_core_bundle_hash,
                "stateMachineKernelVersion": identity.state_machine_kernel_version,
            },
            "agentTaskIdentity": agent_identity,
            "submissionId": submission_id,
            "submissionHash": submission_hash,
            "orderedCommandBatchHashes": list(ordered_command_batch_hashes),
            "baseCheckpointHash": base_checkpoint_hash,
            "baseSequenceNo": base_sequence_no,
            "resultCheckpointHash": result_checkpoint_hash,
            "resultSequenceNo": result_sequence_no,
            "rendererInputHash": renderer_input_hash,
            "rendererOutputHash": renderer_output_hash,
            "runtimeSessionId": None,
            "runtimeCoreBundleHash": identity.runtime_core_bundle_hash,
            "orderedRuntimeEventHashes": [],
            "runtimeFinalStateHash": None,
            "runtimeFinalViewModelHash": None,
            "validationReportHashes": list(validation_report_hashes),
            "terminalStatus": terminal_status,
            "errorCode": error_code,
        }
        descriptor = await asyncio.to_thread(
            self._object_store.write_json,
            operation.project_id,
            manifest,
        )
        return descriptor, self._reference(
            project_id=operation.project_id,
            owner_kind="replay_manifest",
            owner_id=operation.id,
            role="operation-replay",
            descriptor=descriptor,
            payload_type="replay_manifest",
            schema_version=AI_REPLAY_MANIFEST_VERSION,
        )

    def _reference(
        self,
        *,
        project_id: str,
        owner_kind: PrototypeObjectOwnerKind,
        owner_id: str,
        role: str,
        descriptor: PrototypeObjectDescriptor,
        payload_type: PrototypeObjectPayloadType,
        schema_version: int,
    ) -> PrototypeObjectReference:
        return PrototypeObjectReference(
            project_id=project_id,
            owner_kind=owner_kind,
            owner_id=owner_id,
            role=role,
            content_hash=descriptor.content_hash,
            payload_type=payload_type,
            schema_version=schema_version,
            created_at=self._now(),
        )

    def _now(self) -> datetime:
        now = self._clock()
        return now if now.utcoffset() is not None else now.replace(tzinfo=UTC)


def _stable_id(*parts: str) -> str:
    return str(uuid5(AI_SERVICE_NAMESPACE, ":".join(parts)))


def _require_uuid(value: str, code: str) -> None:
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise StructuredPrototypeAiServiceError(
            code, "prototype request ID must be a UUID"
        ) from exc
    if str(parsed) != value:
        raise StructuredPrototypeAiServiceError(
            code, "prototype request ID must use canonical lowercase UUID form"
        )


def _hash_json(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _hash_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _node_ids(node: UINodeV1) -> set[str]:
    result = {node.id}
    if isinstance(node, (StackNodeV1, GridNodeV1, FormNodeV1, FreeformNodeV1)):
        for child in node.children:
            result.update(_node_ids(child))
    return result


def _find_node_payload(node: UINodeV1, node_id: str) -> UINodeV1 | None:
    if node.id == node_id:
        return node
    if not isinstance(node, (StackNodeV1, GridNodeV1, FormNodeV1, FreeformNodeV1)):
        return None
    for child in node.children:
        found = _find_node_payload(child, node_id)
        if found is not None:
            return found
    return None


def _selection_node_ids(
    page_root: UINodeV1,
    selection: PrototypeAiSelectionV1,
) -> set[str]:
    if selection.scope != "selection":
        return _node_ids(page_root)
    result: set[str] = set()
    for node_id in selection.selected_node_ids:
        subtree = _find_node_payload(page_root, node_id)
        if subtree is not None:
            result.update(_node_ids(subtree))
    return result


def _flow_scope_projection(
    document: PrototypeDocumentV1,
    selection: PrototypeAiSelectionV1,
) -> tuple[PrototypeFlowV1, RuntimeRuleV1, PrototypePageV1, tuple[PrototypePageV1, ...]]:
    flow = next((item for item in document.flows if item.id == selection.flow_id), None)
    if flow is None:
        raise StructuredPrototypeAiServiceError(
            "context_invalid", "prototype AI flow scope requires an existing flow"
        )
    rule = next((item for item in document.runtime.rules if item.id == flow.rule_id), None)
    if rule is None:
        raise StructuredPrototypeAiServiceError(
            "context_invalid", "prototype AI flow scope rule does not exist"
        )
    source_page = next(
        (page for page in document.pages if rule.trigger.node_id in _node_ids(page.root)),
        None,
    )
    if source_page is None:
        raise StructuredPrototypeAiServiceError(
            "context_invalid", "prototype AI flow scope trigger has no source page"
        )
    pages_by_id = {page.id: page for page in document.pages}
    target_pages: list[PrototypePageV1] = []
    seen_page_ids: set[str] = set()
    for effect in (*rule.effects, *rule.guard_false_effects):
        if not isinstance(effect, NavigateEffectV1) or effect.target_page_id in seen_page_ids:
            continue
        target_page = pages_by_id.get(effect.target_page_id)
        if target_page is None:
            raise StructuredPrototypeAiServiceError(
                "context_invalid", "prototype AI flow scope target page does not exist"
            )
        seen_page_ids.add(target_page.id)
        target_pages.append(target_page)
    return flow, rule, source_page, tuple(target_pages)


def _nodes_in_scope(
    document: PrototypeDocumentV1,
    node_ids: set[str],
) -> tuple[UINodeV1, ...]:
    result: list[UINodeV1] = []

    def collect(node: UINodeV1) -> None:
        if node.id in node_ids:
            result.append(node)
        if isinstance(node, (StackNodeV1, GridNodeV1, FormNodeV1, FreeformNodeV1)):
            for child in node.children:
                collect(child)

    for page in document.pages:
        collect(page.root)
    for definition in document.component_definitions:
        collect(definition.root)
    return tuple(result)


def _runtime_value_reference_ids(value: RuntimeValueV1) -> set[str]:
    if isinstance(value, EntityRefRuntimeValueV1):
        return {value.schema_id}
    return set()


def _runtime_expression_reference_ids(expression: RuntimeExpressionV1) -> set[str]:
    if isinstance(expression, LiteralExpressionV1):
        return _runtime_value_reference_ids(expression.value)
    if isinstance(expression, VariableExpressionV1):
        return {expression.variable_id}
    if isinstance(expression, FormFieldExpressionV1):
        return {expression.form_id, expression.field_id}
    if isinstance(expression, EventEntityRefExpressionV1):
        return set()
    if isinstance(expression, EntityFieldExpressionV1):
        return (
            _runtime_expression_reference_ids(expression.entity_ref)
            | {expression.field_id}
            | _runtime_value_reference_ids(expression.fallback)
        )
    raise AssertionError("runtime expression union is exhaustive")


def _runtime_predicate_reference_ids(predicate: RuntimePredicateV1) -> set[str]:
    if isinstance(predicate, AllPredicateV1):
        result: set[str] = set()
        for item in predicate.items:
            result.update(_runtime_predicate_reference_ids(item))
        return result
    if isinstance(predicate, RoleIsPredicateV1):
        return {predicate.role_id}
    if isinstance(predicate, FormValidPredicateV1):
        return {predicate.form_id}
    if isinstance(predicate, ComparePredicateV1):
        return _runtime_expression_reference_ids(
            predicate.left
        ) | _runtime_expression_reference_ids(predicate.right)
    raise AssertionError("runtime predicate union is exhaustive")


def _runtime_effect_reference_ids(effect: RuntimeEffectV1) -> set[str]:
    if isinstance(effect, SetVariableEffectV1):
        return {effect.variable_id} | _runtime_expression_reference_ids(effect.value)
    if isinstance(effect, ValidateFormEffectV1):
        return {effect.form_id}
    if isinstance(effect, CreateEntityEffectV1):
        result = {effect.schema_id, effect.result_variable_id}
        for assignment in effect.values:
            result.add(assignment.field_id)
            result.update(_runtime_expression_reference_ids(assignment.value))
        return result
    if isinstance(effect, UpdateEntityEffectV1):
        result = {effect.schema_id} | _runtime_expression_reference_ids(effect.entity_ref)
        for assignment in effect.updates:
            result.add(assignment.field_id)
            result.update(_runtime_expression_reference_ids(assignment.value))
        return result
    if isinstance(effect, NavigateEffectV1):
        return {effect.target_page_id}
    if isinstance(effect, NotifyEffectV1):
        return set()
    raise AssertionError("runtime effect union is exhaustive")


def _behavior_rule_definition_reference_ids(
    definition: RuntimeRuleDefinitionV1,
) -> set[str]:
    result = {definition.trigger.node_id}
    if definition.guard is not None:
        result.update(_runtime_predicate_reference_ids(definition.guard))
    for effect in (*definition.effects, *definition.guard_false_effects):
        result.update(_runtime_effect_reference_ids(effect))
    return result


def _behavior_rule_reference_ids(rule: RuntimeRuleV1) -> set[str]:
    result = {rule.trigger.node_id}
    if rule.guard is not None:
        result.update(_runtime_predicate_reference_ids(rule.guard))
    for effect in (*rule.effects, *rule.guard_false_effects):
        result.update(_runtime_effect_reference_ids(effect))
    return result


def _runtime_view_binding_reference_ids(binding: RuntimeViewBindingV1) -> set[str]:
    if isinstance(binding, TextViewBindingV1):
        return _runtime_expression_reference_ids(binding.value)
    if isinstance(binding, VisibilityViewBindingV1):
        return _runtime_predicate_reference_ids(binding.predicate)
    if isinstance(binding, TableRowsViewBindingV1):
        result = {binding.schema_id}
        if binding.sort_field_id is not None:
            result.add(binding.sort_field_id)
        return result
    raise AssertionError("runtime view-binding union is exhaustive")


def _runtime_scope_slice(
    document: PrototypeDocumentV1,
    node_ids: set[str],
) -> _RuntimeScopeSlice:
    view_bindings = tuple(
        binding for binding in document.runtime.view_bindings if binding.node_id in node_ids
    )
    rules = tuple(rule for rule in document.runtime.rules if rule.trigger.node_id in node_ids)
    referenced_ids: set[str] = set()
    for binding in view_bindings:
        referenced_ids.update(_runtime_view_binding_reference_ids(binding))
    for rule in rules:
        referenced_ids.update(_behavior_rule_reference_ids(rule))
    for node in _nodes_in_scope(document, node_ids):
        if isinstance(node, FormNodeV1):
            referenced_ids.add(node.form_definition_id)
        elif isinstance(node, InputNodeV1) and node.form_definition_id is not None:
            referenced_ids.add(node.form_definition_id)
            assert node.form_field_id is not None
            referenced_ids.add(node.form_field_id)

    roles = tuple(role for role in document.runtime.roles if role.id in referenced_ids)
    variables = tuple(
        variable for variable in document.runtime.variables if variable.id in referenced_ids
    )
    referenced_ids.update(
        variable.entity_schema_id for variable in variables if variable.entity_schema_id is not None
    )
    forms = tuple(
        form
        for form in document.runtime.forms
        if form.id in referenced_ids or any(field.id in referenced_ids for field in form.fields)
    )
    entity_schemas = tuple(
        schema
        for schema in document.runtime.entity_schemas
        if schema.id in referenced_ids or any(field.id in referenced_ids for field in schema.fields)
    )
    schema_ids = {schema.id for schema in entity_schemas}
    scenario_scopes: list[_RuntimeScenarioScope] = []
    for scenario in document.runtime.scenarios:
        entity_fixtures = tuple(
            fixture for fixture in scenario.entity_fixtures if fixture.schema_id in schema_ids
        )
        if entity_fixtures:
            scenario_scopes.append(
                _RuntimeScenarioScope(
                    scenario=scenario,
                    entity_fixtures=entity_fixtures,
                )
            )
    return _RuntimeScopeSlice(
        roles=roles,
        variables=variables,
        forms=forms,
        view_bindings=view_bindings,
        entity_schemas=entity_schemas,
        rules=rules,
        scenarios=tuple(scenario_scopes),
    )


def _runtime_scope_ids(scope: _RuntimeScopeSlice) -> set[str]:
    result: set[str] = set()
    result.update(role.id for role in scope.roles)
    result.update(variable.id for variable in scope.variables)
    for form in scope.forms:
        result.add(form.id)
        result.update(field.id for field in form.fields)
    result.update(binding.id for binding in scope.view_bindings)
    for schema in scope.entity_schemas:
        result.add(schema.id)
        result.update(field.id for field in schema.fields)
    result.update(rule.id for rule in scope.rules)
    for scenario_scope in scope.scenarios:
        result.add(scenario_scope.scenario.id)
        for fixture in scenario_scope.entity_fixtures:
            result.update(entity.id for entity in fixture.entities)
    return result


def _runtime_scope_payload(scope: _RuntimeScopeSlice) -> dict[str, object]:
    return {
        "roles": [role.model_dump(mode="json", by_alias=True) for role in scope.roles],
        "variables": [
            variable.model_dump(mode="json", by_alias=True) for variable in scope.variables
        ],
        "forms": [form.model_dump(mode="json", by_alias=True) for form in scope.forms],
        "viewBindings": [
            binding.model_dump(mode="json", by_alias=True) for binding in scope.view_bindings
        ],
        "entitySchemas": [
            schema.model_dump(mode="json", by_alias=True) for schema in scope.entity_schemas
        ],
        "rules": [rule.model_dump(mode="json", by_alias=True) for rule in scope.rules],
        "scenarios": [
            {
                "id": scenario_scope.scenario.id,
                "key": scenario_scope.scenario.key,
                "actorRoleId": scenario_scope.scenario.actor_role_id,
                "startPageId": scenario_scope.scenario.start_page_id,
                "entityFixtures": [
                    fixture.model_dump(mode="json", by_alias=True)
                    for fixture in scenario_scope.entity_fixtures
                ],
                "allowSimulatedRoleSwitch": (scenario_scope.scenario.allow_simulated_role_switch),
            }
            for scenario_scope in scope.scenarios
        ],
    }


def _command_existing_ids(command: DomainCommandV1) -> set[str]:
    if isinstance(command, AddBehaviorRuleCommandV1):
        return _behavior_rule_definition_reference_ids(command.definition)
    if isinstance(command, ReplaceBehaviorRuleCommandV1):
        return {command.rule_id} | _behavior_rule_definition_reference_ids(command.definition)
    if isinstance(command, RemoveBehaviorRuleCommandV1):
        return {command.rule_id}
    if isinstance(command, RemoveNodeCommandV1):
        return {command.node_id}
    if isinstance(command, UpdateNodeNameCommandV1):
        return {command.node_id}
    if isinstance(command, AddPageCommandV1):
        return {command.after_page_id}
    if isinstance(
        command,
        (DuplicatePageCommandV1, RenamePageCommandV1, DeletePageCommandV1),
    ):
        return {command.page_id}
    if isinstance(command, InsertNodeCommandV1):
        return {command.parent.node_id} if isinstance(command.parent, ExistingNodeRefV1) else set()
    if isinstance(command, MoveNodeCommandV1):
        result: set[str] = set()
        for reference in (command.node, command.target_parent):
            if isinstance(reference, ExistingNodeRefV1):
                result.add(reference.node_id)
        return result
    if isinstance(command, (SetNodePropertyCommandV1, SetNodeLayoutCommandV1)):
        return {command.node.node_id} if isinstance(command.node, ExistingNodeRefV1) else set()
    if isinstance(command, SetRuntimeEntityFieldCommandV1):
        return {
            command.scenario_id,
            command.schema_id,
            command.entity_id,
            command.field_id,
        }
    raise StructuredPrototypeAiServiceError(
        "scope_validation_unsupported",
        f"prototype AI command scope validation does not support {command.kind}",
    )


def _renderer_input_manifest(
    identity: PrototypeRendererWorkerIdentity,
    *,
    document_object_hash: str,
    output_locale: str,
    asset_object_hashes: list[str],
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
        "assetObjectHashes": sorted(asset_object_hashes),
        "sandboxPolicyVersion": identity.sandbox_policy_version,
        "outputLocale": output_locale,
    }


def _render_run(
    *,
    identity: PrototypeRendererWorkerIdentity,
    run: PrototypeAiEditRunRecord,
    render_run_id: str,
    input_manifest_hash: str,
    artifact_id: str | None,
    status: PrototypeRenderStatus,
    now: datetime,
) -> PrototypeRenderRunRecord:
    if run.candidate_object_hash is None:
        raise StructuredPrototypeAiServiceError(
            "completion_evidence_missing", "prototype AI candidate object hash is missing"
        )
    return PrototypeRenderRunRecord(
        id=render_run_id,
        document_id=run.document_id,
        kind="ai_preview",
        revision_id=None,
        ai_edit_run_id=run.id,
        status=status,
        renderer_version=identity.renderer_version,
        renderer_environment_version=identity.renderer_environment_version,
        runtime_core_version=identity.runtime_core_version,
        runtime_core_source_hash=identity.runtime_core_source_hash,
        runtime_core_bundle_hash=identity.runtime_core_bundle_hash,
        state_machine_kernel_version=identity.state_machine_kernel_version,
        render_runtime_image_hash=identity.render_runtime_image_hash,
        browser_version=identity.browser_version,
        font_pack_hash=identity.font_pack_hash,
        viewport_profile_hash=identity.viewport_profile_hash,
        sandbox_policy_version=identity.sandbox_policy_version,
        input_manifest_hash=input_manifest_hash,
        document_object_hash=run.candidate_object_hash,
        document_hash=run.candidate_object_hash,
        operation_id=run.operation_id,
        attempt=1,
        artifact_id=artifact_id,
        output_manifest_hash=None,
        error_code=None,
        error_message=None,
        started_at=now,
        completed_at=None,
        created_at=now,
        updated_at=now,
    )


def _error_code(exc: BaseException) -> str:
    if isinstance(exc, StructuredPrototypeAiServiceError):
        return exc.code
    if isinstance(exc, (StructuredPrototypeStoreError, StructuredPrototypeContractError)):
        return exc.code
    if isinstance(
        exc,
        (
            PrototypeObjectStoreError,
            PrototypeRenderArtifactStoreError,
            PrototypeRendererWorkerError,
            StructuredPrototypeServiceError,
        ),
    ):
        return exc.code
    if isinstance(exc, PrototypeUiEngineerRunnerError):
        text = str(exc).lower()
        if "requires an available claude" in text or "runtime launch is disabled" in text:
            return "runtime_unavailable"
        if "did not submit" in text:
            return "submission_missing"
        return "agent_task_failed"
    if isinstance(exc, PrototypeUiEngineerRuntimeError):
        return exc.code
    if isinstance(exc, ValueError):
        return "context_invalid"
    return "agent_task_failed"


def _safe_error_message(code: str) -> str:
    return {
        "runtime_unavailable": "项目 Claude Code UI Engineer 当前不可用。",
        "submission_missing": "UI Engineer 未提交可验证的结构化结果。",
        "schema_invalid": "UI Engineer 提交的结果不符合结构化协议。",
        "scope_violation": "UI Engineer 提案超出了当前选择范围。",
        "draft_conflict": "原型已发生变化, 请基于最新版本重新发起修改。",
        "preview_render_failed": "提案已验证, 但隔离预览渲染失败。",
    }.get(code, "AI 修改未完成, 请查看运行证据后重试。")
