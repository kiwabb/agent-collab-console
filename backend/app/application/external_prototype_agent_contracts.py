from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.json_safety import JsonObject

EXTERNAL_AGENT_PROTOCOL_VERSION = 1
PROTOTYPE_DESIGNER_SKILL_VERSION = "1.0.0"
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def _camel_alias(field_name: str) -> str:
    head, *tail = field_name.split("_")
    return head + "".join(part.capitalize() for part in tail)


class StrictExternalAgentModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel_alias,
        extra="forbid",
        populate_by_name=False,
        serialize_by_alias=True,
        strict=True,
        str_strip_whitespace=False,
    )


class ExternalAgentContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CreateExternalAgentPairingV1(StrictExternalAgentModel):
    protocol_version: Literal[1]
    client_request_id: Annotated[str, Field(min_length=36, max_length=36)]
    project_id: Annotated[str, Field(min_length=1, max_length=128)]
    document_id: Annotated[str, Field(min_length=1, max_length=128)]
    agent_kind: Literal["claude_code", "codex"]
    permissions: list[Literal["prototype:read", "prototype:propose"]]
    ttl_seconds: Annotated[int, Field(ge=60, le=3600)]
    mcp_url: Annotated[str, Field(min_length=1, max_length=2_048)]

    @field_validator("client_request_id")
    @classmethod
    def validate_client_request_id(cls, value: str) -> str:
        return canonical_uuid(value)

    @field_validator("permissions")
    @classmethod
    def validate_permissions(
        cls,
        permissions: list[Literal["prototype:read", "prototype:propose"]],
    ) -> list[Literal["prototype:read", "prototype:propose"]]:
        if not permissions or len(permissions) != len(set(permissions)):
            raise ValueError("pairing permissions must be non-empty and unique")
        return permissions


class ExternalAgentScopeV1(StrictExternalAgentModel):
    page_id: Annotated[str, Field(min_length=1, max_length=128)] | None
    selected_node_ids: Annotated[list[str], Field(max_length=100)]
    flow_id: Annotated[str, Field(min_length=1, max_length=128)] | None
    viewport: Literal["desktop", "tablet", "mobile"]

    @field_validator("selected_node_ids")
    @classmethod
    def validate_node_ids(cls, node_ids: list[str]) -> list[str]:
        if len(node_ids) != len(set(node_ids)) or any(not value for value in node_ids):
            raise ValueError("selected node IDs must be non-empty and unique")
        return node_ids


class GetActiveDesignContextV1(StrictExternalAgentModel):
    protocol_version: Literal[1]
    scope: ExternalAgentScopeV1


class GetDocumentSliceV1(StrictExternalAgentModel):
    protocol_version: Literal[1]
    slice_kind: Literal["pages", "selection", "tokens", "runtime_flow"]
    page_id: Annotated[str, Field(min_length=1, max_length=128)] | None
    entity_ids: Annotated[list[str], Field(max_length=200)]

    @field_validator("entity_ids")
    @classmethod
    def validate_entity_ids(cls, entity_ids: list[str]) -> list[str]:
        if len(entity_ids) != len(set(entity_ids)) or any(not value for value in entity_ids):
            raise ValueError("document slice entity IDs must be non-empty and unique")
        return entity_ids


class ExternalCommandBatchV1(StrictExternalAgentModel):
    command_contract_version: Annotated[int, Field(ge=1)]
    summary: Annotated[str, Field(min_length=1, max_length=240)]
    commands: Annotated[list[JsonObject], Field(min_length=1, max_length=100)]

    @field_validator("commands")
    @classmethod
    def validate_commands(cls, commands: list[JsonObject]) -> list[JsonObject]:
        for command in commands:
            kind = command.get("kind")
            if not isinstance(kind, str) or not kind or len(kind) > 80:
                raise ValueError("every external command must declare a bounded kind")
        return commands


class ValidateExternalCommandBatchV1(StrictExternalAgentModel):
    protocol_version: Literal[1]
    draft_id: Annotated[str, Field(min_length=1, max_length=128)]
    expected_head_sequence_no: Annotated[int, Field(ge=0)]
    expected_document_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    batch: ExternalCommandBatchV1


class SubmitExternalCommandProposalV1(ValidateExternalCommandBatchV1):
    client_request_id: Annotated[str, Field(min_length=36, max_length=36)]
    message: Annotated[str, Field(min_length=1, max_length=8_000)]
    affected_entity_ids: Annotated[list[str], Field(min_length=1, max_length=500)]

    @field_validator("client_request_id")
    @classmethod
    def validate_client_request_id(cls, value: str) -> str:
        return canonical_uuid(value)

    @field_validator("affected_entity_ids")
    @classmethod
    def validate_affected_ids(cls, entity_ids: list[str]) -> list[str]:
        if len(entity_ids) != len(set(entity_ids)) or any(not value for value in entity_ids):
            raise ValueError("affected entity IDs must be non-empty and unique")
        return entity_ids


class GetExternalProposalStatusV1(StrictExternalAgentModel):
    protocol_version: Literal[1]
    proposal_id: Annotated[str, Field(min_length=1, max_length=128)]


class ExternalPrototypeRevisionV1(StrictExternalAgentModel):
    draft_id: Annotated[str, Field(min_length=1, max_length=128)]
    head_sequence_no: Annotated[int, Field(ge=0)]
    document_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    command_contract_version: Annotated[int, Field(ge=1)]


class ActiveDesignContextResultV1(StrictExternalAgentModel):
    protocol_version: Literal[1]
    project_id: Annotated[str, Field(min_length=1, max_length=128)]
    document_id: Annotated[str, Field(min_length=1, max_length=128)]
    revision: ExternalPrototypeRevisionV1
    supported_command_kinds: Annotated[list[str], Field(min_length=1, max_length=100)]
    context: JsonObject
    truncated: bool

    @field_validator("supported_command_kinds")
    @classmethod
    def validate_supported_command_kinds(cls, command_kinds: list[str]) -> list[str]:
        if len(command_kinds) != len(set(command_kinds)) or any(
            not value or len(value) > 80 for value in command_kinds
        ):
            raise ValueError("supported command kinds must be bounded and unique")
        return command_kinds

    @field_validator("context")
    @classmethod
    def validate_context_size(cls, context: JsonObject) -> JsonObject:
        return bounded_json_object(context, max_bytes=262_144)


class DocumentSliceResultV1(StrictExternalAgentModel):
    protocol_version: Literal[1]
    project_id: Annotated[str, Field(min_length=1, max_length=128)]
    document_id: Annotated[str, Field(min_length=1, max_length=128)]
    revision: ExternalPrototypeRevisionV1
    slice_kind: Literal["pages", "selection", "tokens", "runtime_flow"]
    data: JsonObject
    truncated: bool

    @field_validator("data")
    @classmethod
    def validate_data_size(cls, data: JsonObject) -> JsonObject:
        return bounded_json_object(data, max_bytes=524_288)


class ExternalProposalStatusResultV1(StrictExternalAgentModel):
    protocol_version: Literal[1]
    project_id: Annotated[str, Field(min_length=1, max_length=128)]
    document_id: Annotated[str, Field(min_length=1, max_length=128)]
    proposal_id: Annotated[str, Field(min_length=1, max_length=128)]
    status: Literal["preview_pending", "preview_ready", "applied", "rejected", "stale", "failed"]
    current_revision: ExternalPrototypeRevisionV1
    updated_at: str

    @field_validator("updated_at")
    @classmethod
    def validate_updated_at(cls, value: str) -> str:
        return timezone_aware_iso8601(value)


class ExternalProposalReceiptV1(StrictExternalAgentModel):
    protocol_version: Literal[1]
    proposal_id: str
    status: Literal["preview_pending", "preview_ready", "applied", "rejected", "stale", "failed"]
    request_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    submitted_at: str

    @field_validator("submitted_at")
    @classmethod
    def validate_submitted_at(cls, value: str) -> str:
        return timezone_aware_iso8601(value)


def parse_external_agent_model[ModelT: StrictExternalAgentModel](
    model_type: type[ModelT],
    value: object,
) -> ModelT:
    try:
        return model_type.model_validate(value, strict=True, by_alias=True, by_name=False)
    except ValidationError as exc:
        raise ExternalAgentContractError(
            "request_invalid",
            "external prototype Agent request does not satisfy protocol version 1",
        ) from exc


def canonical_uuid(value: str) -> str:
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError("request identity must be a UUID") from exc
    if str(parsed) != value:
        raise ValueError("request identity must use canonical lowercase UUID form")
    return value


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def bounded_json_object(value: JsonObject, *, max_bytes: int) -> JsonObject:
    try:
        encoded = canonical_json_bytes(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("value must contain finite JSON data") from exc
    if len(encoded) > max_bytes:
        raise ValueError("JSON object exceeds the bounded MCP response size")
    return value


def timezone_aware_iso8601(value: str) -> str:
    from datetime import datetime

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("timestamp must use ISO 8601") from exc
    if parsed.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value


def canonical_model_payload(model: StrictExternalAgentModel) -> JsonObject:
    return model.model_dump(mode="json", by_alias=True)


def canonical_request_hash(model: StrictExternalAgentModel) -> str:
    digest = hashlib.sha256(canonical_json_bytes(canonical_model_payload(model))).hexdigest()
    return f"sha256:{digest}"
