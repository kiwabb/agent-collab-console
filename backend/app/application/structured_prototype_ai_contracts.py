from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, ValidationError, model_validator

from app.adapters.prototype_object_store import canonical_json_bytes
from app.application.structured_prototype_contracts import (
    DomainCommandBatchV1,
    StrictPrototypeModel,
    StructuredPrototypeContractError,
)

AI_ASSISTANT_OUTCOME_CONTRACT_VERSION = 1
AI_EDIT_CONTEXT_CONTRACT_VERSION = 1


class PrototypeAiSelectionV1(StrictPrototypeModel):
    scope: Literal["selection", "page", "document", "flow"]
    page_id: Annotated[str, Field(min_length=1, max_length=128)] | None
    selected_node_ids: Annotated[list[str], Field(max_length=100)]
    flow_id: Annotated[str, Field(min_length=1, max_length=128)] | None
    viewport: Literal["desktop", "tablet", "mobile"]


class PrototypeAssistantAnswerV1(StrictPrototypeModel):
    contract_version: Literal[1]
    kind: Literal["answer"]
    message: Annotated[str, Field(min_length=1, max_length=8_000)]


class PrototypeAssistantClarificationV1(StrictPrototypeModel):
    contract_version: Literal[1]
    kind: Literal["clarification"]
    message: Annotated[str, Field(min_length=1, max_length=2_000)]
    questions: Annotated[list[str], Field(min_length=1, max_length=3)]

    @model_validator(mode="after")
    def validate_questions(self) -> PrototypeAssistantClarificationV1:
        if any(not question or len(question) > 500 for question in self.questions):
            raise ValueError("clarification questions must be non-empty and at most 500 chars")
        return self


class PrototypeAssistantCommandProposalV1(StrictPrototypeModel):
    contract_version: Literal[1]
    kind: Literal["commandProposal"]
    message: Annotated[str, Field(min_length=1, max_length=8_000)]
    summary: Annotated[str, Field(min_length=1, max_length=240)]
    batch: DomainCommandBatchV1
    affected_entity_ids: Annotated[list[str], Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def validate_proposal(self) -> PrototypeAssistantCommandProposalV1:
        if self.batch.summary != self.summary:
            raise ValueError("proposal summary must match the command batch summary")
        if len(self.affected_entity_ids) != len(set(self.affected_entity_ids)):
            raise ValueError("proposal affected entity IDs must be unique")
        return self

    def command_batch(self) -> DomainCommandBatchV1:
        return self.batch


type PrototypeAssistantOutcomeV1 = Annotated[
    PrototypeAssistantAnswerV1
    | PrototypeAssistantClarificationV1
    | PrototypeAssistantCommandProposalV1,
    Field(discriminator="kind"),
]


class PrototypeAssistantOutcomeEnvelopeV1(StrictPrototypeModel):
    outcome: PrototypeAssistantOutcomeV1


def parse_prototype_assistant_outcome(value: object) -> PrototypeAssistantOutcomeV1:
    try:
        return PrototypeAssistantOutcomeEnvelopeV1.model_validate(
            {"outcome": value},
            strict=True,
            by_alias=True,
            by_name=False,
        ).outcome
    except ValidationError as exc:
        raise StructuredPrototypeContractError(
            "schema_invalid",
            "prototype assistant outcome does not satisfy contract version 1",
        ) from exc


def assistant_outcome_payload(outcome: PrototypeAssistantOutcomeV1) -> dict[str, object]:
    return outcome.model_dump(mode="json", by_alias=True)


def canonical_assistant_outcome_json(outcome: PrototypeAssistantOutcomeV1) -> str:
    return canonical_json_bytes(assistant_outcome_payload(outcome)).decode("utf-8")
