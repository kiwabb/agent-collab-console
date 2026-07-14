from __future__ import annotations

import hashlib
import json
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol, TypeVar, cast
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import ValidationError

from app.application.external_prototype_agent_contracts import (
    EXTERNAL_AGENT_PROTOCOL_VERSION,
    PROTOTYPE_DESIGNER_SKILL_VERSION,
    SHA256_PATTERN,
    ActiveDesignContextResultV1,
    CreateExternalAgentPairingV1,
    DocumentSliceResultV1,
    ExternalProposalReceiptV1,
    ExternalProposalStatusResultV1,
    GetActiveDesignContextV1,
    GetDocumentSliceV1,
    GetExternalProposalStatusV1,
    StrictExternalAgentModel,
    SubmitExternalCommandProposalV1,
    ValidateExternalCommandBatchV1,
    canonical_model_payload,
    canonical_request_hash,
)
from app.domain.external_prototype_agent import (
    ExternalAgentAuditEvent,
    ExternalAgentAuditOutcome,
    ExternalAgentPairingRecord,
    ExternalAgentSubmissionClaim,
    ExternalAgentSubmissionRecord,
    IssuedExternalAgentPairing,
)
from app.json_safety import JsonObject, parse_json_object

MCP_SERVER_ID = "prototype-collaboration"
MCP_PATH = "/api/internal/external-prototype-agent-mcp"
SKILL_PACKAGE_PATH = "integrations/local-agent/skills/prototype-designer"
PAIRING_TOKEN_BYTES = 32

READ_TOOLS = frozenset(
    {
        "get_prototype_capabilities",
        "get_active_design_context",
        "get_document_slice",
        "get_proposal_status",
    }
)
PROPOSE_TOOLS = frozenset({"validate_command_batch", "submit_command_proposal"})
ALL_TOOLS = READ_TOOLS | PROPOSE_TOOLS
ExternalAgentModelT = TypeVar("ExternalAgentModelT", bound=StrictExternalAgentModel)

TOOL_INPUT_MODELS: dict[str, type[StrictExternalAgentModel] | None] = {
    "get_prototype_capabilities": None,
    "get_active_design_context": GetActiveDesignContextV1,
    "get_document_slice": GetDocumentSliceV1,
    "validate_command_batch": ValidateExternalCommandBatchV1,
    "submit_command_proposal": SubmitExternalCommandProposalV1,
    "get_proposal_status": GetExternalProposalStatusV1,
}


@dataclass(frozen=True, slots=True)
class ExternalCommandValidationResult:
    affected_entity_ids: tuple[str, ...]
    validation_hash: str

    def __post_init__(self) -> None:
        if (
            not self.affected_entity_ids
            or len(self.affected_entity_ids) != len(set(self.affected_entity_ids))
            or any(not value for value in self.affected_entity_ids)
        ):
            raise ValueError("validated affected entity IDs must be non-empty and unique")
        if SHA256_PATTERN.fullmatch(self.validation_hash) is None:
            raise ValueError("validation hash must be a SHA-256 digest")


class StructuredPrototypeCollaborationPort(Protocol):
    async def assert_pairing_scope(self, project_id: str, document_id: str) -> None: ...

    async def get_active_design_context(
        self,
        pairing: ExternalAgentPairingRecord,
        request: GetActiveDesignContextV1,
    ) -> ActiveDesignContextResultV1: ...

    async def get_document_slice(
        self,
        pairing: ExternalAgentPairingRecord,
        request: GetDocumentSliceV1,
    ) -> DocumentSliceResultV1: ...

    async def validate_command_batch(
        self,
        pairing: ExternalAgentPairingRecord,
        request: ValidateExternalCommandBatchV1,
    ) -> ExternalCommandValidationResult: ...

    async def submit_command_proposal(
        self,
        pairing: ExternalAgentPairingRecord,
        request: SubmitExternalCommandProposalV1,
        request_hash: str,
        *,
        origin: Literal["external_agent"],
    ) -> ExternalProposalReceiptV1: ...

    async def get_proposal_status(
        self,
        pairing: ExternalAgentPairingRecord,
        request: GetExternalProposalStatusV1,
    ) -> ExternalProposalStatusResultV1: ...


class ExternalPrototypeAgentStore(Protocol):
    async def create_pairing(
        self,
        pairing: ExternalAgentPairingRecord,
        event: ExternalAgentAuditEvent,
    ) -> ExternalAgentPairingRecord: ...

    async def load_pairing_by_token_digest(
        self,
        token_digest: str,
    ) -> ExternalAgentPairingRecord | None: ...

    async def load_pairing(self, pairing_id: str) -> ExternalAgentPairingRecord | None: ...

    async def revoke_pairing(
        self,
        pairing: ExternalAgentPairingRecord,
        event: ExternalAgentAuditEvent,
    ) -> None: ...

    async def touch_pairing(self, pairing_id: str, used_at: datetime) -> None: ...

    async def claim_submission(
        self,
        submission: ExternalAgentSubmissionRecord,
    ) -> ExternalAgentSubmissionClaim: ...

    async def complete_submission(
        self,
        submission: ExternalAgentSubmissionRecord,
        event: ExternalAgentAuditEvent,
    ) -> None: ...

    async def fail_submission(
        self,
        submission: ExternalAgentSubmissionRecord,
        event: ExternalAgentAuditEvent,
    ) -> None: ...

    async def record_audit_event(self, event: ExternalAgentAuditEvent) -> None: ...

    async def list_audit_events(
        self,
        project_id: str,
        document_id: str,
        *,
        limit: int,
    ) -> list[ExternalAgentAuditEvent]: ...


class ExternalPrototypeAgentError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class UnavailableStructuredPrototypeCollaborationPort:
    @staticmethod
    def _unavailable() -> ExternalPrototypeAgentError:
        return ExternalPrototypeAgentError(
            "prototype_core_unavailable",
            "structured prototype collaboration core is unavailable",
            retryable=True,
        )

    async def assert_pairing_scope(self, project_id: str, document_id: str) -> None:
        del project_id, document_id
        raise self._unavailable()

    async def get_active_design_context(
        self,
        pairing: ExternalAgentPairingRecord,
        request: GetActiveDesignContextV1,
    ) -> ActiveDesignContextResultV1:
        del pairing, request
        raise self._unavailable()

    async def get_document_slice(
        self,
        pairing: ExternalAgentPairingRecord,
        request: GetDocumentSliceV1,
    ) -> DocumentSliceResultV1:
        del pairing, request
        raise self._unavailable()

    async def validate_command_batch(
        self,
        pairing: ExternalAgentPairingRecord,
        request: ValidateExternalCommandBatchV1,
    ) -> ExternalCommandValidationResult:
        del pairing, request
        raise self._unavailable()

    async def submit_command_proposal(
        self,
        pairing: ExternalAgentPairingRecord,
        request: SubmitExternalCommandProposalV1,
        request_hash: str,
        *,
        origin: Literal["external_agent"],
    ) -> ExternalProposalReceiptV1:
        del pairing, request, request_hash, origin
        raise self._unavailable()

    async def get_proposal_status(
        self,
        pairing: ExternalAgentPairingRecord,
        request: GetExternalProposalStatusV1,
    ) -> ExternalProposalStatusResultV1:
        del pairing, request
        raise self._unavailable()


class ExternalPrototypeAgentService:
    def __init__(
        self,
        *,
        store: ExternalPrototypeAgentStore,
        collaboration: StructuredPrototypeCollaborationPort,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._collaboration = collaboration
        self._clock = clock or (lambda: datetime.now(UTC))

    async def create_pairing(
        self,
        request: CreateExternalAgentPairingV1,
    ) -> IssuedExternalAgentPairing:
        self._validate_loopback_mcp_url(request.mcp_url)
        await self._collaboration.assert_pairing_scope(request.project_id, request.document_id)
        now = self._now()
        token = secrets.token_urlsafe(PAIRING_TOKEN_BYTES)
        pairing = ExternalAgentPairingRecord(
            id=f"external-agent-pairing-{uuid4().hex}",
            client_request_id=request.client_request_id,
            project_id=request.project_id,
            document_id=request.document_id,
            agent_kind=request.agent_kind,
            token_digest=self._token_digest(token),
            permissions=tuple(sorted(request.permissions)),
            status="active",
            protocol_version=EXTERNAL_AGENT_PROTOCOL_VERSION,
            skill_version=PROTOTYPE_DESIGNER_SKILL_VERSION,
            created_at=now,
            expires_at=now + timedelta(seconds=request.ttl_seconds),
            revoked_at=None,
            last_used_at=None,
        )
        event = self._event(
            pairing=pairing,
            event_kind="pairing_created",
            outcome="ok",
        )
        try:
            saved = await self._store.create_pairing(pairing, event)
        except ExternalPrototypeAgentError:
            raise
        if saved.id != pairing.id:
            raise ExternalPrototypeAgentError(
                "pairing_secret_unrecoverable",
                "pairing was already issued; create a new pairing to receive another secret",
            )
        return IssuedExternalAgentPairing(
            pairing=saved,
            bearer_token=token,
            mcp_url=request.mcp_url,
            skill_package_path=SKILL_PACKAGE_PATH,
            install_manifest=self._install_manifest(saved, request.mcp_url),
        )

    async def revoke_pairing(self, pairing_id: str) -> ExternalAgentPairingRecord:
        pairing = await self._store.load_pairing(pairing_id)
        if pairing is None:
            raise ExternalPrototypeAgentError("pairing_missing", "external Agent pairing not found")
        if pairing.status == "revoked":
            return pairing
        now = self._now()
        revoked = replace(pairing, status="revoked", revoked_at=now)
        await self._store.revoke_pairing(
            revoked,
            self._event(pairing=revoked, event_kind="pairing_revoked", outcome="ok"),
        )
        return revoked

    async def authorize_pairing(
        self,
        bearer_token: str,
        *,
        tool_id: str | None = None,
    ) -> ExternalAgentPairingRecord:
        if not bearer_token:
            raise ExternalPrototypeAgentError("pairing_token_missing", "pairing token is required")
        pairing = await self._store.load_pairing_by_token_digest(
            self._token_digest(bearer_token)
        )
        if pairing is None:
            raise ExternalPrototypeAgentError("pairing_token_invalid", "pairing token is invalid")
        now = self._now()
        if pairing.status != "active":
            raise ExternalPrototypeAgentError("pairing_revoked", "pairing has been revoked")
        if now >= pairing.expires_at:
            raise ExternalPrototypeAgentError("pairing_expired", "pairing has expired")
        if tool_id is not None:
            self._assert_tool_permission(pairing, tool_id)
        await self._store.touch_pairing(pairing.id, now)
        return replace(pairing, last_used_at=now)

    def tool_descriptors(self, pairing: ExternalAgentPairingRecord) -> list[JsonObject]:
        allowed = [tool_id for tool_id in sorted(ALL_TOOLS) if self._tool_allowed(pairing, tool_id)]
        return [self._tool_descriptor(tool_id) for tool_id in allowed]

    async def record_protocol_event(
        self,
        pairing: ExternalAgentPairingRecord,
        event_kind: str,
    ) -> None:
        await self._store.record_audit_event(
            self._event(pairing=pairing, event_kind=event_kind, outcome="ok")
        )

    async def list_audit_events(
        self,
        project_id: str,
        document_id: str,
        *,
        limit: int,
    ) -> list[ExternalAgentAuditEvent]:
        return await self._store.list_audit_events(
            project_id,
            document_id,
            limit=limit,
        )

    async def invoke_tool(
        self,
        pairing: ExternalAgentPairingRecord,
        tool_id: str,
        arguments: object,
    ) -> JsonObject:
        started = time.monotonic()
        request_hash: str | None = None
        try:
            self._assert_tool_permission(pairing, tool_id)
            if tool_id == "get_prototype_capabilities":
                self._parse_empty_arguments(arguments)
                result = self._capabilities(pairing)
            elif tool_id == "get_active_design_context":
                context_request = self._parse(GetActiveDesignContextV1, arguments)
                request_hash = canonical_request_hash(context_request)
                context_result = await self._collaboration.get_active_design_context(
                    pairing,
                    context_request,
                )
                self._assert_response_scope(pairing, context_result)
                result = canonical_model_payload(context_result)
            elif tool_id == "get_document_slice":
                slice_request = self._parse(GetDocumentSliceV1, arguments)
                request_hash = canonical_request_hash(slice_request)
                slice_result = await self._collaboration.get_document_slice(pairing, slice_request)
                self._assert_response_scope(pairing, slice_result)
                if slice_result.slice_kind != slice_request.slice_kind:
                    raise ExternalPrototypeAgentError(
                        "prototype_response_invalid",
                        "structured prototype core returned the wrong slice kind",
                    )
                result = canonical_model_payload(slice_result)
            elif tool_id == "validate_command_batch":
                validation_request = self._parse(ValidateExternalCommandBatchV1, arguments)
                request_hash = canonical_request_hash(validation_request)
                validation = await self._collaboration.validate_command_batch(
                    pairing,
                    validation_request,
                )
                result = {
                    "protocolVersion": EXTERNAL_AGENT_PROTOCOL_VERSION,
                    "valid": True,
                    "affectedEntityIds": list(validation.affected_entity_ids),
                    "validationHash": validation.validation_hash,
                }
            elif tool_id == "submit_command_proposal":
                submission_request = self._parse(SubmitExternalCommandProposalV1, arguments)
                request_hash = canonical_request_hash(submission_request)
                receipt = await self._submit(pairing, submission_request, request_hash)
                result = canonical_model_payload(receipt)
            elif tool_id == "get_proposal_status":
                status_request = self._parse(GetExternalProposalStatusV1, arguments)
                request_hash = canonical_request_hash(status_request)
                status_result = await self._collaboration.get_proposal_status(
                    pairing,
                    status_request,
                )
                self._assert_response_scope(pairing, status_result)
                if status_result.proposal_id != status_request.proposal_id:
                    raise ExternalPrototypeAgentError(
                        "prototype_response_invalid",
                        "structured prototype core returned the wrong proposal identity",
                    )
                result = canonical_model_payload(status_result)
            else:
                raise ExternalPrototypeAgentError(
                    "tool_not_allowed",
                    "external Agent MCP tool is not allowed",
                )
        except ExternalPrototypeAgentError as exc:
            await self._store.record_audit_event(
                self._event(
                    pairing=pairing,
                    event_kind="mcp_tool_call",
                    tool_id=tool_id,
                    request_hash=request_hash,
                    outcome="denied" if exc.code == "tool_not_allowed" else "error",
                    error_code=exc.code,
                    duration_ms=self._duration_ms(started),
                )
            )
            raise
        except Exception as exc:
            # The collaboration port is an integration boundary with separately deployed code.
            await self._store.record_audit_event(
                self._event(
                    pairing=pairing,
                    event_kind="mcp_tool_call",
                    tool_id=tool_id,
                    request_hash=request_hash,
                    outcome="error",
                    error_code="internal_error",
                    duration_ms=self._duration_ms(started),
                )
            )
            raise ExternalPrototypeAgentError(
                "internal_error",
                "external prototype Agent tool call failed",
                retryable=True,
            ) from exc
        await self._store.record_audit_event(
            self._event(
                pairing=pairing,
                event_kind="mcp_tool_call",
                tool_id=tool_id,
                request_hash=request_hash,
                outcome="ok",
                duration_ms=self._duration_ms(started),
            )
        )
        return result

    async def _submit(
        self,
        pairing: ExternalAgentPairingRecord,
        request: SubmitExternalCommandProposalV1,
        request_hash: str,
    ) -> ExternalProposalReceiptV1:
        validation = await self._collaboration.validate_command_batch(pairing, request)
        if tuple(sorted(request.affected_entity_ids)) != tuple(
            sorted(validation.affected_entity_ids)
        ):
            raise ExternalPrototypeAgentError(
                "affected_entities_mismatch",
                "declared affected entities do not match command validation",
            )
        now = self._now()
        pending = ExternalAgentSubmissionRecord(
            id=f"external-agent-submission-{uuid4().hex}",
            pairing_id=pairing.id,
            client_request_id=request.client_request_id,
            request_hash=request_hash,
            status="processing",
            proposal_id=None,
            receipt_json=None,
            error_code=None,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )
        claim = await self._store.claim_submission(pending)
        if not claim.created:
            return self._receipt_from_submission(claim.submission)
        try:
            receipt = await self._collaboration.submit_command_proposal(
                pairing,
                request,
                request_hash,
                origin="external_agent",
            )
            if receipt.request_hash != request_hash:
                raise ExternalPrototypeAgentError(
                    "proposal_receipt_invalid",
                    "structured prototype core returned a mismatched proposal receipt",
                )
            completed_at = self._now()
            completed = replace(
                pending,
                status="completed",
                proposal_id=receipt.proposal_id,
                receipt_json=json.dumps(
                    canonical_model_payload(receipt),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                updated_at=completed_at,
                completed_at=completed_at,
            )
            await self._store.complete_submission(
                completed,
                self._event(
                    pairing=pairing,
                    event_kind="proposal_submitted",
                    tool_id="submit_command_proposal",
                    request_hash=request_hash,
                    outcome="ok",
                ),
            )
            return receipt
        except ExternalPrototypeAgentError as exc:
            failed_at = self._now()
            failed = replace(
                pending,
                status="failed",
                error_code=exc.code,
                updated_at=failed_at,
                completed_at=failed_at,
            )
            await self._store.fail_submission(
                failed,
                self._event(
                    pairing=pairing,
                    event_kind="proposal_failed",
                    tool_id="submit_command_proposal",
                    request_hash=request_hash,
                    outcome="error",
                    error_code=exc.code,
                ),
            )
            raise
        except Exception as exc:
            # The collaboration port is an integration boundary with separately deployed code.
            failed_at = self._now()
            failed = replace(
                pending,
                status="failed",
                error_code="internal_error",
                updated_at=failed_at,
                completed_at=failed_at,
            )
            await self._store.fail_submission(
                failed,
                self._event(
                    pairing=pairing,
                    event_kind="proposal_failed",
                    tool_id="submit_command_proposal",
                    request_hash=request_hash,
                    outcome="error",
                    error_code="internal_error",
                ),
            )
            raise ExternalPrototypeAgentError(
                "internal_error",
                "structured prototype core failed while creating the proposal",
                retryable=True,
            ) from exc

    @staticmethod
    def _receipt_from_submission(
        submission: ExternalAgentSubmissionRecord,
    ) -> ExternalProposalReceiptV1:
        if submission.status == "processing":
            raise ExternalPrototypeAgentError(
                "submission_in_progress",
                "an identical proposal submission is still being processed",
                retryable=True,
            )
        if submission.status == "failed":
            raise ExternalPrototypeAgentError(
                submission.error_code or "submission_failed",
                "the previous identical proposal submission failed",
                retryable=True,
            )
        payload = parse_json_object(submission.receipt_json)
        if payload is None:
            raise ExternalPrototypeAgentError(
                "proposal_receipt_missing",
                "completed proposal submission has no receipt",
            )
        try:
            return ExternalProposalReceiptV1.model_validate(
                payload,
                strict=True,
                by_alias=True,
                by_name=False,
            )
        except ValidationError as exc:
            raise ExternalPrototypeAgentError(
                "proposal_receipt_invalid",
                "completed proposal submission has an invalid receipt",
            ) from exc

    @staticmethod
    def _parse(
        model_type: type[ExternalAgentModelT],
        arguments: object,
    ) -> ExternalAgentModelT:
        try:
            return model_type.model_validate(
                arguments,
                strict=True,
                by_alias=True,
                by_name=False,
            )
        except ValidationError as exc:
            raise ExternalPrototypeAgentError(
                "request_invalid",
                "external Agent MCP arguments are invalid",
            ) from exc

    @staticmethod
    def _parse_empty_arguments(arguments: object) -> None:
        if not isinstance(arguments, dict) or arguments:
            raise ExternalPrototypeAgentError(
                "request_invalid",
                "external Agent MCP arguments are invalid",
            )

    @staticmethod
    def _token_digest(token: str) -> str:
        return f"sha256:{hashlib.sha256(token.encode('utf-8')).hexdigest()}"

    @staticmethod
    def _validate_loopback_mcp_url(value: str) -> None:
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as exc:
            raise ExternalPrototypeAgentError("mcp_url_invalid", "MCP URL is invalid") from exc
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or port is None
            or parsed.path != MCP_PATH
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ExternalPrototypeAgentError(
                "mcp_url_invalid",
                "MCP URL must be an explicit loopback HTTP endpoint",
            )

    @staticmethod
    def _tool_allowed(pairing: ExternalAgentPairingRecord, tool_id: str) -> bool:
        if tool_id in READ_TOOLS:
            return "prototype:read" in pairing.permissions
        if tool_id in PROPOSE_TOOLS:
            return "prototype:propose" in pairing.permissions
        return False

    @classmethod
    def _assert_tool_permission(cls, pairing: ExternalAgentPairingRecord, tool_id: str) -> None:
        if tool_id not in ALL_TOOLS or not cls._tool_allowed(pairing, tool_id):
            raise ExternalPrototypeAgentError(
                "tool_not_allowed",
                "external Agent pairing does not permit this MCP tool",
            )

    @staticmethod
    def _capabilities(pairing: ExternalAgentPairingRecord) -> JsonObject:
        return {
            "protocolVersion": EXTERNAL_AGENT_PROTOCOL_VERSION,
            "skillVersion": PROTOTYPE_DESIGNER_SKILL_VERSION,
            "projectId": pairing.project_id,
            "documentId": pairing.document_id,
            "permissions": list(pairing.permissions),
            "requiresActiveContextBeforeProposal": True,
            "authority": {
                "canRead": "prototype:read" in pairing.permissions,
                "canPropose": "prototype:propose" in pairing.permissions,
                "canApply": False,
                "canPublish": False,
            },
        }

    @staticmethod
    def _assert_response_scope(
        pairing: ExternalAgentPairingRecord,
        response: ActiveDesignContextResultV1
        | DocumentSliceResultV1
        | ExternalProposalStatusResultV1,
    ) -> None:
        if response.project_id != pairing.project_id or response.document_id != pairing.document_id:
            raise ExternalPrototypeAgentError(
                "prototype_response_scope_mismatch",
                "structured prototype core returned data outside the paired scope",
            )

    @staticmethod
    def _tool_descriptor(tool_id: str) -> JsonObject:
        descriptions = {
            "get_prototype_capabilities": "Read the pairing scope and authority limits.",
            "get_active_design_context": "Read the bounded active page and selection context.",
            "get_document_slice": "Read a bounded pages, selection, tokens, or runtime-flow slice.",
            "validate_command_batch": "Validate a proposal without changing the active draft.",
            "submit_command_proposal": "Submit one human-reviewable command proposal.",
            "get_proposal_status": "Read the persisted proposal review state.",
        }
        model_type = TOOL_INPUT_MODELS[tool_id]
        input_schema: JsonObject
        if model_type is None:
            input_schema = {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            }
        else:
            input_schema = cast(
                JsonObject,
                model_type.model_json_schema(by_alias=True, mode="validation"),
            )
        return {
            "name": tool_id,
            "description": descriptions[tool_id],
            "inputSchema": input_schema,
        }

    @staticmethod
    def _install_manifest(
        pairing: ExternalAgentPairingRecord,
        mcp_url: str,
    ) -> JsonObject:
        if pairing.agent_kind == "claude_code":
            command = (
                "claude mcp add --scope local --transport http "
                f'{MCP_SERVER_ID} "{mcp_url}" '
                '--header "Authorization: Bearer $PROTOTYPE_AGENT_TOKEN"'
            )
            skill_target = "~/.claude/skills/prototype-designer"
        else:
            command = (
                f'codex mcp add {MCP_SERVER_ID} --url "{mcp_url}" '
                "--bearer-token-env-var PROTOTYPE_AGENT_TOKEN"
            )
            skill_target = "${CODEX_HOME:-$HOME/.codex}/skills/prototype-designer"
        return {
            "manifestVersion": 1,
            "agentKind": pairing.agent_kind,
            "pairingId": pairing.id,
            "skill": {
                "version": pairing.skill_version,
                "source": SKILL_PACKAGE_PATH,
                "target": skill_target,
            },
            "mcp": {
                "serverId": MCP_SERVER_ID,
                "url": mcp_url,
                "tokenEnvironmentVariable": "PROTOTYPE_AGENT_TOKEN",
                "installCommand": command,
            },
        }

    def _event(
        self,
        *,
        pairing: ExternalAgentPairingRecord,
        event_kind: str,
        outcome: ExternalAgentAuditOutcome,
        tool_id: str | None = None,
        request_hash: str | None = None,
        error_code: str | None = None,
        duration_ms: int | None = None,
    ) -> ExternalAgentAuditEvent:
        return ExternalAgentAuditEvent(
            id=f"external-agent-audit-{uuid4().hex}",
            pairing_id=pairing.id,
            project_id=pairing.project_id,
            document_id=pairing.document_id,
            event_kind=event_kind,
            tool_id=tool_id,
            request_hash=request_hash,
            outcome=outcome,
            error_code=error_code,
            duration_ms=duration_ms,
            occurred_at=self._now(),
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.utcoffset() is None:
            raise ExternalPrototypeAgentError(
                "clock_invalid",
                "external Agent clock must return a timezone-aware datetime",
            )
        return value

    @staticmethod
    def _duration_ms(started: float) -> int:
        return max(0, int((time.monotonic() - started) * 1000))
