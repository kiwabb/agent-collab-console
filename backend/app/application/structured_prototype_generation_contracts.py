from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from app.application.structured_prototype_contracts import StructuredPrototypeContractError

GENERATION_CONTRACT_VERSION = 1
GENERATION_BLUEPRINT_CONTRACT_VERSION = 1
GENERATION_FOUNDATION_CONTRACT_VERSION = 1
GENERATION_PAGE_CONTRACT_VERSION = 1
GENERATION_MAX_ARTIFACT_BYTES = 512 * 1024

GenerationTaskKind = Literal[
    "generation_blueprint",
    "generation_foundation",
    "generation_page",
]
GenerationComponentType = Literal["Stack", "Form", "Text", "Input", "Button", "Table"]
REQUIRED_GENERATION_COMPONENT_TYPES = frozenset(
    {"Stack", "Form", "Text", "Input", "Button", "Table"}
)
TECHNICAL_KEY_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


def _camel_alias(field_name: str) -> str:
    head, *tail = field_name.split("_")
    return head + "".join(part.capitalize() for part in tail)


class StrictGenerationModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel_alias,
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
        strict=True,
        frozen=True,
    )


TechnicalKey = Annotated[str, Field(pattern=TECHNICAL_KEY_RE.pattern)]


def _require_unique(values: Iterable[str], label: str) -> set[str]:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}: {value}")
        seen.add(value)
    return seen


class GenerationFoundationIntentV1(StrictGenerationModel):
    visual_language: Annotated[str, Field(min_length=1, max_length=160)]
    density: Literal["compact", "comfortable"]
    responsive_strategy: Annotated[str, Field(min_length=1, max_length=200)]


class GenerationBlueprintPageV1(StrictGenerationModel):
    page_key: TechnicalKey
    title: Annotated[str, Field(min_length=1, max_length=120)]
    route: Annotated[str, Field(pattern=r"^/[a-z0-9/-]*$", max_length=160)]
    purpose: Annotated[str, Field(min_length=1, max_length=300)]
    navigation_group_key: TechnicalKey


class GenerationBlueprintNavigationItemV1(StrictGenerationModel):
    key: TechnicalKey
    label: Annotated[str, Field(min_length=1, max_length=80)]
    target_page_key: TechnicalKey


class GenerationBlueprintFlowIntentV1(StrictGenerationModel):
    key: TechnicalKey
    source_page_key: TechnicalKey
    source_node_key: TechnicalKey
    event: Literal["click", "submit", "rowActivated"]
    target_page_key: TechnicalKey


class GenerationBlueprintV1(StrictGenerationModel):
    contract_version: Literal[1]
    document_title: Annotated[str, Field(min_length=1, max_length=120)]
    product_intent: Annotated[str, Field(min_length=1, max_length=500)]
    output_locale: Literal["zh-CN"]
    foundation_intent: GenerationFoundationIntentV1
    pages: Annotated[list[GenerationBlueprintPageV1], Field(min_length=1, max_length=20)]
    navigation: Annotated[
        list[GenerationBlueprintNavigationItemV1], Field(min_length=1, max_length=30)
    ]
    flow_intents: Annotated[
        list[GenerationBlueprintFlowIntentV1], Field(min_length=1, max_length=30)
    ]
    role_intents: Annotated[list[TechnicalKey], Field(min_length=1, max_length=20)]
    entity_intents: Annotated[list[TechnicalKey], Field(min_length=1, max_length=30)]
    form_intents: Annotated[list[TechnicalKey], Field(min_length=1, max_length=50)]
    scenario_intents: Annotated[list[TechnicalKey], Field(min_length=1, max_length=30)]
    start_page_keys: Annotated[list[TechnicalKey], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def validate_references(self) -> GenerationBlueprintV1:
        available = _require_unique((page.page_key for page in self.pages), "page key")
        _require_unique((page.route for page in self.pages), "page route")
        _require_unique((item.key for item in self.navigation), "navigation key")
        _require_unique((flow.key for flow in self.flow_intents), "flow key")
        _require_unique(self.role_intents, "role intent")
        _require_unique(self.entity_intents, "entity intent")
        _require_unique(self.form_intents, "form intent")
        _require_unique(self.scenario_intents, "scenario intent")
        _require_unique(self.start_page_keys, "start page key")
        if not set(self.start_page_keys).issubset(available):
            raise ValueError("blueprint start pages must exist")
        if any(item.target_page_key not in available for item in self.navigation):
            raise ValueError("blueprint navigation target must exist")
        if any(
            flow.source_page_key not in available or flow.target_page_key not in available
            for flow in self.flow_intents
        ):
            raise ValueError("blueprint flow page must exist")
        return self


class GenerationDesignTokenV1(StrictGenerationModel):
    key: TechnicalKey
    value: Annotated[str, Field(min_length=1, max_length=80)]


class GenerationFoundationV1(StrictGenerationModel):
    contract_version: Literal[1]
    colors: Annotated[list[GenerationDesignTokenV1], Field(min_length=2, max_length=20)]
    spacing: Annotated[list[GenerationDesignTokenV1], Field(min_length=1, max_length=20)]
    component_types: Annotated[list[GenerationComponentType], Field(min_length=6, max_length=6)]
    shared_shell_title: Annotated[str, Field(min_length=1, max_length=80)]
    content_conventions: Annotated[str, Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def validate_foundation(self) -> GenerationFoundationV1:
        _require_unique((token.key for token in self.colors), "color token key")
        _require_unique((token.key for token in self.spacing), "spacing token key")
        component_types = _require_unique(self.component_types, "component type")
        if component_types != REQUIRED_GENERATION_COMPONENT_TYPES:
            raise ValueError("foundation must declare exactly the six MVP component types")
        return self


class GeneratedNodeCommonV1(StrictGenerationModel):
    local_key: TechnicalKey
    name: Annotated[str, Field(min_length=1, max_length=100)]
    visibility: Literal["visible", "hidden"] = "visible"


class GeneratedStackNodeV1(GeneratedNodeCommonV1):
    type: Literal["Stack"]
    direction: Literal["row", "column"]
    gap: Annotated[int, Field(ge=0, le=48)]
    padding: Annotated[int, Field(ge=0, le=64)]
    children: Annotated[list[GeneratedNodeV1], Field(max_length=12)]


class GeneratedFormNodeV1(GeneratedNodeCommonV1):
    type: Literal["Form"]
    form_key: TechnicalKey
    gap: Annotated[int, Field(ge=0, le=48)]
    children: Annotated[list[GeneratedNodeV1], Field(max_length=12)]


class GeneratedTextNodeV1(GeneratedNodeCommonV1):
    type: Literal["Text"]
    content: Annotated[str, Field(min_length=1, max_length=240)]
    semantic: Literal["heading", "body", "label"]
    tone: Literal["default", "muted", "success", "warning", "danger"]


class GeneratedInputNodeV1(GeneratedNodeCommonV1):
    type: Literal["Input"]
    label: Annotated[str, Field(min_length=1, max_length=120)]
    placeholder: Annotated[str, Field(max_length=240)]
    input_type: Literal["text", "number", "email"]
    required: bool
    disabled: bool = False


class GeneratedButtonNodeV1(GeneratedNodeCommonV1):
    type: Literal["Button"]
    label: Annotated[str, Field(min_length=1, max_length=120)]
    variant: Literal["primary", "secondary", "danger", "ghost"]
    disabled: bool = False


class GeneratedTableColumnV1(StrictGenerationModel):
    key: TechnicalKey
    label: Annotated[str, Field(min_length=1, max_length=100)]


class GeneratedTableNodeV1(GeneratedNodeCommonV1):
    type: Literal["Table"]
    columns: Annotated[list[GeneratedTableColumnV1], Field(min_length=1, max_length=20)]
    density: Literal["compact", "comfortable"]


GeneratedNodeV1 = Annotated[
    GeneratedStackNodeV1
    | GeneratedFormNodeV1
    | GeneratedTextNodeV1
    | GeneratedInputNodeV1
    | GeneratedButtonNodeV1
    | GeneratedTableNodeV1,
    Field(discriminator="type"),
]


class GeneratedPageV1(StrictGenerationModel):
    contract_version: Literal[1]
    page_key: TechnicalKey
    title: Annotated[str, Field(min_length=1, max_length=120)]
    route: Annotated[str, Field(pattern=r"^/[a-z0-9/-]*$", max_length=160)]
    root: GeneratedStackNodeV1

    @model_validator(mode="after")
    def validate_local_keys(self) -> GeneratedPageV1:
        _collect_local_keys(self.root, set())
        return self


def _collect_local_keys(node: GeneratedNodeV1, seen: set[str]) -> None:
    if node.local_key in seen:
        raise ValueError(f"duplicate page node local key: {node.local_key}")
    seen.add(node.local_key)
    if isinstance(node, (GeneratedStackNodeV1, GeneratedFormNodeV1)):
        for child in node.children:
            _collect_local_keys(child, seen)


class GenerationBlueprintEnvelopeV1(StrictGenerationModel):
    generation_contract_version: Literal[1]
    job_id: Annotated[str, Field(min_length=1, max_length=128)]
    run_id: Annotated[str, Field(min_length=1, max_length=128)]
    item_id: Annotated[str, Field(min_length=1, max_length=128)]
    task_kind: Literal["generation_blueprint"]
    context_object_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    payload: GenerationBlueprintV1


class GenerationFoundationEnvelopeV1(StrictGenerationModel):
    generation_contract_version: Literal[1]
    job_id: Annotated[str, Field(min_length=1, max_length=128)]
    run_id: Annotated[str, Field(min_length=1, max_length=128)]
    item_id: Annotated[str, Field(min_length=1, max_length=128)]
    task_kind: Literal["generation_foundation"]
    context_object_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    payload: GenerationFoundationV1


class GenerationPageEnvelopeV1(StrictGenerationModel):
    generation_contract_version: Literal[1]
    job_id: Annotated[str, Field(min_length=1, max_length=128)]
    run_id: Annotated[str, Field(min_length=1, max_length=128)]
    item_id: Annotated[str, Field(min_length=1, max_length=128)]
    task_kind: Literal["generation_page"]
    context_object_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    payload: GeneratedPageV1


GenerationArtifactEnvelopeV1 = (
    GenerationBlueprintEnvelopeV1 | GenerationFoundationEnvelopeV1 | GenerationPageEnvelopeV1
)

_ENVELOPE_ADAPTERS: dict[GenerationTaskKind, TypeAdapter[GenerationArtifactEnvelopeV1]] = {
    "generation_blueprint": TypeAdapter(GenerationBlueprintEnvelopeV1),
    "generation_foundation": TypeAdapter(GenerationFoundationEnvelopeV1),
    "generation_page": TypeAdapter(GenerationPageEnvelopeV1),
}


def parse_generation_artifact(
    task_kind: GenerationTaskKind,
    raw: bytes,
) -> GenerationArtifactEnvelopeV1:
    if len(raw) > GENERATION_MAX_ARTIFACT_BYTES:
        raise StructuredPrototypeContractError(
            "limit_exceeded", "structured prototype generation artifact exceeds 512 KiB"
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StructuredPrototypeContractError(
            "schema_invalid", "structured prototype generation artifact is not strict UTF-8 JSON"
        ) from exc
    try:
        return _ENVELOPE_ADAPTERS[task_kind].validate_python(
            payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )
    except ValueError as exc:
        raise StructuredPrototypeContractError(
            "schema_invalid", "structured prototype generation artifact is invalid"
        ) from exc


def generation_artifact_payload(envelope: GenerationArtifactEnvelopeV1) -> dict[str, object]:
    return cast(dict[str, object], envelope.model_dump(mode="json", by_alias=True))
