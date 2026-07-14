from __future__ import annotations

import hashlib
from typing import Literal, Protocol
from uuid import UUID, uuid5

from pydantic import ValidationError

from app.application.external_prototype_agent_contracts import (
    EXTERNAL_AGENT_PROTOCOL_VERSION,
    ActiveDesignContextResultV1,
    DocumentSliceResultV1,
    ExternalProposalReceiptV1,
    ExternalProposalStatusResultV1,
    ExternalPrototypeRevisionV1,
    GetActiveDesignContextV1,
    GetDocumentSliceV1,
    GetExternalProposalStatusV1,
    SubmitExternalCommandProposalV1,
    ValidateExternalCommandBatchV1,
    canonical_json_bytes,
)
from app.application.external_prototype_agent_service import (
    ExternalCommandValidationResult,
    ExternalPrototypeAgentError,
)
from app.application.structured_prototype_ai_service import (
    StructuredPrototypeAiService,
    StructuredPrototypeAiServiceError,
)
from app.application.structured_prototype_contracts import (
    COMMAND_CONTRACT_VERSION,
    DomainCommandBatchV1,
    FormNodeV1,
    PrototypeDocumentV1,
    PrototypePageV1,
    StackNodeV1,
    StructuredPrototypeContractError,
    UINodeV1,
    command_batch_hash,
    execute_command_batch,
)
from app.application.structured_prototype_service import (
    ActivePrototypeState,
    StructuredPrototypeService,
    StructuredPrototypeServiceError,
)
from app.domain.external_prototype_agent import ExternalAgentPairingRecord
from app.domain.structured_prototype import PrototypeDocumentRecord, PrototypeDraftRecord
from app.domain.structured_prototype_ai import PrototypeAiEditRunRecord
from app.json_safety import JsonObject

EXTERNAL_COLLABORATION_NAMESPACE = UUID("89be0a63-7f54-53a4-90ee-c34e440f14ef")
SUPPORTED_COMMAND_KINDS = (
    "insertNode",
    "moveNode",
    "removeNode",
    "setNodeProperty",
    "setNodeLayout",
    "reorderPage",
)


class StructuredPrototypeCollaborationStore(Protocol):
    async def load_document(self, document_id: str) -> PrototypeDocumentRecord | None: ...

    async def load_draft(self, draft_id: str) -> PrototypeDraftRecord | None: ...


class StructuredPrototypeExternalCollaboration:
    def __init__(
        self,
        *,
        store: StructuredPrototypeCollaborationStore,
        structured_service: StructuredPrototypeService,
        ai_service: StructuredPrototypeAiService,
    ) -> None:
        self._store = store
        self._structured_service = structured_service
        self._ai_service = ai_service

    async def assert_pairing_scope(self, project_id: str, document_id: str) -> None:
        await self._active_records(project_id, document_id)

    async def get_active_design_context(
        self,
        pairing: ExternalAgentPairingRecord,
        request: GetActiveDesignContextV1,
    ) -> ActiveDesignContextResultV1:
        state = await self._recover_active_state(pairing)
        document = state.document
        page = (
            self._page(document, request.scope.page_id)
            if request.scope.page_id is not None
            else None
        )
        selected_nodes = self._selected_nodes(
            document,
            request.scope.selected_node_ids,
            page_id=request.scope.page_id,
        )
        flow = None
        if request.scope.flow_id is not None:
            flow = next(
                (item for item in document.flows if item.id == request.scope.flow_id),
                None,
            )
            if flow is None:
                raise ExternalPrototypeAgentError(
                    "context_invalid", "prototype flow does not exist"
                )
        command_batch_schema = DomainCommandBatchV1.model_json_schema(
            by_alias=True,
            mode="validation",
        )
        context: JsonObject = {
            "document": {
                "id": document.id,
                "title": document.title,
                "locale": document.locale,
                "settings": document.settings.model_dump(mode="json", by_alias=True),
            },
            "scope": request.scope.model_dump(mode="json", by_alias=True),
            "tokens": document.tokens.model_dump(mode="json", by_alias=True),
            "navigation": document.navigation.model_dump(mode="json", by_alias=True),
            "page": page.model_dump(mode="json", by_alias=True) if page is not None else None,
            "selectedNodes": [
                node.model_dump(mode="json", by_alias=True) for node in selected_nodes
            ],
            "flow": flow.model_dump(mode="json", by_alias=True) if flow is not None else None,
            "commandBatchSchema": command_batch_schema,
        }
        truncated = len(canonical_json_bytes(context)) > 250_000
        if truncated:
            context = {
                "document": {
                    "id": document.id,
                    "title": document.title,
                    "locale": document.locale,
                },
                "scope": request.scope.model_dump(mode="json", by_alias=True),
                "page": self._page_summary(page) if page is not None else None,
                "selectedNodes": [self._node_summary(node) for node in selected_nodes],
                "flow": (
                    {
                        "id": flow.id,
                        "key": flow.key,
                        "ruleId": flow.rule_id,
                        "fromNodeId": flow.from_node_id,
                        "toPageId": flow.to_page_id,
                    }
                    if flow is not None
                    else None
                ),
                "commandBatchSchema": command_batch_schema,
            }
        return ActiveDesignContextResultV1.model_validate(
            {
                "protocolVersion": EXTERNAL_AGENT_PROTOCOL_VERSION,
                "projectId": pairing.project_id,
                "documentId": pairing.document_id,
                "revision": self._revision_payload(state.draft),
                "supportedCommandKinds": list(SUPPORTED_COMMAND_KINDS),
                "context": context,
                "truncated": truncated,
            },
            strict=True,
            by_alias=True,
            by_name=False,
        )

    async def get_document_slice(
        self,
        pairing: ExternalAgentPairingRecord,
        request: GetDocumentSliceV1,
    ) -> DocumentSliceResultV1:
        state = await self._recover_active_state(pairing)
        document = state.document
        data = self._slice_data(document, request)
        truncated = len(canonical_json_bytes(data)) > 510_000
        if truncated:
            data = self._slice_summary(document, request)
        return DocumentSliceResultV1.model_validate(
            {
                "protocolVersion": EXTERNAL_AGENT_PROTOCOL_VERSION,
                "projectId": pairing.project_id,
                "documentId": pairing.document_id,
                "revision": self._revision_payload(state.draft),
                "sliceKind": request.slice_kind,
                "data": data,
                "truncated": truncated,
            },
            strict=True,
            by_alias=True,
            by_name=False,
        )

    async def validate_command_batch(
        self,
        pairing: ExternalAgentPairingRecord,
        request: ValidateExternalCommandBatchV1,
    ) -> ExternalCommandValidationResult:
        state = await self._state_at_requested_revision(pairing, request)
        batch = self._parse_batch(request)
        try:
            execution = execute_command_batch(
                state.document,
                batch,
                draft_id=request.draft_id,
                client_request_id=self._stable_id(
                    request.draft_id,
                    command_batch_hash(batch),
                    "external-command-validation",
                ),
            )
        except StructuredPrototypeContractError as exc:
            raise ExternalPrototypeAgentError(exc.code, str(exc)) from exc
        allocated_ids = {entity_id for _, entity_id in execution.allocated_entity_ids}
        affected_entity_ids = tuple(
            sorted(set(execution.affected_entity_ids) - allocated_ids)
        )
        if not affected_entity_ids:
            raise ExternalPrototypeAgentError(
                "command_batch_invalid",
                "external command batch must affect at least one existing prototype entity",
            )
        validation_hash = self._hash_payload(
            {
                "draftId": request.draft_id,
                "headSequenceNo": request.expected_head_sequence_no,
                "documentHash": request.expected_document_hash,
                "commandBatchHash": command_batch_hash(batch),
                "affectedEntityIds": list(affected_entity_ids),
            }
        )
        return ExternalCommandValidationResult(
            affected_entity_ids=affected_entity_ids,
            validation_hash=validation_hash,
        )

    async def submit_command_proposal(
        self,
        pairing: ExternalAgentPairingRecord,
        request: SubmitExternalCommandProposalV1,
        request_hash: str,
        *,
        origin: Literal["external_agent"],
    ) -> ExternalProposalReceiptV1:
        if origin != "external_agent":
            raise ExternalPrototypeAgentError(
                "proposal_origin_invalid", "external proposal origin is invalid"
            )
        await self._state_at_requested_revision(pairing, request)
        batch = self._parse_batch(request)
        try:
            run = await self._ai_service.submit_external_proposal(
                pairing_id=pairing.id,
                agent_kind=pairing.agent_kind,
                client_message_id=request.client_request_id,
                document_id=pairing.document_id,
                draft_id=request.draft_id,
                expected_head_sequence_no=request.expected_head_sequence_no,
                expected_document_hash=request.expected_document_hash,
                content=request.message,
                batch=batch,
                affected_entity_ids=tuple(request.affected_entity_ids),
                request_hash=request_hash,
            )
        except StructuredPrototypeAiServiceError as exc:
            raise self._ai_error(exc) from exc
        return ExternalProposalReceiptV1.model_validate(
            {
                "protocolVersion": EXTERNAL_AGENT_PROTOCOL_VERSION,
                "proposalId": run.id,
                "status": self._external_status(run),
                "requestHash": request_hash,
                "submittedAt": run.created_at.isoformat(),
            },
            strict=True,
            by_alias=True,
            by_name=False,
        )

    async def get_proposal_status(
        self,
        pairing: ExternalAgentPairingRecord,
        request: GetExternalProposalStatusV1,
    ) -> ExternalProposalStatusResultV1:
        try:
            run = await self._ai_service.get_run(request.proposal_id)
        except StructuredPrototypeAiServiceError as exc:
            raise self._ai_error(exc) from exc
        expected_task_id = f"external-agent:{pairing.agent_kind}:{pairing.id}"
        if run.document_id != pairing.document_id or run.task_id != expected_task_id:
            raise ExternalPrototypeAgentError(
                "proposal_missing", "external proposal does not exist in this pairing scope"
            )
        _, draft = await self._active_records(pairing.project_id, pairing.document_id)
        return ExternalProposalStatusResultV1.model_validate(
            {
                "protocolVersion": EXTERNAL_AGENT_PROTOCOL_VERSION,
                "projectId": pairing.project_id,
                "documentId": pairing.document_id,
                "proposalId": run.id,
                "status": self._external_status(run),
                "currentRevision": self._revision_payload(draft),
                "updatedAt": run.updated_at.isoformat(),
            },
            strict=True,
            by_alias=True,
            by_name=False,
        )

    async def _recover_active_state(
        self,
        pairing: ExternalAgentPairingRecord,
    ) -> ActivePrototypeState:
        _, draft = await self._active_records(pairing.project_id, pairing.document_id)
        try:
            recovered = await self._structured_service.recover_draft(
                draft_id=draft.id,
                client_request_id=self._stable_id(
                    pairing.id,
                    str(draft.head_sequence_no),
                    draft.head_document_hash,
                    "external-context-recovery",
                ),
            )
        except StructuredPrototypeServiceError as exc:
            raise self._structured_error(exc) from exc
        return recovered.state

    async def _state_at_requested_revision(
        self,
        pairing: ExternalAgentPairingRecord,
        request: ValidateExternalCommandBatchV1,
    ) -> ActivePrototypeState:
        _, draft = await self._active_records(pairing.project_id, pairing.document_id)
        if (
            request.draft_id != draft.id
            or request.expected_head_sequence_no != draft.head_sequence_no
            or request.expected_document_hash != draft.head_document_hash
        ):
            raise ExternalPrototypeAgentError(
                "stale_base", "proposal base no longer matches the active draft"
            )
        return await self._recover_active_state(pairing)

    async def _active_records(
        self,
        project_id: str,
        document_id: str,
    ) -> tuple[PrototypeDocumentRecord, PrototypeDraftRecord]:
        document = await self._store.load_document(document_id)
        if (
            document is None
            or document.project_id != project_id
            or document.active_draft_id is None
        ):
            raise ExternalPrototypeAgentError(
                "pairing_scope_invalid",
                "project and document are not available for external Agent pairing",
            )
        draft = await self._store.load_draft(document.active_draft_id)
        if draft is None or draft.document_id != document.id or draft.status != "active":
            raise ExternalPrototypeAgentError(
                "pairing_scope_invalid",
                "prototype document has no active draft available for pairing",
            )
        return document, draft

    @staticmethod
    def _parse_batch(request: ValidateExternalCommandBatchV1) -> DomainCommandBatchV1:
        try:
            return DomainCommandBatchV1.model_validate(
                request.batch.model_dump(mode="json", by_alias=True),
                strict=True,
                by_alias=True,
                by_name=False,
            )
        except ValidationError as exc:
            raise ExternalPrototypeAgentError(
                "command_batch_invalid",
                "external command batch does not satisfy the structured prototype contract",
            ) from exc

    @staticmethod
    def _page(document: PrototypeDocumentV1, page_id: str) -> PrototypePageV1:
        page = next((item for item in document.pages if item.id == page_id), None)
        if page is None:
            raise ExternalPrototypeAgentError("context_invalid", "prototype page does not exist")
        return page

    def _selected_nodes(
        self,
        document: PrototypeDocumentV1,
        entity_ids: list[str],
        *,
        page_id: str | None,
    ) -> list[UINodeV1]:
        if not entity_ids:
            return []
        roots: list[UINodeV1]
        if page_id is not None:
            roots = [self._page(document, page_id).root]
        else:
            roots = [page.root for page in document.pages]
            roots.extend(definition.root for definition in document.component_definitions)
        found: dict[str, UINodeV1] = {}
        for root in roots:
            self._collect_nodes(root, set(entity_ids), found)
        missing = set(entity_ids) - set(found)
        if missing:
            raise ExternalPrototypeAgentError(
                "context_invalid", "prototype selection contains unknown entities"
            )
        return [found[entity_id] for entity_id in entity_ids]

    @classmethod
    def _collect_nodes(
        cls,
        node: UINodeV1,
        wanted: set[str],
        found: dict[str, UINodeV1],
    ) -> None:
        if node.id in wanted:
            found[node.id] = node
        if isinstance(node, (StackNodeV1, FormNodeV1)):
            for child in node.children:
                cls._collect_nodes(child, wanted, found)

    def _slice_data(
        self,
        document: PrototypeDocumentV1,
        request: GetDocumentSliceV1,
    ) -> JsonObject:
        if request.slice_kind == "pages":
            if request.page_id is not None:
                return {
                    "pages": [
                        self._page(document, request.page_id).model_dump(
                            mode="json", by_alias=True
                        )
                    ]
                }
            return {"pages": [self._page_summary(page) for page in document.pages]}
        if request.slice_kind == "selection":
            nodes = self._selected_nodes(
                document,
                request.entity_ids,
                page_id=request.page_id,
            )
            return {
                "entities": [node.model_dump(mode="json", by_alias=True) for node in nodes]
            }
        if request.slice_kind == "tokens":
            return {"tokens": document.tokens.model_dump(mode="json", by_alias=True)}
        return {
            "flows": [flow.model_dump(mode="json", by_alias=True) for flow in document.flows],
            "runtime": document.runtime.model_dump(mode="json", by_alias=True),
        }

    def _slice_summary(
        self,
        document: PrototypeDocumentV1,
        request: GetDocumentSliceV1,
    ) -> JsonObject:
        if request.slice_kind == "selection":
            nodes = self._selected_nodes(
                document,
                request.entity_ids,
                page_id=request.page_id,
            )
            return {"entities": [self._node_summary(node) for node in nodes]}
        if request.slice_kind == "runtime_flow":
            return {
                "flows": [
                    {
                        "id": flow.id,
                        "key": flow.key,
                        "ruleId": flow.rule_id,
                        "fromNodeId": flow.from_node_id,
                        "toPageId": flow.to_page_id,
                    }
                    for flow in document.flows
                ],
                "runtime": {
                    "pageIds": list(document.runtime.page_ids),
                    "roleIds": [role.id for role in document.runtime.roles],
                    "scenarioIds": [scenario.id for scenario in document.runtime.scenarios],
                },
            }
        return self._slice_data(document, request)

    @staticmethod
    def _page_summary(page: PrototypePageV1) -> JsonObject:
        return {
            "id": page.id,
            "key": page.key,
            "title": page.title,
            "route": page.route,
            "root": StructuredPrototypeExternalCollaboration._node_summary(page.root),
        }

    @staticmethod
    def _node_summary(node: UINodeV1) -> JsonObject:
        return {"id": node.id, "type": node.type, "name": node.name}

    @staticmethod
    def _revision_payload(draft: PrototypeDraftRecord) -> JsonObject:
        revision = ExternalPrototypeRevisionV1.model_validate(
            {
                "draftId": draft.id,
                "headSequenceNo": draft.head_sequence_no,
                "documentHash": draft.head_document_hash,
                "commandContractVersion": COMMAND_CONTRACT_VERSION,
            },
            strict=True,
            by_alias=True,
            by_name=False,
        )
        return revision.model_dump(mode="json", by_alias=True)

    @staticmethod
    def _external_status(
        run: PrototypeAiEditRunRecord,
    ) -> Literal[
        "preview_pending",
        "preview_ready",
        "applied",
        "rejected",
        "stale",
        "failed",
    ]:
        if run.status in {
            "queued",
            "building_context",
            "generating",
            "validating",
            "rendering_preview",
        }:
            return "preview_pending"
        if run.status in {"preview_ready", "applied", "rejected", "stale"}:
            return run.status
        return "failed"

    @staticmethod
    def _structured_error(
        error: StructuredPrototypeServiceError,
    ) -> ExternalPrototypeAgentError:
        if error.code == "draft_conflict":
            return ExternalPrototypeAgentError("stale_base", str(error))
        return ExternalPrototypeAgentError(error.code, str(error))

    @staticmethod
    def _ai_error(error: StructuredPrototypeAiServiceError) -> ExternalPrototypeAgentError:
        mapping = {
            "ai_run_missing": "proposal_missing",
            "draft_conflict": "stale_base",
            "document_missing": "pairing_scope_invalid",
            "draft_missing": "stale_base",
        }
        return ExternalPrototypeAgentError(mapping.get(error.code, error.code), str(error))

    @staticmethod
    def _stable_id(*parts: str) -> str:
        return str(uuid5(EXTERNAL_COLLABORATION_NAMESPACE, "\x1f".join(parts)))

    @staticmethod
    def _hash_payload(value: object) -> str:
        return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"
